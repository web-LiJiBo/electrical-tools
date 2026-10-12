"""Supplement fixture tests: successful payloads never authorize dispatch."""
from copy import deepcopy
import json

import pytest

from standard_knowledge_service_v2.instruction_engine.simulation import DEFAULT_PROFILES, SimulationInstructionService
from standard_knowledge_service_v2.instruction_engine.template_library import TemplateLibrary

EXAMPLES = json.loads(DEFAULT_PROFILES.with_name('instruction_template_examples_supplement.json').read_text(encoding='utf-8'))['examples']


@pytest.mark.parametrize('example', EXAMPLES, ids=lambda e: e['device_id'] + ':' + e['action'])
def test_supplement_payload_and_lookup(example):
    service = SimulationInstructionService()
    before = deepcopy(service.states)
    result = service.generate(example['device_id'], example['action'], example['facts'], example['parameters'])
    assert result.payload, result.explanation
    profile = service.devices[example['device_id']]
    template = profile['actions'][example['action']]
    assert TemplateLibrary().find(profile['scenario'], example['action'], profile['device_type'], profile['protocol'])
    assert not result.dispatch_allowed
    assert service.states == before
    assert not result.payload['source_rule_ids']
    assert result.payload['source_scope'] == 'synthetic_test_fixture_pending_source_binding'
    assert result.payload['expected_feedback']['state_key'] in profile['initial_state']
    value = example['parameters'][template['parameter']] if template.get('parameter') else template['value']
    assert result.payload['expected_feedback']['value'] == value
    if profile['protocol'] == 'Modbus':
        assert result.payload['function_code'] == (6 if template.get('parameter') else 5)
        assert result.payload['encoded_value'] == (value * 10 if template.get('parameter') else 0xFF00 if value else 0)
    else:
        assert result.payload['ctlVal'] == value


@pytest.mark.parametrize('example', EXAMPLES, ids=lambda e: e['device_id'] + ':' + e['action'])
def test_each_condition_and_interlock_fails_closed(example):
    service = SimulationInstructionService()
    template = service.devices[example['device_id']]['actions'][example['action']]
    checks = [dict(parameter=template['condition'].split()[0], operator='==', value=1)] + template['constraints']
    for check in checks:
        for missing in (True, False):
            facts = deepcopy(example['facts'])
            field = check['parameter']
            if missing:
                del facts[field]
            else:
                facts[field] = check['value'] - 1 if check['operator'] == '>=' else 1 - check['value']
            candidate = service.generate(example['device_id'], example['action'], facts, example['parameters'])
            assert not candidate.payload, (example, check, missing)
            assert not candidate.dispatch_allowed


@pytest.mark.parametrize('example', [e for e in EXAMPLES if e['parameters']], ids=lambda e: e['device_id'] + ':' + e['action'])
def test_numeric_ranges_types_and_boundaries(example):
    service = SimulationInstructionService()
    template = service.devices[example['device_id']]['actions'][example['action']]
    parameter = template['parameter']
    for value in (template['minimum'], template['maximum']):
        assert service.generate(example['device_id'], example['action'], example['facts'], {parameter: value}).payload
    for value in (-1, 251, True, float('nan'), float('inf')):
        assert not service.generate(example['device_id'], example['action'], example['facts'], {parameter: value}).payload
    assert not service.generate(example['device_id'], example['action'], example['facts'], {}).payload


def test_custom_profile_does_not_implicitly_load_supplement(tmp_path):
    profile = tmp_path / 'isolated.json'
    profile.write_text(json.dumps({'simulation_only': True, 'devices': []}), encoding='utf-8')
    assert not SimulationInstructionService(profile).devices


def test_supplement_does_not_share_unrelated_action_points():
    service = SimulationInstructionService()
    for tag in ('IEC', 'MB'):
        d = service.devices[f'SIM-{tag}-BESS-01']
        field = 'address' if tag == 'MB' else 'object_reference'
        points = [d['actions'][a]['mapping'][field] for a in ('start', 'alarm', 'adjust_active_power', 'limit_power')]
        assert len(set(points)) == len(points)
