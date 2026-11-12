"""Factual device queries and explicit previews do not need an action clause."""
from copy import deepcopy
import re

from .simulation_access import default_session, simulation_runtime, view_snapshot
from .action_request import action_request_restriction
from .action_parameters import PARAMETER_ALIASES, resolve_action_parameters

ACTION_NAMES = {'start': '启动', 'stop': '停止', 'trip': '分闸', 'open': '分闸',
                'close': '合闸', 'raise_tap': '升一档', 'lower_tap': '降一档',
                'raise': '升一档', 'lower': '降一档', 'set_tap': '设定档位',
                'alarm': '告警', 'reset': '复归', 'lockout': '闭锁'}
FIELD_NAMES = {'running': '运行中', 'position': '分合位置', 'operating_state': '运行状态',
               'winding_hotspot_rise_k': '绕组热点温升(K)', 'top_oil_rise_k': '顶层油温升(K)',
               'winding_average_rise_k': '绕组平均温升(K)', 'cooling_mode': '冷却方式',
               'current': '电流(A)', 'current_a': '电流(A)', 'tap_position': '档位',
               'fault': '故障', 'alarm_active': '告警', 'load_rate': '负载率(%)'}


def _targets(query, parameters, devices, profile, *, entity_names=()):
    # Distribute a shared accessory over explicitly coordinated owners.
    query = re.sub(r'(主变\s*\d+)\s*(?:和|与|及|、)\s*(主变\s*\d+)的(冷却风机|油泵|调压装置)',
                   lambda m: m.group(0) if re.sub(r'\s+', '', m[1]) == re.sub(r'\s+', '', m[2])
                   else f'{m[1]}的{m[3]}和{m[2]}的{m[3]}', query)
    named = re.findall(r'(?:模拟)?(?:主变(?:压器)?|变压器|(?:冷却)?风机|油泵|断路器|隔离开关|接地开关|(?:有载)?调压装置)\s*\d+', query)
    known_names = {re.sub(r'\s+', '', alias).casefold() for device in devices
                   for alias in [device.get('display_name', ''), *device.get('aliases', [])] if alias}
    unknown_names = [name for name in named if re.sub(r'\s+', '', name).casefold() not in known_names]
    parameter_targets = ([parameters['device_id']] if parameters.get('device_id') else [])
    parameter_targets += parameters.get('device_ids', []) if isinstance(parameters.get('device_ids'), list) else []
    query_targets = re.findall(r'SIM-[A-Z0-9-]+', query, re.I)
    explicit = [*parameter_targets, *query_targets]
    if explicit and not all(isinstance(v, str) for v in explicit):
            raise ValueError('模拟设备编号须为文本')
    selected = list(dict.fromkeys(v.upper() for v in explicit))
    if unknown_names:
        return list(dict.fromkeys([*selected, *unknown_names]))
    # Business parameters and natural-language targets are independent claims.
    # Resolve both and keep their union so a conflict can never silently select
    # the parameter target over the user's sentence.
    full_names = [(device['device_id'], match.span()) for device in devices
                  if device.get('display_name')
                  for match in re.finditer(re.escape(device['display_name']) + r'(?!\d)', query)]
    for device in devices:
        aliases = [device.get('display_name', ''), *device.get('aliases', [])]
        # Resolve every explicit name, including mixed ID/name requests.
        if any(not any(owner != device['device_id'] and start <= match.start() and match.end() <= end
                       for owner, (start, end) in full_names)
               for alias in aliases if alias
               for match in re.finditer(re.escape(alias) + r'(?!\d)', query)):
            selected.append(device['device_id'])
    # Resolve ownership per mention, not per device: in "主变1和主变1的风机"
    # the first mention is an independent comparison target.
    role_terms = {'cooling_fan': r'(?:冷却)?风机|冷却风扇', 'oil_pump': r'油泵',
                  'breaker': r'断路器', 'disconnector': r'隔离开关',
                  'earthing_switch': r'接地开关', 'tap_changer': r'调压|档位'}
    groups = profile.get('groups', [])
    for group in groups.values() if isinstance(groups, dict) else groups:
        transformer = group.get('transformer')
        if transformer in selected:
            owner = next((d for d in devices if d['device_id'] == transformer), {})
            aliases = [transformer, owner.get('display_name', ''), *owner.get('aliases', [])]
            roles, independent = set(), False
            for alias in aliases:
                if not alias:
                    continue
                for match in re.finditer(re.escape(alias) + r'(?!\d)', query):
                    if any(other != transformer and start <= match.start() and match.end() <= end
                           for other, (start, end) in full_names):
                        continue
                    tail = query[match.end():]
                    possessive = {role for role, pattern in role_terms.items()
                                  if re.match(r'\s*(?:的)?\s*(?:' + pattern + ')', tail)}
                    coordinated = {role for role, pattern in role_terms.items()
                                   if re.match(r'\s*(?:以及|和|与|及|、)\s*(?:其|它的)\s*(?:' + pattern + ')', tail)}
                    roles.update(possessive | coordinated)
                    independent |= not possessive
            if roles:
                if not independent:
                    selected = [v for v in selected if v != transformer]
                selected.extend(group[role] for role in role_terms if role in roles and group.get(role))
    if not selected:
        if named:
            return list(dict.fromkeys(named))
        # Model-resolved follow-up references still have to match a catalog
        # identity/alias in the current view; no invented device is accepted.
        for name in entity_names:
            for device in devices:
                aliases = [device['device_id'], device.get('display_name', ''), *device.get('aliases', [])]
                if name.casefold() in {alias.casefold() for alias in aliases if alias}:
                    selected.append(device['device_id'])
        if selected:
            return list(dict.fromkeys(selected))
        kinds = {'cooling_fan': r'风机', 'oil_pump': r'油泵', 'transformer': r'主变|变压器',
                 'breaker': r'断路器', 'disconnector': r'隔离开关',
                 'earthing_switch': r'接地开关', 'tap_changer': r'调压装置'}
        for kind, pattern in kinds.items():
            if re.search(pattern, query):
                selected.extend(d['device_id'] for d in devices if d['device_type'] == kind)
    return list(dict.fromkeys(selected))


