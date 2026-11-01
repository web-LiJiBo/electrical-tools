"""Behavior tests for the isolated, explicit-action simulator."""
from copy import deepcopy
import importlib
import importlib.util
import json

import pytest


RUNTIME_MODULE = 'standard_knowledge_service_v2.instruction_engine.simulation_runtime'


def test_completed_events_remain_readable_after_runtime_restart_without_replaying_state(tmp_path):
    path = tmp_path / 'events.jsonl'
    runtime = runtime_class()(event_path=path)
    session = runtime.create_session()
    sid = session['session_id']
    result = execute(runtime, sid, 'SIM-IEC-FAN-01', 'start')
    restarted = runtime_class()(event_path=path)
    assert restarted.events(sid)[0]['event_id'] == result['event_id']
    with pytest.raises(KeyError):
        restarted.snapshot(sid)
    fresh = restarted.create_session()
    assert device(fresh, 'SIM-IEC-FAN-01')['state']['running'] is False


@pytest.mark.parametrize('state_change', ['condition', 'reset', 'execute'])
def test_preview_rejects_changed_analysis_snapshot_without_executable_command(state_change):
    runtime = runtime_class()()
    analyzed = runtime.create_session()
    sid = analyzed['session_id']
    if state_change == 'condition':
        runtime.set_condition(sid, 'normal')
    elif state_change == 'reset':
        runtime.reset(sid)
    else:
        execute(runtime, sid, 'SIM-MB-FAN-01', 'start')
    before = runtime.snapshot(sid)
    history = runtime.events(sid)

    preview = runtime.preview(sid, 'SIM-IEC-FAN-01', 'start',
                              expected_version=analyzed['version'])

    assert preview['status'] == 'blocked'
    assert '版本' in preview['explanation']
    assert preview['command_id'] is None
    assert preview['candidate']['payload'] == {}
    assert preview['simulation_execution_allowed'] is False
    assert runtime.snapshot(sid) == before
    assert runtime.events(sid) == history
    current = runtime.preview(sid, 'SIM-IEC-FAN-01', 'start', expected_version=before['version'])
    assert current['status'] == 'generated'


@pytest.mark.parametrize('expected_version', [True, False, 0.0, '0', -1])
def test_preview_rejects_invalid_analysis_version_without_payload(expected_version):
    runtime = runtime_class()()
    session = runtime.create_session()

    preview = runtime.preview(session['session_id'], 'SIM-IEC-FAN-01', 'start',
                              expected_version=expected_version)

    assert preview['status'] == 'blocked'
    assert '版本' in preview['explanation']
    assert preview['command_id'] is None
    assert preview['candidate']['payload'] == {}
    assert runtime.snapshot(session['session_id']) == session


def test_dynamic_evidence_is_server_owned_through_execution_and_restart(tmp_path):
    path = tmp_path / 'dynamic-evidence-events.jsonl'
    runtime = runtime_class()(event_path=path)
    session = runtime.create_session()
    sid = session['session_id']
    evidence = [{'document_id': 'retrieved-standard', 'clause': '4.2',
                 'details': {'matched_terms': ['冷却', '启动'], 'score': 0.87}}]
    expected = deepcopy(evidence)

    preview = runtime.preview(sid, 'SIM-IEC-FAN-01', 'start', evidence=evidence,
                              expected_version=session['version'])

    assert preview['status'] == 'generated'
    assert preview['candidate']['evidence'] == expected
    assert preview['analysis_evidence'] == expected
    assert runtime.snapshot(sid) == session
    assert runtime.events(sid) == []
    evidence[0]['details']['matched_terms'].append('caller-invented')
    evidence.clear()
    preview['candidate']['evidence'][0]['clause'] = 'client replacement'
    preview['analysis_evidence'][0]['details']['score'] = 0

    result = runtime.execute(sid, preview['command_id'], preview['expected_version'])

    assert result['status'] == 'succeeded'
    assert result['candidate']['evidence'] == expected
    assert result['analysis_evidence'] == expected
    result['candidate']['evidence'][0]['details']['matched_terms'].clear()
    result['analysis_evidence'].clear()
    history = runtime.events(sid)
    assert history[0]['candidate']['evidence'] == expected
    assert history[0]['analysis_evidence'] == expected
    history[0]['candidate']['evidence'].clear()
    history[0]['analysis_evidence'][0]['clause'] = 'changed read-only history'
    repeated = runtime.execute(sid, preview['command_id'], preview['expected_version'])
    assert repeated['candidate']['evidence'] == expected
    assert repeated['analysis_evidence'] == expected
    restarted_history = runtime_class()(event_path=path).events(sid)
    assert restarted_history[0]['candidate']['evidence'] == expected
    assert restarted_history[0]['analysis_evidence'] == expected


