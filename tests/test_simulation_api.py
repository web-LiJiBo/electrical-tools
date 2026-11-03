from types import SimpleNamespace
import asyncio
import json

from fastapi import FastAPI

from standard_knowledge_service_v2.api.routes import register_routes


def client():
    app = FastAPI()
    register_routes(app, SimpleNamespace(facade=SimpleNamespace(), audit_store=None))
    class Client:
        def request(self, method, path, payload=None):
            async def run():
                sent = []
                body = json.dumps(payload).encode() if payload is not None else b''
                async def receive():
                    return {'type': 'http.request', 'body': body, 'more_body': False}
                async def send(message):
                    sent.append(message)
                scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
                         'method': method, 'path': path, 'raw_path': path.encode(),
                         'query_string': b'', 'root_path': '', 'scheme': 'http',
                         'headers': [(b'content-type', b'application/json')],
                         'server': ('test', 80), 'client': ('test', 1)}
                await app(scope, receive, send)
                status = next(m['status'] for m in sent if m['type'] == 'http.response.start')
                data = b''.join(m.get('body', b'') for m in sent if m['type'] == 'http.response.body')
                return SimpleNamespace(status_code=status, json=lambda: json.loads(data))
            return asyncio.run(run())
        def get(self, path):
            return self.request('GET', path)
        def post(self, path, *, json):
            return self.request('POST', path, json)
    return Client()


def test_catalog_and_explicit_execution_api():
    api = client()
    catalog = api.get('/simulation/catalog')
    assert catalog.status_code == 200
    assert len(catalog.json()['devices']) >= 25
    response = api.post('/simulation/sessions', json={})
    assert response.status_code == 200
    session = response.json()
    sid = session['session_id']
    before = api.get(f'/simulation/sessions/{sid}').json()
    preview = api.post(f'/simulation/sessions/{sid}/preview', json={
        'device_id': 'SIM-IEC-FAN-01', 'action': 'start', 'parameters': {}}).json()
    assert preview['status'] == 'generated'
    assert api.get(f'/simulation/sessions/{sid}').json() == before
    result = api.post(f'/simulation/sessions/{sid}/execute', json={
        'command_id': preview['command_id'], 'expected_version': preview['expected_version']})
    assert result.status_code == 200
    assert result.json()['status'] == 'succeeded'
    after = api.get(f'/simulation/sessions/{sid}').json()
    fan = next(d for d in after['devices'] if d['device_id'] == 'SIM-IEC-FAN-01')
    assert fan['state']['running'] is True
    assert after['dispatch_allowed'] is False


def test_simulation_api_validates_inputs_and_unknown_sessions():
    api = client()
    assert api.get('/simulation/sessions/missing').status_code == 404
    for payload in ({'device_ids': 'SIM-IEC-FAN-01'}, {'device_ids': ['REAL-01']},
                    {'scenario_id': 2}, {'condition': []}):
        assert api.post('/simulation/sessions', json=payload).status_code == 422
    sid = api.post('/simulation/sessions', json={}).json()['session_id']
    assert api.post(f'/simulation/sessions/{sid}/preview', json={
        'device_id': 'SIM-IEC-FAN-01', 'action': 'start', 'parameters': None}).status_code == 422
    assert api.post(f'/simulation/sessions/{sid}/execute', json={
        'command_id': 'fake', 'expected_version': True}).status_code == 422
    assert api.post(f'/simulation/sessions/{sid}/execute', json={
        'command_id': 'fake', 'expected_version': 0, 'address': 1}).status_code == 422


def test_condition_reset_and_event_api():
    api = client()
    session = api.post('/simulation/sessions', json={}).json()
    base = f"/simulation/sessions/{session['session_id']}"
    changed = api.post(base + '/condition', json={'condition': 'maintenance'})
    assert changed.status_code == 200
    assert changed.json()['condition'] == 'maintenance'
    assert api.post(base + '/reset', json={}).status_code == 200
    assert api.get(base + '/events').status_code == 200


def test_aggregate_condition_api_only_changes_the_selected_business_scene():
    api = client()
    session = api.post('/simulation/sessions', json={'scenario_id': 'all_devices'}).json()
    base = f"/simulation/sessions/{session['session_id']}"
    changed = api.post(base + '/condition', json={
        'condition': 'high_temperature', 'scenario_id': 'substation_maintenance'})
    assert changed.status_code == 200
    after = changed.json()
    assert len(after['devices']) == 23
    assert after['scenario_conditions']['substation_maintenance'] == 'high_temperature'
    assert after['version'] == session['version'] + 1
    before_other = [d for d in session['devices'] if d['device_id'] == 'SIM-MB-INVERTER-01']
    assert [d for d in after['devices'] if d['device_id'] == 'SIM-MB-INVERTER-01'] == before_other
    for scene in ('renewable_grid_integration', 'offshore_wind'):
        assert api.post(base + '/condition', json={'condition': 'high_temperature', 'scenario_id': scene}).status_code == 422
    assert api.get(base).json() == after
