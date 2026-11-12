"""Deterministic guards; acceptance also runs with the actual online provider."""
import json
from types import SimpleNamespace

import pytest

from standard_knowledge_service_v2.application import AnalysisPipeline
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.decomposition import RemoteModelConfig, RemoteModelDecomposer
from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime
from standard_knowledge_service_v2.retrieval_engine import JsonClauseRepository, LocalLunwenRetrievalAdapter


def app_for(monkeypatch, *, intent='search', actions=None, constraints=None, query_kind=None, entities=None, operating_condition=''):
    decomposer = RemoteModelDecomposer(RemoteModelConfig(
        api_base='https://example.test', model='test-model', api_key_env='API_FIRST_TEST_UNUSED'
    ))
    calls = []
    review_calls = []
    def complete(system, user):
        if 'OPERATION_PLAN_REVIEW' in system:
            from semantic_fixture_helpers import approve_review_packet
            review_calls.append((system, user))
            return json.dumps(approve_review_packet(json.loads(user)), ensure_ascii=False)
        calls.append(user)
        kind = query_kind or ('operation' if intent == 'instruction' else 'device_status')
        from semantic_fixture_helpers import add_semantic_plan
        q = user.split('用户问题：', 1)[1].split('\n请严格')[0]
        return json.dumps(add_semantic_plan({'intent':intent,'entities':entities or [{'name':'主变1','type':'设备'}],
            'actions':actions or [],'constraints':constraints or [],'standard_refs':[],
            'scenario':{'scenario_type':'substation_maintenance','device_type':'变压器','query_kind':kind,'operating_condition':operating_condition},
            'keywords':['主变1'],'confidence':0.9}, q, app.simulation_runtime.catalog, parameters.get('simulation_scenario_id','all_devices')),ensure_ascii=False)
    monkeypatch.setattr(decomposer, 'complete', complete)
    app = AnalysisPipeline(LocalLunwenRetrievalAdapter(JsonClauseRepository([])),decomposer=decomposer)
    app.simulation_runtime = SimulationRuntime(event_path=None)
    snapshot = app.simulation_runtime.create_session('all_devices')
    parameters = {'simulation_mode':True,'simulation_session_id':snapshot['session_id'],
                  'simulation_scenario_id':'substation_maintenance'}
    app._test_review_calls = review_calls
    return app, parameters, snapshot, calls


@pytest.mark.parametrize('query', ['主变1当前状态如何？','主变1的冷却风机支持哪些操作？','启动主变1的冷却风机'])
def test_all_natural_queries_understand_before_reading_snapshot(monkeypatch, query):
    app, parameters, _, calls = app_for(monkeypatch, intent='instruction', actions=['start'])
    original = app.simulation_runtime.snapshot
    def snapshot(sid):
        assert len(calls)==1, 'must understand before reading state'
        return original(sid)
    monkeypatch.setattr(app.simulation_runtime,'snapshot',snapshot)
    response = app.analyze(AnalysisRequest(query,parameters=parameters))
    assert len(calls)==1
    assert response.data['decomposition']['source']=='model_api'


def test_failed_online_understanding_does_not_generate_a_local_preview(monkeypatch):
    app, parameters, before, _ = app_for(monkeypatch)
    from standard_knowledge_service_v2.decomposition.model_errors import ModelCallError
    def failed(*args):
        raise ModelCallError('network_timeout')
    monkeypatch.setattr(app.decomposer,'complete',failed)
    response = app.analyze(AnalysisRequest('启动主变1的冷却风机',parameters=parameters))
    assert response.status=='partial'
    assert response.data['model_understanding']['status']=='failed'
    assert response.data.get('candidate_instruction') is None
    assert app.simulation_runtime.snapshot(before['session_id'])==before


@pytest.mark.parametrize('query', ['禁止启动主变1的冷却风机','不应启动主变1的冷却风机','主变1的冷却风机启动了吗？',
    '不要开启主变1的冷却风机','不执行主变1的冷却风机启动','能否启动主变1的冷却风机','请开启主变1的冷却风机？'])
