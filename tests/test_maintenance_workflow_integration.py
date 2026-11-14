"""Whole pipeline regressions for explicit analysis-only requests and workflow gates."""
import json
from copy import deepcopy
import pytest
from standard_knowledge_service_v2.application import AnalysisPipeline
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.decomposition import RemoteModelConfig,RemoteModelDecomposer
from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime
from standard_knowledge_service_v2.retrieval_engine import JsonClauseRepository,LocalLunwenRetrievalAdapter
from semantic_fixture_helpers import approve_review_packet


def pipeline(monkeypatch,query,payload,condition='normal'):
 model=RemoteModelDecomposer(RemoteModelConfig('https://example.test','controlled'))
 calls=[]
 def complete(system,user):
  calls.append((system,user))
  if 'OPERATION_PLAN_REVIEW' in system:return json.dumps(approve_review_packet(json.loads(user)))
  return json.dumps(payload,ensure_ascii=False)
 monkeypatch.setattr(model,'complete',complete)
 app=AnalysisPipeline(LocalLunwenRetrievalAdapter(JsonClauseRepository([])),decomposer=model)
 app.simulation_runtime=SimulationRuntime(event_path=None)
 before=app.simulation_runtime.create_session('substation_maintenance',condition=condition)
 params={'simulation_mode':True,'simulation_session_id':before['session_id'],'simulation_scenario_id':'substation_maintenance'}
 return app,params,before,calls


def request_payload(query, *, propose=False):
 return {'intent':'instruction' if propose else 'search',
  'entities':[{'name':'主变1的冷却风机','type':'设备'}],
  'actions':['start'] if propose else [],'constraints':[],'standard_refs':[],'keywords':['风机'],
  'scenario':{'query_kind':'device_status','operating_condition':''},'confidence':.95,
  'queries':[{'device_id':'SIM-IEC-FAN-01','owner_id':'SIM-TRANSFORMER-01','target_text':'主变1的冷却风机','source_text':'查询主变1的冷却风机状态','query_kind':'device_status','clarification':''}],
  'operations':[{'device_id':'SIM-IEC-FAN-01','owner_id':'SIM-TRANSFORMER-01','target_text':'主变1的冷却风机','source_text':query,'action':'start','parameters':{},'negated':False,'conditions':[],'order':None,'clarification':''}] if propose else [],
  'request_controls':{'analysis_only':True,'source_text':'不要生成控制指令'}}


def test_analysis_only_restriction_counts_as_covered_without_suppressing_query(monkeypatch):
 query='查询主变1的冷却风机状态，不要生成控制指令'
 app,params,before,calls=pipeline(monkeypatch,query,request_payload(query))
 result=app.analyze(AnalysisRequest(query,parameters=params))
 assert result.status=='answered', result.data.get('answer')
 assert not result.data.get('clarification_required')
 assert result.data['devices'][0]['device_id']=='SIM-IEC-FAN-01'
 assert not result.data.get('simulation_preview')
 assert len(calls)==1
 assert app.simulation_runtime.snapshot(before['session_id'])==before


def test_analysis_only_does_not_review_or_preview_a_model_invented_operation(monkeypatch):
 query='查询主变1的冷却风机状态，不要生成控制指令'
 app,params,before,calls=pipeline(monkeypatch,query,request_payload(query,propose=True))
 def forbidden(*args,**kwargs):pytest.fail('analysis-only must not create candidates or commands')
 monkeypatch.setattr(app.simulation_runtime,'preview',forbidden)
 monkeypatch.setattr(app.generator,'generate',forbidden)
 result=app.analyze(AnalysisRequest(query,parameters=params))
 assert not result.data.get('simulation_preview')
 assert not result.data.get('simulation_batch')
 assert not (result.data.get('candidate_instruction') or {}).get('payload')
 assert len(calls)==1
 assert app.simulation_runtime.snapshot(before['session_id'])==before


