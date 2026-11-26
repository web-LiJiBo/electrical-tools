"""Validate one model-authored semantic plan, then create local previews only."""
from copy import deepcopy
import re

from .action_parameters import resolve_action_parameters
from ..decomposition.evidence import reference_text, catalog_spans
from .action_request import action_request_restriction
from .simulation_access import simulation_runtime
from .request_controls import analysis_only_requested, control_source_text, request_controls_error


def _compact(value):
    return re.sub(r'\s+', '', str(value)).casefold()


def catalog_context(pipeline, request):
    """Identity and capabilities only: model understanding never reads live state."""
    runtime = simulation_runtime(pipeline)
    catalog = runtime.catalog
    scene = catalog.scenarios.get(request.parameters.get('simulation_scenario_id'), {})
    ids = scene.get('device_ids', list(catalog.devices))
    if request.parameters.get('simulation_session_id'):
        from .simulation_access import view_snapshot
        snapshot = view_snapshot(pipeline, request, runtime.snapshot(request.parameters['simulation_session_id']))
        scene = catalog.scenarios.get(snapshot.get('scenario_id'), {})
        ids = [row['device_id'] for row in snapshot['devices']]
    ownership = []
    for profile in catalog.scenarios.values():
        groups = profile.get('groups', {})
        for group in groups.values() if isinstance(groups, dict) else groups:
            for role, device_id in group.items():
                link = {'owner_id': group.get('transformer', ''), 'device_id': device_id, 'role': role}
                if role != 'transformer' and device_id in ids and link not in ownership:
                    ownership.append(link)
    from ..instruction_engine.simulation_inputs import fact_schema
    devices = [catalog.devices[key] for key in ids]
    history = next((message.get('content', '') for message in reversed(request.conversation_context)
                    if message.get('role') == 'user'), '')
    mentioned = _explicit_targets(history, devices, scene) if history else set()
    pools = {}
    for device in devices:
        pools.setdefault(device['device_type'], set()).add(device['device_id'])
    alternatives = [{'device_type': kind, 'previous_device_id': next(iter(pool & mentioned)),
                     'other_device_id': next(iter(pool - mentioned))}
                    for kind, pool in pools.items() if len(pool) == 2 and len(pool & mentioned) == 1]
    return {'reference_context': {'source_text': history, 'mentioned_device_ids': sorted(mentioned),
                                 'unique_alternatives': alternatives},
            'business_parameters': {'action_parameters': deepcopy(request.parameters.get('action_parameters', {}))},
            'devices': [{key: deepcopy(device.get(key, '')) for key in
            ('device_id', 'display_name', 'device_type', 'device_type_name', 'aliases', 'business_scenario')}
            | {'actions': {action: {key: deepcopy(template.get(key)) for key in
                ('display_name', 'parameter', 'parameter_label', 'parameter_type', 'unit', 'minimum', 'maximum',
                 'value_source', 'value', 'result_field', 'unit_definitions', 'simulation_effects', 'condition', 'constraints')}
                for action, template in device.get('actions', {}).items()},
               'fact_fields': sorted(set(device.get('initial_state', {})) | set(device.get('runtime_facts', {}))),
               'fact_schema': fact_schema(device),
               'fact_units': deepcopy(device.get('fact_units', {}))}
            for device_id in ids for device in [catalog.devices[device_id]]], 'ownership': ownership}


def _mention_spans(text, devices):
    return catalog_spans(text, devices)


def _mentions(text, devices, *, nested=False):
    return {key for key, _, _ in catalog_spans(text, devices, nested=nested)}


_ROLES = {'cooling_fan': r'风机|风扇', 'oil_pump': r'油泵', 'tap_changer': r'调压|档位',
          'breaker': r'断路器', 'disconnector': r'隔离开关', 'earthing_switch': r'接地开关',
          'inverter': r'逆变器', 'battery_pcs': r'储能(?:变流器)?'}