@pytest.mark.parametrize('evidence', [None, []])
def test_explicit_device_simulation_does_not_require_analysis_evidence(evidence):
    runtime = runtime_class()()
    session = runtime.create_session(scenario_id=None, device_ids=['SIM-IEC-FAN-01'])

    preview = runtime.preview(session['session_id'], 'SIM-IEC-FAN-01', 'start', evidence=evidence)

    assert preview['status'] == 'generated'
    assert preview['candidate']['evidence'] == []
    assert preview['analysis_evidence'] == []
    assert runtime.snapshot(session['session_id']) == session
    result = runtime.execute(session['session_id'], preview['command_id'], preview['expected_version'])
    assert result['status'] == 'succeeded'
    assert result['candidate']['evidence'] == []
    assert result['analysis_evidence'] == []


@pytest.mark.parametrize('blocking_cause', ['relation', 'effects', 'feedback'])
def test_blocked_preview_removes_encoded_payload_and_keeps_dynamic_evidence(blocking_cause):
    from standard_knowledge_service_v2.instruction_engine.simulation_catalog import SimulationCatalog
    catalog = SimulationCatalog()
    identifier, action = 'SIM-IEC-FAN-01', 'start'
    if blocking_cause == 'relation':
        identifier, action = 'SIM-IEC-DISCONNECTOR-01', 'open'
    elif blocking_cause == 'effects':
        catalog.devices[identifier]['actions'][action]['simulation_effects'] = {}
    else:
        catalog.devices[identifier]['actions'][action]['feedback_mapping'] = {}
    runtime = runtime_class()(catalog)
    session = runtime.create_session()
    evidence = [{'document_id': 'dynamic-blocking-context', 'clause': '7.3'}]

    preview = runtime.preview(session['session_id'], identifier, action, evidence=evidence)

    assert preview['status'] == 'blocked'
    assert preview['command_id'] is None
    assert preview['candidate']['payload'] == {}
    assert preview['candidate']['explanation'] == preview['explanation']
    assert preview['explanation']
    assert preview['candidate']['evidence'] == evidence
    assert preview['analysis_evidence'] == evidence
    assert preview['simulation_execution_allowed'] is False
    assert runtime.snapshot(session['session_id']) == session
    assert runtime.events(session['session_id']) == []


def runtime_class():
    assert importlib.util.find_spec(RUNTIME_MODULE) is not None, 'Explicit simulation runtime is missing'
    return importlib.import_module(RUNTIME_MODULE).SimulationRuntime


def device(snapshot, device_id):
    return next(item for item in snapshot['devices'] if item['device_id'] == device_id)


def execute(runtime, session_id, device_id, action, parameters=None):
    preview = runtime.preview(session_id, device_id, action, parameters)
    assert preview['status'] == 'generated', preview
    return runtime.execute(session_id, preview['command_id'], preview['expected_version'])


@pytest.mark.parametrize('protocol', ['IEC', 'MB'])
def test_fan_preview_is_read_only_and_start_stop_use_independent_feedback(protocol):
    runtime = runtime_class()()
    snapshot = runtime.create_session()
    identifier = f'SIM-{protocol}-FAN-01'
    session_id = snapshot['session_id']
    baseline = runtime.snapshot(session_id)
    preview = runtime.preview(session_id, identifier, 'start')
    assert preview['status'] == 'generated'
    assert runtime.snapshot(session_id) == baseline
    assert runtime.events(session_id) == []
    # A caller can edit returned protocol fields but cannot replace the stored command.
    preview['candidate']['payload']['address'] = 65535
    preview['expected_changes'][identifier]['state']['running'] = False
    result = runtime.execute(session_id, preview['command_id'], preview['expected_version'])
    assert result['status'] == 'succeeded', result
    assert result['dispatch_allowed'] is False
    assert result['feedback']['simulation_only'] is True
    assert result['feedback']['value'] is True
    assert device(result['after'], identifier)['state']['running'] is True
    payload = result['candidate']['payload']
    feedback = result['feedback']['point']
    if protocol == 'IEC':
        assert payload['object_reference'] != feedback['object_reference']
    else:
        assert payload['address'] != feedback['address']
        assert payload['encoded_value'] == 0xff00
        assert payload['address'] != 65535
    stopped = execute(runtime, session_id, identifier, 'stop')
    assert stopped['feedback']['value'] is False
    assert device(stopped['after'], identifier)['state']['running'] is False


