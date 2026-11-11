"""Independent, same-action previews; execution retains the existing runtime gates."""
import re

from .action_parameters import PARAMETER_ALIASES, resolve_action_parameters
from .action_request import action_request_restriction


def batch_restriction(query, parameters, selected):
    if parameters.get('device_id'):
        return '业务参数与正文涉及多台设备，请核对目标，不生成操作预览。'
    if re.search(r'先|然后|随后|再|依次|顺序|逐个', query):
        return '暂不生成有先后依赖的多设备指令，请拆分并逐步核对。'
    # An unqualified type name must not silently turn into a mass command.
    mentions = re.findall(r'SIM-[A-Z0-9-]+|(?:主变(?:压器)?|变压器|冷却风机|风机|油泵|断路器|调压装置)\s*\d+', query, re.I)
    mentions += [d['display_name'] for d in selected if d.get('display_name') in query]
    if (len(set(mentions)) < 2 and len(parameters.get('device_ids', [])) < 2
            and not re.search(r'全部|所有|两台|各台', query)):
        return '当前涉及多台设备，请明确逐台名称、编号或说明操作全部设备。'
    return ''


def build_batch(runtime, snapshot, selected, request, understanding, model_actions, text_action):
    rows = []
    for device in selected:
        available = runtime.catalog.devices[device['device_id']]['actions']
        recognized = [a for a in model_actions if a in available]
        lexical = text_action(request.query, device)
        action = request.parameters.get('action') or (recognized[0] if len(recognized) == 1 else lexical)
        parameters = request.parameters.get('action_parameters', {})
        error = ''
        if not action or action not in available:
            error = '该设备不支持所请求的动作。'
        elif lexical and action != lexical:
            error = '正文动作与理解结果或业务参数不一致。'
        else:
            template = available[action]
            error = action_request_restriction(request.query, understanding, instruction_request=True,
                action_parameter=template.get('parameter'),
                action_parameter_aliases=PARAMETER_ALIASES.get(template.get('parameter'), ()))
            if not error:
                parameters, error = resolve_action_parameters(request.query, template, parameters, understanding)
        preview = ({'status': 'blocked', 'candidate': None, 'explanation': error,
                    'simulation_execution_allowed': False, 'command_id': None}
                   if error else runtime.preview(snapshot['session_id'], device['device_id'], action,
                       parameters, expected_version=snapshot['version']))
        rows.append({'device_id': device['device_id'], 'display_name': device['display_name'],
                     'action_name': available.get(action, {}).get('display_name', action or '无匹配动作'),
                     'parameter_unit': available.get(action, {}).get('unit', ''),
                     'protocol': device['protocol'], 'action': action, 'parameters': parameters,
                     'preview': preview})
    count = sum(row['preview']['status'] == 'generated' for row in rows)
    return {'status': 'generated' if count == len(rows) else 'partial' if count else 'blocked',
            'items': rows, 'generated_count': count, 'blocked_count': len(rows) - count,
            'execution_mode': 'individual_confirmation', 'simulation_only': True}
