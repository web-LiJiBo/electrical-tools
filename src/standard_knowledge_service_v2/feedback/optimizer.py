from __future__ import annotations

from collections import Counter

from .models import ErrorCategory, FeedbackRecord, OptimizationProposal


def propose_optimizations(records: list[FeedbackRecord], minimum_samples: int = 5) -> list[OptimizationProposal]:
    rejected = [record for record in records if not record.accepted]
    counts = Counter(record.category for record in rejected)
    proposals: list[OptimizationProposal] = []
    mapping = {
        ErrorCategory.DECOMPOSITION: ("prompt_or_finetune", "补充分解示例并加入再训练候选集"),
        ErrorCategory.RETRIEVAL: ("retrieval_tuning", "复核召回权重、top-k与同义词"),
        ErrorCategory.CLASSIFICATION: ("threshold_or_retrain", "重标一致性样本并校准分类阈值"),
        ErrorCategory.INSTRUCTION: ("instruction_mapping", "补充场景—指令映射与模板"),
        ErrorCategory.REPORT: ("report_prompt", "优化报告生成约束和事实引用"),
    }
    for category, count in counts.items():
        if count >= minimum_samples and category in mapping:
            kind, reason = mapping[category]
            proposals.append(OptimizationProposal(kind, reason, {"category": category.value}, count))
    return proposals
