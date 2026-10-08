from __future__ import annotations

from ..domain import EvidenceRef
from .models import RuleHit


class EvidenceBuilder:
    def build(self, hit: RuleHit) -> EvidenceRef:
        # 证据必须逐字回引数据集中的原始规则正文，禁止用字段拼接改写原条款。
        quote = hit.rule.content.strip()
        if not quote:
            quote = hit.rule.subject + " " + hit.rule.action
            if hit.rule.condition:
                quote += f"；条件：{hit.rule.condition}"
            if hit.rule.constraints:
                quote += f"；约束：{hit.rule.constraints[0].value}"
        return EvidenceRef(hit.clause.standard_id, hit.clause.version, hit.clause.clause_id, hit.clause.chapter_path, quote.strip(), hit.clause.source_uri)
