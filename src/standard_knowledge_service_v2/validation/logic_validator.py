from __future__ import annotations

from ..instruction_engine.models import ILRProgram
from .validation_models import ValidationStatus


class LogicValidator:
    def validate(self, program: ILRProgram) -> tuple[ValidationStatus, list[str]]:
        if not program.actions:
            return ValidationStatus.FAIL, ["ILR缺少动作"]
        if not program.conditions or program.conditions[0].get("expression") in ("", "true"):
            return ValidationStatus.UNCERTAIN, ["ILR缺少可验证前置条件"]
        return ValidationStatus.PASS, []
