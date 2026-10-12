"""Source-bound, assistant-authored additional batch (no model/heuristic substitute)."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from .reviewed_batch import SOURCE_SHA256
from .supplemental_excel import DEFAULT_ROOT, _write_json
from .clause_filenames import clause_filename

INDEX = DEFAULT_ROOT / "子条款" / "子条款索引.jsonl"
OUTPUT = DEFAULT_ROOT / "分解数据" / "json"
QUEUE = DEFAULT_ROOT / "分解数据" / "新增1000条来源清单.json"
ANNOTATIONS = DEFAULT_ROOT / "分解数据" / "新增1000条助手语义分解.json"
BATCH = "assistant_additional1000"


def sources(index=INDEX):
    raw = Path(index).read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("来源索引已变化，需要重新核对行号")
    return [json.loads(s) for s in raw.decode("utf-8").splitlines() if s.strip()]


def existing_keys(output=OUTPUT, batch=BATCH):
    keys = set()
    for path in Path(output).glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("metadata", {}).get("batch") == batch:
            continue  # allow a verified same-batch repeat publication
        for rule in data.get("rules", []):
            keys.add((data.get("standard_id"), rule.get("content")))
    return keys


def prepare(queue=None, annotations=None, batch=BATCH):
    queue = Path(queue) if queue is not None else QUEUE
    annotations = Path(annotations) if annotations is not None else ANNOTATIONS
    if queue.exists() and annotations.exists():
        historical = json.loads(queue.read_text(encoding="utf-8"))
        authored = json.loads(annotations.read_text(encoding="utf-8"))
        if len(authored.get("items", [])) == 1000:
            if historical.get("source_index_sha256") != SOURCE_SHA256:
                raise ValueError("已有完成批次的来源清单哈希不匹配，拒绝重写历史")
            sources()  # verify that the on-disk source index is still unchanged
            return historical
    seen = existing_keys(batch=batch)
    occupied = set()
    for path in OUTPUT.glob('*.json'):
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('metadata', {}).get('batch') != batch:
            occupied.add(clause_filename(data['standard_id'], data['chapter_path']).casefold())
    items = []
    for line, source in enumerate(sources(), 1):
        text = source["text"]
        key = (source["standard_id"], text)
        if len(source["standard_id"]) > 80 or not re.search(r"\d{4}", source["standard_id"]):
            continue  # apparent body text in the identifier header is not repaired
        # A bounded pilot batch of short, independently numbered provisions.
        # This is selection only: semantic annotations are written by the assistant.
        if key in seen or not (35 <= len(text) <= 85):
            continue
        if not re.match(r"^(\d+(?:\.\d+)+)\s", text):
            continue
        if batch == BATCH and not re.search(r"应|不得|宜|必须|采用|规定|包括|按照", text):
            continue
        filename = clause_filename(source['standard_id'], text.split()[0]).casefold()
        if filename in occupied:
            continue
        occupied.add(filename)
        seen.add(key)
        items.append({"index_line": line, **source})
        if len(items) == 1000:
            break
    if len(items) != 1000:
        raise ValueError("符合筛选条件的独立子条款不足1000条")
    result = {"source_index_sha256": SOURCE_SHA256,
              "selection": "35至85字符、独立数字编号；标准编号不超过80字符且含四位数字；按来源顺序排除已入库、重复和文件名冲突；本续批纳入定义及范围条款" if batch != BATCH else "35至85字、独立数字编号、有规范性或范围描述；标准编号不超过80字且含四位数字；按来源顺序，排除已入库和本批重复",
              "stage": "selected_not_decomposed_not_published", "items": items}
    _write_json(queue, result)
    return result


def publish(index=INDEX, annotations=ANNOTATIONS, output=OUTPUT, queue=QUEUE,
            batch=BATCH, summary_name="新增1000条入库汇总.json"):
    rows = sources(index)
    review = json.loads(Path(annotations).read_text(encoding="utf-8"))
    selected = json.loads(Path(queue).read_text(encoding="utf-8"))
    if selected["source_index_sha256"] != SOURCE_SHA256:
        raise ValueError("来源清单哈希不匹配")
    items = review["items"]
    if review["method"] not in {"assistant_semantic_review", "rule_based_field_extraction_draft"}:
        raise ValueError("未知分解方法")
    if review["method"] == "rule_based_field_extraction_draft" and not review.get('draft_policy'):
        raise ValueError("规则抽取初稿必须明确记录处理策略")
    expected_count = selected.get('target_count', 1000)
    expected = {r["index_line"] for r in selected["items"]}
    if not 1 <= expected_count <= 1000 or len(selected["items"]) != expected_count or len(expected) != expected_count:
        raise ValueError("来源清单数量与目标数量不一致或存在重复原始行")
    selected_by_line = {r["index_line"]: {k: r[k] for k in ('standard_name', 'standard_id', 'text')}
                        for r in selected["items"]}
    selected_rows = {r['index_line']: r for r in selected['items']}
    if len(items) != expected_count or len({r[0] for r in items}) != expected_count or {r[0] for r in items} != expected:
        raise ValueError("分解记录必须覆盖来源清单且不能重复")
    seen = existing_keys(output, batch=batch)
    prepared = []
    for item in items:
        line, subject, operation, condition, *notes = item
        if not isinstance(line, int) or not 1 <= line <= len(rows):
            raise ValueError("来源行号越界")
        source = rows[line - 1]
        if source != selected_by_line[line]:
            raise ValueError("来源清单正文与索引不一致")
        text = source["text"]
        if not subject.strip() or not operation.strip():
            raise ValueError(f"第{line}行缺少语义对象或业务操作")
        if condition and re.sub(r"\s+", "", condition) not in re.sub(r"\s+", "", text):
            raise ValueError(f"第{line}行条件不是原文片段")
        key = (source["standard_id"], text)
        if key in seen:
            raise ValueError(f"第{line}行重复条款")
        seen.add(key)
        queued = selected_rows[line]
        number = queued.get('chapter_path')
        if not number:
            match = re.match(r"^(\d+(?:\.\d+)+)\s", text)
            if not match:
                raise ValueError(f"第{line}行没有可用章节路径")
            number = match[1]
        storage_filename = queued.get('storage_filename')
        if storage_filename:
            if (not isinstance(storage_filename, str) or not storage_filename.endswith('.json')
                    or Path(storage_filename).name != storage_filename or len(storage_filename) > 245):
                raise ValueError(f"第{line}行存储文件名无效")
            identifier = storage_filename[:-5]
        else:
            identifier = clause_filename(key[0], number)[:-5]
        reason = "助手语义初稿，尚未领域专家复核；自然语言条件与原文约束未编译为设备控制前提"
        if review['method'] == 'rule_based_field_extraction_draft':
            reason = '规则式字段抽取初稿，尚未逐条语义审定或领域专家复核；条件未编译为设备控制前提'
        if notes:
            reason += "；" + "；".join(notes)
        payload = {**{k: source[k] for k in ("standard_name", "standard_id")},
                   "version": key[0][-4:] if re.search(r"\d{4}$", key[0]) else "",
                   "chapter_path": number,
                   "entities": [{"name": subject, "type": "条款对象"}],
                   "rules": [{"content": text, "type": "语义分解", "subject": subject,
                              "action": "", "operation": operation, "condition": condition,
                              "constraint": text, "constraint_role": "informational",
                              "related_entities": [subject]}], "relations": [],
                   "metadata": {"dataset": "supplemental_excel", "batch": batch,
                                "decomposition_method": review["method"],
                                "source_index_sha256": SOURCE_SHA256, "source_index_line": line,
                                "audit": {"manual_review_required": True, "reasons": [reason]}}}
        prepared.append((identifier, payload))
    # All source, uniqueness, schema and excerpt checks precede publication.
    expected_paths = {identifier + ".json" for identifier, _ in prepared}
    if len({name.casefold() for name in expected_paths}) != expected_count:
        raise ValueError("标准编号与条款编号组成的文件名重名，拒绝覆盖")
    for existing in Path(output).glob("*.json"):
        data = json.loads(existing.read_text(encoding="utf-8"))
        if data.get("metadata", {}).get("batch") == batch and existing.name not in expected_paths:
            raise ValueError("本批已有不属于当前来源清单的文件，拒绝继续发布")
    for identifier, payload in prepared:
        path = Path(output) / (identifier + ".json")
        if path.exists() and json.loads(path.read_text(encoding="utf-8")) != payload:
            raise ValueError(f"拒绝覆盖不同内容：{path}")
    for identifier, payload in prepared:
        _write_json(Path(output) / (identifier + ".json"), payload)
    summary = {"batch": batch, "clause_count": len(prepared),
               "source_index_sha256": SOURCE_SHA256, "selection": selected["selection"],
               "method": review["method"], "standard_counts": dict(Counter(p["standard_id"] for _, p in prepared)),
               "needs_review_count": expected_count, "device_control_action_count": 0,
               "output_dir": str(Path(output).resolve()), "clause_files": [i + ".json" for i, _ in prepared]}
    _write_json(Path(output).parent / summary_name, summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description="筛选或发布助手逐条分解的新增1000条")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--next1000", action="store_true", help="处理第二批新增1000条，不覆盖前批记录")
    parser.add_argument("--show", nargs=2, type=int, metavar=("START", "COUNT"))
    args = parser.parse_args()
    queue = DEFAULT_ROOT / "分解数据" / "第二批新增1000条来源清单.json" if args.next1000 else QUEUE
    annotations = DEFAULT_ROOT / "分解数据" / "第二批新增1000条助手语义分解.json" if args.next1000 else ANNOTATIONS
    batch = "assistant_additional1000_v2" if args.next1000 else BATCH
    if args.prepare:
        result = prepare(queue, annotations, batch)
        print(json.dumps({k: v for k, v in result.items() if k != "items"}, ensure_ascii=False))
    elif args.show:
        data = json.loads(queue.read_text(encoding="utf-8"))["items"]
        start, count = args.show
        for ordinal, row in enumerate(data[start:start + count], start + 1):
            print(f'{ordinal}|{row["index_line"]}|{row["standard_id"]}|{row["text"]}')
    else:
        result = publish(annotations=annotations, queue=queue, batch=batch,
                         summary_name="第二批新增1000条入库汇总.json" if args.next1000 else "新增1000条入库汇总.json")
        print(json.dumps({k: v for k, v in result.items() if k != "clause_files"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
