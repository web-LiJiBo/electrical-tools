"""Shared customization endpoints; all validation runs in deterministic components."""


def register_customization_routes(app, application):
    from ..instruction_engine import customization
    from ..application.simulation_access import simulation_runtime, invalidate_simulation_sessions

    @app.get('/simulation/configuration')
    def configuration_revision():
        return {'configuration_revision': simulation_runtime(application.facade).configuration_revision}

    @app.get('/simulation/customization')
    def get_customization():
        session = application.facade.simulation_session
        try:
            return customization.snapshot(session, simulation_runtime(application.facade))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return {'status': 'invalid', 'errors': [{'message': str(exc)}]}

    @app.post('/simulation/customization/validate')
    def validate_customization(payload: dict):
        return customization.process(application.facade.simulation_session,
                                     simulation_runtime(application.facade), payload)

    @app.post('/simulation/customization/publish')
    def publish_customization(payload: dict):
        with application.facade.simulation_session.lock:
            result = customization.process(application.facade.simulation_session,
                                           simulation_runtime(application.facade), payload, publish=True)
            if result.get('status') == 'published' and result.get('changed') is not False:
                result.update(invalidate_simulation_sessions(application.facade))
            return result

    @app.post('/simulation/customization/merge-preview')
    def merge_customization(payload: dict):
        from ..instruction_engine.customization_merge import preview
        session = application.facade.simulation_session
        with session.lock:
            try:
                view = customization.snapshot(session, simulation_runtime(application.facade))
                if payload.get('base_revision') != view['base_revision']:
                    raise ValueError('配置已变化，请备份草稿并重新载入最新配置后合并。')
                return preview(payload.get('state'), payload.get('incoming'), payload.get('resolutions'), view['instructions'])
            except (OSError, ValueError, TypeError, KeyError) as exc:
                return {'status': 'invalid', 'errors': [{'message': str(exc)}], 'conflicts': []}