def test_same_template_sessions_are_independent_and_returned_snapshots_are_copies():
    runtime = runtime_class()()
    first = runtime.create_session(device_ids=['SIM-IEC-FAN-01'], scenario_id=None)
    second = runtime.create_session(device_ids=['SIM-IEC-FAN-01'], scenario_id=None)
    device(first, 'SIM-IEC-FAN-01')['runtime_facts']['start_permission'] = 0
    result = execute(runtime, first['session_id'], 'SIM-IEC-FAN-01', 'start')
    assert result['status'] == 'succeeded'
    assert device(runtime.snapshot(second['session_id']), 'SIM-IEC-FAN-01')['state']['running'] is False
    assert runtime.events(second['session_id']) == []


def test_repeated_execution_is_idempotent_and_new_stale_preview_is_blocked():
    runtime = runtime_class()()
    session = runtime.create_session()
    session_id = session['session_id']
    original = runtime.preview(session_id, 'SIM-IEC-FAN-01', 'start')
    stale = runtime.preview(session_id, 'SIM-MB-FAN-01', 'start')
    result = runtime.execute(session_id, original['command_id'], original['expected_version'])
    again = runtime.execute(session_id, original['command_id'], original['expected_version'])
    assert result == again
    assert len(runtime.events(session_id)) == 1
    blocked = runtime.execute(session_id, stale['command_id'], stale['expected_version'])
    assert blocked['status'] == 'blocked'
    assert '版本' in blocked['explanation']
    assert device(runtime.snapshot(session_id), 'SIM-MB-FAN-01')['state']['running'] is False


def test_foreign_and_unknown_commands_cannot_execute():
    runtime = runtime_class()()
    first = runtime.create_session()
    second = runtime.create_session()
    command = runtime.preview(first['session_id'], 'SIM-IEC-FAN-01', 'start')
    assert runtime.execute(second['session_id'], command['command_id'], command['expected_version'])['status'] == 'blocked'
    assert runtime.execute(first['session_id'], 'client-invented-command', 0)['status'] == 'blocked'
    assert runtime.snapshot(first['session_id'])['version'] == first['version']


def test_missing_relations_block_disconnector_and_earthing_switch():
    runtime = runtime_class()()
    session = runtime.create_session(scenario_id=None, device_ids=['SIM-IEC-DISCONNECTOR-01', 'SIM-IEC-EARTHING-01'])
    for identifier in ['SIM-IEC-DISCONNECTOR-01', 'SIM-IEC-EARTHING-01']:
        preview = runtime.preview(session['session_id'], identifier, 'close')
        assert preview['status'] == 'blocked'
        assert any(check['status'] != 'pass' for check in preview['relation_checks'])
    assert runtime.snapshot(session['session_id']) == session


def test_isolation_sequence_rechecks_related_breaker_and_feedback():
    runtime = runtime_class()()
    session_id = runtime.create_session()['session_id']
    assert runtime.preview(session_id, 'SIM-IEC-DISCONNECTOR-01', 'open')['status'] == 'blocked'
    tripped = execute(runtime, session_id, 'SIM-IEC-BREAKER-01', 'trip')
    assert tripped['status'] == 'succeeded'
    assert device(tripped['after'], 'SIM-IEC-BREAKER-01')['runtime_facts']['current'] == 0
    opened = execute(runtime, session_id, 'SIM-IEC-DISCONNECTOR-01', 'open')
    assert opened['status'] == 'succeeded'
    earthed = execute(runtime, session_id, 'SIM-IEC-EARTHING-01', 'close')
    assert earthed['status'] == 'succeeded'
    assert runtime.preview(session_id, 'SIM-IEC-BREAKER-01', 'close')['status'] == 'blocked'


