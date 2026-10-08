from __future__ import annotations

from ..reporting.grounded_generator import GroundedReportGenerator


class ReportService:
    def __init__(self, generator: GroundedReportGenerator | None = None) -> None:
        self.generator = generator or GroundedReportGenerator()

    def generate(self, structured_result: dict):
        return self.generator.generate(structured_result)
