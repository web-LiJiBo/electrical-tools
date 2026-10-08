from __future__ import annotations

from .models import DynamicBehavior, SemanticTuple, StaticParameter


class SemanticFramework:
    def to_three_layers(self, semantic: SemanticTuple) -> tuple[list[StaticParameter], list[DynamicBehavior], list[dict]]:
        static = [
            StaticParameter(
                str(item.get("parameter") or "raw_constraint"),
                item.get("value"),
                str(item.get("unit", "")),
            )
            for item in semantic.constraints
        ]
        behavior = [DynamicBehavior(semantic.condition or "已满足条款前置条件", semantic.action, semantic.target)]
        rules = [{
            "if": semantic.condition or "true",
            "then": {"action": semantic.action, "target": semantic.target},
            "constraints": semantic.constraints,
            "source_rule_id": semantic.source_rule_id,
        }]
        return static, behavior, rules
