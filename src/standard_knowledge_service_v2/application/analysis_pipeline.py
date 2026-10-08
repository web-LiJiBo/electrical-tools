"""端到端编排：分解→检索→语义/指令→验证→报告→审计。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..audit.models import AuditRecord
from ..audit.store import JsonlAuditStore
from ..contracts import AnalysisRequest, AnalysisResponse
from ..config import AppConfig, RetrievalSettings
from ..consistency_evaluation import ConsistencyEvaluationService
from ..decomposition.qwen_decomposer import LocalQwenDecomposer
from ..decomposition.intent_classifier import IntentClassifier
from ..hybrid_reasoning import HybridReasoningEngine, ReasoningStatus
from ..instruction_engine.instruction_generator import InstructionGenerationService
from ..instruction_engine.semantic_extractor import SemanticExtractor
from ..retrieval import LunwenMatchingInput
from ..retrieval_engine.evidence_builder import EvidenceBuilder
from ..retrieval_engine.lunwen_adapter import LocalLunwenRetrievalAdapter
from ..reporting.grounded_generator import GroundedReportGenerator
from ..scenarios.context_builder import ScenarioContextBuilder
from ..validation.applicability_validator import ApplicabilityValidator
from ..validation.clause_instruction_validator import ClauseInstructionValidator
from ..validation.logic_validator import LogicValidator
from ..validation.protocol_validator import ProtocolValidator
from ..validation.safety_gate import SafetyGate
from ..validation.semantic_validator import SemanticValidator
from ..validation.validation_models import ValidationStatus, ValidationSummary


class AnalysisPipeline:
    def __init__(
        self,
        retriever: LocalLunwenRetrievalAdapter,
        audit_store: JsonlAuditStore | None = None,
        config: AppConfig | None = None,
        decomposer: LocalQwenDecomposer | None = None,
        consistency: ConsistencyEvaluationService | None = None,
        reasoner: HybridReasoningEngine | None = None,
    ) -> None:
        self.config = config
        self.retrieval_settings = config.retrieval if config else RetrievalSettings()
        self.decomposer = decomposer or LocalQwenDecomposer()
        self.context_builder = ScenarioContextBuilder()
        self.intent_classifier = IntentClassifier()
        self.retriever = retriever
        self.extractor = SemanticExtractor()
        self.generator = InstructionGenerationService()
        self.applicability = ApplicabilityValidator()
        self.semantic_validator = SemanticValidator()
        self.clause_instruction_validator = ClauseInstructionValidator()
        self.protocol_validator = ProtocolValidator()
        self.logic_validator = LogicValidator()
        self.safety_gate = SafetyGate()
        self.report_generator = GroundedReportGenerator()
        self.consistency = consistency or ConsistencyEvaluationService()
        self.reasoner = reasoner or HybridReasoningEngine()
        self.audit_store = audit_store

    def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        decomposed = self.decomposer.decompose(request.query, request.scenario_hint, request.conversation_context)
        intent = self.intent_classifier.classify(request.query, decomposed.intent, decomposed.actions)
        decomposed.intent = intent.intent
        built = self.context_builder.build(decomposed, request.parameters, request.scenario_hint, request.meta.caller)
        settings = self.retrieval_settings
        parsed_query = decomposed.to_lunwen_parsed_json()
        if built.definition:
            parsed_query["scenario_topics"] = built.definition.standard_topics
            parsed_query["scenario_devices"] = built.definition.device_types
        parsed_query["context_device_type"] = built.context.device_type
        matched = self.retriever.match(LunwenMatchingInput(
            request.query,
            parsed_query,
            top_k_entities=settings.top_k_entities,
            top_k_rules=settings.top_k_rules,
            vector_weight=settings.vector_weight,
            structural_weight=settings.structural_weight,
        ))
        # 模型失败但兜底成功属于技术诊断，不应污染面向业务用户的风险提示。
        diagnostics = list(decomposed.errors)
        warnings = list(built.warnings)
        if not matched.rules:
            return self._respond(request, "uncertain", {"decomposition": decomposed.to_dict(), "intent_classification": intent.to_dict(), "context": asdict(built.context), "missing_fields": [asdict(item) for item in built.missing_fields], "diagnostics": diagnostics}, [], warnings + matched.warnings)
        selected, assessments = self._select_rule(request, matched.rules, decomposed.actions if intent.intent == "instruction" else [])
        if selected is None:
            data = {
                "decomposition": decomposed.to_dict(),
                "intent_classification": intent.to_dict(),
                "context": asdict(built.context),
                "candidate_assessments": assessments,
                "diagnostics": diagnostics,
            }
            reason = "未检索到与请求动作一致的标准条款" if intent.intent == "instruction" else "未检索到足够相关的标准条款"
            return self._respond(request, "uncertain", data, [], warnings + [reason])
        unit = self.retriever.repository.unit_for_rule(selected.rule.rule_id)
        if unit is None:
            return self._respond(request, "uncertain", {"decomposition": decomposed.to_dict()}, [], warnings + ["规则未能回溯至条款"])
        semantic = self.extractor.extract_rule(selected.rule, unit)
        device_config = dict(request.parameters.get("device_config", {}))
        # 页面表单将设备基础信息与协议配置分开填写；协议适配器需要统一视图。
        for key in ("device_id", "device_type", "operating_state"):
            if request.parameters.get(key) not in (None, "") and key not in device_config:
                device_config[key] = request.parameters[key]
        is_instruction_request = intent.intent == "instruction"
        candidate = self.generator.generate(semantic, built.context, device_config, request.target_protocol) if is_instruction_request else None
        program = self.generator.compiler.compile(semantic)
        static_parameters, dynamic_behaviors, constraint_rules = self.generator.compiler.framework.to_three_layers(semantic)
        app_status, app_errors = self.applicability.validate(unit, built.context)
        sem_status, sem_errors = self.semantic_validator.validate(semantic)
        logic_status, logic_errors = self.logic_validator.validate(program)
        if is_instruction_request:
            pair_status, pair_errors = self.clause_instruction_validator.validate(semantic, candidate)
            protocol_status, protocol_errors = self.protocol_validator.validate(candidate)
            summary = self.safety_gate.decide({"applicability": app_status, "semantic": sem_status, "clause_instruction": pair_status, "protocol": protocol_status, "logic": logic_status}, app_errors + sem_errors + pair_errors + protocol_errors + logic_errors, warnings)
        elif app_status is not ValidationStatus.FAIL and sem_status is ValidationStatus.PASS and logic_status is ValidationStatus.PASS:
            summary = ValidationSummary(ValidationStatus.ANSWERED, {"applicability": app_status, "semantic": sem_status, "logic": logic_status}, sem_errors + logic_errors, warnings, dispatch_allowed=False)
        else:
            summary = self.safety_gate.decide({"semantic": sem_status, "logic": logic_status}, sem_errors + logic_errors, warnings)
        evidence = [EvidenceBuilder().build(type("Hit", (), {"rule": selected.rule, "clause": unit})())]
        facts = {"context": asdict(built.context), "clauses": [asdict(item) for item in evidence], "instruction": asdict(candidate) if candidate else None, "validation": summary.to_dict(), "warnings": summary.warnings}
        report = self.report_generator.generate(facts)
        data = {
            "answer": {
                "text": f"根据检索到的标准条款：{selected.rule.content}" if not is_instruction_request else candidate.explanation,
                "conclusion": selected.rule.content,
                "source_rule_id": selected.rule.rule_id,
                "requires_human_confirmation": is_instruction_request,
            },
            "decomposition": decomposed.to_dict(),
            "intent_classification": intent.to_dict(),
            "context": asdict(built.context),
            "scenario_model": asdict(built.definition) if built.definition else None,
            "missing_fields": [asdict(item) for item in built.missing_fields],
            "diagnostics": diagnostics,
            "matching": {
                "entities": [asdict(item) for item in matched.matched_entities],
                "rules": [
                    {"rule_id": item.rule.rule_id, "rank": item.rank, "score": item.combined_score, "content": item.rule.content}
                    for item in matched.rules
                ],
            },
            "selected_rule": {
                "rule_id": selected.rule.rule_id,
                "content": selected.rule.content,
                "retrieval_rank": selected.rank,
            },
            "candidate_assessments": assessments,
            "semantic": asdict(semantic),
            "three_layer_semantics": {
                "static_parameters": [asdict(item) for item in static_parameters],
                "dynamic_behaviors": [asdict(item) for item in dynamic_behaviors],
                "constraint_rules": constraint_rules,
            },
            "if_then": self.generator.compiler.swrl.compile_if_then(semantic),
            "swrl": program.swrl_rules,
            "ilr": program.to_dict(),
            "candidate_instruction": asdict(candidate) if candidate else None,
            "validation": summary.to_dict(),
            "report": report.to_dict(),
        }
        return self._respond(request, summary.status.value, data, [asdict(item) for item in evidence], summary.warnings)

    def _select_rule(
        self,
        request: AnalysisRequest,
        matches: list[Any],
        requested_actions: list[str] | None = None,
    ) -> tuple[Any | None, list[dict[str, Any]]]:
        """对Top-K候选执行一致性评价与混合推理，再按配置权重选择最终条款。"""
        settings = self.retrieval_settings
        facts = dict(request.parameters)
        assessments: list[tuple[float, Any, dict[str, Any]]] = []
        action_set = {item for item in (requested_actions or []) if item}
        for match in matches[: settings.selection_top_k]:
            retrieval_score = float(match.combined_score or 0.0)
            content = match.rule.content or " ".join(filter(None, (match.rule.subject, match.rule.action, match.rule.condition)))
            consistency = self.consistency.compare(request.query, content)
            consistency_score = sum(
                value * weight
                for value, weight in zip(consistency.features.vector(), consistency.attention_weights)
            )
            conditions = [match.rule.condition] if match.rule.condition else []
            conditions.extend(str(item.value) for item in match.rule.constraints if str(item.value).strip())
            reasoning = self.reasoner.decide(conditions, facts, match.rule.subject, consistency)
            reasoning_score = {
                ReasoningStatus.PASS: 1.0,
                ReasoningStatus.UNCERTAIN: 0.5,
                ReasoningStatus.FAIL: 0.0,
            }[reasoning.status]
            total_weight = (
                settings.retrieval_selection_weight
                + settings.consistency_selection_weight
                + settings.reasoning_selection_weight
            )
            selection_score = (
                settings.retrieval_selection_weight * retrieval_score / (1.0 + 0.08 * (max(1, match.rank) - 1))
                + settings.consistency_selection_weight * consistency_score
                + settings.reasoning_selection_weight * reasoning_score
            ) / total_weight
            action_matches = not action_set or match.rule.action in action_set
            rejection_reasons: list[str] = []
            if retrieval_score < settings.minimum_rule_score:
                rejection_reasons.append("retrieval_score_below_minimum")
            if not action_matches:
                rejection_reasons.append("requested_action_mismatch")
            detail = {
                "rule_id": match.rule.rule_id,
                "content": content,
                "retrieval_rank": match.rank,
                "retrieval_score": retrieval_score,
                "consistency": consistency.to_dict(),
                "reasoning": reasoning.to_dict(),
                "selection_score": selection_score,
                "rule_action": match.rule.action,
                "requested_actions": sorted(action_set),
                "action_matches": action_matches,
                "eligible": not rejection_reasons,
                "rejection_reasons": rejection_reasons,
            }
            assessments.append((selection_score, match, detail))
        assessments.sort(key=lambda item: item[0], reverse=True)
        eligible = [item for item in assessments if item[2]["eligible"]]
        return (eligible[0][1] if eligible else None, [item[2] for item in assessments])

    def _respond(self, request: AnalysisRequest, status: str, data: dict, evidence: list[dict], warnings: list[str]) -> AnalysisResponse:
        response = AnalysisResponse(request.meta.request_id, status, data, evidence, warnings)
        if self.audit_store:
            scenario = str(data.get("context", {}).get("scenario", ""))
            self.audit_store.append(AuditRecord(request.meta.request_id, "analyze", asdict(request), response.to_dict(), scenario))
        return response
