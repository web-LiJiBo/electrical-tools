from __future__ import annotations

from ..instruction_engine.models import SemanticTuple
from .validation_models import ValidationStatus


class SemanticValidator:
    def validate(self, semantic: SemanticTuple) -> tuple[ValidationStatus, list[str]]:
        missing = [name for name, value in (("subject", semantic.subject), ("action", semantic.action), ("target", semantic.target)) if not value]
        if missing:
            return ValidationStatus.FAIL, [f"语义字段缺失: {', '.join(missing)}"]
        return ValidationStatus.PASS, []
