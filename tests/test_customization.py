from copy import deepcopy
import pytest
from standard_knowledge_service_v2.instruction_engine import customization as c
from standard_knowledge_service_v2.instruction_engine.simulation_control import SimulationControlSession
from standard_knowledge_service_v2.instruction_engine.simulation_catalog import SimulationCatalog
from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime


def wire(index=1, numeric=False):
    return dict(protocol='Modbus', communication=dict(host=f'192.0.2.{230+index}', port=502),
        command=dict(slave_id=230+index, address=55000, function_code=16 if numeric else 5, data_type='float32' if numeric else 'bool', scale=1, byte_order='big', word_order='big'),
        feedback=dict(protocol='Modbus', direction='read', field='state.output' if numeric else 'state.running', slave_id=230+index, address=55010, function_code=3 if numeric else 1, data_type='float32' if numeric else 'bool', scale=1, byte_order='big', word_order='big'))


def sample():
    fields = [dict(key='running', label='运行', section='state', type='boolean', unit='', value=False),
              dict(key='permission', label='许可', section='runtime_facts', type='boolean', unit='', value=True)]
    return dict(devices=[dict(device_id='SIM-CUSTOM-01', display_name='定制风机一号', scenario_id='substation_maintenance', device_type='cooling_fan', fields=fields)],
                instructions=[dict(instruction_id='CUSTOM-START', display_name='共享启动', device_type='cooling_fan', fields=deepcopy(fields),
                    action=dict(action='start', result_field='running', minimum=None, maximum=None, conditions=[dict(field='permission',operator='==',value=True)]))],
                bindings=[dict(device_id='SIM-CUSTOM-01', instruction_id='CUSTOM-START', wire=wire())])

@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(c, 'CUSTOM_PATH', tmp_path / 'customization.json')
    session = SimulationControlSession()
    runtime = SimulationRuntime(SimulationCatalog(legacy_service=session.service), event_path=tmp_path / 'events.jsonl')
    return session, runtime


def test_publish_restart_and_shared_state(setup):
    session, runtime = setup
    state = sample()
    state['devices'].append(dict(state['devices'][0], device_id='SIM-CUSTOM-02', display_name='定制风机二号'))
    state['bindings'].append(dict(device_id='SIM-CUSTOM-02', instruction_id='CUSTOM-START', wire=wire(2)))
    view = c.snapshot(session, runtime)
    payload = dict(state=state, base_revision=view['base_revision'])
    validated = c.process(session, runtime, payload)
    assert validated['status'] == 'validated', validated
    payload['revision'] = validated['revision']
    assert c.process(session, runtime, payload, publish=True)['status'] == 'published'
    loaded = SimulationControlSession()
    assert loaded.service.devices['SIM-CUSTOM-02']['actions']['start']
    assert len(c.snapshot(session, runtime)['state']['instructions']) == 1
    assert c.process(session, runtime, payload, publish=True)['status'] == 'invalid'


def test_unknown_reference_and_rollback(setup, monkeypatch):
    session, runtime = setup
    state = sample()
    payload = dict(state=state, base_revision=c.snapshot(session, runtime)['base_revision'])
    bad = deepcopy(payload)
    bad['state']['bindings'][0]['instruction_id'] = 'missing'
    assert c.process(session, runtime, bad)['status'] == 'invalid'
    payload['revision'] = c.process(session, runtime, payload)['revision']
    def fail(catalog):
        raise RuntimeError('refresh failed')
    monkeypatch.setattr(runtime, 'refresh_catalog', fail)
    assert c.process(session, runtime, payload, publish=True)['status'] == 'invalid'
    assert not c.CUSTOM_PATH.exists()
    assert 'SIM-CUSTOM-01' not in session.service.devices

