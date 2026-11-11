"""Bind explicitly separated requests independently through the existing pipeline."""
from copy import deepcopy
import re

from ..contracts import AnalysisRequest
from .action_request import action_request_restriction
from .action_parameters import matches_action_parameter, resolve_action_parameters


_ACTION_START = r'请|将|把|启动|开启|停止|停机|分闸|合闸|调整|调节|设置|设定|发出'
_SEPARATOR = re.compile(r'[，；;。]|(?<!\d),(?!\d)|同时|并且|(?:并|和|及)(?=(?:' + _ACTION_START + '))')
_INHERITED_ASSIGNMENT = re.compile(
    r'[请将把\s]*(?:调整|调节|设置|设定)?(?:其|它|该设备)?的?(?:目标)?'
    r'(?:有功功率|无功功率|有功|无功|输出电压|电压|功率上限|功率限制|档位|调压档位)'
    r'(?:设为|设置为|设定为|调整为|调到|调至|调整到|至|到|为)\s*'
    r'[+\-−]?(?:\d[\d,.]*|\.\d+)(?:[eE][+\-]?\d+)?\s*'
    r'(?:kW|MW|W|kvar|Mvar|V|kV|千瓦|兆瓦|伏特|伏|档)\s*', re.I)


def _explicit_target(text, devices):
    if re.search(r'SIM-[A-Z0-9-]+|(?:主变|变压器|风机|油泵|断路器|隔离开关|接地开关|调压装置)\s*\d+', text, re.I):
        return True
    return any(alias in text for d in devices
               for alias in [d.get('display_name', ''), *d.get('aliases', [])] if alias)


def _assignment_scope(constraint, query, devices):
    """Only an exact, actually stated catalog identity can be a target label."""
    if constraint.get('operator') not in ('=', '=='):
        return False
    condition = constraint.get('condition')
    if not isinstance(constraint.get('parameter'), str) or condition not in (None, '') and not isinstance(condition, str):
        return False
    candidates = devices if not condition else [device for device in devices
        if isinstance(condition, str) and condition.casefold() in {alias.casefold() for alias in
            [device['device_id'], device.get('display_name', ''), *device.get('aliases', [])] if alias}]
    if not any(matches_action_parameter(constraint.get('parameter'), template.get('parameter'))
               for device in candidates for template in device.get('actions', {}).values()):
        return False
    if not condition:
        return True
    if not isinstance(condition, str) or condition not in query:
        return False
    return condition.casefold() in {alias.casefold() for device in devices
        for alias in [device['device_id'], device.get('display_name', ''), *device.get('aliases', [])] if alias}


def _conflict(rows, runtime):
    effects, result = {}, []
    for row in rows:
        template = runtime.catalog.devices[row['device_id']]['actions'].get(row['action'], {})
        changes = template.get('simulation_effects', {})
        fields = {(section, field) for section in ('state', 'runtime_facts')
                  for field in changes.get(section, {})}
        fields.add(('action', row['action']))
        owned = effects.setdefault(row['device_id'], set())
        if fields & owned:
            return [], '同一设备存在重复、相互冲突或覆盖同一状态的操作，请明确一个目标或拆分为顺序操作。'
        owned.update(fields)
        result.append(row)
    return result, ''


