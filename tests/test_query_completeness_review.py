"""Query plans preserve every requested target and each kind of local answer."""
import json
from copy import deepcopy

import pytest

from standard_knowledge_service_v2.application import AnalysisPipeline
from standard_knowledge_service_v2.application.simulation_query import answer_simulation_query
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.decomposition import RemoteModelConfig, RemoteModelDecomposer
from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime
from standard_knowledge_service_v2.retrieval_engine import JsonClauseRepository, LocalLunwenRetrievalAdapter


def question(source, target, device='SIM-IEC-FAN-01', kind='device_status', owner=''):
    return {'source_text': source, 'target_text': target, 'device_id': device,
            'query_kind': kind, 'owner_id': owner, 'clarification': ''}


def operation(source, device='SIM-IEC-FAN-01', **changes):
    result = {'source_text': source, 'target_text': source, 'device_id': device,
              'owner_id': '', 'action': 'start', 'parameters': {}, 'negated': False,
              'conditions': [], 'order': None, 'clarification': ''}
    result.update(changes)
    return result


def semantic_answer(monkeypatch, query, queries, operations=(), kind='device_status', context=()):
    """Keep model parsing and runtime real; replace the external completion only."""
    model = RemoteModelDecomposer(RemoteModelConfig('https://example.test', 'controlled'))
    calls = []
    def complete(system, user):
        calls.append((system, user))
        return json.dumps({'intent': 'instruction' if operations else 'search',
            'entities': [], 'actions': list(dict.fromkeys(row['action'] for row in operations)),
            'constraints': [], 'standard_refs': [], 'keywords': ['设备'],
            'scenario': {'query_kind': kind, 'operating_condition': ''}, 'confidence': .95,
            'operations': deepcopy(list(operations)), 'queries': deepcopy(queries)}, ensure_ascii=False)
    monkeypatch.setattr(model, 'complete', complete)
    app = AnalysisPipeline(LocalLunwenRetrievalAdapter(JsonClauseRepository([])), decomposer=model)
    app.simulation_runtime = SimulationRuntime(event_path=None)
    before = app.simulation_runtime.create_session('all_devices')
    request = AnalysisRequest(query, parameters={'simulation_mode': True,
        'simulation_session_id': before['session_id'], 'simulation_scenario_id': 'all_devices'},
        conversation_context=list(context))
    parsed = model.decompose(query, conversation_context=list(context))
    assert parsed.valid, parsed.errors
    result = answer_simulation_query(app, request, decomposed=parsed)
    assert len(calls) == 1
    assert app.simulation_runtime.snapshot(before['session_id']) == before
    return result


def test_full_source_cannot_hide_a_missing_explicit_query_device(monkeypatch):
    query = '查询SIM-IEC-FAN-01和SIM-MB-FAN-01的状态'
    result = semantic_answer(monkeypatch, query, [question(query, 'SIM-IEC-FAN-01')])
    assert result[0] != 'answered'
    assert result[1]['clarification_required'] is True


def test_query_sources_must_cover_the_complete_request(monkeypatch):
    query = '查询SIM-IEC-FAN-01的状态，同时说明它支持哪些操作'
    result = semantic_answer(monkeypatch, query, [question('查询SIM-IEC-FAN-01的状态', 'SIM-IEC-FAN-01')])
    assert result[0] != 'answered'
    assert result[1]['clarification_required'] is True


def test_owner_description_does_not_add_a_transformer_query(monkeypatch):
    query = '查询主变1那台冷却风机的状态'
    result = semantic_answer(monkeypatch, query, [question(query, '主变1那台冷却风机', owner='SIM-TRANSFORMER-01')])
    assert result[0] == 'answered'
    assert [row['device_id'] for row in result[1]['devices']] == ['SIM-IEC-FAN-01']


@pytest.mark.parametrize('target', ['主变2那台冷却风机', '主变 2 的冷却风机'])
def test_owner_description_remains_grounded_with_modifiers_and_spaces(monkeypatch, target):
    query = '查询' + target + '的状态'
    result = semantic_answer(monkeypatch, query,
        [question(query, target, 'SIM-MB-FAN-01', owner='SIM-TRANSFORMER-02')])
    assert result[0] == 'answered'
    assert [row['device_id'] for row in result[1]['devices']] == ['SIM-MB-FAN-01']


@pytest.mark.parametrize('first,second', [('主变1', '主变2'),
    ('SIM-TRANSFORMER-01', 'SIM-TRANSFORMER-02')])
def test_coordinated_owners_share_a_grounded_accessory_suffix(monkeypatch, first, second):
    query = f'查询{first}和{second}各自的冷却风机状态'
    rows = [question(query, first + '的冷却风机', owner='SIM-TRANSFORMER-01'),
            question(query, second + '的冷却风机', 'SIM-MB-FAN-01', owner='SIM-TRANSFORMER-02')]
    result = semantic_answer(monkeypatch, query, rows)
    assert result[0] == 'answered'
    assert {row['device_id'] for row in result[1]['devices']} == {'SIM-IEC-FAN-01', 'SIM-MB-FAN-01'}


def test_independently_requested_owner_is_not_covered_by_an_accessory_row(monkeypatch):
    query = '查询主变1和主变1的冷却风机状态'
    result = semantic_answer(monkeypatch, query, [question(query, '主变1的冷却风机', owner='SIM-TRANSFORMER-01')])
    assert result[0] != 'answered'
    assert result[1]['clarification_required'] is True


