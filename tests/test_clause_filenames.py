import hashlib
import json
from pathlib import Path

import pytest

from standard_knowledge_service_v2.data_ingestion.clause_filenames import clause_filename, supplemental_identity
from standard_knowledge_service_v2.data_ingestion.supplemental_excel import DEFAULT_ROOT
from standard_knowledge_service_v2.retrieval_engine.clause_retriever import JsonClauseRepository


def test_readable_filename_preserves_spaces_numbers_and_escapes_for_windows():
    assert clause_filename('AQ 2012-2007', '5.8.3.3') == 'AQ 2012-2007 5.8.3.3.json'
    assert clause_filename('GB/T 24040-2008/ISO 14040:2006', '4.2.1') == 'GB／T 24040-2008／ISO 14040：2006 4.2.1.json'
    with pytest.raises(ValueError):
        clause_filename('', '1.1')
    with pytest.raises(ValueError):
        clause_filename('GB\n123', '1.1')


def test_supplemental_identifiers_do_not_depend_on_filename():
    payload = {'standard_id': 'AQ 2012-2007', 'chapter_path': '5.8.3.3',
               'rules': [{'content': 'original text', 'subject': 'compressor', 'action': ''}],
               'entities': [{'name': 'compressor'}],
               'metadata': {'dataset': 'supplemental_excel', 'batch': 'assistant_additional1000'}}
    identity = supplemental_identity(payload)
    before = JsonClauseRepository._from_payload(Path(identity + '.json'), payload)
    after = JsonClauseRepository._from_payload(Path(clause_filename(payload['standard_id'], payload['chapter_path'])), payload)
    assert before.clause_id == after.clause_id == identity
    assert before.rules[0].rule_id == after.rules[0].rule_id
    assert before.entities[0].entity_id == after.entities[0].entity_id
    assert supplemental_identity({'metadata': {'dataset': 'lunwen_json'}}) is None


@pytest.mark.skipif(not (DEFAULT_ROOT / '分解数据' / 'JSON文件重命名记录.json').exists(), reason='本地迁移未执行')
def test_all_renamed_files_keep_bytes_and_old_internal_ids():
    directory = DEFAULT_ROOT / '分解数据' / 'json'
    report = json.loads((directory.parent / 'JSON文件重命名记录.json').read_text(encoding='utf-8'))
    assert report['applied'] is True
    assert report['file_count'] == 1100
    assert len(list(directory.glob('*.json'))) >= report['file_count']
    assert len({r['new_name'].casefold() for r in report['items']}) == 1100
    for row in report['items']:
        path = directory / row['new_name']
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
        payload = json.loads(raw.decode('utf-8'))
        assert path.name == clause_filename(payload['standard_id'], payload['chapter_path'])
        assert supplemental_identity(payload) == row['internal_id'] == Path(row['old_name']).stem
        assert not (directory / row['old_name']).exists()
    for summary_name in ('首批100条入库汇总.json', '新增1000条入库汇总.json'):
        summary = json.loads((directory.parent / summary_name).read_text(encoding='utf-8'))
        assert len(summary['clause_files']) == summary['clause_count']
        assert all((directory / name).is_file() for name in summary['clause_files'])
