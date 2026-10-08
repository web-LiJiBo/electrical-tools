from __future__ import annotations

from typing import Any

from ..consistency_evaluation.models import ConsistencyResult
from .models import ReasoningResult, ReasoningStatus, TraceStep
from .safe_rule_engine import SafeRuleEngine
from .semantic_reasoner import SemanticReasoner


class HybridReasoningEngine:
    def __init__(self, rule_engine: SafeRuleEngine | None = None, semantic_reasoner: SemanticReasoner | None = None) -> None:
        self.rule_engine = rule_engine or SafeRuleEngine()
        self.semantic_reasoner = semantic_reasoner

    def decide(self, conditions: list[str], facts: dict[str, Any], entity: str = "", consistency: ConsistencyResult | None = None) -> ReasoningResult:
        rule_status, trace = self.rule_engine.evaluate(conditions, facts)
        paths = self.semantic_reasoner.infer(entity) if self.semantic_reasoner and entity else []
        if paths:
            trace.append(TraceStep("graph", ReasoningStatus.PASS, "找到语义关联路径", {"path_count": len(paths)}))
        if consistency is not None:
            c_status = ReasoningStatus.PASS if consistency.consistent else ReasoningStatus.FAIL
            trace.append(TraceStep("consistency", c_status, "一致性评价完成", {"confidence": consistency.confidence, "conflicts": consistency.conflicts}))
        statuses = [step.status for step in trace if step.stage in ("rule", "consistency")]
        if ReasoningStatus.FAIL in statuses:
            status = ReasoningStatus.FAIL
        elif not statuses or ReasoningStatus.UNCERTAIN in statuses:
            status = ReasoningStatus.UNCERTAIN
        else:
            status = ReasoningStatus.PASS
        confidence = sum(1.0 if s is status else 0.0 for s in statuses) / len(statuses) if statuses else 0.0
        return ReasoningResult(status, confidence, trace, paths)
