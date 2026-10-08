from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain import ClauseKnowledgeUnit, Entity, Rule


@dataclass(slots=True)
class EntityHit:
    entity: Entity
    score: float
    matched_by: str = "lexical"


@dataclass(slots=True)
class RuleHit:
    rule: Rule
    clause: ClauseKnowledgeUnit
    entity_score: float
    content_score: float
    structural_score: float
    score: float


@dataclass(slots=True)
class RetrievalTrace:
    query: str
    linked_entities: list[EntityHit] = field(default_factory=list)
    candidate_rules: int = 0
    filtered_rules: int = 0
    warnings: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
