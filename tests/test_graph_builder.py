import json

from standard_knowledge_service_v2.knowledge_graph import InMemoryGraphBackend, KnowledgeGraphBuilder


def test_graph_builder_creates_document_entities_rules_and_relations(tmp_path) -> None:
    payload = {
        "entities": [{"name": "变压器", "type": "设备"}, {"name": "65K", "type": "阈值"}],
        "rules": [{"content": "温升不大于65K", "related_entities": ["变压器", "65K"]}],
        "relations": [{"source": "变压器", "target": "65K", "type": "温升限制"}],
    }
    (tmp_path / "case.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    backend = InMemoryGraphBackend()
    stats = KnowledgeGraphBuilder(backend).build_directory(tmp_path, clear=True)
    assert stats.files_succeeded == 1
    assert stats.entities == 2 and stats.rules == 1
    assert {node["label"] for node in backend.nodes.values()} == {"Document", "Entity", "Rule"}
    assert any(item[1] == "温升限制" for item in backend.relations)


def test_bad_json_is_isolated(tmp_path) -> None:
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    stats = KnowledgeGraphBuilder(InMemoryGraphBackend()).build_directory(tmp_path)
    assert stats.files_seen == 1 and len(stats.failures) == 1
