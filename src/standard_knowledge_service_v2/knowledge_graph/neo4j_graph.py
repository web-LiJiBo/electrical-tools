"""Neo4j-backed, source-aligned knowledge graph with incremental synchronization.

The graph is an evidence-navigation layer.  It never grants control permission.
All Neo4j imports are delayed so the default offline installation remains usable
without the optional graph dependency.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from .create_graph import normalize_name


def _node_id(label: str, key: str) -> str:
    return f"{label}:{normalize_name(key)}"


def _safe_relation(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff]", "_", value or "RELATION")


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return sha256(_stable_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class GraphSyncPayload:
    documents: tuple[dict[str, Any], ...]
    entities: tuple[dict[str, Any], ...]
    rules: tuple[dict[str, Any], ...]
    relations: tuple[dict[str, Any], ...]
    unit_hashes: Mapping[str, str]
    fingerprint: str

    @property
    def counts(self) -> dict[str, int]:
        return {
            "documents": len(self.documents),
            "entities": len(self.entities),
            "rules": len(self.rules),
            "relations": len(self.relations),
        }

    def subset(self, document_ids: set[str]) -> "GraphSyncPayload":
        documents = tuple(row for row in self.documents if row["clause_id"] in document_ids)
        rules = tuple(row for row in self.rules if row["document_id"] in document_ids)
        relations = tuple(row for row in self.relations if row["document_id"] in document_ids)
        referenced = {row["source"] for row in relations} | {row["target"] for row in relations}
        entities = tuple(row for row in self.entities if row["id"] in referenced)
        hashes = {key: value for key, value in self.unit_hashes.items() if key in document_ids}
        return GraphSyncPayload(documents, entities, rules, relations, hashes, self.fingerprint)


@dataclass(frozen=True, slots=True)
class GraphSyncReport:
    status: str
    fingerprint: str
    changed_documents: int
    removed_documents: int
    unchanged_documents: int
    batches_written: int
    counts: Mapping[str, int]
    completed_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_sync_payload(units: Iterable[Any]) -> GraphSyncPayload:
    """Create a deterministic graph payload and one hash per clause unit."""
    documents: list[dict[str, Any]] = []
    entities_by_id: dict[str, dict[str, Any]] = {}
    rules: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    unit_hashes: dict[str, str] = {}
    seen_clauses: set[str] = set()
    seen_rules: set[str] = set()

    for unit in units:
        clause_id = str(unit.clause_id)
        if clause_id in seen_clauses:
            raise ValueError(f"Duplicate clause identity: {clause_id}")
        seen_clauses.add(clause_id)
        document_id = _node_id("Document", clause_id)
        entity_ids: dict[str, str] = {}
        entity_snapshot: list[dict[str, Any]] = []
        for entity in unit.entities:
            normalized = normalize_name(entity.normalized_name or entity.name)
            entity_id = _node_id("Entity", normalized)
            entity_ids[normalize_name(entity.name)] = entity_id
            row = {
                "id": entity_id,
                "name": entity.name,
                "normalized_name": normalized,
                "type": entity.category,
                "aliases": list(entity.aliases),
            }
            entities_by_id[entity_id] = row
            entity_snapshot.append(row)
            relations.append({
                "source": document_id,
                "target": entity_id,
                "type": "MENTIONS",
                "document_id": clause_id,
                "properties": {},
            })

        rule_snapshot: list[dict[str, Any]] = []
        for index, rule in enumerate(unit.rules):
            rule_key = str(rule.rule_id or f"{clause_id}#{index}")
            if rule_key in seen_rules:
                raise ValueError(f"Duplicate rule identity: {rule_key}")
            seen_rules.add(rule_key)
            rule_id = _node_id("Rule", rule_key)
            constraint_payload = [asdict(item) for item in rule.constraints]
            row = {
                "id": rule_id,
                "rule_id": rule_key,
                "name": rule.content,
                "content": rule.content,
                "document_id": clause_id,
                "subject": rule.subject,
                "action": rule.action,
                "operation": rule.operation,
                "condition": rule.condition,
                "priority": rule.priority,
                "constraints_json": _stable_json(constraint_payload),
            }
            rules.append(row)
            rule_snapshot.append(row)
            relations.append({
                "source": document_id,
                "target": rule_id,
                "type": "CONTAINS_RULE",
                "document_id": clause_id,
                "properties": {},
            })
            # This mirrors the source clause's entity-rule association.  It is
            # evidence navigation, not a newly inferred applicability claim.
            for entity_id in sorted(set(entity_ids.values())):
                relations.append({
                    "source": entity_id,
                    "target": rule_id,
                    "type": "HAS_RULE",
                    "document_id": clause_id,
                    "properties": {},
                })

        explicit_snapshot: list[dict[str, Any]] = []
        for relation in unit.relations:
            if not isinstance(relation, dict):
                continue
            source = entity_ids.get(normalize_name(str(relation.get("source", ""))))
            target = entity_ids.get(normalize_name(str(relation.get("target", ""))))
            if source and target:
                row = {
                    "source": source,
                    "target": target,
                    "type": _safe_relation(str(relation.get("type") or "RELATION")),
                    "document_id": clause_id,
                    "properties": {},
                }
                relations.append(row)
                explicit_snapshot.append(row)

        source_snapshot = {
            "clause_id": clause_id,
            "standard_id": unit.standard_id,
            "standard_name": unit.standard_name,
            "version": unit.version,
            "chapter_path": unit.chapter_path,
            "text": unit.text,
            "source_path": unit.source_uri,
            "entities": sorted(entity_snapshot, key=lambda item: item["id"]),
            "rules": sorted(rule_snapshot, key=lambda item: item["id"]),
            "relations": sorted(
                explicit_snapshot,
                key=lambda item: (item["source"], item["type"], item["target"]),
            ),
        }
        source_hash = _hash(source_snapshot)
        unit_hashes[clause_id] = source_hash
        documents.append({
            "id": document_id,
            "clause_id": clause_id,
            "name": clause_id,
            "standard_id": unit.standard_id,
            "standard_name": unit.standard_name,
            "version": unit.version,
            "chapter_path": unit.chapter_path,
            "source_path": unit.source_uri,
            "source_hash": source_hash,
        })

    documents.sort(key=lambda item: item["clause_id"])
    rules.sort(key=lambda item: item["id"])
    relations.sort(key=lambda item: (item["document_id"], item["source"], item["type"], item["target"]))
    entities = tuple(sorted(entities_by_id.values(), key=lambda item: item["id"]))
    fingerprint = _hash(sorted(unit_hashes.items()))
    return GraphSyncPayload(
        tuple(documents), entities, tuple(rules), tuple(relations), unit_hashes, fingerprint
    )


class Neo4jKnowledgeGraph:
    """Runtime graph using the official Neo4j driver and bounded queries."""

    backend_name = "neo4j"
    state_id = "standard_knowledge_graph"

    def __init__(
        self,
        driver: Any,
        *,
        database: str = "neo4j",
        batch_size: int = 500,
        sync_state_path: Path | None = None,
    ) -> None:
        self.driver = driver
        self.database = database
        self.batch_size = batch_size
        self.sync_state_path = sync_state_path
        self.last_sync: GraphSyncReport | None = None

    @classmethod
    def connect(cls, settings: Any) -> "Neo4jKnowledgeGraph":
        password = os.environ.get(settings.neo4j_password_env, "")
        if not password:
            raise RuntimeError(
                f"Neo4j密码环境变量{settings.neo4j_password_env}未设置"
            )
        try:
            from neo4j import GraphDatabase  # type: ignore
        except ImportError as exc:
            raise RuntimeError("启用Neo4j后端需要安装可选依赖neo4j") from exc
        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, password),
            connection_timeout=settings.neo4j_connection_timeout_seconds,
        )
        return cls(
            driver,
            database=settings.neo4j_database,
            batch_size=settings.batch_size,
            sync_state_path=settings.sync_state_path,
        )

    def close(self) -> None:
        self.driver.close()

    def health_check(self) -> None:
        self.driver.verify_connectivity()
        self._records("RETURN 1 AS ok")

    def _records(self, query: str, parameters: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        result = self.driver.execute_query(
            query,
            parameters_=dict(parameters or {}),
            database_=self.database,
        )
        records = result.records if hasattr(result, "records") else result[0]
        return [dict(record) for record in records]

    def _write(self, query: str, parameters: Mapping[str, Any] | None = None) -> None:
        self._records(query, parameters)

    def _batches(self, rows: Sequence[dict[str, Any]]) -> Iterable[list[dict[str, Any]]]:
        for index in range(0, len(rows), self.batch_size):
            yield list(rows[index:index + self.batch_size])

    def ensure_schema(self) -> None:
        statements = [
            "CREATE CONSTRAINT document_id_unique IF NOT EXISTS FOR (n:Document) REQUIRE n._id IS UNIQUE",
            "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (n:Entity) REQUIRE n._id IS UNIQUE",
            "CREATE CONSTRAINT rule_id_unique IF NOT EXISTS FOR (n:Rule) REQUIRE n._id IS UNIQUE",
            "CREATE CONSTRAINT graph_sync_state_unique IF NOT EXISTS FOR (n:GraphSyncState) REQUIRE n._id IS UNIQUE",
            "CREATE INDEX document_clause_id IF NOT EXISTS FOR (n:Document) ON (n.clause_id)",
            "CREATE INDEX document_standard_id IF NOT EXISTS FOR (n:Document) ON (n.standard_id)",
            "CREATE INDEX entity_normalized_name IF NOT EXISTS FOR (n:Entity) ON (n.normalized_name)",
            "CREATE INDEX rule_rule_id IF NOT EXISTS FOR (n:Rule) ON (n.rule_id)",
        ]
        for statement in statements:
            self._write(statement)

    def _sync_state(self) -> dict[str, Any]:
        rows = self._records(
            "MATCH (s:GraphSyncState {_id: $id}) RETURN s{.*} AS state",
            {"id": self.state_id},
        )
        return dict(rows[0].get("state") or {}) if rows else {}

    def _existing_hashes(self) -> dict[str, str]:
        rows = self._records(
            "MATCH (d:Document) RETURN d.clause_id AS clause_id, d.source_hash AS source_hash"
        )
        return {
            str(row["clause_id"]): str(row.get("source_hash") or "")
            for row in rows
            if row.get("clause_id")
        }

    def synchronize(self, units: Iterable[Any]) -> GraphSyncReport:
        payload = build_sync_payload(units)
        self.ensure_schema()
        state = self._sync_state()
        desired_counts = payload.counts
        now = datetime.now(timezone.utc).isoformat()
        state_counts = {
            key: int(state.get(key, -1)) for key in desired_counts
        }
        if state.get("fingerprint") == payload.fingerprint and state_counts == desired_counts:
            report = GraphSyncReport(
                "unchanged", payload.fingerprint, 0, 0, len(payload.documents), 0,
                desired_counts, now,
            )
            self.last_sync = report
            self._write_local_state(report)
            return report

        existing = self._existing_hashes()
        changed = {
            clause_id for clause_id, source_hash in payload.unit_hashes.items()
            if existing.get(clause_id) != source_hash
        }
        removed = set(existing) - set(payload.unit_hashes)
        affected = sorted(changed | removed)
        batches_written = 0
        for batch in self._batches([{"clause_id": item} for item in affected]):
            ids = [row["clause_id"] for row in batch]
            self._write(
                "MATCH ()-[r]->() WHERE r.document_id IN $document_ids DELETE r",
                {"document_ids": ids},
            )
            self._write(
                "MATCH (r:Rule) WHERE r.document_id IN $document_ids DETACH DELETE r",
                {"document_ids": ids},
            )
            self._write(
                "MATCH (d:Document) WHERE d.clause_id IN $document_ids DETACH DELETE d",
                {"document_ids": ids},
            )
            batches_written += 1

        changed_payload = payload.subset(changed)
        batches_written += self._upsert_nodes("Document", changed_payload.documents)
        batches_written += self._upsert_nodes("Entity", changed_payload.entities)
        batches_written += self._upsert_nodes("Rule", changed_payload.rules)
        batches_written += self._upsert_relations(changed_payload.relations)
        if affected:
            self._write("MATCH (e:Entity) WHERE NOT (e)--() DELETE e")

        metadata = {
            "_id": self.state_id,
            "fingerprint": payload.fingerprint,
            "completed_at": now,
            **desired_counts,
        }
        self._write(
            "MERGE (s:GraphSyncState {_id: $id}) SET s += $state",
            {"id": self.state_id, "state": metadata},
        )
        report = GraphSyncReport(
            "updated", payload.fingerprint, len(changed), len(removed),
            len(payload.documents) - len(changed), batches_written, desired_counts, now,
        )
        self.last_sync = report
        self._write_local_state(report)
        return report

    def _upsert_nodes(self, label: str, rows: Sequence[dict[str, Any]]) -> int:
        if not rows:
            return 0
        query = f"UNWIND $rows AS row MERGE (n:`{label}` {{_id: row.id}}) SET n += row"
        batches = 0
        for batch in self._batches(rows):
            self._write(query, {"rows": batch})
            batches += 1
        return batches

    def _upsert_relations(self, rows: Sequence[dict[str, Any]]) -> int:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[_safe_relation(row["type"])].append(row)
        batches = 0
        for relation_type, relation_rows in sorted(grouped.items()):
            query = (
                "UNWIND $rows AS row "
                "MATCH (a {_id: row.source}), (b {_id: row.target}) "
                f"MERGE (a)-[r:`{relation_type}` {{document_id: row.document_id}}]->(b) "
                "SET r += row.properties"
            )
            for batch in self._batches(relation_rows):
                self._write(query, {"rows": batch})
                batches += 1
        return batches

    def _write_local_state(self, report: GraphSyncReport) -> None:
        if self.sync_state_path is None:
            return
        path = Path(self.sync_state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)

    def evidence_path(self, rule_id: str) -> dict[str, Any]:
        rows = self._records(
            "MATCH (d:Document)-[:CONTAINS_RULE]->(r:Rule {rule_id: $rule_id}) "
            "RETURN d._id AS document_node_id, r._id AS rule_node_id, "
            "d.standard_id AS standard_id, d.standard_name AS standard_name, "
            "d.chapter_path AS chapter_path, d.source_path AS source_path, "
            "r.content AS quote LIMIT 1",
            {"rule_id": rule_id},
        )
        if not rows:
            return {}
        row = rows[0]
        return {
            "backend": "neo4j",
            "path": [row["document_node_id"], "CONTAINS_RULE", row["rule_node_id"]],
            "rule_id": rule_id,
            "standard_id": row.get("standard_id", ""),
            "standard_name": row.get("standard_name", ""),
            "chapter_path": row.get("chapter_path", ""),
            "source_path": row.get("source_path", ""),
            "quote": row.get("quote", ""),
            "grants_control_permission": False,
        }

    def neighbors(
        self, node_name: str, relation_types: set[str] | None = None
    ) -> list[tuple[str, str]]:
        rows = self._records(
            "MATCH (n:Entity {normalized_name: $name})-[r]->(m) "
            "WHERE size($relation_types) = 0 OR type(r) IN $relation_types "
            "RETURN type(r) AS relation, coalesce(m.name, m._id) AS target "
            "ORDER BY relation, target LIMIT 50",
            {
                "name": normalize_name(node_name),
                "relation_types": sorted(relation_types or set()),
            },
        )
        return [(str(row["relation"]), str(row["target"])) for row in rows]

    def summary(self) -> dict[str, Any]:
        report = self.last_sync
        counts = dict(report.counts) if report else {}
        return {
            "backend": "neo4j",
            "database": self.database,
            "connected": True,
            "sync_status": report.status if report else "not_started",
            "fingerprint": report.fingerprint if report else "",
            **counts,
            "neo4j_imported": bool(report),
            "dispatch_allowed": False,
        }
