from copy import deepcopy
import math
from .protocol_messages import build_message, numeric
from .simulation_wire_profiles import _missing_fields


def extract_wire(device, action):
    template = device['actions'][action]
    return dict(protocol=device['protocol'], communication=deepcopy(device.get('communication', {})),
                command={k: deepcopy(v) for k, v in {**device.get('mapping', {}), **template.get('mapping', {})}.items() if k not in ('host', 'port')},
                feedback={k: deepcopy(v) for k, v in template.get('feedback_mapping', {}).items() if k not in ('host', 'port')})


def apply_wire(profile, action, wire, *, strict=True):
    if not isinstance(wire, dict) or set(wire) != {'protocol', 'communication', 'command', 'feedback'}:
        raise ValueError('关联必须补齐完整wire通信、写入及独立读回配置。')
    protocol = wire['protocol']
    if protocol not in ('IEC61850', 'Modbus') or any(not isinstance(wire[k], dict) for k in ('communication', 'command', 'feedback')):
        raise ValueError('wire协议或映射格式无效。')
    wire = deepcopy(wire)
    for section in ('command', 'feedback'):
        for key in ('host', 'port'):
            if strict and key in wire[section] and wire[section][key] != wire['communication'].get(key):
                raise ValueError('映射内通信地址与communication不一致，请只在通信配置中设置host和port。')
            wire[section].pop(key, None)
    profile['mapping'] = {k: v for k, v in profile.get('mapping', {}).items() if k not in ('host', 'port')}
    # A prior expanded catalog may retain endpoint copies on observation points.
    for point in profile.get('points', {}).values():
        if isinstance(point, dict):
            point.pop('host', None)
            point.pop('port', None)
    for existing_action in profile.get('actions', {}).values():
        for mapping_key in ('mapping', 'feedback_mapping'):
            for endpoint_key in ('host', 'port'):
                existing_action.get(mapping_key, {}).pop(endpoint_key, None)
    profile['protocol'] = protocol
    if protocol == 'Modbus':
        profile['mapping'] = {'slave_id': wire['command'].get('slave_id')}
    profile['communication'] = {**deepcopy(wire['communication']), 'simulation_only': True}
    template = profile['actions'][action]
    for section in ('command', 'feedback'):
        if strict and 'unit' in wire[section] and wire[section]['unit'] != template.get('unit', ''):
            raise ValueError('报文映射工程单位必须与指令单位一致。')
    template['mapping'] = deepcopy(wire['command'])
    template['feedback_mapping'] = deepcopy(wire['feedback'])
    template['mapping'].setdefault('unit', template.get('unit', ''))
    template['feedback_mapping'].setdefault('unit', template.get('unit', ''))
    missing = _missing_fields(wire['command'], protocol, command=True)
    missing += ['feedback.' + k for k in _missing_fields(wire['feedback'], protocol, command=False)]
    if strict and missing:
        raise ValueError('报文配置不完整：' + '、'.join(missing))
    if strict and protocol == 'IEC61850':
        for mapping in (wire['command'], wire['feedback']):
            if any(not isinstance(mapping.get(key), str) for key in ('object_reference', 'domain_id', 'item_id')):
                raise ValueError('IEC点位标识须为文本。')
            domain, separator, reference = mapping['object_reference'].partition('/')
            parts, path = mapping['item_id'].split('$'), reference.split('.')
            if (not separator or domain != mapping['domain_id'] or len(parts) < 3
                    or len(path) < 2 or not all(path) or parts[0] != path[0]
                    or parts[2:2 + len(path) - 1] != path[1:]):
                raise ValueError('IEC点位标识不一致：对象引用须与MMS域及变量标识指向同一对象。')
    template['wire_profile_missing_fields'] = missing
    effects = template['simulation_effects']
    section = 'state' if effects.get('state') else 'runtime_facts'
    field = next(iter(effects[section]))
    if strict and wire['feedback'].get('field') != f'{section}.{field}':
        raise ValueError('读回映射field必须对应动作结果字段。')
    if strict and any(wire[k].get('protocol', protocol) != protocol for k in ('command', 'feedback')):
        raise ValueError('写入及读回协议必须与设备协议一致。')
    if strict:
        command, feedback = wire['command'], wire['feedback']
        metadata = profile.get('state_fields' if section == 'state' else 'runtime_fact_fields', {}).get(field, {})
        result_type = metadata.get('type')
        effect = effects[section][field]
        boolean_result = result_type == 'boolean' or type(effect) is bool
        numeric_result = result_type in ('integer', 'number') or isinstance(effect, dict) and 'from_parameter' in effect
        if boolean_result and any(mapping.get('data_type') != 'bool' for mapping in (command, feedback)):
            raise ValueError('布尔结果必须使用bool写入和读回类型，不能隐式转换数值反馈。')
        if numeric_result and any(mapping.get('data_type') not in ('uint16', 'int16', 'uint32', 'int32', 'float32') for mapping in (command, feedback)):
            raise ValueError('数值结果必须使用支持的数值写入和读回类型。')
        if protocol == 'Modbus':
            if command.get('slave_id') != feedback.get('slave_id'):
                raise ValueError('写入与读回必须使用同一设备单元标识slave_id。')
            for label, mapping in (('写入', command), ('读回', feedback)):
                if any(mapping.get(key) not in ('big', 'little') for key in ('byte_order', 'word_order')):
                    raise ValueError(f'{label}字节序和字序只能为big或little。')
                scale = mapping.get('scale')
                if type(scale) not in (int, float) or not math.isfinite(scale) or not 0 < scale <= 1e12:
                    raise ValueError(f'{label}倍率须为有限正数且不超过1e12。')
                if mapping.get('data_type') == 'bool' and scale != 1:
                    raise ValueError(f'{label}布尔类型倍率须为1。')
        values = [template['value']] if 'value' in template else [template['minimum'], template['maximum']]
        try:
            for value in values:
                if protocol == 'Modbus' and feedback.get('data_type') != 'bool':
                    numeric(value, feedback.get('data_type'), feedback.get('scale'))
                candidate = dict(protocol=protocol, target=profile['device_id'], payload=dict(engineering_value=value, unit=template.get('unit', '')))
                build_message(candidate, profile, action, {})
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f'完整报文编码校验失败：{exc}') from exc
    # Stable per-device/action point identities prevent a shared feedback point
    # from silently overriding an independent mapping during catalog adaptation.
    command_name, feedback_name = f'{action}_command', f'{action}_feedback'
    template['command_point'], template['feedback_point'] = command_name, feedback_name
    template['feedback_mapping']['point'] = feedback_name
    points = profile.setdefault('points', {})
    points[command_name] = {**deepcopy(template['mapping']), 'protocol': protocol, 'direction': 'write', 'unit': template.get('unit', '')}
    points[feedback_name] = deepcopy(template['feedback_mapping'])