def test_global_analysis_only_evidence_survives_knowledge_subrequest(monkeypatch):
 from test_grounded_advice import setup,Client
 from standard_knowledge_service_v2.application.grounded_advice import GroundedAdviceService
 query='查询主变1的冷却风机状态，同时说明断路器条款依据，不要生成控制指令'
 payload=request_payload(query)
 payload['queries'].append({'device_id':'','owner_id':'','target_text':'断路器条款依据',
  'source_text':'说明断路器条款依据','query_kind':'standard_query','clarification':''})
 app,params,before,calls=pipeline(monkeypatch,query,payload)
 knowledge,_,proposal,_=setup()
 from types import SimpleNamespace
 class Retriever:
  repository=knowledge.retriever.repository
  last_trace=None
  def match(self,*args):
   rule=self.repository.unit_for_rule('r1').rules[0]
   return SimpleNamespace(rules=[SimpleNamespace(rule=rule,rank=1,combined_score=1)],matched_entities=[],warnings=[])
 app.retriever=Retriever()
 proposal.update(instruction=None,answer_supported=False,rule_ids=[],
  support_assessments=[],unable_reason='测试来源尚待核验')
 advice_calls=[]
 client=Client(proposal)
 def complete(*args):
  advice_calls.append(args)
  return client.complete(*args)
 app.advisor=GroundedAdviceService(type('AdviceClient',(),{'complete':staticmethod(complete)})())
 result=app.analyze(AnalysisRequest(query,parameters=params))
 child=next(x for x in result.data['query_results'] if x['query_kind']=='knowledge')
 assert child['data'].get('advice') is not None,child
 assert len(advice_calls)==1 and len(calls)==1
 assert not result.data.get('simulation_preview')
 assert not (result.data.get('candidate_instruction') or {}).get('payload')
 assert app.simulation_runtime.snapshot(before['session_id'])==before


def test_readiness_diagnosis_is_read_only_and_uses_current_fault(monkeypatch):
 query='请检查主变1的冷却风机是否具备启动条件，只做检查'
 payload=request_payload(query)
 payload['queries'][0].update(source_text='请检查主变1的冷却风机是否具备启动条件',query_kind='device_readiness',requested_action='start')
 payload['scenario']['query_kind']='device_readiness'
 payload['request_controls']['source_text']='只做检查'
 app,params,before,calls=pipeline(monkeypatch,query,payload,condition='cooling_fault')
 def forbidden(*a,**kw):pytest.fail('readiness must never generate previews')
 monkeypatch.setattr(app.simulation_runtime,'preview',forbidden)
 result=app.analyze(AnalysisRequest(query,parameters=params))
 assert result.status=='answered',result.data.get('answer')
 item=result.data['query_results'][0]['readiness']
 assert item['status']=='blocked'
 assert any(c.get('field')=='device_fault' and c.get('actual')==1 for c in item['checks'])
 assert len(calls)==1
 assert app.simulation_runtime.snapshot(before['session_id'])==before


def test_source_rejection_clears_final_conclusion_and_report():
 from types import SimpleNamespace
 from test_grounded_advice import setup,Client
 from standard_knowledge_service_v2.application.grounded_advice import GroundedAdviceService
 from standard_knowledge_service_v2.decomposition import RawTextFallback
 base,_,_,_=setup();unit=base.retriever.repository.unit_for_rule('r1')
 class Retriever:
  repository=base.retriever.repository
  last_trace=None
  def match(self,*a):return SimpleNamespace(rules=[SimpleNamespace(rule=unit.rules[0],rank=1,combined_score=1)],matched_entities=[],warnings=[])
 unsupported={'summary':'候选断路器条文不支持此试验问题','answer_supported':False,
  'support_assessments':[{'rule_id':'r1','supports_answer':False,'reason':'对象和任务不适用'}],
  'unable_reason':'没有适用依据','rule_ids':[],'suggestions':[],'instruction':None}
 app=AnalysisPipeline(Retriever(),decomposer=RawTextFallback())
 app.advisor=GroundedAdviceService(Client(unsupported))
 result=app.analyze(AnalysisRequest('变压器检修后绝缘试验依据是什么？'))
 d=result.data
 assert result.status=='uncertain'
 assert d['answer'].get('conclusion') in (None,'')
 assert not d['answer'].get('source_rule_id')
 assert not d.get('selected_rule')
 assert not result.evidence
 assert d['processing']['source_result_status']=='uncertain'
 assert d['report']['sections']['clauses']==[]
 assert d['report']['sections']['instruction'] is None
 assert d['validation']['status'] not in ('answered','pass')


