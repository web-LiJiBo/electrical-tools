from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ValidationStatus(str, Enum):
    ANSWERED = "answered"
    PASS = "pass"
    FAIL = "fail"
    UNCERTAIN = "uncertain"
    NEEDS_HUMAN = "needs_human"


@dataclass(slots=True)
class ValidationSummary:
    status: ValidationStatus
    checks: dict[str, ValidationStatus] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    dispatch_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        result["checks"] = {key: value.value for key, value in self.checks.items()}
        return result
