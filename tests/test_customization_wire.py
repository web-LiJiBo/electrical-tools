from copy import deepcopy
import pytest
from test_customization import sample
from standard_knowledge_service_v2.instruction_engine import customization as c
from standard_knowledge_service_v2.instruction_engine.protocol_messages import build_message


def wire():
    return dict(protocol='Modbus', communication=dict(host='192.0.2.240', port=502),
        command=dict(slave_id=240, address=55000, function_code=5, data_type='bool', scale=1, byte_order='big', word_order='big'),
        feedback=dict(protocol='Modbus', direction='read', field='state.running', slave_id=240, address=55010, function_code=1, data_type='bool', scale=1, byte_order='big', word_order='big'))


def test_custom_wire_complete_bundle_and_catalog():
    state = sample()
    state['bindings'][0]['wire'] = wire()
    _, catalog, _ = c._prepare(state, deepcopy(c.EMPTY))
    profile = catalog.devices['SIM-CUSTOM-01']
    candidate = dict(protocol='Modbus', target=profile['device_id'], payload=dict(engineering_value=True))
    bundle = build_message(candidate, profile, 'start', {})
    assert bundle['request_count'] == 2
    assert bundle['endpoint'] == dict(host='192.0.2.240', port=502)
    assert bundle['requests'][1]['hex'].endswith('01 d6 e2 00 01')


@pytest.mark.parametrize('change', ['missing', 'bad_code', 'bad_feedback', 'bad_host'])
def test_reject_incomplete_or_unencodable_wire(change):
    state = sample()
    w = wire()
    if change == 'missing':
        del w['command']['scale']
    if change == 'bad_code':
        w['command']['function_code'] = 6
    if change == 'bad_feedback':
        w['feedback']['function_code'] = 3
    if change == 'bad_host':
        w['communication']['host'] = 'http://bad'
    state['bindings'][0]['wire'] = w
    with pytest.raises(ValueError):
        c._prepare(state, deepcopy(c.EMPTY))


def test_legacy_load_only_and_unbound_rejected():
    state = sample()
    state['bindings'][0].pop('wire')
    with pytest.raises(ValueError, match='完整'):
        c._prepare(state, deepcopy(c.EMPTY))
    _, catalog, _ = c._prepare(state, deepcopy(c.EMPTY), strict=False)
    assert catalog.devices['SIM-CUSTOM-01']['actions']['start']['wire_profile_missing_fields']
    state['bindings'] = []
    with pytest.raises(ValueError, match='至少关联'):
        c._prepare(state, deepcopy(c.EMPTY))


@pytest.mark.parametrize('model', ['direct-with-normal-security', 'sbo-with-normal-security', 'direct-with-enhanced-security', 'sbo-with-enhanced-security'])
def test_iec_four_control_models(model):
    base = c.SimulationCatalog(legacy_service=c._base())
    w = c.extract_wire(base.devices['SIM-IEC-FAN-01'], 'start')
    w['communication']['host'] = '192.0.2.240'
    w['command'].update(domain_id='CUSTOM240', item_id='GGIO1$CO$SPCSO1$Oper', object_reference='CUSTOM240/GGIO1.SPCSO1', control_model=model, selection_timeout_ms=5000)
    w['feedback'].update(domain_id='CUSTOM240', item_id='GGIO1$ST$Ind1$stVal', object_reference='CUSTOM240/GGIO1.Ind1', field='state.running')
    state = sample()
    state['bindings'][0]['wire'] = w
    _, catalog, _ = c._prepare(state, deepcopy(c.EMPTY))
    profile = catalog.devices['SIM-CUSTOM-01']
    candidate = dict(protocol='IEC61850', target=profile['device_id'], payload=dict(engineering_value=True))
    result = build_message(candidate, profile, 'start', {})
    assert result['request_count'] >= 5
    assert result['parameters']['control_model'] == model


@pytest.mark.parametrize('code,dtype', [(6, 'uint16'), (16, 'float32')])
def test_numeric_modbus(code, dtype):
    from standard_knowledge_service_v2.instruction_engine.customization_wire import apply_wire
    state = sample()
    state['devices'][0].update(device_type='dispatch_unit')
    fields = state['devices'][0]['fields']
    fields[0].update(key='output', type='number', unit='MW', value=0.0)
    action = dict(action='adjust_active_power', result_field='output', minimum=0.0, maximum=100.0, conditions=[dict(field='permission', operator='==', value=True)])
    profile = c._compile(state['devices'][0], [action])
    w = wire()
    w['command'].update(function_code=code, data_type=dtype)
    w['feedback'].update(function_code=3, data_type=dtype, field='state.output')
    apply_wire(profile, 'adjust_active_power', w)
    candidate = dict(protocol='Modbus', target=profile['device_id'], payload=dict(engineering_value=50))
    result = build_message(candidate, profile, 'adjust_active_power', {})
    assert result['request_count'] == 2
    assert result['parameters']['function_code'] == code


