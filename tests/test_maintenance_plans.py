"""Server-owned conditions and feedback-gated maintenance plans."""
from copy import deepcopy
import pytest

from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime
from standard_knowledge_service_v2.instruction_engine.simulation_catalog import SimulationCatalog


def make_runtime():
    runtime = SimulationRuntime()
    session = runtime.create_session()
    return runtime, session['session_id']


def steps():
    return [{'device_id': 'SIM-IEC-FAN-01', 'action': 'start', 'parameters': {},
             'conditions': ['device_fault == 0'], 'order': 1},
            {'device_id': 'SIM-MB-FAN-01', 'action': 'start', 'parameters': {},
             'conditions': ['device_fault == 0'], 'order': 2}]


def test_false_condition_blocks_preview_without_a_command():
    runtime, sid = make_runtime()
    preview = runtime.preview(sid, 'SIM-IEC-FAN-01', 'start', conditions=['device_fault == 1'])
    assert preview['status'] == 'blocked'
    assert preview['command_id'] is None
    assert preview['candidate']['payload'] == {}
    assert preview['condition_checks'][0]['status'] == 'fail'


def test_condition_missing_fact_is_unknown_not_false_or_ignored():
    runtime, sid = make_runtime()
    del runtime._sessions[sid].devices['SIM-IEC-FAN-01']['runtime_facts']['device_fault']
    preview = runtime.preview(sid, 'SIM-IEC-FAN-01', 'start', conditions=['device_fault == 0'])
    assert preview['status'] == 'blocked'
    assert preview['command_id'] is None
    assert preview['condition_checks'][0]['status'] == 'unknown'


@pytest.mark.parametrize('condition', ['没有故障', '__import__("os").system("whoami")', 'device_fault == 0 or 1', 'invented_fact == 0'])
def test_unsupported_condition_cannot_become_an_unconditional_command(condition):
    runtime, sid = make_runtime()
    preview = runtime.preview(sid, 'SIM-IEC-FAN-01', 'start', conditions=[condition])
    assert preview['status'] == 'blocked'
    assert preview['command_id'] is None


def test_conditions_are_copied_bound_and_rechecked_at_execution():
    runtime, sid = make_runtime()
    supplied = ['device_fault == 0']
    preview = runtime.preview(sid, 'SIM-IEC-FAN-01', 'start', conditions=supplied)
    assert preview['status'] == 'generated'
    supplied.clear()
    preview['conditions'].clear()
    runtime._sessions[sid].devices['SIM-IEC-FAN-01']['runtime_facts']['device_fault'] = 1
    result = runtime.execute(sid, preview['command_id'], preview['expected_version'])
    assert result['status'] == 'blocked'
    assert result['condition_checks'][0]['status'] == 'fail'
    assert len(runtime.events(sid)) == 1
    assert runtime.snapshot(sid)['version'] == 0


def test_only_first_step_is_previewed_and_next_needs_feedback_and_latest_version():
    runtime, sid = make_runtime()
    plan = runtime.create_plan(sid, steps(), expected_version=0)
    assert plan['steps'][0]['preview']['status'] == 'generated'
    assert plan['steps'][1].get('preview') is None
    blocked = runtime.preview_plan_step(sid, plan['plan_id'], 2, expected_version=0)
    assert blocked['status'] == 'blocked'
    assert blocked['command_id'] is None
    preview = plan['steps'][0]['preview']
    execution = runtime.execute(sid, preview['command_id'], preview['expected_version'])
    assert execution['status'] == execution['feedback']['status'] == 'succeeded'
    assert runtime.preview_plan_step(sid, plan['plan_id'], 2, expected_version=0)['status'] == 'blocked'
    second = runtime.preview_plan_step(sid, plan['plan_id'], 2, expected_version=1)
    assert second['status'] == 'generated'
    assert runtime.snapshot(sid)['version'] == 1  # Preview never executes next step.
    assert runtime.preview_plan_step(sid, plan['plan_id'], 2, expected_version=1) == second
    done = runtime.execute(sid, second['command_id'], second['expected_version'])
    assert done['status'] == 'succeeded'
    assert runtime.execute(sid, second['command_id'], second['expected_version']) == done
    assert runtime.plan_snapshot(sid, plan['plan_id'])['status'] == 'completed'
    assert len(runtime.events(sid)) == 2


@pytest.mark.parametrize('change', ['version', 'config'])
def test_plan_rejects_changes_between_steps(change):
    runtime, sid = make_runtime()
    plan = runtime.create_plan(sid, steps(), expected_version=0)
    first = plan['steps'][0]['preview']
    runtime.execute(sid, first['command_id'], 0)
    if change == 'version':
        runtime.set_condition(sid, 'normal')
    else:
        runtime.catalog.devices['SIM-MB-FAN-01']['actions']['start']['value'] = False
    result = runtime.preview_plan_step(sid, plan['plan_id'], 2, expected_version=runtime.snapshot(sid)['version'])
    assert result['status'] == 'blocked'
    assert result['command_id'] is None
    assert runtime.plan_snapshot(sid, plan['plan_id'])['status'] == 'stopped'


