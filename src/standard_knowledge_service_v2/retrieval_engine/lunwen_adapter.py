"""在工具目录内复现论文的实体链接→规则召回→结构重排流程。"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re
from time import perf_counter

from ..retrieval import LunwenMatchingInput, LunwenMatchingOutput, MatchedEntity, RuleMatch
from .clause_retriever import JsonClauseRepository
from .entity_linker import EntityLinker
from .models import RetrievalTrace, RuleHit
from .reranker import EvidenceReranker
from .text import normalize, prepared_similarity, structural_score, text_similarity, tokens


class LocalLunwenRetrievalAdapter:
    def __init__(self, repository: JsonClauseRepository, threshold: float = 0.3) -> None:
        self.repository = repository
        self.linker = EntityLinker(threshold)
        self.last_trace: RetrievalTrace | None = None
        self._entities = []
        self._rows = []
        self.refresh_index()

    def refresh_index(self) -> None:
        """Rebuild immutable query features after repositories are combined."""
        self._entities = [entity for entity, _ in self.repository.all_entities()]
        self.linker = EntityLinker(self.linker.threshold)
        self.linker.prepare(self._entities)
        # Query-time retrieval used to normalize/tokenize every clause several
        # times. Build immutable lexical features once when the repository is
        # assembled; this changes no score formula and avoids repeated local work.
        self._rows = []
        for unit in self.repository.units:
            for rule in unit.rules:
                if self._navigation_only(rule, unit):
                    continue
                rule_text = self._rule_text(rule)
                unit_text = " ".join([rule_text, rule.subject, *(item.name for item in unit.entities)])
                rule_normalized, unit_normalized = normalize(rule_text), normalize(unit_text)
                self._rows.append((rule, unit, rule_text, rule_normalized, tokens(rule_normalized),
                                   unit_text, unit_normalized, tokens(unit_normalized)))

    @classmethod
    def from_dataset(cls, directory: Path, limit: int | None = None, threshold: float = 0.3) -> "LocalLunwenRetrievalAdapter":
        return cls(JsonClauseRepository.from_directory(directory, limit), threshold)

    def match(self, request: LunwenMatchingInput) -> LunwenMatchingOutput:
        started = perf_counter()
        extracted = [str(item.get("name", "")) for item in request.parsed_json.get("entities", []) if isinstance(item, dict) and item.get("name")]
        if not extracted:
            extracted = [request.clause_text]
        linked = self.linker.link(extracted, self._entities, request.top_k_entities) if request.use_entity_linking else []
        linked_at = perf_counter()
        focus_terms = self._focus_terms(request.parsed_json)
        if request.parsed_json.get("intent") in {"search", "compliance", "difference", "consistency"}:
            action_codes = {str(value).lower() for value in request.parsed_json.get("actions", [])}
            # An inferred "inspect" must not become a literal match for an
            # unrelated English term such as "inspection" in the source text.
            focus_terms = [term for term in focus_terms
                           if term.lower() not in action_codes or term.lower() in request.clause_text.lower()]
        scope_query = request.parsed_json.get("intent") != "instruction" and bool(
            re.search(r"适用范围|适用对象|适用于(?:哪些|什么|何种|哪类|何类)", request.clause_text)
        )
        if scope_query:
            focus_terms.append("适用")
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
        standard_filter = str(request.parsed_json.get("requested_standard_id", "")).strip()
        chapter_filter = str(request.parsed_json.get("requested_chapter_path", "")).strip()
        version_filter = str(request.parsed_json.get("requested_version", "")).strip()
        rows = [row for row in self._rows
                if (not standard_filter or row[1].standard_id == standard_filter)
                and (not chapter_filter or row[1].chapter_path == chapter_filter)
                and (not version_filter or self._version_matches(row[1], version_filter))]
        # 实体Top-K不能成为硬过滤器。并入全库文本候选，避免“温升异常”等故障特征
        # 被大量同名设备实体挤出候选集。
        # 当前核验库约1.2万条规则，可承受全库轻量重排。保留实体召回轨迹，
        # 但不再用Top-K实体裁掉语义相关条款。
        hits: list[RuleHit] = []
        query_normalized = normalize(request.clause_text)
        query_tokens = tokens(query_normalized)
        semantic_normalized = normalize(semantic_query)
        semantic_tokens = tokens(semantic_normalized)
        prepared_terms = [(normalize(term), tokens(normalize(term))) for term in issue_terms if normalize(term)]
        prepared_extracted = [(normalize(name), tokens(normalize(name))) for name in extracted if normalize(name)]
        device_type = str(request.parsed_json.get("context_device_type", "")).strip()
        device_prepared = (normalize(device_type), tokens(normalize(device_type))) if device_type else None
        requested_actions = {
            str(item).strip() for item in request.parsed_json.get("actions", []) if str(item).strip()
        }
        for rule, unit, rule_text, rule_normalized, rule_tokens, unit_text, unit_normalized, unit_tokens in rows:
            # A bare term name cannot answer which work a standard applies to.
            # Require scope wording in the source, rather than infer it from metadata.
            if scope_query and not re.search(r"适用于|适用范围|适用对象", normalize(rule_text)):
                continue
            entity_score = max((item.score for item in linked if item.entity in unit.entities), default=0.0)
            unit_text = " ".join([rule_text, rule.subject, *(item.name for item in unit.entities)])
            direct_entity_score = max(
                (1.0 if name in unit_normalized else prepared_similarity(name, name_tokens, unit_normalized, unit_tokens)
                 for name, name_tokens in prepared_extracted),
                default=0.0,
            )
            entity_score = max(entity_score, direct_entity_score)
            if device_prepared:
                device_name, device_tokens = device_prepared
                device_score = prepared_similarity(device_name, device_tokens, unit_normalized, unit_tokens)
                if device_name in unit_normalized:
                    device_score = 1.0
                entity_score = 0.6 * entity_score + 0.4 * device_score
            content_score = (
                0.25 * prepared_similarity(query_normalized, query_tokens, rule_normalized, rule_tokens)
                + 0.15 * prepared_similarity(semantic_normalized, semantic_tokens, rule_normalized, rule_tokens)
                # Explicit parameter/topic phrase presence is strong evidence;
                # dividing a short phrase by the entire clause length otherwise
                # ranks unrelated short clauses above the full source sentence.
                + 0.60 * max((1.0 if len(term) >= 2 and term in rule_normalized
                              else prepared_similarity(term, term_tokens, rule_normalized, rule_tokens)
                              for term, term_tokens in prepared_terms), default=0.0)
            )
            # Knowledge questions can mention operations without requiring a
            # device action field. Keep legacy direct callers and instruction
            # retrieval compatible, while treating both libraries equally for queries.
            if requested_actions and request.parsed_json.get("intent", "instruction") == "instruction":
                action_score = 1.0 if rule.action in requested_actions else 0.0
                content_score = 0.65 * content_score + 0.35 * action_score
            hits.append(RuleHit(rule, unit, entity_score, content_score, structural_score(request.clause_text, rule_text), 0.0))
        scored_at = perf_counter()
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
        finished = perf_counter()
        self.last_trace = RetrievalTrace(request.clause_text, linked, len(hits), len(ranked), parameters={
            "vector_weight": request.vector_weight, "structural_weight": request.structural_weight,
            "timing_ms": {"entity_linking": round((linked_at - started) * 1000, 2),
                          "filter_and_score": round((scored_at - linked_at) * 1000, 2),
                          "rank_and_deduplicate": round((finished - scored_at) * 1000, 2),
                          "total": round((finished - started) * 1000, 2)},
            "indexed_rules": len(self._rows), "scored_rules": len(rows)})
        return LunwenMatchingOutput(
            [MatchedEntity(item.entity.name, item.score) for item in linked],
            [RuleMatch(item.rule, rank=index + 1, vector_score=item.content_score, structural_score=item.structural_score, combined_score=item.score) for index, item in enumerate(ranked)],
            digest,
            [] if ranked else ([f"未找到版本 {version_filter} 的匹配条款"] if version_filter else ["未召回规则"]),
        )

    @staticmethod
    def _navigation_only(rule, unit) -> bool:
        if ("标题" in rule.operation and "仅" in rule.operation
                or rule.operation == "清单缺失"
                or rule.operation.startswith("保留原始") and "数值" in rule.operation):
            return True
        if unit.metadata.get("classification") == "heading":
            return True
        reasons = unit.metadata.get("audit", {}).get("reasons", [])
        return any(re.search(r"(?:^|[；;])\s*仅(?:为)?标题(?:[，,。；;]|$)", str(reason)) for reason in reasons)

    @staticmethod
    def _version_matches(unit, requested: str) -> bool:
        """Apply an exact year/version filter across heterogeneous source fields."""
        requested_text = re.sub(r"\s+", "", str(requested)).lower()
        requested_years = re.findall(r"(?:19|20)\d{2}", requested_text)
        candidates = [
            str(getattr(unit, "version", "")),
            str(getattr(unit, "standard_id", "")),
            str(getattr(unit, "standard_name", "")),
        ]
        if requested_years:
            expected = requested_years[-1]
            return any(expected in re.findall(r"(?:19|20)\d{2}", value) for value in candidates)
        return any(requested_text == re.sub(r"\s+", "", value).lower() for value in candidates if value)

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