def test_original_query_guards_survive_an_incorrect_model_instruction(monkeypatch, query):
    app, parameters, _, calls = app_for(monkeypatch,intent='instruction',actions=['start'])
    response=app.analyze(AnalysisRequest(query,parameters=parameters))
    assert len(calls)==1
    assert not (response.data.get('candidate_instruction') or {}).get('payload')


def test_understood_condition_cannot_be_dropped_from_preview(monkeypatch):
    app, parameters, _, calls=app_for(monkeypatch,intent='instruction',actions=['start'],
        constraints=[{'parameter':'绕组热点温升','operator':'>','value':'80','unit':'K','condition':'主变1'}])
    response=app.analyze(AnalysisRequest('如果主变1温升超过80K，就启动主变1的冷却风机',parameters=parameters))
    assert len(calls)==1
    assert not (response.data.get('candidate_instruction') or {}).get('payload')
    assert response.data['decomposition']['constraints'][0]['value']=='80'


@pytest.mark.parametrize('query,actions', [
    ('先停止主变1的冷却风机，再启动它',['stop','start']),
    ('将主变1的调压装置设定为8.5档',['regulate_voltage']),
    ('将主变1的调压装置设定为-1档',['regulate_voltage']),
])
def test_single_action_preview_does_not_change_understood_request(monkeypatch,query,actions):
    app, parameters, _, calls=app_for(monkeypatch,intent='instruction',actions=actions)
    response=app.analyze(AnalysisRequest(query,parameters=parameters))
    assert len(calls)==1
    assert not (response.data.get('candidate_instruction') or {}).get('payload')


def test_plain_start_still_generates_only_a_preview(monkeypatch):
    app, parameters, before, calls=app_for(monkeypatch,intent='instruction',actions=['start'])
    response=app.analyze(AnalysisRequest('启动主变1的冷却风机',parameters=parameters))
    assert len(calls)==1 and response.status=='generated'
    assert response.data['candidate_instruction']['payload']['requested_action']=='start'
    assert app.simulation_runtime.snapshot(before['session_id'])==before


def test_parallel_devices_remain_parallel_after_model_understanding(monkeypatch):
    app, parameters, _, calls=app_for(monkeypatch)
    response=app.analyze(AnalysisRequest('比较主变1和断路器2的当前状态',parameters=parameters))
    assert len(calls)==1
    assert {d['device_id'] for d in response.data['devices']}=={'SIM-TRANSFORMER-01','SIM-MB-BREAKER-01'}


def test_unknown_number_is_not_replaced_with_registered_devices(monkeypatch):
    app, parameters, _, calls=app_for(monkeypatch)
    response=app.analyze(AnalysisRequest('主变99当前状态如何？',parameters=parameters))
    assert len(calls)==1 and response.status=='uncertain'
    assert response.data['devices']==[]


def test_temperature_assessment_reuses_first_understanding(monkeypatch):
    app, parameters, _, calls=app_for(monkeypatch)
    response=app.analyze(AnalysisRequest('主变1温升状态是否正常？',parameters=parameters))
    assert len(calls)==1
    assert response.data['decomposition']['source']=='model_api'


def test_model_routes_operation_without_old_action_keywords(monkeypatch):
    app, parameters, before, calls=app_for(monkeypatch,intent='instruction',actions=['start'],query_kind='operation')
    response=app.analyze(AnalysisRequest('请让主变1的冷却风机开始转动',parameters=parameters))
    assert len(calls)==1 and response.status=='generated'
    assert response.data['candidate_instruction']['payload']['requested_action']=='start'
    assert app.simulation_runtime.snapshot(before['session_id'])==before


def test_model_entity_resolves_a_followup_without_lexical_target(monkeypatch):
    app, parameters, _, calls=app_for(monkeypatch,query_kind='device_status',
        entities=[{'name':'SIM-IEC-FAN-01','type':'设备'}])
    response=app.analyze(AnalysisRequest('它现在怎样？',parameters=parameters,
        conversation_context=[{'role':'user','content':'刚才查询的是主变1的冷却风机'}]))
    assert len(calls)==1 and response.status=='answered'
    assert [d['device_id'] for d in response.data['devices']]==['SIM-IEC-FAN-01']


