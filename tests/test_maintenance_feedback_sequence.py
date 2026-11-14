"""Failure-stop restrictions belong to the sequential runtime, not cancellation."""
from copy import deepcopy
import json
import pytest
from standard_knowledge_service_v2.application import AnalysisPipeline
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.decomposition import RemoteModelConfig, RemoteModelDecomposer
from standard_knowledge_service_v2.retrieval_engine import JsonClauseRepository, LocalLunwenRetrievalAdapter
from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime
from semantic_fixture_helpers import approve_review_packet


QUERY = '把主变1的调压装置先从当前档位升一档，确认反馈成功后再升一档；若第一步失败，第二步不要执行。请给出可执行方案'


def structure(*, full_evidence=True):
    sources = [QUERY, QUERY] if full_evidence else [
        '把主变1的调压装置先从当前档位升一档', '确认反馈成功后再升一档；若第一步失败，第二步不要执行']
    rows = [{'device_id': 'SIM-IEC-TAP-01', 'owner_id': 'SIM-TRANSFORMER-01',
        'target_text': '主变1的调压装置', 'source_text': source, 'action': 'raise',
        'parameters': {}, 'negated': False, 'conditions': [], 'order': i + 1, 'clarification': ''}
        for i, source in enumerate(sources)]
    return {'intent': 'instruction', 'entities': [{'name': '主变1的调压装置', 'type': '设备'}],
        'actions': ['raise'], 'constraints': [], 'standard_refs': [], 'keywords': ['调压'],
        'scenario': {'query_kind': 'operation', 'operating_condition': ''}, 'confidence': .96,
        'operations': rows, 'queries': [], 'request_controls': {'analysis_only': False, 'source_text': ''}}


def run(monkeypatch, payload, *, reject_review=False, query=QUERY, condition='normal'):
    model = RemoteModelDecomposer(RemoteModelConfig('https://example.test', 'controlled'))
    calls = []
    def complete(system, user):
        calls.append((system, user))
        if 'OPERATION_PLAN_REVIEW' in system:
            approval = approve_review_packet(json.loads(user))
            if reject_review:
                approval.update(approved=False, has_negation=True, reason='用户实际取消了操作')
            return json.dumps(approval)
        return json.dumps(payload, ensure_ascii=False)
    monkeypatch.setattr(model, 'complete', complete)
    app = AnalysisPipeline(LocalLunwenRetrievalAdapter(JsonClauseRepository([])), decomposer=model)
    app.simulation_runtime = SimulationRuntime(event_path=None)
    before = app.simulation_runtime.create_session(condition=condition)
    response = app.analyze(AnalysisRequest(query, parameters={
        'simulation_mode': True, 'simulation_session_id': before['session_id']}))
    return app.simulation_runtime, before['session_id'], response, calls


def test_feedback_failure_stop_policy_reaches_review_and_runs_one_confirmed_step_at_a_time(monkeypatch):
    runtime, sid, response, calls = run(monkeypatch, structure())
    assert response.status == 'generated', response.data.get('answer')
    assert len(calls) == 2
    plan = response.data['simulation_plan']
    assert plan['steps'][1]['preview'] is None
    first = plan['steps'][0]['preview']
    assert runtime.execute(sid, first['command_id'], first['expected_version'])['status'] == 'succeeded'
    second = runtime.preview_plan_step(sid, plan['plan_id'], 2, expected_version=1)
    assert second['status'] == 'generated'
    assert runtime.snapshot(sid)['version'] == 1


def test_original_incomplete_evidence_is_rejected_for_coverage_and_keeps_no_commands(monkeypatch):
    runtime, sid, response, calls = run(monkeypatch, structure(full_evidence=False))
    assert response.status == 'uncertain'
    assert '原文证据' in response.data['answer']['text']
    assert len(calls) == 1
    assert runtime._sessions[sid].commands == {}


@pytest.mark.parametrize('restriction', ['negated', 'analysis_only', 'review_negation'])
def test_real_cancellation_still_cannot_create_a_sequence(monkeypatch, restriction):
    payload = structure()
    if restriction == 'negated':
        payload['operations'][1]['negated'] = True
    elif restriction == 'analysis_only':
        payload['request_controls'] = {'analysis_only': True, 'source_text': QUERY}
    runtime, sid, response, calls = run(monkeypatch, payload, reject_review=restriction == 'review_negation')
    assert not (response.data.get('candidate_instruction') or {}).get('payload')
    assert runtime._sessions[sid].commands == {}
    assert runtime._sessions[sid].plans == {}


CONDITIONAL_QUERY = '如果主变1的冷却风机没有故障、未被检修闭锁且供电可用，就启动主变1的冷却风机；任何条件不满足都不要生成启动指令'


def conditional_structure(conditions=None):
    payload = structure()
    payload['entities'] = [{'name': '主变1的冷却风机', 'type': '设备'}]
    payload['actions'] = ['start']
    payload['operations'] = [{'device_id': 'SIM-IEC-FAN-01', 'owner_id': 'SIM-TRANSFORMER-01',
        'target_text': '主变1的冷却风机', 'source_text': CONDITIONAL_QUERY, 'action': 'start',
        'parameters': {}, 'negated': False, 'conditions': conditions if conditions is not None else
        ['device_fault == 0', 'maintenance_lockout == 0', 'power_available == 1'],
        'order': None, 'clarification': ''}]
    return payload


def test_compiled_condition_failure_stop_reaches_review_but_fault_blocks_every_command(monkeypatch):
    runtime, sid, response, calls = run(monkeypatch, conditional_structure(),
                                        query=CONDITIONAL_QUERY, condition='cooling_fault')
    assert len(calls) == 2, response.data.get('answer')
    assert response.data['operation_review']['status'] == 'approved'
    assert response.status == 'uncertain'
    checks = response.data['simulation_plan']['steps'][0]['preview']['condition_checks']
    assert len(checks) == 3
    fault = next(check for check in checks if check['field'] == 'device_fault')
    assert fault['actual'] == 1 and fault['value'] == 0 and fault['status'] == 'fail'
    assert runtime._sessions[sid].commands == {}


def test_uncompilable_failure_condition_cannot_bypass_negation_or_create_commands(monkeypatch):
    runtime, sid, response, calls = run(monkeypatch, conditional_structure(['没有故障']), query=CONDITIONAL_QUERY)
    assert response.status == 'uncertain'
    assert len(calls) == 1
    assert runtime._sessions[sid].commands == {}
