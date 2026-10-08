"""安全条件判定器：只解释白名单比较表达式，禁止 eval。"""

from __future__ import annotations

import operator
import re
from typing import Any

from .models import ReasoningStatus, TraceStep

OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge, "==": operator.eq, "!=": operator.ne}
ALIASES = {"不大于": "<=", "不得大于": "<=", "不小于": ">=", "不得小于": ">=", "等于": "=="}


class SafeRuleEngine:
    _pattern = re.compile(r"^\s*(?P<field>[\w\u4e00-\u9fff.]+)\s*(?P<op><=|>=|==|!=|<|>|不大于|不得大于|不小于|不得小于|等于)\s*(?P<value>-?\d+(?:\.\d+)?|true|false|[^\s]+)\s*$", re.I)

    @staticmethod
    def _coerce(value: Any) -> Any:
        if isinstance(value, (int, float, bool)):
            return value
        text = str(value).strip()
        if text.lower() in ("true", "false"):
            return text.lower() == "true"
        try:
            return float(text)
        except ValueError:
            return text

    def evaluate_condition(self, expression: str, facts: dict[str, Any]) -> TraceStep:
        match = self._pattern.match(expression or "")
        if not match:
            return TraceStep("rule", ReasoningStatus.UNCERTAIN, "条件无法安全解析", {"expression": expression})
        field, raw_op, expected = match.group("field", "op", "value")
        if field not in facts:
            return TraceStep("rule", ReasoningStatus.UNCERTAIN, "缺少条件所需事实", {"field": field, "expression": expression})
        op = ALIASES.get(raw_op, raw_op)
        actual, wanted = self._coerce(facts[field]), self._coerce(expected)
        if type(actual) is not type(wanted) and not (isinstance(actual, (int, float)) and isinstance(wanted, (int, float))):
            return TraceStep("rule", ReasoningStatus.UNCERTAIN, "事实与阈值类型不兼容", {"actual": actual, "expected": wanted})
        passed = bool(OPS[op](actual, wanted))
        return TraceStep("rule", ReasoningStatus.PASS if passed else ReasoningStatus.FAIL, "条件满足" if passed else "条件不满足", {"field": field, "actual": actual, "operator": op, "expected": wanted})

    def evaluate(self, expressions: list[str], facts: dict[str, Any], mode: str = "all") -> tuple[ReasoningStatus, list[TraceStep]]:
        steps = [self.evaluate_condition(item, facts) for item in expressions]
        statuses = [step.status for step in steps]
        if not steps or ReasoningStatus.UNCERTAIN in statuses:
            return ReasoningStatus.UNCERTAIN, steps
        if mode == "any":
            return (ReasoningStatus.PASS if ReasoningStatus.PASS in statuses else ReasoningStatus.FAIL), steps
        return (ReasoningStatus.PASS if all(s is ReasoningStatus.PASS for s in statuses) else ReasoningStatus.FAIL), steps
