from __future__ import annotations

from ..contracts import AnalysisRequest


def analysis_request_from_json(payload: dict) -> AnalysisRequest:
    return AnalysisRequest(
        query=str(payload.get("query", "")), scenario_hint=str(payload.get("scenario_hint", "")),
        parameters=dict(payload.get("parameters", {})), target_protocol=str(payload.get("target_protocol", "")),
        conversation_context=list(payload.get("conversation_context", [])),
    )
