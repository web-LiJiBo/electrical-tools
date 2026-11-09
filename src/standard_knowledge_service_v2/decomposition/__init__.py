"""本地或远程模型查询分解、术语归一化与安全回退。"""

from .remote_model_decomposer import RemoteModelConfig, RemoteModelDecomposer
from .fallback import RawTextFallback
from .models import DecompositionResult, MissingField
from .normalizer import DomainTermNormalizer
from .qwen_decomposer import LocalQwenDecomposer

__all__ = [
    "RemoteModelConfig", "RemoteModelDecomposer", "DecompositionResult", "DomainTermNormalizer",
    "LocalQwenDecomposer", "MissingField", "RawTextFallback",
]
