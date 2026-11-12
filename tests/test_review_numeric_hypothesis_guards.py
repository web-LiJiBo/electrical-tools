"""User-facing numeric/hypothesis regressions; model replies are controlled fixtures."""
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from standard_knowledge_service_v2.application.grounded_advice import GroundedAdviceService
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.retrieval_engine import JsonClauseRepository, LocalLunwenRetrievalAdapter
from test_api_first_analysis import app_for as legacy_fixture_app


def app_for(monkeypatch, **settings):
    """Controlled model fixture implementing the current complete-plan contract."""
    app, params, before, calls = legacy_fixture_app(monkeypatch, **settings)
    original = app.decomposer.complete
    def complete(system, user):
        if 'OPERATION_PLAN_REVIEW' in system:
            return original(system, user)
        parsed = json.loads(original(system, user))
        source = user.split('用户问题：', 1)[1].split('\n请严格', 1)[0]
        kind = parsed['scenario']['query_kind']
        entities = settings.get('entities') or []
        device = next((e['name'] for e in entities if e['name'].startswith('SIM-')), 'SIM-TRANSFORMER-01')
        if kind == 'operation' and parsed['actions'] == ['adjust_active_power'] and not entities:
            device = 'SIM-IEC-INVERTER-01'
        constraints = settings.get('constraints') or []
        arguments = {}
        for c in constraints:
            parameter = c['parameter']
            if parameter == 'tap_position':
                device = 'SIM-IEC-TAP-01'
            if c.get('operator') == '=' and not c.get('condition') and parameter in ('power_kw', 'tap_position'):
                scale = {'kW':'1','MW':'1000','mW':'0.000001','档':'1'}[c['unit']]
                number = Decimal(str(c['value'])) * Decimal(scale)
                arguments[parameter] = int(number) if parameter == 'tap_position' else float(number)
        parsed.update(operations=[], queries=[])
        if kind == 'operation':
            action = parsed['actions'][0]
            if device == 'SIM-IEC-TAP-01':
                action = 'set_tap'
            parsed['operations'] = [{'device_id':device,'target_text':source,'owner_id':'','action':action,
                'parameters':arguments,'source_text':source,'negated':False,'conditions':[],'order':None,'clarification':''}]
        else:
            parsed['queries'] = [{'device_id':device,'target_text':source,'owner_id':'','query_kind':kind,
                                  'source_text':source,'clarification':''}]
        return json.dumps(parsed, ensure_ascii=False)
    monkeypatch.setattr(app.decomposer, 'complete', complete)
    return app, params, before, calls


@pytest.mark.parametrize('value,unit,want', [(4.095,'kW','4095'),(0.12,'mW','0.00012')])
def test_normalized_measurement_retains_its_exact_magnitude(value, unit, want):
    from standard_knowledge_service_v2.decomposition.models import DecompositionResult
    from standard_knowledge_service_v2.decomposition.normalizer import DomainTermNormalizer
    parsed = DomainTermNormalizer().normalize(DecompositionResult(
        constraints=[{'parameter':'power_kw','operator':'=','value':value,'unit':unit}]))
    measurement = parsed.constraints[0]
    assert measurement['unit'] == 'W'
    assert Decimal(str(measurement['value'])) == Decimal(want)


def test_rating_is_not_an_action_argument():
    from standard_knowledge_service_v2.application.action_parameters import resolve_action_parameters
    result, error = resolve_action_parameters('请将110kV主变1的调压装置设定为9档',
        {'parameter':'tap_position','unit':'档','parameter_type':'integer'}, {})
    assert not error
    assert result == {'tap_position':9}


def test_direct_hypothesis_assessment_does_not_substitute_snapshot(monkeypatch):
    from standard_knowledge_service_v2.application.real_clause_assessment import assess_real_clause
    from standard_knowledge_service_v2.decomposition.models import DecompositionResult
    constraints = [{'parameter':'绕组热点温升','operator':'>','value':95,'unit':'K'}]
    app, params, snapshot = hypothesis_app(monkeypatch, constraints)
    parsed = DecompositionResult(constraints=constraints,entities=[{'name':'SIM-TRANSFORMER-01'}])
    _, data, _ = assess_real_clause(app, AnalysisRequest('假设主变1热点温升>95K，请判断。',parameters=params),
        snapshot=snapshot,device_id='SIM-TRANSFORMER-01',decomposed=parsed)
    assert data['device_assessment']['assessment_basis'] == 'user_hypothesis'
    assert data['device_assessment']['status'] == 'abnormal'


