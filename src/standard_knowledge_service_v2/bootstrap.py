"""组合根：装配本地数据集、检索、主流程与审计。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Application:
    facade: Any
    registry: Any
    audit_store: Any


def build_application(config_path: str | Path) -> Application:
    """装配可离线运行的默认实现；可选模型和Neo4j均由各适配器延迟启用。"""
    from .application.analysis_pipeline import AnalysisPipeline
    from .audit.store import JsonlAuditStore
    from .config import load_config
    from .consistency_evaluation import ConsistencyEvaluationService
    from .decomposition.deepseek_decomposer import DeepSeekConfig, DeepSeekDecomposer
    from .decomposition.qwen_decomposer import LocalQwenDecomposer
    from .hybrid_reasoning import HybridReasoningEngine
    from .llm_decomposition import QwenDecompositionConfig
    from .retrieval_engine.lunwen_adapter import LocalLunwenRetrievalAdapter
    from .scenarios.registry import ScenarioRegistry

    project_root = Path(__file__).resolve().parents[2]
    config = load_config(config_path, project_root)
    dataset = config.data.verified_json if config.data.verified_json.is_dir() else config.data.redistributed_train
    if not dataset.is_dir():
        raise FileNotFoundError(f"配置的数据集目录不存在: {dataset}")
    retriever = LocalLunwenRetrievalAdapter.from_dataset(
        dataset, threshold=config.retrieval.entity_similarity_threshold
    )
    audit_store = JsonlAuditStore(config.data.audit_store)
    if config.llm.backend == "deepseek_api":
        decomposer = DeepSeekDecomposer(DeepSeekConfig(
            api_base=config.llm.api_base,
            model=config.llm.remote_model,
            api_key_env=config.llm.api_key_env,
            timeout_seconds=config.llm.timeout_seconds,
            temperature=config.llm.temperature,
            max_tokens=config.llm.max_new_tokens,
        ))
    elif config.llm.backend == "local_transformers":
        decomposer = LocalQwenDecomposer(QwenDecompositionConfig(
            model_path=config.models.llm,
            adapter_path=config.models.llm_adapter,
            temperature=config.llm.temperature,
            do_sample=config.llm.do_sample,
            max_new_tokens=config.llm.max_new_tokens,
            repetition_penalty=config.llm.repetition_penalty,
        ))
    else:
        raise ValueError(f"不支持的llm_decomposition.backend: {config.llm.backend}")
    consistency = ConsistencyEvaluationService(
        config.models.consistency_classifier,
        list(config.consistency.weights),
        config.consistency.threshold,
    )
    pipeline = AnalysisPipeline(retriever, audit_store, config, decomposer, consistency, HybridReasoningEngine())
    return Application(facade=pipeline, registry=ScenarioRegistry(), audit_store=audit_store)
