"""由 ``lunwen/create_graph.py`` 复制并工程化的知识图谱构建模块。

默认内存后端便于离线构建和测试；需要持久化时使用 Py2neoGraphBackend。
本模块不引用源项目，工具目录可独立部署。
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


class GraphBackend(Protocol):
    def clear(self) -> None: ...
    def upsert_node(self, label: str, key: str, properties: dict[str, Any]) -> str: ...
    def merge_relation(self, source: str, relation: str, target: str, properties: dict[str, Any] | None = None) -> None: ...


@dataclass(slots=True)
class GraphBuildStats:
    files_seen: int = 0
    files_succeeded: int = 0
    documents: int = 0
    entities: int = 0
    rules: int = 0
    relations: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InMemoryGraphBackend:
    """确定性内存图后端，可用于测试、演示和离线完整性检查。"""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.relations: set[tuple[str, str, str, str]] = set()

    def clear(self) -> None:
        self.nodes.clear()
        self.relations.clear()

    def upsert_node(self, label: str, key: str, properties: dict[str, Any]) -> str:
        node_id = f"{label}:{normalize_name(key)}"
        current = self.nodes.setdefault(node_id, {"label": label, "key": key})
        current.update({k: v for k, v in properties.items() if v not in (None, "")})
        return node_id

    def merge_relation(self, source: str, relation: str, target: str, properties: dict[str, Any] | None = None) -> None:
        props = json.dumps(properties or {}, ensure_ascii=False, sort_keys=True)
        self.relations.add((source, relation, target, props))

    def neighbors(self, node_name: str, relation_types: set[str] | None = None) -> list[tuple[str, str]]:
        wanted = normalize_name(node_name)
        source_ids = {node_id for node_id, node in self.nodes.items() if normalize_name(node.get("name", node.get("key", ""))) == wanted}
        found: list[tuple[str, str]] = []
        for source, relation, target, _ in self.relations:
            if source in source_ids and (not relation_types or relation in relation_types):
                target_node = self.nodes.get(target, {})
                found.append((relation, str(target_node.get("name", target_node.get("key", target)))))
        return found


class Py2neoGraphBackend:
    """Neo4j 适配器；延迟导入 py2neo，不影响离线测试。"""

    def __init__(self, uri: str, user: str, password: str) -> None:
        try:
            from py2neo import Graph  # type: ignore
        except ImportError as exc:
            raise RuntimeError("启用 Neo4j 后端需要安装可选依赖 py2neo") from exc
        self.graph = Graph(uri, auth=(user, password))

    def clear(self) -> None:
        self.graph.run("MATCH (n) DETACH DELETE n")

    def upsert_node(self, label: str, key: str, properties: dict[str, Any]) -> str:
        node_id = f"{label}:{normalize_name(key)}"
        props = dict(properties, _id=node_id, name=properties.get("name", key))
        self.graph.run(f"MERGE (n:`{label}` {{_id: $id}}) SET n += $props", id=node_id, props=props)
        return node_id

    def merge_relation(self, source: str, relation: str, target: str, properties: dict[str, Any] | None = None) -> None:
        safe_relation = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff]", "_", relation or "RELATION")
        self.graph.run(
            f"MATCH (a {{_id: $source}}), (b {{_id: $target}}) MERGE (a)-[r:`{safe_relation}`]->(b) SET r += $props",
            source=source,
            target=target,
            props=properties or {},
        )


class KnowledgeGraphBuilder:
    def __init__(self, backend: GraphBackend) -> None:
        self.backend = backend

    @staticmethod
    def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
        raw = payload.get("raw_output")
        if isinstance(raw, str):
            try:
                decoded = json.loads(raw)
                if isinstance(decoded, dict):
                    return decoded
            except json.JSONDecodeError:
                pass
        return payload

    def process_document(self, payload: dict[str, Any], document_id: str, source_path: str = "") -> dict[str, int]:
        data = self._unwrap(payload)
        doc = self.backend.upsert_node("Document", document_id, {"name": document_id, "source_path": source_path})
        entities: dict[str, str] = {}
        for entity in data.get("entities", []) or []:
            if not isinstance(entity, dict) or not entity.get("name"):
                continue
            name = str(entity["name"])
            entities[normalize_name(name)] = self.backend.upsert_node(
                "Entity", name, {"name": name, "type": entity.get("type", ""), "desc": entity.get("desc", "")}
            )
            self.backend.merge_relation(doc, "MENTIONS", entities[normalize_name(name)])
        rules_created = 0
        for index, rule in enumerate(data.get("rules", []) or []):
            if not isinstance(rule, dict) or not rule.get("content"):
                continue
            content = str(rule["content"])
            rule_key = f"{document_id}#{index}:{content}"
            rule_id = self.backend.upsert_node("Rule", rule_key, dict(rule, name=content, document_id=document_id))
            self.backend.merge_relation(doc, "CONTAINS_RULE", rule_id)
            for name in rule.get("related_entities", []) or []:
                entity_id = entities.get(normalize_name(str(name)))
                if entity_id:
                    self.backend.merge_relation(entity_id, "HAS_RULE", rule_id)
            rules_created += 1
        explicit_relations = 0
        for relation in data.get("relations", []) or []:
            if not isinstance(relation, dict):
                continue
            source = entities.get(normalize_name(str(relation.get("source", ""))))
            target = entities.get(normalize_name(str(relation.get("target", ""))))
            if source and target:
                self.backend.merge_relation(source, str(relation.get("type") or "RELATION"), target)
                explicit_relations += 1
        return {"entities": len(entities), "rules": rules_created, "relations": explicit_relations}

    def build_directory(self, directory: Path, clear: bool = False) -> GraphBuildStats:
        if clear:
            self.backend.clear()
        stats = GraphBuildStats()
        for path in sorted(directory.rglob("*.json")):
            stats.files_seen += 1
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("JSON 顶层必须是对象")
                counts = self.process_document(payload, path.stem, str(path))
                stats.files_succeeded += 1
                stats.documents += 1
                stats.entities += counts["entities"]
                stats.rules += counts["rules"]
                stats.relations += counts["relations"]
            except Exception as exc:  # 单文件失败不能中断批次
                stats.failures.append({"file": str(path), "error": str(exc)})
        return stats


def build_existing_json(dataset_dir: Path, summary_path: Path) -> GraphBuildStats:
    backend = InMemoryGraphBackend()
    stats = KnowledgeGraphBuilder(backend).build_directory(dataset_dir, clear=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    result = stats.to_dict() | {"unique_nodes": len(backend.nodes), "unique_relations": len(backend.relations), "backend": "memory"}
    summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从论文分解 JSON 构建知识图谱")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--summary", type=Path, default=Path("artifacts/knowledge_graph/build_summary.json"))
    args = parser.parse_args(list(argv) if argv is not None else None)
    stats = build_existing_json(args.dataset, args.summary)
    print(json.dumps(stats.to_dict(), ensure_ascii=False))
    return 0 if not stats.failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
