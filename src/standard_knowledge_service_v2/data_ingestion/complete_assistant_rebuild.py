"""Verify complete assistant-authored coverage before changing the live snapshot.

This module does not perform semantic extraction. It only audits published
annotations, builds a complete source snapshot and activates validated data.
"""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil

from .assistant_rebuild import read_sources, SOURCE_SHA256
from .supplemental_excel import _write_json


def snapshot_digest(directory):
    """Bind both filenames and file bytes, independent of publication order."""
    hashes, total_bytes = [], 0
    for path in sorted(Path(directory).glob('*.json')):
        absolute = str(path.resolve())
        if os.name == 'nt' and not absolute.startswith('\\\\?\\'):
            absolute = ('\\\\?\\UNC\\'+absolute[2:]) if absolute.startswith('\\\\') else '\\\\?\\'+absolute
        raw = Path(absolute).read_bytes()
        total_bytes += len(raw)
        hashes.append(hashlib.sha256(path.name.encode('utf-8')+b'\0'+hashlib.sha256(raw).digest()).digest())
    return len(hashes), total_bytes, hashlib.sha256(b''.join(sorted(hashes))).hexdigest()


def coverage(index, provenance, stage, *, require_complete=False):
    rows, locations = read_sources(index, provenance)
    stage = Path(stage).resolve()
    canonical = {}
    duplicate_lines = {}
    for line, source in enumerate(rows, 1):
        key = hashlib.sha256((source['standard_id']+'\0'+source['text']).encode('utf-8')).hexdigest()
        if key not in canonical:
            canonical[key] = (line, source)
            duplicate_lines[key] = []
        else:
            duplicate_lines[key].append(line)
    seen, records, file_names = {}, [], set()
    classes = Counter()
    for path in sorted((stage/'批次记录').glob('*.json')):
        ledger = json.loads(path.read_text(encoding='utf-8'))
        summary = ledger['summary']
        if summary['source_index_sha256'] != SOURCE_SHA256 or summary['external_model_calls'] != 0:
            raise ValueError('批次来源或方法错误')
        annotation_path = stage/'语义标注'/(summary['batch'].rsplit('_', 1)[1]+'.json')
        if hashlib.sha256(annotation_path.read_bytes()).hexdigest() != ledger['annotation_sha256']:
            raise ValueError('原语义标注被修改')
        if len(ledger['records']) != summary['processed_source_rows']:
            raise ValueError('记录与汇总不一致')
        for record in ledger['records']:
            key = record['source_identity']
            if key not in canonical or key in seen:
                raise ValueError('未知来源或跨批次重复语义分解')
            line, source = canonical[key]
            if record['source_index_line'] != line or any(record[k] != source[k] for k in ('standard_id','standard_name','text')):
                raise ValueError('分解来源不是正确的新原文')
            if record['source_location'] != locations[line-1]:
                raise ValueError('Excel来源坐标不一致')
            if record['condition'] and record['condition'] not in source['text']:
                raise ValueError('条件不是原文片段')
            seen[key] = record
            record = dict(record, duplicate_source_lines=duplicate_lines[key])
            records.append(record)
            classes[record['classification']] += 1
        for filename in summary['files']:
            if filename.casefold() in file_names or Path(filename).name != filename:
                raise ValueError('文件重复或越界')
            file_names.add(filename.casefold())
    json_files = list((stage/'分解数据/json').glob('*.json'))
    if {p.name.casefold() for p in json_files} != file_names:
        raise ValueError('暂存库存在遗漏或孤立文件')
    published_keys = set()
    for path in json_files:
        payload = json.loads(path.read_text(encoding='utf-8'))
        key = payload['metadata']['source_identity']
        if key not in seen or key in published_keys:
            raise ValueError('JSON来源未分类或重复发布')
        classified = seen[key]
        if classified['classification'] not in ('normative','definition','scope'):
            raise ValueError('标题或缺失上下文被作为判定规则发布')
        if payload['metadata']['decomposition_method'] != 'assistant_authored_semantic_decomposition':
            raise ValueError('不接受规则抽取冒充语义分解')
        if not payload['metadata']['audit']['manual_review_required']:
            raise ValueError('未经专家审查不得移除待复核标记')
        if len(payload['rules']) != 1:
            raise ValueError('本次发布必须保留一条完整来源规则')
        rule = payload['rules'][0]
        for output_key, record_key in (('content','text'),('subject','subject'),('operation','operation'),('condition','condition')):
            if rule[output_key] != classified[record_key]:
                raise ValueError('JSON语义字段与标注不一致')
        if rule['constraint'] != classified['text'] or rule['action']:
            raise ValueError('原文约束缺失或出现未授权设备控制动作')
        if payload['standard_id'] != classified['standard_id'] or payload['standard_name'] != classified['standard_name']:
            raise ValueError('标准身份不一致')
        published_keys.add(key)
    expected_published = {key for key, record in seen.items() if record['classification'] in ('normative','definition','scope')}
    if published_keys != expected_published:
        raise ValueError('可发布分类未完整生成JSON')
    result = dict(source_rows=len(rows), unique_sources=len(canonical),
        duplicate_source_rows=sum(map(len, duplicate_lines.values())),
        completed_unique_sources=len(seen), remaining_unique_sources=len(canonical)-len(seen),
        classifications=dict(classes), staged_json_count=len(json_files),
        complete=len(seen)==len(canonical), records=sorted(records,key=lambda r:r['source_index_line']))
    if require_complete and not result['complete']:
        raise ValueError(f"仍有{result['remaining_unique_sources']}条唯一来源未完成，禁止替换数据库")
    return result