def test_legacy_advanced_complete_wire_round_trip(tmp_path):
    from standard_knowledge_service_v2.instruction_engine import template_editor as te
    from standard_knowledge_service_v2.instruction_engine.simulation import SimulationInstructionService
    service = SimulationInstructionService()
    w = wire()
    w['command']['slave_id'] = 3
    w['feedback'].update(slave_id=3, field='state.alarm_active')
    payload = dict(device_id='SIM-MB-FAN-01', action='alarm', wire=w,
        template=dict(function='local_alarm', condition='alarm_permission == 1', constraints=[], value=True,
                      mapping=deepcopy(w['command'])))
    assert te.test_template(service, payload)['valid'] is True
    path = tmp_path / 'advanced.json'
    assert te.save_custom(service, payload, path)['status'] == 'saved'
    restarted = SimulationInstructionService()
    te.load_custom(restarted, path)
    profile = c.SimulationCatalog(legacy_service=restarted).devices['SIM-MB-FAN-01']
    candidate = dict(protocol='Modbus', target=profile['device_id'], payload=dict(engineering_value=True))
    result = build_message(candidate, profile, 'alarm', {})
    assert result['endpoint']['host'] == w['communication']['host']
    assert result['feedback_mapping']['address'] == 55010


def test_legacy_snapshot_can_be_opened_to_repair(tmp_path, monkeypatch):
    from standard_knowledge_service_v2.instruction_engine.simulation_control import SimulationControlSession
    from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime
    state = sample()
    state['bindings'][0].pop('wire')
    path = tmp_path / 'legacy.json'
    path.write_bytes(c._encode(dict(schema_version=1, simulation_only=True, state=state)))
    monkeypatch.setattr(c, 'CUSTOM_PATH', path)
    session = SimulationControlSession()
    runtime = SimulationRuntime(c.SimulationCatalog(legacy_service=session.service), event_path=tmp_path / 'events.jsonl')
    view = c.snapshot(session, runtime)
    assert view['load_error'] == ''
    assert view['load_warning']
    assert view['state'] == state
    assert view['incomplete_bindings'] == state['bindings']
    assert c.process(session, runtime, dict(state=state, base_revision=view['base_revision']))['status'] == 'invalid'


@pytest.mark.parametrize('section', ['command', 'feedback'])
def test_explicit_wire_units_cannot_disagree_with_action(section):
    state = sample()
    state['bindings'][0]['wire'][section]['unit'] = 'MW'
    with pytest.raises(ValueError, match='单位'):
        c._prepare(state, deepcopy(c.EMPTY))


@pytest.mark.parametrize('changes', [
    {'byte_order': 'invalid'}, {'word_order': 'invalid'},
    {'scale': 0}, {'scale': -1}, {'scale': float('inf')}, {'scale': float('nan')},
    {'scale': True}, {'scale': 2}, {'slave_id': 99},
    {'data_type': 'float32', 'function_code': 3},
])
def test_reject_unfaithful_modbus_feedback(changes):
    state = sample()
    state['bindings'][0]['wire']['feedback'].update(changes)
    with pytest.raises(ValueError):
        c._prepare(state, deepcopy(c.EMPTY))


@pytest.mark.parametrize('section,key,value', [('command', 'host', '192.0.2.99'), ('feedback', 'host', '192.0.2.99'), ('command', 'port', 503), ('feedback', 'port', 503)])
def test_reject_conflicting_mapping_endpoint(section, key, value):
    state = sample()
    state['bindings'][0]['wire'][section][key] = value
    with pytest.raises(ValueError, match='communication不一致'):
        c._prepare(state, deepcopy(c.EMPTY))


def test_wire_endpoint_has_single_authoritative_source():
    from standard_knowledge_service_v2.instruction_engine.customization_wire import apply_wire, extract_wire
    state = sample()
    profile = c._compile(state['devices'][0], [state['instructions'][0]['action']])
    w = wire()
    for section in ('command', 'feedback'):
        w[section].update(host=w['communication']['host'], port=w['communication']['port'])
    apply_wire(profile, 'start', w)
    extracted = extract_wire(profile, 'start')
    assert all('host' not in extracted[k] and 'port' not in extracted[k] for k in ('command', 'feedback'))
    profile['mapping'].update(host='192.0.2.20', port=502)
    profile['points']['old_observation'] = dict(host='192.0.2.20', port=502)
    w['command']['host'] = '192.0.2.20'
    apply_wire(profile, 'start', w, strict=False)
    assert 'host' not in profile['mapping']
    assert all('host' not in p and 'port' not in p for p in profile['points'].values())
    candidate = dict(protocol='Modbus', target=profile['device_id'], payload=dict(engineering_value=True))
    assert build_message(candidate, profile, 'start', {})['endpoint'] == w['communication']
