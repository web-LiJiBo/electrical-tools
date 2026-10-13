"""Publish manually authored semantic batches for the corrected Excel source.

No text-to-semantics heuristic or paid API is used here. The assistant must
read each source and author a classification/semantic record. Publishing a
batch only writes staging data; replacing the live database is a separate
operation after every unique source record has been accounted for.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from .clause_filenames import clause_filename
from .supplemental_excel import _write_json

SOURCE_SHA256 = '5ff128023585dd00c41144f4fde374886c4bd34842a832712ee55529adea9e09'


def read_sources(index, provenance):
    raw = Path(index).read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError('新来源索引哈希变化，必须重新核对')
    rows = [json.loads(line) for line in raw.decode('utf-8').splitlines()]
    trace = [json.loads(line) for line in Path(provenance).read_text(encoding='utf-8').splitlines()]
    if len(rows) != len(trace):
        raise ValueError('原文与追溯行数不一致')
    return rows, trace


def publish(index, provenance, annotations, stage):
    rows, trace = read_sources(index, provenance)
    # Global, content-distinct numbering conflicts get deterministic filenames
    # before parallel batches write; scheduling order cannot choose the winner.
    number_contents = {}
    for row in rows:
        number = re.match(r'^\s*(\d+(?:\.\d+)*)(?=\s|[\u4e00-\u9fff])', row['text'])
        if number:
            number_contents.setdefault((row['standard_id'], number[1]), set()).add(row['text'])
    annotation_raw = Path(annotations).read_bytes()
    annotation_sha256 = hashlib.sha256(annotation_raw).hexdigest()
    annotations = json.loads(annotation_raw)
    if annotations.get('method') != 'assistant_authored_semantic_decomposition':
        raise ValueError('只接受助手实际阅读后撰写的语义记录，不运行自动抽取')
    if annotations.get('source_index_sha256') != SOURCE_SHA256:
        raise ValueError('语义标注没有绑定新索引')
    batch = annotations['batch']
    if not re.fullmatch(r'assistant_processed_20261013_\d{3}', batch):
        raise ValueError('非法重建批号')
    expected = annotations['source_lines']
    items = annotations['items']
    if (len(expected) != len(set(expected)) or len(items) != len(expected) or
            {item[0] for item in items} != set(expected) or len({item[0] for item in items}) != len(items)):
        raise ValueError('语义标注必须完整覆盖批次来源且不能重复')
    stage = Path(stage).resolve()
    json_dir = stage/'分解数据/json'
    ledger = stage/'批次记录'/f'{batch}.json'
    if ledger.exists():
        previous = json.loads(ledger.read_text(encoding='utf-8'))
        if previous.get('annotation_sha256') != annotation_sha256:
            raise ValueError('已有批次标注不一致，拒绝覆盖')
        for name in previous['summary']['files']:
            if not (json_dir/name).is_file():
                raise ValueError('已发布批次文件缺失')
        return previous['summary']
    prepared, classified, occupied = [], [], set()
    for item in items:
        line, kind, subject, operation, condition, *notes = item
        if type(line) is not int or not 1 <= line <= len(rows):
            raise ValueError('来源行号越界')
        source, location = rows[line-1], trace[line-1]
        text = source['text']
        if kind not in ('heading', 'normative', 'definition', 'scope', 'context_required'):
            raise ValueError('未知语义分类')
        if not isinstance(condition, str) or (condition and condition not in text):
            raise ValueError(f'第{line}行条件必须为原文连续片段')
        if not subject.strip() or not operation.strip():
            raise ValueError('标注对象和要求不能为空')
        numbered = re.match(r'^\s*(\d+(?:\.\d+)*)(?=\s|[\u4e00-\u9fff])', text)
        chapter = numbered[1] if numbered else f'来源行-{line:08d}'
        identity = hashlib.sha256((source['standard_id']+'\0'+text).encode('utf-8')).hexdigest()
        record = dict(source_index_line=line, source_identity=identity, **source,
                      classification=kind, subject=subject, operation=operation,
                      condition=condition, notes=notes, source_location=location)
        classified.append(record)
        if kind in ('heading', 'context_required'):
            continue
        storage_chapter = chapter
        if len(number_contents.get((source['standard_id'], chapter), set())) > 1:
            storage_chapter += f' 来源行-{line:08d}'
        filename = clause_filename(source['standard_id'], storage_chapter)
        # Do not silently overwrite independent rows sharing a source number.
        if filename.casefold() in occupied or (json_dir/filename).exists():
            filename = clause_filename(source['standard_id'], chapter+f' 来源行-{line:08d}')
        if filename.casefold() in occupied:
            raise ValueError('同号异文文件名冲突')
        occupied.add(filename.casefold())
        payload = dict(standard_name=source['standard_name'], standard_id=source['standard_id'],
            version=source['standard_id'][-4:], chapter_path=chapter,
            entities=[dict(name=subject, type='条款对象')],
            rules=[dict(content=text, type='语义分解', subject=subject, action='',
                operation=operation, condition=condition, constraint=text,
                constraint_role='compliance' if kind=='normative' else 'informational', related_entities=[subject])],
            relations=[], metadata=dict(dataset='processed_public_standard_excel', batch=batch,
                decomposition_method=annotations['method'], source_index_sha256=SOURCE_SHA256,
                source_index_line=line, source_identity=identity, source_location=location,
                classification=kind, original_clause_number=numbered[1] if numbered else '',
                audit=dict(manual_review_required=True,
                    reasons=['助手已进行语言语义分解；尚未领域专家审定，未核验全部标准现行性；自然语言条件未编译为控制前提']+notes)))
        prepared.append((filename, payload))
    report = dict(batch=batch, source_index_sha256=SOURCE_SHA256, processed_source_rows=len(items),
        classification_counts=dict(Counter(row['classification'] for row in classified)),
        staged_json_count=len(prepared), external_model_calls=0, live_database_replaced=False,
        original_database_changed=False, files=[name for name,_ in prepared])
    # Check the entire batch before any staging write.
    for name, payload in prepared:
        if (json_dir/name).exists():
            raise ValueError('暂存文件已有不同批次，拒绝覆盖')
    for name, payload in prepared:
        _write_json(json_dir/name, payload)
    _write_json(ledger, dict(annotation_sha256=annotation_sha256, summary=report, records=classified))
    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--provenance', type=Path, required=True)
    parser.add_argument('--annotations', type=Path, required=True)
    parser.add_argument('--stage', type=Path, required=True)
    args = parser.parse_args()
    result = publish(args.index, args.provenance, args.annotations, args.stage)
    print(json.dumps({k:v for k,v in result.items() if k!='files'}, ensure_ascii=False))