def test_failed_feedback_stops_plan_and_does_not_retry_or_create_next_command():
    catalog = SimulationCatalog()
    catalog.devices['SIM-IEC-FAN-01']['runtime_facts']['feedback_failure'] = True
    runtime = SimulationRuntime(catalog)
    sid = runtime.create_session()['session_id']
    plan = runtime.create_plan(sid, steps(), expected_version=0)
    first = plan['steps'][0]['preview']
    failed = runtime.execute(sid, first['command_id'], 0)
    assert failed['status'] == 'failed'
    assert runtime.execute(sid, first['command_id'], 0) == failed
    assert runtime.plan_snapshot(sid, plan['plan_id'])['status'] == 'stopped'
    assert runtime.preview_plan_step(sid, plan['plan_id'], 2, expected_version=0)['status'] == 'blocked'
    assert len(runtime.events(sid)) == 1
    assert len(runtime._sessions[sid].commands) == 1


def test_plan_and_command_cannot_cross_sessions():
    runtime, sid = make_runtime()
    foreign = runtime.create_session()['session_id']
    plan = runtime.create_plan(sid, steps(), expected_version=0)
    with pytest.raises(KeyError):
        runtime.plan_snapshot(foreign, plan['plan_id'])
    with pytest.raises(KeyError):
        runtime.preview_plan_step(foreign, plan['plan_id'], 2, expected_version=0)
    preview = plan['steps'][0]['preview']
    assert runtime.execute(foreign, preview['command_id'], 0)['status'] == 'blocked'
    assert runtime.snapshot(sid)['version'] == 0


def test_independent_review_needs_server_proof_bound_to_exact_operations():
    from standard_knowledge_service_v2.application.operation_review import validate_review
    ops = [dict(row, negated=False, clarification='') for row in steps()]
    raw = {'approved': True, 'items': [dict(index=i, matches_request=True, reason='原文一致',
        device_id=row['device_id'], action=row['action'], parameters={}) for i, row in enumerate(ops)],
        'missing_requests': [], 'has_negation': False, 'has_conditions': True,
        'has_order': True, 'reason': '原话条件和顺序与后台支持一致'}
    support = {'conditions': True, 'order': True, 'operations': deepcopy(ops)}
    assert validate_review(raw, ops)['status'] == 'blocked'
    assert validate_review(raw, ops, support)['status'] == 'approved'
    changed = deepcopy(ops)
    changed[0]['conditions'] = ['device_fault == 1']
    assert validate_review(raw, changed, support)['status'] == 'blocked'
    raw['has_negation'] = True
    assert validate_review(raw, ops, support)['status'] == 'blocked'

def preparation_input(conditions=None, order=None):
    from types import SimpleNamespace
    from standard_knowledge_service_v2.decomposition.models import DecompositionResult
    runtime, sid = make_runtime()
    query = '如果冷却风机1没有故障就启动冷却风机1'
    row = {'device_id': 'SIM-IEC-FAN-01', 'action': 'start', 'parameters': {},
           'conditions': ['device_fault == 0'] if conditions is None else conditions,
           'order': order, 'negated': False, 'clarification': '', 'owner_id': '',
           'source_text': query, 'target_text': '冷却风机1'}
    decomposed = DecompositionResult(intent='instruction', actions=['start'], operations=[row],
        queries=[], scenario={'query_kind': 'operation'}, valid=True)
    request = SimpleNamespace(query=query, parameters={'simulation_mode': True, 'simulation_session_id': sid},
                              conversation_context=[])
    pipeline = SimpleNamespace(simulation_runtime=runtime)
    return pipeline, request, decomposed


def plans_module():
    import importlib.util
    name = 'standard_knowledge_service_v2.application.maintenance_plans'
    assert importlib.util.find_spec(name) is not None, 'compiled maintenance planning is missing'
    return __import__(name, fromlist=['prepare_operation_plan'])


def test_prepare_is_readonly_and_preview_after_review_binds_condition():
    module = plans_module()
    pipeline, request, decomposed = preparation_input()
    runtime, sid = pipeline.simulation_runtime, request.parameters['simulation_session_id']
    prepared = module.prepare_operation_plan(pipeline, request, decomposed)
    assert prepared['status'] == 'prepared'
    assert prepared['execution_support']['conditions'] is True
    assert runtime._sessions[sid].commands == {}
    assert runtime._sessions[sid].plans == {}
    status, data, evidence, warnings = module.preview_operation_plan(pipeline, request, decomposed, prepared)
    assert status == 'generated'
    preview = data['simulation_plan']['steps'][0]['preview']
    assert preview['conditions'] == ['device_fault == 0']
    assert len(runtime._sessions[sid].commands) == 1