def test_model_assessment_route_is_not_hidden_by_local_facts(monkeypatch):
    app, parameters, _, calls=app_for(monkeypatch,query_kind='assessment')
    response=app.analyze(AnalysisRequest('帮我判断主变1的工况是否有问题',parameters=parameters))
    assert len(calls)==1
    assert 'device_assessment' in response.data


def test_postfix_explicit_action_keeps_existing_behavior(monkeypatch):
    app, parameters, _, calls=app_for(monkeypatch,intent='instruction',actions=['trip'],query_kind='operation')
    response=app.analyze(AnalysisRequest('模拟断路器1分闸',parameters=parameters))
    assert len(calls)==1 and response.status=='generated'


def test_online_parse_without_routing_kind_does_not_use_keyword_shortcut(monkeypatch):
    app, parameters, _, calls=app_for(monkeypatch,intent='instruction',actions=['start'])
    original=app.decomposer.complete
    def missing_kind(*args):
        value=json.loads(original(*args))
        value['scenario'].pop('query_kind')
        return json.dumps(value)
    monkeypatch.setattr(app.decomposer,'complete',missing_kind)
    response=app.analyze(AnalysisRequest('启动主变1的冷却风机',parameters=parameters))
    assert len(calls)==1 and response.status=='partial'
    assert response.data.get('candidate_instruction') is None


def test_disabling_advice_does_not_enable_offline_understanding(monkeypatch):
    app, parameters, _, _=app_for(monkeypatch)
    app.config=SimpleNamespace(advice_enabled=False,llm=SimpleNamespace(allow_offline_fallback=False))
    from standard_knowledge_service_v2.decomposition.model_errors import ModelCallError
    def failed(*args): raise ModelCallError('network_timeout')
    monkeypatch.setattr(app.decomposer,'complete',failed)
    response=app.analyze(AnalysisRequest('启动主变1的冷却风机',parameters=parameters))
    assert response.status=='partial'
    assert response.data.get('candidate_instruction') is None


def test_natural_condition_without_numeric_operator_is_preserved(monkeypatch):
    app, parameters, _, _=app_for(monkeypatch,intent='instruction',actions=['start'],
        constraints=[{'parameter':'许可','operator':'','value':'','condition':'负责人确认后'}])
    response=app.analyze(AnalysisRequest('请启动主变1的冷却风机，待负责人确认后进行',parameters=parameters))
    assert not (response.data.get('candidate_instruction') or {}).get('payload')


def test_assessment_reuses_the_model_resolved_followup_target(monkeypatch):
    app, parameters, _, _=app_for(monkeypatch,query_kind='assessment',
        entities=[{'name':'SIM-TRANSFORMER-01','type':'设备'}])
    response=app.analyze(AnalysisRequest('帮我判断它的工况是否有问题',parameters=parameters,
        conversation_context=[{'role':'user','content':'查询主变1'}]))
    assert response.data['device_assessment']['device_id']=='SIM-TRANSFORMER-01'


def test_standard_advice_cannot_lose_the_original_user_condition():
    from test_grounded_advice import setup, Client
    from standard_knowledge_service_v2.application.grounded_advice import GroundedAdviceService
    app, data, proposal, request=setup()
    request.query='依据标准，如果电流超过1000A则模拟断路器1分闸'
    data['decomposition']={'constraints':[{'parameter':'电流','operator':'>','value':'1000','unit':'A'}]}
    GroundedAdviceService(Client(proposal)).enrich(app,request,data)
    assert not (data.get('candidate_instruction') or {}).get('payload')


@pytest.mark.parametrize('query,extra', [
    ('请启动主变1的冷却风机和主变99的冷却风机',{}),
    ('启动主变2的冷却风机',{'device_id':'SIM-TRANSFORMER-01'}),
])
def test_incomplete_or_conflicting_targets_do_not_choose_one_known_device(monkeypatch,query,extra):
    app, parameters, _, _=app_for(monkeypatch,intent='instruction',actions=['start'])
    response=app.analyze(AnalysisRequest(query,parameters={**parameters,**extra}))
    assert response.status=='uncertain'
    assert not (response.data.get('candidate_instruction') or {}).get('payload')


