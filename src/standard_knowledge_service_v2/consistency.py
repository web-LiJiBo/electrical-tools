"""规则层多维特征融合的一致性判定接口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .domain import EvidenceRef, Rule


@dataclass(slots=True)
class ConsistencyFeatures:
    rule_semantic_similarity: float
    numeric_constraint_match: float
    action_condition_overlap: float
    rule_count_difference: float = 0.0


@dataclass(slots=True)
class ConsistencyOutcome:
    is_consistent: bool
    confidence: float
    features: ConsistencyFeatures
    attention_weights: list[float] = field(default_factory=list)
    conflict_details: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)
    model_fingerprint: str = ""


class FeatureExtractor(Protocol):
    def extract(self, rules_a: list[Rule], rules_b: list[Rule]) -> ConsistencyFeatures: ...


class ConsistencyClassifier(Protocol):
    def predict(self, features: ConsistencyFeatures) -> ConsistencyOutcome: ...


class ConsistencyService(Protocol):
    def compare(self, clause_a: str, clause_b: str, input_type: str = "id") -> ConsistencyOutcome: ...


class FixedSplitEvaluator(Protocol):
    """固定ID划分、固定模型和固定图谱版本下输出可复核指标。"""

    def evaluate(self) -> dict[str, Any]: ...

