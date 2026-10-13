"""Select candidate public-standard Excels without modifying source files.

The report documents preferences, not expert certification of clause accuracy.
Enterprise standards/internal policies are excluded on the user's instruction.
Excel corrections are described in a plan for the artifact-tool authoring step.
"""
import argparse
from collections import defaultdict
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
import unicodedata

import openpyxl

LOOKUPS = {
    'AQ 2012-2007': ('石油天然气安全规程', 'https://std.samr.gov.cn/hb/search/stdHBDetailed?id=8B1827F1931DBB19E05397BE0A0AB44A'),
    'GB/T 29512-2013': ('手部防护 防护手套的选择、使用和维护指南', 'https://std.samr.gov.cn/gb/search/gbDetailed?id=71F772D7FA3CD3A7E05397BE0A0AB82A'),
    'SY/T 0086-2020': ('阴极保护管道的电绝缘标准', 'https://std.samr.gov.cn/hb/search/stdHBDetailed?id=C56BF491017B89F9E05397BE0A0A47C9'),
    'AQ/T 3031-2010': ('危险化学品经营单位主要负责人安全生产培训大纲及考核标准', 'https://www.mem.gov.cn/fw/flfgbz/bz/bzwb/201301/P020190327398444499409.pdf'),
    'AQ/T 3032-2010': ('危险化学品经营单位安全生产管理人员安全生产培训大纲及考核标准', 'https://std.samr.gov.cn/hb/search/stdHBDetailed?id=8B1827F190F4BB19E05397BE0A0AB44A'),
    'AQ/T 3034-2022': ('化工过程安全管理导则', 'https://std.samr.gov.cn/hb/search/stdHBDetailed?id=F2714B32FAB23E0FE05397BE0A0A41B8'),
    'GB/T 39674-2020': ('电力软交换系统测试规范', 'https://std.samr.gov.cn/gb/search/gbDetailedCNF?id=B691BB77865DD126E05397BE0A0AF3B3'),
    'GB/T 6067.1-2010': ('起重机械安全规程 第1部分：总则', 'https://std.samr.gov.cn/gb/search/gbDetailed?id=71F772D7D542D3A7E05397BE0A0AB82A'),
}
LOCAL_NAMES = {}


def normalize(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text).replace('—', '-').replace('–', '-').replace('_', '/')).replace('--', '-')


def filename_id(name):
    stem = unicodedata.normalize('NFKC', Path(name).stem).replace('—', '-').replace('–', '-')
    stem = stem.replace('GB+', 'GB ').replace('GBZT ', 'GBZ/T ')
    stem = re.sub(r'^([A-Z]+)[_]T', r'\1/T', stem)
    match = re.match(r'^(GB(?:Z)?(?:/T)?|AQ(?:/T)?|YJ(?:/T)?|GA(?:/T)?|SY(?:/T)?|SH(?:/T)?|HJ(?:/T)?|YD(?:/T)?|DL(?:/T)?|JT(?:/T)?|JC(?:/T)?|HG(?:/T)?|NB(?:/T)?|SL(?:/T)?|XF(?:/T)?|WS(?:/T)?|LY(?:/T)?|TSG|DB\d+(?:/T)?)\s*([0-9]+(?:\.[0-9]+)*)[- ]+(\d{4})(?=$|\s)', stem)
    return f'{match[1]} {match[2]}-{match[3]}' if match else None


def clause_number(text):
    match = re.match(r'^\s*(\d+(?:\.\d+)*)(?=\s|[\u4e00-\u9fff])', text)
    return match[1] if match else None


