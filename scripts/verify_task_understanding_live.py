"""Small, multi-purpose acceptance set. Every answer uses the configured real API."""
import argparse
import json
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from standard_knowledge_service_v2.bootstrap import build_application
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.application.simulation_access import simulation_runtime

F, M, P, I = 'SIM-IEC-FAN-01', 'SIM-MB-FAN-01', 'SIM-IEC-PUMP-01', 'SIM-MB-INVERTER-01'
CASES = [
    dict(id='A', query=f'{I}昨天记录有功600kW，当前实测有功0.25MW；告诉我当前有功，再生成把它调整到120千瓦的指令。',
         ops=[(I, 'adjust_active_power')], facts=[(I, 'active_power_kw', 250)], target=120, queries=1),
    dict(id='B', query='查一下主变1和其冷却风机的当前状态，再生成启动该风机的指令，主变本体不操作。',
         ops=[(F, 'start')], queries=2),
    dict(id='C', query='主变1和主变2各自的冷却风机当前都没有故障，分别生成启动指令；不要启动模拟冷却油泵1，并告诉我该油泵当前运行状态。',
         ops=[(F, 'start'), (M, 'start')], facts=[(F, 'device_fault', 0), (M, 'device_fault', 0)], queries=1),
    dict(id='D', query='模拟冷却风机1当前device_fault=0；仅在它的power_available=1时才启动它，并告诉我它当前的running。',
         ops=[(F, 'start')], facts=[(F, 'device_fault', 0)], queries=1, conditional=True),
    dict(id='E', query='告诉我模拟冷却风机1当前运行状态，同时请启动模拟冷却风机99。',
         blocked=True, queries=1, unchanged=True),
    dict(id='F', query=f'{I}当前实测有功0.25MW，请将有功设为120kW。',
         blocked=True, unchanged=True, extra={'action_parameters': {'power_kw': 130}}),
    dict(id='G', query='请生成启动另一台冷却风机的指令，并告诉我它当前的故障标志。',
         history=[{'role': 'user', 'content': '我刚才查看的是主变1和模拟冷却风机1的当前状态。'}],
         ops=[(M, 'start')], queries=1),
    dict(id='H', query='模拟冷却风机1目前有故障；只分析它能否启动，并告诉我当前故障标志，不要生成操作指令。',
         readonly=True, facts=[(F, 'device_fault', 1)], queries=2),
    dict(id='I', query=f'{I}昨天记录有功600kW，当前实测有功−0.25兆瓦；查询当前有功，再生成将它设为0.12MW的指令。',
         ops=[(I, 'adjust_active_power')], facts=[(I, 'active_power_kw', -250)], target=120, queries=1),
    dict(id='J', query='模拟冷却风机1目前没有故障，它在运行吗？不要停它，帮我开起来，同时查一下主变1的当前运行状态。',
         ops=[(F, 'start')], facts=[(F, 'device_fault', 0)], queries=2),
    dict(id='K', query='主变一号的冷却风机当前没有故障，给我启动它的指令，并查它当前的故障标志。',
         ops=[(F, 'start')], facts=[(F, 'device_fault', 0)], queries=1),
]
QUERY_EXPECTATIONS = {
    'A': [(I, 'device_status', ['active_power_kw'])],
    'B': [('SIM-TRANSFORMER-01', 'device_status', []), (F, 'device_status', [])],
    'C': [(P, 'device_status', ['running'])], 'D': [(F, 'device_status', ['running'])],
    'E': [(F, 'device_status', ['running'])], 'G': [(M, 'device_status', ['device_fault'])],
    'H': [(F, 'device_status', ['device_fault']), (F, 'device_readiness', [])],
    'I': [(I, 'device_status', ['active_power_kw'])],
    'J': [(F, 'device_status', ['running']), ('SIM-TRANSFORMER-01', 'device_status', [])],
    'K': [(F, 'device_status', ['device_fault'])],
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--cases', default='A,C,F,G,H,I')
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_load((ROOT / 'configs/settings.example.yaml').read_text(encoding='utf-8'))
    config['llm_decomposition']['timeout_seconds'] = 60
    config['audit']['store'] = str(out / 'audit.jsonl')
    config['knowledge']['build_summary'] = str(out / 'graph.json')
    config['knowledge']['sync_state_path'] = str(out / 'graph-state.json')
    path = out / 'settings.yaml'
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding='utf-8')
    app = build_application(path).facade
    runtime = simulation_runtime(app)
    active, calls = '', []
    complete = app.decomposer.complete

    def traced(system, user):
        start = time.monotonic()
        record = {'case': active, 'model': app.decomposer.config.model,
                  'thinking_mode': app.decomposer.config.thinking_mode}
        try:
            raw = complete(system, user)
            record['completed'] = True
        except Exception as exc:
            record.update(completed=False, error_type=type(exc).__name__)
            raise
        finally:
            record['seconds'] = round(time.monotonic() - start, 2)
            calls.append(record)
        with (out / 'model.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'case': active, 'system': system, 'user': user, 'raw': raw}, ensure_ascii=False) + '\n')
        return raw

    app.decomposer.complete = traced
    results = []
    for case in CASES:
        if case['id'] not in args.cases.split(','):
            continue
        active = case['id']
        snap = runtime.create_session('all_devices')
        response = app.analyze(AnalysisRequest(case['query'], parameters={
            'simulation_mode': True, 'simulation_session_id': snap['session_id'], **case.get('extra', {})},
            conversation_context=case.get('history', []))).to_dict()
        after = runtime.snapshot(snap['session_id'])
        data = response['data']
        plan = data.get('decomposition', {})
        failures = []
        if plan.get('source') != 'model_api' or not plan.get('valid'):
            failures.append('真实模型理解未完成')
        if case.get('readonly'):
            if response['status'] != 'answered' or plan.get('operations'):
                failures.append('只读诊断未正常回答或生成了操作')
        elif case.get('blocked'):
            if response['status'] == 'generated':
                failures.append('应阻断的操作生成了指令')
        else:
            if response['status'] != 'generated':
                failures.append('未生成预期指令')
            actual = [(row['device_id'], row['action']) for row in plan.get('operations') or []]
            if sorted(actual) != sorted(case['ops']):
                failures.append('设备或动作错误/遗漏')
            if plan.get('actions') != list(dict.fromkeys(action for _, action in actual)):
                failures.append('摘要未由任务统一生成')
            if plan.get('scenario', {}).get('query_kind') != 'operation':
                failures.append('处理类型与操作清单不一致')
            if case.get('target') is not None:
                operations = plan.get('operations') or []
                if not operations or operations[0]['parameters'].get('power_kw') != case['target']:
                    failures.append('目标值与当前值/历史值混淆')
                payload = data.get('simulation_preview', {}).get('candidate', {}).get('payload', {})
                if payload.get('engineering_value') != case['target']:
                    failures.append('最终指令目标值错误')
            if case.get('conditional') and not any(row.get('conditions') for row in plan.get('operations') or []):
                failures.append('遗漏用户执行前提')
        if len(data.get('query_results', [])) < case.get('queries', 0):
            failures.append('遗漏独立查询')
        for device_id, kind, fields in QUERY_EXPECTATIONS.get(case['id'], []):
            matching = [row for row in data.get('query_results', []) if row.get('query_kind') == kind
                        and any(device.get('device_id') == device_id for device in row.get('devices', []))
                        and set(fields) <= set(row.get('requested_fields') or [])]
            if not matching:
                failures.append('查询设备、类型或字段未正确返回：' + device_id + '/' + kind)
        previews = ([data['simulation_preview']] if data.get('simulation_preview') else
                    [row['preview'] for row in data.get('simulation_batch', {}).get('items', [])])
        previews += [row['preview'] for row in data.get('simulation_plan', {}).get('steps', [])
                     if row.get('preview')]
        if case.get('blocked') or case.get('readonly'):
            if any(row.get('status') == 'generated' for row in previews):
                failures.append('受限或只读问题生成了可执行预览')
        elif not any(row.get('status') == 'generated' for row in previews):
            failures.append('未生成有效指令预览')
        if case.get('ops'):
            payload_operations = {(row.get('candidate', {}).get('target'),
                                   row.get('candidate', {}).get('payload', {}).get('requested_action'))
                                  for row in previews if row.get('status') == 'generated'}
            if payload_operations != set(case['ops']):
                failures.append('最终指令设备或动作与预期不一致')
        devices = {row['device_id']: row for row in after['devices']}
        for device_id, field, value in case.get('facts', []):
            current = {**devices[device_id]['state'], **devices[device_id]['runtime_facts']}
            if current.get(field) != value:
                failures.append('补充状态采用错误：' + field)
        if case['id'] == 'A' and '250' not in data.get('answer', {}).get('text', ''):
            failures.append('回答正文未展示本次当前值250kW')
        if case['id'] == 'D' and '运行中' not in data.get('answer', {}).get('text', ''):
            failures.append('条件计划回答遗漏当前运行状态')
        if any(event.get('status') == 'succeeded' for event in runtime.events(snap['session_id'])):
            failures.append('分析时擅自执行动作')
        if case.get('unchanged') and snap != after:
            failures.append('冲突或未知操作请求改动了状态')
        for row in data.get('simulation_inputs', {}).get('applied', []):
            for source in row.get('sources', []):
                if source['origin'] == 'question' and type(source['supplied_value']) in (int, float) and not source.get('value_evidence'):
                    failures.append('当前数值缺少原文字段核验记录')
        result = {'case': case, 'response': response, 'before': snap, 'after': after,
                  'calls': sum(row['case'] == active for row in calls), 'failures': failures}
        results.append(result)
        (out / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'case': active, 'status': response['status'], 'calls': result['calls'], 'failures': failures}, ensure_ascii=False), flush=True)
    (out / 'calls.json').write_text(json.dumps(calls, indent=2), encoding='utf-8')
    return int(any(row['failures'] for row in results))


if __name__ == '__main__':
    raise SystemExit(main())
