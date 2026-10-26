from __future__ import annotations

from ..contracts import AnalysisRequest


MAX_QUERY_LENGTH = 20_000
MAX_SCENARIO_HINT_LENGTH = 1_000
MAX_PARAMETER_FIELDS = 200
MAX_CONVERSATION_ITEMS = 20
MAX_CONVERSATION_CONTENT_LENGTH = 10_000


def _string_field(payload: dict, name: str, *, required: bool = False, maximum: int) -> str:
    value = payload.get(name, "")
    if not isinstance(value, str):
        raise ValueError(f"{name}必须是字符串")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{name}不能为空")
    if len(value) > maximum:
        raise ValueError(f"{name}长度不能超过{maximum}个字符")
    return value


def _parameters(payload: dict) -> dict:
    value = payload.get("parameters", {})
    if not isinstance(value, dict):
        raise ValueError("parameters必须是JSON对象")
    if len(value) > MAX_PARAMETER_FIELDS:
        raise ValueError(f"parameters字段数不能超过{MAX_PARAMETER_FIELDS}")
    return dict(value)


def _conversation_context(payload: dict) -> list[dict[str, str]]:
    value = payload.get("conversation_context", [])
    if not isinstance(value, list):
        raise ValueError("conversation_context必须是JSON数组")
    if len(value) > MAX_CONVERSATION_ITEMS:
        raise ValueError(f"conversation_context不能超过{MAX_CONVERSATION_ITEMS}条")
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"conversation_context[{index}]必须是JSON对象")
        role, content = item.get("role"), item.get("content")
        if role not in {"system", "user", "assistant"}:
            raise ValueError(f"conversation_context[{index}].role必须是system、user或assistant")
        if not isinstance(content, str):
            raise ValueError(f"conversation_context[{index}].content必须是字符串")
        if len(content) > MAX_CONVERSATION_CONTENT_LENGTH:
            raise ValueError(
                f"conversation_context[{index}].content长度不能超过"
                f"{MAX_CONVERSATION_CONTENT_LENGTH}个字符"
            )
        normalized.append({"role": role, "content": content})
    return normalized


def query_request_from_json(payload: object) -> tuple[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("请求体必须是JSON对象")
    return (
        _string_field(payload, "query", required=True, maximum=MAX_QUERY_LENGTH),
        _string_field(payload, "scenario_hint", maximum=MAX_SCENARIO_HINT_LENGTH),
    )


def analysis_request_from_json(payload: object) -> AnalysisRequest:
    query, scenario_hint = query_request_from_json(payload)
    assert isinstance(payload, dict)
    return AnalysisRequest(
        query=query,
        scenario_hint=scenario_hint,
        parameters=_parameters(payload),
        target_protocol=_string_field(payload, "target_protocol", maximum=64),
        conversation_context=_conversation_context(payload),
    )
