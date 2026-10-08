# JSON分解校核结果

本目录以 `datasets/lunwen/data/2017.xlsx` 的 Sheet1 为原文依据。文件名 `N_clause1.json` 中的 N 是 Sheet1 第一列的条款对编号；`N_clause1.json` 表示该编号对应行的第一个条款，`N_clause2.json` 表示第二个条款。Excel 的物理行号单独保存在 `metadata.source.excel_row` 中。

## 生成内容

- `json/`：每个 Excel 条款对应一个已校核 JSON；包含 `metadata.source` 和 `metadata.audit`。
- `修正对照表.xlsx`：完整 Excel 对照表与汇总页。
- `修正对照表.csv`：同一内容的文本表。
- `audit_summary.json`：可程序读取的统计。

## 本次统计

```json
{
  "excel_file": "D:\\攻关项目\\06-工具\\standard_knowledge_service_outline\\datasets\\lunwen\\data\\2017.xlsx",
  "excel_rows": 3338,
  "source_clause_cells": 6676,
  "expected_json_files": 6674,
  "generated_json_files": 6674,
  "original_json_files_unique": 6344,
  "status_counts": {
    "created_missing_decomposition": 330,
    "passed_source_grounding": 5679,
    "needs_manual_review": 622,
    "corrected_to_source_faithful_rule": 43,
    "skipped_blank_source_text": 2
  },
  "corrected_count": 373,
  "manual_review_count": 961,
  "split_content_mismatch_count": 0,
  "generated_at": "2026-08-28T08:55:02.679366+00:00",
  "audit_version": "1.0"
}
```

自动修正只处理文件缺失、JSON结构损坏或规则文本与原文明显无关的高置信度错误；语义近似、实体别名或轻微改写被标为 `needs_manual_review`，不自动删除。