def _action(query, device):
    actions = device.get('actions', {})
    available = set(actions) if isinstance(actions, dict) else {
        a['action'] if isinstance(a, dict) else a for a in actions}
    patterns = [('raise', r'升(?:一)?档'), ('lower', r'降(?:一)?档'),
                ('raise_tap', r'升(?:一)?档'), ('lower_tap', r'降(?:一)?档'),
                ('set_tap', r'设定.*档|调(?:到|至)\s*\d+\s*档'),
                ('start', r'启动|开启|开动'), ('stop', r'停止|停机|关闭风机|关闭油泵'),
                ('trip', r'分闸|跳闸|断开'), ('open', r'分闸|分开|断开'), ('close', r'合闸|合上')]
    return next((a for a, pattern in patterns if a in available and re.search(pattern, query)), '')


def answer_simulation_query(pipeline, request, *, decomposed=None, intent=None):
    if request.parameters.get('simulation_mode') is not True:
        return None
    query = request.query
    kind = decomposed.scenario.get('query_kind') if decomposed else None
    # Standard and provenance questions continue through the full knowledge path.
    if not (decomposed and decomposed.operations) and (kind in ('standard_query', 'assessment', 'other') or re.search(r'标准|条款|规范|规程|依据|要求|符合|合规|限值|规定', query)):
        return None
    # The API's structured purpose drives routing. Legacy/offline decomposers
    # without that optional field retain their explicit compatibility path.
    capability = kind == 'device_capability' if kind else bool(re.search(r'哪些(?:操作|动作|指令)|(?:支持|能做|可以做|可用).*?(?:操作|动作|指令)|操作能力', query))
    factual = kind == 'device_status' if kind else bool(re.search(r'状态|数据|读数|测量|温升|温度|电流|告警|档位|位置|正常|异常|比较|对比', query))
    operation = kind == 'operation' if kind else bool(re.search(r'启动|开启|开动|停止|停机|关闭风机|关闭油泵|分闸|合闸|跳闸|升.*档|降.*档|设定.*档|调到.*档', query))
    if not (capability or factual or operation):
        return None
    runtime = simulation_runtime(pipeline)
    sid = request.parameters.get('simulation_session_id')
    try:
        snapshot = runtime.snapshot(sid) if sid else default_session(pipeline)
    except (KeyError, ValueError):
        return 'uncertain', {'answer': {'text': '模拟会话不存在，请重新选择或创建会话。'},
                             'candidate_instruction': None, 'simulation_factual': True}, [], []
    snapshot = view_snapshot(pipeline, request, snapshot)
    profile = runtime.catalog.scenarios.get(snapshot.get('scenario_id'), {})
    devices = snapshot['devices']
    # Read aliases/capabilities from the catalog, not from a model's invented IDs.
    devices = [{**deepcopy(runtime.catalog.devices[d['device_id']]), **d} for d in devices]
    names = [e['name'] for e in decomposed.entities if isinstance(e, dict) and isinstance(e.get('name'), str)] if decomposed else []
    semantic = decomposed is not None and decomposed.operations is not None and decomposed.queries is not None
    if semantic and (decomposed.operations or operation):
        from .semantic_operations import operation_previews
        return operation_previews(pipeline, request, snapshot, devices, profile, decomposed)
    if semantic:
        from .semantic_operations import bind_target, clarification
        ids = []
        for item in decomposed.queries:
            if item.get('query_kind') not in ('device_status', 'device_capability'):
                continue
            key, reason = bind_target(item, query, devices, profile, conversation_context=request.conversation_context)
            if reason:
                return clarification({'simulation_factual': True, 'candidate_instruction': None}, reason)
            ids.append(key)
        ids = list(dict.fromkeys(ids))
        if not ids:
            return clarification({'simulation_factual': True, 'candidate_instruction': None}, '请明确要查询的设备。')
    else:
        ids = _targets(query, request.parameters, devices, profile, entity_names=names)
    from .mixed_operation_preview import answer_mixed_operations
    mixed = None if semantic else answer_mixed_operations(pipeline, request, snapshot, devices, decomposed, intent)
    if mixed is not None:
        return mixed
    by_id = {d['device_id']: d for d in devices}
    unknown = [key for key in ids if key not in by_id]
    base = {'simulation_factual': True, 'simulation_session_id': snapshot['session_id'],
            'context': {'scenario': snapshot.get('scenario_id', 'general')},
            'candidate_instruction': None, 'devices': [],
            'fact_source': 'simulation_snapshot', 'dispatch_allowed': False}
    if unknown:
        base['answer'] = {'text': '该会话未登记以下设备：' + '、'.join(unknown) + '。请核对编号或创建包含该设备的会话。'}
        return 'uncertain', base, [], []
    if not ids:
        base['answer'] = {'text': '请指定要查询的模拟设备。当前会话支持：' + '、'.join(d.get('display_name', d['device_id']) for d in devices)}
        return 'uncertain', base, [], []
    selected = [by_id[key] for key in ids]
    base['devices'] = [{k: deepcopy(d.get(k)) for k in ('device_id', 'display_name', 'device_type', 'protocol', 'state', 'runtime_facts', 'points')}
                       for d in selected]
    model_actions = list(dict.fromkeys(a for a in (decomposed.actions if decomposed else []) if a != 'inspect'))
    restriction = action_request_restriction(query, decomposed)
    if operation and not capability and (restriction or len(model_actions) > 1):
        base['answer'] = {'text': restriction or '当前只支持明确的单项操作，请拆分多步骤请求。'}
        return 'uncertain', base, [], []
    authorized = intent.intent == 'instruction' if intent else not re.search(
        r'禁止|不应|不得|不要|不执行|不启动|不停止|取消|如何|怎么|为什么|能否|是否|可以|能不能|吗', query)
    if operation and not capability and authorized:
        if len(selected) != 1:
            from .multi_device_preview import batch_restriction, build_batch
            reason = batch_restriction(query, request.parameters, selected)
            supplied = request.parameters.get('device_ids')
            if supplied:
                stated = _targets(query, {}, devices, profile)
                if stated and set(stated) != set(supplied):
                    reason = '业务参数的设备列表与正文目标不一致，请核对目标。'
            if reason:
                base['answer'] = {'text': reason}
                return 'uncertain', base, [], []
            batch = build_batch(runtime, snapshot, selected, request, decomposed, model_actions, _action)
            base['simulation_batch'] = batch
            base['answer'] = {'text': f"已识别{len(selected)}台设备：{batch['generated_count']}条模拟指令可预览，"
                f"{batch['blocked_count']}条被阻止。请在“操作建议”中逐台核对并模拟下发；尚未执行。"}
            return ('generated' if batch['generated_count'] else 'uncertain'), base, [], []
        device = selected[0]
        available = runtime.catalog.devices[device['device_id']]['actions']
        understood = [a for a in model_actions if a in available]
        text_action = _action(query, device)
        action = request.parameters.get('action') or (understood[0] if len(understood) == 1 else text_action)
        if text_action and action != text_action:
            base['answer'] = {'text': '问题中的动作与理解结果或业务参数不一致，未生成预览，请明确所需操作。'}
            return 'uncertain', base, [], []
        if not isinstance(action, str) or not action or action not in available:
            base['answer'] = {'text': '该设备未配置所请求的操作，请查看其通用模板中的可用动作。'}
            return 'uncertain', base, [], []
        parameters = request.parameters.get('action_parameters', {})
        template = available[action]
        restriction = action_request_restriction(query, decomposed, instruction_request=True,
            action_parameter=template.get('parameter'),
            action_parameter_aliases=PARAMETER_ALIASES.get(template.get('parameter'), ()))
        if restriction:
            base['answer'] = {'text': restriction}
            return 'uncertain', base, [], []
        parameters, parameter_error = resolve_action_parameters(query, template, parameters, decomposed)
        if parameter_error:
            base['answer'] = {'text': parameter_error}
            return 'uncertain', base, [], []
        preview = runtime.preview(snapshot['session_id'], device['device_id'], action, parameters)
        base['simulation_preview'] = preview
        base['candidate_instruction'] = preview.get('candidate')
        base['answer'] = {'text': '已生成模拟操作预览，尚未执行。请在“操作建议”中核对后点击“模拟下发”。' if preview['status'] == 'generated'
                          else '模拟操作暂不可执行：' + str(preview.get('explanation', preview.get('candidate', {}).get('explanation', '条件不满足')))}
        return ('generated' if preview['status'] == 'generated' else 'uncertain'), base, [], []
    base['device_capabilities'] = []
    lines = []
    for device in selected:
        name = device.get('display_name') or device['device_id']
        state = device.get('state', {})
        facts = device.get('runtime_facts', {})
        fields = [f'{FIELD_NAMES.get(k, k)}：{v}' for k, v in {**state, **facts}.items()]
        lines.append(f'{name}（{device["device_id"]}）：' + '；'.join(fields))
        actions = runtime.catalog.devices[device['device_id']].get('actions', {})
        capabilities = [{'action': key, 'name': ACTION_NAMES.get(key, key),
                         'parameter': item.get('parameter'), 'unit': item.get('unit', ''),
                         'minimum': item.get('minimum'), 'maximum': item.get('maximum'),
                         'condition': item.get('condition', ''), 'template_ref': item.get('template_ref')}
                        for key, item in actions.items()]
        base['device_capabilities'].append({'device_id': device['device_id'], 'actions': capabilities})
        if capability or operation:
            lines.append('可用操作：' + ('、'.join(a['name'] for a in capabilities) or '本体仅提供状态和测量查询'))
    base['answer'] = {'text': '\n'.join(lines) + '\n以上为当前模拟状态；整体健康或标准符合性需结合适用依据判断。'}
    # Preserve source-based temperature assessment as optional evidence, never a fact gate.
    if len(selected) == 1 and selected[0]['device_type'] == 'transformer' and re.search(r'正常|异常|温升', query):
        from .real_clause_assessment import assess_real_clause
        _, assessment, evidence = assess_real_clause(pipeline, request, snapshot=snapshot, device_id=selected[0]['device_id'], decomposed=decomposed)
        if assessment.get('real_clause_evidence'):
            base.update({k: v for k, v in assessment.items() if k not in ('answer', 'context', 'candidate_instruction', 'device_assessment')})
            base['device_assessment'] = assessment['device_assessment']
            base['answer']['text'] += '\n' + assessment['answer']['text']
            return 'answered', base, evidence, []
    return 'answered', base, [], []
