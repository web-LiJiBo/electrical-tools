from __future__ import annotations

from .validation_models import ValidationStatus, ValidationSummary


class SafetyGate:
    """第一版固定禁用真实下发，即使所有验证通过也只返回待人工确认。"""

    def decide(self, checks: dict[str, ValidationStatus], errors: list[str] | None = None, warnings: list[str] | None = None) -> ValidationSummary:
        errors, warnings = list(errors or []), list(warnings or [])
        values = list(checks.values())
        if ValidationStatus.FAIL in values:
            status = ValidationStatus.FAIL
        elif ValidationStatus.UNCERTAIN in values:
            status = ValidationStatus.UNCERTAIN
        else:
            status = ValidationStatus.NEEDS_HUMAN
            warnings.append("第一版不允许自动设备下发，必须人工确认")
        return ValidationSummary(status, checks, errors, warnings, dispatch_allowed=False)
