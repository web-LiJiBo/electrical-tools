"""Compile a deliberately small, non-executable condition language."""
from copy import deepcopy
import json
import math
import operator
import re

_COMPARE = {'==': operator.eq, '!=': operator.ne, '<': operator.lt,
            '<=': operator.le, '>': operator.gt, '>=': operator.ge}
_EXPRESSION = re.compile(r'\s*(?:(state|runtime_facts)\.)?([A-Za-z][A-Za-z0-9_]*)\s*(==|!=|<=|>=|<|>)\s*(.+?)\s*')


def compile_conditions(conditions, profile):
    """Only configured fact names and finite JSON scalar comparisons are legal."""
    if type(conditions) is not list or len(conditions) > 16:
        raise ValueError('执行条件须为最多16项的比较表达式数组')
    compiled = []
    for expression in conditions:
        match = _EXPRESSION.fullmatch(expression) if type(expression) is str and len(expression) <= 200 else None
        if match is None:
            raise ValueError('执行条件无法安全编译，仅支持目录事实字段的单项比较')
        section, key, comparison, literal = match.groups()
        sections = {'state': profile.get('initial_state', {}), 'runtime_facts': profile.get('runtime_facts', {})}
        section = section or ('runtime_facts' if key in sections['runtime_facts'] else 'state')
        if key not in sections[section]:
            raise ValueError(f'执行条件字段未在设备模板白名单登记：{key}')
        try:
            value = json.loads(literal)
        except (ValueError, TypeError) as exc:
            raise ValueError('执行条件只支持有限数值、布尔或JSON字符串常量') from exc
        if (type(value) not in (int, float, bool, str)
                or type(value) is float and not math.isfinite(value)
                or comparison in ('<', '<=', '>', '>=') and type(value) not in (int, float)):
            raise ValueError('执行条件值或比较符不受支持')
        compiled.append({'expression': expression, 'section': section, 'field': key,
                         'operator': comparison, 'value': value})
    return compiled


def evaluate_conditions(compiled, entry):
    checks = []
    for condition in compiled:
        section = entry.get(condition['section'], {})
        actual, wanted = section.get(condition['field']), condition['value']
        compatible = (type(actual) is type(wanted) or type(actual) in (int, float) and type(wanted) in (int, float))
        valid = (condition['field'] in section and compatible
                 and (type(actual) is not float or math.isfinite(actual)))
        status = 'unknown'
        if valid:
            status = 'pass' if _COMPARE[condition['operator']](actual, wanted) else 'fail'
        checks.append({**deepcopy(condition), 'actual': deepcopy(actual), 'status': status,
                       'explanation': f"用户条件 {condition['expression']}："
                       + (f'当前值{actual!r}，' + ('满足' if status == 'pass' else '不满足')
                          if status != 'unknown' else '事实缺失或类型无效，无法确认')})
    return checks
