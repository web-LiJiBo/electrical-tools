"""基于结构化事实的回答、报告组装与导出。"""

from .grounded_generator import GroundedReportGenerator
from .report_builder import ReportBuilder

__all__ = ["GroundedReportGenerator", "ReportBuilder"]
