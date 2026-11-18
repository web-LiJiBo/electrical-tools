"""Normalize representations and expose ordinary business clarification early."""
from copy import deepcopy
import json

from ..decomposition.evidence import literal, reference_text, target_evidence
from .action_parameters import _convert
from ..instruction_engine.operation_conditions import compile_conditions


def normalize_plan(understanding, query, catalog, business_parameters=None, conversation_context=()):
    result = deepcopy(understanding)
    if result.operations is None or result.queries is None:
        return result
    current = []
    for fact in result.context_facts:
        source = literal(fact.get('source_text', ''))
        if source and source not in literal(query) and any(
                source in literal(message.get('content', '')) for message in conversation_context):
            result.historical_facts.append({**fact, 'usage': 'reference', 'source_kind': 'conversation_history'})
            result.normalization_notes.append('历史对话中的状态仅保留作参考，不作为本次新补充状态；按当前快照校验')
        else:
            current.append(fact)
    result.context_facts = current
    positive = []
    for operation in result.operations:
        if operation.get('negated') is True:
            result.prohibitions.append({key: deepcopy(operation.get(key, ''))
                for key in ('device_id', 'target_text', 'owner_id', 'action', 'source_text', 'clarification')})
        else:
            positive.append(operation)
    result.operations = positive
    supplied = (business_parameters or {}).get('action_parameters', {})
    supplied = supplied if isinstance(supplied, dict) else {}
    for operation in positive:
        evidence = []
        for item in operation.get('parameter_evidence', []):
            parameter = item.get('parameter')
            valid_literal = (item.get('source_text') and literal(item['source_text']) in literal(query)
                             and item.get('value_text') and literal(item['value_text']) in literal(item['source_text']))
            if not valid_literal and parameter in supplied and operation['parameters'].get(parameter) == supplied[parameter]:
                result.normalization_notes.append('动作目标采用用户业务参数，不伪造正文数字引用')
            else:
                evidence.append(item)
        operation['parameter_evidence'] = evidence
        template = catalog.devices.get(operation['device_id'], {}).get('actions', {}).get(operation['action'], {})
        parameter = template.get('parameter')
        try:
            values = target_evidence(query, evidence, parameter, _convert, template.get('unit', '')) if parameter else []
        except ValueError:
            values = []  # Keep invalid evidence for the validation layer to reject.
        if values and len(set(values)) == 1:
            value = values[0]
            canonical = int(value) if value == value.to_integral_value() else float(value)
            if operation['parameters'].get(parameter) != canonical:
                result.normalization_notes.append('按原文数值和单位规范化目标参数：' + parameter)
            operation['parameters'][parameter] = canonical
    result.actions = list(dict.fromkeys(row['action'] for row in positive)) if positive else result.actions
    for row in [*result.operations, *result.queries, *result.prohibitions]:
        source = row.get('source_text', '')
        if source and literal(source) not in literal(query) and reference_text(source) in reference_text(query):
            row['source_text'] = query
            result.normalization_notes.append('编号规范化引用已关联原始问题，未修改原问题')
    if result.scenario.get('context_kind') == 'background':
        for row in result.operations:
            profile = catalog.devices.get(row['device_id'], {})
            template = profile.get('actions', {}).get(row['action'], {})
            intrinsic = [template.get('condition', '')]
            intrinsic += [f"{c.get('parameter')} {c.get('operator')} {json.dumps(c.get('value'))}"
                          for c in template.get('constraints', []) if c.get('role') != 'compliance']
            facts = [f"{f['parameter']} == {json.dumps(f['value'])}" for f in result.context_facts
                     if f['device_id'] == row['device_id'] and f.get('usage') == 'current'
                     and f.get('operator') in ('=', '==')]
            signatures = set()
            def signature(expression):
                try:
                    item = compile_conditions([expression], profile)[0]
                    return item['section'], item['field'], item['operator'], json.dumps(item['value'], sort_keys=True)
                except (ValueError, KeyError, TypeError):
                    return None
            for expression in [*intrinsic, *facts]:
                value = signature(expression)
                if value:
                    signatures.add(value)
            explicit = {e['expression'] for e in row.get('condition_evidence', [])
                        if e.get('kind') == 'user_condition' and e.get('source_text')
                        and literal(e['source_text']) in literal(query)}
            kept = []
            for expression in row.get('conditions', []):
                if expression not in explicit and signature(expression) in signatures:
                    result.normalization_notes.append('背景或模板条件不重复记为用户前提：' + expression)
                else:
                    kept.append(expression)
            row['conditions'] = kept
    return result


