from __future__ import annotations

from .validation_models import ValidationStatus, ValidationSummary


class SafetyGate:
    """生成前校验；所有验证通过后仅返回生成结果。"""

    def decide(self, checks: dict[str, ValidationStatus], errors: list[str] | None = None, warnings: list[str] | None = None) -> ValidationSummary:
        errors, warnings = list(errors or []), list(warnings or [])
        values = list(checks.values())
        if ValidationStatus.FAIL in values:
            status = ValidationStatus.FAIL
        elif ValidationStatus.UNCERTAIN in values:
            status = ValidationStatus.UNCERTAIN
        else:
            status = ValidationStatus.GENERATED
        return ValidationSummary(status, checks, errors, warnings, dispatch_allowed=False)
