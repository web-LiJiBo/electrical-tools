from types import SimpleNamespace
import pytest
from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime


def test_publication_invalidates_old_world_commands_and_default_reference():
    from standard_knowledge_service_v2.application.simulation_access import invalidate_simulation_sessions, default_session
    runtime=SimulationRuntime();session=runtime.create_session('all_devices');sid=session['session_id']
    command=runtime.preview(sid,'SIM-IEC-FAN-01','start',{})
    assert command['status']=='generated'
    pipeline=SimpleNamespace(simulation_runtime=runtime,_default_simulation_session_id=sid)
    old=runtime.configuration_revision
    result=invalidate_simulation_sessions(pipeline)
    assert result['requires_reanalysis'] is True and result['configuration_revision']!=old
    with pytest.raises(KeyError):runtime.snapshot(sid)
    with pytest.raises(KeyError):runtime.message_parameters(sid,command['command_id'],command['expected_version'])
    assert default_session(pipeline)['session_id']!=sid


def test_invalid_publish_keeps_session_and_success_requires_new_question(tmp_path,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from standard_knowledge_service_v2.instruction_engine import customization as c
    from standard_knowledge_service_v2.instruction_engine.simulation_control import SimulationControlSession
    from standard_knowledge_service_v2.api.customization_routes import register_customization_routes
    monkeypatch.setattr(c,'CUSTOM_PATH',tmp_path/'customization.json')
    runtime=SimulationRuntime();sid=runtime.create_session('all_devices')['session_id']
    pipeline=SimpleNamespace(simulation_runtime=runtime,simulation_session=SimulationControlSession(),_default_simulation_session_id=sid)
    pipeline.simulation_session.service.states['SIM-IEC-FAN-01']['running']=True
    app=FastAPI();register_customization_routes(app,SimpleNamespace(facade=pipeline));client=TestClient(app)
    view=client.get('/simulation/customization').json();old=runtime.configuration_revision
    bad=client.post('/simulation/customization/publish',json={'state':view['state'],'base_revision':view['base_revision'],'revision':'invalid'}).json()
    assert bad['status']=='invalid' and runtime.configuration_revision==old
    assert runtime.snapshot(sid)
    from test_customization import sample
    payload={'state':sample(),'base_revision':view['base_revision']}
    checked=client.post('/simulation/customization/validate',json=payload).json();assert checked['status']=='validated'
    saved=client.post('/simulation/customization/publish',json={**payload,'revision':checked['revision']}).json()
    assert saved['status']=='published' and saved['requires_reanalysis']
    assert pipeline.simulation_session.service.states['SIM-IEC-FAN-01']['running'] is False
    assert client.get('/simulation/configuration').json()['configuration_revision']==saved['configuration_revision']
    with pytest.raises(KeyError):runtime.snapshot(sid)
    # Saving exactly the published configuration must not invalidate another world.
    view=client.get('/simulation/customization').json()
    fresh=runtime.create_session('all_devices')['session_id'];pipeline._default_simulation_session_id=fresh
    old_revision=runtime.configuration_revision;old_file=c.CUSTOM_PATH.stat().st_mtime_ns
    payload={'state':view['state'],'base_revision':view['base_revision']}
    checked=client.post('/simulation/customization/validate',json=payload).json()
    saved=client.post('/simulation/customization/publish',json={**payload,'revision':checked['revision']}).json()
    assert saved['status']=='published' and saved['changed'] is False
    assert saved['requires_reanalysis'] is False and runtime.configuration_revision==old_revision
    assert runtime.snapshot(fresh) and pipeline._default_simulation_session_id==fresh
    assert c.CUSTOM_PATH.stat().st_mtime_ns==old_file
