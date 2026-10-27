import copy
import importlib.util
from pathlib import Path

from standard_knowledge_service_v2.data_ingestion.clause_filenames import supplemental_identity


def helpers():
    path = Path(__file__).resolve().parents[1] / 'scripts/enrich_supplement_metadata.py'
    assert path.exists(), '缺少来源元数据补充工具'
    spec = importlib.util.spec_from_file_location('source_metadata_enrichment', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_identity_survives_standard_number_correction():
    payload = {'standard_id': 'M33', 'rules': [{'content': '1.1 原始条款'}],
               'metadata': {'dataset': 'supplemental_excel', 'batch': 'assistant_remaining_010'}}
    original_id = supplemental_identity(payload)
    corrected = copy.deepcopy(payload)
    corrected['metadata']['original_standard_id'] = payload['standard_id']
    corrected['standard_id'] = 'YD/T 1022-2018'
    assert supplemental_identity(corrected) == original_id


def test_number_comes_from_filename_and_preserves_part_and_year():
    h = helpers()
    assert h.filename_identity('SY_T 0087.5-2016.xlsx') == ('SY/T 0087.5-2016', '2016')
    assert h.filename_identity('Q_GGW04018.5—2025温室气体.xlsx') == ('Q/GGW 04018.5-2025', '2025')
    assert h.filename_identity('附件11：DEC-OTP-G-IS-001-2025-2+规定.xlsx') == ('DEC-OTP-G-IS-001-2025-2', '2025')
    assert h.filename_identity('国家管网集团能量隔离和锁定管理细则.xlsx') == ('', '')
    assert h.filename_identity('ICS 75.200.xlsx') == ('', '')


def test_scope_uses_body_and_excludes_contents_and_normative_references():
    h = helpers()
    rows = [{'source_row': i + 3, 'raw_text': s} for i, s in enumerate([
        '1 范围…………1', '1 范围', '本标准规定了电力软交换系统的要求。',
        '本标准适用于电力软交换系统。', '2 规范性引用文件', '最新版本适用于本文件。'])]
    result = h.scope_evidence(rows)
    assert [r['source_row'] for r in result] == [5, 6]
    assert '最新版本' not in str(result)


def test_general_provisions_scope_keeps_continuation_only():
    h = helpers()
    rows = [{'source_row': i + 3, 'raw_text': s} for i, s in enumerate([
        '1 总则', '1.0.1 编制目的。', '1.0.2 本标准适用于在役陆上钢质油气管',
        '道，其他钢质油气管道可参照执行。', '1.0.3 其他规定。', '2 术语'])]
    result = h.scope_evidence(rows)
    assert [r['source_row'] for r in result] == [5, 6]


def test_scope_handles_split_management_articles_and_merged_ocr_cells():
    h = helpers()
    rows = [{'source_row': 7, 'raw_text': '第二条 本规定适用于集团公司总部部门及所属企业的事故'},
            {'source_row': 8, 'raw_text': '事件管理。'}, {'source_row': 9, 'raw_text': '第三条 引用文件'}]
    assert [r['source_row'] for r in h.scope_evidence(rows)] == [7, 8]
    rows = [{'source_row': 115, 'raw_text': '8.2 设备选型……36\t1.0.1 编制目的。\n1.0.2 本规范适用于光纤系统工程设计。'}]
    result = h.scope_evidence(rows)
    assert result[0]['text'] == '1.0.2 本规范适用于光纤系统工程设计。'
    rows = [{'source_row': 27, 'raw_text': '1 主题内容与适用范围\n1.1 主题内容'},
            {'source_row': 28, 'raw_text': '本标准适用于污染物排放管理。'},
            {'source_row': 29, 'raw_text': '5 引用标准'}]
    assert [r['source_row'] for r in h.scope_evidence(rows)] == [28]


def test_pdf_locator_requires_full_text_and_reports_repeated_matches():
    h = helpers()
    text = '本标准适用于在役陆上钢质油气管道及其他附属设施的设计与管理。'
    pages = ['目录', '本标准适用于在役陆上钢质油气管道及\n其他附属设施的设计与管理。', text]
    result = h.locate_pdf(text, pages)
    assert result['status'] == 'multiple_exact_text_matches'
    assert result['pages'] == [2, 3]
    assert h.locate_pdf('1 范围', pages)['pages'] == []
    assert h.locate_pdf(text + '不存在的尾部', pages)['pages'] == []


def test_header_conflicts_are_not_silently_overwritten():
    h = helpers()
    assert h.resolve_identity('GB 1234-2020.xlsx', 'GB 1234-2019')['status'] == 'identity_conflict'
    result = h.resolve_identity('SY_T 6638-2024.xlsx', 'SYII 6638-2024')
    assert result['standard_id'] == 'SY/T 6638-2024'
    assert result['status'] == 'filename_confirmed'
    assert h.resolve_identity('YJ_T 9011-2019.xlsx', 'AQ/T 9011-2019')['status'] == 'official_code_change'


def test_legacy_first_batch_requires_exact_source_text_and_preserves_duplicates():
    h = helpers()
    records = [{'standard_id': 'GB 1234-2020', 'standard_name': '名称', 'text': '原文'}] * 2
    payload = {'standard_id': 'GB 1234-2020', 'standard_name': '名称', 'rules': [{'content': '原文'}], 'metadata': {}}
    assert h.source_lines(payload, records, {('GB 1234-2020', '原文'): [1, 2]}) == [1, 2]
    payload['rules'][0]['content'] = '相似但不同的原文'
    import pytest
    with pytest.raises(ValueError, match='精确来源'):
        h.source_lines(payload, records, {('GB 1234-2020', '原文'): [1, 2]})
