from pathlib import Path
from types import SimpleNamespace

import pytest

from standard_knowledge_service_v2.config import load_config
from standard_knowledge_service_v2.domain import ClauseKnowledgeUnit, Entity, Rule
from standard_knowledge_service_v2.knowledge_graph.current_graph import CurrentKnowledgeGraph
from standard_knowledge_service_v2.knowledge_graph.neo4j_graph import (
    Neo4jKnowledgeGraph,
    build_sync_payload,
)
from standard_knowledge_service_v2.knowledge_graph.runtime import build_runtime_graph


def _unit(content: str = "温升不得超过65K") -> ClauseKnowledgeUnit:
    return ClauseKnowledgeUnit(
        "clause-1",
        "GB/T 1-2026",
        "2026",
        "6.2",
        content,
        [Entity("e1", "变压器", "设备")],
        [Rule("rule-1", "变压器", "限制", "运行时", content=content)],
        [{"source": "变压器", "target": "变压器", "type": "适用设备"}],
        source_uri="source.json",
        standard_name="变压器技术要求",
    )


class _Result:
    def __init__(self, records=()):
        self.records = list(records)


class FakeDriver:
    def __init__(self):
        self.queries = []
        self.state = {}
        self.hashes = {}
        self.verify_calls = 0

    def verify_connectivity(self):
        self.verify_calls += 1

    def execute_query(self, query, parameters_=None, database_=None):
        parameters = dict(parameters_ or {})
        self.queries.append((query, parameters, database_))
        if "RETURN 1 AS ok" in query:
            return _Result([{"ok": 1}])
        if "GraphSyncState" in query and "RETURN s{.*}" in query:
            return _Result([{"state": dict(self.state)}] if self.state else [])
        if "RETURN d.clause_id AS clause_id" in query:
            return _Result([
                {"clause_id": key, "source_hash": value}
                for key, value in sorted(self.hashes.items())
            ])
        if query.startswith("UNWIND $rows") and "MERGE (n:`Document`" in query:
            for row in parameters["rows"]:
                self.hashes[row["clause_id"]] = row["source_hash"]
            return _Result()
        if "MATCH (d:Document) WHERE d.clause_id IN $document_ids" in query:
            for clause_id in parameters["document_ids"]:
                self.hashes.pop(clause_id, None)
            return _Result()
        if "MERGE (s:GraphSyncState" in query:
            self.state = dict(parameters["state"])
            return _Result()
        if "CONTAINS_RULE" in query and "RETURN d._id AS document_node_id" in query:
            return _Result([{
                "document_node_id": "Document:clause-1",
                "rule_node_id": "Rule:rule-1",
                "standard_id": "GB/T 1-2026",
                "standard_name": "变压器技术要求",
                "chapter_path": "6.2",
                "source_path": "source.json",
                "quote": "温升不得超过65K",
            }])
        if "MATCH (n:Entity {normalized_name: $name})" in query:
            return _Result([{"relation": "HAS_RULE", "target": "温升不得超过65K"}])
        return _Result()


def _settings(**overrides):
    values = {
        "graph_backend": "neo4j",
        "fallback_to_memory": True,
        "neo4j_password_env": "TEST_NEO4J_PASSWORD",
        "neo4j_uri": "bolt://localhost:7687",
        "neo4j_user": "neo4j",
        "neo4j_database": "neo4j",
        "neo4j_connection_timeout_seconds": 1.0,
        "batch_size": 2,
        "sync_state_path": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_config_loads_authoritative_neo4j_settings():
    config = load_config("configs/settings.example.yaml")
    assert config.knowledge.graph_backend == "neo4j"
    assert config.knowledge.neo4j_database == "neo4j"
    assert config.knowledge.batch_size == 500
    assert config.knowledge.fallback_to_memory is True


def test_payload_fingerprint_is_deterministic_and_content_sensitive():
    first = build_sync_payload([_unit()])
    second = build_sync_payload([_unit()])
    changed = build_sync_payload([_unit("温升不得超过60K")])
    assert first.fingerprint == second.fingerprint
    assert first.fingerprint != changed.fingerprint
    assert first.counts == {"documents": 1, "entities": 1, "rules": 1, "relations": 4}


def test_neo4j_sync_uses_schema_batches_and_skips_unchanged(tmp_path):
    driver = FakeDriver()
    graph = Neo4jKnowledgeGraph(
        driver, batch_size=2, sync_state_path=tmp_path / "sync.json"
    )
    graph.health_check()
    first = graph.synchronize([_unit()])
    assert first.status == "updated" and first.changed_documents == 1
    assert driver.verify_calls == 1
    assert any("CREATE CONSTRAINT" in query for query, _, _ in driver.queries)
    assert any("UNWIND $rows" in query for query, _, _ in driver.queries)
    assert (tmp_path / "sync.json").is_file()

    writes_before = sum("UNWIND $rows" in query for query, _, _ in driver.queries)
    second = graph.synchronize([_unit()])
    writes_after = sum("UNWIND $rows" in query for query, _, _ in driver.queries)
    assert second.status == "unchanged"
    assert second.changed_documents == 0
    assert writes_after == writes_before

    third = graph.synchronize([_unit("温升不得超过60K")])
    assert third.status == "updated" and third.changed_documents == 1
    assert any(
        "DELETE r" in query and params.get("document_ids") == ["clause-1"]
        for query, params, _ in driver.queries
    )


def test_neo4j_evidence_and_neighbor_queries_remain_non_authorizing():
    graph = Neo4jKnowledgeGraph(FakeDriver())
    evidence = graph.evidence_path("rule-1")
    assert evidence["backend"] == "neo4j"
    assert evidence["quote"] == "温升不得超过65K"
    assert evidence["grants_control_permission"] is False
    assert graph.neighbors("变压器") == [("HAS_RULE", "温升不得超过65K")]


def test_runtime_falls_back_explicitly_and_can_be_strict(monkeypatch):
    def fail(_settings):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(Neo4jKnowledgeGraph, "connect", fail)
    messages = []
    graph = build_runtime_graph([_unit()], _settings(), messages.append)
    assert isinstance(graph, CurrentKnowledgeGraph)
    summary = graph.summary()
    assert summary["requested_backend"] == "neo4j"
    assert "connection refused" in summary["fallback_reason"]
    assert any("明确降级" in message for message in messages)

    with pytest.raises(RuntimeError, match="未允许内存降级"):
        build_runtime_graph(
            [_unit()], _settings(fallback_to_memory=False), messages.append
        )
