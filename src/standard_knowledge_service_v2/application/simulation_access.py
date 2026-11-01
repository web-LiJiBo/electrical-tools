"""One lazily constructed simulation runtime per application, with isolated sessions."""
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
