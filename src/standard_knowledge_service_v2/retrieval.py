"""混合检索、实体链接、结构化重排和证据支持状态。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .domain import ClauseKnowledgeUnit, EvidenceRef, Rule, ScenarioContext


@dataclass(slots=True)
class LLMDecompositionInput:
    """在线查询大模型分解输入。"""

    query_text: str
    scenario_hint: str = ""
    conversation_context: list[dict[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class LLMDecompositionOutput:
    """严格JSON Schema校验后的分解结果。"""

    intent: str
    entities: list[dict[str, str]] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    constraints: list[dict[str, Any]] = field(default_factory=list)
    standard_refs: list[dict[str, str]] = field(default_factory=list)
    scenario: dict[str, Any] = field(default_factory=dict)
    keywords: list[str] = field(default_factory=list)
    confidence: float = 0.0
    valid: bool = False
    errors: list[str] = field(default_factory=list)
    raw_output: str = ""

    def to_lunwen_parsed_json(self) -> dict[str, Any]:
        return {
            "entities": self.entities, "actions": self.actions, "constraints": self.constraints,
            "standard_refs": self.standard_refs, "scenario": self.scenario, "keywords": self.keywords,
            "rules": [], "relations": [],
        }


@dataclass(slots=True)
class StructuredQuery:
    raw_query: str
    intent: str = "search"
    standard_ids: list[str] = field(default_factory=list)
    versions: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    voltage_levels: list[str] = field(default_factory=list)
    constraints: list[dict[str, Any]] = field(default_factory=list)
    scenario: ScenarioContext | None = None


@dataclass(slots=True)
class Candidate:
    unit: ClauseKnowledgeUnit
    sparse_score: float = 0.0
    dense_score: float = 0.0
    structure_score: float = 0.0
    graph_score: float = 0.0
    final_score: float = 0.0


@dataclass(slots=True)
class RetrievalResult:
    candidates: list[Candidate]
    rules: list[Rule] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)
    query_fingerprint: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LunwenMatchingInput:
    """论文检索函数的稳定业务输入；模型、图谱和缓存不属于请求字段。"""

    clause_text: str
    parsed_json: dict[str, Any] = field(default_factory=dict)
    use_entity_linking: bool = True
    top_k_entities: int = 26
    top_k_rules: int = 22
    use_rule_content_sim: bool = True
    vector_weight: float = 0.8
    structural_weight: float = 0.2


@dataclass(slots=True)
class MatchedEntity:
    name: str
    similarity: float


@dataclass(slots=True)
class RuleMatch:
    rule: Rule
    rank: int
    vector_score: float | None = None
    structural_score: float | None = None
    combined_score: float | None = None


@dataclass(slots=True)
class LunwenMatchingOutput:
    matched_entities: list[MatchedEntity]
    rules: list[RuleMatch]
    retrieval_fingerprint: str
    warnings: list[str] = field(default_factory=list)


class QueryUnderstanding(Protocol):
    def parse(self, query: str, scenario: ScenarioContext | None = None) -> StructuredQuery: ...


class LLMQueryDecomposer(Protocol):
    """大模型分解后必须先校验，失败时由编排层回退到原文检索。"""

    def decompose(self, request: LLMDecompositionInput) -> LLMDecompositionOutput: ...


class SparseRetriever(Protocol):
    def search(self, query: StructuredQuery, top_k: int) -> list[Candidate]: ...


class DenseRetriever(Protocol):
    def search(self, query: StructuredQuery, top_k: int) -> list[Candidate]: ...


class HybridRetriever(Protocol):
    def retrieve(self, query: StructuredQuery, candidate_top_k: int, output_top_k: int) -> RetrievalResult: ...


class EntityRuleRetriever(Protocol):
    def retrieve_rules(self, text: str, extracted_entities: list[str], top_k: int) -> list[Rule]: ...


class LunwenRuleRetriever(Protocol):
    """SBERT实体链接→HAS_RULE遍历→向量和结构分数重排。"""

    def match(self, request: LunwenMatchingInput) -> LunwenMatchingOutput: ...


class EvidenceReranker(Protocol):
    """结构化特征至少含标准号、版本、实体、章节、数值和表格行匹配。"""

    def rerank(self, query: StructuredQuery, candidates: list[Candidate]) -> list[Candidate]: ...


class CitationVerifier(Protocol):
    def verify(self, answer: str, evidence: list[EvidenceRef]) -> tuple[float, list[str]]: ...
