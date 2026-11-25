"""Explicit synthetic wire settings for publication contract tests."""
from copy import deepcopy
from standard_knowledge_service_v2.instruction_engine.simulation_catalog import SimulationCatalog
from standard_knowledge_service_v2.instruction_engine.customization_wire import extract_wire


def iec_wire(domain, field, *, action='start', numeric=False, reference=None):
    catalog = SimulationCatalog()
    wire = extract_wire(catalog.devices['SIM-IEC-FAN-01'], 'start')
    wire['command']['unit'] = 'MW' if numeric else ''
    wire['feedback']['unit'] = 'MW' if numeric else ''
    wire['communication']['host'] = '192.0.2.245'
    reference = reference or f'{domain}/GGIO1.{action}'
    logical_node, data_object = reference.split('/', 1)[1].split('.', 1)
    wire['command'].update(domain_id=domain, item_id=f'{logical_node}$CO${data_object.replace(".", "$")}$Oper', object_reference=reference, data_type='float32' if numeric else 'bool', value_shape='primitive')
    wire['feedback'].update(domain_id=domain, item_id=f'GGIO1$ST${field}$stVal', object_reference=f'{domain}/GGIO1.{field}', field=f'state.{field}', data_type='float32' if numeric else 'bool')
    return wire


def modbus_wire(field='alarm_active'):
    return dict(protocol='Modbus', communication=dict(host='192.0.2.3', port=502),
        command=dict(slave_id=3,address=10,function_code=5,data_type='bool',scale=1,byte_order='big',word_order='big'),
        feedback=dict(protocol='Modbus',direction='read',field=f'state.{field}',slave_id=3,address=1010,function_code=1,data_type='bool',scale=1,byte_order='big',word_order='big'))


def import_wires(row):
    result = deepcopy(row)
    actions = row['actions']
    result['wires'] = {action: iec_wire(row['device_id'].replace('-', '_'), 'running', action=action) for action in actions}
    return result
