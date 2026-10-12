"""Publish the assistant-reviewed 100-clause batch to the independent JSON store.

Semantic judgements are authored in the reviewed annotation file, not generated
by keyword heuristics or a substituted external model. Original text is copied
verbatim from the exact, hash-bound source index.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from .supplemental_excel import DEFAULT_ROOT, _write_json
from .clause_filenames import clause_filename


SOURCE_SHA256 = "4ef6d9ea4832d6df7617e8acfd73004caab9f714ad792c0e490fa383c258aaf4"


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def publish_reviewed_batch(index: Path, annotations: Path, output: Path) -> dict:
    index, annotations, output = (Path(p).resolve() for p in (index, annotations, output))
    raw = index.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("来源索引已变化，不能按旧行号套用语义分解，请重新核对样本")
    reviewed = json.loads(annotations.read_text(encoding="utf-8"))
    items = reviewed["items"]
    if len(items) != 100 or len({item[0] for item in items}) != 100:
        raise ValueError("首批必须为100个不同的来源条款")
    sources = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    prepared = []
    for line, subject, operation, condition, quote, reason in items:
        source = sources[line - 1]
        text = source["text"]
        clause_number = re.match(r"^(\d+(?:\.\d+)+)\s", text)
        if not clause_number:
            raise ValueError(f"第{line}行缺少样本约定的原始条款编号")
        for field, value in (("condition", condition), ("constraint_quote", quote)):
            if value and _compact(value) not in _compact(text):
                raise ValueError(f"第{line}行{field}不是原文片段：{value}")
        identifier = clause_filename(source["standard_id"], clause_number[1])[:-5]
        # Business/data operations are distinct from device-control action codes.
        # None of this reviewed sample authorizes a direct device-control action.
        rule = {"content": text, "type": "语义分解",
                "subject": subject, "action": "", "operation": operation,
                "condition": condition, "constraint": quote,
                "constraint_role": "informational" if reason else "unspecified",
                "related_entities": [subject]}
        payload = {"standard_name": source["standard_name"],
                   "standard_id": source["standard_id"],
                   "version": source["standard_id"][-4:] if re.search(r"\d{4}$", source["standard_id"]) else "",
                   "chapter_path": clause_number[1],
                   "entities": [{"name": subject, "type": "条款对象"}],
                   "rules": [rule], "relations": [],
                   "metadata": {"dataset": "supplemental_excel", "batch": "assistant_first100",
                                "decomposition_method": reviewed["method"],
                                "audit": {"manual_review_required": bool(reason),
                                          "reasons": [reason] if reason else []}}}
        prepared.append((identifier, payload))
    if len({i for i, _ in prepared}) != 100:
        raise ValueError("样本存在相同标准编号和正文的重复条款")
    # Validate the entire batch before publishing any file.
    if len({i.casefold() for i, _ in prepared}) != 100:
        raise ValueError("标准编号与条款编号组成的文件名重名，拒绝覆盖")
    for identifier, payload in prepared:
        path = output / (identifier + ".json")
        if path.exists() and json.loads(path.read_text(encoding="utf-8")) != payload:
            raise ValueError(f"拒绝覆盖不同内容：{path}")
    for identifier, payload in prepared:
        _write_json(output / (identifier + ".json"), payload)
    summary = {"batch": "assistant_first100", "clause_count": len(prepared),
               "source_index_sha256": SOURCE_SHA256,
               "standard_counts": dict(Counter(p["standard_id"] for _, p in prepared)),
               "needs_review_count": sum(p["metadata"]["audit"]["manual_review_required"] for _, p in prepared),
               "device_control_action_count": 0, "output_dir": str(output),
               "clause_files": [i + ".json" for i, _ in prepared]}
    _write_json(output.parent / "首批100条入库汇总.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="发布已由助手逐条语义分解的100条补充条款")
    parser.add_argument("--index", type=Path, default=DEFAULT_ROOT / "子条款" / "子条款索引.jsonl")
    parser.add_argument("--annotations", type=Path, default=DEFAULT_ROOT / "分解数据" / "首批100条助手语义分解.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_ROOT / "分解数据" / "json")
    args = parser.parse_args()
    summary = publish_reviewed_batch(args.index, args.annotations, args.output)
    print(json.dumps({k: v for k, v in summary.items() if k != "clause_files"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
