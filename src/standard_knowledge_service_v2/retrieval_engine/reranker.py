from __future__ import annotations

from .models import RuleHit


class EvidenceReranker:
    def __init__(self, vector_weight: float = 0.8, structural_weight: float = 0.2) -> None:
        if vector_weight < 0 or structural_weight < 0 or vector_weight + structural_weight == 0:
            raise ValueError("重排权重必须为非负且至少一项大于0")
        total = vector_weight + structural_weight
        self.vector_weight, self.structural_weight = vector_weight / total, structural_weight / total

    def rank(self, hits: list[RuleHit]) -> list[RuleHit]:
        for item in hits:
            item.score = self.vector_weight * ((item.entity_score + item.content_score) / 2) + self.structural_weight * item.structural_score
        return sorted(hits, key=lambda item: item.score, reverse=True)