def answer_mixed_operations(pipeline, request, snapshot, devices, understanding, intent):
    if understanding is None or understanding.scenario.get('query_kind') != 'operation' or getattr(intent, 'intent', None) != 'instruction':
        return None
    fragments = [part.strip() for part in _SEPARATOR.split(request.query) if part.strip()]
    if len(fragments) < 2:
        return None
    base = {'simulation_factual': True, 'simulation_session_id': snapshot['session_id'],
            'context': {'scenario': snapshot['scenario_id']}, 'candidate_instruction': None,
            'devices': [], 'dispatch_allowed': False}
    def blocked(reason, *, model_failed=False):
        data = {**base, 'answer': {'text': reason}, 'control_block_reason': reason}
        if model_failed:
            data['model_understanding'] = {'status': 'failed', 'source': 'operation_fragment'}
        return ('partial' if model_failed else 'uncertain'), data, [], []
    reason = action_request_restriction(request.query, understanding)
    if not reason and re.search(r'假如|假设|仅在|前提|一旦|除非|否则|直到', request.query):
        reason = '请求带有假设或执行前提，未生成省略条件的多动作预览。'
    if not reason and re.search(r'先|然后|随后|再|依次|顺序|逐个', request.query):
        reason = '暂不生成有先后依赖的多动作指令，请拆分并逐步核对。'
    if not reason and (understanding.scenario.get('operating_condition')
            or any(not _assignment_scope(c, request.query, devices)
                   for c in understanding.constraints if any(c.get(k) not in (None,'') for k in ('operator','value','condition')))):
        reason = '整句包含附加条件，尚未编译到每条指令，未生成省略条件的预览。'
    if reason:
        return blocked(reason)
    if len(fragments) > 8:
        return blocked('一次最多处理8个明确子请求，请分批提交。')
    if request.parameters.get('action') or request.parameters.get('action_parameters'):
        return blocked('多动作请求不能共用一组动作参数，请把每条操作的目标值写在对应正文中。')
    runtime = pipeline.simulation_runtime
    rows, prior_targets = [], set()
    supplied_id = request.parameters.get('device_id')
    if supplied_id and isinstance(supplied_id, str):
        prior_targets = {supplied_id.upper()}
    for index, fragment in enumerate(fragments):
        scoped = fragment
        if not _explicit_target(fragment, devices):
            if len(prior_targets) != 1 or not _INHERITED_ASSIGNMENT.fullmatch(fragment):
                return blocked(f'第{index + 1}条未明确唯一设备，请写出完整设备名称；省略设备仅支持明确的参数赋值。')
            scoped = next(iter(prior_targets)) + '：' + fragment
        parameters = {key: deepcopy(value) for key, value in request.parameters.items()
                      if key not in ('device_id', 'device_ids', 'action', 'action_parameters')}
        parameters['simulation_session_id'] = snapshot['session_id']
        parameters['simulation_scenario_id'] = snapshot['scenario_id']
        child = pipeline.analyze(AnalysisRequest(scoped, scenario_hint=request.scenario_hint,
            parameters=parameters, target_protocol=request.target_protocol,
            conversation_context=deepcopy(request.conversation_context)))
        data = child.data
        if data.get('model_understanding', {}).get('status') == 'failed':
            return blocked(f'第{index + 1}条模型理解未完成，未生成不完整指令列表。', model_failed=True)
        if (not data.get('simulation_factual') or data.get('decomposition', {}).get('scenario', {}).get('query_kind') != 'operation'
                or data.get('intent_classification', {}).get('intent') != 'instruction'):
            return blocked(f'第{index + 1}条不是可明确理解的模拟操作，请核对后单独提交。')
        if data.get('simulation_batch'):
            children = deepcopy(data['simulation_batch']['items'])
        elif data.get('devices'):
            if len(data['devices']) != 1:
                return blocked(f'第{index + 1}条目标不唯一，请明确设备。')
            device = data['devices'][0]
            preview = data.get('simulation_preview')
            actions = [a for a in data.get('decomposition', {}).get('actions', []) if a != 'inspect']
            action = (preview or {}).get('candidate', {}).get('payload', {}).get('requested_action') or (actions[0] if len(actions) == 1 else '')
            if not action:
                return blocked(f'第{index + 1}条动作不明确，请核对后单独提交。')
            template = runtime.catalog.devices[device['device_id']]['actions'].get(action, {})
            payload = (preview or {}).get('candidate', {}).get('payload', {})
            child_parameters, _ = resolve_action_parameters(scoped, template, {}, data.get('decomposition'))
            if template.get('parameter') and 'engineering_value' in payload:
                child_parameters[template['parameter']] = payload['engineering_value']
            children = [{'device_id': device['device_id'], 'display_name': device['display_name'],
                'protocol': device['protocol'], 'action': action, 'action_name': template.get('display_name', action),
                'parameter_unit': template.get('unit', ''),
                'parameters': child_parameters, 'preview': preview or {'status':'blocked', 'candidate':None,
                    'explanation':data.get('answer', {}).get('text', '本条未生成预览')}}]
        else:
            return blocked(f"第{index + 1}条：" + data.get('answer', {}).get('text', '未识别到有效设备。'))
        prior_targets = {row['device_id'] for row in children}
        for row in children:
            row.update(source_query=fragment, scoped_query=scoped,
                       decomposition=data.get('decomposition'), fragment_index=index)
        rows.extend(children)
    supplied = request.parameters.get('device_ids') or ([supplied_id] if supplied_id else [])
    if supplied and {str(v).upper() for v in supplied} != {row['device_id'] for row in rows}:
        return blocked('业务参数设备与逐条解析的目标不一致，请核对。')
    if (runtime.snapshot(snapshot['session_id'])['version'] != snapshot['version']
            or any(row['preview'].get('expected_version', snapshot['version']) != snapshot['version'] for row in rows)):
        return blocked('分析过程中设备状态已变化，请重新分析整组指令。')
    rows, reason = _conflict(rows, runtime)
    if reason:
        return blocked(reason)
    count = sum(row['preview']['status'] == 'generated' for row in rows)
    ids = {row['device_id'] for row in rows}
    base['devices'] = [{key: deepcopy(device.get(key)) for key in ('device_id','display_name','device_type','protocol','state','runtime_facts')}
                       for device in devices if device['device_id'] in ids]
    base['simulation_batch'] = {'status': 'generated' if count == len(rows) else 'partial' if count else 'blocked',
        'items': rows, 'generated_count': count, 'blocked_count': len(rows) - count,
        'device_count': len(ids), 'execution_mode':'individual_confirmation', 'simulation_only':True}
    base['answer'] = {'text': f'已为{len(ids)}台设备生成{len(rows)}条操作结果：{count}条可预览，{len(rows)-count}条被阻止。请逐条核对并模拟下发；尚未执行。'}
    return ('generated' if count else 'uncertain'), base, [], []
