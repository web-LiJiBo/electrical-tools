import json

from standard_knowledge_service_v2.data_ingestion.remaining_inventory import inventory


def test_inventory_accounts_for_every_source_without_publishing(tmp_path):
    records = [
        {'standard_name': '标准', 'standard_id': 'GB 123-2020', 'text': '1.1 已完成原文'},
        {'standard_name': '标准', 'standard_id': 'GB 123-2020', 'text': '1.1 已完成原文'},
        {'standard_name': '标准', 'standard_id': 'GB 123-2020', 'text': '1.1 新的不同原文'},
        {'standard_name': '标准', 'standard_id': 'GB 123-2020', 'text': '2.1 待分解原文'},
        {'standard_name': '标准', 'standard_id': 'GB 123-2020', 'text': '2.1 待分解原文'},
        {'standard_name': '标准', 'standard_id': 'GB 123-2020', 'text': '2.1 同编号不同原文'},
        {'standard_name': '标准', 'standard_id': 'GB 123-2020', 'text': '表格碎片'},
    ]
    index = tmp_path / 'source.jsonl'
    index.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in records), encoding='utf-8')
    completed = tmp_path / 'completed'
    completed.mkdir()
    target = completed / 'GB 123-2020 1.1.json'
    target.write_text(json.dumps({'standard_id': 'GB 123-2020',
                                 'rules': [{'content': records[0]['text']}]}), encoding='utf-8')
    before = target.read_bytes()
    result = inventory(index, completed)
    assert result['source_row_count'] == 7
    assert result['completed_source_row_count'] == 2
    assert result['remaining_source_row_count'] == 5
    assert result['remaining_unique_record_count'] == 4
    assert result['remaining_duplicate_source_row_count'] == 1
    assert result['items'][1]['duplicate_source_lines'] == [5]
    assert result['preflight_issue_record_counts'] == {
        'filename_conflicts_with_completed_record': 1,
        'filename_conflicts_with_other_pending_record': 2,
        'no_unambiguous_leading_numeric_clause_number': 1,
    }
    assert all(i['status'] == 'pending_semantic_decomposition' for i in result['items'])
    assert target.read_bytes() == before
    assert len(list(completed.glob('*.json'))) == 1
