from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from ..domain import EvidenceRef


@dataclass(slots=True)
class SemanticTuple:
    subject: str
    action: str
    target: str
    condition: str = ""
    constraints: list[dict[str, Any]] = field(default_factory=list)
    source_rule_id: str = ""
    evidence: list[EvidenceRef] = field(default_factory=list)


@dataclass(slots=True)
class StaticParameter:
    name: str
    value: Any
    unit: str = ""
    source: str = "clause"


@dataclass(slots=True)
class DynamicBehavior:
    trigger: str
    action: str
    target: str
    timeout_ms: int | None = None


@dataclass(slots=True)
class ILRProgram:
    program_id: str = field(default_factory=lambda: f"ilr-{uuid4().hex[:12]}")
    conditions: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    static_parameters: list[StaticParameter] = field(default_factory=list)
    dynamic_behaviors: list[DynamicBehavior] = field(default_factory=list)
    constraint_rules: list[dict[str, Any]] = field(default_factory=list)
    swrl_rules: list[str] = field(default_factory=list)
    source_rule_ids: list[str] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CandidateInstruction:
    instruction_id: str = field(default_factory=lambda: f"candidate-{uuid4().hex[:12]}")
    protocol: str = ""
    target: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    explanation: str = ""
    missing_fields: list[str] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)
    dispatch_allowed: bool = False