def test_existing_preset_preserves_complete_wire_and_live_state(setup):
    session, runtime = setup
    original = deepcopy(runtime.catalog.devices['SIM-IEC-FAN-01']['actions']['start'])
    for endpoint_key in ('host', 'port'):
        original['mapping'].pop(endpoint_key, None)
        original['feedback_mapping'].pop(endpoint_key, None)
    current = runtime.create_session('substation_maintenance')
    sid = current['session_id']
    live = runtime._sessions[sid]
    live.devices['SIM-IEC-FAN-01']['state']['running'] = True
    view = c.snapshot(session, runtime)
    preset = next(p for p in view['instructions'] if p['instruction_id'] == 'PRESET:SIM-IEC-FAN-01:start')
    state = deepcopy(c.EMPTY)
    state['bindings'] = [dict(device_id='SIM-IEC-FAN-01', instruction_id=preset['instruction_id'])]
    payload = dict(state=state, base_revision=view['base_revision'])
    result = c.process(session, runtime, payload)
    assert result['status'] == 'validated', result
    payload['revision'] = result['revision']
    assert c.process(session, runtime, payload, publish=True)['status'] == 'published'
    after = runtime.catalog.devices['SIM-IEC-FAN-01']['actions']['start']
    assert after['mapping'] == original['mapping']
    assert {k: v for k, v in after['feedback_mapping'].items() if k != 'point'} == {k: v for k, v in original['feedback_mapping'].items() if k != 'point'}
    assert live.devices['SIM-IEC-FAN-01']['state']['running'] is True
    restarted = SimulationCatalog(legacy_service=SimulationControlSession().service)
    assert restarted.devices['SIM-IEC-FAN-01']['actions']['start']['mapping'] == original['mapping']


def test_numeric_effect_and_shared_instruction_compatibility(setup):
    session, runtime = setup
    state = sample()
    fields = [dict(key='output', label='出力', section='state', type='number', unit='MW', value=10.0),
              dict(key='permission', label='许可', section='runtime_facts', type='boolean', unit='', value=True)]
    state['devices'][0].update(device_type='dispatch_unit', scenario_id='power_grid_operation', fields=fields)
    instruction = state['instructions'][0]
    instruction.update(device_type='dispatch_unit', fields=deepcopy(fields))
    instruction['action'].update(action='adjust_active_power', result_field='output', minimum=0.0, maximum=100.0)
    state['devices'].append(dict(state['devices'][0], device_id='SIM-CUSTOM-02', display_name='定制调度二号', fields=deepcopy(fields)))
    state['bindings'][0]['wire'] = wire(numeric=True)
    state['bindings'].append(dict(device_id='SIM-CUSTOM-02', instruction_id=instruction['instruction_id'], wire=wire(2, numeric=True)))
    payload = dict(state=state, base_revision=c.snapshot(session, runtime)['base_revision'])
    result = c.process(session, runtime, payload)
    assert result['status'] == 'validated', result
    payload['revision'] = result['revision']
    assert c.process(session, runtime, payload, publish=True)['status'] == 'published'
    device = runtime.catalog.devices['SIM-CUSTOM-01']
    assert device['display_name'] == state['devices'][0]['display_name']
    assert device['actions']['adjust_active_power']['simulation_effects'] == {'state': {'output': {'from_parameter': 'output'}}}
    state['devices'][1]['fields'][0]['unit'] = 'kW'
    payload['base_revision'] = c.snapshot(session, runtime)['base_revision']
    assert c.process(session, runtime, payload)['status'] == 'invalid'


def test_duplicate_binding_and_changed_confirmation(setup):
    session, runtime = setup
    state = sample()
    payload = dict(state=state, base_revision=c.snapshot(session, runtime)['base_revision'])
    result = c.process(session, runtime, payload)
    payload['revision'] = result['revision']
    payload['state']['instructions'][0]['display_name'] = '变更后的共享指令'
    assert c.process(session, runtime, payload, publish=True)['status'] == 'invalid'
    payload['state']['bindings'].append(deepcopy(payload['state']['bindings'][0]))
    assert c.process(session, runtime, payload)['status'] == 'invalid'

