"""Convert the local manual form into a validated simulator-only profile."""

import math
import re

SCENARIOS = {
    'power_grid_operation': '电网调度运行',
    'renewable_grid_integration': '新能源并网',
    'substation_maintenance': '变电站设备运维',
}
DEVICE_TYPES = {
    'dispatch_unit': '调度机组', 'reactive_compensator': '无功补偿装置',
    'cooling_fan': '冷却风机',
}
ACTIONS = {
    'dispatch_unit': {'adjust_active_power': '调整有功出力', 'limit_power': '设置功率上限'},
    'reactive_compensator': {'adjust_reactive_power': '调整无功功率', 'regulate_voltage': '调整电压'},
    'cooling_fan': {'start': '启动', 'stop': '停止'},
}
UNITS = ('MW', 'kW', 'W', 'Mvar', 'kvar', 'var', 'kV', 'V', 'MW/min', '℃', '%', 'Hz')
ACTION_UNITS = {
    'adjust_active_power': {'MW', 'kW', 'W'}, 'limit_power': {'MW', 'kW', 'W'},
    'adjust_reactive_power': {'Mvar', 'kvar', 'var'}, 'regulate_voltage': {'kV', 'V'},
}
OPS = ('==', '!=', '<', '<=', '>', '>=')


def options():
    return {'scenarios': SCENARIOS, 'device_types': DEVICE_TYPES, 'actions': ACTIONS, 'units': UNITS}


def _keys(row, expected, message):
    if not isinstance(row, dict) or set(row) != set(expected.split()):
        raise ValueError(message)


def _number(value):
    return type(value) in (int, float) and -1e12 <= value <= 1e12 and math.isfinite(value)


def _literal(value, kind):
    if kind == 'boolean':
        return type(value) is bool
    if kind == 'integer':
        return type(value) is int and _number(value)
    if kind == 'number':
        return _number(value)
    return kind == 'enum' and isinstance(value, str) and bool(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,39}', value))


def compile_device(row):
    _keys(row, 'device_id display_name scenario_id template_id device_type fields actions',
          '设备配置字段不完整或包含未知字段。')
    identifier, name, kind, scenario = (row[k] for k in ('device_id', 'display_name', 'device_type', 'scenario_id'))
    if not isinstance(kind, str) or kind not in DEVICE_TYPES or not isinstance(scenario, str) or scenario not in SCENARIOS:
        raise ValueError('请选择支持的场景和设备类型。')
    fields, actions = row['fields'], row['actions']
    if not isinstance(fields, list) or not 1 <= len(fields) <= 30:
        raise ValueError('请填写 1 至 30 个状态字段。')
    if not isinstance(actions, list) or not 1 <= len(actions) <= 64:
        raise ValueError('请填写至少一个支持的动作。')
    profile = dict(device_id=identifier, display_name=name, aliases=[], device_type=kind, scenario=scenario,
                   protocol='IEC61850', initial_state={}, runtime_facts={}, state_fields={}, runtime_fact_fields={},
                   source='manual_device_import', mapping={}, actions={})
    specs = {}
    for item in fields:
        _keys(item, 'key label section type unit value', '状态字段格式不完整。')
        key, label, section, dtype, unit, value = (item[k] for k in ('key', 'label', 'section', 'type', 'unit', 'value'))
        if (not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', key)
                or key in specs or key in ('true', 'false')):
            raise ValueError('状态字段名须为小写英文字母、数字或下划线，且不能重复。')
        if (not isinstance(label, str) or not 1 <= len(label.strip()) <= 40 or section not in ('state', 'runtime_facts')
                or not _literal(value, dtype) or unit not in ('', *UNITS)
                or (dtype in ('boolean', 'enum') and unit)):
            raise ValueError(f'状态字段 {key} 的名称、类型、单位或初始值无效。')
        specs[key] = item
        values = 'initial_state' if section == 'state' else 'runtime_facts'
        metadata = 'state_fields' if section == 'state' else 'runtime_fact_fields'
        profile[values][key] = value
        profile[metadata][key] = {'display_name': label.strip(), 'type': dtype, 'unit': unit}
    prefix = 'LOCAL_' + identifier.replace('-', '_')
    for item in actions:
        custom = isinstance(item, dict) and 'value_source' in item
        _keys(item, 'action result_field minimum maximum conditions' + (' display_name value_source value parameter' if custom else ''), '动作配置字段不完整。')
        action, key = item['action'], item['result_field']
        if (not isinstance(action, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', action)
                or not custom and action not in ACTIONS[kind] or action in profile['actions']
                or not isinstance(key, str) or key not in specs):
            raise ValueError('动作不受设备类型支持、重复或没有绑定有效的结果字段。')
        spec = specs[key]
        unit = spec['unit']
        if custom:
            from .custom_action_definition import compile_definition
            settings, effect = compile_definition(item, spec, _literal)
        elif action in ACTION_UNITS:
            low, high = item['minimum'], item['maximum']
            if (spec['type'] not in ('integer', 'number') or unit not in ACTION_UNITS[action]
                    or not _literal(low, spec['type']) or not _literal(high, spec['type']) or low >= high):
                raise ValueError(f'{ACTIONS[kind][action]}：结果字段类型、单位或目标范围无效。')
            settings = {'parameter': key, 'parameter_type': spec['type'], 'minimum': low, 'maximum': high}
            effect = {'from_parameter': key}
        else:
            if spec['type'] != 'boolean' or item['minimum'] is not None or item['maximum'] is not None:
                raise ValueError('启停动作应绑定布尔状态，不填写数值范围。')
            settings = {'value': action == 'start'}
            effect = settings['value']
        conditions = item['conditions']
        if not isinstance(conditions, list) or not (0 if custom else 1) <= len(conditions) <= 10:
            raise ValueError('自定义动作可填写0至10条前置条件；已有动作至少填写1条。')
        checks = []
        for rule in conditions:
            _keys(rule, 'field operator value', '前置条件格式不完整。')
            field, op, wanted = rule['field'], rule['operator'], rule['value']
            if (not isinstance(field, str) or field not in specs or op not in OPS
                    or specs[field]['type'] == 'enum' or not _literal(wanted, specs[field]['type'])
                    or (specs[field]['type'] == 'boolean' and op not in ('==', '!='))):
                raise ValueError('前置条件必须引用已填写的状态字段，比较类型与字段类型须一致。')
            literal = str(wanted).lower() if type(wanted) is bool else str(wanted)
            checks.append((field, op, literal))
        section = spec['section']
        profile['actions'][action] = {
            'function': action, 'display_name': ACTIONS[kind].get(action, action), 'unit': unit, **settings,
            'condition': ' '.join(checks[0]) if checks else 'true',
            'constraints': [{'parameter': field, 'operator': op, 'value': literal, 'role': 'precondition'}
                            for field, op, literal in checks[1:]],
            'mapping': {'object_reference': f'{prefix}/CTRL/GGIO1.{action}',
                        'control_model': 'direct-with-normal-security', 'service': 'Operate'},
            'simulation_effects': {section: {key: effect}},
            'feedback_mapping': {'protocol': 'IEC61850', 'direction': 'read', 'field': f'{section}.{key}',
                                 'object_reference': f'{prefix}/STATUS/GGIO1.{key}', 'unit': unit,
                                 'data_type': {'boolean': 'bool', 'integer': 'int32', 'number': 'float32'}[spec['type']]},
        }
    return profile