def _explicit_targets(query, devices, profile):
    """Check explicit identities per occurrence without choosing model targets."""
    text = reference_text(query)
    spans = sorted(_mention_spans(query, devices), key=lambda span: span[1:])
    owners = {device['device_id'] for device in devices if device['device_type'] == 'transformer'}
    groups = profile.get('groups', {})
    groups = list(groups.values()) if isinstance(groups, dict) else groups
    roles = {**_ROLES, 'cooling_fan': r'(?:冷却)?(?:风机|风扇)',
             'tap_changer': r'(?:有载)?调压装置'}
    required = set()
    for key, start, end in spans:
        if key not in owners:
            required.add(key)
            continue
        # Coordinated owners can share the accessory suffix. Follow only
        # consecutive, explicitly named catalog owners joined by conjunctions.
        suffix, coordinated_owners = end, {key}
        for other, left, right in spans:
            if left < suffix:
                continue
            if (other in owners and other not in coordinated_owners
                    and re.fullmatch(r'和|与|及|、|以及', text[suffix:left])):
                suffix = right
                coordinated_owners.add(other)
            else:
                break
        possessive = {role for role, pattern in roles.items()
            if re.match(r'的?(?:(?:那|这|该)台|各自的?|分别的?)?(?:' + pattern + ')', text[suffix:])}
        coordinated = {role for role, pattern in roles.items()
            if re.match(r'(?:以及|和|与|及|、)(?:其|它的)(?:' + pattern + ')', text[end:])}
        if not possessive:
            required.add(key)
        for group in groups:
            if group.get('transformer') == key:
                required.update(group[role] for role in possessive | coordinated if group.get(role))
    return required


def _shared_suffix_target(target, source, owner, devices):
    """Accept only a catalog owner plus an explicitly shared accessory suffix."""
    owners = [device for device in devices if device['device_type'] == 'transformer']
    if len(_mentions(source, owners)) < 2 or not re.search(r'各自|分别|和|与|及|、', source):
        return False
    device = next((device for device in owners if device['device_id'] == owner), {})
    for alias in [device.get('device_id', ''), device.get('display_name', ''), *device.get('aliases', [])]:
        if alias and re.fullmatch(re.escape(_compact(alias)) + r'的?(?:冷却风机|风机|油泵|调压装置|有载调压装置)', _compact(target)):
            role = re.sub('^' + re.escape(_compact(alias)) + '的?', '', _compact(target))
            return _compact(alias) in _compact(source) and role in _compact(source)
    return False