def analyse(path, root):
    with path.open('rb') as handle:
        book = openpyxl.load_workbook(handle, read_only=True, data_only=False, keep_links=False)
        try:
            sheets = []
            for sheet in book:
                values = []
                for index, row in enumerate(sheet.iter_rows(), 1):
                    cells = [c for c in row if c.value is not None and str(c.value).strip()]
                    if not cells:
                        continue
                    if any(c.data_type in ('f', 'e') for c in cells):
                        raise ValueError('未校验的公式或错误单元格')
                    if len(cells) != 1 or not isinstance(cells[0].value, str):
                        raise ValueError('需要单列文本，拒绝静默拼接或转换')
                    values.append((index, cells[0].value))
                if values:
                    sheets.append((sheet.title, values))
            if len(sheets) != 1:
                raise ValueError('需要单个非空工作表')
            sheet_name, values = sheets[0]
        finally:
            book.close()
    identifier = filename_id(path.name)
    if not identifier:
        raise ValueError('文件名无法识别公共标准编号')
    first = [v for _, v in values[:3]]
    name, start, native = None, 0, False
    if len(first) >= 2 and normalize(identifier) in normalize(first[1]):
        name, start, native = first[0], 2, True
    elif len(first) >= 2 and normalize(identifier) == normalize(first[0]):
        name, start = first[1], 2
    elif len(first) >= 3 and normalize(identifier) == normalize(first[2]):
        name, start = ' '.join(first[:2]), 3
    elif len(first) >= 2 and re.match(r'^[A-Z]+(?:/T)?\s*\d', unicodedata.normalize('NFKC', first[1])) and not clause_number(first[0]):
        header_identifier = filename_id(first[1] + '.xlsx')
        if header_identifier and header_identifier.split(' ', 1)[1] != identifier.split(' ', 1)[1]:
            lookup = LOOKUPS.get(identifier)
            if not lookup or normalize(first[0]) != normalize(lookup[0]):
                raise ValueError(f'文件名与正文表头标准编号冲突：{identifier} / {header_identifier}；不按文件名强行改号')
        # Keep filename identity as requested; a historical AQ/YJ or GA/XF
        # alias is only logged, not used to merge two different identifiers.
        name, start, native = first[0], 2, True
    elif identifier not in LOOKUPS and identifier not in LOCAL_NAMES:
        raise ValueError('缺少可核验的标准名称，等待补充来源')
    lookup = LOOKUPS.get(identifier) or (LOCAL_NAMES.get(identifier) if name is None else None)
    if lookup:
        name = lookup[0]
    body = values[start:]
    if not body or not name or clause_number(name):
        raise ValueError('名称或正文不可可靠确定')
    numbers = {n for _, t in body if (n := clause_number(t))}
    numbered = sum(clause_number(t) is not None for _, t in body)
    return dict(source=str(path), relative_path=path.relative_to(root).as_posix(),
                filename=path.name, standard_id=identifier, standard_name=name,
                name_source=lookup[1] if lookup else 'selected_workbook_header',
                lookup_status='official_name_checked' if identifier in LOOKUPS else 'source_header_only_not_officially_rechecked',
                standard_status='已废止，仅保留历史版本' if identifier == 'GB/T 29512-2013' else '未统一复核现行性',
                source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), sheet=sheet_name,
                original_header=first[:start], native_header=native, row_count=len(body),
                numbered_ratio=numbered/len(body), clause_numbers=sorted(numbers),
                correction_required=start != 2 or normalize(first[0]) != normalize(name) or not normalize(first[1]).startswith(normalize(identifier)),
                rows=body)


