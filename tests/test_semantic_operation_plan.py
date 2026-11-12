"""Whole-request semantic plans must never be split or silently overwritten."""
import json
from copy import deepcopy

import pytest

from standard_knowledge_service_v2.application import AnalysisPipeline
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.decomposition import RemoteModelConfig, RemoteModelDecomposer
from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime
from standard_knowledge_service_v2.retrieval_engine import JsonClauseRepository, LocalLunwenRetrievalAdapter


def operation(source, device='SIM-IEC-FAN-01', action='start', **changes):
    return dict(device_id=device, target_text=source, owner_id='', action=action,
                parameters={}, source_text=source, negated=False, conditions=[],
                order=None, clarification='', **changes)


def planned_app(monkeypatch, query, operations, queries=None, *, legacy=False):
    model = RemoteModelDecomposer(RemoteModelConfig('https://example.test', 'test'))
    calls = []
    def complete(system, user):
        calls.append((system, user))
        payload = {'intent': 'instruction' if operations else 'search',
            'entities': [{'name': '主变1', 'type': '设备'}],
            'actions': list(dict.fromkeys(item['action'] for item in operations)),
            'constraints': [], 'standard_refs': [], 'keywords': ['模拟设备'],
            'scenario': {'query_kind': 'operation' if operations else 'device_status', 'operating_condition': ''},
            'confidence': .95}
        if not legacy:
            payload.update(operations=deepcopy(operations), queries=queries or [])
        return json.dumps(payload, ensure_ascii=False)
    monkeypatch.setattr(model, 'complete', complete)
    app = AnalysisPipeline(LocalLunwenRetrievalAdapter(JsonClauseRepository([])), decomposer=model)
    app.simulation_runtime = SimulationRuntime(event_path=None)
    before = app.simulation_runtime.create_session('all_devices')
    parameters = {'simulation_mode': True, 'simulation_session_id': before['session_id'],
                  'simulation_scenario_id': 'all_devices'}
    return app, parameters, before, calls


@pytest.mark.parametrize('query', ['请启动主变1的冷却风机，谢谢', '启动主变 1 的冷却风机'])
def test_single_semantic_operation_ignores_politeness_and_alias_spaces(monkeypatch, query):
    item = operation(query)
    item['owner_id'] = 'SIM-TRANSFORMER-01'
    app, params, before, calls = planned_app(monkeypatch, query, [item])
    response = app.analyze(AnalysisRequest(query, parameters=params))
    assert response.status == 'generated'
    assert response.data['candidate_instruction']['target'] == 'SIM-IEC-FAN-01'
    assert len(calls) == 1
    assert app.simulation_runtime.snapshot(before['session_id']) == before
    assert 'SIM-IEC-FAN-01' in calls[0][1]
    assert 'SIM-TRANSFORMER-01' in calls[0][1]
    assert 'ownership' in calls[0][1]


def test_two_operations_are_generated_from_one_understanding(monkeypatch):
    query = '启动主变1的冷却风机，同时停止主变2的油泵'
    first = operation('启动主变1的冷却风机'); first['owner_id'] = 'SIM-TRANSFORMER-01'
    second = operation('停止主变2的油泵', 'SIM-MB-PUMP-01', 'stop'); second['owner_id'] = 'SIM-TRANSFORMER-02'
    app, params, before, calls = planned_app(monkeypatch, query, [first, second])
    result = app.analyze(AnalysisRequest(query, parameters=params))
    rows = result.data['simulation_batch']['items']
    assert [(row['device_id'], row['action']) for row in rows] == [('SIM-IEC-FAN-01', 'start'), ('SIM-MB-PUMP-01', 'stop')]
    assert all(row['source_query'] and row['scoped_query'] and row['decomposition'] for row in rows)
    assert len(calls) == 1
    assert app.simulation_runtime.snapshot(before['session_id']) == before


