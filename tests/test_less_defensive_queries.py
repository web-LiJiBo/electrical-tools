"""Normal prose and unique read-only references should not require rephrasing."""
from standard_knowledge_service_v2.contracts import AnalysisRequest
from test_maintenance_workflow_integration import (
    pipeline, request_payload, operations_payload, guarded_operation)


def test_presentation_tail_does_not_block_readonly_result(monkeypatch):
    query = '查询主变1的冷却风机状态，不要生成控制指令。请清楚地说明结果'
    app, params, before, calls = pipeline(monkeypatch, query, request_payload(query))
    result = app.analyze(AnalysisRequest(query, parameters=params))
    assert result.status == 'partial'
    assert result.data.get('clarification_required') is False
    assert result.data['devices']
    assert len(calls) == 1
    assert app.simulation_runtime.snapshot(before['session_id']) == before


def test_unique_current_device_reference_can_use_same_sentence_evidence(monkeypatch):
    query = '查询主变1的冷却风机状态，并说明系统当前数据，不要生成控制指令'
    payload = request_payload(query)
    payload['queries'][0]['source_text'] = '并说明系统当前数据'
    app, params, before, calls = pipeline(monkeypatch, query, payload)
    result = app.analyze(AnalysisRequest(query, parameters=params))
    assert result.status in ('answered', 'partial')
    assert result.data['devices'][0]['device_id'] == 'SIM-IEC-FAN-01'
    assert len(calls) == 1


def test_known_fault_is_a_blocked_condition_not_a_clarification(monkeypatch):
    query = '只有确认主变1的冷却风机无故障时才允许启动'
    ops = [guarded_operation(query, conditions=['device_fault == 0'])]
    app, params, before, calls = pipeline(monkeypatch, query,
        operations_payload(query, ops), condition='cooling_fault')
    result = app.analyze(AnalysisRequest(query, parameters=params))
    assert result.data.get('clarification_required') is False
    assert not result.data.get('clarification_questions')
    assert result.data['simulation_plan']['steps'][0]['preview']['command_id'] is None
    assert len(calls) == 2


def test_readonly_owner_span_can_bind_explicit_shared_accessory(monkeypatch):
    query = '查询主变1和主变2各自的冷却风机状态，不要生成控制指令'
    payload = request_payload(query)
    payload['queries'] = [{**payload['queries'][0], 'target_text': owner,
        'owner_id': owner_id, 'device_id': key, 'source_text': query}
        for owner, owner_id, key in [
            ('主变1', 'SIM-TRANSFORMER-01', 'SIM-IEC-FAN-01'),
            ('主变2', 'SIM-TRANSFORMER-02', 'SIM-MB-FAN-01')]]
    app, params, before, calls = pipeline(monkeypatch, query, payload)
    result = app.analyze(AnalysisRequest(query, parameters=params))
    assert result.status == 'answered'
    assert {d['device_id'] for d in result.data['devices']} == {'SIM-IEC-FAN-01', 'SIM-MB-FAN-01'}
    assert len(calls) == 1
