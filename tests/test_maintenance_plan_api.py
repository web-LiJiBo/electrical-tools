"""Plans are server-authored; HTTP can only request an already reviewed step."""
from types import SimpleNamespace
import asyncio
import httpx
from fastapi import FastAPI
from standard_knowledge_service_v2.api.simulation_routes import register_simulation_routes
from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime


class Client:
    def __init__(self, app):
        self.app = app

    def request(self, method, path, **kwargs):
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test') as client:
                return await client.request(method, path, **kwargs)
        return asyncio.run(send())

    def get(self, path):
        return self.request('GET', path)

    def post(self, path, **kwargs):
        return self.request('POST', path, **kwargs)


def test_plan_http_blocks_future_step_and_preserves_conditions_after_feedback():
    runtime = SimulationRuntime()
    sid = runtime.create_session()['session_id']
    steps = [{'device_id': device_id, 'action': 'start', 'parameters': {}, 'order': i + 1,
              'conditions': ['device_fault == 0']}
             for i, device_id in enumerate(['SIM-IEC-FAN-01', 'SIM-MB-FAN-01'])]
    plan = runtime.create_plan(sid, steps, expected_version=0)
    app = FastAPI()
    register_simulation_routes(app, SimpleNamespace(facade=SimpleNamespace(simulation_runtime=runtime)))
    api = Client(app)
    route = f"/simulation/sessions/{sid}/plans/{plan['plan_id']}"
    assert api.get(route).status_code == 200
    early = api.post(route + '/preview', json={'step': 2, 'expected_version': 0})
    assert early.json()['status'] == 'blocked'
    first = plan['steps'][0]['preview']
    assert api.post(f'/simulation/sessions/{sid}/execute', json={
        'command_id': first['command_id'], 'expected_version': 0}).json()['status'] == 'succeeded'
    assert api.get(route).json()['next_step'] == 2
    second = api.post(route + '/preview', json={'step': 2, 'expected_version': 1}).json()
    assert second['status'] == 'generated'
    assert second['conditions'] == ['device_fault == 0']
    for invalid in ({'step': True, 'expected_version': 1}, {'step': 2, 'expected_version': True},
                    {'step': 2, 'expected_version': 1, 'conditions': []}):
        assert api.post(route + '/preview', json=invalid).status_code == 422
    foreign = runtime.create_session()['session_id']
    assert api.get(route.replace(sid, foreign)).status_code == 404
    assert api.post(route.replace(sid, foreign) + '/preview', json={'step': 2, 'expected_version': 1}).status_code == 404
