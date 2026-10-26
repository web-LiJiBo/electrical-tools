import json
from datetime import datetime, timedelta, timezone

from standard_knowledge_service_v2.application import AnalysisPipeline
from standard_knowledge_service_v2.audit import AuditRecord, JsonlAuditStore
from standard_knowledge_service_v2.config import load_config
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.decomposition.fallback import RawTextFallback
from standard_knowledge_service_v2.retrieval_engine import JsonClauseRepository, LocalLunwenRetrievalAdapter


def _record(request_id: str, created_at: datetime) -> AuditRecord:
    return AuditRecord(
        request_id=request_id,
        service="analyze",
        input_snapshot={},
        result_snapshot={},
        created_at=created_at.isoformat(),
    )


def test_audit_store_prunes_expired_records_and_preserves_unreadable_lines(tmp_path):
    now = datetime(2026, 10, 26, tzinfo=timezone.utc)
    path = tmp_path / "audit.jsonl"
    rows = [
        json.dumps(_record("old", now - timedelta(days=366)).to_dict(), ensure_ascii=False),
        "{broken-json",
        json.dumps(_record("current", now - timedelta(days=1)).to_dict(), ensure_ascii=False),
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    store = JsonlAuditStore(path, retention_days=365)

    # Constructor uses the real clock; run a deterministic prune for the boundary assertion.
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert store.prune_expired(now) == 1
    assert store.get("old") is None
    assert store.get("current") is not None
    assert "{broken-json" in path.read_text(encoding="utf-8")


def test_configured_audit_fingerprints_are_nonempty_and_stable():
    config = load_config("configs/settings.example.yaml")
    first = AnalysisPipeline(LocalLunwenRetrievalAdapter(JsonClauseRepository([])), config=config)
    second = AnalysisPipeline(LocalLunwenRetrievalAdapter(JsonClauseRepository([])), config=config)

    assert config.audit.retention_days == 365
    assert config.audit.record_model_and_config_fingerprint is True
    assert first.model_fingerprint == second.model_fingerprint
    assert first.config_fingerprint == second.config_fingerprint
    assert len(first.model_fingerprint) == len(first.config_fingerprint) == 64


def test_pipeline_writes_configured_fingerprints_to_audit(tmp_path):
    config = load_config("configs/settings.example.yaml")
    store = JsonlAuditStore(tmp_path / "audit.jsonl")
    pipeline = AnalysisPipeline(
        LocalLunwenRetrievalAdapter(JsonClauseRepository([])),
        audit_store=store,
        config=config,
        decomposer=RawTextFallback(),
    )
    request = AnalysisRequest("查询断路器标准")

    pipeline.analyze(request)
    record = store.get(request.meta.request_id)

    assert record is not None
    assert record.model_fingerprint == pipeline.model_fingerprint
    assert record.config_fingerprint == pipeline.config_fingerprint