def bind_target(item, query, devices, profile, *, previous=None, conversation_context=()):
    """Reject invented evidence, unknown IDs, and contradicted owner/child pairs."""
    if item.get('clarification'):
        return '', item['clarification']
    source, target = item.get('source_text', ''), item.get('target_text', '')
    if not source or _compact(source) not in _compact(query):
        return '', '模型提供的原文证据未出现在本次问题中，请重新明确请求。'
    # A source span can include an earlier explicit target in the same request;
    # it cannot choose among multiple devices or rewrite the original wording.
    if (reference_text(target) in reference_text(query)
            and _explicit_targets(query, devices, profile) == {item.get('device_id', '').upper()}):
        source = query
    if not target or (reference_text(target) not in reference_text(source)
            and not _shared_suffix_target(target, source, item.get('owner_id', '').upper(), devices)):
        return '', '设备目标缺少对应原文证据，请明确设备。'
    key = item.get('device_id', '').upper()
    by_id = {device['device_id']: device for device in devices}
    if key not in by_id:
        return '', '当前场景未登记所请求的设备，请核对编号或名称。'
    device = by_id[key]
    mentioned = _mentions(target, devices)
    owner = item.get('owner_id', '').upper()
    owners = {d['device_id'] for d in devices if d['device_type'] == 'transformer'}
    stated_owners = mentioned & owners
    if owner and owner not in owners:
        return '', '设备所属关系没有对应原文或目录依据，请明确目标。'
    if len(stated_owners) == 1:
        stated_owner = next(iter(stated_owners))
        if owner and owner != stated_owner:
            return '', '设备所属关系与原文不一致，请明确目标。'
        owner = stated_owner if device['device_type'] != 'transformer' else owner
    groups = profile.get('groups', {})
    groups = list(groups.values()) if isinstance(groups, dict) else groups
    if owner and device['device_type'] != 'transformer':
        if not any(group.get('transformer') == owner and group.get(device['device_type']) == key for group in groups):
            return '', '设备编号与所属主设备相矛盾，请明确要操作哪台设备。'
    same_type = {value for value in mentioned if by_id[value]['device_type'] == device['device_type']}
    if same_type and key not in same_type:
        return '', '原文设备名称与识别编号不一致，请明确目标。'
    if len(same_type) > 1 and not owner:
        return '', '原文存在多个同名候选设备，请使用完整名称或唯一编号。'
    role = next((kind for kind, pattern in _ROLES.items() if re.search(pattern, target)), None)
    if role is None and owner and 'action' not in item:
        source_roles = {kind for kind, pattern in _ROLES.items() if re.search(pattern, source)}
        if len(source_roles) == 1:
            role = next(iter(source_roles))
    if device['device_type'] == 'transformer' and role:
        return '', '原文请求附属设备，但识别为主设备，请明确所属设备。'
    direct_relation = (owner and role == device['device_type']
                       and owner in _mentions(source, devices, nested=True))
    if key not in mentioned and not direct_relation:
        referenced = role is not None or re.search(r'其|它|该(?:设备|冷却风机|风机|油泵|断路器|开关|装置)|刚才|另(?:一)?台|另一个', target)
        contextual = set()
        if referenced:
            for message in reversed(conversation_context):
                if message.get('role') == 'user':
                    contextual = _mentions(message.get('content', ''), devices)
                    context_roles = {kind for kind, pattern in _ROLES.items() if re.search(pattern, message.get('content', ''))}
                    if context_roles:
                        contextual = {value for value in contextual if by_id[value]['device_type'] in context_roles}
                        if not contextual:
                            groups = profile.get('groups', {})
                            for group in groups.values() if isinstance(groups, dict) else groups:
                                if group.get('transformer') in _mentions(message.get('content', ''), devices):
                                    contextual.update(group[kind] for kind in context_roles if kind in group)
                    # Resolve an explicit owner/accessory reference through the
                    # same catalog relation, without consulting live state.
                    if contextual:
                        break
        from .device_references import reference_candidates
        preceding = (reference_candidates(target, previous, devices, profile, _ROLES)
                     if previous is not None else None)
        contextual = reference_candidates(target, contextual, devices, profile, _ROLES)
        current = set()
        if referenced:
            question, fragment, label = reference_text(query), reference_text(source), reference_text(target)
            start = question.find(fragment)
            if start >= 0:
                for match in re.finditer(re.escape(label), fragment):
                    candidates = _explicit_targets(question[:start + match.start()], devices, profile)
                    current.update(reference_candidates(target, candidates, devices, profile, _ROLES))
        # A current-sentence reference takes precedence over older messages.
        # More than one preceding target remains ambiguous, even when history
        # happens to mention the model's selected device.
        stated = _mentions(source, devices)
        resolved = (current == {key} if current else stated == {key} or
                    (preceding == {key} if preceding is not None else contextual == {key}))
        implicit = (_explicit_targets(query, devices, profile) == {key}
                    and _mentions(source, devices) == {key})
        if not (referenced and resolved or implicit):
            return '', '设备编号缺少唯一的原文或归属依据，请提供完整目标。'
    return key, ''


def clarification(base, reason):
    data = {'devices': [], **base, 'answer': {'text': reason}, 'control_block_reason': reason,
            'clarification_required': True, 'clarification_questions': [reason]}
    return 'uncertain', data, [], []


