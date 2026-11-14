"""Explicit, local-only simulation endpoints. Analysis never calls execution."""
from fastapi import HTTPException

from ..application.simulation_access import simulation_runtime


def register_simulation_routes(app, application):
    def runtime():
        return simulation_runtime(application.facade)

    def fields(payload, allowed):
        if not isinstance(payload, dict) or set(payload) - set(allowed):
            raise ValueError('请求包含不支持的字段')

    def string(payload, key, default=None):
        value = payload.get(key, default)
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise ValueError(f'{key}须为非空文本')
        return value

    def perform(function):
        try:
            return function()
        except KeyError as exc:
            raise HTTPException(404, '模拟会话、设备或命令不存在') from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get('/simulation/catalog')
    def catalog():
        return runtime().catalog.describe()

    @app.post('/simulation/sessions')
    def create(payload: dict):
        def run():
            fields(payload, {'scenario_id', 'device_ids', 'condition'})
            scenario = string(payload, 'scenario_id', 'substation_maintenance')
            condition = string(payload, 'condition', 'normal')
            ids = payload.get('device_ids')
            if ids is not None and (not isinstance(ids, list) or not ids
                    or not all(isinstance(v, str) and v.startswith('SIM-') for v in ids)):
                raise ValueError('device_ids须为已登记模拟设备编号的非空数组')
            if ids and any(v not in runtime().catalog.devices for v in ids):
                raise ValueError('device_ids包含未登记模拟设备')
            return runtime().create_session(scenario, ids, condition)
        return perform(run)

    @app.get('/simulation/sessions/{session_id}')
    def state(session_id: str):
        return perform(lambda: runtime().snapshot(session_id))

    @app.post('/simulation/sessions/{session_id}/preview')
    def preview(session_id: str, payload: dict):
        def run():
            fields(payload, {'device_id', 'action', 'parameters'})
            device = string(payload, 'device_id')
            action = string(payload, 'action')
            params = payload.get('parameters', {})
            if not isinstance(params, dict):
                raise ValueError('parameters须为JSON对象')
            return runtime().preview(session_id, device, action, params)
        return perform(run)

    @app.post('/simulation/sessions/{session_id}/execute')
    def execute(session_id: str, payload: dict):
        def run():
            fields(payload, {'command_id', 'expected_version'})
            command = string(payload, 'command_id')
            version = payload.get('expected_version')
            if type(version) is not int or version < 0:
                raise ValueError('expected_version须为非负整数')
            return runtime().execute(session_id, command, version)
        return perform(run)

    @app.get('/simulation/sessions/{session_id}/plans/{plan_id}')
    def plan(session_id: str, plan_id: str):
        return perform(lambda: runtime().plan_snapshot(session_id, plan_id))

    @app.post('/simulation/sessions/{session_id}/plans/{plan_id}/preview')
    def plan_preview(session_id: str, plan_id: str, payload: dict):
        def run():
            fields(payload, {'step', 'expected_version'})
            step, version = payload.get('step'), payload.get('expected_version')
            if type(step) is not int or step < 1:
                raise ValueError('step须为正整数')
            if type(version) is not int or version < 0:
                raise ValueError('expected_version须为非负整数')
            return runtime().preview_plan_step(session_id, plan_id, step, expected_version=version)
        return perform(run)

    @app.post('/simulation/sessions/{session_id}/condition')
    def condition(session_id: str, payload: dict):
        def run():
            fields(payload, {'condition', 'scenario_id'})
            scene = string(payload, 'scenario_id') if 'scenario_id' in payload else None
            return runtime().set_condition(session_id, string(payload, 'condition'), scenario_id=scene)
        return perform(run)

    @app.post('/simulation/sessions/{session_id}/reset')
    def reset(session_id: str, payload: dict):
        return perform(lambda: (fields(payload, set()), runtime().reset(session_id))[1])

    @app.get('/simulation/sessions/{session_id}/events')
    def events(session_id: str):
        return perform(lambda: runtime().events(session_id))
