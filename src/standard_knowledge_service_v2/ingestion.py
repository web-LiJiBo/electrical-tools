"""第3、4章：标准导入、层级切分和格式互操作接口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol

from .domain import ClauseKnowledgeUnit


@dataclass(slots=True)
class SourceDocument:
    path: Path
    format: str
    standard_id: str = ""
    version: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ImportCheckpoint:
    source_id: str
    last_unit_id: str = ""
    processed: int = 0
    failed: int = 0


class DocumentParser(Protocol):
    """解析PDF/Excel/XML等来源并保留文件—章—节—条层级。"""

    def parse(self, source: SourceDocument) -> Iterable[dict[str, Any]]: ...


class ClauseSegmenter(Protocol):
    def segment(self, parsed_document: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]: ...


class StructuredKnowledgeExtractor(Protocol):
    """输出实体、关系、规则、约束并保留原文证据。"""

    def extract(self, raw_clause: dict[str, Any]) -> ClauseKnowledgeUnit: ...


class FormatInterchange(Protocol):
    """保证XML、JSON、RDF之间统一ID和语义往返一致。"""

    def to_xml(self, unit: ClauseKnowledgeUnit) -> str: ...
    def to_json(self, unit: ClauseKnowledgeUnit) -> dict[str, Any]: ...
    def to_rdf(self, unit: ClauseKnowledgeUnit) -> list[tuple[str, str, str]]: ...


class BatchIngestionPipeline(Protocol):
    def run(self, sources: Iterable[SourceDocument], resume: bool = True) -> ImportCheckpoint: ...

