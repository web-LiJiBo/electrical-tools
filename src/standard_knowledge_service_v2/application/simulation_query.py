"""Factual device queries and explicit previews do not need an action clause."""
from copy import deepcopy
import re

from .simulation_access import default_session, simulation_runtime

ACTION_NAMES = {'start': '启动', 'stop': '停止', 'trip': '分闸', 'open': '分闸',
                'close': '合闸', 'raise_tap': '升一档', 'lower_tap': '降一档',
                'raise': '升一档', 'lower': '降一档', 'set_tap': '设定档位',
                'alarm': '告警', 'reset': '复归', 'lockout': '闭锁'}
FIELD_NAMES = {'running': '运行中', 'position': '分合位置', 'operating_state': '运行状态',
               'winding_hotspot_rise_k': '绕组热点温升(K)', 'top_oil_rise_k': '顶层油温升(K)',
               'winding_average_rise_k': '绕组平均温升(K)', 'cooling_mode': '冷却方式',
               'current': '电流(A)', 'current_a': '电流(A)', 'tap_position': '档位',
               'fault': '故障', 'alarm_active': '告警', 'load_rate': '负载率(%)'}


def _targets(query, parameters, devices, profile):
    explicit = re.findall(r'SIM-[A-Z0-9-]+', query, re.I)
    explicit += [parameters['device_id']] if parameters.get('device_id') else []
    explicit += parameters.get('device_ids', []) if isinstance(parameters.get('device_ids'), list) else []
    if explicit:
        if not all(isinstance(v, str) for v in explicit):
            raise ValueError('模拟设备编号须为文本')
        selected = list(dict.fromkeys(v.upper() for v in explicit))
    else:
        selected = []
        for device in devices:
            aliases = [device.get('display_name', ''), *device.get('aliases', [])]
            if any(alias and re.search(re.escape(alias) + r'(?!\d)', query) for alias in aliases):
                selected.append(device['device_id'])
    # Resolve relational names through scenario roles, e.g. 主变1的冷却风机.
    role_terms = {'cooling_fan': r'风机|冷却风扇', 'oil_pump': r'油泵',
                  'breaker': r'断路器', 'disconnector': r'隔离开关',
                  'earthing_switch': r'接地开关', 'tap_changer': r'调压|档位'}
    groups = profile.get('groups', [])
    for group in groups.values() if isinstance(groups, dict) else groups:
        transformer = group.get('transformer')
        if transformer in selected:
            roles = [role for role, pattern in role_terms.items() if re.search(pattern, query)]
            if roles:
                selected = [v for v in selected if v != transformer]
                selected.extend(group[role] for role in roles if group.get(role))
    if not selected:
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


def answer_simulation_query(pipeline, request):
    if request.parameters.get('simulation_mode') is not True:
        return None
    query = request.query
    # Standard and provenance questions continue through the full knowledge path.
    if re.search(r'标准|条款|规范|规程|依据|要求|符合|合规|限值|规定', query):
        return None
    capability = bool(re.search(r'哪些(?:操作|动作|指令)|(?:支持|能做|可以做|可用).*?(?:操作|动作|指令)|操作能力', query))
    factual = bool(re.search(r'状态|运行数据|测量|温升|温度|电流|告警|档位|位置|正常|异常|比较|对比', query))
    operation = bool(re.search(r'启动|停止|停机|分闸|合闸|跳闸|升.*档|降.*档|设定.*档|调到.*档', query))
    if not (capability or factual or operation):
        return None
    runtime = simulation_runtime(pipeline)
    sid = request.parameters.get('simulation_session_id')
    try:
        snapshot = runtime.snapshot(sid) if sid else default_session(pipeline)
    except (KeyError, ValueError):
        return 'uncertain', {'answer': {'text': '模拟会话不存在，请重新选择或创建会话。'},
                             'candidate_instruction': None, 'simulation_factual': True}, [], []
    profile = runtime.catalog.scenarios.get(snapshot.get('scenario_id'), {})
    devices = snapshot['devices']
    # Read aliases/capabilities from the catalog, not from a model's invented IDs.
    devices = [{**deepcopy(runtime.catalog.devices[d['device_id']]), **d} for d in devices]
    ids = _targets(query, request.parameters, devices, profile)
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
    if operation and not capability and not re.search(r'不要|不执行|不启动|不停止|取消|如何|怎么|为什么|能否|是否|可以|能不能', query):
        if len(selected) != 1:
            base['answer'] = {'text': '当前涉及多台设备，请指定唯一的模拟操作目标；已列出相关设备状态。'}
            return 'uncertain', base, [], []
        device = selected[0]
        action = request.parameters.get('action') or _action(query, device)
        if not action:
            base['answer'] = {'text': '该设备未配置所请求的操作，请查看其通用模板中的可用动作。'}
            return 'uncertain', base, [], []
        parameters = request.parameters.get('action_parameters', {})
        if action == 'set_tap' and not parameters:
            number = re.search(r'(\d+)\s*档', query)
            if number:
                template = runtime.catalog.devices[device['device_id']]['actions'][action]
                parameters = {template.get('parameter', 'tap_position'): int(number[1])}
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
        _, assessment, evidence = assess_real_clause(pipeline, request, snapshot=snapshot, device_id=selected[0]['device_id'])
        if assessment.get('real_clause_evidence'):
            base.update({k: v for k, v in assessment.items() if k not in ('answer', 'context', 'candidate_instruction', 'device_assessment')})
            base['device_assessment'] = assessment['device_assessment']
            base['answer']['text'] += '\n' + assessment['answer']['text']
            return 'answered', base, evidence, []
    return 'answered', base, [], []
