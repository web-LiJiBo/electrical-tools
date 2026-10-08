"""在工具目录内复现论文的实体链接→规则召回→结构重排流程。"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from ..retrieval import LunwenMatchingInput, LunwenMatchingOutput, MatchedEntity, RuleMatch
from .clause_retriever import JsonClauseRepository
from .entity_linker import EntityLinker
from .models import RetrievalTrace, RuleHit
from .reranker import EvidenceReranker
from .text import structural_score, text_similarity


class LocalLunwenRetrievalAdapter:
    def __init__(self, repository: JsonClauseRepository, threshold: float = 0.3) -> None:
        self.repository = repository
        self.linker = EntityLinker(threshold)
        self.last_trace: RetrievalTrace | None = None

    @classmethod
    def from_dataset(cls, directory: Path, limit: int | None = None, threshold: float = 0.3) -> "LocalLunwenRetrievalAdapter":
        return cls(JsonClauseRepository.from_directory(directory, limit), threshold)

    def match(self, request: LunwenMatchingInput) -> LunwenMatchingOutput:
        extracted = [str(item.get("name", "")) for item in request.parsed_json.get("entities", []) if isinstance(item, dict) and item.get("name")]
        if not extracted:
            extracted = [request.clause_text]
        candidates = [entity for entity, _ in self.repository.all_entities()]
        linked = self.linker.link(extracted, candidates, request.top_k_entities) if request.use_entity_linking else []
        focus_terms = self._focus_terms(request.parsed_json)
        semantic_query = " ".join([request.clause_text, *focus_terms])
        device_entities = [
            str(item.get("name", ""))
            for item in request.parsed_json.get("entities", [])
            if isinstance(item, dict) and "设备" in str(item.get("type", ""))
        ]
        entity_terms = device_entities + [str(request.parsed_json.get("context_device_type", ""))]
        issue_terms = [
            term for term in focus_terms
            if not any(term in entity or entity in term for entity in entity_terms if entity)
        ]
        all_pairs = [(rule, unit) for unit in self.repository.units for rule in unit.rules]
        # 实体Top-K不能成为硬过滤器。并入全库文本候选，避免“温升异常”等故障特征
        # 被大量同名设备实体挤出候选集。
        # 当前核验库约1.2万条规则，可承受全库轻量重排。保留实体召回轨迹，
        # 但不再用Top-K实体裁掉语义相关条款。
        pairs = all_pairs
        hits: list[RuleHit] = []
        for rule, unit in pairs:
            # 原始规则正文是检索主文本；结构化字段只作为正文缺失时的兼容回退。
            rule_text = self._rule_text(rule)
            entity_score = max((item.score for item in linked if item.entity in unit.entities), default=0.0)
            unit_text = " ".join([rule_text, rule.subject, *(item.name for item in unit.entities)])
            direct_entity_score = max(
                (1.0 if name in unit_text else text_similarity(name, unit_text) for name in extracted),
                default=0.0,
            )
            entity_score = max(entity_score, direct_entity_score)
            device_type = str(request.parsed_json.get("context_device_type", "")).strip()
            if device_type:
                device_score = text_similarity(device_type, unit_text)
                if device_type in unit_text:
                    device_score = 1.0
                entity_score = 0.6 * entity_score + 0.4 * device_score
            content_score = (
                0.25 * text_similarity(request.clause_text, rule_text)
                + 0.15 * text_similarity(semantic_query, rule_text)
                + 0.60 * max((text_similarity(term, rule_text) for term in issue_terms), default=0.0)
            )
            requested_actions = {
                str(item).strip() for item in request.parsed_json.get("actions", []) if str(item).strip()
            }
            if requested_actions:
                action_score = 1.0 if rule.action in requested_actions else 0.0
                content_score = 0.65 * content_score + 0.35 * action_score
            hits.append(RuleHit(rule, unit, entity_score, content_score, structural_score(request.clause_text, rule_text), 0.0))
        ranked_all = EvidenceReranker(request.vector_weight, request.structural_weight).rank(hits)
        ranked: list[RuleHit] = []
        seen_content: set[str] = set()
        for item in ranked_all:
            key = " ".join((item.rule.content or "").split())
            if key and key in seen_content:
                continue
            if key:
                seen_content.add(key)
            ranked.append(item)
            if len(ranked) >= request.top_k_rules:
                break
        digest = sha256(f"{request.clause_text}|{request.top_k_entities}|{request.top_k_rules}|{len(self.repository.units)}".encode()).hexdigest()[:16]
        self.last_trace = RetrievalTrace(request.clause_text, linked, len(hits), len(ranked), parameters={"vector_weight": request.vector_weight, "structural_weight": request.structural_weight})
        return LunwenMatchingOutput(
            [MatchedEntity(item.entity.name, item.score) for item in linked],
            [RuleMatch(item.rule, rank=index + 1, vector_score=item.content_score, structural_score=item.structural_score, combined_score=item.score) for index, item in enumerate(ranked)],
            digest,
            [] if ranked else ["未召回规则"],
        )

    @staticmethod
    def _rule_text(rule) -> str:
        return rule.content or " ".join(
            [rule.subject, rule.action, rule.condition] + [str(item.value) for item in rule.constraints]
        )

    @staticmethod
    def _focus_terms(parsed: dict) -> list[str]:
        terms: list[str] = []
        terms.extend(str(item) for item in parsed.get("keywords", []) if str(item).strip())
        terms.extend(str(item) for item in parsed.get("actions", []) if str(item).strip())
        scenario = parsed.get("scenario", {})
        if isinstance(scenario, dict):
            terms.extend(str(value) for value in scenario.values() if str(value).strip())
        for item in parsed.get("constraints", []):
            if isinstance(item, dict):
                terms.extend(str(item.get(key, "")) for key in ("parameter", "value", "condition") if str(item.get(key, "")).strip())
        terms.extend(str(item) for item in parsed.get("scenario_topics", []) if str(item).strip())
        if str(parsed.get("context_device_type", "")).strip():
            terms.append(str(parsed["context_device_type"]))
        return list(dict.fromkeys(terms))
