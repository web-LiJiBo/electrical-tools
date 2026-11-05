from pathlib import Path
from standard_knowledge_service_v2.bootstrap import build_application
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.decomposition.models import DecompositionResult
from standard_knowledge_service_v2.application.real_clause_assessment import assess_real_clause
from standard_knowledge_service_v2.application.simulation_access import simulation_runtime


def test_actual_dataset_grounding_no_invented_action(monkeypatch):
    monkeypatch.delenv("ELECTRICAL_TOOLS_OFFLINE_UNUSED_KEY",raising=False)
    root=Path(__file__).resolve().parents[1]
    pipeline=build_application(root/"configs/settings.offline.yaml").facade
    from standard_knowledge_service_v2.application.simulation_access import simulation_runtime
    for number,expected in [(1,"abnormal"),(2,"normal")]:
        sid = simulation_runtime(pipeline).create_session(condition='high_temperature' if number == 1 else 'normal')['session_id']
        result=pipeline.analyze(AnalysisRequest(f"模拟变压器{number}目前温升状态是否正常？",parameters={"simulation_mode":True,"simulation_session_id":sid}))
        data=result.data
        assert data["device_assessment"]["status"]==expected
        assert data["candidate_instruction"] is None
        assert data["real_clause_evidence"]["source_excel"]["excel_file"]=="2017.xlsx"
        assert data["matching"]["rules"]
        assert [c["limit"] for c in data["device_assessment"]["checks"]]==[78,60,65]
        assert data["semantic"] and data["consistency"]
        assert result.evidence
    unsupported=pipeline.analyze(AnalysisRequest("SIM-IEC-BREAKER-01目前状态是否正常？",parameters={"simulation_mode":True}))
    assert unsupported.status=="answered"
    assert unsupported.data['devices'][0]['device_id']=='SIM-IEC-BREAKER-01'
    assert unsupported.data["candidate_instruction"] is None

    unavailable=pipeline.analyze(AnalysisRequest("请按2099版标准判断模拟变压器1温升是否正常？",
        parameters={"simulation_mode":True,"standard_version":"2099"}))
    assert unavailable.status=="uncertain"
    assert not unavailable.evidence
    assert unavailable.data["requested_source"]["version"]=="2099"

    snapshot=simulation_runtime(pipeline).create_session('substation_maintenance')
    understood=DecompositionResult(intent='assessment', valid=True, source='test',
        entities=[{'name':'主变1','type':'设备'}],
        constraints=[{'parameter':'绕组热点温升','operator':'=','value':95,'unit':'K','condition':'用户假设'}],
        scenario={'query_kind':'assessment'})
    status,data,_=assess_real_clause(pipeline,
        AnalysisRequest('假设主变1绕组热点温升为95K，请判断。',parameters={
            'simulation_mode':True,'simulation_session_id':snapshot['session_id']}),
        snapshot=snapshot,device_id='SIM-TRANSFORMER-01',decomposed=understood)
    assert status=='answered'
    assessment=data['device_assessment']
    assert assessment['assessment_basis']=='user_hypothesis'
    assert assessment['status']=='abnormal'
    assert assessment['hypothetical_assessment']['provided_facts']['winding_hotspot_rise_k']==95
    assert assessment['current_snapshot_assessment']['runtime_facts']['winding_hotspot_rise_k']==50
    assert assessment['checks'][0]['actual']==95