@pytest.mark.parametrize('conditions,order', [(['没有故障'], None), (['device_fault == 0'], 2)])
def test_rejected_preparation_preview_stays_readonly(conditions, order):
    module = plans_module()
    pipeline, request, decomposed = preparation_input(conditions, order)
    prepared = module.prepare_operation_plan(pipeline, request, decomposed)
    assert prepared['status'] != 'prepared'
    status, data, _, _ = module.preview_operation_plan(pipeline, request, decomposed, prepared)
    assert status == 'uncertain'
    assert data['candidate_instruction'] is None
    assert pipeline.simulation_runtime._sessions[request.parameters['simulation_session_id']].commands == {}


def test_multiple_conditional_operations_without_order_are_not_silently_serialized():
    module = plans_module()
    pipeline, request, decomposed = preparation_input()
    second = deepcopy(decomposed.operations[0])
    second.update(device_id='SIM-MB-FAN-01', target_text='冷却风机2')
    request.query += '，如果冷却风机2没有故障就启动冷却风机2'
    second['source_text'] = '如果冷却风机2没有故障就启动冷却风机2'
    decomposed.operations.append(second)
    prepared = module.prepare_operation_plan(pipeline, request, decomposed)
    assert prepared['status'] == 'blocked'
    assert pipeline.simulation_runtime._sessions[request.parameters['simulation_session_id']].commands == {}
    assert '顺序' in prepared['reason']


def test_analysis_only_added_after_preparation_cannot_allocate_any_command():
    module = plans_module()
    pipeline, request, decomposed = preparation_input()
    prepared = module.prepare_operation_plan(pipeline, request, decomposed)
    assert prepared['status'] == 'prepared'
    decomposed.request_controls = {'analysis_only': True, 'source_text': request.query}
    status, data, _, _ = module.preview_operation_plan(pipeline, request, decomposed, prepared)
    assert status == 'uncertain'
    assert data['candidate_instruction'] is None
    assert pipeline.simulation_runtime._sessions[request.parameters['simulation_session_id']].commands == {}


@pytest.mark.parametrize('change', ['version', 'config', 'session'])
def test_changes_between_preparation_and_review_do_not_allocate_or_crash(change):
    module = plans_module()
    pipeline, request, decomposed = preparation_input()
    runtime, sid = pipeline.simulation_runtime, request.parameters['simulation_session_id']
    prepared = module.prepare_operation_plan(pipeline, request, decomposed)
    assert prepared['status'] == 'prepared'
    if change == 'version':
        runtime.set_condition(sid, 'normal')
    elif change == 'config':
        runtime.catalog.devices['SIM-IEC-FAN-01']['actions']['start']['value'] = False
    else:
        request.parameters['simulation_session_id'] = runtime.create_session()['session_id']
    status, data, _, _ = module.preview_operation_plan(pipeline, request, decomposed, prepared)
    assert status == 'uncertain'
    assert data['candidate_instruction'] is None
    assert runtime._sessions[sid].commands == {}
    assert runtime._sessions[sid].plans == {}


def test_unknown_feedback_does_not_commit_or_open_the_next_step(monkeypatch):
    runtime, sid = make_runtime()
    original = runtime._feedback
    def unknown_feedback(entry, template, payload, validate_only=False):
        result = original(entry, template, payload, validate_only=validate_only)
        if not validate_only:
            result.update(status='unknown', explanation='模拟反馈结果未确认')
        return result
    monkeypatch.setattr(runtime, '_feedback', unknown_feedback)
    plan = runtime.create_plan(sid, steps(), expected_version=0)
    first = plan['steps'][0]['preview']
    result = runtime.execute(sid, first['command_id'], 0)
    assert result['status'] == 'unknown'
    assert result['before'] == result['after']
    assert runtime.snapshot(sid)['version'] == 0
    assert runtime.plan_snapshot(sid, plan['plan_id'])['status'] == 'stopped'
    assert runtime.preview_plan_step(sid, plan['plan_id'], 2, expected_version=0)['status'] == 'blocked'
    assert runtime.execute(sid, first['command_id'], 0) == result


def test_plan_readiness_query_uses_refreshed_template_and_latest_shared_facts():
    module = plans_module()
    pipeline, request, decomposed = preparation_input()
    runtime = pipeline.simulation_runtime
    updated = deepcopy(runtime.catalog)
    updated.devices['SIM-IEC-FAN-01']['actions']['start']['condition'] = 'start_permission == 0'
    runtime.refresh_catalog(updated)
    text = '判断冷却风机1能否启动'
    request.query += '，' + text
    decomposed.queries = [{'query_kind': 'device_readiness', 'device_id': 'SIM-IEC-FAN-01',
        'requested_action': 'start', 'source_text': text, 'target_text': '冷却风机1', 'owner_id': '', 'clarification': ''}]
    prepared = module.prepare_operation_plan(pipeline, request, decomposed)
    assert prepared['status'] == 'prepared'
    readiness = prepared['factual_results'][0]['readiness']
    assert readiness['status'] == 'blocked'
    check = next(item for item in readiness['checks'] if item['field'] == 'start_permission')
    assert check['actual'] == 1 and check['expected'] == 0
