from __future__ import annotations

from collections import defaultdict, deque

from ..domain import ClauseKnowledgeUnit, Entity, Rule
from ..retrieval_engine.text import text_similarity


class InMemoryKnowledgeGraphRepository:
    def __init__(self) -> None:
        self.entities: dict[str, Entity] = {}
        self.rules: dict[str, Rule] = {}
        self.entity_rules: dict[str, set[str]] = defaultdict(set)
        self.edges: dict[str, list[tuple[str, str]]] = defaultdict(list)

    def upsert_clause_graph(self, unit: ClauseKnowledgeUnit) -> None:
        names = {entity.name: entity.entity_id for entity in unit.entities}
        for entity in unit.entities:
            self.entities[entity.entity_id] = entity
            for rule in unit.rules:
                self.rules[rule.rule_id] = rule
                self.entity_rules[entity.entity_id].add(rule.rule_id)
        for relation in unit.relations:
            source, target = names.get(str(relation.get("source", ""))), names.get(str(relation.get("target", "")))
            if source and target:
                self.edges[source].append((str(relation.get("type", "RELATION")), target))

    def link_entities(self, names, top_k: int) -> list[tuple[Entity, float]]:
        hits = []
        for entity in self.entities.values():
            score = max((text_similarity(str(name), entity.name) for name in names), default=0.0)
            if score > 0:
                hits.append((entity, score))
        return sorted(hits, key=lambda item: item[1], reverse=True)[:top_k]

    def rules_for_entities(self, entity_ids) -> list[Rule]:
        ids = {rule_id for entity_id in entity_ids for rule_id in self.entity_rules.get(entity_id, set())}
        return [self.rules[item] for item in ids]

    def traverse(self, entity_id: str, relations: list[str], max_depth: int) -> list[list[str]]:
        allowed = set(relations)
        queue, paths, seen = deque([(entity_id, [entity_id], 0)]), [], {entity_id}
        while queue:
            current, path, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for rel, target in self.edges.get(current, []):
                if allowed and rel not in allowed:
                    continue
                next_path = path + [rel, target]
                paths.append(next_path)
                if target not in seen:
                    seen.add(target)
                    queue.append((target, next_path, depth + 1))
        return paths
