from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class ErrorCategory(str, Enum):
    DECOMPOSITION = "decomposition"
    RETRIEVAL = "retrieval"
    CLASSIFICATION = "classification"
    INSTRUCTION = "instruction"
    REPORT = "report"
    OTHER = "other"


@dataclass(slots=True)
class FeedbackRecord:
    request_id: str
    accepted: bool
    rating: int
    category: ErrorCategory = ErrorCategory.OTHER
    correction: dict[str, Any] = field(default_factory=dict)
    scenario: str = ""
    model_version: str = ""
    latency_ms: float | None = None
    record_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["category"] = self.category.value
        return data


@dataclass(slots=True)
class OptimizationProposal:
    kind: str
    reason: str
    parameters: dict[str, Any]
    evidence_count: int
    requires_approval: bool = True