def test_ui_action_cannot_replace_semantic_action(monkeypatch):
    query = '请让主变1的冷却风机开始转动'
    app, params, _, calls = planned_app(monkeypatch, query, [operation(query)])
    result = app.analyze(AnalysisRequest(query, parameters={**params, 'action': 'stop'}))
    assert result.data.get('clarification_required') is True
    assert not (result.data.get('candidate_instruction') or {}).get('payload')
    assert not result.data.get('simulation_batch')
    assert len(calls) == 1


def test_state_modifier_does_not_override_requested_stop(monkeypatch):
    query = '停止已经启动的主变1的冷却风机'
    app, params, _, _ = planned_app(monkeypatch, query, [operation(query, action='stop')])
    result = app.analyze(AnalysisRequest(query, parameters=params))
    assert result.status == 'generated'
    assert result.data['candidate_instruction']['payload']['requested_action'] == 'stop'


def test_conflicting_explicit_ownership_never_adds_targets(monkeypatch):
    query = '启动主变1的冷却风机2'
    wrong = operation(query, device='SIM-MB-FAN-01'); wrong['owner_id'] = 'SIM-TRANSFORMER-01'
    app, params, before, _ = planned_app(monkeypatch, query, [wrong])
    result = app.analyze(AnalysisRequest(query, parameters=params))
    assert result.data.get('clarification_required') is True
    assert not result.data.get('simulation_batch')
    assert not (result.data.get('candidate_instruction') or {}).get('payload')
    assert app.simulation_runtime.snapshot(before['session_id']) == before


@pytest.mark.parametrize('query,changes', [
    ('请别将主变1的冷却风机启动', {}),
    ('不要将主变1的冷却风机有功功率设定为120kW', {}),
    ('待批准后启动主变1的冷却风机', {'conditions': ['批准后']}),
    ('先启动主变1的冷却风机', {'order': 1}),
    ('启动主变1的冷却风机', {'negated': True}),
])
def test_negation_conditions_and_order_fail_closed(monkeypatch, query, changes):
    item = operation(query); item.update(changes)
    app, params, before, calls = planned_app(monkeypatch, query, [item])
    result = app.analyze(AnalysisRequest(query, parameters=params))
    assert not (result.data.get('candidate_instruction') or {}).get('payload')
    assert not result.data.get('simulation_batch')
    assert len(calls) == 1
    assert app.simulation_runtime.snapshot(before['session_id']) == before


def test_online_missing_plan_schema_does_not_fall_back_to_hard_splitting(monkeypatch):
    query = '启动主变1的冷却风机，同时停止主变2的油泵'
    app, params, before, calls = planned_app(monkeypatch, query, [operation(query)], legacy=True)
    result = app.analyze(AnalysisRequest(query, parameters=params))
    assert result.data['model_understanding']['status'] == 'failed'
    assert not result.data.get('simulation_batch')
    assert len(calls) == 1
    assert app.simulation_runtime.snapshot(before['session_id']) == before


def test_status_query_consumes_the_same_semantic_device_binding(monkeypatch):
    query = '我想确认主变2那台冷却风机此刻是否运行。'
    queries = [{'device_id': 'SIM-MB-FAN-01', 'target_text': '主变2那台冷却风机',
                'owner_id': 'SIM-TRANSFORMER-02', 'query_kind': 'device_status',
                'source_text': query, 'clarification': ''}]
    app, params, before, calls = planned_app(monkeypatch, query, [], queries)
    result = app.analyze(AnalysisRequest(query, parameters=params))
    assert [device['device_id'] for device in result.data['devices']] == ['SIM-MB-FAN-01']
    assert not result.data.get('simulation_batch')
    assert not result.data.get('simulation_preview')
    assert len(calls) == 1
    assert app.simulation_runtime.snapshot(before['session_id']) == before


def test_invented_source_evidence_is_not_accepted(monkeypatch):
    query = '启动主变1的冷却风机'
    item = operation('启动主变2的冷却风机', device='SIM-MB-FAN-01')
    app, params, _, _ = planned_app(monkeypatch, query, [item])
    result = app.analyze(AnalysisRequest(query, parameters=params))
    assert not (result.data.get('candidate_instruction') or {}).get('payload')
    assert not result.data.get('simulation_batch')


