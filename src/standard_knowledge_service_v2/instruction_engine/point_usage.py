"""Compare physical points while allowing compatible same-field aliases."""
import json


def modbus_space(function_code):
    return {1: 'coil', 5: 'coil', 2: 'discrete_input', 4: 'input_register'}.get(function_code, 'holding_register')


def point_keys(protocol, mapping):
    if protocol == 'Modbus':
        width = 2 if mapping.get('data_type') in ('int32', 'uint32', 'float32') else 1
        return tuple(('Modbus', mapping['slave_id'], modbus_space(mapping.get('function_code')), address)
                     for address in range(mapping['address'], mapping['address'] + width))
    location = ((mapping['domain_id'], mapping['item_id'])
                if mapping.get('domain_id') and mapping.get('item_id') else mapping['object_reference'])
    return (('IEC61850', location),)


def validate_device_points(device):
    used = {}
    for name, template in device['actions'].items():
        for direction, mapping in [('写入', {**device.get('mapping', {}), **template.get('mapping', {})}),
                                   ('反馈', template['feedback_mapping'])]:
            keys = point_keys(device['protocol'], mapping)
            signature = (keys, template['feedback_mapping'].get('field'),
                         mapping.get('data_type'), mapping.get('scale', 1),
                         mapping.get('byte_order', 'big'), mapping.get('word_order', 'big'),
                         mapping.get('unit', template.get('unit', '')),
                         json.dumps(mapping.get('value_encoding', {}), sort_keys=True),
                         mapping.get('control_model'), mapping.get('value_shape'))
            for key in keys:
                prior = used.get(key)
                if prior is not None and (prior[1] != direction or prior[2] != signature):
                    raise ValueError(f"{device['device_id']}：动作{prior[0]}的{prior[1]}与动作{name}的{direction}点位重叠或共享字段、编码冲突。")
                used[key] = (name, direction, signature)
