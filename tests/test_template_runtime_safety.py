"""Template persistence must agree with the complete, executable runtime catalog."""
from copy import deepcopy
import json
from threading import RLock
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from standard_knowledge_service_v2.api.routes import register_routes
from standard_knowledge_service_v2.instruction_engine import template_editor
from standard_knowledge_service_v2.instruction_engine.simulation import SimulationInstructionService
from standard_knowledge_service_v2.instruction_engine.simulation_catalog import SimulationCatalog
from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime


def alarm(device='SIM-IEC-FAN-01', reference='SIM_EDITOR/CTRL/GGIO1.SPCSO1'):
    mapping = ({'object_reference': reference, 'control_model': 'direct-with-normal-security',
                'service': 'Operate'} if 'IEC' in device else
               {'slave_id': 3, 'address': 10, 'function_code': 5, 'data_type': 'bool'})
    return {'device_id': device, 'action': 'alarm', 'template': {
        'function': 'mock_alarm', 'condition': 'start_permission == 1',
        'constraints': [], 'value': True, 'mapping': mapping},
        'facts': {'start_permission': 1}, 'parameters': {}}


def write_rows(path, rows):
    path.write_text(json.dumps({'simulation_only': True, 'items': rows}), encoding='utf-8')


def application(monkeypatch, path):
    service = SimulationInstructionService()
    runtime = SimulationRuntime(SimulationCatalog(legacy_service=service), event_path=None)
    pipeline = SimpleNamespace(simulation_session=SimpleNamespace(service=service, lock=RLock()),
                               simulation_runtime=runtime)
    original_save = template_editor.save_custom
    monkeypatch.setattr(template_editor, 'save_custom',
                        lambda service, payload, **kwargs: original_save(service, payload, path, **kwargs))
    app = FastAPI()
    register_routes(app, SimpleNamespace(facade=pipeline, audit_store=None))
    return service, runtime, TestClient(app)


def test_http_rejected_collision_leaves_file_service_and_world_unchanged(monkeypatch, tmp_path):
    path = tmp_path / 'templates.json'
    service, runtime, client = application(monkeypatch, path)
    sid = runtime.create_session('all_devices')['session_id']
    assert client.post('/simulation/templates', json=alarm()).status_code == 200
    before_file, before_devices = path.read_bytes(), deepcopy(service.devices)
    before_world = runtime.snapshot(sid)
    before_catalog = runtime.catalog.describe()

    response = client.post('/simulation/templates', json=alarm('SIM-IEC-PUMP-01'))

    assert response.status_code == 422
    assert '冲突' in response.json()['detail']
    assert path.read_bytes() == before_file
    assert service.devices == before_devices
    assert runtime.snapshot(sid) == before_world
    assert runtime.catalog.describe() == before_catalog
    restarted = SimulationInstructionService()
    assert len(template_editor.load_custom(restarted, path)) == 1
    assert SimulationCatalog(legacy_service=restarted).devices


@pytest.mark.parametrize('existing_file', [False, True])
def test_http_publish_failure_rolls_back_file_and_service(monkeypatch, tmp_path, existing_file):
    path = tmp_path / 'templates.json'
    service, runtime, client = application(monkeypatch, path)
    sid = runtime.create_session('all_devices')['session_id']
    if existing_file:
        assert client.post('/simulation/templates', json=alarm()).status_code == 200
    previous = path.read_bytes() if existing_file else None
    before_devices, before_world = deepcopy(service.devices), runtime.snapshot(sid)
    monkeypatch.setattr(runtime, 'refresh_catalog',
                        lambda catalog: (_ for _ in ()).throw(ValueError('运行目录发布失败')))

    response = client.post('/simulation/templates', json=alarm(
        'SIM-IEC-PUMP-01', 'SIM_EDITOR_PUMP/CTRL/GGIO1.alarm'))

    assert response.status_code == 422
    assert (path.read_bytes() if path.exists() else None) == previous
    assert service.devices == before_devices
    assert runtime.snapshot(sid) == before_world


def test_file_commit_failure_does_not_publish_or_change_service(monkeypatch, tmp_path):
    path = tmp_path / 'templates.json'
    service = SimulationInstructionService()
    template_editor.save_custom(service, alarm(), path)
    runtime = SimulationRuntime(SimulationCatalog(legacy_service=service))
    sid = runtime.create_session('all_devices')['session_id']
    before_file, before_devices = path.read_bytes(), deepcopy(service.devices)
    before_world, before_catalog = runtime.snapshot(sid), runtime.catalog.describe()
    monkeypatch.setattr(template_editor.os, 'replace',
                        lambda *args: (_ for _ in ()).throw(OSError('文件替换失败')))

    with pytest.raises(OSError, match='文件替换失败'):
        template_editor.save_custom(service, alarm('SIM-IEC-PUMP-01', 'OTHER/CTRL/alarm'),
                                    path, publish=runtime.refresh_catalog)

    assert path.read_bytes() == before_file
    assert service.devices == before_devices
    assert runtime.snapshot(sid) == before_world
    assert runtime.catalog.describe() == before_catalog