@pytest.mark.parametrize('query', [
    '启动主变1的冷却风机和主变2的冷却风机',
    '启动主变1的冷却风机，同时停止主变2的油泵',
])
def test_omitted_explicit_targets_cannot_produce_a_partial_plan(monkeypatch, query):
    item = operation(query); item['owner_id'] = 'SIM-TRANSFORMER-01'
    app, params, _, _ = planned_app(monkeypatch, query, [item])
    result = app.analyze(AnalysisRequest(query, parameters=params))
    assert result.data.get('clarification_required') is True
    assert not result.data.get('simulation_preview')
    assert not result.data.get('simulation_batch')


def test_action_omitted_from_plan_but_present_in_summary_is_blocked(monkeypatch):
    query = '启动主变1的冷却风机，同时停止它'
    app, params, _, _ = planned_app(monkeypatch, query, [operation(query)])
    original = app.decomposer.complete
    def complete(*args):
        data = json.loads(original(*args)); data['actions'] = ['start', 'stop']
        return json.dumps(data, ensure_ascii=False)
    monkeypatch.setattr(app.decomposer, 'complete', complete)
    result = app.analyze(AnalysisRequest(query, parameters=params))
    assert not result.data.get('simulation_preview')


def test_model_cannot_invent_a_numeric_target_not_present_in_source(monkeypatch):
    query = '调整SIM-IEC-INVERTER-01的有功功率'
    item = operation(query, device='SIM-IEC-INVERTER-01', action='adjust_active_power')
    item['parameters'] = {'power_kw': 120}
    app, params, _, _ = planned_app(monkeypatch, query, [item])
    result = app.analyze(AnalysisRequest(query, parameters=params))
    assert not result.data.get('simulation_preview')


def test_operation_and_status_query_share_one_understanding(monkeypatch):
    query = '启动主变1的冷却风机，同时查询主变2的油泵状态'
    item = operation('启动主变1的冷却风机'); item['owner_id'] = 'SIM-TRANSFORMER-01'
    questions = [{'device_id': 'SIM-MB-PUMP-01', 'target_text': '主变2的油泵',
                  'owner_id': 'SIM-TRANSFORMER-02', 'query_kind': 'device_status',
                  'source_text': '查询主变2的油泵状态', 'clarification': ''}]
    app, params, before, calls = planned_app(monkeypatch, query, [item], questions)
    result = app.analyze(AnalysisRequest(query, parameters=params))
    assert result.status == 'generated'
    assert result.data['query_results'][0]['devices'][0]['device_id'] == 'SIM-MB-PUMP-01'
    assert len(calls) == 1
    assert app.simulation_runtime.snapshot(before['session_id']) == before


def test_shared_owner_suffix_from_observed_model_output_has_grounded_targets(monkeypatch):
    query = '启动主变1和主变2各自的冷却风机'
    first = operation(query); first.update(target_text='主变1的冷却风机', owner_id='SIM-TRANSFORMER-01')
    second = operation(query, device='SIM-MB-FAN-01'); second.update(target_text='主变2的冷却风机', owner_id='SIM-TRANSFORMER-02')
    app, params, before, calls = planned_app(monkeypatch, query, [first, second])
    result = app.analyze(AnalysisRequest(query, parameters=params))
    assert result.status == 'generated'
    assert {row['device_id'] for row in result.data['simulation_batch']['items']} == {'SIM-IEC-FAN-01', 'SIM-MB-FAN-01'}
    assert len(calls) == 1
    assert app.simulation_runtime.snapshot(before['session_id']) == before


