"""lunwen论文代码和现有原型的防腐适配层大纲。"""

from __future__ import annotations

from typing import Any

from .domain import ClauseKnowledgeUnit, ScenarioContext
from .retrieval import (
    LLMDecompositionInput,
    LLMDecompositionOutput,
    LunwenMatchingInput,
    LunwenMatchingOutput,
)
from .llm_decomposition import QwenDecompositionConfig, QwenTextDecomposer


class ExistingLLMDecompositionAdapter:
    """兼容旧命名的本地Qwen在线查询分解适配器。"""

    def __init__(self, model_path: str | None = None) -> None:
        config = QwenDecompositionConfig()
        if model_path:
            from pathlib import Path

            config.model_path = Path(model_path)
        self._delegate = QwenTextDecomposer(config)

    def decompose(self, request: LLMDecompositionInput) -> LLMDecompositionOutput:
        return self._delegate.decompose(request)


class LunwenRetrievalAdapter:
    """论文检索主适配器。

    对接 `lunwen/evaluate_consistency.py` 中的实体加载、实体匹配、
    HAS_RULE查询、规则向量和结构化重排函数。
    """

    def __init__(self, dataset_dir: str | None = None, dataset_limit: int | None = None) -> None:
        self._delegate: Any | None = None
        self._dataset_dir = dataset_dir
        self._dataset_limit = dataset_limit

    def load(self, graph: Any = None, sbert: Any = None) -> None:
        """读取工具目录内复制的JSON；不运行或导入论文目录代码。"""
        from pathlib import Path
        from .retrieval_engine.lunwen_adapter import LocalLunwenRetrievalAdapter

        directory = Path(self._dataset_dir) if self._dataset_dir else Path(__file__).resolve().parents[2] / "datasets" / "lunwen" / "output_jsons_new" / "train"
        self._delegate = LocalLunwenRetrievalAdapter.from_dataset(directory, self._dataset_limit)

    def match(self, request: LunwenMatchingInput) -> LunwenMatchingOutput:
        if self._delegate is None:
            self.load()
        return self._delegate.match(request)


class ExistingTask3Adapter:
    """封装现有静态参数/FSM/约束/ILR/协议代码。"""

    def extract_executable_semantics(self, unit: ClauseKnowledgeUnit) -> Any:
        from .instruction_engine.semantic_extractor import SemanticExtractor
        from .instruction_engine.ilr_compiler import ILRCompiler

        semantics = SemanticExtractor().extract_unit(unit)
        return [ILRCompiler().compile(item) for item in semantics]


class ExistingTask4Adapter:
    """封装现有图谱、规则召回、一致性、推理、SKSM和审计代码。"""

    def __init__(self, dataset_dir: str | None = None) -> None:
        self.retriever = LunwenRetrievalAdapter(dataset_dir)

    def search_rules(self, text: str, top_k: int) -> list[Any]:
        output = self.retriever.match(LunwenMatchingInput(text, top_k_rules=top_k))
        return [item.rule for item in output.rules]

    def check_compliance(self, context: ScenarioContext) -> Any:
        from .hybrid_reasoning.hybrid_engine import HybridReasoningEngine

        conditions = list(context.parameters.get("conditions", []))
        return HybridReasoningEngine().decide(conditions, context.parameters)
