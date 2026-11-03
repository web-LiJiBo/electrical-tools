import json

from standard_knowledge_service_v2.application import AnalysisPipeline
from standard_knowledge_service_v2.consistency_evaluation import ConsistencyEvaluationService
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.decomposition import RawTextFallback
from standard_knowledge_service_v2.decomposition.intent_classifier import IntentClassifier
from standard_knowledge_service_v2.instruction_engine.simulation import SimulationInstructionService
from standard_knowledge_service_v2.instruction_engine.template_editor import load_custom
from standard_knowledge_service_v2.retrieval_engine import JsonClauseRepository, LocalLunwenRetrievalAdapter


def _write_clause(directory, name, *, version, content, action=""):
    payload = {
        "standard_id": f"DL/T 9000-{version}",
        "standard_name": "模拟电力设备标准",
        "version": version,
        "entities": [{"name": "冷却风机", "type": "设备"}],
        "rules": [{"content": content, "subject": "冷却风机", "action": action, "condition": ""}],
    }
    (directory / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _pipeline(directory):
    repository = JsonClauseRepository.from_directory(directory)
    return AnalysisPipeline(LocalLunwenRetrievalAdapter(repository), decomposer=RawTextFallback())


def test_unrelated_question_is_not_answered_by_best_available_clause(tmp_path):
    _write_clause(tmp_path, "electrical", version="2026", content="冷却风机运行前应检查电源电压。")

    response = _pipeline(tmp_path).analyze(AnalysisRequest("手机如何恢复出厂设置？"))

    assert response.status == "uncertain"
    assert not response.evidence
    assert "selected_rule" not in response.data
    assert "retrieval_score_below_minimum" in response.data["candidate_assessments"][0]["rejection_reasons"]


def test_explicit_version_is_a_hard_filter(tmp_path):
    text_2010 = "2010版要求冷却风机运行前检查电源。"
    text_2026 = "2026版要求冷却风机运行前检查联锁。"
    _write_clause(tmp_path, "old", version="2010", content=text_2010)
    _write_clause(tmp_path, "new", version="2026", content=text_2026)

    response = _pipeline(tmp_path).analyze(AnalysisRequest(
        "2026版冷却风机运行前需要检查什么？",
        parameters={"standard_version": "2026"},
    ))

    assert response.status == "answered"
    assert response.evidence[0]["version"] == "2026"
    assert response.data["selected_rule"]["content"] == text_2026


def test_missing_requested_version_returns_uncertain_instead_of_fallback(tmp_path):
    _write_clause(tmp_path, "old", version="2010", content="冷却风机运行前应检查电源。")

    response = _pipeline(tmp_path).analyze(AnalysisRequest(
        "2026版冷却风机运行前需要检查什么？"
    ))

    assert response.status == "uncertain"
    assert not response.evidence
    assert any("2026" in warning for warning in response.warnings)


def test_negated_control_request_cannot_be_instruction_intent(tmp_path):
    _write_clause(tmp_path, "start", version="2026", content="冷却风机启动前应检查启动许可。", action="start")

    classification = IntentClassifier().classify("禁止启动模拟风机", "instruction", ["start"])
    response = _pipeline(tmp_path).analyze(AnalysisRequest("禁止启动模拟风机"))

    assert classification.intent == "search"
    assert response.data["intent_classification"]["intent"] == "search"
    assert response.data.get("candidate_instruction") is None
    assert response.data["processing"]["instruction_status"] == "not_generated"


def test_incompatible_units_are_a_hard_consistency_conflict():
    result = ConsistencyEvaluationService().compare("温升不大于65K", "温升不大于65m")

    assert not result.consistent
    assert result.features.numeric_constraint_similarity == 0.0
    assert any(item["type"] == "numeric_constraint" for item in result.conflicts)


def test_missing_numeric_constraint_is_not_misreported_as_a_conflict():
    result = ConsistencyEvaluationService().compare("变压器温升要求是什么", "变压器温升不大于65K")

    assert result.features.numeric_constraint_similarity == 0.0
    assert not result.features.numeric_constraint_conflict
    assert not any(item["type"] == "numeric_constraint" for item in result.conflicts)


def test_non_strict_template_loading_quarantines_bad_rows(tmp_path):
    path = tmp_path / "custom.json"
    path.write_text(json.dumps({
        "simulation_only": True,
        "items": [{"device_id": "NOT-A-SIMULATOR", "action": "start", "template": {}}],
    }), encoding="utf-8")
    service = SimulationInstructionService()

    loaded = load_custom(service, path, strict=False)

    assert loaded == []
    assert service.template_load_errors
    assert service.devices
