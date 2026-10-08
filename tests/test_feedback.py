from standard_knowledge_service_v2.feedback import ErrorCategory, FeedbackRecord, FeedbackService
from standard_knowledge_service_v2.feedback.store import JsonlFeedbackStore


def test_feedback_is_persisted_and_generates_reviewable_proposal(tmp_path) -> None:
    service = FeedbackService(JsonlFeedbackStore(tmp_path / "feedback.jsonl"))
    for index in range(2):
        service.submit(FeedbackRecord(str(index), False, 2, ErrorCategory.RETRIEVAL))
    assert service.snapshot()["samples"] == 2
    proposals = service.optimization_proposals(minimum_samples=2)
    assert proposals[0].requires_approval
    assert proposals[0].kind == "retrieval_tuning"


def test_invalid_rating_is_rejected(tmp_path) -> None:
    service = FeedbackService(JsonlFeedbackStore(tmp_path / "feedback.jsonl"))
    try:
        service.submit(FeedbackRecord("bad", False, 6))
    except ValueError:
        return
    raise AssertionError("应拒绝非法评分")
