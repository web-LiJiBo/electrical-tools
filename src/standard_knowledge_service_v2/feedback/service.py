from __future__ import annotations

from .models import FeedbackRecord, OptimizationProposal
from .monitor import quality_snapshot
from .optimizer import propose_optimizations
from .store import JsonlFeedbackStore


class FeedbackService:
    def __init__(self, store: JsonlFeedbackStore) -> None:
        self.store = store

    def submit(self, record: FeedbackRecord) -> str:
        if not 1 <= record.rating <= 5:
            raise ValueError("rating 必须在 1 到 5 之间")
        self.store.append(record)
        return record.record_id

    def snapshot(self) -> dict[str, object]:
        return quality_snapshot(self.store.list())

    def optimization_proposals(self, minimum_samples: int = 5) -> list[OptimizationProposal]:
        return propose_optimizations(self.store.list(), minimum_samples)
