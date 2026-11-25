from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from standard_knowledge_service_v2.api.simulation_routes import register_simulation_routes
from standard_knowledge_service_v2.application.simulation_query import answer_simulation_query
from standard_knowledge_service_v2.decomposition.intent_classifier import IntentClassifier
from standard_knowledge_service_v2.instruction_engine import device_import
from standard_knowledge_service_v2.instruction_engine.simulation_catalog import SimulationCatalog
from standard_knowledge_service_v2.instruction_engine.simulation_control import SimulationControlSession
from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime


from wire_fixtures import import_wires, iec_wire

def test_import_api_validates_then_publishes_whole_batch_and_loads_it_after_restart(tmp_path, monkeypatch):
    path = tmp_path / 'imported_devices.json'
    monkeypatch.setattr(device_import, 'IMPORT_PATH', path)
    session = SimulationControlSession()
    runtime = SimulationRuntime(SimulationCatalog(legacy_service=session.service))
    before = runtime.create_session('all_devices')
    scoped = runtime.create_session('substation_maintenance')
    isolated = runtime.create_session('substation_maintenance', ['SIM-IEC-FAN-01'])
    runtime.apply_fact_inputs(before['session_id'], [
        {'device_id': 'SIM-IEC-FAN-01', 'field': 'state.running', 'value': True},
    ], expected_version=before['version'])
    before = runtime.snapshot(before['session_id'])
    app = FastAPI()
    register_simulation_routes(app, SimpleNamespace(facade=SimpleNamespace(simulation_runtime=runtime, simulation_session=session)))
    api = TestClient(app)
    base = '/simulation/device-import'
    normal = import_wires(api.get(base).json()['sample'])
    assert api.post(base + '/validate', json={'devices': [normal]},
                    headers={'origin': 'https://unrelated.example'}).status_code == 403
    assert api.post(base + '/validate', content=b' ' * (device_import.MAX_FILE_SIZE + 1)).status_code == 413
    locked = deepcopy(normal)
    locked.update(device_id='SIM-IMPORT-FAN-02', display_name='测试闭锁风机')
    locked['initial_values']['maintenance_lockout'] = True
    locked = import_wires(locked)

    duplicate = api.post(base + '/validate', json={'devices': [normal, normal]}).json()
    assert duplicate['status'] == 'invalid' and duplicate['errors'][0]['row'] == 2
    assert not path.exists() and normal['device_id'] not in runtime.catalog.devices
    invalid = deepcopy(locked)
    invalid['initial_values']['maintenance_lockout'] = 1
    assert api.post(base + '/validate', json={'devices': [normal, invalid]}).json()['status'] == 'invalid'

    rows = [normal, locked]
    preview = api.post(base + '/validate', json={'devices': rows}).json()
    assert preview['status'] == 'validated' and not path.exists()
    bad_token = api.post(base + '/publish', json={'devices': rows, 'revision': 'stale'})
    assert bad_token.status_code == 422 and not path.exists()
    request = {'devices': rows, 'revision': preview['revision']}
    assert api.post(base + '/publish', json=request).json()['status'] == 'published'
    assert api.post(base + '/publish', json=request).json()['status'] == 'invalid'
    assert path.exists()
    for old in (before, scoped, isolated):
        with pytest.raises(KeyError):
            runtime.snapshot(old['session_id'])
    updated = runtime.create_session('all_devices')
    assert {row['device_id'] for row in rows} <= {d['device_id'] for d in updated['devices']}
    catalog = api.get('/simulation/catalog').json()
    scenario = next(item for item in catalog['scenarios'] if item['scenario_id'] == 'substation_maintenance')
    assert {row['device_id'] for row in rows} <= set(scenario['device_ids'])
    assert runtime.catalog.devices[normal['device_id']]['aliases'] == [normal['display_name']]
    with pytest.raises(KeyError):
        runtime.preview(before['session_id'], normal['device_id'], 'start', {})
    fresh = runtime.create_session('all_devices')['session_id']
    assert runtime.preview(fresh, normal['device_id'], 'start', {})['status'] == 'generated'
    assert runtime.preview(fresh, locked['device_id'], 'start', {})['status'] == 'blocked'
    restored = SimulationControlSession()
    assert {row['device_id'] for row in rows} <= restored.service.devices.keys()


def test_publication_failure_rolls_back_and_unreadable_store_keeps_builtin_devices(tmp_path, monkeypatch):
    path = tmp_path / 'imported_devices.json'
    monkeypatch.setattr(device_import, 'IMPORT_PATH', path)
    session = SimulationControlSession()
    runtime = SimulationRuntime(SimulationCatalog(legacy_service=session.service))
    row = import_wires(device_import.options(session.service)['sample'])
    preview = device_import.process(session, runtime, [row])

    def fail(_catalog):
        raise OSError('mock publication error')

    monkeypatch.setattr(runtime, 'refresh_catalog', fail)
    with pytest.raises(OSError, match='mock publication error'):
        device_import.process(session, runtime, [row], publish=True, revision=preview['revision'])
    assert not path.exists() and row['device_id'] not in session.service.devices

    path.write_text('damaged', encoding='utf-8')
    restarted = SimulationControlSession()
    assert device_import.BLUEPRINT in restarted.service.devices
    assert device_import.options(restarted.service)['load_error']
    with pytest.raises(ValueError, match='无法加载'):
        device_import.process(restarted, runtime, [row])