def test_feedback_failure_rolls_back_points_state_and_facts_and_keeps_event(tmp_path):
    from standard_knowledge_service_v2.instruction_engine.simulation_catalog import SimulationCatalog
    catalog = SimulationCatalog()
    catalog.devices['SIM-IEC-FAN-01']['runtime_facts']['feedback_failure'] = True
    event_path = tmp_path / 'simulation-events.jsonl'
    runtime = runtime_class()(catalog=catalog, event_path=event_path)
    session_id = runtime.create_session()['session_id']
    before = runtime.snapshot(session_id)
    result = execute(runtime, session_id, 'SIM-IEC-FAN-01', 'start')
    assert result['status'] == 'failed'
    assert result['feedback']['status'] == 'failed'
    assert result['before'] == result['after'] == before
    assert runtime.snapshot(session_id) == before
    assert runtime.events(session_id)[0]['event_id'] == result['event_id']
    persisted = json.loads(event_path.read_text(encoding='utf-8').strip())
    assert persisted['status'] == 'failed'


@pytest.mark.parametrize('condition', ['normal', 'high_temperature', 'cooling_fault', 'maintenance'])
def test_all_conditions_are_explicit_and_reset_invalidates_commands(condition):
    runtime = runtime_class()()
    created = runtime.create_session(condition=condition)
    assert created['condition'] == condition
    session_id = created['session_id']
    runtime.set_condition(session_id, 'normal')
    command = runtime.preview(session_id, 'SIM-IEC-FAN-01', 'start')
    reset = runtime.reset(session_id)
    assert reset['version'] > command['expected_version']
    assert runtime.execute(session_id, command['command_id'], command['expected_version'])['status'] == 'blocked'
    assert device(runtime.snapshot(session_id), 'SIM-IEC-FAN-01')['state']['running'] is False
    runtime.set_condition(session_id, 'cooling_fault')
    assert runtime.preview(session_id, 'SIM-IEC-FAN-01', 'start')['status'] == 'blocked'


@pytest.mark.parametrize('protocol', ['IEC', 'MB'])
def test_tap_numeric_effects_preserve_integer_types_and_limits(protocol):
    runtime = runtime_class()()
    session_id = runtime.create_session()['session_id']
    identifier = f'SIM-{protocol}-TAP-01'
    result = execute(runtime, session_id, identifier, 'set_tap', {'tap_position': 10})
    assert result['status'] == 'succeeded'
    assert type(result['feedback']['value']) is int
    assert result['feedback']['value'] == 10
    assert execute(runtime, session_id, identifier, 'raise')['feedback']['value'] == 11
    assert execute(runtime, session_id, identifier, 'lower')['feedback']['value'] == 10
    execute(runtime, session_id, identifier, 'set_tap', {'tap_position': 17})
    assert runtime.preview(session_id, identifier, 'raise')['status'] == 'blocked'


@pytest.mark.parametrize('value', [True, False, float('nan'), float('inf'), -1, 18, 3.5, '4', None])
def test_invalid_tap_parameters_cannot_generate(value):
    runtime = runtime_class()()
    session_id = runtime.create_session()['session_id']
    before = runtime.snapshot(session_id)
    assert runtime.preview(session_id, 'SIM-MB-TAP-01', 'set_tap', {'tap_position': value})['status'] == 'blocked'
    assert runtime.snapshot(session_id) == before


@pytest.mark.parametrize('expected_version', [True, False, 0.0, '0', None, -1])
def test_invalid_version_types_cannot_execute(expected_version):
    runtime = runtime_class()()
    session_id = runtime.create_session()['session_id']
    command = runtime.preview(session_id, 'SIM-IEC-FAN-01', 'start')
    assert runtime.execute(session_id, command['command_id'], expected_version)['status'] == 'blocked'
    assert device(runtime.snapshot(session_id), 'SIM-IEC-FAN-01')['state']['running'] is False


def test_invalid_device_action_and_parameter_fields_do_not_mutate():
    runtime = runtime_class()()
    session_id = runtime.create_session()['session_id']
    before = runtime.snapshot(session_id)
    for identifier, action, parameters in [
        ('REAL-DEVICE', 'start', {}), ('SIM-IEC-FAN-01', 'arbitrary', {}),
        ('SIM-IEC-FAN-01', 'start', {'address': 100}),
        ('SIM-IEC-FAN-01', 'start', []),
    ]:
        assert runtime.preview(session_id, identifier, action, parameters)['status'] == 'blocked'
    assert runtime.snapshot(session_id) == before
    with pytest.raises(KeyError):
        runtime.snapshot('unknown-session')
    with pytest.raises(ValueError):
        runtime.create_session(device_ids=['REAL-DEVICE'])
    with pytest.raises(ValueError):
        runtime.set_condition(session_id, 'unknown-condition')


