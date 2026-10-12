"""Build a source-aligned local graph from the repository used by the application.

Audit metadata is not converted into graph entities or rule content. A graph
edge is evidence navigation, never proof of applicability or control permission.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

from .create_graph import InMemoryGraphBackend, normalize_name


class CurrentKnowledgeGraph(InMemoryGraphBackend):
    def __init__(self, units):
        super().__init__()
        self.rule_nodes = {}
        self.document_nodes = {}
        self.by_name = defaultdict(list)
        self.outgoing = defaultdict(list)
        seen = set()
        for unit in units:
            if unit.clause_id in seen:
                raise ValueError(f"Duplicate clause identity: {unit.clause_id}")
            seen.add(unit.clause_id)
            doc = self.upsert_node("Document", unit.clause_id, {
                "name": unit.clause_id, "clause_id": unit.clause_id,
                "standard_id": unit.standard_id, "standard_name": unit.standard_name, "version": unit.version,
                "chapter_path": unit.chapter_path, "source_path": unit.source_uri,
            })
            self.document_nodes[unit.clause_id] = doc
            entities = {}
            for entity in unit.entities:
                eid = self.upsert_node("Entity", entity.name, {"name": entity.name, "type": entity.category})
                entities[entity.name] = eid
                self.merge_relation(doc, "MENTIONS", eid)
            for rule in unit.rules:
                rid = self.upsert_node("Rule", rule.rule_id, {
                    "name": rule.content, "content": rule.content, "rule_id": rule.rule_id,
                    "document_id": unit.clause_id, "subject": rule.subject,
                    "action": rule.action, "operation": rule.operation, "condition": rule.condition,
                    "constraints_json": json.dumps([asdict(c) for c in rule.constraints], ensure_ascii=False),
                })
                self.rule_nodes[rule.rule_id] = rid
                self.merge_relation(doc, "CONTAINS_RULE", rid)
                # This is the same clause-level entity-rule association as the
                # runtime repository, not a newly inferred semantic relationship.
                for eid in entities.values():
                    self.merge_relation(eid, "HAS_RULE", rid)
            for rel in unit.relations:
                source, target = entities.get(rel.get("source")), entities.get(rel.get("target"))
                if source and target:
                    self.merge_relation(source, str(rel.get("type") or "RELATION"), target)
        for node_id, node in self.nodes.items():
            self.by_name[normalize_name(node.get("name", node["key"]))].append(node_id)
        for source, relation, target, _ in sorted(self.relations):
            self.outgoing[source].append((relation, target))

    def neighbors(self, node_name, relation_types=None):
        found = []
        for node_id in self.by_name.get(normalize_name(node_name), []):
            for rel, target in self.outgoing.get(node_id, []):
                if not relation_types or rel in relation_types:
                    node = self.nodes[target]
                    found.append((rel, str(node.get("name", node["key"]))))
        # Bounded explanatory traversal, not an exhaustive control inference.
        return found[:50]

    def evidence_path(self, rule_id):
        rid = self.rule_nodes.get(rule_id)
        if rid is None:
            return {}
        rule = self.nodes[rid]
        doc_id = self.document_nodes[rule["document_id"]]
        doc = self.nodes[doc_id]
        return {"backend": "local_memory", "path": [doc_id, "CONTAINS_RULE", rid],
                "rule_id": rule_id, "standard_id": doc.get("standard_id", ""),
                "standard_name": doc.get("standard_name", ""),
                "chapter_path": doc.get("chapter_path", ""), "source_path": doc.get("source_path", ""),
                "quote": rule["content"], "grants_control_permission": False}

    def summary(self):
        return {"backend": "local_memory", "documents": len(self.document_nodes),
                "rules": len(self.rule_nodes), "unique_nodes": len(self.nodes),
                "unique_relations": len(self.relations),
                "node_labels": dict(Counter(n["label"] for n in self.nodes.values())),
                "neo4j_imported": False, "dispatch_allowed": False}


def export_current_graph(application, output_dir):
    graph = application.facade.knowledge_graph
    units = application.facade.retriever.repository.units
    sources = [{"clause_id": u.clause_id, "path": u.source_uri,
                "sha256": sha256(Path(u.source_uri).read_bytes()).hexdigest()} for u in units]
    summary = graph.summary() | {"source_file_count": len(sources),
        "sources_fingerprint": sha256(json.dumps(sources, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        "source_directories": dict(Counter(str(Path(u.source_uri).parent) for u in units)),
        "scope": "来源条款导航图；不代表有效规范认证或自动控制授权"}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in (("graph.json", {"schema_version": "1.0", "summary": summary,
            "nodes": graph.nodes, "relations": [list(r) for r in sorted(graph.relations)]}),
            ("source_manifest.json", sources), ("build_summary.json", summary)):
        path = output_dir / name
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    return summary


def main():
    from ..bootstrap import build_application
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/settings.offline.yaml")
    parser.add_argument("--output", default="artifacts/knowledge_graph/current")
    args = parser.parse_args()
    app = build_application(args.config)
    print(json.dumps(export_current_graph(app, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