def test_operation_and_standard_query_use_one_understanding_and_one_advice_call(monkeypatch):
    from standard_knowledge_service_v2.application.grounded_advice import GroundedAdviceService
    from test_grounded_advice import setup, Client
    query = '启动主变1的冷却风机，同时说明DL/T 664的温度要求'
    op = operation('启动主变1的冷却风机'); op['owner_id'] = 'SIM-TRANSFORMER-01'
    questions = [{'device_id': '', 'target_text': 'DL/T 664', 'owner_id': '',
                  'query_kind': 'standard_query', 'source_text': '说明DL/T 664的温度要求', 'clarification': ''}]
    app, params, before, calls = planned_app(monkeypatch, query, [op], questions)
    knowledge, _, proposal, _ = setup()
    from types import SimpleNamespace
    class Retriever:
        repository = knowledge.retriever.repository
        def match(self, *_):
            rule = self.repository.unit_for_rule('r1').rules[0]
            return SimpleNamespace(rules=[SimpleNamespace(rule=rule, rank=1, combined_score=1)], warnings=[], matched_entities=[])
    app.retriever = Retriever()
    proposal['instruction'] = None
    advice_calls = []
    client = Client(proposal)
    def complete(*args):
        advice_calls.append(args)
        return client.complete(*args)
    app.advisor = GroundedAdviceService(type('AdviceClient', (), {'complete': staticmethod(complete)})())
    result = app.analyze(AnalysisRequest(query, parameters=params))
    assert result.data['simulation_preview']['status'] == 'generated'
    assert len(calls) == len(advice_calls) == 1
    assert result.data['query_results'][0]['data'].get('advice') is not None
    assert app.simulation_runtime.snapshot(before['session_id']) == before


def test_length_finished_response_is_rejected_even_when_json_is_parseable(monkeypatch):
    query = '启动主变1的冷却风机'
    app, params, _, _ = planned_app(monkeypatch, query, [operation(query)])
    content = app.decomposer.complete('', '')
    from standard_knowledge_service_v2.decomposition.remote_model_decomposer import RemoteModelDecomposer
    monkeypatch.setattr(app.decomposer, 'complete', RemoteModelDecomposer.complete.__get__(app.decomposer))
    monkeypatch.setenv('MODEL_API_KEY', 'local-test-key')
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self):
            return json.dumps({'choices': [{'finish_reason': 'length', 'message': {'content': content}}]}).encode()
    requests = []
    def urlopen(request, **_):
        requests.append(request)
        return Response()
    monkeypatch.setattr('standard_knowledge_service_v2.decomposition.remote_model_decomposer.urlopen', urlopen)
    result = app.analyze(AnalysisRequest(query, parameters=params))
    assert result.data['model_understanding']['status'] == 'failed'
    assert not result.data.get('simulation_preview')
    assert json.loads(requests[0].data)['max_tokens'] >= 4096


@pytest.mark.parametrize('mutation', ['missing_query_list', 'missing_negation', 'invalid_order', 'query_kind'])
def test_incomplete_or_mistyped_semantic_schema_fails_closed(monkeypatch, mutation):
    query = '启动主变1的冷却风机'
    app, params, _, _ = planned_app(monkeypatch, query, [operation(query)])
    original = app.decomposer.complete
    def complete(*args):
        data = json.loads(original(*args))
        if mutation == 'missing_query_list': data.pop('queries')
        elif mutation == 'missing_negation': data['operations'][0].pop('negated')
        elif mutation == 'invalid_order': data['operations'][0]['order'] = True
        else:
            data['operations'] = []
            data['scenario']['query_kind'] = 'device_status'
            data['queries'] = [{'device_id':'SIM-IEC-FAN-01','target_text':query,'owner_id':'',
                'source_text':query,'query_kind':'execute','clarification':''}]
        return json.dumps(data)
    monkeypatch.setattr(app.decomposer, 'complete', complete)
    result = app.analyze(AnalysisRequest(query, parameters=params))
    assert result.data['model_understanding']['status'] == 'failed'


def test_model_resolved_pronoun_must_match_the_previous_user_device(monkeypatch):
    query = '请让刚才查询的设备开始转动'
    app, params, _, calls = planned_app(monkeypatch, query, [operation(query)])
    result = app.analyze(AnalysisRequest(query, parameters=params,
        conversation_context=[{'role':'user','content':'查询主变1冷却风机'}]))
    assert result.status == 'generated'
    assert len(calls) == 1
    result = app.analyze(AnalysisRequest(query, parameters=params,
        conversation_context=[{'role':'user','content':'查询主变2冷却风机'}]))
    assert not result.data.get('simulation_preview')
