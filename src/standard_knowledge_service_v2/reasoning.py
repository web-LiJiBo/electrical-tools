"""规则前向链、图谱语义推理及统一的不确定性处理。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .domain import Decision, Rule, ScenarioContext


@dataclass(slots=True)
class ReasoningTrace:
    matched_rules: list[str] = field(default_factory=list)
    graph_paths: list[list[str]] = field(default_factory=list)
    evaluated_conditions: list[dict[str, Any]] = field(default_factory=list)
    unresolved_conditions: list[str] = field(default_factory=list)
    config_fingerprint: str = ""


class SafeRuleEngine(Protocol):
    """无法解析的条件必须返回不确定，不得默认判为通过。"""

    def evaluate(self, rules: list[Rule], parameters: dict[str, Any]) -> tuple[Decision, ReasoningTrace]: ...


class SemanticReasoner(Protocol):
    def infer(self, entity: str, relation_types: list[str], max_depth: int) -> ReasoningTrace: ...


class HybridReasoningEngine(Protocol):
    def decide(
        self,
        context: ScenarioContext,
        candidate_rules: list[Rule],
    ) -> tuple[Decision, ReasoningTrace]: ...

