"""Explicit, local-only simulation endpoints. Analysis never calls execution."""
import json
import logging
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from ..application.simulation_access import simulation_runtime

logger = logging.getLogger(__name__)


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
        instance = runtime()
        return {**instance.catalog.describe(), 'configuration_revision': instance.configuration_revision}

    @app.get('/simulation/device-import')
    def device_import_options():
        from ..instruction_engine.device_import import options
        session = application.facade.simulation_session
        with session.lock:
            return options(session.service)

    async def import_devices(request, publish=False):
        from ..instruction_engine.device_import import MAX_FILE_SIZE, process

        origin = request.headers.get('origin')
        if origin:
            try:
                parsed = urlsplit(origin)
                allowed = parsed.scheme in ('http', 'https') and parsed.hostname in ('localhost', '127.0.0.1', '::1')
            except ValueError:
                allowed = False
            if not allowed:
                raise HTTPException(403, '模拟设备导入仅允许本机页面发起。')

        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_FILE_SIZE:
                raise HTTPException(413, '设备导入请求超过大小限制。')
            body.extend(chunk)
        try:
            payload = json.loads(body)
        except (ValueError, RecursionError) as exc:
            raise HTTPException(422, '导入请求必须为有效 JSON。') from exc

        def run():
            fields(payload, {'devices', 'revision'} if publish else {'devices'})
            if publish:
                string(payload, 'revision')
            with application.facade.simulation_session.lock:
                result = process(application.facade.simulation_session, runtime(), payload.get('devices'),
                                 publish=publish, revision=payload.get('revision'))
                if publish and result.get('status') == 'published':
                    from ..application.simulation_access import invalidate_simulation_sessions
                    result.update(invalidate_simulation_sessions(application.facade))
                return result

        try:
            return await run_in_threadpool(perform, run)
        except OSError as exc:
            logger.exception('模拟设备导入文件读写失败')
            raise HTTPException(503, '无法读写已发布的设备数据，请检查文件权限或磁盘空间。') from exc

    @app.post('/simulation/device-import/validate')
    async def validate_device_import(request: Request):
        return await import_devices(request)

    @app.post('/simulation/device-import/publish')
    async def publish_device_import(request: Request):
        return await import_devices(request, publish=True)

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

    @app.get('/simulation/sessions/{session_id}/commands/{command_id}/message-parameters')
    def message_parameters(session_id: str, command_id: str, expected_version: int):
        return perform(lambda: runtime().message_parameters(session_id, command_id, expected_version))

    @app.post('/simulation/sessions/{session_id}/commands/{command_id}/message')
    def generate_message(session_id: str, command_id: str, payload: dict):
        def run():
            fields(payload, {'expected_version', 'options'})
            return runtime().generate_message(session_id, command_id, payload.get('expected_version'), payload.get('options'))
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
