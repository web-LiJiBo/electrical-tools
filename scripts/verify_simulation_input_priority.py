"""Real-model acceptance for simulation input precedence; no model stubs."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import URLError
from http.client import RemoteDisconnected

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

CASES = [
    dict(id='text_fault', query='SIM-IEC-FAN-01当前设备故障标志device_fault为1，请启动该风机',
         expected='blocked', field='runtime_facts.device_fault', value=1),
    dict(id='business_fault', query='请启动SIM-IEC-FAN-01',
         extra={'device_facts': {'SIM-IEC-FAN-01': {'device_fault': 1}}},
         expected='blocked', field='runtime_facts.device_fault', value=1),
    dict(id='target_override', query='请将SIM-IEC-VALVE-01的有功功率回降至60MW',
         expected='generated', target=60),
    dict(id='business_target', query='请将SIM-IEC-VALVE-01的有功功率回降至指定目标值，目标在业务参数中提供',
         extra={'action_parameters': {'target_power_mw': 60}}, expected='generated', target=60),
    dict(id='fill_missing', query='SIM-IEC-FAN-01当前设备故障标志device_fault为0，请启动该风机',
         remove='device_fault', expected='generated', field='runtime_facts.device_fault', value=0),
    dict(id='input_conflict', query='SIM-IEC-FAN-01当前设备故障标志device_fault为0，请启动该风机',
         extra={'device_facts': {'SIM-IEC-FAN-01': {'device_fault': 1}}}, expected='conflict'),
    dict(id='derived_position', query='SIM-IEC-BREAKER-01当前分合位置position为open，请对该断路器分闸',
         expected='generated', device='SIM-IEC-BREAKER-01', field='state.position', value='open', derived=0),
    dict(id='unit_conversion', query='SIM-IEC-BREAKER-01当前支路电流current为0.2kA，请对该断路器分闸',
         expected='generated', device='SIM-IEC-BREAKER-01', field='runtime_facts.current', value=200),
    dict(id='reference_only', query='历史记录记载SIM-IEC-FAN-01的device_fault为1，这只是历史记录，不修改当前状态。请查询它当前的设备故障标志',
         expected='reference'),
    dict(id='business_target_conflict', query='请将SIM-IEC-VALVE-01的有功功率回降至60MW',
         extra={'action_parameters': {'target_power_mw': 70},
                'device_facts': {'SIM-IEC-FAN-01': {'device_fault': 1}}}, expected='conflict'),
    dict(id='invalid_enum', query='请对SIM-IEC-BREAKER-01分闸',
         extra={'device_facts': {'SIM-IEC-BREAKER-01': {'position': 'invalid'}}}, expected='conflict'),
    dict(id='normal_regression', query='请启动SIM-IEC-FAN-01', expected='generated'),
    dict(id='clear_fixture_fault', query='请启动SIM-IEC-FAN-01', seed_fault=True,
         extra={'device_facts': {'SIM-IEC-FAN-01': {'device_fault': 0}}},
         expected='generated', field='runtime_facts.device_fault', value=0),
    dict(id='derived_alias', query='请对SIM-IEC-BREAKER-01分闸',
         extra={'device_facts': {'SIM-IEC-BREAKER-01': {'breaker_closed': 0}}},
         expected='generated', device='SIM-IEC-BREAKER-01', field='state.position', value='open', derived=0),
    dict(id='action_binding_conflict', query='请启动SIM-IEC-FAN-01',
         extra={'action': 'stop', 'device_facts': {'SIM-IEC-FAN-01': {'device_fault': 1}}}, expected='conflict'),
    dict(id='device_binding_conflict', query='请启动SIM-IEC-FAN-01',
         extra={'device_id': 'SIM-MB-FAN-01', 'device_facts': {'SIM-IEC-FAN-01': {'device_fault': 1}}}, expected='conflict'),
    dict(id='equivalent_current', query='SIM-IEC-BREAKER-01当前支路电流current为0.7A，请对该断路器分闸',
         extra={'device_facts': {'SIM-IEC-BREAKER-01': {'current': {'value': 700, 'unit': 'mA'}}}},
         expected='blocked', device='SIM-IEC-BREAKER-01', field='runtime_facts.current', value=0.7),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cases', nargs='*')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    import yaml
    from standard_knowledge_service_v2.bootstrap import build_application
    from standard_knowledge_service_v2.contracts import AnalysisRequest
    from standard_knowledge_service_v2.application.simulation_access import simulation_runtime
    from standard_knowledge_service_v2.decomposition import remote_model_decomposer as remote

    active = 'startup'
    original_http = remote.urlopen
    attempts = []
    def real_http(request, *a, **kw):
        for attempt in range(3):
            row = {'case': active, 'attempt': attempt + 1}
            try:
                response = original_http(request, *a, **kw)
                row['status'] = response.status
                return response
            except (URLError, RemoteDisconnected, TimeoutError, ConnectionError) as exc:
                row['exception'] = type(exc).__name__
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
            finally:
                attempts.append(row)
                with (args.out / '真实HTTP记录.jsonl').open('a', encoding='utf-8') as f:
                    f.write(json.dumps(row, ensure_ascii=False) + '\n')
    remote.urlopen = real_http
    cfg = yaml.safe_load((ROOT / 'configs/settings.example.yaml').read_text(encoding='utf-8'))
    cfg['audit']['store'] = str(args.out / '验收审计.jsonl')
    cfg['knowledge']['build_summary'] = str(args.out / '图谱摘要.json')
    cfg['knowledge']['sync_state_path'] = str(args.out / '图谱状态.json')
    config = args.out / '验收配置.yaml'
    config.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding='utf-8')
    app = build_application(config).facade
    runtime = simulation_runtime(app)
    original_complete = app.decomposer.complete
    def complete(system, user):
        raw = original_complete(system, user)
        with (args.out / '模型原始输出.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps({'case': active, 'system': system, 'user': user, 'raw': raw}, ensure_ascii=False) + '\n')
        return raw
    app.decomposer.complete = complete
    results = []
    for case in CASES:
        if args.cases and case['id'] not in args.cases:
            continue
        active = case['id']
        snapshot = runtime.create_session('all_devices')
        sid = snapshot['session_id']
        if case.get('remove'):
            del runtime._sessions[sid].devices['SIM-IEC-FAN-01']['runtime_facts'][case['remove']]
        if case.get('seed_fault'):
            runtime._sessions[sid].devices['SIM-IEC-FAN-01']['runtime_facts']['device_fault'] = 1
        before = runtime.snapshot(sid)
        params = {'simulation_mode': True, 'simulation_session_id': sid, **case.get('extra', {})}
        response = app.analyze(AnalysisRequest(case['query'], parameters=params)).to_dict()
        after = runtime.snapshot(sid)
        entry = next(d for d in after['devices'] if d['device_id'] == case.get('device', 'SIM-IEC-FAN-01'))
        data = response['data']
        row = {'id': active, 'query': case['query'], 'parameters': case.get('extra', {}),
               'response': response, 'snapshot_before': before, 'snapshot_after': after,
               'real_api': data.get('decomposition', {}).get('source') == 'model_api'}
        errors = []
        if not row['real_api']:
            errors.append('实际模型理解未成功')
        if response['status'] == 'partial':
            errors.append('模型处理未完成，不能计入通过')
        generated = response['status'] == 'generated'
        if case['expected'] == 'generated' and not generated:
            errors.append('应生成指令')
        if case['expected'] in ('blocked', 'conflict') and generated:
            errors.append('应阻止生成')
        if 'field' in case:
            section, field = case['field'].split('.')
            if entry.get(section, {}).get(field) != case['value']:
                errors.append('未优先采用用户当前值')
            comparisons = data.get('simulation_inputs', {}).get('applied', [])
            if not comparisons:
                errors.append('缺少输入来源与原值记录')
        if 'derived' in case and entry['runtime_facts']['breaker_closed'] != case['derived']:
            errors.append('关联事实未同步')
        if case['expected'] in ('conflict', 'reference') and after != before:
            errors.append('冲突或参考记录改变了状态')
        preview = data.get('simulation_preview')
        if generated and preview:
            message = runtime.generate_message(sid, preview['command_id'], preview['expected_version'], {})
            row['message'] = message
            if runtime.snapshot(sid) != after or message['sent']:
                errors.append('报文生成改变了状态或发生发送')
            if 'target' in case and message['engineering_value'] != case['target']:
                errors.append('报文目标值不正确')
            if data.get('simulation_inputs', {}).get('applied') and not (
                    message.get('simulation_inputs') or message.get('parameter_comparison')):
                errors.append('报文未保留补充输入来源')
        if any(e.get('status') in ('succeeded', 'failed', 'feedback_failed') for e in runtime.events(sid)):
            errors.append('分析发生了动作执行')
        row.update(accepted=not errors, failures=errors)
        results.append(row)
        (args.out / '验收结果.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'id': active, 'accepted': row['accepted'], 'status': response['status'], 'failures': errors, 'answer': data.get('answer')}, ensure_ascii=False), flush=True)
    summary = {'cases': len(results), 'accepted': sum(r['accepted'] for r in results),
               'failed': [{'id': r['id'], 'failures': r['failures']} for r in results if not r['accepted']],
               'real_http_attempts': len(attempts), 'model_responses_mocked': False}
    (args.out / '验收汇总.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
