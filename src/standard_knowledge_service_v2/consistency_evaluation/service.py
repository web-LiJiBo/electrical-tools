from __future__ import annotations

from pathlib import Path

from .classifier import load_classifier
from .features import extract_features
from .models import ConsistencyResult


class ConsistencyEvaluationService:
    def __init__(self, checkpoint: Path | None = None, weights: list[float] | None = None, threshold: float = 0.62) -> None:
        self.classifier = load_classifier(checkpoint, weights, threshold)

    def compare(self, left: str, right: str, left_rules: list[str] | None = None, right_rules: list[str] | None = None) -> ConsistencyResult:
        return self.classifier.predict(extract_features(left, right, left_rules, right_rules))
