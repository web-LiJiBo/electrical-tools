from test_action_preconditions import _pipeline, _request


def test_knowledge_explanation_does_not_require_current_measurements(tmp_path):
    response = _pipeline(tmp_path).analyze(_request(query="线路什么情况下需要跳闸"))
    assert response.status == "answered"
    assert response.data["candidate_instruction"] is None
    assert response.evidence
    assert "100" in response.data["answer"]["text"]
