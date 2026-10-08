from __future__ import annotations

import math
import re
from collections import Counter
from typing import Sequence

from .models import ConsistencyFeatures
from .numeric_constraints import numeric_constraint_similarity


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norms = math.sqrt(sum(v * v for v in left)) * math.sqrt(sum(v * v for v in right))
    return dot / norms if norms else 0.0


def token_similarity(left: str, right: str) -> float:
    def tokens(text: str) -> Counter[str]:
        return Counter(re.findall(r"[\u4e00-\u9fff]|[A-Za-z]+|\d+(?:\.\d+)?", (text or "").lower()))
    a, b = tokens(left), tokens(right)
    terms = sorted(set(a) | set(b))
    return cosine_similarity([a[t] for t in terms], [b[t] for t in terms]) if terms else 1.0


def structural_similarity(left: str, right: str) -> float:
    markers = ("应", "必须", "不得", "不应", "可以", "当", "时", "条件", "要求")
    a = {m for m in markers if m in left}
    b = {m for m in markers if m in right}
    return len(a & b) / len(a | b) if a or b else 1.0


def rule_set_similarity(left_rules: list[str], right_rules: list[str]) -> float:
    if not left_rules and not right_rules:
        return 1.0
    if not left_rules or not right_rules:
        return 0.0
    forward = [max(token_similarity(a, b) for b in right_rules) for a in left_rules]
    backward = [max(token_similarity(b, a) for a in left_rules) for b in right_rules]
    return (sum(forward) / len(forward) + sum(backward) / len(backward)) / 2


def extract_features(left: str, right: str, left_rules: list[str] | None = None, right_rules: list[str] | None = None) -> ConsistencyFeatures:
    return ConsistencyFeatures(
        rule_set_similarity=rule_set_similarity(left_rules or [left], right_rules or [right]),
        numeric_constraint_similarity=numeric_constraint_similarity(left, right),
        semantic_similarity=token_similarity(left, right),
        structural_similarity=structural_similarity(left, right),
    )
