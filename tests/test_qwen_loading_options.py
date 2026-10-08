"""不加载7B权重，仅验证加载器不会再传入不兼容的自动设备映射。"""

from pathlib import Path
from unittest.mock import patch

from standard_knowledge_service_v2.llm_decomposition import QwenDecompositionConfig, QwenTextDecomposer


def test_qwen_loader_does_not_use_auto_device_map(tmp_path) -> None:
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    calls = {}

    class FakeTokenizer:
        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            return cls()

    class FakeModel:
        generation_config = None
        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            calls.update(kwargs)
            return cls()
        def eval(self):
            return self
        def to(self, device):
            return self

    class FakeGenerationConfig:
        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            return cls()

    import sys
    import types
    fake_transformers = types.SimpleNamespace(AutoModelForCausalLM=FakeModel, AutoTokenizer=FakeTokenizer, GenerationConfig=FakeGenerationConfig)
    fake_torch = types.SimpleNamespace(float16="f16", float32="f32", cuda=types.SimpleNamespace(is_available=lambda: False))
    with patch.dict(sys.modules, {"torch": fake_torch, "transformers": fake_transformers}):
        QwenTextDecomposer(QwenDecompositionConfig(model_path=Path(tmp_path))).load()
    assert "device_map" not in calls