def test_model_paraphrased_condition_is_not_required_to_match_original_words(monkeypatch):
    app, parameters, _, _=app_for(monkeypatch,intent='instruction',actions=['start'],operating_condition='经维护人员许可后')
    response=app.analyze(AnalysisRequest('请启动主变1的冷却风机，前提是维护人员已经批准',parameters=parameters))
    assert not (response.data.get('candidate_instruction') or {}).get('payload')


def test_tap_precondition_is_not_mistaken_for_target_assignment(monkeypatch):
    app, parameters, _, _=app_for(monkeypatch,intent='instruction',actions=['regulate_voltage'],
        constraints=[{'parameter':'当前档位','operator':'>','value':10,'unit':'档','condition':'限制操作工况'}])
    response=app.analyze(AnalysisRequest('请将主变1的调压装置设定为8档，限于当前档位大于10档的工况',parameters=parameters))
    assert not (response.data.get('candidate_instruction') or {}).get('payload')


def test_previous_target_reference_is_not_a_conditional_action(monkeypatch):
    app, parameters, _, _=app_for(monkeypatch,intent='instruction',actions=['start'],
        entities=[{'name':'SIM-IEC-FAN-01','type':'设备'}])
    response=app.analyze(AnalysisRequest('请让刚才查询的设备开始转动',parameters=parameters,
        conversation_context=[{'role':'user','content':'查询主变1冷却风机'}]))
    assert response.status=='generated'


@pytest.mark.parametrize('parameter', ['档位','目标档位','调压档位','tap_position'])
def test_tap_target_assignment_remains_supported(monkeypatch,parameter):
    app, parameters, _, _=app_for(monkeypatch,intent='instruction',actions=['regulate_voltage'],
        constraints=[{'parameter':parameter,'operator':'=','value':9,'unit':'档','condition':''}])
    response=app.analyze(AnalysisRequest('请将主变1的调压装置设定为9档',parameters=parameters))
    assert response.status=='generated'


def test_advisory_intent_does_not_bypass_model_condition_checks():
    from test_grounded_advice import setup, Client
    from standard_knowledge_service_v2.application.grounded_advice import GroundedAdviceService
    app, data, proposal, request=setup()
    request.query='依据标准，电流超过1000A的工况下，模拟断路器1应如何处理'
    data['intent_classification']={'intent':'search'}
    data['decomposition']={'constraints':[{'parameter':'current','operator':'>','value':1000}],
                           'scenario':{'operating_condition':'电流大于1000A'}}
    GroundedAdviceService(Client(proposal)).enrich(app,request,data)
    assert not (data.get('candidate_instruction') or {}).get('payload')


def test_api_assessment_alias_is_normalized_without_offline_fallback(monkeypatch):
    app, parameters, _, calls=app_for(monkeypatch,intent='assessment',query_kind='assessment')
    response=app.analyze(AnalysisRequest('主变1温升是否正常？',parameters=parameters))
    assert len(calls)==1 and response.status!='partial'
    assert response.data['decomposition']['source']=='model_api'
    assert response.data['device_assessment']['device_id']=='SIM-TRANSFORMER-01'


def test_business_target_cannot_override_a_different_sentence_target(monkeypatch):
    app, parameters, _, _ = app_for(monkeypatch, intent='instruction', actions=['start'], query_kind='operation')
    response = app.analyze(AnalysisRequest('启动主变2的冷却风机', parameters={
        **parameters, 'device_id': 'SIM-IEC-FAN-01'}))
    assert response.status == 'uncertain'
    assert not (response.data.get('candidate_instruction') or {}).get('payload')
    assert '多台设备' in response.data['answer']['text']


def test_business_action_value_cannot_override_sentence_value(monkeypatch):
    app, parameters, _, _ = app_for(monkeypatch, intent='instruction', actions=['regulate_voltage'], query_kind='operation')
    response = app.analyze(AnalysisRequest('请将主变1的调压装置设定为9档', parameters={
        **parameters, 'action_parameters': {'tap_position': 10}}))
    assert response.status == 'uncertain'
    assert not (response.data.get('candidate_instruction') or {}).get('payload')
    assert '目标值与业务参数不一致' in response.data['answer']['text']
