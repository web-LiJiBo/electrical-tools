import json

from standard_knowledge_service_v2.adapters import LunwenRetrievalAdapter
from standard_knowledge_service_v2.domain import ClauseKnowledgeUnit, Entity, Rule
from standard_knowledge_service_v2.knowledge import InMemoryKnowledgeGraphRepository, InMemoryStandardRepository, VersionService
from standard_knowledge_service_v2.retrieval import LunwenMatchingInput
from standard_knowledge_service_v2.retrieval_engine import JsonClauseRepository, LocalLunwenRetrievalAdapter
from standard_knowledge_service_v2.retrieval_engine.evidence_builder import EvidenceBuilder


def _write_sample(tmp_path) -> None:
    payload = {
        "entities": [{"name": "集电线路", "type": "设备"}, {"name": "过流保护", "type": "保护功能"}],
        "rules": [{"content": "集电线路发生过流时应跳闸", "subject": "集电线路", "action": "跳闸", "condition": "发生过流", "constraint": "电流不大于额定值"}],
        "relations": [{"source": "集电线路", "target": "过流保护", "type": "配置保护"}],
    }
    (tmp_path / "case.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_local_lunwen_retrieval_builds_rule_and_scores(tmp_path) -> None:
    _write_sample(tmp_path)
    adapter = LocalLunwenRetrievalAdapter.from_dataset(tmp_path)
    result = adapter.match(LunwenMatchingInput("集电线路过流时应跳闸", {"entities": [{"name": "集电线路"}]}))
    assert result.matched_entities[0].name == "集电线路"
    assert result.rules[0].rule.action == "trip"
    assert result.rules[0].rule.content == "集电线路发生过流时应跳闸"
    assert result.rules[0].combined_score is not None


def test_evidence_keeps_source_and_clause_id(tmp_path) -> None:
    _write_sample(tmp_path)
    repo = JsonClauseRepository.from_directory(tmp_path)
    adapter = LocalLunwenRetrievalAdapter(repo)
    adapter.match(LunwenMatchingInput("集电线路过流", {"entities": [{"name": "集电线路"}]}))
    hit = adapter.last_trace
    assert hit is not None and hit.candidate_rules == 1
    unit, rule = repo.units[0], repo.units[0].rules[0]
    from standard_knowledge_service_v2.retrieval_engine.models import RuleHit
    evidence = EvidenceBuilder().build(RuleHit(rule, unit, 1, 1, 1, 1))
    assert evidence.clause_id == "case" and evidence.source_uri.endswith("case.json")
    assert evidence.quote == "集电线路发生过流时应跳闸"


def test_memory_standard_graph_and_version_services() -> None:
    entity = Entity("e1", "集电线路", "设备")
    rule = Rule("r1", "集电线路", "跳闸", "发生过流")
    unit = ClauseKnowledgeUnit("c1", "DL/T 1", "2025", "5.1", "集电线路发生过流时应跳闸", [entity], [rule])
    standards = InMemoryStandardRepository([unit])
    assert standards.get_clause("c1") is unit
    graph = InMemoryKnowledgeGraphRepository()
    graph.upsert_clause_graph(unit)
    linked = graph.link_entities(["集电线路"], 1)
    assert graph.rules_for_entities([linked[0][0].entity_id])[0].rule_id == "r1"
    assert VersionService().is_current("2025", ["2023", "2025"])


def test_existing_adapter_uses_tool_dataset_without_source_import(tmp_path) -> None:
    _write_sample(tmp_path)
    adapter = LunwenRetrievalAdapter(str(tmp_path))
    result = adapter.match(LunwenMatchingInput("集电线路过流", {"entities": [{"name": "集电线路"}]}))
    assert len(result.rules) == 1