def build_snapshot(index, provenance, stage, prepared):
    result = coverage(index, provenance, stage, require_complete=True)
    prepared = Path(prepared).resolve()
    if prepared.exists():
        raise ValueError('新快照目录已存在，禁止覆盖')
    source = Path(stage)/'分解数据/json'
    shutil.copytree(source, prepared/'分解数据/json')
    # Keep the actual authored annotations and ledgers outside the runtime JSON
    # directory, so activation can independently repeat the complete audit.
    shutil.copytree(Path(stage)/'语义标注', prepared/'语义标注')
    shutil.copytree(Path(stage)/'批次记录', prepared/'批次记录')
    location = prepared/'子条款'
    location.mkdir()
    shutil.copyfile(index, location/'子条款索引.jsonl')
    shutil.copyfile(provenance, location/'来源追溯.jsonl')
    with (location/'来源分类及重复追溯.jsonl').open('w',encoding='utf-8') as stream:
        for record in result['records']:
            stream.write(json.dumps(record,ensure_ascii=False)+'\n')
    from ..retrieval_engine.clause_retriever import JsonClauseRepository
    repo = JsonClauseRepository.from_directory(prepared/'分解数据/json')
    if len(repo.units) != result['staged_json_count'] or len({u.clause_id for u in repo.units}) != len(repo.units):
        raise ValueError('新快照不能完整加载或存在ID冲突')
    _, total_bytes, digest = snapshot_digest(prepared/'分解数据/json')
    manifest = dict(snapshot_date='2026-10-13', source='处理数据.rar公共标准格式优选后的Excel，助手逐条语言语义分解',
        source_index_sha256=SOURCE_SHA256, repository_directory='datasets/supplemental/分解数据/json',
        original_database_unchanged=True, file_count=len(repo.units), rule_count=len(repo.units),
        unique_clause_ids=len(repo.units), total_bytes=total_bytes,
        source_rows=result['source_rows'],unique_source_records=result['unique_sources'],
        duplicate_source_rows=result['duplicate_source_rows'], classifications=result['classifications'],
        manual_review_required_count=len(repo.units), all_json_valid=True,
        sorted_record_hashes_sha256=digest,
        decomposition_method='assistant_authored_semantic_decomposition', external_model_calls=0,
        enterprise_standards_excluded=True, publication_status='本地完整快照已校验，未提交或推送远端',
        limitations='助手语义分解不等于领域专家审定、标准有效性核验或控制授权；标题及缺上下文内容仅保留来源记录')
    _write_json(prepared/'publish_manifest.json',manifest)
    return manifest


def activate(prepared, repository, rollback_name):
    """Recoverable same-parent swaps, restricted to the exact configured dataset."""
    prepared, repository = Path(prepared).resolve(), Path(repository).resolve()
    live = repository/'datasets/supplemental'
    if not prepared.is_dir() or prepared.parent != live.parent or prepared == live:
        raise ValueError('完整快照必须位于datasets目录下独立暂存目录')
    if Path(rollback_name).name != rollback_name or not rollback_name.startswith('supplemental_rollback_'):
        raise ValueError('非法回退目录名称')
    rollback = live.parent/rollback_name
    if rollback.exists() or not live.is_dir():
        raise ValueError('回退目标已存在或旧库丢失')
    manifest = json.loads((prepared/'publish_manifest.json').read_text(encoding='utf-8'))
    if manifest.get('source_index_sha256') != SOURCE_SHA256:
        raise ValueError('快照不是新来源')
    audited = coverage(prepared/'子条款/子条款索引.jsonl',
                       prepared/'子条款/来源追溯.jsonl', prepared, require_complete=True)
    count, total_bytes, digest = snapshot_digest(prepared/'分解数据/json')
    if (count != manifest['file_count'] or total_bytes != manifest['total_bytes'] or
            digest != manifest['sorted_record_hashes_sha256'] or
            audited['unique_sources'] != manifest['unique_source_records'] or
            audited['classifications'] != manifest['classifications']):
        raise ValueError('完整快照与清单不一致，禁止替换数据库')
    from ..retrieval_engine.clause_retriever import JsonClauseRepository
    old_original = JsonClauseRepository.from_directory(repository/'datasets/lunwen/verified_json/json')
    new = JsonClauseRepository.from_directory(prepared/'分解数据/json')
    if len(new.units) != manifest['file_count'] or {u.clause_id for u in old_original.units}&{u.clause_id for u in new.units}:
        raise ValueError('完整加载失败或与原始库ID冲突')
    # All targets were resolved and checked above; no delete or recursive move.
    live.rename(rollback)
    try:
        prepared.rename(live)
    except Exception:
        rollback.rename(live)
        raise
    return dict(live=str(live),rollback=str(rollback),new_file_count=len(new.units),original_library_units=len(old_original.units))


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--index',type=Path,required=True)
    parser.add_argument('--provenance',type=Path,required=True)
    parser.add_argument('--stage',type=Path,required=True)
    parser.add_argument('--require-complete',action='store_true')
    parser.add_argument('--prepare',type=Path)
    parser.add_argument('--progress', type=Path)
    args=parser.parse_args()
    result=build_snapshot(args.index,args.provenance,args.stage,args.prepare) if args.prepare else coverage(args.index,args.provenance,args.stage,require_complete=args.require_complete)
    compact = {k:v for k,v in result.items() if k!='records'}
    if args.progress:
        _write_json(args.progress, dict(compact, source_index_sha256=SOURCE_SHA256,
            decomposition_method='assistant_authored_semantic_decomposition',
            external_model_calls=0, publication_status='暂存核验，不代表正式库已替换'))
    print(json.dumps(compact,ensure_ascii=False))
