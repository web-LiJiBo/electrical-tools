import pytest

from standard_knowledge_service_v2.contracts import AnalysisRequest
from test_api_first_analysis import app_for


@pytest.mark.parametrize('query', [
    '启动主变1的冷却风机和主变2的冷却风机',
    '启动主变1和主变2的冷却风机',
    '启动SIM-IEC-FAN-01和主变2的冷却风机',
])
def test_parallel_fans_have_two_previews_without_mutating_state(monkeypatch, query):
    app, params, before, calls = app_for(monkeypatch, intent='instruction', actions=['start'])
    response = app.analyze(AnalysisRequest(query, parameters=params))
    assert response.status == 'generated'
    items = response.data['simulation_batch']['items']
    assert {i['device_id'] for i in items} == {'SIM-IEC-FAN-01', 'SIM-MB-FAN-01'}
    assert all(i['preview']['status'] == 'generated' for i in items)
    assert len({i['preview']['command_id'] for i in items}) == 2
    assert response.data['candidate_instruction'] is None
    assert response.data['processing']['instruction_status'] == 'generated'
    assert len(calls) == 1
    assert app.simulation_runtime.snapshot(before['session_id']) == before


def test_devices_without_requested_capability_are_individually_blocked(monkeypatch):
    app, params, _, _ = app_for(monkeypatch, intent='instruction', actions=['start'])
    response = app.analyze(AnalysisRequest('启动主变1和主变2', parameters=params))
    batch = response.data['simulation_batch']
    assert batch['status'] == 'blocked'
    assert all(i['preview']['status'] == 'blocked' for i in batch['items'])


def test_independent_interlocks_produce_visible_partial_batch(monkeypatch):
    app, params, before, _ = app_for(monkeypatch, intent='instruction', actions=['start'])
    runtime = app.simulation_runtime
    runtime._sessions[before['session_id']].devices['SIM-MB-FAN-01']['runtime_facts']['maintenance_lockout'] = 1
    before = runtime.snapshot(before['session_id'])
    response = app.analyze(AnalysisRequest('启动主变1和主变2的冷却风机', parameters=params))
    batch = response.data['simulation_batch']
    assert batch['status'] == 'partial'
    assert (batch['generated_count'], batch['blocked_count']) == (1, 1)
    by_id = {row['device_id']: row['preview'] for row in batch['items']}
    assert by_id['SIM-IEC-FAN-01']['status'] == 'generated'
    assert by_id['SIM-MB-FAN-01']['status'] == 'blocked'
    assert runtime.snapshot(before['session_id']) == before


def test_conflicting_business_device_list_is_not_a_batch_authorization(monkeypatch):
    app, params, _, _ = app_for(monkeypatch, intent='instruction', actions=['start'])
    response = app.analyze(AnalysisRequest('启动主变1的冷却风机', parameters={
        **params, 'device_ids': ['SIM-MB-FAN-01']}))
    assert response.status == 'uncertain'
    assert not response.data.get('simulation_batch')


@pytest.mark.parametrize('query', [
    '启动主变1的冷却风机和主变99的冷却风机',
    '如果温升超限就启动主变1和主变2的冷却风机',
    '禁止启动主变1和主变2的冷却风机',
    '先启动主变1的冷却风机，再启动主变2的冷却风机',
    '启动冷却风机',
])
def test_unknown_conditional_negated_sequential_or_ambiguous_are_not_batched(monkeypatch, query):
    app, params, _, _ = app_for(monkeypatch, intent='instruction', actions=['start'])
    response = app.analyze(AnalysisRequest(query, parameters=params))
    assert not response.data.get('simulation_batch')
    assert not (response.data.get('candidate_instruction') or {}).get('payload')


def test_each_execution_keeps_version_checks_and_pending_item_can_be_repreviewed(monkeypatch):
    app, params, before, _ = app_for(monkeypatch, intent='instruction', actions=['start'])
    data = app.analyze(AnalysisRequest('启动主变1和主变2的冷却风机', parameters=params)).data
    one, two = data['simulation_batch']['items']
    runtime = app.simulation_runtime
    sid = before['session_id']
    p = one['preview']
    first = runtime.execute(sid, p['command_id'], p['expected_version'])
    assert first['status'] == 'succeeded'
    assert runtime.execute(sid, p['command_id'], p['expected_version']) == first
    p = two['preview']
    assert runtime.execute(sid, p['command_id'], p['expected_version'])['status'] == 'blocked'
    fresh = runtime.preview(sid, two['device_id'], two['action'], two['parameters'])
    assert fresh['expected_version'] == 1
    assert runtime.execute(sid, fresh['command_id'], fresh['expected_version'])['status'] == 'succeeded'
    state = runtime.snapshot(sid)
    assert all(d['state']['running'] for d in state['devices'] if d['device_id'] in {one['device_id'], two['device_id']})


def test_instruction_endpoint_exposes_the_complete_batch(monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from standard_knowledge_service_v2.api.routes import register_routes
    pipeline, params, _, _ = app_for(monkeypatch, intent='instruction', actions=['start'])
    api = FastAPI()
    register_routes(api, SimpleNamespace(facade=pipeline))
    response = TestClient(api).post('/generate-instruction', json={
        'query': '启动主变1和主变2的冷却风机', 'parameters': params})
    assert response.status_code == 200
    assert len(response.json()['simulation_batch']['items']) == 2
    assert response.json()['simulation_session_id'] == params['simulation_session_id']
