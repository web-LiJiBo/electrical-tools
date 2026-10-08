"""应用编排：把检索、推理、指令和质量门禁组合为场景服务。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .consistency import ConsistencyOutcome
from .domain import Decision, EvidenceRef, ScenarioContext
from .instructions import InstructionCandidate, InstructionValidation
from .retrieval import LLMDecompositionOutput, LunwenMatchingOutput, RetrievalResult


@dataclass(slots=True)
class KnowledgeServiceResult:
    request_id: str
    status: str
    decomposition: LLMDecompositionOutput | None = None
    rule_matching: LunwenMatchingOutput | None = None
    retrieval: RetrievalResult | None = None
    decision: Decision | None = None
    consistency: ConsistencyOutcome | None = None
    instruction: InstructionCandidate | None = None
    instruction_validation: InstructionValidation | None = None
    evidence: list[EvidenceRef] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    audit_id: str = ""


class ScenarioAdapter(Protocol):
    scenario_name: str

    def normalize_context(self, raw_input: dict[str, Any]) -> ScenarioContext: ...
    def required_parameters(self) -> list[str]: ...
    def scenario_weights(self) -> dict[str, float]: ...


class SearchService(Protocol):
    def search(self, query: str, context: ScenarioContext, top_k: int = 10) -> KnowledgeServiceResult: ...


class DecomposeAndMatchService(Protocol):
    """固定顺序：大模型分解→校验/归一化→论文规则检索→证据补全。"""

    def execute(self, request_id: str, query: str, context: ScenarioContext) -> KnowledgeServiceResult: ...


class ComplianceService(Protocol):
    def check(self, context: ScenarioContext, standard_refs: list[str]) -> KnowledgeServiceResult: ...


class DifferenceService(Protocol):
    def compare_versions(self, standard_id: str, version_a: str, version_b: str) -> KnowledgeServiceResult: ...


class KnowledgeServiceFacade(Protocol):
    """最终工具统一门面：检索、一致性、合规、差异、候选指令。"""

    def search(self, request_id: str, query: str, context: ScenarioContext, top_k: int) -> KnowledgeServiceResult: ...
    def consistency(self, request_id: str, clause_a: str, clause_b: str) -> KnowledgeServiceResult: ...
    def compliance(self, request_id: str, context: ScenarioContext, standard_refs: list[str]) -> KnowledgeServiceResult: ...
    def difference(self, request_id: str, standard_id: str, version_a: str, version_b: str) -> KnowledgeServiceResult: ...
    def generate_instruction(self, request_id: str, clause_id: str, context: ScenarioContext) -> KnowledgeServiceResult: ...


class SKSMRegistry(Protocol):
    def register(self, module_id: str, adapter: ScenarioAdapter) -> None: ...
    def resolve(self, scenario: str) -> ScenarioAdapter: ...
