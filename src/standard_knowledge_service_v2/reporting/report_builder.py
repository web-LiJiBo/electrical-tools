from __future__ import annotations

from typing import Any

from .models import GeneratedReport


class ReportBuilder:
    def build(self, facts: dict[str, Any]) -> GeneratedReport:
        context = facts.get("context", {})
        clauses = facts.get("clauses", [])
        validation = facts.get("validation", {})
        candidate = facts.get("instruction", {})
        summary = f"场景：{context.get('scenario', 'general')}；匹配条款：{len(clauses)} 条；安全结论：{validation.get('status', 'uncertain')}。"
        lines = ["# 标准知识服务分析报告", "", f"## 结论\n{summary}", "", "## 场景与参数", f"```json\n{context}\n```", "", "## 匹配条款"]
        lines.extend([f"- {item.get('clause_id', '')}：{item.get('quote', '')}" for item in clauses] or ["- 未找到可用条款证据"])
        lines.extend(["", "## 候选指令", f"```json\n{candidate}\n```", "", "## 验证与风险", f"```json\n{validation}\n```"])
        return GeneratedReport(summary, "\n".join(lines), facts, list(facts.get("warnings", [])))
