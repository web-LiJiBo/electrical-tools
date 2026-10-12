"""动作前置条件判定：独立于条款合规评价与检索排名。"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from ..hybrid_reasoning.models import ReasoningStatus, TraceStep
from ..hybrid_reasoning.safe_rule_engine import ALIASES, SafeRuleEngine


@dataclass(slots=True)
class PreconditionDecision:
    status: ReasoningStatus
    trace: list[TraceStep]

    def to_dict(self) -> dict:
        return {"status": self.status.value, "trace": [asdict(step) for step in self.trace]}


class ActionPreconditionEvaluator:
    def __init__(self) -> None:
        self.engine = SafeRuleEngine()

    def evaluate(self, expression: str, facts: dict[str, Any] | None = None, constraints: list[dict] | None = None) -> PreconditionDecision:
        decisions = [self._evaluate_one(expression, facts)]
        for constraint in constraints or []:
            role = constraint.get("role", "unspecified")
            if role == "compliance":
                continue
            if role != "precondition":
                step = TraceStep("precondition", ReasoningStatus.UNCERTAIN, "约束用途未标明，不能确认动作前置要求", {"constraint": constraint})
                decisions.append(PreconditionDecision(step.status, [step]))
                continue
            if constraint.get("operator") and constraint.get("parameter"):
                text = f"{constraint['parameter']} {constraint['operator']} {constraint.get('value', '')}{constraint.get('unit', '')}"
            else:
                text = str(constraint.get("value", ""))
            decisions.append(self._evaluate_one(text, facts))
        statuses = [decision.status for decision in decisions]
        status = ReasoningStatus.FAIL if ReasoningStatus.FAIL in statuses else (ReasoningStatus.UNCERTAIN if ReasoningStatus.UNCERTAIN in statuses else ReasoningStatus.PASS)
        return PreconditionDecision(status, [step for decision in decisions for step in decision.trace])

    def _evaluate_one(self, expression: str, facts: dict[str, Any] | None = None) -> PreconditionDecision:
        facts = dict(facts or {})
        match = self.engine._pattern.match(expression or "")
        if not match:
            step = TraceStep("precondition", ReasoningStatus.UNCERTAIN, "缺少可验证的动作前置条件或表达式无法解析", {"expression": expression})
            return PreconditionDecision(step.status, [step])
        field, raw_op, expected = match.group("field", "op", "value")
        if field not in facts or facts[field] is None:
            step = TraceStep("precondition", ReasoningStatus.UNCERTAIN, "缺少动作前置条件所需事实", {"field": field, "expression": expression})
            return PreconditionDecision(step.status, [step])
        # 支持“电流 >= 额定值”等显式事实引用，不以协议配置或模型补充信息代替实测事实。
        raw_wanted = facts[expected] if expected in facts else expected
        actual, wanted = self.engine._coerce(facts[field]), self.engine._coerce(raw_wanted)
        op = ALIASES.get(raw_op, raw_op)
        invalid = isinstance(facts[field], (dict, list, tuple)) or raw_wanted is None or isinstance(raw_wanted, (dict, list, tuple))
        invalid |= any(isinstance(value, float) and not math.isfinite(value) for value in (actual, wanted))
        if op in ("<", "<=", ">", ">="):
            invalid |= any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in (actual, wanted))
        else:
            invalid |= isinstance(actual, bool) != isinstance(wanted, bool)
        if invalid:
            step = TraceStep("precondition", ReasoningStatus.UNCERTAIN, "事实或阈值不可安全比较；需补充有效数值或完成单位转换", {"field": field, "expression": expression})
            return PreconditionDecision(step.status, [step])
        threshold = str(wanted).lower() if isinstance(wanted, bool) else str(wanted)
        step = self.engine.evaluate_condition(f"{field} {op} {threshold}", facts)
        step.stage = "precondition"
        return PreconditionDecision(step.status, [step])