def plan_coverage(understanding, query, devices, profile):
    """Cross-check explicit catalog claims and original source coverage."""
    error = request_controls_error(understanding, query)
    if error:
        return error
    rows = [*understanding.operations, *understanding.queries, *understanding.prohibitions]
    covered = {row.get('device_id', '').upper() for row in rows}
    known = {reference_text(alias) for device in devices for alias in
        [device['device_id'], device.get('display_name', ''), *device.get('aliases', [])] if alias}
    if any(token not in known for token in re.findall(r'sim-[a-z0-9-]+', reference_text(query))):
        return '正文包含当前场景未登记的设备名称或编号，请核对。'
    uncovered = list(reference_text(query))
    for _, start, end in catalog_spans(query, devices):
        uncovered[start:end] = ' ' * (end - start)
    explicit = re.findall(r'SIM-[A-Z0-9-]+|(?:主变(?:压器)?|变压器|冷却风机|风机|油泵|断路器|隔离开关|接地开关|调压装置)\s*\d+', ''.join(uncovered), re.I)
    if explicit:
        return '正文包含当前场景未登记的设备名称或编号，请核对。'
    # Resolve ownership per occurrence: the owner in "主变1的风机" is
    # descriptive, while "主变1和主变1的风机" asks about two targets.
    if _explicit_targets(query, devices, profile) - covered:
        return '语义清单未覆盖正文中的全部明确设备，请补充或核对目标。'
    summary = set(understanding.actions) - {'inspect'}
    planned = {row['action'] for row in understanding.operations}
    # The historic summary code uses regulate_voltage for a tap assignment.
    if planned & {'set_tap', 'raise', 'lower', 'raise_tap', 'lower_tap'}:
        planned.add('regulate_voltage')
    if summary - planned and understanding.operations:
        return '整句动作摘要与逐项清单不完整一致，请明确所有操作。'
    sources = {_compact(row.get('source_text', '')) for row in rows}
    control_source = control_source_text(understanding, query)
    if control_source:
        sources.add(_compact(control_source))
    sources = sorted(sources, key=len, reverse=True)
    for source in sources:
        if not source or source not in _compact(query):
            return '清单来源未对应本次原文，请重新明确请求。'
    # Source spans prove provenance, not verbatim coverage of presentation text.
    # Explicit device coverage stays deterministic; operation intent/omissions
    # are checked against the entire request by the independent review.
    return ''


def untraced_text(understanding, query):
    """Unquoted prose is a completeness notice, never an execution decision."""
    remaining = _compact(query)
    sources = [row.get('source_text', '') for row in
               [*understanding.operations, *understanding.queries]]
    sources.append(control_source_text(understanding, query))
    for source in sorted({_compact(text) for text in sources if text}, key=len, reverse=True):
        remaining = remaining.replace(source, '')
    return re.sub(r'同时|并且|以及|谢谢(?:你|您)?|麻烦了|辛苦了|[，；;。?？、,！!\s]', '', remaining)


def _bind_plan_targets(understanding, request, devices, profile):
    # Bind in textual order so a query may refer to an earlier operation or
    # query. Targets coordinated in one source remain a set, never last-wins.
    rows = [*understanding.operations, *understanding.queries]
    rows = [item for item in rows if 'action' in item or item['query_kind'] in ('device_status', 'device_capability', 'device_readiness')]
    rows.sort(key=lambda item: _compact(request.query).find(_compact(item['source_text'])))
    source, group, previous = None, set(), None
    references, bindings = {}, {}
    for item in rows:
        if item['source_text'] != source:
            previous = group or previous
            source, group = item['source_text'], set()
        question, fragment, target = (reference_text(value) for value in
                                      (request.query, item['source_text'], item['target_text']))
        offset = question.find(fragment)
        occurrences = [(offset + match.start(), offset + match.end())
                       for match in re.finditer(re.escape(target), fragment)] if offset >= 0 and target else []
        # Source windows can differ while citing the same original occurrence.
        # "another" must use its original antecedent, not the previous row's result.
        identity = ((occurrences[0] if len(occurrences) == 1 else (fragment, target)),
                    item.get('owner_id', ''))
        if identity in references:
            key = references[identity]
            reason = '' if item['device_id'].upper() == key else '同一处设备指代对应多个编号，请明确目标。'
        else:
            key, reason = bind_target(item, request.query, devices, profile, previous=group or previous,
                                      conversation_context=request.conversation_context)
        if reason:
            return {}, reason
        references[identity] = key
        bindings[id(item)] = key
        group.add(key)
    return bindings, ''