def create_plan(input_root, output):
    root, output = Path(input_root).resolve(), Path(output).resolve()
    if output.exists() or output == root or output.is_relative_to(root):
        raise ValueError('必须使用源目录之外的全新输出目录，禁止覆盖')
    output.mkdir(parents=True)
    groups, excluded, unresolved = defaultdict(list), [], []
    LOCAL_NAMES.clear()
    retry = []
    files = sorted(root.rglob('*.xlsx'))
    for path in files:
        relative = path.relative_to(root).as_posix()
        if ('企标' in path.parts or '制度' in path.parts or '制程' in path.parts or 'DEC文件' in path.parts or
            path.name.startswith(('Q', 'DEC')) or '国家管网集团' in path.name or '管理规定' in path.name or path.name.startswith('附件14')):
            excluded.append(dict(path=relative, reason='用户要求排除企标及企业内部制度'))
            continue
        try:
            item = analyse(path, root)
            groups[item['standard_id']].append(item)
            if item['native_header']:
                LOCAL_NAMES.setdefault(item['standard_id'], (item['standard_name'], '同包正确表头: '+item['relative_path']))
        except Exception as exc:
            retry.append(path)
    for path in retry:
        try:
            item = analyse(path, root)
            groups[item['standard_id']].append(item)
        except Exception as exc:
            unresolved.append(dict(path=path.relative_to(root).as_posix(), reason=str(exc)))
    selected, choices = [], []
    for identifier, versions in sorted(groups.items()):
        versions.sort(key=lambda x: (x['native_header'], x['numbered_ratio'], len(x['clause_numbers']), x['row_count'], x['relative_path']), reverse=True)
        preferred = versions[0]
        selected.append(preferred)
        if len(versions) > 1:
            comparison = []
            preferred_text = normalize(''.join(t for _, t in preferred['rows']))
            for alternative in versions[1:]:
                alternative_text = normalize(''.join(t for _, t in alternative['rows']))
                extra = sorted(set(alternative['clause_numbers']) - set(preferred['clause_numbers']))
                missing = sorted(set(preferred['clause_numbers']) - set(alternative['clause_numbers']))
                comparison.append(dict(path=alternative['relative_path'], row_count=alternative['row_count'],
                    same_normalized_body=alternative_text == preferred_text,
                    alternative_only_numbers=extra, preferred_only_numbers=missing,
                    text_similarity=round(SequenceMatcher(None, preferred_text, alternative_text, autojunk=False).ratio(), 4)))
            choices.append(dict(standard_id=identifier, preferred=preferred['relative_path'],
                criterion='原有正确表头优先，其次一行一条的编号覆盖比例及条款覆盖；不是按文件日期或单纯行数取舍',
                status='格式优选；不同正文仍需人工内容复核' if any(not x['same_normalized_body'] for x in comparison) else '正文规范化后一致',
                alternatives=comparison))
    summary = dict(input_root=str(root), source_file_count=len(files), selected_document_count=len(selected),
        excluded_count=len(excluded), unresolved_count=len(unresolved), duplicate_groups=len(choices),
        correction_count=sum(x['correction_required'] for x in selected),
        source_row_count=sum(x['row_count'] for x in selected), database_changed=False,
        original_excels_changed=False, approved_for_control=False,
        excluded=excluded, unresolved=unresolved, duplicate_choices=choices,
        selected=[{k:v for k,v in x.items() if k not in ('rows', 'clause_numbers')} for x in selected])
    (output/'整理清单.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    # Sidecar rows preserve source coordinates and every body value exactly.
    # Chapter titles are retained for traceability, not asserted to be rules.
    with (output/'子条款索引.jsonl').open('w', encoding='utf-8') as index, (output/'来源追溯.jsonl').open('w', encoding='utf-8') as provenance:
        for item in selected:
            for row, text in item['rows']:
                index.write(json.dumps(dict(standard_name=item['standard_name'], standard_id=item['standard_id'], text=text), ensure_ascii=False)+'\n')
                provenance.write(json.dumps(dict(source=item['relative_path'], source_row=row, sheet=item['sheet'], source_sha256=item['source_sha256']), ensure_ascii=False)+'\n')
    (output/'excel整理计划.json').write_text(json.dumps(selected, ensure_ascii=False), encoding='utf-8')
    return {k:v for k,v in summary.items() if k not in ('excluded', 'unresolved', 'duplicate_choices', 'selected')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(create_plan(args.input, args.output), ensure_ascii=False, indent=2))
