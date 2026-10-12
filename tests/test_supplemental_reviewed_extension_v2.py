"""Second continuation: exact sources, preserved history, unique loading and safe publication."""
import hashlib
import json
from pathlib import Path

import pytest

from standard_knowledge_service_v2.bootstrap import build_application
from standard_knowledge_service_v2.data_ingestion.clause_filenames import clause_filename
from standard_knowledge_service_v2.data_ingestion.reviewed_extension import INDEX, OUTPUT, publish
from standard_knowledge_service_v2.retrieval import LunwenMatchingInput
from standard_knowledge_service_v2.retrieval_engine.clause_retriever import JsonClauseRepository

ROOT = Path(__file__).resolve().parents[1]
QUEUE = OUTPUT.parent / '第二批新增1000条来源清单.json'
ANNOTATIONS = OUTPUT.parent / '第二批新增1000条助手语义分解.json'
BATCH = 'assistant_additional1000_v2'
pytestmark = pytest.mark.skipif(not ANNOTATIONS.exists(), reason='本地第二批新增数据未安装')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def test_all_thousand_sources_and_authored_semantics_are_exact():
    rows = [json.loads(s) for s in INDEX.read_text(encoding='utf-8').splitlines()]
    queue = load(QUEUE)
    assert hashlib.sha256(INDEX.read_bytes()).hexdigest() == queue['source_index_sha256']
    selected = queue['items']
    authored = load(ANNOTATIONS)
    assert authored['method'] == 'assistant_semantic_review'
    items = authored['items']
    payloads = [load(p) for p in OUTPUT.glob('*.json')]
    current = [p for p in payloads if p['metadata']['batch'] == BATCH]
    assert len(selected) == len(items) == len(current) == 1000
    keyed = {p['metadata']['source_index_line']: p for p in current}
    assert set(keyed) == {p['index_line'] for p in selected} == {a[0] for a in items}
    assert len(keyed) == 1000
    for line, subject, operation, condition, *notes in items:
        source = rows[line - 1]
        p = keyed[line]
        assert (p['standard_name'], p['standard_id']) == (source['standard_name'], source['standard_id'])
        assert p['chapter_path'] == source['text'].split()[0]
        rule = p['rules'][0]
        assert rule['content'] == rule['constraint'] == source['text']
        assert (rule['subject'], rule['operation'], rule['condition']) == (subject, operation, condition)
        assert rule['action'] == '' and rule['constraint_role'] == 'informational'
        assert p['metadata']['audit']['manual_review_required'] is True
        assert all(n in p['metadata']['audit']['reasons'][0] for n in notes)
        assert (OUTPUT / clause_filename(p['standard_id'], p['chapter_path'])).exists()
    historical = [p for p in payloads if p['metadata']['batch'] in
                  {'assistant_first100', 'assistant_additional1000', BATCH}]
    assert len(historical) == 2100
    assert len({(p['standard_id'], p['rules'][0]['content']) for p in payloads}) == len(payloads)
    assert len({p.name.casefold() for p in OUTPUT.glob('*.json')}) == len(payloads)


def test_previous_1100_file_bytes_are_unchanged():
    report = load(OUTPUT.parent / 'JSON文件重命名记录.json')
    assert len(report['items']) == 1100
    for item in report['items']:
        assert hashlib.sha256((OUTPUT / item['new_name']).read_bytes()).hexdigest() == item['sha256']


def test_unified_8774_unique_units_and_new_clause_retrieval():
    app = build_application(ROOT / 'configs/settings.offline.yaml')
    repo = app.facade.retriever.repository
    original = JsonClauseRepository.from_directory(ROOT / 'datasets/lunwen/verified_json/json')
    assert len(original.units) == 6674
    supplemental_count = len(list(OUTPUT.glob('*.json')))
    assert len(repo.units) == len({u.clause_id for u in repo.units}) == 6674 + supplemental_count
    added = [u for u in repo.units if u.metadata.get('batch') == BATCH]
    assert len(added) == 1000
    assert not {(u.standard_id, u.text) for u in original.units}.intersection(
        {(u.standard_id, u.text) for u in added})
    result = app.facade.retriever.match(LunwenMatchingInput(
        '安全防范系统误报警对未设计的事件做出响应',
        {'entities': [{'name': '误报警', 'type': '条款对象'}],
         'keywords': ['未设计的事件', '误报警']}, top_k_rules=10))
    hits = [repo.unit_for_rule(r.rule.rule_id) for r in result.rules]
    assert any(u.metadata.get('batch') == BATCH and u.standard_id == 'GB 50348-2018'
               and u.chapter_path == '2.0.28' for u in hits)


def test_repeat_publication_and_invalid_condition_preflight(tmp_path):
    kwargs = dict(queue=QUEUE, annotations=ANNOTATIONS, batch=BATCH,
                  summary_name='第二批新增1000条入库汇总.json')
    output = tmp_path / 'json'
    first = publish(output=output, **kwargs)
    assert first == publish(output=output, **kwargs)
    assert len(list(output.glob('*.json'))) == 1000
    invalid = load(ANNOTATIONS)
    invalid['items'][-1][3] = '不存在于原文的虚构控制阈值'
    bad = tmp_path / 'invalid.json'
    bad.write_text(json.dumps(invalid, ensure_ascii=False), encoding='utf-8')
    kwargs['annotations'] = bad
    with pytest.raises(ValueError, match='条件不是原文片段'):
        publish(output=tmp_path / 'empty', **kwargs)
    assert not (tmp_path / 'empty').exists()
