"""Dynamic references describe advice; protocol conversion uses device templates."""
from copy import deepcopy
import json
import pytest

from test_grounded_advice import Client, setup
from standard_knowledge_service_v2.application.grounded_advice import GroundedAdviceService
from standard_knowledge_service_v2.application.simulation_access import simulation_runtime
from standard_knowledge_service_v2.domain import Rule


def unbound_setup(**kwargs):
    pipeline, data, proposal, request = setup(**kwargs)
    template = pipeline.simulation_session.service.devices['SIM-IEC-BREAKER-01']['actions']['trip']
    template.pop('source_rule_ids', None)
    template.pop('source_bindings', None)
    return pipeline, data, proposal, request


def test_unbound_advice_converts_empty_actions_and_natural_conditions():
    pipeline, data, proposal, request = unbound_setup(action='', condition='满足条款说明的自然语言条件', reviewed=False)
    before = pipeline.simulation_session.snapshot()
    assert GroundedAdviceService(Client(proposal)).enrich(pipeline, request, data) == 'generated'
    assert data['candidate_instruction']['payload']['requested_action'] == 'trip'
    assert data['simulation_preview']['simulation_execution_allowed'] is True
    assert data['simulation_session_id']
    assert data['advice']['sources'][0]['manual_review_required'] is True
    assert pipeline.simulation_session.snapshot() == before
    assert data['candidate_instruction']['evidence'][0]['rule_id'] == 'r1'


def test_multiple_retrieved_clauses_can_support_one_unbound_proposal():
    pipeline, data, proposal, request = unbound_setup(action='', condition='')
    unit = pipeline.retriever.repository.unit_for_rule('r1')
    unit.rules.append(Rule('r2', '断路器', '', '', content='另一条独立测试说明，供模拟分析引用。'))
    pipeline.retriever.repository.unit_for_rule = lambda key: unit if key in {'r1', 'r2'} else None
    data['matching'] = {'rules': [{'rule_id': 'r1'}, {'rule_id': 'r2'}]}
    proposal['instruction']['rule_ids'] = ['r1', 'r2']
    assert GroundedAdviceService(Client(proposal)).enrich(pipeline, request, data) == 'generated'
    assert {e['rule_id'] for e in data['candidate_instruction']['evidence']} == {'r1', 'r2'}
    runtime = simulation_runtime(pipeline)
    preview = data['simulation_preview']
    result = runtime.execute(data['simulation_session_id'], preview['command_id'], preview['expected_version'])
    assert result['status'] == 'succeeded'
    assert {e['rule_id'] for e in result['candidate']['evidence']} == {'r1', 'r2'}


def test_state_change_during_model_analysis_invalidates_advice_preview():
    pipeline, data, proposal, request = unbound_setup()
    runtime = simulation_runtime(pipeline)
    sid = runtime.create_session()['session_id']
    request.parameters['simulation_session_id'] = sid
    class ChangingClient:
        def complete(self, *_):
            runtime.set_condition(sid, 'maintenance')
            return json.dumps(proposal, ensure_ascii=False)
    assert GroundedAdviceService(ChangingClient()).enrich(pipeline, request, data) != 'generated'
    assert not (data.get('candidate_instruction') or {}).get('payload')
    assert data['advice']['conversion']['status'] == 'blocked'
    assert '变化' in data['advice']['conversion']['reason']


def test_template_interlocks_remain_required_without_clause_binding():
    pipeline, data, proposal, request = unbound_setup()
    runtime = simulation_runtime(pipeline)
    sid = runtime.create_session(condition='cooling_fault')['session_id']
    request.query = '依据条款，主变1的冷却风机应如何处理？'
    request.parameters['simulation_session_id'] = sid
    proposal['instruction'].update(text='建议启动模拟冷却风机1', device_id='SIM-IEC-FAN-01', action='start')
    assert GroundedAdviceService(Client(proposal)).enrich(pipeline, request, data) != 'generated'
    assert not (data.get('candidate_instruction') or {}).get('payload')
    assert data['advice']['conversion']['status'] == 'blocked'


def test_explicitly_conflicting_source_scenario_is_not_reported_as_applicable():
    pipeline, data, proposal, request = unbound_setup()
    pipeline.retriever.repository.unit_for_rule('r1').metadata['scenario'] = 'offshore_wind'
    assert GroundedAdviceService(Client(proposal)).enrich(pipeline, request, data) != 'generated'
    assert data['advice']['conversion']['status'] == 'blocked'
    assert not (data.get('candidate_instruction') or {}).get('payload')


