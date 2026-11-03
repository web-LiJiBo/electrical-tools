"""注意力模型兼容加载与显式的无模型备用分类器。"""

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
        if features.numeric_constraint_conflict:
            conflicts.append({"type": "numeric_constraint", "score": features.numeric_constraint_similarity})
        if features.structural_similarity < 0.5:
            conflicts.append({"type": "modality_or_condition", "score": features.structural_similarity})
        # Numeric constraints are safety-critical. An incompatible unit/range
        # cannot be outvoted by lexical or structural similarity.
        hard_numeric_conflict = features.numeric_constraint_conflict
        consistent = score >= self.threshold and not hard_numeric_conflict
        return ConsistencyResult(consistent, score if consistent else 1.0 - score, features, attention, conflicts)


class TorchAttentionClassifier:
    """按权重元数据恢复论文的注意力融合分类器。"""

    def __init__(self, checkpoint: Path) -> None:
        try:
            import torch
            from torch import nn
        except ImportError as exc:
            raise RuntimeError("加载论文注意力模型需要安装 torch") from exc

        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
        state_dict = state.get("model_state_dict", state)
        input_dim = int(state.get("input_dim", state_dict["attn_fc1.weight"].shape[1]))
        hidden_dim = int(state.get("hidden_dim", state_dict["attn_fc1.weight"].shape[0]))
        dropout_rate = float(state.get("dropout_rate", 0.0))

        class AttentionFusionModel(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                attention_hidden = int(state_dict["attn_fc2.weight"].shape[0])
                classifier_hidden = int(state_dict["cls_fc1.weight"].shape[0])
                self.attn_fc1 = nn.Linear(input_dim, hidden_dim)
                self.attn_bn1 = nn.BatchNorm1d(hidden_dim)
                self.attn_fc2 = nn.Linear(hidden_dim, attention_hidden)
                self.attn_bn2 = nn.BatchNorm1d(attention_hidden)
                self.attn_fc3 = nn.Linear(attention_hidden, input_dim)
                self.cls_fc1 = nn.Linear(input_dim, classifier_hidden)
                self.cls_bn = nn.BatchNorm1d(classifier_hidden)
                self.cls_fc2 = nn.Linear(classifier_hidden, 2)
                self.dropout = nn.Dropout(dropout_rate)

            def forward(self, x):
                attention = self.dropout(torch.relu(self.attn_bn1(self.attn_fc1(x))))
                attention = self.dropout(torch.relu(self.attn_bn2(self.attn_fc2(attention))))
                attention = torch.softmax(self.attn_fc3(attention), dim=1)
                fused = attention * x
                classified = self.dropout(torch.relu(self.cls_bn(self.cls_fc1(fused))))
                return self.cls_fc2(classified), attention

        self.torch = torch
        self.input_dim = input_dim
        # The full checkpoint was trained with rule-set, numeric-constraint and
        # semantic/keyword-overlap features, in this order.
        self.feature_indices = tuple(range(input_dim))
        self.model = AttentionFusionModel()
        self.model.load_state_dict(state_dict)
        self.model.eval()

    def predict(self, features: ConsistencyFeatures) -> ConsistencyResult:
        full_vector = features.vector()
        if self.input_dim > len(full_vector):
            raise ValueError(
                f"注意力模型需要{self.input_dim}个特征，当前仅提供{len(full_vector)}个"
            )
        model_vector = [full_vector[index] for index in self.feature_indices]
        with self.torch.no_grad():
            logits, weights = self.model(self.torch.tensor([model_vector], dtype=self.torch.float32))
            probabilities = self.torch.softmax(logits, dim=1)[0]
            label = int(self.torch.argmax(probabilities).item())
        conflicts = []
        consistent = bool(label)
        if features.numeric_constraint_conflict:
            consistent = False
            conflicts.append({"type": "numeric_constraint", "score": features.numeric_constraint_similarity})
        return ConsistencyResult(consistent, float(probabilities[label]), features,
                                 [float(v) for v in weights[0]], conflicts,
                                 model="lunwen-attention-model")


def load_classifier(checkpoint: Path | None = None, weights: list[float] | None = None, threshold: float = 0.62):
    """Load the configured attention model or fail loudly.

    The weighted classifier remains available only when callers explicitly do
    not configure a checkpoint (mainly deterministic unit tests). A configured
    production checkpoint must never silently degrade.
    """
    if checkpoint is not None:
        checkpoint = Path(checkpoint)
        if not checkpoint.is_file():
            raise FileNotFoundError(f"一致性注意力模型文件不存在: {checkpoint}")
        try:
            return TorchAttentionClassifier(checkpoint)
        except Exception as exc:
            raise RuntimeError(f"一致性注意力模型加载失败: {checkpoint}: {exc}") from exc
    return WeightedConsistencyClassifier(weights, threshold)
