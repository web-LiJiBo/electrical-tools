from __future__ import annotations

import math
import re
from collections import Counter


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", (text or "")).lower()


def tokens(text: str) -> Counter[str]:
    # 中文单字加英文/数字片段，确保无需第三方分词器也有稳定结果。
    return Counter(re.findall(r"[\u4e00-\u9fff]|[a-z]+|\d+(?:\.\d+)?", normalize(text)))


def cosine(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    common = set(left) & set(right)
    numerator = sum(left[key] * right[key] for key in common)
    denominator = math.sqrt(sum(value * value for value in left.values())) * math.sqrt(sum(value * value for value in right.values()))
    return numerator / denominator if denominator else 0.0


def text_similarity(left: str, right: str) -> float:
    a, b = normalize(left), normalize(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        # 短词命中长实体只提供部分证据，避免“气体”与任意气体相关实体并列满分。
        return min(len(a), len(b)) / max(len(a), len(b))
    return cosine(tokens(a), tokens(b))


def structural_score(query: str, rule_text: str) -> float:
    # “应/当/时”在标准文本中出现过于普遍，作为结构特征会把无关条款抬高。
    tags = ("不应", "不得", "必须", "严禁", "不大于", "不小于", "不超过", "至少", "至多", "条件")
    q, r = {tag for tag in tags if tag in query}, {tag for tag in tags if tag in rule_text}
    return len(q & r) / len(q | r) if q or r else 0.0