def test_direct_advice_rejects_a_changed_canonical_target():
    from test_grounded_advice import setup, Client
    from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime
    app, data, proposal, request = setup(action='adjust_active_power')
    app.simulation_runtime = SimulationRuntime(event_path=None)
    snapshot = app.simulation_runtime.create_session('all_devices')
    request.query = '依据标准，将SIM-IEC-INVERTER-01的有功功率设为120kW'
    request.parameters.update(simulation_session_id=snapshot['session_id'],action_parameters={'power_kw':120})
    data['decomposition'] = {'constraints':[{'parameter':'power_kw','operator':'=','value':120,'unit':'kW'}]}
    proposal['instruction'] = {'text':'将模拟逆变器的有功功率调整为130kW','device_id':'SIM-IEC-INVERTER-01',
        'action':'adjust_active_power','parameters':{'power_kw':130},'rule_ids':['r1']}
    GroundedAdviceService(Client(proposal)).enrich(app,request,data)
    assert not (data.get('candidate_instruction') or {}).get('payload')
    assert data['advice']['conversion']['status'] == 'blocked'


@pytest.mark.parametrize('value,unit,expected', [(4.095, 'kW', 4.095), (0.12, 'mW', 0.00000012), (0.12, 'MW', 120)])
def test_exact_model_unit_conversion_reaches_the_requested_value(monkeypatch, value, unit, expected):
    app, params, before, _ = app_for(monkeypatch, intent='instruction', actions=['adjust_active_power'],
        constraints=[{'parameter':'power_kw','operator':'=','value':value,'unit':unit,'condition':''}])
    params['simulation_scenario_id'] = 'renewable_grid_integration'
    result = app.analyze(AnalysisRequest(f'将SIM-IEC-INVERTER-01的有功功率设为{value}{unit}', parameters=params))
    assert result.status == 'generated', result.data.get('answer')
    assert result.data['candidate_instruction']['payload']['engineering_value'] == expected
    json.dumps(result.to_dict(), ensure_ascii=False)
    assert app.simulation_runtime.snapshot(before['session_id']) == before


@pytest.mark.parametrize('query', ['请将110kV主变1的调压装置设定为9档', '请将额定电压110kV的主变1调压装置设定为9档'])
def test_only_tap_assignment_is_used_as_the_tap_target(monkeypatch, query):
    app, params, before, _ = app_for(monkeypatch, intent='instruction', actions=['regulate_voltage'],
        constraints=[{'parameter':'tap_position','operator':'=','value':9,'unit':'档','condition':''}])
    result = app.analyze(AnalysisRequest(query, parameters=params))
    assert result.status == 'generated', result.data.get('answer')
    assert result.data['candidate_instruction']['payload']['engineering_value'] == 9
    assert app.simulation_runtime.snapshot(before['session_id']) == before


def hypothesis_app(monkeypatch, constraints):
    app, params, before, _ = app_for(monkeypatch, intent='compliance', query_kind='assessment',
        entities=[{'name':'SIM-TRANSFORMER-01','type':'设备'}], constraints=constraints)
    path = Path(__file__).resolve().parents[1] / 'datasets/lunwen/verified_json/json/11_clause2.json'
    unit = JsonClauseRepository._from_payload(path, json.loads(path.read_text(encoding='utf-8')))
    app.retriever = LocalLunwenRetrievalAdapter(JsonClauseRepository([unit]))
    return app, params, before


@pytest.mark.parametrize('operator,value,expected', [('>',95,'abnormal'),('>=',95,'abnormal'),('>',78,'abnormal'),('>=',78,'uncertain'),('<',95,'uncertain')])
def test_inequality_hypothesis_is_never_replaced_with_snapshot(monkeypatch, operator, value, expected):
    app, params, before = hypothesis_app(monkeypatch, [
        {'parameter':'绕组热点温升','operator':operator,'value':value,'unit':'K','condition':'用户假设'}])
    result = app.analyze(AnalysisRequest(f'假设主变1绕组热点温升{operator}{value}K，请判断是否正常。', parameters=params))
    assessment = result.data['device_assessment']
    assert assessment['assessment_basis'] == 'user_hypothesis'
    assert assessment['status'] == expected
    assert assessment['current_snapshot_assessment']['checks'][0]['actual'] == 50
    assert assessment['checks'][0]['actual'] != 50
    assert app.simulation_runtime.snapshot(before['session_id']) == before