def test_feedback_address_failure_is_rejected_before_any_commit(tmp_path):
    service = SimulationInstructionService()
    before = deepcopy(service.devices)
    payload = alarm('SIM-MB-FAN-01')
    payload['template']['mapping']['address'] = 65535
    path = tmp_path / 'templates.json'

    with pytest.raises(ValueError, match='点位地址无效'):
        template_editor.save_custom(service, payload, path)

    assert not path.exists()
    assert service.devices == before


def test_historical_collision_is_quarantined_without_rewriting_file(tmp_path):
    path = tmp_path / 'templates.json'
    write_rows(path, [alarm(), alarm('SIM-IEC-PUMP-01'), alarm('SIM-MB-FAN-01')])
    before = path.read_bytes()
    service = SimulationInstructionService()

    loaded = template_editor.load_custom(service, path, strict=False)

    assert [row['device_id'] for row in loaded] == ['SIM-IEC-FAN-01', 'SIM-MB-FAN-01']
    assert 'alarm' not in service.devices['SIM-IEC-PUMP-01']['actions']
    assert len(service.template_load_errors) == 1
    assert '第2条' in service.template_load_errors[0]
    assert '冲突' in service.template_load_errors[0]
    assert path.read_bytes() == before
    assert SimulationRuntime(SimulationCatalog(legacy_service=service)).create_session('all_devices')


def test_strict_historical_collision_never_partially_mutates_service(tmp_path):
    path = tmp_path / 'templates.json'
    write_rows(path, [alarm(), alarm('SIM-IEC-PUMP-01')])
    service = SimulationInstructionService()
    before = deepcopy(service.devices)

    with pytest.raises(ValueError, match='冲突'):
        template_editor.load_custom(service, path, strict=True)

    assert service.devices == before


def test_new_valid_template_can_be_saved_while_old_bad_row_stays_quarantined(tmp_path):
    path = tmp_path / 'templates.json'
    write_rows(path, [alarm(), alarm('SIM-IEC-PUMP-01')])
    service = SimulationInstructionService()
    template_editor.load_custom(service, path, strict=False)

    result = template_editor.save_custom(service, alarm('SIM-MB-FAN-01'), path)

    assert result['status'] == 'saved'
    restarted = SimulationInstructionService()
    loaded = template_editor.load_custom(restarted, path, strict=False)
    assert len(loaded) == 2
    assert 'alarm' in restarted.devices['SIM-MB-FAN-01']['actions']
    assert 'alarm' not in restarted.devices['SIM-IEC-PUMP-01']['actions']
    assert len(json.loads(path.read_text(encoding='utf-8'))['items']) == 3
    assert SimulationCatalog(legacy_service=restarted).devices


def test_modbus_alarm_saves_and_really_previews_and_executes_in_old_and_new_sessions(monkeypatch, tmp_path):
    path = tmp_path / 'templates.json'
    _, runtime, client = application(monkeypatch, path)
    old = runtime.create_session('all_devices')
    assert client.post('/simulation/templates/test', json=alarm('SIM-MB-FAN-01')).json()['status'] == 'generated'
    saved = client.post('/simulation/templates', json=alarm('SIM-MB-FAN-01'))
    assert saved.status_code == 200
    assert saved.json()['runtime_refreshed'] is True
    for session in (old, runtime.create_session('all_devices')):
        sid = session['session_id']
        preview = client.post(f'/simulation/sessions/{sid}/preview', json={
            'device_id': 'SIM-MB-FAN-01', 'action': 'alarm', 'parameters': {}}).json()
        assert preview['status'] == 'generated', preview
        execution = client.post(f'/simulation/sessions/{sid}/execute', json={
            'command_id': preview['command_id'], 'expected_version': preview['expected_version']}).json()
        assert execution['status'] == 'succeeded'
        assert execution['feedback']['point']['data_type'] == 'bool'
        assert execution['feedback']['encoded_value'] is True
        device = next(d for d in execution['after']['devices'] if d['device_id'] == 'SIM-MB-FAN-01')
        assert device['state']['alarm_active'] is True


def test_editor_probe_rejects_cross_device_point_collision():
    service = SimulationInstructionService()
    service.devices['SIM-IEC-FAN-01']['actions']['alarm'] = alarm()['template']
    before = deepcopy(service.devices)
    with pytest.raises(ValueError, match='冲突'):
        template_editor.test_template(service, alarm('SIM-IEC-PUMP-01'))
    assert service.devices == before
