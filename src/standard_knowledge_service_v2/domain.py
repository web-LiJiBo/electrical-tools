"""跨模块共享的领域对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DecisionStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNCERTAIN = "uncertain"
    NEEDS_HUMAN = "needs_human"


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    standard_id: str
    version: str
    clause_id: str
    chapter_path: str
    quote: str
    source_uri: str = ""
    support_status: str = "supported"


@dataclass(slots=True)
class Entity:
    entity_id: str
    name: str
    category: str
    normalized_name: str = ""
    aliases: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Constraint:
    parameter: str
    operator: str
    value: Any
    unit: str = ""
    condition: str = ""


@dataclass(slots=True)
class Rule:
    rule_id: str
    subject: str
    action: str
    condition: str
    constraints: list[Constraint] = field(default_factory=list)
    priority: int = 0
    evidence: list[EvidenceRef] = field(default_factory=list)
    # 分解JSON中的原始规则正文。结构化字段用于推理，content用于检索、引用和报告，
    # 两者不能互相替代，否则仅含正文的规则会在转换过程中丢失信息。
    content: str = ""


@dataclass(slots=True)
class ClauseKnowledgeUnit:
    clause_id: str
    standard_id: str
    version: str
    chapter_path: str
    text: str
    entities: list[Entity] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    source_uri: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScenarioContext:
    scenario: str
    device_type: str = ""
    voltage_level: str = ""
    operating_condition: str = ""
    operation_type: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    caller: str = ""


@dataclass(slots=True)
class Decision:
    status: DecisionStatus
    summary: str
    evidence: list[EvidenceRef] = field(default_factory=list)
    violations: list[dict[str, Any]] = field(default_factory=list)
    reasoning_paths: list[list[str]] = field(default_factory=list)
    confidence: float = 0.0
