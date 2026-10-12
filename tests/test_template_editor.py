from copy import deepcopy
import pytest
from standard_knowledge_service_v2.instruction_engine.simulation import SimulationInstructionService
from standard_knowledge_service_v2.instruction_engine.template_editor import save_custom, load_custom, test_template as probe_template

def sample():
    return {'device_id': 'SIM-MB-FAN-01', 'action': 'alarm', 'template': {
        'function': 'mock_alarm', 'condition': 'alarm_permission == 1', 'constraints': [],
        'value': True, 'state_key': 'running', 'mapping': {'slave_id': 3, 'address': 10, 'function_code': 5, 'data_type': 'bool'}},
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
