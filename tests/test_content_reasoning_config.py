import json

from standard_knowledge_service_v2.application import AnalysisPipeline
from standard_knowledge_service_v2.config import load_config
from standard_knowledge_service_v2.consistency_evaluation.models import ConsistencyFeatures, ConsistencyResult
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.domain import Rule
from standard_knowledge_service_v2.retrieval import RuleMatch
from standard_knowledge_service_v2.retrieval_engine import JsonClauseRepository, LocalLunwenRetrievalAdapter
from standard_knowledge_service_v2.retrieval_engine.evidence_builder import EvidenceBuilder
from standard_knowledge_service_v2.retrieval_engine.models import RuleHit


def test_rule_content_is_preserved_for_retrieval_evidence_and_report(tmp_path) -> None:
    original = "集电线路发生过流时应立即切除故障线路。"
    payload = {
        "entities": [{"name": "集电线路", "type": "设备"}],
        "rules": [{"content": original, "subject": "", "action": "", "condition": ""}],
    }
    (tmp_path / "case.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    repository = JsonClauseRepository.from_directory(tmp_path)
    rule, unit = repository.units[0].rules[0], repository.units[0]
    assert rule.content == original
    evidence = EvidenceBuilder().build(RuleHit(rule, unit, 0.0, 1.0, 1.0, 1.0))
    assert evidence.quote == original


class _ControlledConsistency:
    def compare(self, left: str, right: str) -> ConsistencyResult:
        score = 1.0 if "过流" in right else 0.0
        features = ConsistencyFeatures(score, score, score, score)
        return ConsistencyResult(bool(score), 1.0, features, [0.25] * 4)


def test_consistency_and_reasoning_can_replace_retrieval_top_one(tmp_path) -> None:
    adapter = LocalLunwenRetrievalAdapter(JsonClauseRepository([]))
    pipeline = AnalysisPipeline(adapter, consistency=_ControlledConsistency())
    unrelated = Rule("r1", "变压器", "检查", "", content="变压器应定期检查")
    relevant = Rule("r2", "集电线路", "跳闸", "", content="集电线路发生过流时应跳闸")
    matches = [
        RuleMatch(unrelated, rank=1, combined_score=0.9),
        RuleMatch(relevant, rank=2, combined_score=0.7),
    ]
    selected, assessments = pipeline._select_rule(AnalysisRequest("集电线路过流如何处理"), matches)
    assert selected is not None and selected.rule.rule_id == "r2"
    assert assessments[0]["rule_id"] == "r2"
    assert "consistency" in assessments[0] and "reasoning" in assessments[0]


def test_example_config_controls_paths_and_thresholds() -> None:
    config = load_config("configs/settings.example.yaml")
    assert config.models.llm.name == "master"
    assert config.data.verified_json.name == "json"
    assert config.retrieval.entity_similarity_threshold == 0.3
    assert config.consistency.threshold == 0.62
