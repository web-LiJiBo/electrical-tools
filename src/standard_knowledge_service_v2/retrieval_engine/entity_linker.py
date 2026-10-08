from __future__ import annotations

from ..domain import Entity
from .models import EntityHit
from .text import text_similarity


class EntityLinker:
    def __init__(self, threshold: float = 0.3) -> None:
        self.threshold = threshold

    def link(self, names: list[str], candidates: list[Entity], top_k: int = 26) -> list[EntityHit]:
        best: dict[str, EntityHit] = {}
        for name in names:
            for entity in candidates:
                score = text_similarity(name, entity.normalized_name or entity.name)
                if score >= self.threshold and (entity.entity_id not in best or score > best[entity.entity_id].score):
                    best[entity.entity_id] = EntityHit(entity, score)
        return sorted(best.values(), key=lambda item: item.score, reverse=True)[:top_k]
