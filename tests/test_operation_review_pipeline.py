"""Full entrypoint: review is batch-wide and precedes all command creation."""
import json
from copy import deepcopy
import pytest
from standard_knowledge_service_v2.contracts import AnalysisRequest
from test_semantic_operation_plan import planned_app, operation


def approved_review(operations):
    return {'approved':True,'items':[{'index':i,'matches_request':True,'reason':'原文一致',
        'device_id':op['device_id'],'action':op['action'],'parameters':deepcopy(op['parameters'])}
        for i,op in enumerate(operations)],'missing_requests':[],
        'has_negation':False,'has_conditions':False,'has_order':False,'reason':'整批一致'}


def reviewed_app(monkeypatch, query, ops, *, review=None, failure=None):
    app,params,before,calls=planned_app(monkeypatch,query,ops)
    original=app.decomposer.complete
    review_calls=[]
    def complete(system,user):
        if 'OPERATION_PLAN_REVIEW' not in system:
            return original(system,user)
        review_calls.append((system,user))
        if failure: raise RuntimeError(failure)
        return json.dumps(review if review is not None else approved_review(ops),ensure_ascii=False)
    monkeypatch.setattr(app.decomposer,'complete',complete)
    return app,params,before,calls,review_calls


def test_reverse_action_is_rejected_before_any_preview(monkeypatch):
    query='启动主变1的冷却风机'; ops=[operation(query,action='stop')]
    review=approved_review(ops);review.update(approved=False,reason='原话启动却写成停止')
    review['items'][0].update(matches_request=False,reason='动作相反')
    app,params,before,calls,checks=reviewed_app(monkeypatch,query,ops,review=review)
    def forbidden(*args,**kwargs): pytest.fail('rejected review must never create a command')
    monkeypatch.setattr(app.simulation_runtime,'preview',forbidden)
    result=app.analyze(AnalysisRequest(query,parameters=params))
    assert result.status=='uncertain'
    assert result.data['operation_review']['status']=='blocked'
    assert not result.data.get('simulation_preview')
    assert len(calls)==len(checks)==1
    assert app.simulation_runtime.snapshot(before['session_id'])==before


def test_many_operations_have_only_one_batch_review(monkeypatch):
    query='启动冷却风机1，同时启动冷却风机2'
    ops=[operation('启动冷却风机1'),operation('启动冷却风机2',device='SIM-MB-FAN-01')]
    app,params,before,calls,checks=reviewed_app(monkeypatch,query,ops)
    result=app.analyze(AnalysisRequest(query,parameters=params))
    assert result.data['simulation_batch']['generated_count']==2
    assert result.data['operation_review']['status']=='approved'
    assert len(calls)==len(checks)==1
    packet=json.loads(checks[0][1]); assert packet['query']==query
    assert len(packet['operations'])==2
    assert app.simulation_runtime.snapshot(before['session_id'])==before


def test_review_failure_blocks_without_leaking_exception(monkeypatch):
    query='启动主变1的冷却风机'
    app,params,_,calls,checks=reviewed_app(monkeypatch,query,[operation(query)],failure='SECRET_KEY_DO_NOT_ECHO')
    result=app.analyze(AnalysisRequest(query,parameters=params))
    assert result.data['operation_review']['status']=='failed'
    assert result.data['processing']['instruction_status']=='unavailable'
    assert not result.data.get('simulation_preview')
    assert 'SECRET_KEY_DO_NOT_ECHO' not in json.dumps(result.to_dict())
    assert len(calls)==len(checks)==1


def test_review_does_not_mutate_or_replace_first_plan(monkeypatch):
    query='启动主变1的冷却风机'; ops=[operation(query)]
    review=approved_review(ops);review['items'][0]['action']='stop'
    app,params,_,_,_=reviewed_app(monkeypatch,query,ops,review=review)
    result=app.analyze(AnalysisRequest(query,parameters=params))
    assert not result.data.get('simulation_preview')
    assert result.data['decomposition']['operations'][0]['action']=='start'