def test_catalog_tap_action_is_supported_without_a_legacy_action_word_entry():
    pipeline, data, proposal, request = unbound_setup()
    runtime = simulation_runtime(pipeline)
    sid = runtime.create_session()['session_id']
    request.query = '依据条款，SIM-IEC-TAP-01应如何操作？'
    request.parameters['simulation_session_id'] = sid
    proposal['instruction'].update(text='建议升一档', device_id='SIM-IEC-TAP-01', action='raise')
    before = deepcopy(runtime.snapshot(sid))
    assert GroundedAdviceService(Client(proposal)).enrich(pipeline, request, data) == 'generated'
    assert data['candidate_instruction']['payload']['requested_action'] == 'raise'
    assert runtime.snapshot(sid) == before


@pytest.mark.parametrize('mode', ['disabled', 'invalid_output', 'empty_proposal', 'no_source'])
def test_old_preview_and_generation_are_not_retained_on_failed_or_empty_advice(mode):
    pipeline, data, proposal, request = unbound_setup()
    data['simulation_preview'] = {'status': 'generated', 'command_id': 'old-command'}
    data['instruction_generation'] = {'status': 'generated'}
    data['candidate_instruction'] = {'payload': {'old': True}}
    client = Client(proposal)
    if mode == 'disabled': client = None
    if mode == 'invalid_output': client = Client({'bad': True})
    if mode == 'empty_proposal': proposal['instruction'] = None
    if mode == 'no_source': data['selected_rule']['rule_id'] = 'missing'
    GroundedAdviceService(client).enrich(pipeline, request, data)
    assert not (data.get('candidate_instruction') or {}).get('payload')
    assert not data.get('simulation_preview')
    assert not data.get('instruction_generation')


@pytest.mark.parametrize('word', ['不要生成建议', '取消指令生成'])
def test_user_cancellation_does_not_generate_an_unbound_preview(word):
    pipeline, data, proposal, request = unbound_setup()
    request.query += word
    GroundedAdviceService(Client(proposal)).enrich(pipeline, request, data)
    assert data['advice']['conversion']['status'] == 'blocked'
    assert not data.get('simulation_preview')


def test_invalid_session_still_returns_source_analysis_with_no_command():
    pipeline, data, proposal, request = unbound_setup()
    request.parameters['simulation_session_id'] = 'missing'
    GroundedAdviceService(Client(proposal)).enrich(pipeline, request, data)
    assert data['advice']['status'] == 'generated'
    assert data['advice']['conversion']['status'] == 'blocked'
    assert '会话不存在' in data['advice']['conversion']['reason']


@pytest.mark.parametrize('name', ['主变1', '模拟变压器1', 'SIM-TRANSFORMER-01'])
def test_transformer_reference_resolves_the_requested_associated_fan(name):
    pipeline, data, proposal, request = unbound_setup()
    request.query = f'依据条款，{name}的冷却风机应如何处理？'
    proposal['instruction'].update(text='建议启动冷却风机', action='start', device_id='SIM-IEC-FAN-01')
    client = Client(proposal)
    assert GroundedAdviceService(client).enrich(pipeline, request, data) == 'generated'
    assert client.packet['device']['device_id'] == 'SIM-IEC-FAN-01'
    assert data['simulation_preview']['candidate']['target'] == 'SIM-IEC-FAN-01'


@pytest.mark.parametrize('text', ['不要启动风机', '不应启动风机', '禁止启动风机',
                                 '是否启动风机', '启动风机吗？', '启动风机与否待确认',
                                 '启动风机并停止油泵', '启动风机并合闸'])
def test_negative_question_or_multiple_model_actions_do_not_create_a_command(text):
    pipeline, data, proposal, request = unbound_setup()
    request.query = '依据条款，主变1的冷却风机应如何处理？'
    proposal['instruction'].update(text=text, action='start', device_id='SIM-IEC-FAN-01')
    GroundedAdviceService(Client(proposal)).enrich(pipeline, request, data)
    assert data['advice'].get('error_code') == 'invalid_model_output'
    assert not data.get('simulation_preview')
    assert not (data.get('candidate_instruction') or {}).get('payload')
