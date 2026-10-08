"""注意力模型兼容加载与无需深度学习依赖的透明降级分类器。"""

from __future__ import annotations

from pathlib import Path

from .models import ConsistencyFeatures, ConsistencyResult


class WeightedConsistencyClassifier:
    def __init__(self, weights: list[float] | None = None, threshold: float = 0.62) -> None:
        self.weights = weights or [0.30, 0.35, 0.20, 0.15]
        self.threshold = threshold

    def predict(self, features: ConsistencyFeatures) -> ConsistencyResult:
        total = sum(self.weights) or 1.0
        attention = [weight / total for weight in self.weights]
        score = sum(value * weight for value, weight in zip(features.vector(), attention))
        conflicts = []
        if features.numeric_constraint_similarity < 0.5:
            conflicts.append({"type": "numeric_constraint", "score": features.numeric_constraint_similarity})
        if features.structural_similarity < 0.5:
            conflicts.append({"type": "modality_or_condition", "score": features.structural_similarity})
        return ConsistencyResult(score >= self.threshold, score if score >= self.threshold else 1.0 - score, features, attention, conflicts)


class TorchAttentionClassifier:
    """兼容论文 AttentionFusionModel：4→8→4 注意力、加权后 1→2 分类。"""

    def __init__(self, checkpoint: Path, input_dim: int = 4) -> None:
        try:
            import torch
            from torch import nn
        except ImportError as exc:
            raise RuntimeError("加载论文注意力模型需要安装 torch") from exc

        class AttentionFusionModel(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.fc1 = nn.Linear(input_dim, 8)
                self.fc2 = nn.Linear(8, input_dim)
                self.classifier = nn.Linear(1, 2)

            def forward(self, x):
                attention = torch.softmax(self.fc2(torch.relu(self.fc1(x))), dim=1)
                fused = torch.sum(attention * x, dim=1, keepdim=True)
                return self.classifier(fused), attention

        self.torch = torch
        self.model = AttentionFusionModel()
        state = torch.load(checkpoint, map_location="cpu")
        self.model.load_state_dict(state.get("model_state_dict", state))
        self.model.eval()

    def predict(self, features: ConsistencyFeatures) -> ConsistencyResult:
        with self.torch.no_grad():
            logits, weights = self.model(self.torch.tensor([features.vector()], dtype=self.torch.float32))
            probabilities = self.torch.softmax(logits, dim=1)[0]
            label = int(self.torch.argmax(probabilities).item())
        return ConsistencyResult(bool(label), float(probabilities[label]), features, [float(v) for v in weights[0]], model="lunwen-attention-model")


def load_classifier(checkpoint: Path | None = None, weights: list[float] | None = None, threshold: float = 0.62):
    if checkpoint and checkpoint.is_file():
        try:
            return TorchAttentionClassifier(checkpoint)
        except (RuntimeError, ValueError, KeyError):
            pass
    return WeightedConsistencyClassifier(weights, threshold)
