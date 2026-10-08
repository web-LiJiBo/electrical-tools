"""本地 Qwen 适配器；模型失败时回退到原文提取，保持后台链路可用。"""

from __future__ import annotations

from ..llm_decomposition import QwenDecompositionConfig, QwenTextDecomposer
from ..retrieval import LLMDecompositionInput
from .fallback import RawTextFallback
from .models import DecompositionResult, MissingField
from .normalizer import DomainTermNormalizer


class LocalQwenDecomposer:
    def __init__(self, config: QwenDecompositionConfig | None = None, fallback: RawTextFallback | None = None) -> None:
        self._decomposer = QwenTextDecomposer(config)
        self._fallback = fallback or RawTextFallback()
        self._normalizer = DomainTermNormalizer()

    def decompose(self, query: str, scenario_hint: str = "", conversation_context: list[dict[str, str]] | None = None) -> DecompositionResult:
        output = self._decomposer.decompose(LLMDecompositionInput(query, scenario_hint, conversation_context or []))
        if not output.valid:
            return self._normalizer.normalize(self._fallback.decompose(query, scenario_hint, output.errors))
        missing = []
        if not output.scenario.get("device_type"):
            missing.append(MissingField("device_type", "模型和原文均未明确设备类型", "场景匹配"))
        result = DecompositionResult(
            intent=output.intent, entities=output.entities, actions=output.actions, constraints=output.constraints,
            standard_refs=output.standard_refs, scenario=output.scenario, keywords=output.keywords,
            confidence=output.confidence, valid=True, source="local_qwen", errors=output.errors,
            missing_fields=missing, raw_output=output.raw_output,
        )
        return self._normalizer.normalize(result)
