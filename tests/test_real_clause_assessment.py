from pathlib import Path
from standard_knowledge_service_v2.bootstrap import build_application
from standard_knowledge_service_v2.contracts import AnalysisRequest


def test_actual_dataset_grounding_no_invented_action(monkeypatch):
    monkeypatch.delenv("ELECTRICAL_TOOLS_OFFLINE_UNUSED_KEY",raising=False)
    root=Path(__file__).resolve().parents[1]
    pipeline=build_application(root/"configs/settings.offline.yaml").facade
    for number,expected in [(1,"abnormal"),(2,"normal")]:
        result=pipeline.analyze(AnalysisRequest(f"模拟变压器{number}目前温升状态是否正常？",parameters={"simulation_mode":True}))
        data=result.data
        assert data["device_assessment"]["status"]==expected
        assert data["candidate_instruction"] is None
        assert data["real_clause_evidence"]["source_excel"]["excel_file"]=="2017.xlsx"
        assert data["matching"]["rules"]
        assert [c["limit"] for c in data["device_assessment"]["checks"]]==[78,60,65]
        assert data["semantic"] and data["consistency"]
        assert result.evidence
    unsupported=pipeline.analyze(AnalysisRequest("SIM-IEC-BREAKER-01目前状态是否正常？",parameters={"simulation_mode":True}))
    assert unsupported.status=="uncertain"
    assert unsupported.data["candidate_instruction"] is None
