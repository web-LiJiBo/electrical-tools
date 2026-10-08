from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ReasoningStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNCERTAIN = "uncertain"


@dataclass(slots=True)
class TraceStep:
    stage: str
    status: ReasoningStatus
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReasoningResult:
    status: ReasoningStatus
    confidence: float
    trace: list[TraceStep]
    graph_paths: list[list[str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