def factual_plan_queries(understanding, request, snapshot, devices, profile, *, bindings=None):
    results = []
    if bindings is None:
        bindings, reason = _bind_plan_targets(understanding, request, devices, profile)
        if reason:
            return [], reason
    for item in (understanding.queries or []):
        if id(item) not in bindings:
            continue
        key = bindings[id(item)]
        if 'action' in item:
            continue
        device = next(device for device in devices if device['device_id'] == key)
        fields = ('device_id', 'display_name', 'device_type', 'state', 'runtime_facts')
        entry = {name: deepcopy(device.get(name)) for name in fields}
        if item['query_kind'] == 'device_capability':
            entry['actions'] = list(device.get('actions', {}))
        result = {'query_kind': item['query_kind'], 'source_query': item['source_text'], 'devices': [entry], 'requested_fields': item.get('requested_fields', [])}
        if item['query_kind'] == 'device_readiness':
            from .device_readiness import evaluate_device_readiness
            result['readiness'] = evaluate_device_readiness(device, item['requested_action'], devices=devices, profile=profile)
        results.append(result)
    return results, ''


def identity_resolution(pipeline, request, understanding):
    """Give the semantic reviewer the actual scene's verified identity evidence."""
    from .simulation_access import default_session, view_snapshot
    runtime = simulation_runtime(pipeline)
    sid = request.parameters.get('simulation_session_id')
    snapshot = view_snapshot(pipeline, request, runtime.snapshot(sid) if sid else default_session(pipeline))
    devices = [runtime.catalog.devices[row['device_id']] for row in snapshot['devices']]
    bindings, reason = _bind_plan_targets(understanding, request, devices,
                                         runtime.catalog.scenarios.get(snapshot.get('scenario_id'), {}))
    if reason:
        return {'status': 'unresolved', 'reason': reason, 'items': []}
    return {'status': 'verified', 'items': [
        {'device_id': bindings[id(row)], 'target_text': row['target_text'],
         'source_text': row['source_text'], 'owner_id': row.get('owner_id', ''),
         'same_type_candidates': [device['device_id'] for device in devices if device['device_type']
                                  == runtime.catalog.devices[bindings[id(row)]]['device_type']]}
        for row in [*understanding.operations, *understanding.queries] if id(row) in bindings]}


def factual_answer(results):
    from .simulation_query import FIELD_NAMES, ACTION_NAMES, _readiness_state_summary
    lines = []
    for item in results:
        for device in item.get('devices', []):
            name = device.get('display_name') or device['device_id']
            if item['query_kind'] == 'device_capability':
                lines.append(name + '可用操作：' + '、'.join(ACTION_NAMES.get(a, a) for a in device.get('actions', [])))
            elif item['query_kind'] == 'device_readiness':
                readiness = item['readiness']
                lines.append(name + '前置条件：' + {'ready':'已满足','blocked':'不满足','unknown':'待核验'}[readiness['status']])
                lines.append(_readiness_state_summary(device.get('state')))
                lines.extend(check.get('reason', '') for check in readiness.get('checks', []))
            else:
                values = {**device.get('state', {}), **device.get('runtime_facts', {})}
                requested = item.get('requested_fields') or list(values)
                lines.append(name + '：' + '；'.join(f'{FIELD_NAMES.get(key, key)}：{values[key]}' for key in requested if key in values))
    return '\n'.join(lines)


