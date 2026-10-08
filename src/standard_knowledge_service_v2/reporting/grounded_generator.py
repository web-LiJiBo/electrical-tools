"""报告文字只复述已验证事实；后续可替换为受约束的本地 Qwen。"""

from __future__ import annotations

from .models import GeneratedReport
from .report_builder import ReportBuilder


class GroundedReportGenerator:
    def __init__(self, builder: ReportBuilder | None = None) -> None:
        self.builder = builder or ReportBuilder()

    def generate(self, facts: dict) -> GeneratedReport:
        return self.builder.build(facts)