def test_legacy_template_and_import_keep_customization_and_live_state(setup, tmp_path, monkeypatch):
    from standard_knowledge_service_v2.instruction_engine import template_editor, device_import
    session, runtime = setup
    monkeypatch.setattr(device_import, 'IMPORT_PATH', tmp_path / 'imports.json')
    monkeypatch.setattr(template_editor, 'CUSTOM_PATH', tmp_path / 'legacy_templates.json')
    payload = dict(state=sample(), base_revision=c.snapshot(session, runtime)['base_revision'])
    payload['revision'] = c.process(session, runtime, payload)['revision']
    assert c.process(session, runtime, payload, publish=True)['status'] == 'published'
    snapshot = runtime.create_session('all_devices')
    sid = snapshot['session_id']
    runtime.apply_fact_inputs(sid, [dict(device_id='SIM-CUSTOM-01', field='state.running', value=True)],
                             expected_version=snapshot['version'])
    template = dict(device_id='SIM-MB-FAN-01', action='alarm', template=dict(
        function='local_alarm', condition='alarm_permission == 1', constraints=[], value=True,
        mapping=dict(slave_id=3, address=10, function_code=5, data_type='bool')))
    with pytest.raises(ValueError, match='完整报文|报文配置不完整'):
        template_editor.save_custom(session.service, template, tmp_path / 'legacy_templates.json', publish=runtime.refresh_catalog)
    assert 'SIM-CUSTOM-01' in runtime.catalog.devices
    assert 'alarm' not in runtime.catalog.devices['SIM-MB-FAN-01']['actions']
    rows = [dict(device_id='SIM-IMPORT-FAN-CROSS', display_name='组合入口风机', scenario_id='substation_maintenance',
                 template_id=device_import.BLUEPRINT, initial_values={key: True for key in device_import.FACT_LABELS}, actions=['start'])]
    validated = device_import.process(session, runtime, rows)
    assert validated['status'] == 'invalid', validated
    live = {d['device_id']: d for d in runtime.snapshot(sid)['devices']}
    assert live['SIM-CUSTOM-01']['state']['running'] is True
    assert 'SIM-IMPORT-FAN-CROSS' not in runtime.catalog.devices
    restarted = SimulationCatalog(legacy_service=SimulationControlSession().service)
    assert 'SIM-CUSTOM-01' in restarted.devices


def test_legacy_editor_consistently_rejects_custom_device_without_mutation(setup, tmp_path):
    from standard_knowledge_service_v2.instruction_engine import template_editor
    session, runtime = setup
    payload = dict(state=sample(), base_revision=c.snapshot(session, runtime)['base_revision'])
    payload['revision'] = c.process(session, runtime, payload)['revision']
    assert c.process(session, runtime, payload, publish=True)['status'] == 'published'
    before_devices = deepcopy(session.service.devices)
    before_states = deepcopy(session.service.states)
    before_custom_file = c.CUSTOM_PATH.read_bytes()
    legacy_path = tmp_path / 'legacy_templates.json'
    template = dict(device_id='SIM-CUSTOM-01', action='alarm', template=dict(
        function='local_alarm', condition='permission == true', constraints=[], value=True,
        mapping=dict(object_reference='LOCAL_SIM_CUSTOM_01/CTRL/GGIO1.alarm',
                     control_model='direct-with-normal-security', service='Operate')))
    for operation in (lambda: template_editor.test_template(session.service, template),
                      lambda: template_editor.save_custom(session.service, template, legacy_path,
                                                          publish=runtime.refresh_catalog)):
        with pytest.raises(ValueError, match='自定义配置.*指令'):
            operation()
    assert session.service.devices == before_devices
    assert session.service.states == before_states
    assert c.CUSTOM_PATH.read_bytes() == before_custom_file
    assert not legacy_path.exists()
