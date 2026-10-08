"""以2017.xlsx为基准审计、规范化并生成独立JSON数据集。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXCEL = PROJECT_ROOT / "datasets" / "lunwen" / "data" / "2017.xlsx"
DEFAULT_SOURCE_ROOT = PROJECT_ROOT / "datasets" / "lunwen"
DEFAULT_OUTPUT = DEFAULT_SOURCE_ROOT / "json_corrected"
NUMERIC_RE = re.compile(r"\d+(?:\.\d+)?")


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip()


def comparable_text(value: Any) -> str:
    """忽略规则拆分时常见的分隔符，比较全部规则对原文的覆盖。"""
    return re.sub(r"[\s,，;；:：.。、()（）\[\]【】]", "", str(value or ""))


def text_hash(value: str) -> str:
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()[:16]


def clean_list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


@dataclass(slots=True)
class AuditRow:
    pair_id: int
    clause_index: int
    filename: str
    excel_row: int
    source_text: str
    source_hash: str
    source_dataset: str = ""
    source_file: str = ""
    exists_in_output_jsons: bool = False
    exists_in_output_jsons_new: bool = False
    split_content_match: str = "not_compared"
    parse_valid: bool = False
    schema_valid: bool = False
    rule_content_matches_source: bool = False
    numeric_coverage: str = "not_checked"
    semantic_fields_present: bool = False
    original_rule_content: str = ""
    corrected_rule_content: str = ""
    audit_status: str = ""
    auto_corrections: list[str] = field(default_factory=list)
    manual_review_reason: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["auto_corrections"] = "；".join(self.auto_corrections)
        data["manual_review_reason"] = "；".join(self.manual_review_reason)
        return data


def collect_files(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for split in ("train", "test"):
        directory = root / split
        if directory.is_dir():
            for path in directory.glob("*.json"):
                if path.name in result:
                    raise ValueError(f"同一划分目录出现重名JSON: {path.name}")
                result[path.name] = path
    return result


def read_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("raw_output"), str):
            data = json.loads(data["raw_output"])
        return (data if isinstance(data, dict) else None), ""
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, str(exc)


def canonical_json(source_text: str, pair_id: int, clause_index: int) -> dict[str, Any]:
    return {
        "entities": [],
        "rules": [{
            "content": source_text,
            "type": "未标注",
            "subject": "",
            "action": "",
            "condition": "",
            "constraint": source_text,
            "related_entities": [],
        }],
        "relations": [],
        "metadata": {
            "pair_id": pair_id,
            "clause_index": clause_index,
            "source_excel": "2017.xlsx",
            "audit_status": "generated_from_source_pending_semantic_review",
        },
    }


def audit_and_correct(source_text: str, pair_id: int, clause_index: int, filename: str, excel_row: int, selected: Path | None, old: Path | None, new: Path | None) -> tuple[dict[str, Any], AuditRow]:
    row = AuditRow(pair_id, clause_index, filename, excel_row, source_text, text_hash(source_text))
    row.exists_in_output_jsons = old is not None
    row.exists_in_output_jsons_new = new is not None
    old_data, old_error = read_json(old) if old else (None, "")
    new_data, new_error = read_json(new) if new else (None, "")
    if old and new:
        row.split_content_match = "match" if old_data is not None and new_data is not None and json.dumps(old_data, ensure_ascii=False, sort_keys=True) == json.dumps(new_data, ensure_ascii=False, sort_keys=True) else "different_or_invalid"
    if selected is None:
        row.audit_status = "generated_from_source_pending_semantic_review"
        row.auto_corrections.append("缺失JSON：依据Excel原文生成最小保真结构")
        row.manual_review_reason.append("没有现有实体、动作、条件和关系可供验证")
        return canonical_json(source_text, pair_id, clause_index), row
    data, error = read_json(selected)
    row.source_dataset = "output_jsons_new" if new == selected else "output_jsons"
    row.source_file = str(selected)
    if data is None:
        row.audit_status = "generated_from_source_pending_semantic_review"
        row.auto_corrections.append(f"原JSON无法解析：{error or old_error or new_error}")
        row.manual_review_reason.append("原JSON不可用，需人工补充分解语义")
        return canonical_json(source_text, pair_id, clause_index), row
    row.parse_valid = True
    entities = clean_list(data.get("entities"))
    rules = clean_list(data.get("rules"))
    relations = clean_list(data.get("relations"))
    row.schema_valid = isinstance(data.get("entities"), list) and isinstance(data.get("rules"), list) and isinstance(data.get("relations"), list)
    if not row.schema_valid:
        row.auto_corrections.append("entities/rules/relations已规范为对象列表")
    valid_rules = [item for item in rules if normalize_text(item.get("content", ""))]
    if valid_rules:
        row.original_rule_content = str(valid_rules[0].get("content", ""))
    combined_rule_text = "".join(str(item.get("content", "")) for item in valid_rules)
    row.rule_content_matches_source = comparable_text(combined_rule_text) == comparable_text(source_text)
    if not valid_rules:
        rules = canonical_json(source_text, pair_id, clause_index)["rules"]
        row.auto_corrections.append("缺少有效规则内容：按Excel原文补充规则content和constraint")
        row.manual_review_reason.append("缺少主体、动作、条件等语义字段")
    elif not row.rule_content_matches_source:
        rules = [dict(item) for item in valid_rules]
        row.manual_review_reason.append("全部规则内容合并后不能覆盖Excel原文，需人工复核语义分解")
    else:
        rules = [dict(item) for item in valid_rules]
    row.corrected_rule_content = str(rules[0].get("content", "")) if rules else ""
    first = rules[0] if rules else {}
    row.semantic_fields_present = bool(normalize_text(first.get("subject", "")) and normalize_text(first.get("action", "")))
    source_numbers = set(NUMERIC_RE.findall(source_text))
    decomposed_text = json.dumps({"entities": entities, "rules": rules, "relations": relations}, ensure_ascii=False)
    row.numeric_coverage = "complete" if source_numbers <= set(NUMERIC_RE.findall(decomposed_text)) else "missing:" + ",".join(sorted(source_numbers - set(NUMERIC_RE.findall(decomposed_text))))
    if row.numeric_coverage != "complete":
        row.manual_review_reason.append("原文数值未完整出现在结构化分解中")
    if not row.semantic_fields_present:
        row.manual_review_reason.append("规则缺少主体或动作")
    if row.rule_content_matches_source and row.schema_valid and row.semantic_fields_present and row.numeric_coverage == "complete":
        row.audit_status = "verified_structural"
    elif row.auto_corrections:
        row.audit_status = "auto_corrected_pending_semantic_review"
    else:
        row.audit_status = "pending_semantic_review"
    result = {"entities": entities, "rules": rules, "relations": relations, "metadata": {
        "pair_id": pair_id,
        "clause_index": clause_index,
        "source_excel": "2017.xlsx",
        "source_text_hash": row.source_hash,
        "source_dataset": row.source_dataset,
        "source_file": row.source_file,
        "audit_status": row.audit_status,
        "auto_corrections": row.auto_corrections,
        "manual_review_reason": row.manual_review_reason,
    }}
    return result, row


def write_xlsx(rows: list[AuditRow], output: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.table import Table, TableStyleInfo

    workbook = Workbook()
    summary = workbook.active
    summary.title = "汇总"
    statuses: dict[str, int] = {}
    for row in rows:
        statuses[row.audit_status] = statuses.get(row.audit_status, 0) + 1
    summary.append(["项目", "数量/说明"])
    summary.append(["原始Excel非空条款数", len(rows)])
    for status, count in sorted(statuses.items()):
        summary.append([status, count])
    summary.append(["说明", "verified_structural仅表示结构与原文规则文本已通过确定性校验；语义准确性仍以待人工复核项为准。"])
    details = workbook.create_sheet("修正对照表")
    data = [row.to_dict() for row in rows]
    headers = list(data[0]) if data else []
    details.append(headers)
    for item in data:
        details.append([item.get(header, "") for header in headers])
    for sheet in (summary, details):
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F4E78")
            cell.alignment = Alignment(horizontal="center", vertical="center")
        sheet.freeze_panes = "A2"
    if headers:
        table = Table(displayName="CorrectionComparison", ref=f"A1:{chr(64 + min(len(headers), 26))}{len(data) + 1}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        details.add_table(table)
    widths = {"A": 10, "B": 11, "C": 20, "D": 10, "E": 55, "F": 20, "G": 22, "H": 55, "I": 14, "J": 18, "K": 18, "L": 12, "M": 12, "N": 18, "O": 16, "P": 12, "Q": 14, "R": 45, "S": 45, "T": 35, "U": 45}
    for column, width in widths.items():
        details.column_dimensions[column].width = width
    for row_cells in details.iter_rows(min_row=2):
        for cell in row_cells:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    output.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output)


def write_readme(output: Path, summary: dict[str, Any]) -> None:
    statuses = summary["status_counts"]
    lines = [
        "# JSON 审计与修正数据集",
        "",
        "本目录以 `datasets/lunwen/data/2017.xlsx` 为唯一原文基准生成。每个 `json/<编号>_clause<1或2>.json` 对应 Excel 中同一编号条款对的第一条或第二条文本。",
        "",
        "## 文件说明",
        "",
        "- `json/`：规范 JSON；保留已有实体、规则和关系，并增加来源及审计元数据。",
        "- `correction_comparison.xlsx`：完整人工审阅表，包含原文、原始规则、修正内容、状态和原因。",
        "- `correction_comparison.csv`、`correction_comparison.json`：同一对照表的机器可读版本。",
        "- `audit_summary.json`：本次运行统计。",
        "",
        "## 本次结果",
        "",
        f"- Excel 非空条款：{summary['expected_nonempty_clauses']}；空单元格跳过：{summary['skipped_empty_excel_cells']}。",
        f"- 新 JSON 数量：{summary['canonical_json_files']}。",
        f"- 两套既有 JSON 均存在且内容一致：{summary['both_split_content_match']}。",
        f"- 两套既有 JSON 均缺失、已按原文生成最小保真 JSON：{summary['missing_in_both_splits']}。",
        f"- `verified_structural`：{statuses.get('verified_structural', 0)}。",
        f"- `pending_semantic_review`：{statuses.get('pending_semantic_review', 0)}。",
        f"- `generated_from_source_pending_semantic_review`：{statuses.get('generated_from_source_pending_semantic_review', 0)}。",
        "",
        "## 状态定义",
        "",
        "- `verified_structural`：JSON 可解析，字段结构合法，所有规则内容合并后覆盖 Excel 原文，且首条规则具备主体和动作；这只是确定性结构核验，不等同于专家语义验收。",
        "- `pending_semantic_review`：原 JSON 可用，但规则内容合并后未完整覆盖原文或数值存在缺失；需由领域专家或可用大模型复核，不会自动虚构语义字段。",
        "- `generated_from_source_pending_semantic_review`：两套原 JSON 均不存在；已依据 Excel 原文创建最小保真规则，实体、动作、条件、关系待补充。",
        "",
        "人工修订后，应更新对应 JSON 的 `entities`、`rules`、`relations`，并在 `metadata` 中保留来源与修订理由；然后重新运行审计脚本确认覆盖状态。",
    ]
    (output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(excel: Path, source_root: Path, output: Path, overwrite: bool) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()) and not overwrite:
        raise FileExistsError(f"输出目录已存在且非空，使用--overwrite确认覆盖: {output}")
    if output.exists() and overwrite:
        shutil.rmtree(output)
    canonical_dir = output / "json"
    canonical_dir.mkdir(parents=True, exist_ok=True)
    old_files = collect_files(source_root / "output_jsons")
    new_files = collect_files(source_root / "output_jsons_new")
    frame = pd.read_excel(excel, header=None)
    rows: list[AuditRow] = []
    skipped = 0
    for index, values in frame.iterrows():
        try:
            pair_id = int(values.iloc[0])
        except (TypeError, ValueError):
            continue
        for clause_index in (1, 2):
            raw = values.iloc[clause_index]
            if pd.isna(raw) or not normalize_text(raw):
                skipped += 1
                continue
            filename = f"{pair_id}_clause{clause_index}.json"
            old, new = old_files.get(filename), new_files.get(filename)
            selected = new or old
            corrected, audit = audit_and_correct(str(raw), pair_id, clause_index, filename, index + 1, selected, old, new)
            (canonical_dir / filename).write_text(json.dumps(corrected, ensure_ascii=False, indent=2), encoding="utf-8")
            rows.append(audit)
    with (output / "correction_comparison.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].to_dict()) if rows else [])
        writer.writeheader()
        writer.writerows(row.to_dict() for row in rows)
    (output / "correction_comparison.json").write_text(json.dumps([row.to_dict() for row in rows], ensure_ascii=False, indent=2), encoding="utf-8")
    write_xlsx(rows, output / "correction_comparison.xlsx")
    statuses: dict[str, int] = {}
    for row in rows:
        statuses[row.audit_status] = statuses.get(row.audit_status, 0) + 1
    both_match = sum(row.split_content_match == "match" for row in rows)
    summary = {
        "excel": str(excel),
        "expected_nonempty_clauses": len(rows),
        "skipped_empty_excel_cells": skipped,
        "canonical_json_files": len(list(canonical_dir.glob("*.json"))),
        "both_split_content_match": both_match,
        "missing_in_both_splits": sum(not row.exists_in_output_jsons and not row.exists_in_output_jsons_new for row in rows),
        "rule_content_coverage": sum(row.rule_content_matches_source for row in rows),
        "status_counts": statuses,
        "output": str(output),
    }
    (output / "audit_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_readme(output, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="以2017.xlsx审计并规范化JSON分解数据")
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.excel, args.source_root, args.output, args.overwrite), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