def test_manually_configured_dispatch_device_is_saved_and_available_to_queries(tmp_path, monkeypatch):
    path = tmp_path / 'imported_devices.json'
    monkeypatch.setattr(device_import, 'IMPORT_PATH', path)
    session = SimulationControlSession()
    runtime = SimulationRuntime(SimulationCatalog(legacy_service=session.service))
    snapshot = runtime.create_session('all_devices')
    facade = SimpleNamespace(simulation_runtime=runtime, simulation_session=session)
    app = FastAPI()
    register_simulation_routes(app, SimpleNamespace(facade=facade))
    api = TestClient(app)
    base = '/simulation/device-import'
    options = api.get(base).json()['manual_configuration']
    assert 'dispatch_unit' in options['device_types']
    identifier = 'SIM-IEC-DISPATCH-02'
    row = {
        'device_id': identifier, 'display_name': '模拟调度机组2', 'scenario_id': 'power_grid_operation',
        'device_type': 'dispatch_unit', 'template_id': 'manual_iec61850',
        'fields': [
            {'key': 'active_power_mw', 'label': '有功出力', 'section': 'state', 'type': 'number',
             'unit': 'MW', 'value': 100},
            {'key': 'control_permission', 'label': '控制许可', 'section': 'runtime_facts', 'type': 'boolean',
             'unit': '', 'value': True},
            {'key': 'maintenance_lockout', 'label': '检修闭锁', 'section': 'runtime_facts', 'type': 'boolean',
             'unit': '', 'value': False},
        ],
        'actions': [{'action': 'adjust_active_power', 'result_field': 'active_power_mw',
                     'minimum': 0, 'maximum': 200, 'conditions': [
                         {'field': 'control_permission', 'operator': '==', 'value': True},
                         {'field': 'maintenance_lockout', 'operator': '==', 'value': False},
                     ]}],
    }
    row['wire'] = iec_wire('IMPORT_DISPATCH_02', 'active_power_mw', action='adjust_active_power', numeric=True)
    invalid = deepcopy(row)
    invalid['fields'][0]['value'] = '100'
    assert api.post(base + '/validate', json={'devices': [invalid]}).json()['status'] == 'invalid'
    invalid = deepcopy(row)
    invalid['actions'][0]['conditions'][0]['field'] = 'unknown'
    assert api.post(base + '/validate', json={'devices': [invalid]}).json()['status'] == 'invalid'
    assert not path.exists()
    review = api.post(base + '/validate', json={'devices': [row]}).json()
    assert review['status'] == 'validated', review
    assert not path.exists()
    saved = api.post(base + '/publish', json={'devices': [row], 'revision': review['revision']}).json()
    assert saved['status'] == 'published', saved
    assert path.exists()
    assert identifier in runtime.catalog.scenarios['power_grid_operation']['device_ids']
    assert runtime.catalog.devices[identifier]['display_name'] == row['display_name']
    with pytest.raises(KeyError):
        runtime.snapshot(snapshot['session_id'])
    sid = runtime.create_session('all_devices')['session_id']
    query = '请把模拟调度机组2的有功功率调整到115 MW'
    request = SimpleNamespace(query=query, parameters={'simulation_mode': True, 'simulation_session_id': sid,
                                                        'simulation_scenario_id': 'power_grid_operation'})
    status, result, *_ = answer_simulation_query(facade, request, intent=IntentClassifier().classify(query))
    assert status == 'generated', result
    preview = result['simulation_preview']
    assert preview['expected_changes'][identifier]['state']['active_power_mw'] == 115
    old = next(d for d in runtime.snapshot(sid)['devices'] if d['device_id'] == identifier)
    assert old['state']['active_power_mw'] == 100
    profile = runtime.catalog.devices[identifier]
    action = profile['actions']['adjust_active_power']
    assert action['feedback_mapping']['object_reference'] != action['mapping']['object_reference']
    assert runtime.preview(sid, identifier, 'adjust_active_power', {'active_power_mw': 220})['status'] == 'blocked'
    runtime.apply_fact_inputs(sid, [{'device_id': identifier, 'field': 'runtime_facts.control_permission',
                                     'value': False}], expected_version=runtime.snapshot(sid)['version'])
    status, result, *_ = answer_simulation_query(facade, request, intent=IntentClassifier().classify(query))
    assert status == 'uncertain' and result['simulation_preview']['status'] == 'blocked'
    restarted = SimulationControlSession()
    assert restarted.service.devices[identifier]['initial_state']['active_power_mw'] == 100
    assert restarted.facts[identifier]['control_permission'] is True
