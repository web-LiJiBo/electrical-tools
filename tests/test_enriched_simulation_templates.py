from copy import deepcopy
import json
from pathlib import Path

import pytest

from standard_knowledge_service_v2.instruction_engine.simulation import SimulationInstructionService
from standard_knowledge_service_v2.instruction_engine.template_library import TemplateLibrary


@pytest.mark.parametrize('tag', ['IEC', 'MB'])
@pytest.mark.parametrize('kind', ['FAN', 'PUMP'])
@pytest.mark.parametrize('action', ['start', 'stop'])
def test_cooling_templates_generation_only(tag, kind, action):
    service = SimulationInstructionService()
    key = f'SIM-{tag}-{kind}-01'
    profile = service.devices[key]
    before = deepcopy(service.states)
    result = service.generate(key, action, profile['runtime_facts'])
    assert result.payload
    assert 'expected_feedback' not in result.payload
    assert service.states == before
    assert not result.dispatch_allowed
    assert TemplateLibrary().find(profile['scenario'], action, profile['device_type'], profile['protocol'])
    if tag == 'MB':
        assert result.payload['function_code'] == 5
        assert result.payload['encoded_value'] == (0xFF00 if action == 'start' else 0)


@pytest.mark.parametrize('field,value', [('maintenance_lockout', 1), ('device_fault', 1), ('power_available', 0), ('start_permission', 0)])
def test_cooling_start_interlocks(field, value):
    service = SimulationInstructionService()
    key = 'SIM-MB-FAN-01'
    facts = deepcopy(service.devices[key]['runtime_facts'])
    facts[field] = value
    assert not service.generate(key, 'start', facts).payload


def test_cooling_stop_needs_redundant_cooling_fact():
    service = SimulationInstructionService()
    facts = deepcopy(service.devices['SIM-IEC-PUMP-01']['runtime_facts'])
    for value in (0, None):
        facts['redundant_cooling_available'] = value
        assert not service.generate('SIM-IEC-PUMP-01', 'stop', facts).payload
    del facts['redundant_cooling_available']
    assert not service.generate('SIM-IEC-PUMP-01', 'stop', facts).payload


@pytest.mark.parametrize('tag', ['IEC', 'MB'])
@pytest.mark.parametrize('action,parameter,value,address', [
    ('adjust_reactive_power', 'reactive_power_kvar', 120.5, 101),
    ('regulate_voltage', 'voltage_v', 400.5, 102),
])
def test_setpoint_uses_own_mapping(tag, action, parameter, value, address):
    service = SimulationInstructionService()
    key = f'SIM-{tag}-INVERTER-01'
    profile = service.devices[key]
    result = service.generate(key, action, profile['runtime_facts'], {parameter: value})
    assert 'expected_feedback' not in result.payload
    assert result.payload['engineering_value'] == value
    if tag == 'MB':
        assert result.payload['function_code'] == 6
        assert result.payload['address'] == address
        assert result.payload['encoded_value'] == round(value * 10)
    else:
        assert result.payload['ctlVal'] == value
        assert result.payload['object_reference'] != profile['mapping']['object_reference']


@pytest.mark.parametrize('value', [-1, 501, True, float('nan'), float('inf'), 100.01])
def test_invalid_modbus_reactive_setpoints(value):
    service = SimulationInstructionService()
    key = 'SIM-MB-INVERTER-01'
    assert not service.generate(key, 'adjust_reactive_power', service.devices[key]['runtime_facts'], {'reactive_power_kvar': value}).payload


@pytest.mark.parametrize('field', ['grid_connected', 'control_mode_available'])
def test_setpoint_permission_and_mode(field):
    service = SimulationInstructionService()
    key = 'SIM-IEC-INVERTER-01'
    facts = deepcopy(service.devices[key]['runtime_facts'])
    facts[field] = 0
    assert not service.generate(key, 'regulate_voltage', facts, {'voltage_v': 400}).payload


def test_extra_parameters_and_wrong_scenario_blocked():
    service = SimulationInstructionService()
    key = 'SIM-MB-FAN-01'
    facts = service.devices[key]['runtime_facts']
    assert not service.generate(key, 'start', facts, {'unexpected': 1}).payload
    assert not service.generate(key, 'start', facts, scenario='power_grid_operation').payload


def test_new_templates_do_not_claim_source_authorization():
    service = SimulationInstructionService()
    for key, profile in service.devices.items():
        for action, template in profile['actions'].items():
            if profile['device_type'] in ('cooling_fan', 'oil_pump') or action in ('adjust_reactive_power', 'regulate_voltage'):
                assert not template['source_rule_ids']
                assert template['source_scope'] == 'synthetic_test_fixture_pending_source_binding'


def test_fixed_examples_are_loadable_and_match_generation_outcomes():
    service = SimulationInstructionService()
    example_path = Path(__file__).resolve().parents[1] / 'configs' / 'instruction_template_examples.json'
    examples = json.loads(example_path.read_text(encoding='utf-8'))['examples']
    before = deepcopy(service.states)
    for index, example in enumerate(examples):
        result = service.generate(example['device_id'], example['action'], example['facts'], example['parameters'])
        assert bool(result.payload) == (index < 4)
        assert not result.dispatch_allowed
    assert service.states == before