def clarification_questions(understanding, catalog):
    if understanding.operations is None or understanding.queries is None:
        return []
    questions = list(understanding.clarifications)
    for row in [*(understanding.operations or []), *(understanding.queries or [])]:
        if row.get('clarification'):
            questions.append(row['clarification'])
        elif row.get('device_id') not in catalog.devices and (row.get('device_id') or 'action' in row
                or row.get('query_kind') in ('device_status', 'device_capability', 'device_readiness')):
            name = row.get('target_text') or row.get('device_id') or '设备'
            questions.append(f'请明确{name}对应的已登记设备；当前没有选择或替换设备。')
    if (understanding.scenario.get('query_kind') == 'operation' and not understanding.operations
            and not understanding.queries and not understanding.prohibitions and not questions):
        names = '、'.join(row.get('name', '') for row in understanding.entities)
        questions.append(f'未形成明确的可用操作，请核对设备{names or "名称/编号"}及所需动作。')
    return list(dict.fromkeys(q for q in questions if q))


def unresolved_response(pipeline, request, understanding, questions):
    from .simulation_access import simulation_runtime, default_session, view_snapshot
    from .semantic_operations import factual_plan_queries, factual_answer
    runtime = simulation_runtime(pipeline)
    sid = request.parameters.get('simulation_session_id')
    snapshot = view_snapshot(pipeline, request, runtime.snapshot(sid) if sid else default_session(pipeline))
    known = deepcopy(understanding)
    known.operations = []
    known.queries = [row for row in known.queries if row.get('device_id') in runtime.catalog.devices
                     and not row.get('clarification') and row['query_kind'] in
                     ('device_status', 'device_capability', 'device_readiness')]
    devices = [{**runtime.catalog.devices[d['device_id']], **d} for d in snapshot['devices']]
    results, error = factual_plan_queries(known, request, snapshot, devices,
        runtime.catalog.scenarios.get(snapshot.get('scenario_id'), {})) if known.queries else ([], '')
    if error:
        results = []
    text = factual_answer(results)
    text += ('\n' if text else '') + '需要补充：' + '；'.join(questions) + ' 未生成操作指令。'
    data = {'simulation_factual': True, 'simulation_session_id': snapshot['session_id'],
            'context': {'scenario': snapshot.get('scenario_id')}, 'decomposition': understanding.to_dict(),
            'candidate_instruction': None, 'answer': {'text': text}, 'query_results': results,
            'clarification_required': True, 'clarification_questions': questions, 'resolution_status': 'needs_clarification',
            'devices': [device for item in results for device in item['devices']]}
    questions = [row for row in understanding.queries if row['query_kind'] == 'standard_query'
                 or row['query_kind'] == 'assessment' and not row.get('clarification')
                 and row.get('device_id') in runtime.catalog.devices]
    if questions:
        knowledge = pipeline._question_response(request, understanding, questions)
        data['query_results'].append({'query_kind': 'knowledge', 'status': knowledge.status,
                                     'data': knowledge.data, 'evidence': knowledge.evidence})
        data['answer']['text'] += '\n' + knowledge.data.get('answer', {}).get('text', '来源或条件不足，请查看条款查询结果。')
    return data


def preflight_blocked_response(pipeline, request, understanding):
    """An entirely blocked request needs facts, not a second model verdict."""
    if not understanding.operations or any(row.get('conditions') or row.get('order') is not None for row in understanding.operations):
        return None
    from .simulation_access import simulation_runtime, default_session, view_snapshot
    from .semantic_operations import validate_operation_rows, operation_previews
    runtime = simulation_runtime(pipeline)
    sid = request.parameters.get('simulation_session_id')
    snapshot = view_snapshot(pipeline, request, runtime.snapshot(sid) if sid else default_session(pipeline))
    devices = [{**runtime.catalog.devices[d['device_id']], **d} for d in snapshot['devices']]
    profile = runtime.catalog.scenarios.get(snapshot.get('scenario_id'), {})
    rows, _, error = validate_operation_rows(pipeline, request, snapshot, devices, profile, understanding)
    if error or not rows or any(row.get('unsupported') for row in rows):
        return None
    with runtime._lock:
        session = runtime._session(snapshot['session_id'])
        if session.version != snapshot['version']:
            return None
        checks = [runtime._prepare(session, row['device_id'], row['action'], row['parameters']) for row in rows]
        if any(check['status'] == 'generated' for check in checks):
            return None
        result = operation_previews(pipeline, request, snapshot, devices, profile, understanding)
    result[1]['operation_review'] = {'status': 'not_requested', 'reason_code': 'runtime_blocked',
                                    'reason': '程序校验未通过，未请求模型批准或生成可执行预览'}
    return result
