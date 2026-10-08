from __future__ import annotations

from collections import Counter

from .models import FeedbackRecord


def quality_snapshot(records: list[FeedbackRecord]) -> dict[str, object]:
    total = len(records)
    accepted = sum(record.accepted for record in records)
    latencies = [record.latency_ms for record in records if record.latency_ms is not None]
    return {
        "samples": total,
        "acceptance_rate": accepted / total if total else 0.0,
        "average_rating": sum(record.rating for record in records) / total if total else 0.0,
        "average_latency_ms": sum(latencies) / len(latencies) if latencies else None,
        "error_distribution": dict(Counter(record.category.value for record in records if not record.accepted)),
    }
