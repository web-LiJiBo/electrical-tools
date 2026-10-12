import hashlib
import json
import re

import pytest

from standard_knowledge_service_v2.data_ingestion.continuous_batches import paths, prepare
from standard_knowledge_service_v2.data_ingestion.reviewed_extension import INDEX, OUTPUT, publish
from standard_knowledge_service_v2.retrieval_engine.clause_retriever import JsonClauseRepository


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def test_continuation_identity_is_loaded_independent_of_filename():
    from standard_knowledge_service_v2.data_ingestion.clause_filenames import supplemental_identity
    p = {'standard_id': 'GB/T 1-2020', 'rules': [{'content': '1.1 原文'}],
         'metadata': {'dataset': 'supplemental_excel', 'batch': 'assistant_remaining_001'}}
    assert supplemental_identity(p).startswith('supp_remaining_001_')
    assert supplemental_identity(p) == supplemental_identity(dict(p, chapter_path='1.1'))


@pytest.mark.skipif(not (OUTPUT.parent / '连续分批001入库汇总.json').exists(), reason='本地续批未发布')
def test_published_continuations_exact_sources_and_preserved_history():
    source = [json.loads(s) for s in INDEX.read_text(encoding='utf-8').splitlines()]
    repo = JsonClauseRepository.from_directory(OUTPUT)
    assert len(repo.units) == len(list(OUTPUT.glob('*.json'))) == len({u.clause_id for u in repo.units})
    for summary_path in OUTPUT.parent.glob('连续分批*入库汇总.json'):
        summary = read(summary_path)
        number = int(summary['batch'].rsplit('_', 1)[1])
        root, queue_path, annotation_path = paths(number)
        queue = read(queue_path)
        assert prepare(number) == queue
        annotations = read(annotation_path)['items']
        expected_count = queue.get('target_count', 1000)
        assert len(annotations) == len(queue['items']) == len(summary['clause_files']) == expected_count
        assert {a[0] for a in annotations} == {r['index_line'] for r in queue['items']}
        by_line = {a[0]: a for a in annotations}
        for name in summary['clause_files']:
            p = read(OUTPUT / name)
            line = p['metadata']['source_index_line']
            original = source[line - 1]
            rule = p['rules'][0]
            assert (p['standard_name'], p['standard_id']) == (original['standard_name'], original['standard_id'])
            assert rule['content'] == rule['constraint'] == original['text']
            a = by_line[line]
            assert (rule['subject'], rule['operation'], rule['condition']) == tuple(a[1:4])
            assert not rule['action'] and rule['constraint_role'] == 'informational'
            assert p['metadata']['audit']['manual_review_required']
            assert all(n in p['metadata']['audit']['reasons'][0] for n in a[4:])
            assert not rule['condition'] or re.sub(r'\s+', '', rule['condition']) in re.sub(r'\s+', '', rule['content'])
        for name, digest in read(root / '入库前哈希.json').items():
            assert hashlib.sha256((OUTPUT / name).read_bytes()).hexdigest() == digest


def test_continuation_rejects_partial_before_writing(tmp_path):
    _, queue, annotations = paths(1)
    if not annotations.exists():
        pytest.skip('本地来源清单未安装')
    review = read(annotations)
    review['items'] = review['items'][:999]
    bad = tmp_path / 'partial.json'
    bad.write_text(json.dumps(review, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(ValueError, match='分解记录必须覆盖'):
        publish(queue=queue, annotations=bad, output=tmp_path / 'json', batch='assistant_remaining_001')
    assert not (tmp_path / 'json').exists()
