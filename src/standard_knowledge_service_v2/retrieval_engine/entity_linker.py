from __future__ import annotations

from ..domain import Entity
from .models import EntityHit
from .text import cosine, normalize, tokens


class EntityLinker:
    def __init__(self, threshold: float = 0.3) -> None:
        self.threshold = threshold
        self._prepared: dict[str, tuple[str, object]] = {}
        self._name_entities: dict[str, list[Entity]] = {}
        self._token_names: dict[str, set[str]] = {}

    def prepare(self, candidates: list[Entity]) -> None:
        """Build a reusable lexical shortlist instead of scanning all entities."""
        if self._name_entities:
            return
        for entity in candidates:
            raw = entity.normalized_name or entity.name
            name = normalize(raw)
            self._name_entities.setdefault(name, []).append(entity)
            self._prepared.setdefault(raw, (name, tokens(name)))
        for name in self._name_entities:
            for token in tokens(name):
                self._token_names.setdefault(token, set()).add(name)

    def _shortlist(self, name: str, candidates: list[Entity]) -> list[Entity]:
        if not self._name_entities:
            self.prepare(candidates)
        if name in self._name_entities:
            return self._name_entities[name]
        keys = list(tokens(name))
        postings = [self._token_names[key] for key in keys if key in self._token_names]
        if not postings:
            return []
        intersection = set.intersection(*postings)
        names = intersection or set.union(*sorted(postings, key=len)[:3])
        return [entity for candidate_name in names for entity in self._name_entities[candidate_name]]

    def _similarity(self, a: str, left_tokens, right: str) -> float:
        if not a:
            return 0.0
        b, counter = self._prepared.setdefault(right, (normalize(right), tokens(right)))
        if not b:
            return 0.0
        if a == b:
            return 1.0
        if a in b or b in a:
            return min(len(a), len(b)) / max(len(a), len(b))
        return cosine(left_tokens, counter)

    def link(self, names: list[str], candidates: list[Entity], top_k: int = 26) -> list[EntityHit]:
        best: dict[str, EntityHit] = {}
        for name in names:
            normalized = normalize(name)
            prepared = tokens(normalized)
            for entity in self._shortlist(normalized, candidates):
                score = self._similarity(normalized, prepared, entity.normalized_name or entity.name)
                if score >= self.threshold and (entity.entity_id not in best or score > best[entity.entity_id].score):
                    best[entity.entity_id] = EntityHit(entity, score)
        return sorted(best.values(), key=lambda item: item.score, reverse=True)[:top_k]
