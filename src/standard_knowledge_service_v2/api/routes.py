"""路由注册独立于应用工厂，便于测试和后续扩展。"""

from __future__ import annotations

from .schemas import analysis_request_from_json
from ..retrieval import LunwenMatchingInput


def register_routes(app, application) -> None:
    from fastapi import HTTPException

    @app.get("/health")
    def health():
        return {"status": "ok", "dispatch_allowed": False}

    @app.post("/analyze")
    def analyze(payload: dict):
        try:
            return application.facade.analyze(analysis_request_from_json(payload)).to_dict()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/decompose")
    def decompose(payload: dict):
        query = str(payload.get("query", ""))
        if not query.strip():
            raise HTTPException(status_code=422, detail="query不能为空")
        return application.facade.decomposer.decompose(query, str(payload.get("scenario_hint", ""))).to_dict()

    @app.post("/search")
    def search(payload: dict):
        query = str(payload.get("query", ""))
        if not query.strip():
            raise HTTPException(status_code=422, detail="query不能为空")
        parsed = application.facade.decomposer.decompose(query).to_lunwen_parsed_json()
        result = application.facade.retriever.match(LunwenMatchingInput(query, parsed))
        return {"entities": [item.__dict__ if hasattr(item, "__dict__") else {"name": item.name, "similarity": item.similarity} for item in result.matched_entities], "rules": [{"rule_id": item.rule.rule_id, "rank": item.rank, "score": item.combined_score} for item in result.rules], "warnings": result.warnings}

    @app.post("/generate-instruction")
    def generate_instruction(payload: dict):
        response = application.facade.analyze(analysis_request_from_json(payload))
        return {"status": response.status, "candidate_instruction": response.data.get("candidate_instruction"), "missing_fields": response.data.get("missing_fields", [])}

    @app.post("/validate")
    def validate(payload: dict):
        response = application.facade.analyze(analysis_request_from_json(payload))
        return {"status": response.status, "validation": response.data.get("validation"), "evidence": response.evidence}

    @app.post("/generate-report")
    def generate_report(payload: dict):
        response = application.facade.analyze(analysis_request_from_json(payload))
        return {"status": response.status, "report": response.data.get("report"), "warnings": response.warnings}

    @app.get("/audit/{request_id}")
    def audit(request_id: str):
        record = application.audit_store.get(request_id)
        if not record:
            raise HTTPException(status_code=404, detail="审计记录不存在")
        return record.to_dict()