def test_status_and_capability_are_answered_by_each_query_kind(monkeypatch):
    query = '查询SIM-IEC-FAN-01的状态，同时说明SIM-MB-PUMP-01支持哪些操作'
    rows = [question('查询SIM-IEC-FAN-01的状态', 'SIM-IEC-FAN-01'),
            question('说明SIM-MB-PUMP-01支持哪些操作', 'SIM-MB-PUMP-01', 'SIM-MB-PUMP-01', 'device_capability')]
    result = semantic_answer(monkeypatch, query, rows)
    assert result[0] == 'answered'
    data = result[1]
    assert [(row['query_kind'], row['devices'][0]['device_id']) for row in data['query_results']] == [
        ('device_status', 'SIM-IEC-FAN-01'), ('device_capability', 'SIM-MB-PUMP-01')]
    assert data['query_results'][0]['devices'][0]['state']['running'] is False
    assert {'start', 'stop'} <= set(data['query_results'][1]['devices'][0]['actions'])
    assert '可用操作' in data['answer']['text']
    assert {row['device_id'] for row in data['device_capabilities']} == {'SIM-IEC-FAN-01', 'SIM-MB-PUMP-01'}


def test_same_sentence_pronoun_uses_the_preceding_explicit_query(monkeypatch):
    query = '查询SIM-IEC-FAN-01的状态，同时说明它支持哪些操作'
    rows = [question('查询SIM-IEC-FAN-01的状态', 'SIM-IEC-FAN-01'),
            question('说明它支持哪些操作', '它', kind='device_capability')]
    result = semantic_answer(monkeypatch, query, rows)
    assert result[0] == 'answered'
    assert [row['devices'][0]['device_id'] for row in result[1]['query_results']] == ['SIM-IEC-FAN-01'] * 2


def test_pronoun_after_two_coordinated_devices_requires_clarification(monkeypatch):
    source = '查询SIM-IEC-FAN-01和SIM-MB-FAN-01的状态'
    query = source + '，同时说明它支持哪些操作'
    rows = [question(source, 'SIM-IEC-FAN-01'),
            question(source, 'SIM-MB-FAN-01', 'SIM-MB-FAN-01'),
            question('说明它支持哪些操作', '它', kind='device_capability')]
    result = semantic_answer(monkeypatch, query, rows,
        context=[{'role': 'user', 'content': '查询SIM-IEC-FAN-01的状态'}])
    assert result[0] != 'answered'
    assert result[1]['clarification_required'] is True


def test_mixed_standard_query_keeps_the_fact_answer_for_pipeline_aggregation(monkeypatch):
    query = '查询SIM-IEC-FAN-01的状态，同时说明DL/T 664的温度要求'
    rows = [question('查询SIM-IEC-FAN-01的状态', 'SIM-IEC-FAN-01'),
            question('说明DL/T 664的温度要求', 'DL/T 664', '', 'standard_query')]
    result = semantic_answer(monkeypatch, query, rows, kind='standard_query')
    assert result is not None
    assert result[0] == 'answered'
    assert [row['query_kind'] for row in result[1]['query_results']] == ['device_status']
    assert result[1]['candidate_instruction'] is None


def test_only_standard_queries_continue_through_the_knowledge_path(monkeypatch):
    query = '说明DL/T 664的温度要求'
    assert semantic_answer(monkeypatch, query,
        [question(query, 'DL/T 664', '', 'standard_query')], kind='standard_query') is None


def test_explicit_operation_is_consumed_even_when_top_level_kind_is_standard(monkeypatch):
    query = '请启动SIM-IEC-FAN-01'
    result = semantic_answer(monkeypatch, query, [], [operation(query)], kind='standard_query')
    assert result[0] == 'generated'
    assert result[1]['candidate_instruction']['target'] == 'SIM-IEC-FAN-01'


def test_again_is_a_single_action_not_a_sequence(monkeypatch):
    query = '请再次启动SIM-IEC-FAN-01'
    result = semantic_answer(monkeypatch, query, [], [operation(query)], kind='operation')
    assert result[0] == 'generated'
    assert result[1]['simulation_preview']['command_id']


@pytest.mark.parametrize('change', [{'order': 1}, {'conditions': ['检查通过']}, {'negated': True}])
def test_structured_execution_restrictions_still_prevent_previews(monkeypatch, change):
    query = '启动SIM-IEC-FAN-01'
    result = semantic_answer(monkeypatch, query, [], [operation(query, **change)], kind='operation')
    assert result[0] != 'generated'
    assert not result[1].get('simulation_preview')
    assert result[1]['candidate_instruction'] is None


@pytest.mark.parametrize('query', ['仅在检查通过后启动SIM-IEC-FAN-01',
    '假如检查通过，启动SIM-IEC-FAN-01', '启动SIM-IEC-FAN-01，前提是检查通过'])
def test_existing_explicit_condition_wording_still_blocks_unconditional_previews(monkeypatch, query):
    result = semantic_answer(monkeypatch, query, [], [operation(query)], kind='operation')
    assert result[0] != 'generated'
    assert not result[1].get('simulation_preview')
    assert result[1]['candidate_instruction'] is None


def test_two_ordered_actions_remain_blocked(monkeypatch):
    query = '先启动SIM-IEC-FAN-01，随后启动SIM-MB-FAN-01'
    ops = [operation('先启动SIM-IEC-FAN-01', order=1),
           operation('随后启动SIM-MB-FAN-01', device='SIM-MB-FAN-01', order=2)]
    result = semantic_answer(monkeypatch, query, [], ops, kind='operation')
    assert result[0] != 'generated'
    assert not result[1].get('simulation_batch')
    assert result[1]['candidate_instruction'] is None
