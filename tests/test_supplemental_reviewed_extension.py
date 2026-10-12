import hashlib
import json
from pathlib import Path

import pytest

from standard_knowledge_service_v2.bootstrap import build_application
from standard_knowledge_service_v2.data_ingestion.reviewed_batch import SOURCE_SHA256
from standard_knowledge_service_v2.data_ingestion.reviewed_extension import (
    ANNOTATIONS, BATCH, INDEX, OUTPUT, QUEUE, publish,
)
from standard_knowledge_service_v2.retrieval import LunwenMatchingInput
from standard_knowledge_service_v2.retrieval_engine.clause_retriever import JsonClauseRepository

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not ANNOTATIONS.exists(), reason='本地新增1000条补充数据未安装')


def test_extension_preserves_all_thousand_source_rows_and_semantics():
    assert hashlib.sha256(INDEX.read_bytes()).hexdigest() == SOURCE_SHA256
    rows = [json.loads(line) for line in INDEX.read_text(encoding='utf-8').splitlines()]
    items = json.loads(ANNOTATIONS.read_text(encoding='utf-8'))['items']
    selected = json.loads(QUEUE.read_text(encoding='utf-8'))['items']
    payloads = [json.loads(p.read_text(encoding='utf-8')) for p in OUTPUT.glob('*.json')]
    payloads = [p for p in payloads if p.get('metadata', {}).get('batch') == BATCH]
    assert len(items) == len(selected) == len(payloads) == 1000
    keyed = {p['metadata']['source_index_line']: p for p in payloads}
    assert len(keyed) == 1000
    assert set(keyed) == {r['index_line'] for r in selected}
    for line, subject, operation, condition, *notes in items:
        source = rows[line - 1]
        payload = keyed[line]
        assert payload['standard_name'] == source['standard_name']
        assert payload['standard_id'] == source['standard_id']
        assert payload['chapter_path'] == source['text'].split()[0]
        rule = payload['rules'][0]
        assert rule['content'] == rule['constraint'] == source['text']
        assert (rule['subject'], rule['operation'], rule['condition']) == (subject, operation, condition)
        assert rule['action'] == ''
        assert rule['constraint_role'] == 'informational'
        assert payload['metadata']['decomposition_method'] == 'assistant_semantic_review'
        assert payload['metadata']['batch'] == BATCH
        assert payload['metadata']['audit']['manual_review_required'] is True
        assert all(note in payload['metadata']['audit']['reasons'][0] for note in notes)
    old = [json.loads(p.read_text(encoding='utf-8')) for p in OUTPUT.glob('*.json')]
    old = [p for p in old if p.get('metadata', {}).get('batch') == 'assistant_first100']
    assert len(old) == 100
    combined = [(p['standard_id'], p['rules'][0]['content']) for p in old + payloads]
    assert len(set(combined)) == 1100


def test_unified_loader_counts_and_new_device_clause_retrieval():
    app = build_application(ROOT / 'configs/settings.offline.yaml')
    repo = app.facade.retriever.repository
    original = JsonClauseRepository.from_directory(ROOT / 'datasets/lunwen/verified_json/json')
    assert len(original.units) == 6674
    supplemental = JsonClauseRepository.from_directory(OUTPUT)
    assert len(repo.units) == 6674 + len(supplemental.units)
    assert sum(u.metadata.get('dataset') == 'supplemental_excel' for u in repo.units) == len(supplemental.units)
    assert sum(u.metadata.get('batch') == BATCH for u in repo.units) == 1000
    assert len({u.clause_id for u in repo.units}) == len(repo.units)
    original_keys = {(u.standard_id, u.text) for u in original.units}
    new_keys = {(u.standard_id, u.text) for u in repo.units if u.metadata.get('batch') == BATCH}
    assert not original_keys.intersection(new_keys)
    result = app.facade.retriever.match(LunwenMatchingInput(
        '空气压缩机仪表风管网联锁装置压力降低自动启动',
        {'entities': [{'name': '空气压缩机', 'type': '设备'}],
         'keywords': ['仪表风管网', '联锁装置', '自动启动']}, top_k_rules=10))
    hits = [repo.unit_for_rule(r.rule.rule_id) for r in result.rules]
    assert any(u.metadata.get('batch') == BATCH and u.standard_id == 'AQ 2012-2007'
               and u.chapter_path == '5.8.3.3' for u in hits)
    assert all(r.rule.action == '' for r in result.rules
               if repo.unit_for_rule(r.rule.rule_id).metadata.get('batch') == BATCH)


