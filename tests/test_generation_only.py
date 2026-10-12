from types import SimpleNamespace
from fastapi import FastAPI
from standard_knowledge_service_v2.api.routes import register_routes
from standard_knowledge_service_v2.instruction_engine.simulation_control import SimulationControlSession

def test_execution_routes_removed():
    app = FastAPI()
    register_routes(app, SimpleNamespace())
    paths = {r.path for r in app.routes}
    assert '/analyze' in paths and '/generate-instruction' in paths
    assert '/simulation/state' in paths
    assert not {'/simulation/confirm', '/simulation/run', '/simulation/reset', '/simulation/tasks/{task_id}', '/simulation/cases'} & paths

def test_no_task_or_execution_methods():
    session = SimulationControlSession()
    assert not any(hasattr(session, name) for name in ('confirm', 'control', 'task', 'tasks', 'reset'))
    assert not hasattr(session.service, 'run')
    state = session.snapshot()
    state['devices'][0]['state']['active_power_mw'] = 0
    assert session.snapshot()['devices'][0]['state']['active_power_mw'] == 100
