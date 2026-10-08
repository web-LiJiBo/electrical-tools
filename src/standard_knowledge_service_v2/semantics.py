"""四层机器可读表达、三层可执行语义及质量校验契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .domain import ClauseKnowledgeUnit, Constraint, Rule


@dataclass(slots=True)
class MachineReadableLayers:
    basic_elements: dict[str, Any] = field(default_factory=dict)
    characteristic_elements: dict[str, Any] = field(default_factory=dict)
    procedural_elements: list[dict[str, Any]] = field(default_factory=list)
    auxiliary_elements: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExecutableSemantics:
    static_parameters: list[dict[str, Any]] = field(default_factory=list)
    dynamic_behaviors: list[dict[str, Any]] = field(default_factory=list)
    constraint_rules: list[Constraint] = field(default_factory=list)


@dataclass(slots=True)
class SemanticValidationReport:
    valid: bool
    completeness: float
    accuracy: float | None = None
    consistency: float = 0.0
    conflicts: list[str] = field(default_factory=list)
    redundancies: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class SemanticMapper(Protocol):
    def build_readable_layers(self, unit: ClauseKnowledgeUnit) -> MachineReadableLayers: ...
    def build_executable_semantics(self, unit: ClauseKnowledgeUnit) -> ExecutableSemantics: ...


class SemanticValidator(Protocol):
    def validate_unit(self, unit: ClauseKnowledgeUnit) -> SemanticValidationReport: ...
    def validate_cross_clause_rules(self, rules: list[Rule]) -> SemanticValidationReport: ...

