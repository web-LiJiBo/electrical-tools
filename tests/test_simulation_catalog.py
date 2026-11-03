"""Reusable catalog behavior; the legacy encoder remains a pure consumer."""
from copy import deepcopy
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from standard_knowledge_service_v2.instruction_engine.simulation import SimulationInstructionService
from standard_knowledge_service_v2.instruction_engine.template_library import TemplateLibrary


def catalog(**kwargs):
    module_name = 'standard_knowledge_service_v2.instruction_engine.simulation_catalog'
    assert importlib.util.find_spec(module_name), 'the reusable simulation catalog is missing'
    return importlib.import_module(module_name).SimulationCatalog(**kwargs)


def test_catalog_preserves_all_legacy_devices_actions_and_mappings():
    old = SimulationInstructionService()
    expanded = catalog()
    assert len(old.devices) == 19
    assert sum(len(d['actions']) for d in old.devices.values()) == 47
    assert len(expanded.devices) == 27  # Original 25 plus two independent fault-isolation breakers.
    for identifier, profile in old.devices.items():
        migrated = expanded.devices[identifier]
        assert migrated['mapping'] == profile['mapping']
        assert migrated['initial_state'].items() >= profile['initial_state'].items()
        for name, action in profile['actions'].items():
            assert migrated['actions'][name].items() >= action.items()
    assert 'SIM-IEC-FEEDER-BREAKER-01' in expanded.devices
    assert 'SIM-MB-FEEDER-BREAKER-01' in expanded.devices


def test_substation_has_two_related_groups_seven_types_and_four_conditions():
    expanded = catalog()
    scenario = expanded.scenarios['substation_maintenance']
    assert len(scenario['device_ids']) == 14
    assert {expanded.devices[x]['device_type'] for x in scenario['device_ids']} == {
        'transformer', 'breaker', 'disconnector', 'earthing_switch', 'cooling_fan', 'oil_pump', 'tap_changer'}
    assert set(scenario['conditions']) == {'normal', 'high_temperature', 'cooling_fault', 'maintenance'}
    assert set(scenario['groups']) == {'A', 'B'}
    for group in scenario['groups'].values():
        assert set(group) == {'transformer', 'breaker', 'disconnector', 'earthing_switch', 'cooling_fan', 'oil_pump', 'tap_changer'}
        assert set(group.values()) <= set(scenario['device_ids'])
    assert scenario['conditions']['maintenance']['SIM-IEC-BREAKER-01']['state']['position'] == 'open'
    assert scenario['conditions']['cooling_fault']['SIM-IEC-FAN-01']['runtime_facts']['device_fault'] == 1
    assert '主变1' in expanded.devices['SIM-TRANSFORMER-01']['aliases']


def test_normal_and_high_temperature_conditions_keep_distinct_measurement_samples():
    expanded = catalog()
    conditions = expanded.scenarios['substation_maintenance']['conditions']
    normal = conditions['normal']['SIM-TRANSFORMER-01']['runtime_facts']
    high = conditions['high_temperature']['SIM-TRANSFORMER-01']['runtime_facts']
    assert normal['winding_hotspot_rise_k'] == 50
    assert normal['top_oil_rise_k'] == 40
    assert normal['winding_average_rise_k'] == 45
    assert high['winding_hotspot_rise_k'] == 85
    assert expanded.devices['SIM-TRANSFORMER-01']['runtime_facts']['winding_hotspot_rise_k'] == 85


@pytest.mark.parametrize('tag', ['IEC', 'MB'])
def test_unbound_fan_action_reuses_template_across_scenario_names_without_mutation(tag):
    expanded = catalog()
    service = expanded.make_service()
    identifier = f'SIM-{tag}-FAN-01'
    before = deepcopy(service.states)
    results = [service.generate(identifier, 'start', expanded.devices[identifier]['runtime_facts'], scenario=name)
               for name in ['substation_maintenance', 'a_different_station']]
    assert all(result.payload for result in results)
    assert results[0].payload['template_id'] == results[1].payload['template_id']
    assert not results[0].payload['source_rule_ids']
    assert service.states == before
    assert all(not result.dispatch_allowed for result in results)
    assert TemplateLibrary().find('a_different_station', 'start', 'cooling_fan', service.devices[identifier]['protocol'])
    assert not TemplateLibrary().find('a_different_station', 'start', 'cooling_fan', 'unknown')
    assert not TemplateLibrary().find('a_different_station', 'start', 'transformer', 'IEC61850')


def test_template_finder_keeps_known_device_capabilities_when_scenario_changes():
    library = TemplateLibrary()
    assert library.find('a_different_station', 'adjust_active_power', 'inverter', 'Modbus')
    assert not library.find('a_different_station', 'start', 'inverter', 'Modbus')
    assert not library.find('a_different_station', 'runback_power', 'cooling_fan', 'IEC61850')


