from copy import deepcopy
import json
import pytest
from standard_knowledge_service_v2.instruction_engine.simulation import SimulationInstructionService
from standard_knowledge_service_v2.instruction_engine.template_editor import save_custom, load_custom, test_template as probe_template

def sample():
    return {'device_id': 'SIM-MB-FAN-01', 'action': 'alarm', 'template': {
        'function': 'mock_alarm', 'condition': 'alarm_permission == 1', 'constraints': [],
        'value': True, 'mapping': {'slave_id': 3, 'address': 10, 'function_code': 5, 'data_type': 'bool'}},
        'facts': {'alarm_permission': 1}, 'parameters': {}}

def test_saved_template_reloads_and_cannot_overwrite(tmp_path):
    service = SimulationInstructionService()
    path = tmp_path / 'custom.json'
    assert save_custom(service, sample(), path)['status'] == 'saved'
    other = SimulationInstructionService()
    assert len(load_custom(other, path)) == 1
    assert other.devices['SIM-MB-FAN-01']['actions']['alarm']['source_rule_ids'] == []
    with pytest.raises(ValueError, match='已存在'):
        save_custom(service, sample(), path)

def test_test_endpoint_does_not_mutate_and_blocks_false_condition():
    service = SimulationInstructionService()
    before = deepcopy(service.devices), deepcopy(service.states)
    assert probe_template(service, sample())['status'] == 'generated'
    payload = sample()
    payload['facts'] = {'alarm_permission': 0}
    assert probe_template(service, payload)['status'] == 'blocked'
    assert (service.devices, service.states) == before

def test_editor_rejects_fake_source_binding_and_bad_mapping():
    service = SimulationInstructionService()
    payload = sample()
    payload['template']['source_rule_ids'] = ['fake']
    with pytest.raises(ValueError, match='不支持字段'):
        probe_template(service, payload)
    payload = sample()
    payload['template']['mapping']['function_code'] = 6
    with pytest.raises(ValueError, match='编码无效'):
        probe_template(service, payload)


@pytest.mark.parametrize('field', ['expected_feedback', 'state_key', 'state_value'])
def test_editor_rejects_execution_feedback(field):
    payload = sample()
    payload['template'][field] = 'legacy'
    with pytest.raises(ValueError, match='不支持字段'):
        probe_template(SimulationInstructionService(), payload)


def test_legacy_saved_feedback_is_ignored(tmp_path):
    row = sample()
    row['template'].update(state_key='running', state_value=True,
                           expected_feedback={'state_key': 'running', 'value': True})
    path = tmp_path / 'legacy.json'
    path.write_text(json.dumps({'simulation_only': True, 'items': [row]}), encoding='utf-8')
    loaded = load_custom(SimulationInstructionService(), path)
    assert not {'state_key', 'state_value', 'expected_feedback'} & loaded[0]['template'].keys()


def test_runtime_template_refresh_keeps_state_and_invalidates_old_preview(tmp_path):
    from standard_knowledge_service_v2.instruction_engine.simulation_catalog import SimulationCatalog
    from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime
    service = SimulationInstructionService()
    runtime = SimulationRuntime(SimulationCatalog(legacy_service=service))
    before = runtime.create_session('all_devices')
    sid = before['session_id']
    old = runtime.preview(sid, 'SIM-MB-FAN-01', 'start', {})
    save_custom(service, sample(), tmp_path / 'custom.json')
    runtime.refresh_catalog(SimulationCatalog(legacy_service=service))
    after = runtime.snapshot(sid)
    assert after['devices'] == before['devices']
    assert after['version'] > before['version']
    assert 'alarm' in runtime.catalog.devices['SIM-MB-FAN-01']['actions']
    assert 'alarm' in runtime._sessions[sid].profiles['SIM-MB-FAN-01']['actions']
    assert 'alarm' in runtime._sessions[runtime.create_session('all_devices')['session_id']].profiles['SIM-MB-FAN-01']['actions']
    assert runtime.execute(sid, old['command_id'], old['expected_version'])['status'] == 'blocked'


def test_save_http_route_synchronizes_running_catalog(monkeypatch, tmp_path):
    from threading import RLock
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from standard_knowledge_service_v2.api.routes import register_routes
    from standard_knowledge_service_v2.application.simulation_access import simulation_runtime
    from standard_knowledge_service_v2.instruction_engine import template_editor
    service = SimulationInstructionService()
    pipeline = SimpleNamespace(simulation_session=SimpleNamespace(service=service, lock=RLock()))
    runtime = simulation_runtime(pipeline)
    snapshot = runtime.create_session('all_devices')
    real_save = template_editor.save_custom
    monkeypatch.setattr(template_editor, 'save_custom',
                        lambda service, payload: real_save(service, payload, tmp_path / 'custom.json'))
    app = FastAPI()
    register_routes(app, SimpleNamespace(facade=pipeline, audit_store=None))
    client = TestClient(app)
    response = client.post('/simulation/templates', json=sample())
    assert response.status_code == 200
    assert response.json()['runtime_refreshed'] is True
    assert 'alarm' in runtime.catalog.devices['SIM-MB-FAN-01']['actions']
    assert runtime.snapshot(snapshot['session_id'])['version'] == snapshot['version'] + 1
