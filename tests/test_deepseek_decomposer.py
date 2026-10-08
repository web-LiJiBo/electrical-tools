import json
from unittest.mock import patch

from standard_knowledge_service_v2.decomposition import DeepSeekConfig, DeepSeekDecomposer


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        content = json.dumps({
            "intent": "instruction",
            "entities": [{"name": "集电线路", "type": "设备", "desc": ""}],
            "actions": ["trip"],
            "constraints": [],
            "standard_refs": [],
            "scenario": {"scenario_type": "海上风电", "device_type": "集电线路"},
            "keywords": ["集电线路", "过流"],
            "confidence": 0.9,
        }, ensure_ascii=False)
        return json.dumps({"choices": [{"message": {"content": content}}]}, ensure_ascii=False).encode()


def test_deepseek_response_is_validated_and_normalized(monkeypatch) -> None:
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "secret-not-logged")
    config = DeepSeekConfig(api_key_env="TEST_DEEPSEEK_KEY")
    with patch("standard_knowledge_service_v2.decomposition.deepseek_decomposer.urlopen", return_value=_Response()):
        result = DeepSeekDecomposer(config).decompose("集电线路过流时跳闸", "海上风电")
    assert result.source == "deepseek_api"
    assert result.actions == ["trip"]
    assert result.confidence == 0.9


def test_deepseek_free_text_action_is_mapped_after_validation(monkeypatch) -> None:
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "secret-not-logged")
    with patch("standard_knowledge_service_v2.decomposition.deepseek_decomposer.urlopen", return_value=_Response()):
        result = DeepSeekDecomposer(DeepSeekConfig(api_key_env="TEST_DEEPSEEK_KEY")).decompose("集电线路过流")
    assert result.actions == ["trip"]


def test_missing_api_key_uses_safe_fallback(monkeypatch) -> None:
    monkeypatch.delenv("MISSING_DEEPSEEK_KEY", raising=False)
    result = DeepSeekDecomposer(DeepSeekConfig(api_key_env="MISSING_DEEPSEEK_KEY")).decompose("集电线路跳闸")
    assert result.source == "raw_text_fallback"
    assert result.actions == ["trip"]
    assert "MISSING_DEEPSEEK_KEY" in result.errors[0]
    assert "secret" not in result.errors[0]
