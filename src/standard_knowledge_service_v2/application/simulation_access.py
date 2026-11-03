"""One lazily constructed simulation runtime per application, with isolated sessions."""
from copy import deepcopy
from threading import RLock

_runtime_lock = RLock()


def simulation_runtime(pipeline):
    with _runtime_lock:
        runtime = getattr(pipeline, 'simulation_runtime', None)
        if runtime is None:
            from ..instruction_engine.simulation_catalog import SimulationCatalog
            from ..instruction_engine.simulation_runtime import SimulationRuntime
            session = getattr(pipeline, 'simulation_session', None)
            catalog = SimulationCatalog(legacy_service=session.service if session else None)
            from pathlib import Path
            root = Path(__file__).resolve().parents[3]
            runtime = SimulationRuntime(catalog, event_path=root / 'data/simulation/events.jsonl')
            pipeline.simulation_runtime = runtime
        return runtime


def default_session(pipeline):
    with _runtime_lock:
        runtime = simulation_runtime(pipeline)
        identifier = getattr(pipeline, '_default_simulation_session_id', None)
        if not identifier:
            identifier = runtime.create_session()['session_id']
            pipeline._default_simulation_session_id = identifier
        return runtime.snapshot(identifier)


def view_snapshot(pipeline, request, snapshot):
    """Filter one shared simulation world without making another state copy."""
    name = request.parameters.get('simulation_scenario_id')
    if name is None:
        return snapshot
    runtime = simulation_runtime(pipeline)
    if not isinstance(name, str) or name not in runtime.catalog.scenarios:
        raise ValueError('当前业务场景未配置模拟设备')
    profile = runtime.catalog.scenarios[name]
    ids = set(profile['device_ids'])
    if not ids <= {d['device_id'] for d in snapshot['devices']}:
        raise ValueError('模拟会话不包含当前场景设备，请刷新页面建立完整演示会话')
    result = deepcopy(snapshot)
    result['scenario_id'] = name
    result['condition'] = snapshot.get('scenario_conditions', {}).get(name, snapshot['condition'])
    result['devices'] = [device for device in result['devices'] if device['device_id'] in ids]
    return result
