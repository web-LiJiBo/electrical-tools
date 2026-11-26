from copy import deepcopy
import pytest
from test_custom_action_templates import custom_state
from test_customization import sample
from standard_knowledge_service_v2.instruction_engine import customization as c
from standard_knowledge_service_v2.instruction_engine.simulation_control import SimulationControlSession
from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime


def two_actions():
    state = custom_state(value=True)
    state['devices'][0]['fields'].append(dict(key='alarm', label='告警', section='state', type='boolean', unit='', value=False))
    second = deepcopy(state['instructions'][0])
    second.update(instruction_id='SECOND', display_name='第二动作', fields=deepcopy(state['devices'][0]['fields']))
    second['action'].update(action='set_alarm', display_name='设置告警', result_field='alarm')
    state['instructions'].append(second)
    binding = deepcopy(state['bindings'][0]); binding['instruction_id'] = 'SECOND'
    binding['wire']['command']['address'] = 55020
    binding['wire']['feedback'].update(address=55030, field='state.alarm')
    state['bindings'].append(binding)
    return state


@pytest.mark.parametrize('overlap', ['write_read', 'write_write', 'read_read'])
def test_different_action_fields_cannot_alias_incompatible_points(overlap):
    state = two_actions(); a, b = [row['wire'] for row in state['bindings']]
    if overlap == 'write_read': b['command']['address'] = a['feedback']['address']
    elif overlap == 'write_write': b['command']['address'] = a['command']['address']
    else: b['feedback']['address'] = a['feedback']['address']
    with pytest.raises(ValueError, match='点位.*(重叠|冲突)|共享.*字段'):
        c._prepare(state, deepcopy(c.EMPTY))


def test_start_stop_can_share_command_and_same_state_feedback():
    state = sample(); second = deepcopy(state['instructions'][0])
    second['instruction_id'] = 'STOP'; second['action']['action'] = 'stop'
    state['instructions'].append(second)
    state['bindings'].append(dict(deepcopy(state['bindings'][0]), instruction_id='STOP'))
    c._prepare(state, deepcopy(c.EMPTY))


def test_modbus_input_register_is_separate_from_holding_register():
    state = custom_state('parameter', numeric=True)
    wire = state['bindings'][0]['wire']; wire['feedback'].update(function_code=4, address=wire['command']['address'])
    _, catalog, _ = c._prepare(state, deepcopy(c.EMPTY))
    runtime = SimulationRuntime(catalog, event_path=None)
    sid = runtime.create_session('all_devices')['session_id']
    preview = runtime.preview(sid, 'SIM-CUSTOM-01', 'set_air_ratio', {'target_ratio': 45})
    assert preview['status'] == 'generated', preview
    packet = runtime.generate_message(sid, preview['command_id'], preview['expected_version'], {})
    assert packet['engineering_value'] == 45


def test_iec_different_actions_cannot_write_another_actions_feedback():
    from standard_knowledge_service_v2.instruction_engine.point_usage import validate_device_points
    profile = deepcopy(c.SimulationCatalog().devices['SIM-IEC-FAN-01'])
    profile['actions']['stop']['mapping'] = deepcopy(profile['actions']['start']['feedback_mapping'])
    with pytest.raises(ValueError, match='点位重叠'):
        validate_device_points(profile)


def test_modbus_shared_registers_must_cover_exact_same_span_and_field():
    from standard_knowledge_service_v2.instruction_engine.point_usage import validate_device_points
    state = custom_state('parameter', numeric=True)
    _, catalog, _ = c._prepare(state, deepcopy(c.EMPTY))
    profile = deepcopy(catalog.devices['SIM-CUSTOM-01'])
    second = deepcopy(profile['actions']['set_air_ratio'])
    second['mapping']['address'] += 1
    second['feedback_mapping']['address'] += 20
    profile['actions']['second'] = second
    with pytest.raises(ValueError, match='点位重叠'):
        validate_device_points(profile)


def test_existing_device_endpoint_change_needs_bound_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr(c, 'CUSTOM_PATH', tmp_path / 'custom.json')
    session = SimulationControlSession(); runtime = SimulationRuntime(event_path=None)
    target = runtime.catalog.devices['SIM-MB-FAN-01']; wire = c.extract_wire(target, 'start')
    wire['communication']['host'] = '192.0.2.249'; wire['command']['address'] = 61000
    wire['feedback'].update(address=61010, field='state.running')
    state = deepcopy(c.EMPTY)
    action = dict(action='new_alarm', display_name='新动作', value_source='fixed', value=True, parameter='', result_field='running', minimum=None, maximum=None, conditions=[])
    state['instructions'] = [dict(instruction_id='NEW', display_name='新动作', device_type='cooling_fan', fields=c.device_fields(target), action=action)]
    state['bindings'] = [dict(device_id=target['device_id'], instruction_id='NEW', wire=wire)]
    payload = dict(state=state, base_revision=c.snapshot(session, runtime)['base_revision'])
    result = c.process(session, runtime, payload)
    assert result['status'] == 'validated'
    change = result['communication_changes'][0]
    assert change['device_id'] == target['device_id'] and 'stop' in change['affected_actions']
    payload['revision'] = result['revision']
    assert c.process(session, runtime, payload, publish=True)['status'] == 'invalid'
    assert not c.CUSTOM_PATH.exists()
    payload['communication_confirmations'] = ['WRONG-DEVICE']
    assert c.process(session, runtime, payload, publish=True)['status'] == 'invalid'
    payload['communication_confirmations'] = [target['device_id']]
    assert c.process(session, runtime, payload, publish=True)['status'] == 'published'
    assert runtime.catalog.devices[target['device_id']]['communication']['host'] == '192.0.2.249'
    restore = dict(state=deepcopy(c.EMPTY), base_revision=c.snapshot(session, runtime)['base_revision'])
    result = c.process(session, runtime, restore)
    assert result['communication_changes'][0]['device_id'] == target['device_id']
    assert target['device_id'] in result['affected_devices']
    restore['revision'] = result['revision']
    assert c.process(session, runtime, restore, publish=True)['status'] == 'invalid'
