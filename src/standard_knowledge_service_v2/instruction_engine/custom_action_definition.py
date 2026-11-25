"""Compile explicitly configured assignment actions; no name-based behavior."""
import re


def compile_definition(item, spec, literal):
    label = item['display_name']
    if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80 or any(ord(c)<32 for c in label):
        raise ValueError('请填写有效的动作名称。')
    if spec['type'] not in ('boolean', 'integer', 'number'):
        raise ValueError('动作结果须为布尔、整数或数值字段。')
    mode = item['value_source']
    settings = dict(custom_action=True, value_source=mode, result_field=spec['key'], display_name=label.strip())
    if mode == 'fixed':
        if item['parameter'] or item['minimum'] is not None or item['maximum'] is not None:
            raise ValueError('固定值动作不填写参数名或目标范围。')
        if not literal(item['value'], spec['type']):
            raise ValueError('固定值类型必须与结果字段一致，布尔值不能用0或1替代。')
        return {**settings, 'value': item['value']}, item['value']
    if mode != 'parameter':
        raise ValueError('请选择固定值或参数值来源。')
    if spec['type'] not in ('integer', 'number') or item['value'] is not None:
        raise ValueError('参数写入需使用数值或整数字段，不填写固定值。')
    parameter = item['parameter']
    if not isinstance(parameter, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', parameter) or parameter in ('true','false'):
        raise ValueError('参数名须为小写字母开头的英文、数字或下划线，最多40字符。')
    low, high = item['minimum'], item['maximum']
    if not literal(low, spec['type']) or not literal(high, spec['type']) or low >= high:
        raise ValueError('参数范围类型须与结果字段一致，最小值须小于最大值。')
    return {**settings, 'parameter': parameter, 'parameter_type': spec['type'],
            'parameter_label': spec['label'], 'minimum': low, 'maximum': high}, {'from_parameter': parameter}
