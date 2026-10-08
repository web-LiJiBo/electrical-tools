"""优先使用已结构化规则，不以模型补造条款事实。"""

from __future__ import annotations

from ..domain import ClauseKnowledgeUnit, Rule
from .models import SemanticTuple


class SemanticExtractor:
    def extract_rule(self, rule: Rule, unit: ClauseKnowledgeUnit | None = None) -> SemanticTuple:
        evidence = list(rule.evidence)
        if not evidence and unit is not None:
            from ..domain import EvidenceRef
            evidence = [EvidenceRef(unit.standard_id, unit.version, unit.clause_id, unit.chapter_path, unit.text, unit.source_uri)]
        constraints = [{"parameter": item.parameter, "operator": item.operator, "value": item.value, "unit": item.unit, "condition": item.condition} for item in rule.constraints]
        return SemanticTuple(rule.subject, rule.action, rule.subject, rule.condition, constraints, rule.rule_id, evidence)

    def extract_unit(self, unit: ClauseKnowledgeUnit) -> list[SemanticTuple]:
        return [self.extract_rule(rule, unit) for rule in unit.rules]
