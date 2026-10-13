import hashlib
import json
from pathlib import Path

import pytest

from standard_knowledge_service_v2.data_ingestion import assistant_rebuild as rebuild


@pytest.fixture
def source_files(tmp_path, monkeypatch):
    rows = [dict(standard_id='AQ 2012-2007', standard_name='石油天然气安全规程', text='4 一般规定'),
            dict(standard_id='AQ 2012-2007', standard_name='石油天然气安全规程', text='4.1 发生事故后应及时报告。')]
    index = tmp_path/'source.jsonl'
    index.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows), encoding='utf-8')
    provenance = tmp_path/'trace.jsonl'
    provenance.write_text(''.join(json.dumps(dict(source='public.xlsx', source_row=i+3, source_sha256='test', sheet='Sheet1'))+'\n' for i in range(2)), encoding='utf-8')
    digest = hashlib.sha256(index.read_bytes()).hexdigest()
    monkeypatch.setattr(rebuild, 'SOURCE_SHA256', digest)
    annotations = tmp_path/'annotations.json'
    authored = dict(method='assistant_authored_semantic_decomposition', batch='assistant_processed_20261013_001',
                    source_index_sha256=digest, source_lines=[1, 2],
                    items=[[1, 'heading', '一般规定', '章节标题', ''],
                           [2, 'normative', '事故报告', '事故后及时报告', '发生事故后']])
    annotations.write_text(json.dumps(authored, ensure_ascii=False), encoding='utf-8')
    return index, provenance, annotations, tmp_path/'stage', authored


def test_heading_excluded_and_normative_source_preserved(source_files):
    index, provenance, annotations, stage, _ = source_files
    result = rebuild.publish(index, provenance, annotations, stage)
    assert result['staged_json_count'] == 1
    files = list((stage/'分解数据/json').glob('*.json'))
    payload = json.loads(files[0].read_text(encoding='utf-8'))
    assert payload['rules'][0]['content'] == '4.1 发生事故后应及时报告。'
    assert payload['rules'][0]['action'] == ''
    assert payload['metadata']['audit']['manual_review_required']
    assert payload['metadata']['source_location']['source_row'] == 4
    assert not result['live_database_replaced']


def test_repeat_is_idempotent(source_files):
    index, provenance, annotations, stage, _ = source_files
    a = rebuild.publish(index, provenance, annotations, stage)
    b = rebuild.publish(index, provenance, annotations, stage)
    assert a == b
    assert len(list((stage/'分解数据/json').glob('*.json'))) == 1


@pytest.mark.parametrize('bad', ['method', 'quote', 'coverage', 'hash'])
def test_invalid_annotations_do_not_write_a_partial_stage(source_files, bad):
    index, provenance, annotations, stage, authored = source_files
    if bad == 'method': authored['method'] = 'rule_based_field_extraction_draft'
    if bad == 'quote': authored['items'][1][4] = '自动关闭设备'
    if bad == 'coverage': authored['items'].pop()
    if bad == 'hash': authored['source_index_sha256'] = 'changed'
    annotations.write_text(json.dumps(authored, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(ValueError): rebuild.publish(index, provenance, annotations, stage)
    assert not stage.exists()