def validate_operation_rows(pipeline, request, snapshot, devices, profile, understanding, *, allow_restrictions=False):
    """Validate bindings and parameters without issuing server-owned commands.

    Restriction compilation is a separate server responsibility. Enabling it here
    retains each condition/order for that compiler, never grants execution.
    """
    rows = understanding.operations
    def blocked(reason):
        return [], [], reason
    error = request_controls_error(understanding, request.query)
    if error:
        return blocked(error)
    if analysis_only_requested(understanding):
        return blocked('本次请求仅限分析，不生成操作指令或计划预览。')
    if not rows:
        return blocked('未识别到明确操作，请说明设备和所需动作。')
    from .operation_review import order_evidence_error
    provenance_error = order_evidence_error(rows, request.query)
    if provenance_error:
        return blocked(provenance_error)
    orders = [item.get('order') for item in rows]
    feedback_sequence = (allow_restrictions and 2 <= len(rows) <= 8
        and all(item.get('negated') is False for item in rows)
        and all(type(value) is int for value in orders)
        and sorted(orders) == list(range(1, len(rows) + 1)))
    runtime = simulation_runtime(pipeline)
    condition_guard = False
    cited = understanding.clause_context
    if cited and (snapshot['session_id'] != cited['session_id'] or snapshot['version'] != cited['snapshot_version']
                  or runtime._catalog_version() != cited['catalog_version']):
        return blocked('条款分析期间设备状态或配置已变化，请重新分析。')
    if allow_restrictions and any(item.get('conditions') for item in rows):
        from ..instruction_engine.operation_conditions import compile_conditions
        try:
            for item in rows:
                compile_conditions(item.get('conditions', []), runtime.catalog.devices.get(item['device_id'], {}))
        except (ValueError, TypeError) as exc:
            return blocked(f'执行条件无法安全编译：{exc}')
        condition_guard = all(item.get('negated') is False for item in rows)
    from ..decomposition.intent_classifier import IntentClassifier
    online = understanding.source == 'model_api'
    from .context_facts import context_error, background_only, describes_observation
    context_reason = context_error(understanding, request.query, devices)
    if context_reason:
        return blocked(context_reason)
    reason = ('用户否定或取消操作，只保留回答，不生成操作预览'
              if not online and not (feedback_sequence or condition_guard) and IntentClassifier.action_is_negated(request.query) else '') if allow_restrictions else ('' if online else action_request_restriction(request.query))
    if not online and not allow_restrictions and not reason and (understanding.scenario.get('operating_condition') and not background_only(understanding)
            or re.search(r'假如|假设|仅在|前提|一旦|除非|否则|直到|先.+(?:再|然后)', request.query)):
        reason = '请求带有执行条件或顺序要求，当前不能编排，请拆分后逐步核对。'
    if reason:
        return blocked(reason)
    if not online and allow_restrictions and understanding.scenario.get('operating_condition') and not background_only(understanding) and not any(item['conditions'] for item in rows):
        return blocked('整句运行前提未保留到逐项执行条件，不能仅凭顺序支持生成预览。')
    if len(rows) > 8:
        return blocked('一次最多预览8条明确操作，请分批提交。')
    for prohibition in understanding.prohibitions:
        key, error = bind_target(prohibition, request.query, devices, profile, conversation_context=request.conversation_context)
        if error:
            return blocked(error)
        if any(row['device_id'] == key and row['action'] == prohibition['action'] for row in rows):
            return blocked('同一设备动作同时被要求和禁止，请明确所需操作。')
    previews, previous = [], None
    reason = plan_coverage(understanding, request.query, devices, profile)
    if reason:
        return blocked(reason)
    bindings, reason = _bind_plan_targets(understanding, request, devices, profile)
    if reason:
        return blocked(reason)
    factual_results, reason = factual_plan_queries(understanding, request, snapshot, devices, profile, bindings=bindings)
    if reason:
        return blocked(reason)
    for item in rows:
        if item['negated'] or not allow_restrictions and (item['conditions'] or item['order'] is not None):
            return blocked('操作包含否定、执行条件或先后要求，当前不生成省略限制的预览。')
        if (not online or understanding.intent != 'instruction') and IntentClassifier().classify(item['source_text'], 'instruction', [item['action']], query_kind='operation',
                                       feedback_sequence=feedback_sequence, condition_guard=condition_guard).intent != 'instruction':
            return blocked('原文为疑问或咨询表达，未明确要求执行操作。')
        device_id = bindings[id(item)]
        available = runtime.catalog.devices[device_id]['actions']
        action = item['action']
        unsupported = not action or action not in available
        supplied_action = request.parameters.get('action')
        if supplied_action and supplied_action != action:
            return blocked('业务动作参数与正文理解不一致，请明确所需操作；未覆盖正文动作。')
        if len(rows) > 1 and request.parameters.get('action_parameters'):
            return blocked('多条操作不能共用动作参数，请把各项目标写入对应正文。')
        template = available.get(action, {})
        parameters = item['parameters']
        supplied = request.parameters.get('action_parameters', {})
        if not isinstance(supplied, dict) or any(key in parameters and parameters[key] != value for key, value in supplied.items()):
            return blocked('正文目标值与业务参数不一致，请核对。')
        parameters = {**parameters, **supplied}
        from .mixed_operation_preview import _assignment_scope
        for constraint in understanding.constraints:
            if describes_observation(constraint, understanding):
                continue
            if not any(constraint.get(field) not in (None, '') for field in ('operator', 'value', 'condition')):
                continue
            if _assignment_scope(constraint, request.query, devices):
                continue
            comparison = constraint.get('operator', '')
            comparison = '==' if comparison == '=' else comparison
            expression = f"{constraint.get('parameter', '')} {comparison} {constraint.get('value', '')}{constraint.get('unit', '')}"
            unit = constraint.get('unit')
            if unit and all(runtime.catalog.devices[op['device_id']].get('fact_units', {}).get(
                    constraint.get('parameter')) == unit for op in rows):
                expression = f"{constraint.get('parameter', '')} {comparison} {constraint.get('value', '')}"
            scope = constraint.get('condition') or ''
            scope_targets = _explicit_targets(scope, devices, profile) if isinstance(scope, str) else set()
            retained = allow_restrictions and any(_compact(expression) == _compact(condition)
                and (not scope or isinstance(scope, str)
                     and (scope_targets == {operation['device_id']} if scope_targets
                          else _compact(scope) in _compact(operation['source_text'])))
                for operation in rows for condition in operation['conditions'])
            if not retained:
                return blocked('整句包含未保留到执行校验的附加条件，未生成无条件预览。')
        scoped = {'actions': [action], 'constraints': [], 'scenario': {}, 'parameter_evidence': item.get('parameter_evidence', []), 'model_parameters': item['parameters'], 'business_parameters': supplied}
        configured_parameter = template.get('configured_parameter_fact') if cited else None
        if configured_parameter:
            device = next(device for device in devices if device['device_id'] == device_id)
            value = device.get('runtime_facts', {}).get(configured_parameter)
            if value is not None:
                scoped['configured_parameters'] = {template['parameter']: value}
        inferred, reason = resolve_action_parameters(item['source_text'], template, item['parameters'], scoped)
        if (template.get('parameter') in item['parameters'] and template['parameter'] not in inferred and not reason
                and template['parameter'] not in supplied):
            return blocked('模型动作参数缺少原文目标值证据，请明确数值和单位。')
        if template.get('parameter') in supplied and not item.get('parameter_evidence'):
            inferred.pop(template['parameter'], None)
        parameters, reason = resolve_action_parameters(item['source_text'], template, parameters, scoped)
        if reason:
            return blocked(reason)
        parameter_sources = []
        parameter = template.get('parameter')
        if parameter in inferred:
            parameter_sources.append({'origin': 'device_configuration' if configured_parameter and not item.get('parameter_evidence') else 'question', 'parameter': parameter,
                'source_text': item['source_text'], 'value': inferred[parameter], 'unit': template.get('unit', '')})
        if parameter in supplied:
            parameter_sources.append({'origin': 'business_parameters', 'parameter': parameter,
                'value': supplied[parameter], 'unit': template.get('unit', '')})
        previews.append({'device_id': device_id, 'display_name': runtime.catalog.devices[device_id]['display_name'],
            'protocol': runtime.catalog.devices[device_id]['protocol'], 'action': action,
            'action_name': template.get('display_name', action), 'parameter_unit': template.get('unit', ''),
            'parameters': parameters, 'parameter_sources': parameter_sources,
            'source_query': item['source_text'], 'scoped_query': item['source_text'],
            'decomposition': understanding.to_dict(), 'semantic_operation': deepcopy(item), 'unsupported': unsupported})
        previous = device_id
    supplied_ids = request.parameters.get('device_ids') or ([request.parameters['device_id']] if request.parameters.get('device_id') else [])
    if supplied_ids and (not isinstance(supplied_ids, list) or any(not isinstance(value, str) for value in supplied_ids)
            or {value.upper() for value in supplied_ids} != {row['device_id'] for row in previews}):
        return blocked('业务参数设备与正文涉及多台设备或目标不一致，请核对；未增加或覆盖设备。')
    from .mixed_operation_preview import _conflict
    # Sequential changes of one device are validated by the plan compiler.
    if not allow_restrictions or not any(item['order'] is not None for item in rows):
        previews, reason = _conflict(previews, runtime)
    else:
        reason = ''
    if reason:
        return blocked(reason)
    return previews, factual_results, ''