def test_reusable_templates_do_not_embed_instance_or_scenario_bindings():
    expanded = catalog()
    for template in [*expanded.device_templates.values(), *expanded.action_templates.values()]:
        assert not {'device_id', 'scenario', 'scenario_id', 'source_rule_ids'} & template.keys()
        assert 'SIM-' not in json.dumps(template)
    description = expanded.describe()
    assert all(isinstance(description[key], list) for key in ['devices', 'device_templates', 'action_templates', 'scenarios'])
    assert description['simulation_only'] is True
    assert description['dispatch_allowed'] is False
    description['devices'][0]['display_name'] = 'changed by caller'
    assert expanded.devices[description['devices'][0]['device_id']]['display_name'] != 'changed by caller'


def test_every_scenario_action_has_distinct_command_feedback_and_explicit_effects():
    expanded = catalog()
    for identifier in expanded.scenarios['substation_maintenance']['device_ids']:
        device = expanded.devices[identifier]
        assert device['points']
        for name, action in device['actions'].items():
            assert action['template_ref'] in expanded.action_templates
            assert action['simulation_effects']
            feedback = action['feedback_mapping']
            command = {**device['mapping'], **action.get('mapping', {})}
            address_field = 'address' if device['protocol'] == 'Modbus' else 'object_reference'
            assert feedback[address_field] != command[address_field], (identifier, name)
            assert feedback['field'].startswith(('state.', 'runtime_facts.'))


@pytest.mark.parametrize('tag', ['IEC', 'MB'])
def test_new_numeric_tap_actions_encode_bounded_integers(tag):
    expanded = catalog()
    service = expanded.make_service()
    identifier = f'SIM-{tag}-TAP-01'
    facts = {**service.devices[identifier]['initial_state'], **service.devices[identifier]['runtime_facts']}
    generated = service.generate(identifier, 'set_tap', facts, {'tap_position': 9})
    assert generated.payload
    assert generated.payload['engineering_value'] == 9
    assert generated.payload['unit'] == '档'
    for value in [0, 18, True, 8.5]:
        assert not service.generate(identifier, 'set_tap', facts, {'tap_position': value}).payload
    assert service.generate(identifier, 'raise', facts).payload
    assert service.generate(identifier, 'lower', facts).payload


def test_cross_device_interlocks_are_abstract_and_missing_relations_cannot_look_satisfied():
    expanded = catalog()
    disconnector = expanded.devices['SIM-IEC-DISCONNECTOR-01']['actions']['open']
    requirements = disconnector['relation_requirements']
    assert {'role': 'breaker', 'field': 'state.position', 'operator': '==', 'value': 'open'} in requirements
    assert {'role': 'breaker', 'field': 'runtime_facts.current', 'operator': '==', 'value': 0} in requirements
    earthing = expanded.devices['SIM-MB-EARTHING-01']['actions']['close']
    assert {'role': 'disconnector', 'field': 'state.position', 'operator': '==', 'value': 'open'} in earthing['relation_requirements']


def test_earthing_uses_the_branch_voltage_fact_that_breaker_operations_update():
    expanded = catalog()
    breaker = expanded.devices['SIM-IEC-BREAKER-01']
    assert breaker['actions']['trip']['simulation_effects']['runtime_facts']['voltage_present'] == 0
    assert breaker['actions']['close']['simulation_effects']['runtime_facts']['voltage_present'] == 1
    earthing = expanded.devices['SIM-IEC-EARTHING-01']
    assert 'voltage_present' not in earthing['runtime_facts']
    assert {'role': 'breaker', 'field': 'runtime_facts.voltage_present', 'operator': '==', 'value': 0} in earthing['actions']['close']['relation_requirements']


def test_catalog_preserves_session_custom_actions_without_mutating_service():
    service = SimulationInstructionService()
    extra = deepcopy(service.devices['SIM-IEC-FAN-01']['actions']['start'])
    extra['function'] = 'custom_fan_start'
    service.devices['SIM-IEC-FAN-01']['actions']['custom_start'] = extra
    before = deepcopy(service.devices)
    expanded = catalog(legacy_service=service)
    assert expanded.make_service().generate('SIM-IEC-FAN-01', 'custom_start', before['SIM-IEC-FAN-01']['runtime_facts']).payload
    assert service.devices == before


@pytest.mark.parametrize('fault', ['duplicate_id', 'point_collision'])
def test_catalog_rejects_explicit_instance_conflicts(tmp_path, fault):
    config_root = Path(__file__).resolve().parents[1] / 'configs'
    for name in ['device_templates', 'action_templates', 'device_instances', 'scenario_profiles']:
        (tmp_path / f'{name}.json').write_text((config_root / f'{name}.json').read_text(encoding='utf-8'), encoding='utf-8')
    path = tmp_path / 'device_instances.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    if fault == 'duplicate_id':
        data['device_instances'][0]['device_id'] = 'SIM-IEC-FAN-01'
    else:
        data['device_instances'][1]['points']['open_command'] = deepcopy(data['device_instances'][0]['points']['open_command'])
        data['device_instances'][1]['protocol'] = data['device_instances'][0]['protocol']
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError):
        catalog(config_dir=tmp_path)
