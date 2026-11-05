"""Reconcile explicit target assignments in the selected template's units."""
from decimal import Decimal, InvalidOperation
import re


PARAMETER_ALIASES = {
    'tap_position': {'档位', '目标档位', '调压档位'},
    'power_kw': {'有功功率', '目标有功功率', '目标功率', '有功功率设定值'},
    'reactive_power_kvar': {'无功功率', '目标无功功率', '无功功率设定值'},
    'voltage_v': {'电压', '输出电压', '目标电压', '电压设定值'},
    'power_limit_kw': {'功率上限', '功率限制', '功率限值', '目标功率上限'},
    'target_power_mw': {'目标功率', '回降功率', '回降目标功率', '有功功率'},
}
# dimension, scale to base unit; independent active/reactive power dimensions.
UNITS = {
    'w': ('power', '1'), 'kw': ('power', '1000'),
    'MW': ('power', '1000000'), 'mW': ('power', '0.001'), 'mw': ('power', '0.001'),
    '瓦': ('power', '1'), '千瓦': ('power', '1000'), '兆瓦': ('power', '1000000'),
    'var': ('reactive', '1'), 'kvar': ('reactive', '1000'),
    'Mvar': ('reactive', '1000000'), 'mvar': ('reactive', '0.001'),
    '乏': ('reactive', '1'), '千乏': ('reactive', '1000'), '兆乏': ('reactive', '1000000'),
    'v': ('voltage', '1'), 'kv': ('voltage', '1000'),
    '伏': ('voltage', '1'), '伏特': ('voltage', '1'), '千伏': ('voltage', '1000'),
    '档': ('tap', '1'),
}
NUMBER = r'[+-]?(?:\d[\d,]*(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
SIGNS = str.maketrans({'−': '-', '－': '-', '＋': '+'})
VALUE_WITH_UNIT = re.compile(r'(?<![A-Za-z0-9_.,+-])(' + NUMBER
    + r')\s*([A-Za-z]+(?:\s*[/*^·]\s*[A-Za-z0-9+-]+)*|兆瓦|千瓦|瓦|兆乏|千乏|乏|千伏|伏特|伏|档)')


def matches_action_parameter(name, parameter):
    return bool(parameter) and name in {parameter, *PARAMETER_ALIASES.get(parameter, ())}


def _number(value):
    if isinstance(value, bool):
        raise ValueError('目标值必须是有限数值，不能是布尔值')
    text = str(value).strip().translate(SIGNS)
    if ',' in text:
        if not re.fullmatch(r'[+-]?\d{1,3}(?:,\d{3})+(?:\.\d*)?(?:[eE][+-]?\d+)?', text):
            raise ValueError('目标数值的千分位格式无效，请明确完整数值')
        text = text.replace(',', '')
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError('目标值必须是有限数值') from exc
    if not number.is_finite():
        raise ValueError('目标值必须是有限数值')
    return number


def _convert(value, unit, target_unit):
    number = _number(value)
    unit, target_unit = str(unit or '').strip(), target_unit.strip()
    if unit == target_unit:
        return number
    # Preserve SI prefix case: mW is a milliwatt, MW a megawatt.
    source = UNITS.get(unit) or UNITS.get(unit.lower())
    target = UNITS.get(target_unit) or UNITS.get(target_unit.lower())
    if not source or not target or source[0] != target[0]:
        raise ValueError('目标值单位缺失或与动作模板不兼容，请明确目标单位')
    return number * Decimal(source[1]) / Decimal(target[1])


def resolve_action_parameters(query, template, parameters, understanding=None):
    """Never pick one value when text, model and business parameters disagree."""
    if not isinstance(parameters, dict):
        return {}, '动作参数必须是字段字典'
    result = dict(parameters)
    parameter = template.get('parameter')
    if not parameter:
        return result, ''
    unit = str(template.get('unit', ''))
    data = understanding.to_dict() if hasattr(understanding, 'to_dict') else (understanding or {})
    try:
        stated = [_convert(match[1], match[2], unit) for match in VALUE_WITH_UNIT.finditer(query.translate(SIGNS))]
        for constraint in data.get('constraints', []):
            if (matches_action_parameter(constraint.get('parameter'), parameter)
                    and constraint.get('operator') in ('=', '==') and not constraint.get('condition')):
                # Tap models historically omit the unit on an unambiguous integer target.
                constraint_unit = constraint.get('unit') or ('档' if parameter == 'tap_position' else '')
                stated.append(_convert(constraint.get('value'), constraint_unit, unit))
        if len(set(stated)) > 1:
            return {}, '正文与模型理解包含不同目标值，未生成操作预览；请明确一个目标值'
        if parameter in result:
            supplied = _number(result[parameter])
            if stated and supplied != stated[0]:
                return {}, '问题中的目标值与业务参数不一致，未生成操作预览；请保留一个明确值。'
            # Retain the template's strict input type checks for supplied parameters.
            return result, ''
        if stated:
            value = stated[0]
            if template.get('parameter_type') == 'integer' and value != value.to_integral_value():
                return {}, '档位必须为整数，未截取或修改输入值；请重新指定档位。'
            result[parameter] = int(value) if value == value.to_integral_value() else float(value)
        return result, ''
    except (ValueError, InvalidOperation) as exc:
        return {}, str(exc)
