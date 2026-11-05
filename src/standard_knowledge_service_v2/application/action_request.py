"""Keep user restrictions intact at every simulation-preview entry point."""
import re

from ..decomposition.intent_classifier import IntentClassifier
from .action_parameters import matches_action_parameter


def action_request_restriction(query, understanding=None, *, instruction_request=False,
                               action_parameter=None, action_parameter_aliases=()):
    if IntentClassifier.action_is_negated(query):
        return '用户否定或取消操作，只保留回答，不生成操作预览'
    if re.search(r'如果|只有|才(?:能|可|允许|执行|启动|开启|停止|分闸|合闸|进行|操作|回降)|(?:当|若).+(?:时|则|就)|(?:待|等).+(?:后|再)|(?:确认|批准|审核|许可)后', query):
        return '条件式操作尚未编译为执行前校验，未生成无条件预览；请明确条件处理方式'
    data = understanding.to_dict() if hasattr(understanding, 'to_dict') else (understanding or {})
    if not instruction_request:
        return ''
    actions = {a for a in data.get('actions', []) if a and a != 'inspect'}
    if len(actions) > 1:
        return '当前只支持明确的单项操作，请拆分多步骤请求'
    for constraint in data.get('constraints', []):
        argument = (constraint.get('operator') in ('=', '==') and not constraint.get('condition')
            and action_parameter and (constraint.get('parameter') == action_parameter
                or action_parameter == 'tap_position' and matches_action_parameter(constraint.get('parameter'), action_parameter)
                or constraint.get('parameter') in action_parameter_aliases))
        if not argument and any(constraint.get(k) not in (None, '') for k in ('operator', 'value', 'condition')):
            return '模型识别到附加条件，当前单动作入口尚未编译该条件，未生成无条件预览'
    condition = data.get('scenario', {}).get('operating_condition', '')
    if isinstance(condition, str) and condition.strip():
        return '模型识别到请求中的运行条件，尚未编译为执行前校验，未生成无条件预览'
    return ''
