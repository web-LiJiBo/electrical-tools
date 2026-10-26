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
    from .retrieval_engine.clause_retriever import JsonClauseRepository
    from .scenarios.registry import ScenarioRegistry

    def progress(message: str) -> None:
        print(f"[启动进度] {message}", flush=True)

    def report_repository(label: str, repository: JsonClauseRepository) -> None:
        report = repository.load_report
        progress(
            f"{label}加载完成：成功 {report['loaded']} 个，"
            f"跳过 {report['skipped']} 个，共检查 {report['files_seen']} 个JSON文件"
        )
        for item in report["error_samples"]:
            progress(
                f"{label}跳过文件：{item['path']} "
                f"[{item['error']}] {item['message']}"
            )

    project_root = Path(__file__).resolve().parents[2]
    progress("正在读取项目配置")
    config = load_config(config_path, project_root)
    dataset = config.data.verified_json if config.data.verified_json.is_dir() else config.data.redistributed_train
    if not dataset.is_dir():
        raise FileNotFoundError(f"配置的数据集目录不存在: {dataset}")
    progress("正在加载已核验标准条款")
    retriever = LocalLunwenRetrievalAdapter.from_dataset(
        dataset, threshold=config.retrieval.entity_similarity_threshold
    )
    report_repository("已核验条款", retriever.repository)
    if config.data.supplemental_json is not None:
        if not config.data.supplemental_json.is_dir():
            raise FileNotFoundError(f"配置的补充条款目录不存在: {config.data.supplemental_json}")
        progress("正在加载补充条款；文件较多，请耐心等待")
        supplemental = JsonClauseRepository.from_directory(config.data.supplemental_json)
        report_repository("补充条款", supplemental)
        existing_ids = {unit.clause_id for unit in retriever.repository.units}
        if any(unit.clause_id in existing_ids for unit in supplemental.units):
            raise ValueError("原库和补充库的条款内部标识发生冲突")
        retriever.repository.units.extend(supplemental.units)
    progress(f"条款加载完成，共 {len(retriever.repository.units)} 条")
    audit_store = JsonlAuditStore(config.data.audit_store, config.audit.retention_days)
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
    progress("正在初始化一致性评价、场景识别和指令校验组件")
    consistency = ConsistencyEvaluationService(
        config.models.consistency_classifier,
        list(config.consistency.weights),
        config.consistency.threshold,
    )
    from .knowledge_graph.current_graph import CurrentKnowledgeGraph
    from .hybrid_reasoning.semantic_reasoner import SemanticReasoner
    progress("正在构建内存知识图谱")
    graph = CurrentKnowledgeGraph(retriever.repository.units)
    progress("内存知识图谱构建完成")
    pipeline = AnalysisPipeline(retriever, audit_store, config, decomposer, consistency,
                                HybridReasoningEngine(semantic_reasoner=SemanticReasoner(graph)))
    pipeline.knowledge_graph = graph
    from .application.grounded_advice import GroundedAdviceService
    pipeline.advisor = GroundedAdviceService(decomposer if config.advice_enabled else None)
    progress("后台组件初始化完成，正在启动HTTP服务")
    return Application(facade=pipeline, registry=ScenarioRegistry(), audit_store=audit_store)
