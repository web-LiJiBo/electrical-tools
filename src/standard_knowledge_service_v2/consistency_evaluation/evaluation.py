from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .service import ConsistencyEvaluationService


@dataclass(slots=True)
class EvaluationSample:
    left: str
    right: str
    label: bool


def evaluate_fixed_split(service: ConsistencyEvaluationService, samples: Iterable[EvaluationSample]) -> dict[str, float | int]:
    tp = fp = tn = fn = 0
    for sample in samples:
        predicted = service.compare(sample.left, sample.right).consistent
        tp += int(predicted and sample.label)
        fp += int(predicted and not sample.label)
        tn += int(not predicted and not sample.label)
        fn += int(not predicted and sample.label)
    total = tp + fp + tn + fn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"samples": total, "accuracy": (tp + tn) / total if total else 0.0, "precision": precision, "recall": recall, "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0, "tp": tp, "fp": fp, "tn": tn, "fn": fn}
