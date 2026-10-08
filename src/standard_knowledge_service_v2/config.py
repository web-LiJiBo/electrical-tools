"""统一、可校验的运行配置加载器。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class ModelPaths:
    llm: Path
    llm_adapter: Path | None
    embedding: Path
    embedding_baseline: Path
    consistency_classifier: Path
    consistency_classifier_candidates: dict[str, Path]
    manifests: Path


@dataclass(frozen=True, slots=True)
class DataPaths:
    source_excel: Path
    original_train: Path
    original_test: Path
    verified_json: Path
    redistributed_train: Path
    redistributed_test: Path
    correction_mapping: Path
    graph_build_source: Path
    graph_build_summary: Path
    feedback_store: Path
    optimization_proposals: Path
    audit_store: Path


@dataclass(frozen=True, slots=True)
class RetrievalSettings:
    entity_similarity_threshold: float = 0.3
    top_k_entities: int = 26
    top_k_rules: int = 22
    vector_weight: float = 0.8
    structural_weight: float = 0.2
    selection_top_k: int = 5
    minimum_rule_score: float = 0.0
    retrieval_selection_weight: float = 0.65
    consistency_selection_weight: float = 0.25
    reasoning_selection_weight: float = 0.10


@dataclass(frozen=True, slots=True)
class LLMSettings:
    backend: str = "local_transformers"
    remote_model: str = "deepseek-chat"
    api_base: str = "https://api.deepseek.com"
    api_key_env: str = "DEEPSEEK_API_KEY"
    timeout_seconds: float = 30.0
    temperature: float = 0.1
    do_sample: bool = False
    max_new_tokens: int = 1024
    repetition_penalty: float = 1.05


@dataclass(frozen=True, slots=True)
class ConsistencySettings:
    threshold: float = 0.62
    weights: tuple[float, ...] = (0.30, 0.35, 0.20, 0.15)


@dataclass(frozen=True, slots=True)
class AppConfig:
    project_root: Path
    source_path: Path
    models: ModelPaths
    data: DataPaths
    retrieval: RetrievalSettings
    llm: LLMSettings
    consistency: ConsistencySettings


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"配置项{name}必须是对象")
    return value


def _path(root: Path, value: Any, name: str) -> Path:
    if not str(value or "").strip():
        raise ValueError(f"配置项{name}不能为空")
    candidate = Path(str(value))
    return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()


def _optional_path(root: Path, value: Any) -> Path | None:
    if not str(value or "").strip():
        return None
    candidate = Path(str(value))
    return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()


def _number(section: dict[str, Any], key: str, default: float, minimum: float = 0.0) -> float:
    value = float(section.get(key, default))
    if value < minimum:
        raise ValueError(f"配置项{key}不得小于{minimum}")
    return value


def _positive_int(section: dict[str, Any], key: str, default: int) -> int:
    value = int(section.get(key, default))
    if value <= 0:
        raise ValueError(f"配置项{key}必须大于0")
    return value


def load_config(config_path: str | Path, project_root: str | Path | None = None) -> AppConfig:
    """读取YAML并将所有相对路径统一解析到工具项目根目录。"""
    source = Path(config_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"配置文件不存在: {source}")
    payload = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("配置文件顶层必须是对象")

    root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[2]
    model = _mapping(payload.get("model_paths"), "model_paths")
    dataset = _mapping(payload.get("dataset_paths"), "dataset_paths")
    retrieval = _mapping(payload.get("retrieval"), "retrieval")
    llm = _mapping(payload.get("llm_decomposition"), "llm_decomposition")
    consistency = _mapping(payload.get("consistency"), "consistency")
    audit = _mapping(payload.get("audit"), "audit")
    knowledge = _mapping(payload.get("knowledge"), "knowledge")
    feedback = _mapping(payload.get("feedback"), "feedback")
    original = _mapping(dataset.get("decomposed_json_original"), "dataset_paths.decomposed_json_original")
    redistributed = _mapping(dataset.get("decomposed_json_redistributed"), "dataset_paths.decomposed_json_redistributed")
    classifier_candidates = _mapping(model.get("consistency_classifier_candidates"), "model_paths.consistency_classifier_candidates")

    vector_weight = _number(retrieval, "vector_weight", 0.8)
    structural_weight = _number(retrieval, "structural_weight", 0.2)
    if vector_weight + structural_weight <= 0:
        raise ValueError("vector_weight与structural_weight不能同时为0")
    selection_weights = [
        _number(retrieval, "retrieval_selection_weight", 0.65),
        _number(retrieval, "consistency_selection_weight", 0.25),
        _number(retrieval, "reasoning_selection_weight", 0.10),
    ]
    if sum(selection_weights) <= 0:
        raise ValueError("候选选择权重不能全部为0")

    raw_consistency_weights = consistency.get("fallback_weights", [0.30, 0.35, 0.20, 0.15])
    if not isinstance(raw_consistency_weights, list) or len(raw_consistency_weights) != 4:
        raise ValueError("consistency.fallback_weights必须包含4个数值")

    return AppConfig(
        project_root=root,
        source_path=source,
        models=ModelPaths(
            llm=_path(root, model.get("llm"), "model_paths.llm"),
            llm_adapter=_optional_path(root, model.get("llm_adapter")),
            embedding=_path(root, model.get("embedding"), "model_paths.embedding"),
            embedding_baseline=_path(root, model.get("embedding_baseline"), "model_paths.embedding_baseline"),
            consistency_classifier=_path(root, model.get("consistency_classifier"), "model_paths.consistency_classifier"),
            consistency_classifier_candidates={
                str(name): _path(root, value, f"model_paths.consistency_classifier_candidates.{name}")
                for name, value in classifier_candidates.items()
            },
            manifests=_path(root, model.get("manifests"), "model_paths.manifests"),
        ),
        data=DataPaths(
            source_excel=_path(root, dataset.get("source_excel"), "dataset_paths.source_excel"),
            original_train=_path(root, original.get("train"), "dataset_paths.decomposed_json_original.train"),
            original_test=_path(root, original.get("test"), "dataset_paths.decomposed_json_original.test"),
            verified_json=_path(root, dataset.get("decomposed_json_verified"), "dataset_paths.decomposed_json_verified"),
            redistributed_train=_path(root, redistributed.get("train"), "dataset_paths.decomposed_json_redistributed.train"),
            redistributed_test=_path(root, redistributed.get("test"), "dataset_paths.decomposed_json_redistributed.test"),
            correction_mapping=_path(root, dataset.get("correction_mapping"), "dataset_paths.correction_mapping"),
            graph_build_source=_path(root, knowledge.get("json_build_source"), "knowledge.json_build_source"),
            graph_build_summary=_path(root, knowledge.get("build_summary"), "knowledge.build_summary"),
            feedback_store=_path(root, feedback.get("store"), "feedback.store"),
            optimization_proposals=_path(root, feedback.get("proposal_output"), "feedback.proposal_output"),
            audit_store=_path(root, audit.get("store", "data/audit/audit.jsonl"), "audit.store"),
        ),
        retrieval=RetrievalSettings(
            entity_similarity_threshold=_number(retrieval, "entity_similarity_threshold", 0.3),
            top_k_entities=_positive_int(retrieval, "top_k_entities", 26),
            top_k_rules=_positive_int(retrieval, "top_k_rules", 22),
            vector_weight=vector_weight,
            structural_weight=structural_weight,
            selection_top_k=_positive_int(retrieval, "selection_top_k", 5),
            minimum_rule_score=_number(retrieval, "minimum_rule_score", 0.0),
            retrieval_selection_weight=selection_weights[0],
            consistency_selection_weight=selection_weights[1],
            reasoning_selection_weight=selection_weights[2],
        ),
        llm=LLMSettings(
            backend=str(llm.get("backend", "local_transformers")).strip(),
            remote_model=str(llm.get("remote_model", "deepseek-chat")).strip(),
            api_base=str(llm.get("api_base", "https://api.deepseek.com")).strip(),
            api_key_env=str(llm.get("api_key_env", "DEEPSEEK_API_KEY")).strip(),
            timeout_seconds=_number(llm, "timeout_seconds", 30.0, minimum=0.1),
            temperature=float(llm.get("temperature", 0.1)),
            do_sample=bool(llm.get("do_sample", False)),
            max_new_tokens=_positive_int(llm, "max_new_tokens", 1024),
            repetition_penalty=_number(llm, "repetition_penalty", 1.05),
        ),
        consistency=ConsistencySettings(
            threshold=_number(consistency, "fallback_threshold", 0.62),
            weights=tuple(float(item) for item in raw_consistency_weights),
        ),
    )