def operation_previews(pipeline, request, snapshot, devices, profile, understanding):
    base = {'simulation_factual': True, 'simulation_session_id': snapshot['session_id'],
            'context': {'scenario': snapshot['scenario_id']}, 'candidate_instruction': None,
            'devices': [], 'dispatch_allowed': False, 'semantic_plan': True}
    previews, factual_results, reason = validate_operation_rows(pipeline, request, snapshot, devices, profile, understanding)
    if reason:
        return clarification(base, reason)
    runtime = simulation_runtime(pipeline)
    # All semantic checks finish before issuing any server-owned command IDs.
    for row in previews:
        row['preview'] = ({'status': 'blocked', 'candidate': None, 'command_id': None,
            'simulation_execution_allowed': False, 'explanation': '该设备不支持所请求的动作。'}
            if row.pop('unsupported') else runtime.preview(snapshot['session_id'], row['device_id'], row['action'], row['parameters'],
                expected_version=snapshot['version'], parameter_sources=row['parameter_sources'],
                evidence=(understanding.clause_context or {}).get('evidence', [])))
    ids = {row['device_id'] for row in previews}
    base['devices'] = [{key: deepcopy(device.get(key)) for key in
        ('device_id', 'display_name', 'device_type', 'protocol', 'state', 'runtime_facts')}
        for device in devices if device['device_id'] in ids]
    count = sum(row['preview']['status'] == 'generated' for row in previews)
    if len(previews) == 1:
        base['simulation_preview'] = previews[0]['preview']
        base['candidate_instruction'] = previews[0]['preview']['candidate']
        base['semantic_operation'] = previews[0]['semantic_operation']
    else:
        base['simulation_batch'] = {'status': 'generated' if count == len(previews) else 'partial' if count else 'blocked',
            'items': previews, 'generated_count': count, 'blocked_count': len(previews) - count,
            'device_count': len(ids), 'execution_mode': 'individual_confirmation', 'simulation_only': True}
    base['answer'] = {'text': (f'已识别{len(ids)}台设备、{len(previews)}条操作，{count}条可预览；尚未执行。' if count else '\n'.join((row.get('display_name') or row['device_id']) + '：' + row['preview'].get('explanation', '条件未通过') for row in previews))}
    if factual_results:
        import json
        base['query_results'] = factual_results
        base['answer']['text'] += '\n' + factual_answer(factual_results)
    return ('generated' if count else 'uncertain'), base, [], []
