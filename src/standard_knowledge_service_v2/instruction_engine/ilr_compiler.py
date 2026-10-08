from __future__ import annotations

from .models import ILRProgram, SemanticTuple
from .semantic_framework import SemanticFramework
from .swrl_compiler import SwrlCompiler


class ILRCompiler:
    def __init__(self, framework: SemanticFramework | None = None) -> None:
        self.framework = framework or SemanticFramework()
        self.swrl = SwrlCompiler()

    def compile(self, semantic: SemanticTuple) -> ILRProgram:
        static, behaviors, rules = self.framework.to_three_layers(semantic)
        return ILRProgram(
            conditions=[{"expression": semantic.condition or "true", "source": "clause"}],
            actions=[{"action": semantic.action, "target": semantic.target, "constraints": semantic.constraints}],
            static_parameters=static,
            dynamic_behaviors=behaviors,
            constraint_rules=rules,
            swrl_rules=[self.swrl.compile(semantic)],
            source_rule_ids=[semantic.source_rule_id] if semantic.source_rule_id else [],
            evidence=semantic.evidence,
        )
