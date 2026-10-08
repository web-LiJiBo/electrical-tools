"""AI4S质量基础设施：溯源、审计、拒答、监控和仿真。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from .domain import Decision, EvidenceRef


@dataclass(slots=True)
class AuditRecord:
    request_id: str
    service: str
    caller: str
    scenario: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    input_snapshot: dict[str, Any] = field(default_factory=dict)
    evidence: list[EvidenceRef] = field(default_factory=list)
    model_fingerprint: str = ""
    config_fingerprint: str = ""
    result_snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TrustAssessment:
    confidence: float
    citation_faithfulness: float
    evidence_complete: bool
    should_reject: bool
    reasons: list[str] = field(default_factory=list)


class TraceabilityService(Protocol):
    def trace_clause(self, clause_id: str, version: str | None = None) -> list[EvidenceRef]: ...
    def trace_decision(self, request_id: str) -> dict[str, Any]: ...


class TrustGate(Protocol):
    def assess(self, decision: Decision, evidence: list[EvidenceRef]) -> TrustAssessment: ...


class AuditStore(Protocol):
    def append(self, record: AuditRecord) -> None: ...
    def get(self, request_id: str) -> AuditRecord | None: ...


class ExecutionMonitor(Protocol):
    def start(self, instruction_id: str, expected: dict[str, Any]) -> str: ...
    def report(self, execution_id: str, state: dict[str, Any]) -> dict[str, Any]: ...


class DigitalTwinGateway(Protocol):
    def simulate(self, scenario: dict[str, Any], instructions: list[dict[str, Any]]) -> dict[str, Any]: ...