def test_repeat_publish_is_idempotent_and_invalid_annotations_publish_nothing(tmp_path):
    output = tmp_path / 'json'
    first = publish(output=output)
    second = publish(output=output)
    assert first == second
    assert len(list(output.glob('*.json'))) == 1000
    invalid = json.loads(ANNOTATIONS.read_text(encoding='utf-8'))
    invalid['items'][-1][3] = 'source does not contain this fabricated threshold'
    bad = tmp_path / 'invalid.json'
    bad.write_text(json.dumps(invalid, ensure_ascii=False), encoding='utf-8')
    empty_output = tmp_path / 'invalid_output'
    with pytest.raises(ValueError, match='条件不是原文片段'):
        publish(annotations=bad, output=empty_output)
    assert not empty_output.exists()


def test_conflicting_payload_is_not_overwritten_and_bad_count_is_rejected(tmp_path):
    output = tmp_path / 'json'
    summary = publish(output=output)
    target = output / summary['clause_files'][0]
    altered = json.loads(target.read_text(encoding='utf-8'))
    altered['standard_name'] = 'locally edited name'
    target.write_text(json.dumps(altered), encoding='utf-8')
    with pytest.raises(ValueError, match='拒绝覆盖不同内容'):
        publish(output=output)
    assert json.loads(target.read_text(encoding='utf-8'))['standard_name'] == 'locally edited name'
    incomplete = json.loads(ANNOTATIONS.read_text(encoding='utf-8'))
    incomplete['items'].pop()
    bad = tmp_path / 'incomplete.json'
    bad.write_text(json.dumps(incomplete, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(ValueError, match='1000条'):
        publish(annotations=bad, output=tmp_path / 'empty')
    assert not (tmp_path / 'empty').exists()


def test_extra_queue_rows_and_stale_batch_files_are_rejected(tmp_path):
    selected = json.loads(QUEUE.read_text(encoding='utf-8'))
    selected['items'].append(selected['items'][0])
    bad = tmp_path / 'bad_queue.json'
    bad.write_text(json.dumps(selected, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(ValueError, match='来源清单必须有1000条'):
        publish(queue=bad, output=tmp_path / 'empty')
    assert not (tmp_path / 'empty').exists()
    stale_output = tmp_path / 'stale_output'
    stale_output.mkdir()
    (stale_output / 'unknown.json').write_text(json.dumps({'metadata': {'batch': BATCH}}), encoding='utf-8')
    with pytest.raises(ValueError, match='不属于当前来源清单'):
        publish(output=stale_output)
    assert len(list(stale_output.glob('*.json'))) == 1


def test_completed_source_queue_is_not_reselected_or_overwritten(tmp_path, monkeypatch):
    from standard_knowledge_service_v2.data_ingestion import reviewed_extension as module
    queue = tmp_path / 'queue.json'
    authored = tmp_path / 'annotations.json'
    queue.write_bytes(QUEUE.read_bytes())
    authored.write_bytes(ANNOTATIONS.read_bytes())
    before = queue.read_bytes()
    monkeypatch.setattr(module, 'QUEUE', queue)
    monkeypatch.setattr(module, 'ANNOTATIONS', authored)
    def forbidden():
        raise AssertionError('Completed historical selection must not run again')
    monkeypatch.setattr(module, 'existing_keys', forbidden)
    result = module.prepare()
    assert len(result['items']) == 1000
    assert queue.read_bytes() == before