def mixed_standard_app(monkeypatch, *, approved=True, error=False, no_sources=False):
    from types import SimpleNamespace
    from test_grounded_advice import setup, Client
    from standard_knowledge_service_v2.application.grounded_advice import GroundedAdviceService
    query='启动主变1的冷却风机，同时说明DL/T 664的温度要求'
    ops=[operation('启动主变1的冷却风机')]
    questions=[dict(device_id='',owner_id='',target_text='DL/T 664',source_text='说明DL/T 664的温度要求',query_kind='standard_query',clarification='')]
    app,params,before,calls=planned_app(monkeypatch,query,ops,questions)
    knowledge,_,proposal,_=setup()
    class Retriever:
        repository=knowledge.retriever.repository
        def match(self,*_):
            rule=self.repository.unit_for_rule('r1').rules[0]
            return SimpleNamespace(rules=[SimpleNamespace(rule=rule,rank=1,combined_score=1)],warnings=[],matched_entities=[])
    if not no_sources: app.retriever=Retriever()
    proposal['instruction']=None
    advice_calls=[]
    def complete(system,user):
        advice_calls.append((system,user))
        if error: raise RuntimeError('SECRET_COMBINED_ERROR')
        packet=json.loads(user)
        review=approved_review(packet['operation_review_request']['operations'])
        review['approved']=approved
        if not approved: review['items'][0]['matches_request']=False;review['reason']='动作不一致'
        return json.dumps({'operation_review':review,'advice':proposal},ensure_ascii=False)
    app.advisor=GroundedAdviceService(type('CombinedClient',(),{'complete':staticmethod(complete)})())
    return app,params,before,calls,advice_calls,query


def test_standard_analysis_and_review_share_second_call(monkeypatch):
    app,params,before,calls,advice,query=mixed_standard_app(monkeypatch)
    result=app.analyze(AnalysisRequest(query,parameters=params))
    assert result.data['simulation_preview']['status']=='generated'
    assert result.data['operation_review']['status']=='approved'
    assert len(calls)+len(advice)+len(app._test_review_calls)==2
    assert len(advice)==1
    assert app.simulation_runtime.snapshot(before['session_id'])==before


@pytest.mark.parametrize('error',[False,True])
def test_failed_combined_review_has_no_third_call_and_no_preview(monkeypatch,error):
    app,params,before,calls,advice,query=mixed_standard_app(monkeypatch,approved=False,error=error)
    monkeypatch.setattr(app.simulation_runtime,'preview',lambda *a,**kw:pytest.fail('must not preview before approval'))
    result=app.analyze(AnalysisRequest(query,parameters=params))
    assert not result.data.get('simulation_preview')
    assert len(calls)+len(advice)+len(app._test_review_calls)==2
    assert 'SECRET_COMBINED_ERROR' not in json.dumps(result.to_dict())


def test_no_clause_sources_uses_review_only_without_third_call(monkeypatch):
    app,params,before,calls,advice,query=mixed_standard_app(monkeypatch,no_sources=True)
    result=app.analyze(AnalysisRequest(query,parameters=params))
    assert result.data['operation_review']['status']=='approved'
    assert result.status=='partial'
    assert len(calls)+len(advice)+len(app._test_review_calls)==2
    assert advice==[]


def test_again_is_a_single_operation_in_the_reviewed_full_pipeline(monkeypatch):
    query='请再次启动主变1的冷却风机'
    app,params,before,calls,checks=reviewed_app(monkeypatch,query,[operation(query)])
    result=app.analyze(AnalysisRequest(query,parameters=params))
    assert result.status=='generated'
    assert result.data['simulation_preview']['candidate']['payload']['requested_action']=='start'
    assert len(calls)==len(checks)==1


