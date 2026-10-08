"""第5章：ILR、指令模板、协议适配和三层验证。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .domain import EvidenceRef
from .semantics import ExecutableSemantics


@dataclass(slots=True)
class ILRProgram:
    program_id: str
    variables: dict[str, str]
    statements: list[dict[str, Any]]
    source_evidence: list[EvidenceRef]


@dataclass(slots=True)
class InstructionCandidate:
    instruction_id: str
    protocol: str
    target: str
    payload: dict[str, Any]
    template_version: str
    evidence: list[EvidenceRef]
    dispatch_allowed: bool = False


@dataclass(slots=True)
class InstructionValidation:
    semantic_valid: bool
    protocol_valid: bool
    logic_valid: bool
    requires_human_confirmation: bool = True
    errors: list[str] = field(default_factory=list)
    simulation_report_id: str = ""


class ILRCompiler(Protocol):
    def compile(self, semantics: ExecutableSemantics) -> ILRProgram: ...


class InstructionTemplateRepository(Protocol):
    def find(self, scenario: str, function_type: str, device_type: str) -> list[dict[str, Any]]: ...


class ProtocolAdapter(Protocol):
    protocol_name: str

    def generate(self, program: ILRProgram, device_config: dict[str, Any]) -> InstructionCandidate: ...
    def validate_format(self, instruction: InstructionCandidate) -> list[str]: ...


class InstructionValidator(Protocol):
    def validate(self, program: ILRProgram, instruction: InstructionCandidate) -> InstructionValidation: ...


class InstructionGenerationService(Protocol):
    def generate_candidate(
        self,
        semantics: ExecutableSemantics,
        scenario: str,
        device_config: dict[str, Any],
    ) -> tuple[InstructionCandidate, InstructionValidation]: ...

