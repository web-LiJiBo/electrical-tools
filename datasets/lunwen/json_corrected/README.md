# JSON 审计与修正数据集

本目录以 `datasets/lunwen/data/2017.xlsx` 为唯一原文基准生成。每个 `json/<编号>_clause<1或2>.json` 对应 Excel 中同一编号条款对的第一条或第二条文本。

## 文件说明

- `json/`：规范 JSON；保留已有实体、规则和关系，并增加来源及审计元数据。
- `correction_comparison.xlsx`：完整人工审阅表，包含原文、原始规则、修正内容、状态和原因。
- `correction_comparison.csv`、`correction_comparison.json`：同一对照表的机器可读版本。
- `audit_summary.json`：本次运行统计。

## 本次结果

- Excel 非空条款：6674；空单元格跳过：2。
- 新 JSON 数量：6674。
- 两套既有 JSON 均存在且内容一致：6344。
- 两套既有 JSON 均缺失、已按原文生成最小保真 JSON：330。
- `verified_structural`：3222。
- `pending_semantic_review`：3122。
- `generated_from_source_pending_semantic_review`：330。

## 状态定义

- `verified_structural`：JSON 可解析，字段结构合法，所有规则内容合并后覆盖 Excel 原文，且首条规则具备主体和动作；这只是确定性结构核验，不等同于专家语义验收。
- `pending_semantic_review`：原 JSON 可用，但规则内容合并后未完整覆盖原文或数值存在缺失；需由领域专家或可用大模型复核，不会自动虚构语义字段。
- `generated_from_source_pending_semantic_review`：两套原 JSON 均不存在；已依据 Excel 原文创建最小保真规则，实体、动作、条件、关系待补充。

人工修订后，应更新对应 JSON 的 `entities`、`rules`、`relations`，并在 `metadata` 中保留来源与修订理由；然后重新运行审计脚本确认覆盖状态。
