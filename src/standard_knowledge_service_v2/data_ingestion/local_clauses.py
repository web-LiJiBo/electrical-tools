"""Additive local clause imports: preview, persist, then publish a prepared index."""
from copy import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
import unicodedata

from ..retrieval_engine.clause_retriever import JsonClauseRepository

STORE_PATH = Path(__file__).resolve().parents[3] / 'data/knowledge/local_clauses.json'
MAX_REQUEST = 2 * 1024 * 1024
MAX_STORE = 8 * 1024 * 1024
_lock = RLock()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')


def normalize(row):
    if not isinstance(row, dict):
        raise ValueError('每条条款必须为JSON对象。')
    limits = dict(standard_id=120, standard_name=200, version=80, clause_number=160,
                  content=20000, subject=120, action=120, condition=2000, constraint=2000)
    if set(row) - set(limits) - {'keywords'}:
        raise ValueError('条款含不支持的字段，请按格式示例导入。')
    result = {}
    for name, limit in limits.items():
        value = row.get(name, '')
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(f'{name}须为不超过{limit}字符的文本。')
        result[name] = value.strip()
    if any(not result[k] for k in ('standard_id', 'version', 'clause_number', 'content')):
        raise ValueError('请补齐标准编号、版本、条款号和条款正文。')
    keywords = row.get('keywords', [])
    if not isinstance(keywords, list) or len(keywords) > 30 or any(not isinstance(k, str) or not k.strip() or len(k) > 120 for k in keywords):
        raise ValueError('keywords须为最多30项的非空文本数组。')
    result['keywords'] = list(dict.fromkeys(k.strip() for k in keywords))
    return result


def identity(row):
    return tuple(unicodedata.normalize('NFKC', row[k]).strip().casefold()
                 for k in ('standard_id', 'version', 'clause_number'))


def read_records():
    path = Path(STORE_PATH)
    if not path.exists():
        return []
    if path.stat().st_size > MAX_STORE:
        raise ValueError('本地条款文件过大。')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('clauses'), list):
        raise ValueError('本地条款文件结构无效，原文件未修改。')
    return [normalize(r) for r in data['clauses']]


def to_unit(row):
    key = 'LOCAL-CLAUSE-' + hashlib.sha256(encode(identity(row))).hexdigest()[:24]
    names = list(dict.fromkeys([row['subject'], *row['keywords']]))
    payload = dict(standard_id=row['standard_id'], standard_name=row['standard_name'], version=row['version'],
                   chapter_path=row['clause_number'], metadata={'dataset': 'local_user_import',
                   'source': {'type': 'local_user_import', 'source_text': row['content']}},
                   entities=[{'name': n, 'type': '用户条款主题'} for n in names if n],
                   rules=[{'content': row['content'], 'subject': row['subject'], 'action': row['action'],
                           'condition': row['condition'], 'constraint': row['constraint']}])
    unit = JsonClauseRepository._from_payload(Path(STORE_PATH), payload)
    unit.clause_id = key
    for index, entity in enumerate(unit.entities):
        entity.entity_id = f'{key}:entity:{index}'
    for index, rule in enumerate(unit.rules):
        rule.rule_id = f'{key}:rule:{index}'
    return unit


def load_units():
    return [to_unit(row) for row in read_records()]


def prepare_runtime(pipeline, additions):
    from ..knowledge_graph.local_overlay import add_local_units
    from ..hybrid_reasoning.semantic_reasoner import SemanticReasoner
    retriever = pipeline.retriever.with_units(additions)
    graph = add_local_units(pipeline.knowledge_graph, additions, pipeline.retriever.repository.units)
    reasoner = copy(pipeline.reasoner)
    reasoner.semantic_reasoner = SemanticReasoner(graph)
    return retriever, graph, reasoner


def replace_file(content):
    path = Path(STORE_PATH);path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(content)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def process(pipeline, payload, *, publish=False):
    with _lock:
        try:
            if not isinstance(payload, dict) or set(payload) - {'clauses', 'revision'}:
                raise ValueError('请求须包含clauses条款数组。')
            incoming = payload.get('clauses')
            if not isinstance(incoming, list) or not 1 <= len(incoming) <= 100:
                raise ValueError('每批须包含1至100条条款。')
            rows = []
            for index, row in enumerate(incoming, 1):
                try: rows.append(normalize(row))
                except ValueError as exc: raise ValueError(f'第{index}条：{exc}') from exc
            previous = read_records()
            known = {identity(row): row for row in previous}
            # Existing datasets remain read-only. Compare the public clause identity.
            sources = {identity({'standard_id': u.standard_id, 'version': u.version, 'clause_number': u.chapter_path}): u
                       for u in pipeline.retriever.repository.units if u.metadata.get('dataset') != 'local_user_import'}
            added, conflicts, unchanged = [], [], 0
            for row in rows:
                key = identity(row);old = known.get(key);source = sources.get(key)
                if old is not None or source is not None:
                    same = row['content'] == old['content'] if old is not None else row['content'] == source.text.strip()
                    if same: unchanged += 1
                    else: conflicts.append({'standard_id': row['standard_id'], 'version': row['version'],
                           'clause_number': row['clause_number'], 'current': old['content'] if old else source.text,
                           'incoming': row['content']})
                else:
                    known[key] = row;added.append(row)
            if conflicts:
                return dict(status='conflicts', conflicts=conflicts, added=0, unchanged=unchanged,
                            errors=[{'message': '同一标准、版本及条款号内容不同；本批未保存，请核对版本或条款号。'}])
            content = encode({'schema_version': 1, 'clauses': [*previous, *added]})
            if len(content) > MAX_STORE: raise ValueError('合并后的本地条款超过8MB，请分库整理。')
            token = hashlib.sha256(encode([previous, rows])).hexdigest()
            result = dict(status='validated', revision=token, added=len(added), unchanged=unchanged,
                          clauses=rows, conflicts=[], errors=[])
            if not publish: return result
            if payload.get('revision') != token: raise ValueError('导入预览已变化，请重新预览后确认。')
            if added:
                runtime = prepare_runtime(pipeline, [to_unit(r) for r in added])
                replace_file(content)
                pipeline.retriever, pipeline.knowledge_graph, pipeline.reasoner = runtime
            return dict(result, status='published', changed=bool(added), total=len(previous)+len(added))
        except (ValueError, TypeError, OSError, KeyError, RuntimeError) as exc:
            return dict(status='invalid', errors=[{'message': str(exc)}], conflicts=[], added=0)
