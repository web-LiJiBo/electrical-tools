from __future__ import annotations

from ..domain import ClauseKnowledgeUnit, ScenarioContext
from .validation_models import ValidationStatus


class ApplicabilityValidator:
    def validate(self, unit: ClauseKnowledgeUnit, context: ScenarioContext) -> tuple[ValidationStatus, list[str]]:
        errors: list[str] = []
        if not unit.text:
            return ValidationStatus.FAIL, ["条款原文为空"]
        scope = str(unit.metadata.get("scenario", ""))
        if scope and scope not in (context.scenario, "general"):
            errors.append(f"条款场景范围不匹配: {scope}")
        if context.device_type and unit.entities and not any(context.device_type in entity.name or entity.name in context.device_type for entity in unit.entities):
            # JSON实体可能不含设备名称，此情形仅提示人工确认。
            return ValidationStatus.UNCERTAIN, ["条款实体与设备类型无法确认匹配"] + errors
        return (ValidationStatus.FAIL if errors else ValidationStatus.PASS), errors
