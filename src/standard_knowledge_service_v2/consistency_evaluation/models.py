from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class NumericConstraint:
    operator: str
    value: float
    unit: str = ""
    upper_value: float | None = None


@dataclass(slots=True)
class ConsistencyFeatures:
    rule_set_similarity: float
    numeric_constraint_similarity: float
    semantic_similarity: float
    structural_similarity: float

    def vector(self) -> list[float]:
        return [self.rule_set_similarity, self.numeric_constraint_similarity, self.semantic_similarity, self.structural_similarity]


@dataclass(slots=True)
class ConsistencyResult:
    consistent: bool
    confidence: float
    features: ConsistencyFeatures
    attention_weights: list[float]
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    model: str = "transparent-weighted-fallback"

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["features"] = asdict(self.features)
        return result

