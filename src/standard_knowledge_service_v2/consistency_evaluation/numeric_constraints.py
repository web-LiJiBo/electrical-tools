"""复制并整理自 lunwen/evaluate_consistency.py 的数值约束算法。"""

from __future__ import annotations

import math
import re

from .models import NumericConstraint

UNIT_FACTORS = {
    "kv": ("v", 1000.0), "v": ("v", 1.0), "mw": ("w", 1_000_000.0), "kw": ("w", 1000.0),
    "w": ("w", 1.0), "mm": ("m", 0.001), "cm": ("m", 0.01), "m": ("m", 1.0),
    "ms": ("s", 0.001), "s": ("s", 1.0), "%": ("%", 1.0), "k": ("k", 1.0), "℃": ("℃", 1.0),
}
OP_SYNONYMS = {
    "不大于": "<=", "不得大于": "<=", "小于等于": "<=", "至多": "<=", "≤": "<=",
    "不小于": ">=", "不得小于": ">=", "大于等于": ">=", "至少": ">=", "≥": ">=",
    "小于": "<", "低于": "<", "<": "<", "大于": ">", "高于": ">", ">": ">",
    "等于": "=", "为": "=", "=": "=",
}


def _normalise(value: float, unit: str) -> tuple[float, str]:
    canonical, factor = UNIT_FACTORS.get(unit.lower(), (unit.lower(), 1.0))
    return value * factor, canonical


def extract_numeric_constraints(text: str) -> list[NumericConstraint]:
    candidates: list[NumericConstraint] = []
    operators = "|".join(sorted(map(re.escape, OP_SYNONYMS), key=len, reverse=True))
    pattern = re.compile(rf"(?P<op>{operators})\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>kV|V|MW|kW|W|mm|cm|m|ms|s|%|K|℃)?", re.I)
    for match in pattern.finditer(text or ""):
        value, unit = _normalise(float(match.group("value")), match.group("unit") or "")
        candidates.append(NumericConstraint(OP_SYNONYMS[match.group("op")], value, unit))
    ranges = re.compile(r"(?P<low>\d+(?:\.\d+)?)\s*(?:至|到|~|—|-)\s*(?P<high>\d+(?:\.\d+)?)\s*(?P<unit>kV|V|MW|kW|W|mm|cm|m|ms|s|%|K|℃)?", re.I)
    for match in ranges.finditer(text or ""):
        low, unit = _normalise(float(match.group("low")), match.group("unit") or "")
        high, _ = _normalise(float(match.group("high")), match.group("unit") or "")
        candidates.append(NumericConstraint("range", low, unit, high))
    return candidates


def _interval(item: NumericConstraint) -> tuple[float, float]:
    if item.operator in ("<=", "<"):
        return -math.inf, item.value
    if item.operator in (">=", ">"):
        return item.value, math.inf
    if item.operator == "range":
        return item.value, item.upper_value if item.upper_value is not None else item.value
    return item.value, item.value


def single_constraint_similarity(left: NumericConstraint, right: NumericConstraint) -> float:
    if left.unit and right.unit and left.unit != right.unit:
        return 0.0
    l_low, l_high = _interval(left)
    r_low, r_high = _interval(right)
    if max(l_low, r_low) > min(l_high, r_high):
        return 0.0
    if left.operator == right.operator and left.value == right.value and left.upper_value == right.upper_value:
        return 1.0
    finite = [abs(v) for v in (left.value, right.value, left.upper_value, right.upper_value) if v is not None and math.isfinite(v)]
    scale = max(finite or [1.0])
    distance = abs(left.value - right.value) / scale
    return max(0.5, 1.0 - distance)


def numeric_constraint_similarity(left_text: str, right_text: str) -> float:
    left, right = extract_numeric_constraints(left_text), extract_numeric_constraints(right_text)
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    scores = [max(single_constraint_similarity(item, other) for other in right) for item in left]
    return sum(scores) / len(scores)