def test_reviewer_catches_order_missing_from_first_plan(monkeypatch):
    query='先启动冷却风机1，然后停止油泵2'
    ops=[operation('先启动冷却风机1'),operation('然后停止油泵2',device='SIM-MB-PUMP-01',action='stop')]
    review=approved_review(ops);review.update(approved=False,has_order=True,reason='原文有先后依赖')
    app,params,_,calls,checks=reviewed_app(monkeypatch,query,ops,review=review)
    result=app.analyze(AnalysisRequest(query,parameters=params))
    assert not result.data.get('simulation_batch')
    assert result.data['operation_review']['status']=='blocked'
    assert len(calls)==len(checks)==1


def test_simultaneous_requests_do_not_share_review_decisions(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from standard_knowledge_service_v2.application import AnalysisPipeline
    from standard_knowledge_service_v2.decomposition import RemoteModelConfig,RemoteModelDecomposer
    from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime
    from standard_knowledge_service_v2.retrieval_engine import JsonClauseRepository,LocalLunwenRetrievalAdapter
    barrier=Barrier(2)
    model=RemoteModelDecomposer(RemoteModelConfig('https://example.test','test'))
    def complete(system,user):
        if 'OPERATION_PLAN_REVIEW' in system:
            packet=json.loads(user);barrier.wait(timeout=10)
            result=approved_review(packet['operations'])
            if '风机2' in packet['query']:
                result.update(approved=False,reason='第二项拒绝');result['items'][0]['matches_request']=False
            return json.dumps(result)
        query=user.split('用户问题：',1)[1].split('\n请严格')[0]
        device='SIM-MB-FAN-01' if '风机2' in query else 'SIM-IEC-FAN-01'
        return json.dumps({'intent':'instruction','entities':[{'name':device,'type':'设备'}],
            'actions':['start'],'constraints':[],'standard_refs':[],'keywords':['风机'],
            'scenario':{'query_kind':'operation','operating_condition':''},'confidence':.9,
            'operations':[operation(query,device=device)],'queries':[]})
    monkeypatch.setattr(model,'complete',complete)
    app=AnalysisPipeline(LocalLunwenRetrievalAdapter(JsonClauseRepository([])),decomposer=model)
    app.simulation_runtime=SimulationRuntime(event_path=None)
    before=app.simulation_runtime.create_session('all_devices')
    params={'simulation_mode':True,'simulation_session_id':before['session_id'],'simulation_scenario_id':'all_devices'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(app.analyze,AnalysisRequest(q,parameters=params)) for q in ['启动冷却风机1','启动冷却风机2']]
        first,second=[f.result(timeout=15) for f in futures]
    assert first.data['operation_review']['status']=='approved'
    assert first.data['candidate_instruction']['target']=='SIM-IEC-FAN-01'
    assert second.data['operation_review']['status']=='blocked'
    assert not second.data.get('simulation_preview')
    assert app.simulation_runtime.snapshot(before['session_id'])==before


@pytest.mark.parametrize('error',[False,True])
def test_whole_sentence_knowledge_evidence_cannot_generate_before_review(monkeypatch,error):
    app,params,_,calls,advice,query=mixed_standard_app(monkeypatch,approved=False,error=error)
    original=app.decomposer.complete
    def complete(system,user):
        raw=original(system,user)
        if 'OPERATION_PLAN_REVIEW' not in system:
            value=json.loads(raw);value['queries'][0]['source_text']=query
            return json.dumps(value)
        return raw
    monkeypatch.setattr(app.decomposer,'complete',complete)
    def forbidden(*args,**kwargs): pytest.fail('No candidate or command before review')
    monkeypatch.setattr(app.generator,'generate',forbidden)
    monkeypatch.setattr(app.simulation_runtime,'preview',forbidden)
    result=app.analyze(AnalysisRequest(query,parameters=params))
    assert not result.data.get('simulation_preview')
    assert len(calls)==len(advice)==1
    assert app._test_review_calls==[]
