"""Read-only compilation followed by reviewed, explicitly confirmed plans."""
from copy import deepcopy

from .simulation_access import default_session, simulation_runtime, view_snapshot
from .request_controls import analysis_only_requested, request_controls_error
from .operation_review import _same_json
from ..instruction_engine.operation_conditions import compile_conditions, evaluate_conditions


def prepare_operation_plan(pipeline, request, decomposed):
    """Produce server review context without allocating any command or plan ID."""
    operations = decomposed.operations or []
    if not operations or not any(row.get('conditions') or row.get('order') is not None for row in operations):
        return None
    prepared = {'status': 'blocked', 'reason': '', 'steps': [], 'execution_support': {}}
    if request.parameters.get('simulation_mode') is not True:
        prepared['reason'] = '受限条件和顺序计划仅支持明确开启的本地模拟模式。'
        return prepared
    if analysis_only_requested(decomposed):
        prepared['reason'] = '本次请求只做分析，不能生成执行计划。'
        return prepared
    runtime = simulation_runtime(pipeline)
    try:
        sid = request.parameters.get('simulation_session_id')
        snapshot = runtime.snapshot(sid) if sid else default_session(pipeline)
        snapshot = view_snapshot(pipeline, request, snapshot)
        prepared['snapshot'] = deepcopy(snapshot)
        devices = [{**deepcopy(runtime.catalog.devices[row['device_id']]), **row,
                    'actions': deepcopy(runtime.catalog.devices[row['device_id']]['actions'])}
                   for row in snapshot['devices']]
        profile = runtime.catalog.scenarios.get(snapshot.get('scenario_id'), {})
        from .semantic_operations import validate_operation_rows
        rows, factual_results, reason = validate_operation_rows(pipeline, request, snapshot, devices, profile,
                                                                decomposed, allow_restrictions=True)
        if reason:
            prepared['reason'] = reason
            return prepared
        orders = [row.get('order') for row in operations]
        ordered = any(value is not None for value in orders)
        if len(rows) > 1 and not ordered:
            prepared['reason'] = '多项条件操作须明确连续顺序；当前不支持无顺序的条件批量操作，请分开提出。'
            return prepared
        if ordered and (any(type(value) is not int for value in orders)
                        or sorted(orders) != list(range(1, len(rows) + 1))):
            prepared['reason'] = '仅支持每项明确编号、从1开始连续且唯一的顺序步骤。'
            return prepared
        for row, original in zip(rows, operations):
            if row.get('unsupported'):
                prepared['reason'] = '设备不支持所请求的动作，未生成部分顺序计划。'
                return prepared
            row.pop('unsupported', None)
            row['conditions'] = deepcopy(original.get('conditions', []))
            row['order'] = original.get('order')
            compiled = compile_conditions(row['conditions'], runtime.catalog.devices[row['device_id']])
            entry = next(device for device in snapshot['devices'] if device['device_id'] == row['device_id'])
            row['condition_checks'] = evaluate_conditions(compiled, entry)
        prepared.update(status='prepared', steps=sorted(rows, key=lambda row: row['order']) if ordered else rows,
                        factual_results=factual_results, catalog_version=runtime._catalog_version(),
                        execution_support={'conditions': any(row.get('conditions') for row in operations),
                                           'order': ordered, 'operations': deepcopy(operations),
                                           'failure_policy': 'stop_on_unsuccessful_or_unknown_feedback' if ordered else None,
                                           'condition_failure_policy': 'block_on_unsatisfied_or_unknown_conditions',
                                           'per_step_confirmation': True})
    except (KeyError, ValueError, TypeError) as exc:
        prepared['reason'] = f'无法安全准备受限执行计划：{exc}'
    return prepared


def preview_operation_plan(pipeline, request, decomposed, prepared):
    """Called only after review approval; only the first step receives a command."""
    snapshot = prepared.get('snapshot', {})
    base = {'simulation_factual': True, 'simulation_session_id': snapshot.get('session_id'),
            'semantic_plan': True, 'candidate_instruction': None, 'devices': [], 'dispatch_allowed': False,
            'context': {'scenario': snapshot.get('scenario_id')}}
    reason = prepared.get('reason')
    controls_error = request_controls_error(decomposed, request.query)
    if analysis_only_requested(decomposed) or controls_error:
        reason = controls_error or '本次请求只做分析，不能生成执行计划。'
    elif request.parameters.get('simulation_mode') is not True:
        reason = '受限执行计划需要明确开启本地模拟模式。'
    elif request.parameters.get('simulation_session_id', snapshot.get('session_id')) != snapshot.get('session_id'):
        reason = '模拟会话在准备后发生变化，请重新分析。'
    elif prepared.get('status') == 'prepared':
        runtime = simulation_runtime(pipeline)
        if prepared.get('catalog_version') != runtime._catalog_version():
            reason = '操作复核期间配置版本发生变化，请重新分析。'
        elif not _same_json(prepared.get('execution_support', {}).get('operations'), decomposed.operations):
            reason = '操作清单在准备后发生变化，请重新分析。'
        else:
            try:
                plan = runtime.create_plan(snapshot['session_id'], prepared['steps'], expected_version=snapshot['version'])
            except (ValueError, KeyError) as exc:
                return _blocked_response(base, f'计划预览已阻止：{exc}')
            base['simulation_plan'] = plan
            base['query_results'] = deepcopy(prepared.get('factual_results', []))
            first = plan['steps'][0]['preview']
            ids = {row['device_id'] for row in prepared['steps']}
            base['devices'] = [{key: deepcopy(device.get(key)) for key in
                ('device_id', 'display_name', 'device_type', 'protocol', 'state', 'runtime_facts')}
                for device in snapshot['devices'] if device['device_id'] in ids]
            base['candidate_instruction'] = first['candidate'] if first['status'] == 'generated' else None
            reason = (f"已准备{len(plan['steps'])}步操作，仅第1步可预览；须逐步明确确认，前步成功反馈后才开放下一步。"
                      if first['status'] == 'generated' else first['explanation'])
            if first.get('condition_checks'):
                additions = [check['explanation'] for check in first['condition_checks'] if check['explanation'] not in reason]
                if additions:
                    reason += '\n' + '\n'.join(additions)
            base['answer'] = {'text': reason}
            if first['status'] == 'generated':
                return 'generated', base, [], []
            base['condition_status'] = 'unknown' if any(
                check['status'] == 'unknown' for check in first.get('condition_checks', [])) else 'blocked'
            base['clarification_required'] = False
    reason = reason or '执行条件或顺序无法安全编译，未生成指令。'
    return _blocked_response(base, reason)


def _blocked_response(base, reason):
    base.update(answer={'text': reason}, control_block_reason=reason,
                clarification_required=base.get('clarification_required', True))
    base['clarification_questions'] = [reason] if base['clarification_required'] else []
    return 'uncertain', base, [], []
