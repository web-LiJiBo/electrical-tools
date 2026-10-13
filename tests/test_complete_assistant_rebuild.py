import hashlib
import json

import pytest

from standard_knowledge_service_v2.data_ingestion import assistant_rebuild as author
from standard_knowledge_service_v2.data_ingestion import complete_assistant_rebuild as finalizer


@pytest.fixture
def authored_stage(tmp_path, monkeypatch):
    rows = [dict(standard_id='TEST-2026', standard_name='试验', text='1 章节'),
            dict(standard_id='TEST-2026', standard_name='试验', text='1.1 发生事故后及时报告。'),
            dict(standard_id='TEST-2026', standard_name='试验', text='1.1 发生事故后及时报告。')]
    index, trace = tmp_path/'index.jsonl', tmp_path/'trace.jsonl'
    index.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows), encoding='utf-8')
    trace.write_text(''.join(json.dumps(dict(source='test.xlsx', source_row=i+3, sheet='Sheet1', source_sha256='test'))+'\n' for i in range(3)), encoding='utf-8')
    digest = hashlib.sha256(index.read_bytes()).hexdigest()
    monkeypatch.setattr(author, 'SOURCE_SHA256', digest)
    monkeypatch.setattr(finalizer, 'SOURCE_SHA256', digest)
    stage = tmp_path/'stage'
    (stage/'语义标注').mkdir(parents=True)
    annotation = stage/'语义标注/001.json'
    annotation.write_text(json.dumps(dict(method='assistant_authored_semantic_decomposition',
        batch='assistant_processed_20261013_001', source_index_sha256=digest,
        source_lines=[1, 2], items=[[1, 'heading', '章节', '组织章节', ''],
            [2, 'normative', '事故报告', '及时报告', '发生事故后']]), ensure_ascii=False), encoding='utf-8')
    author.publish(index, trace, annotation, stage)
    return index, trace, stage, tmp_path


def test_coverage_counts_duplicates_without_duplicate_rules(authored_stage):
    index, trace, stage, _ = authored_stage
    report = finalizer.coverage(index, trace, stage, require_complete=True)
    assert report['source_rows'] == 3
    assert report['unique_sources'] == 2
    assert report['duplicate_source_rows'] == 1
    assert report['staged_json_count'] == 1
    assert report['records'][1]['duplicate_source_lines'] == [3]


def test_complete_gate_rejects_missing_sources(authored_stage):
    index, trace, _, root = authored_stage
    with pytest.raises(ValueError, match='禁止替换'):
        finalizer.coverage(index, trace, root/'empty', require_complete=True)
    with pytest.raises(ValueError):
        finalizer.build_snapshot(index, trace, root/'empty', root/'prepared')
    assert not (root/'prepared').exists()


@pytest.mark.parametrize('field', ['content', 'action', 'subject'])
def test_modified_json_rejected(authored_stage, field):
    index, trace, stage, _ = authored_stage
    target = next((stage/'分解数据/json').glob('*.json'))
    payload = json.loads(target.read_text(encoding='utf-8'))
    payload['rules'][0][field] = 'modified'
    target.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(ValueError):
        finalizer.coverage(index, trace, stage)


def test_annotation_hash_rejected(authored_stage):
    index, trace, stage, _ = authored_stage
    annotation = stage/'语义标注/001.json'
    annotation.write_text(annotation.read_text(encoding='utf-8')+' ', encoding='utf-8')
    with pytest.raises(ValueError, match='原语义标注'):
        finalizer.coverage(index, trace, stage)


def test_prepared_snapshot_reaudited_and_recoverable_swap(authored_stage):
    index, trace, stage, root = authored_stage
    repository = root/'repository'
    original = repository/'datasets/lunwen/verified_json/json'
    original.mkdir(parents=True)
    live = repository/'datasets/supplemental'
    live.mkdir()
    (live/'old.txt').write_text('retained', encoding='utf-8')
    prepared = repository/'datasets/prepared'
    manifest = finalizer.build_snapshot(index, trace, stage, prepared)
    assert manifest['file_count'] == 1
    assert (prepared/'语义标注/001.json').is_file()
    result = finalizer.activate(prepared, repository, 'supplemental_rollback_test')
    assert result['new_file_count'] == 1
    assert (repository/'datasets/supplemental_rollback_test/old.txt').read_text() == 'retained'
    assert (live/'publish_manifest.json').is_file()
    assert not prepared.exists()


def test_activation_rejects_changed_manifest_before_live_move(authored_stage):
    index, trace, stage, root = authored_stage
    repository = root/'repository'
    (repository/'datasets/lunwen/verified_json/json').mkdir(parents=True)
    live = repository/'datasets/supplemental'
    live.mkdir()
    prepared = repository/'datasets/prepared'
    manifest = finalizer.build_snapshot(index, trace, stage, prepared)
    manifest['sorted_record_hashes_sha256'] = 'changed'
    (prepared/'publish_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='清单不一致'):
        finalizer.activate(prepared, repository, 'supplemental_rollback_test')
    assert live.is_dir()
    assert prepared.is_dir()
    assert not (repository/'datasets/supplemental_rollback_test').exists()