def operations_payload(query,ops):
 return {'intent':'instruction','entities':[{'name':'主变1','type':'设备'}],
  'actions':list(dict.fromkeys(x['action'] for x in ops)),'constraints':[],'standard_refs':[],'keywords':['运维'],
  'scenario':{'query_kind':'operation','operating_condition':''},'confidence':.95,'operations':deepcopy(ops),'queries':[],
  'request_controls':{'analysis_only':False,'source_text':''}}


def guarded_operation(query, *, action='start',device='SIM-IEC-FAN-01',conditions=None,order=None):
 return {'device_id':device,'target_text':query,'owner_id':'SIM-TRANSFORMER-01','source_text':query,
  'action':action,'parameters':{},'conditions':conditions or [],'order':order,'negated':False,'clarification':''}


def test_current_fault_blocks_typed_condition_after_two_stage_review(monkeypatch):
 query='只有确认主变1的冷却风机无故障时才允许启动；任何条件不满足都不要生成启动指令'
 ops=[guarded_operation(query,conditions=['device_fault == 0'])]
 app,params,before,calls=pipeline(monkeypatch,query,operations_payload(query,ops),condition='cooling_fault')
 result=app.analyze(AnalysisRequest(query,parameters=params));d=result.data
 assert result.status=='uncertain',d.get('answer')
 assert d['operation_review']['status']=='approved'
 assert len(calls)==2
 first=d['simulation_plan']['steps'][0]['preview']
 assert first['status']=='blocked' and first['command_id'] is None
 assert first['condition_checks'][0]['actual']==1
 assert 'device_fault' in d['answer']['text']
 assert app.simulation_runtime.snapshot(before['session_id'])==before


def test_user_condition_is_not_lost_between_pipeline_preview_and_execute(monkeypatch):
 query='只有确认主变1的冷却风机无故障时才允许启动'
 ops=[guarded_operation(query,conditions=['device_fault == 0'])]
 app,params,before,calls=pipeline(monkeypatch,query,operations_payload(query,ops))
 result=app.analyze(AnalysisRequest(query,parameters=params));d=result.data
 assert result.status=='generated',d.get('answer')
 first=d['simulation_plan']['steps'][0]['preview']
 assert len(calls)==2 and first['status']=='generated'
 runtime=app.simulation_runtime;sid=before['session_id']
 runtime._sessions[sid].devices['SIM-IEC-FAN-01']['runtime_facts']['device_fault']=1
 execution=runtime.execute(sid,first['command_id'],first['expected_version'])
 assert execution['status']!='succeeded'
 state=next(x['state'] for x in runtime.snapshot(sid)['devices'] if x['device_id']=='SIM-IEC-FAN-01')
 assert state['running'] is False


def test_two_step_plan_has_only_first_preview_until_success_feedback(monkeypatch):
 query='将主变1的调压装置先升一档，反馈成功后再升一档；若第一步失败，第二步不要执行'
 ops=[guarded_operation(query,action='raise',device='SIM-IEC-TAP-01',order=i) for i in [1,2]]
 app,params,before,calls=pipeline(monkeypatch,query,operations_payload(query,ops))
 result=app.analyze(AnalysisRequest(query,parameters=params));d=result.data
 assert result.status=='generated',d.get('answer')
 assert d['intent_classification']['intent']=='instruction'
 plan=d['simulation_plan'];sid=before['session_id'];runtime=app.simulation_runtime
 assert len(calls)==2 and plan['steps'][1]['preview'] is None
 assert runtime.preview_plan_step(sid,plan['plan_id'],2,expected_version=0)['status']=='blocked'
 first=plan['steps'][0]['preview']
 assert runtime.execute(sid,first['command_id'],first['expected_version'])['status']=='succeeded'
 snapshot=runtime.snapshot(sid)
 second=runtime.preview_plan_step(sid,plan['plan_id'],2,expected_version=snapshot['version'])
 assert second['status']=='generated'
 assert len(calls)==2
 assert runtime.execute(sid,second['command_id'],second['expected_version'])['status']=='succeeded'
 after=next(x['state']['tap_position'] for x in runtime.snapshot(sid)['devices'] if x['device_id']=='SIM-IEC-TAP-01')
 initial=next(x['state']['tap_position'] for x in before['devices'] if x['device_id']=='SIM-IEC-TAP-01')
 assert after==initial+2