def test_complete_bounded_hypothesis_can_prove_all_limits(monkeypatch):
    constraints = [{'parameter':name,'operator':'<=','value':value,'unit':'K'} for name,value in
        [('绕组热点温升',78),('顶层油温升',60),('绕组平均温升',65)]]
    app, params, _ = hypothesis_app(monkeypatch, constraints)
    result = app.analyze(AnalysisRequest('假设主变1热点温升<=78K、顶层油温升<=60K、绕组平均温升<=65K，请判断。', parameters=params))
    a = result.data['device_assessment']
    assert a['assessment_basis'] == 'user_hypothesis'
    assert a['status'] == 'normal'
    assert a['hypothetical_assessment']['complete'] is True


def test_conflicting_hypothesis_is_uncertain(monkeypatch):
    app, params, _ = hypothesis_app(monkeypatch, [
        {'parameter':'绕组热点温升','operator':'>','value':95,'unit':'K'},
        {'parameter':'绕组热点温升','operator':'<','value':70,'unit':'K'}])
    a = app.analyze(AnalysisRequest('假设主变1热点温升>95K且<70K，请判断。', parameters=params)).data['device_assessment']
    assert a['assessment_basis'] == 'user_hypothesis'
    assert a['status'] == 'uncertain'


def test_unparsed_explicit_hypothesis_does_not_claim_current_values_answer_it(monkeypatch):
    app, params, _ = hypothesis_app(monkeypatch, [])
    a = app.analyze(AnalysisRequest('假设主变1温升过高，请判断。', parameters=params)).data['device_assessment']
    assert a['assessment_basis'] == 'user_hypothesis'
    assert a['status'] == 'uncertain'


@pytest.mark.parametrize('proposal_value,text_value,business_value,allowed', [
    (130,130,120,False), (120,130,120,False), (120,120,130,False), (120,120,120,True)])
def test_full_advice_path_reconciles_user_business_and_instruction_values(monkeypatch, proposal_value, text_value, business_value, allowed):
    from test_grounded_advice import setup
    base, _, proposal, _ = setup(action='adjust_active_power', condition='')
    unit = base.retriever.repository.unit_for_rule('r1')
    unit.rules[0].subject = '逆变器'
    unit.rules[0].content = '合成测试来源：逆变器有功功率可调节。'
    app, params, before, _ = app_for(monkeypatch, intent='instruction', query_kind='standard_query',
        actions=['adjust_active_power'], entities=[{'name':'SIM-IEC-INVERTER-01','type':'设备'}],
        constraints=[{'parameter':'power_kw','operator':'=','value':120,'unit':'kW','condition':''}])
    app.retriever = SimpleNamespace(repository=base.retriever.repository, last_trace=None,
        match=lambda *_: SimpleNamespace(rules=[SimpleNamespace(rule=unit.rules[0],rank=1,combined_score=1)],matched_entities=[],warnings=[]))
    proposal['instruction'] = {'text':f'将模拟逆变器的有功功率调整为{text_value}kW',
        'device_id':'SIM-IEC-INVERTER-01','action':'adjust_active_power','parameters':{'power_kw':proposal_value},'rule_ids':['r1']}
    from test_grounded_advice import Client
    app.advisor = GroundedAdviceService(Client(proposal))
    params.update(simulation_scenario_id='renewable_grid_integration', action_parameters={'power_kw':business_value})
    result = app.analyze(AnalysisRequest('依据标准，将SIM-IEC-INVERTER-01的有功功率设为120kW', parameters=params))
    payload = (result.data.get('candidate_instruction') or {}).get('payload')
    if allowed:
        assert result.status == 'generated', result.data.get('advice')
        assert payload['engineering_value'] == 120
    else:
        assert not payload
        assert result.data['advice']['conversion']['status'] == 'blocked'
    assert app.simulation_runtime.snapshot(before['session_id']) == before
