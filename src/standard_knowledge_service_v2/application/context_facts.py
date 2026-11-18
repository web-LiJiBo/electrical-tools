"""User observations can explicitly supplement the local simulation world."""
import re
from copy import deepcopy


def apply_user_inputs(pipeline, request, understanding):
    """Resolve the whole input set first; never partially apply conflicting values."""
    from .simulation_access import simulation_runtime, default_session, view_snapshot
    from ..instruction_engine.simulation_inputs import collect_inputs
    runtime = simulation_runtime(pipeline)
    sid = request.parameters.get('simulation_session_id')
    snapshot = runtime.snapshot(sid) if sid else default_session(pipeline)
    snapshot = view_snapshot(pipeline, request, snapshot)
    profiles = {d['device_id']: runtime.catalog.devices[d['device_id']] for d in snapshot['devices']}
    operations = understanding.operations or []
    supplied_action = request.parameters.get('action')
    if supplied_action and any(row['action'] != supplied_action for row in operations):
        raise ValueError('提问与业务参数中的动作冲突；未更新模拟状态')
    supplied_ids = request.parameters.get('device_ids') or ([request.parameters['device_id']]
                    if request.parameters.get('device_id') else [])
    targets = {row['device_id'] for row in operations}
    if not targets:
        targets = {row['device_id'] for row in (understanding.queries or []) if row.get('device_id')}
    if supplied_ids and (not isinstance(supplied_ids, list)
            or any(not isinstance(value, str) for value in supplied_ids)
            or {value.upper() for value in supplied_ids} != targets):
        raise ValueError('提问与业务参数中的设备冲突；未更新模拟状态')
    supplied = request.parameters.get('action_parameters', {})
    if not isinstance(supplied, dict):
        raise ValueError('action_parameters须为字段对象')
    if supplied:
        from .action_parameters import resolve_action_parameters
        if len(operations) != 1:
            raise ValueError('业务动作目标只能绑定一条明确操作')
        operation = operations[0]
        if any(key in operation['parameters'] and operation['parameters'][key] != value
               for key, value in supplied.items()):
            raise ValueError('提问与业务参数中的动作目标冲突；未更新模拟状态')
        template = profiles.get(operation['device_id'], {}).get('actions', {}).get(operation['action'], {})
        _, reason = resolve_action_parameters(operation['source_text'], template, supplied, {'parameter_evidence': operation.get('parameter_evidence', []), 'model_parameters': operation['parameters'], 'business_parameters': supplied})
        if reason:
            raise ValueError(reason)
    updates, skipped = collect_inputs(profiles, understanding.context_facts,
        request.parameters.get('device_facts', {}), request.query,
        runtime.catalog.scenarios.get(snapshot.get('scenario_id'), {}))
    report = runtime.apply_fact_inputs(snapshot['session_id'], updates, expected_version=snapshot['version'])
    report['skipped'] = skipped
    return report


def context_error(understanding, query, devices):
    compact = lambda value: re.sub(r'\s+', '', str(value)).casefold()
    ids = {row['device_id'] for row in devices}
    for fact in understanding.context_facts:
        if fact['device_id'] not in ids or compact(fact['source_text']) not in compact(query):
            return '背景事实缺少当前设备或原文依据，请明确其来源。'
    if understanding.scenario.get('context_kind') == 'uncertain':
        return '尚不能区分背景说明与执行前提，请明确哪些条件必须在操作前满足。'
    return ''


def background_only(understanding):
    return understanding.scenario.get('context_kind') == 'background' and bool(understanding.context_facts)


def describes_observation(constraint, understanding):
    return background_only(understanding) and any(
        all(constraint.get(key, '') == fact.get(key, '') for key in ('parameter', 'operator', 'value', 'unit'))
        for fact in understanding.context_facts)


def annotate_context(data):
    facts = data.get('decomposition', {}).get('context_facts') or []
    report = data.get('simulation_inputs') or {}
    applied = list(report.get('applied', []))
    def visit(value):
        if isinstance(value, dict):
            for row in value.get('parameter_comparison', []):
                if row not in applied:
                    applied.append(deepcopy(row))
            for key in ('simulation_preview', 'simulation_batch', 'simulation_plan', 'items', 'steps', 'preview'):
                if key in value:
                    visit(value[key])
        elif isinstance(value, list):
            for row in value:
                visit(row)
    visit(data)
    if applied:
        data['simulation_inputs'] = {**report, 'applied': applied}
        conflicts = [row for row in applied if row.get('conflict')]
        if conflicts:
            notice = f'补充输入与模拟数据有{len(conflicts)}处冲突，已优先采用补充输入；详情见“系统理解”。'
            text = data.setdefault('answer', {}).setdefault('text', '')
            if notice not in text:
                data['answer']['text'] = text + '\n' + notice
    if not facts:
        return
    devices = {row['device_id']: row for row in data.get('devices', [])}
    rows = []
    for fact in facts:
        device = devices.get(fact['device_id'], {})
        current = {**device.get('state', {}), **device.get('runtime_facts', {})}
        rows.append({**fact, 'origin': 'user_statement', 'current_value': current.get(fact['parameter']),
                     'field_status': ('not_matched' if fact['parameter'] not in current
                         else 'unavailable' if current[fact['parameter']] is None else 'unverified'),
                     'comparison': 'not_verified', 'notice': '已匹配的当前值可用于模拟校验；参考值、范围和未匹配字段仍作为背景。'})
    data['context_fact_comparison'] = rows
    data.setdefault('answer', {}).setdefault('text', '')
    notice = '未采用的背景数据仍保留来源，详情见“系统理解”。'
    if applied:
        return
    if notice not in data['answer']['text']:
        data['answer']['text'] += '\n' + notice