def test_two_concurrent_commands_at_same_version_cannot_both_change_state():
    from concurrent.futures import ThreadPoolExecutor
    runtime = runtime_class()()
    session_id = runtime.create_session()['session_id']
    commands = [runtime.preview(session_id, identifier, 'start')
                for identifier in ['SIM-IEC-FAN-01', 'SIM-MB-FAN-01']]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(runtime.execute, session_id, item['command_id'], item['expected_version'])
                   for item in commands]
        results = [future.result() for future in futures]
    assert sorted(item['status'] for item in results) == ['blocked', 'succeeded']
    final = runtime.snapshot(session_id)
    assert final['version'] == 1
    assert sum(device(final, identifier)['state']['running']
               for identifier in ['SIM-IEC-FAN-01', 'SIM-MB-FAN-01']) == 1


def test_configuration_change_requires_new_session_preview():
    from standard_knowledge_service_v2.instruction_engine.simulation_catalog import SimulationCatalog
    catalog = SimulationCatalog()
    runtime = runtime_class()(catalog)
    session_id = runtime.create_session()['session_id']
    preview = runtime.preview(session_id, 'SIM-IEC-FAN-01', 'start')
    catalog.devices['SIM-IEC-FAN-01']['actions']['start']['value'] = False
    result = runtime.execute(session_id, preview['command_id'], preview['expected_version'])
    assert result['status'] == 'blocked'
    assert result['before'] == result['after']
    assert '配置版本' in result['explanation']


@pytest.mark.parametrize('protocol,encoded', [('IEC', 1), ('MB', False)])
def test_switch_feedback_encodes_position_separately_from_command(protocol, encoded):
    runtime = runtime_class()()
    session_id = runtime.create_session()['session_id']
    result = execute(runtime, session_id, f'SIM-{protocol}-BREAKER-01', 'trip')
    assert result['feedback']['value'] == 'open'
    assert type(result['feedback']['encoded_value']) is type(encoded)
    assert result['feedback']['encoded_value'] == encoded


def test_event_storage_failure_does_not_commit_any_state(tmp_path):
    # A directory is an invalid log file: the real append operation must fail.
    runtime = runtime_class()(event_path=tmp_path)
    session_id = runtime.create_session()['session_id']
    before = runtime.snapshot(session_id)
    preview = runtime.preview(session_id, 'SIM-IEC-FAN-01', 'start')
    with pytest.raises(OSError):
        runtime.execute(session_id, preview['command_id'], preview['expected_version'])
    assert runtime.snapshot(session_id) == before
    assert runtime.events(session_id) == []


def test_scaled_fractional_engineering_values_are_not_inferred_as_integer_parameters():
    from standard_knowledge_service_v2.instruction_engine.simulation_catalog import SimulationCatalog
    catalog = SimulationCatalog()
    # The current value happens to be an integer; the template explicitly permits
    # tenths using a register scale of ten, so integer inference would be wrong.
    profile = catalog.devices['SIM-MB-FAN-01']
    profile['initial_state']['speed_percent'] = 0
    profile['actions']['set_speed'] = {
        'function': 'fan_set_speed', 'condition': 'start_permission == 1',
        'parameter': 'speed_percent', 'minimum': 0, 'maximum': 100, 'unit': '%',
        'mapping': {'slave_id': 3, 'address': 250, 'function_code': 6, 'data_type': 'uint16', 'scale': 10},
        'simulation_effects': {'state': {'speed_percent': {'from_parameter': 'speed_percent'}}},
        'feedback_mapping': {'protocol': 'Modbus', 'slave_id': 3, 'address': 1250,
                             'function_code': 3, 'data_type': 'uint16', 'scale': 10,
                             'field': 'state.speed_percent', 'unit': '%'},
    }
    runtime = runtime_class()(catalog)
    session_id = runtime.create_session()['session_id']
    result = execute(runtime, session_id, 'SIM-MB-FAN-01', 'set_speed', {'speed_percent': 12.5})
    assert result['status'] == 'succeeded'
    assert result['feedback']['value'] == 12.5
    assert result['feedback']['encoded_value'] == 125
    assert result['candidate']['payload']['encoded_value'] == 125
