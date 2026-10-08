"""对外JSON契约；可映射为FastAPI/OpenAPI，但不绑定具体Web框架。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class RequestMeta:
    request_id: str = field(default_factory=lambda: str(uuid4()))
    caller: str = ""
    scenario: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass(slots=True)
class AnalysisRequest:
    """端到端后台入口：自然语言、可选场景提示和已知业务参数。"""

    query: str
    scenario_hint: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    target_protocol: str = ""
    conversation_context: list[dict[str, str]] = field(default_factory=list)
    meta: RequestMeta = field(default_factory=RequestMeta)

    def __post_init__(self) -> None:
        if not self.query or not self.query.strip():
            raise ValueError("query不能为空")


@dataclass(slots=True)
class SearchRequest:
    query: str
    top_k: int = 10
    context: dict[str, Any] = field(default_factory=dict)
    filters: dict[str, Any] = field(default_factory=dict)
    meta: RequestMeta = field(default_factory=RequestMeta)


@dataclass(slots=True)
class ConsistencyRequest:
    clause_a: str
    clause_b: str
    input_type: str = "id"
    meta: RequestMeta = field(default_factory=RequestMeta)


@dataclass(slots=True)
class ComplianceRequest:
    parameters: dict[str, Any]
    standard_refs: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    meta: RequestMeta = field(default_factory=RequestMeta)


@dataclass(slots=True)
class InstructionRequest:
    clause_id: str
    device_config: dict[str, Any]
    context: dict[str, Any] = field(default_factory=dict)
    meta: RequestMeta = field(default_factory=RequestMeta)


@dataclass(slots=True)
class APIResponse:
    request_id: str
    status: str
    data: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AnalysisResponse(APIResponse):
    """主流程响应；data中固定保留分解、场景、缺失字段和降级原因。"""

    pass
