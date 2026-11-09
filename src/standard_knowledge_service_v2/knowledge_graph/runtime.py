"""Select and initialize the configured runtime graph backend."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .current_graph import CurrentKnowledgeGraph
from .neo4j_graph import Neo4jKnowledgeGraph


def build_runtime_graph(
    units: Iterable[Any],
    settings: Any,
    progress: Callable[[str], None] | None = None,
):
    """Build memory graph or connect/synchronize Neo4j according to settings.

    A Neo4j failure is only converted to a memory fallback when explicitly
    allowed.  The returned memory graph exposes the requested backend and the
    fallback reason in its summary so degradation is never silent.
    """

    report = progress or (lambda _message: None)
    materialized_units = units if isinstance(units, list) else list(units)
    if settings.graph_backend == "memory":
        report("正在构建内存知识图谱")
        graph = CurrentKnowledgeGraph(materialized_units)
        report("内存知识图谱构建完成")
        return graph

    if settings.graph_backend != "neo4j":
        raise ValueError(f"不支持的知识图谱后端: {settings.graph_backend}")

    graph = None
    try:
        report("正在检查Neo4j连接")
        graph = Neo4jKnowledgeGraph.connect(settings)
        graph.health_check()
        report("Neo4j连接正常，正在核对图谱数据指纹")
        sync = graph.synchronize(materialized_units)
        if sync.status == "unchanged":
            report(
                f"Neo4j图谱未变化，跳过重建：{sync.counts['documents']}个条款文档"
            )
        else:
            report(
                "Neo4j增量同步完成："
                f"更新{sync.changed_documents}个，删除{sync.removed_documents}个，"
                f"保留{sync.unchanged_documents}个"
            )
        return graph
    except Exception as exc:
        if graph is not None:
            graph.close()
        if not settings.fallback_to_memory:
            raise RuntimeError(f"Neo4j初始化失败且未允许内存降级: {exc}") from exc
        reason = f"{type(exc).__name__}: {exc}"
        report(f"Neo4j不可用，已明确降级到内存图：{reason}")
        return CurrentKnowledgeGraph(
            materialized_units,
            requested_backend="neo4j",
            fallback_reason=reason,
        )
