import json

from standard_knowledge_service_v2.application import AnalysisPipeline
from standard_knowledge_service_v2.audit import JsonlAuditStore
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.instruction_engine.models import CandidateInstruction, ILRProgram, SemanticTuple
from standard_knowledge_service_v2.retrieval_engine import LocalLunwenRetrievalAdapter
from standard_knowledge_service_v2.validation import SafetyGate
from standard_knowledge_service_v2.validation.clause_instruction_validator import ClauseInstructionValidator
from standard_knowledge_service_v2.validation.validation_models import ValidationStatus


def _dataset(tmp_path) -> None:
    payload = {
        "entities": [{"name": "集电线路", "type": "设备"}],
        "rules": [{"content": "集电线路发生过流时应跳闸", "subject": "集电线路", "action": "trip", "condition": "电流 >= 100", "constraint": "电流不小于100A"}],
        "relations": [],
    }
    (tmp_path / "case.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_validation_gate_never_allows_dispatch() -> None:
    result = SafetyGate().decide({"semantic": ValidationStatus.PASS, "protocol": ValidationStatus.PASS})
    assert result.status is ValidationStatus.NEEDS_HUMAN
    assert result.dispatch_allowed is False


def test_clause_instruction_mismatch_fails() -> None:
    semantic = SemanticTuple("线路", "trip", "线路")
    candidate = CandidateInstruction(protocol="IEC61850", payload={"requested_action": "close"})
    status, _ = ClauseInstructionValidator().validate(semantic, candidate)
    assert status is ValidationStatus.FAIL


def test_end_to_end_pipeline_keeps_evidence_and_audit(tmp_path) -> None:
    _dataset(tmp_path)
    retriever = LocalLunwenRetrievalAdapter.from_dataset(tmp_path)
    store = JsonlAuditStore(tmp_path / "audit.jsonl")
    pipeline = AnalysisPipeline(retriever, store)
    request = AnalysisRequest(
        "请生成海上风电集电线路过流跳闸候选指令",
        "海上风电",
        parameters={"device_id": "CB-01", "operating_state": "运行", "device_type": "集电线路", "device_config": {"device_id": "CB-01", "logical_node": "PTRC1", "data_object": "Tr.general", "protocol": "IEC61850"}},
        target_protocol="IEC61850",
    )
    response = pipeline.analyze(request)
    assert response.status == "needs_human"
    assert response.evidence and response.data["candidate_instruction"]["dispatch_allowed"] is False
    assert response.evidence[0]["quote"] == "集电线路发生过流时应跳闸"
    assert response.data["selected_rule"]["content"] == response.evidence[0]["quote"]
    assert response.data["candidate_assessments"]
    assert "consistency" in response.data["candidate_assessments"][0]
    assert "reasoning" in response.data["candidate_assessments"][0]
    assert response.evidence[0]["quote"] in response.data["report"]["markdown"]
    assert store.get(request.meta.request_id) is not None


def test_unknown_protocol_and_missing_config_are_safe() -> None:
    semantic = SemanticTuple("线路", "trip", "线路")
    candidate = CandidateInstruction(protocol="Other", missing_fields=["supported_protocol"])
    assert candidate.dispatch_allowed is False


def test_explicit_action_rejects_rule_with_different_action(tmp_path) -> None:
    payload = {
        "entities": [{"name": "线路", "type": "设备"}],
        "rules": [{
            "content": "线路发生接地故障时应采用消弧线圈接地方式",
            "subject": "线路",
            "action": "采用接地方式",
            "condition": "接地故障",
        }],
    }
    (tmp_path / "rules.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    pipeline = AnalysisPipeline(LocalLunwenRetrievalAdapter.from_dataset(tmp_path))

    response = pipeline.analyze(AnalysisRequest("请生成线路过流跳闸候选指令"))

    assert response.status == "uncertain"
    assert "selected_rule" not in response.data
    assessment = response.data["candidate_assessments"][0]
    assert assessment["action_matches"] is False
    assert "requested_action_mismatch" in assessment["rejection_reasons"]
