"""Synthetic OpenXML fixtures only; no real standard is invented or modified."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from xml.sax.saxutils import escape
from zipfile import ZipFile

from standard_knowledge_service_v2.data_ingestion.supplemental_excel import (
    DEFAULT_ROOT, build_subclause_index, import_directory, read_excel,
)


def fixture(path, sheets=None):
    """Build minimal test bytes, not a user-facing Excel deliverable."""
    sheets = sheets or [("测试正文", {"A1": "测试标准（非真实标准）", "A2": "TEST-2026",
                                    "A3": "1.1", "B3": "测试条款正文", "C3": 0,
                                    "A5": "续行", "B5": "=1+1"}, "A1:C1")]
    path.parent.mkdir(parents=True, exist_ok=True)
    main = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    with ZipFile(path, 'w') as archive:
        overrides = ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets)+1))
        archive.writestr('[Content_Types].xml', f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>{overrides}</Types>')
        archive.writestr('_rels/.rels', f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        listing = ''.join(f'<sheet name="{escape(s[0])}" sheetId="{i}" r:id="rId{i}"/>' for i, s in enumerate(sheets, 1))
        archive.writestr('xl/workbook.xml', f'<workbook xmlns="{main}" xmlns:r="{rel}"><sheets>{listing}</sheets></workbook>')
        links = ''.join(f'<Relationship Id="rId{i}" Type="{rel}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets)+1))
        archive.writestr('xl/_rels/workbook.xml.rels', f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{links}</Relationships>')
        for i, (_, values, merge) in enumerate(sheets, 1):
            rows = {}
            for coordinate, value in values.items():
                row = int(''.join(c for c in coordinate if c.isdigit()))
                if isinstance(value, str) and value.startswith('='):
                    cell = f'<c r="{coordinate}"><f>{escape(value[1:])}</f></c>'
                elif isinstance(value, str):
                    cell = f'<c r="{coordinate}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
                else:
                    cell = f'<c r="{coordinate}" t="n"><v>{value}</v></c>'
                rows.setdefault(row, []).append(cell)
            data = ''.join(f'<row r="{row}">{"".join(cells)}</row>' for row, cells in sorted(rows.items()))
            merging = f'<mergeCells count="1"><mergeCell ref="{merge}"/></mergeCells>' if merge else ''
            archive.writestr(f'xl/worksheets/sheet{i}.xml', f'<worksheet xmlns="{main}"><sheetData>{data}</sheetData>{merging}</worksheet>')


class SupplementalExcelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'input' / '测试.xlsx'
        fixture(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def run_import(self, **kwargs):
        return import_directory(self.root / 'input', self.root / 'output', self.root / 'reports', **kwargs)

    def test_headers_merged_multicolumn_zero_blank_rows_formula_provenance(self):
        before = self.source.read_bytes()
        result = read_excel(self.source)
        sheet = result['sheets'][0]
        self.assertEqual(sheet['standard_id'], 'TEST-2026')
        self.assertEqual(sheet['merged_ranges'], ['A1:C1'])
        self.assertEqual([r['source_row'] for r in sheet['rows']], [3, 5])
        self.assertEqual(sheet['rows'][0]['cells'][2]['value'], 0)
        self.assertEqual(sheet['rows'][0]['cells'][2]['coordinate'], 'C3')
        self.assertEqual(sheet['rows'][1]['cells'][1]['value'], '=1+1')
        self.assertIsNone(sheet['rows'][1]['cells'][1]['cached_value'])
        self.assertFalse(result['approved_for_control'])
        self.assertTrue(sheet['warnings'])
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(result['source_sha256'], hashlib.sha256(before).hexdigest())

    def test_invalid_sheet_is_reported_without_silent_header_shift(self):
        fixture(self.source, [('好表', {'A1': '测试标准', 'A2': 'TEST', 'A3': '正文'}, ''),
                              ('坏表', {'A2': 'TEST', 'A3': '正文'}, '')])
        result = self.run_import()
        self.assertEqual(result['status'], 'failed_or_partial')
        self.assertEqual(len(result['documents']), 1)
        self.assertEqual(result['errors'][0]['sheet'], '坏表')

    def test_ambiguous_header_rejected(self):
        fixture(self.source, [('测试', {'A1': '标准一', 'B1': '标准二', 'A2': 'TEST', 'A3': '正文'}, '')])
        self.assertFalse(read_excel(self.source)['sheets'])

    def test_empty_body_rejected(self):
        fixture(self.source, [('测试', {'A1': '标准一', 'A2': 'TEST'}, '')])
        self.assertIn('没有条款正文', read_excel(self.source)['errors'][0]['message'])

    def test_rerun_and_same_basename_in_different_folders(self):
        fixture(self.root / 'input' / '子目录' / '测试.xlsx')
        first, second = self.run_import(), self.run_import()
        self.assertEqual(len(first['documents']), 2)
        self.assertEqual([d['document_id'] for d in first['documents']], [d['document_id'] for d in second['documents']])
        self.assertEqual(len(list((self.root / 'output').glob('*.json'))), 2)
        snapshot = json.loads((self.root / 'reports' / 'latest.json').read_text(encoding='utf-8'))
        self.assertEqual(snapshot['run_id'], second['run_id'])

    def test_select_sheet_and_missing_sheet(self):
        self.assertEqual(self.run_import(sheets=['测试正文'])['status'], 'success')
        self.assertEqual(self.run_import(sheets=['不存在'])['status'], 'failed_or_partial')

    def test_unsupported_xls_and_broken_file(self):
        (self.root / 'input' / '旧版.xls').touch()
        (self.root / 'input' / '损坏.xlsx').touch()
        result = self.run_import()
        self.assertEqual(len(result['errors']), 2)
        self.assertEqual(len(result['documents']), 1)

    def test_overlapping_directories_rejected(self):
        with self.assertRaises(ValueError):
            import_directory(self.root / 'input', self.root / 'input' / 'output', self.root / 'reports')

    def test_default_location_is_separate_from_original_repository(self):
        self.assertEqual(DEFAULT_ROOT.name, '补充标准条款')
        self.assertEqual(DEFAULT_ROOT.parent.name, '06-工具')

    def test_one_row_one_clause_minimal_fields_original_number(self):
        fixture(self.source, [('测试正文', {'A1': '测试标准', 'A2': 'TEST-2026',
                                         'A3': '1.1', 'B3': '测试条款正文', 'C3': 0,
                                         'A5': '1.2 第二条正文\n同行不拆分'}, '')])
        report = self.run_import()
        output = self.root / 'subclauses' / 'index.jsonl'
        summary = build_subclause_index(self.root / 'reports' / 'latest.json', output)
        units = [json.loads(line) for line in output.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(summary['subclause_count'], report['row_count'])
        self.assertEqual(set(units[0]), {'standard_name', 'standard_id', 'text'})
        self.assertEqual(units[0]['standard_id'], 'TEST-2026')
        self.assertEqual(units[0]['text'], '1.1\t测试条款正文\t0')
        self.assertEqual(units[1]['text'], '1.2 第二条正文\n同行不拆分')
        build_subclause_index(self.root / 'reports' / 'latest.json', output)
        self.assertEqual(len(output.read_text(encoding='utf-8').splitlines()), 2)

    def test_unverified_formula_blocks_minimal_export(self):
        self.run_import()
        output = self.root / 'subclauses' / 'index.jsonl'
        with self.assertRaisesRegex(ValueError, '未校验公式'):
            build_subclause_index(self.root / 'reports' / 'latest.json', output)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
