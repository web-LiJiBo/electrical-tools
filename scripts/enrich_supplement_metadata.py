"""Recover second-batch metadata from hashed local imports; never infer control rules.

Default is a preview. --apply backs up every changed record before writing it.
Original source indices and rule text remain immutable historical evidence.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import unicodedata
import zipfile


MEM_CODES = 'https://www.mem.gov.cn/gk/zfxxgkpt/fdzdgknr/202501/t20250126_513844.shtml'
FIRE_CODES = 'https://www.mem.gov.cn/gk/zfxxgkpt/fdzdgknr/202012/t20201207_374310.shtml'
CODE_CHANGES = {
    ('AQ/T 3052-2015', 'YJ/T 3052-2015'): MEM_CODES,
    ('AQ/T 9011-2019', 'YJ/T 9011-2019'): MEM_CODES,
    ('GA/T 970-2011', 'XF/T 970-2011'): FIRE_CODES,
}
NUMBER = re.compile(r'(?<![A-Z])((?:GB|SY|HJ|YD|AQ|GA|XF|YJ)(?:\s*[/_]\s*T)?|Q\s*[/_\-]\s*GGW)\s*(\d+(?:\.\d+)*)\s*[-—－–]+\s*((?:19|20)\d{2})(?!\d)', re.I)


def normal(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(text)))


def filename_identity(filename):
    # A formal header such as AQ/T contains a slash but is not a filesystem path.
    stem = re.sub(r'\.(?:xlsx|xlsm|pdf)$', '', str(filename), flags=re.I)
    dec = re.search(r'DEC-[A-Z0-9-]+-((?:19|20)\d{2})-\d+', stem)
    if dec:
        return dec.group(), dec.group(1)
    match = NUMBER.search(stem)
    if not match:
        return '', ''
    prefix = re.sub(r'\s+', '', match[1].upper()).replace('_', '/').replace('Q-GGW', 'Q/GGW')
    return f'{prefix} {match[2]}-{match[3]}', match[3]


def resolve_identity(filename, header):
    identifier, year = filename_identity(filename)
    original, _ = filename_identity(header + '.xlsx')
    if identifier:
        change = CODE_CHANGES.get((original, identifier))
        if original and original != identifier and not change:
            return dict(standard_id=original, version='', status='identity_conflict', filename_candidate=identifier)
        return dict(standard_id=identifier, version=year,
                    status='official_code_change' if change else 'filename_confirmed',
                    **({'official_source': change, 'previous_code': original} if change else {}))
    document = re.fullmatch(r'国家管网办[\[〔]((?:19|20)\d{2})[\]〕]\d+号', header)
    if document:
        return dict(standard_id=header, version=document[1], status='document_reference_from_header')
    return dict(standard_id='', version='', status='no_number_in_source_filename')


def scope_evidence(rows):
    """Quote scope paragraphs, never normative references or later device rules."""
    selected = []
    active = False
    general = False
    continuation = False
    scope_section = 1
    for row in rows:
        text = row['raw_text']
        compact = normal(text)
        heading = re.fullmatch(r'([12])(?:范围|适用范围|主题内容与适用范围)', normal(text.splitlines()[0]))
        if heading:
            active, general, continuation = True, False, False
            scope_section = int(heading[1])
            selected = []
            continue
        if re.fullmatch(r'1总则', compact):
            active, general, continuation = True, True, False
            scope_section = 1
            selected = []
            continue
        if active and re.match(r'^' + str(scope_section + 1) + r'(?:\s|[.、．]|规范性|引用|术语)', text.strip()):
            break
        if active and re.fullmatch(r'\d+(?:引用标准|规范性引用文件|术语和定义|定义)', compact):
            break
        if not active:
            # Structured management documents can have a self-contained scope article.
            if re.match(r'^(?:第[一二三四五六七八九十]+条|\d+(?:\.\d+)*\s)', text.strip()) and ('[适用范围]' in compact or '【适用范围】' in compact):
                selected.append(row)
            continue
        if general:
            starts = bool(re.match(r'^1[.．]\d+', compact))
            if starts:
                continuation = '适用' in compact or ('本规范是' in compact and '技术依据' in compact)
            elif re.match(r'^\d+[.．]\d+', compact):
                continuation = False
            if continuation:
                selected.append(row)
        else:
            if re.match(r'^2\s*$', compact):
                break
            selected.append(row)
    if selected:
        return [dict(source_row=r['source_row'], text=r['raw_text']) for r in selected]
    # OCR may merge the scope paragraph with a contents-column cell. Keep only
    # its exact substring; never reword or fuse unrelated columns into a scope.
    for index, row in enumerate(rows):
        text = row['raw_text']
        match = re.search(r'1\s*[.．]\s*0\s*[.．]\s*\d+\s+本(?:标准|规范|文件)[^。；]{0,100}?适用', text)
        article = index < 25 and re.match(r'^第[一二三四五六七八九十]+条\s*.*?本(?:规定|办法|细则)适用', text.strip())
        if not match and not article:
            continue
        first = text[match.start():] if match else text
        output = [dict(source_row=row['source_row'], text=first)]
        for following in rows[index + 1:]:
            part = following['raw_text']
            if re.match(r'^(?:第[一二三四五六七八九十]+条|\d+(?:\s*[.．]\s*\d+)*\s)', part.strip()):
                break
            if len(output) >= 5:
                break
            output.append(dict(source_row=following['source_row'], text=part))
        return output
    return []


def pdf_index(pages):
    parts, ends, length = [], [], 0
    for page in pages:
        part = normal(page)
        parts.append(part)
        length += len(part)
        ends.append(length)
    return ''.join(parts), ends


def locate_pdf(text, pages):
    """Only full normalized text matches count; page numbers are physical PDF pages."""
    needle = normal(text)
    if len(needle) < 20:
        return dict(status='text_too_short_for_unique_location', pages=[])
    haystack, ends = pdf_index(pages) if isinstance(pages, list) else pages
    matches, start = [], 0
    while True:
        pos = haystack.find(needle, start)
        if pos < 0:
            break
        matches.append(list(range(bisect_right(ends, pos) + 1, bisect_right(ends, pos + len(needle) - 1) + 2)))
        start = pos + 1
    return dict(status=('exact_text_match' if len(matches) == 1 else 'multiple_exact_text_matches') if matches else 'text_not_located',
                pages=sorted({page for match in matches for page in match}), match_count=len(matches))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def source_lines(payload, index, by_key):
    meta = payload['metadata']
    original_id = meta.get('original_standard_id', payload['standard_id'])
    key = original_id, payload['rules'][0]['content']
    if 'source_index_line' in meta:
        return [meta['source_index_line']]
    candidates = by_key.get(key, [])
    if not candidates:
        raise ValueError('历史条款没有精确来源，禁止用相似文本替代')
    return candidates


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    temporary = path.with_name(path.name + '.metadata.tmp')
    temporary.write_bytes(raw)
    temporary.replace(path)


def read_sources(repo, working, names):
    report = json.loads((working / '导入记录/latest.json').read_text(encoding='utf-8'))
    index_path = repo / 'datasets/supplemental/子条款/子条款索引.jsonl'
    index_raw = index_path.read_bytes()
    index = [json.loads(line) for line in index_raw.decode('utf-8').splitlines()]
    rows, locations, documents = [], [], {}
    input_dir = working / '原始Excel'
    for item in report['documents']:
        path = working / '读取结果' / (item['document_id'] + '.json')
        imported = json.loads(path.read_text(encoding='utf-8'))
        relative = imported['source_key']
        source_path = input_dir / relative
        source_raw = source_path.read_bytes()
        if digest(source_raw) != imported['source_sha256'] or item['sha256'] != imported['source_sha256']:
            raise ValueError('原始文件哈希与导入记录不一致: ' + relative)
        for sheet in imported['sheets']:
            doc_id = digest((relative + '\0' + imported['source_sha256'] + '\0' + sheet['sheet_name']).encode())[:24]
            identity = resolve_identity(source_path.name, sheet['standard_id'])
            identifier = identity['standard_id']
            name_entry = names.get(identifier)
            title = name_entry['standard_name'] if name_entry else sheet['standard_name']
            if not identifier:
                title = source_path.stem
            if identifier.startswith(('Q/GGW ', 'DEC-')):
                match = NUMBER.search(source_path.stem)
                tail = source_path.stem[match.end():].lstrip('+ ') if match else source_path.stem.split('+', 1)[-1]
                if tail and re.search('[\u4e00-\u9fff]', tail):
                    title = tail
            pdf = source_path.with_suffix('.pdf')
            pdf_status, page_texts = 'source_pdf_not_available', []
            if pdf.exists():
                import fitz
                fitz.TOOLS.mupdf_display_errors(False)
                fitz.TOOLS.mupdf_display_warnings(False)
                fitz.TOOLS.mupdf_warnings(reset=True)
                with fitz.open(pdf) as book:
                    page_texts = [page.get_text() for page in book]
                pdf_warnings = fitz.TOOLS.mupdf_warnings(reset=True)
                pdf_status = 'searchable_text' if any(normal(p) for p in page_texts) else 'scanned_pdf_requires_ocr'
            else:
                pdf_warnings = ''
            scope = scope_evidence(sheet['rows'])
            info = dict(document_id=doc_id, source_file=relative, source_sha256=imported['source_sha256'],
                        sheet=sheet['sheet_name'], original_standard_id=sheet['standard_id'],
                        original_standard_name=sheet['standard_name'], standard_name=title,
                        **identity, version_meaning='edition_year_not_effective_date',
                        current_validity='not_assessed', scope_status='source_excerpt_available' if scope else 'scope_not_located',
                        scope_evidence=scope, original_pdf=dict(file=pdf.relative_to(input_dir).as_posix() if pdf.exists() else '',
                            status=pdf_status, page_count=len(page_texts), extraction_warnings=pdf_warnings[:1000],
                            sha256=digest(pdf.read_bytes()) if pdf.exists() else ''),
                        name_basis=dict(status=name_entry['lookup_status'], source=name_entry['name_source']) if name_entry else dict(status='source_header_or_filename', source=relative))
            if page_texts:
                locator = pdf_index(page_texts)
                for scope_row in scope:
                    scope_row['pdf_location'] = locate_pdf(scope_row['text'], locator)
            else:
                locator = ('', [])
            documents[doc_id] = info
            for row in sheet['rows']:
                rows.append(dict(standard_name=sheet['standard_name'], standard_id=sheet['standard_id'], text=row['raw_text']))
                location = dict(document_id=doc_id, source_file=relative, source_sha256=imported['source_sha256'],
                                sheet=sheet['sheet_name'], row=row['source_row'], cells=[c['coordinate'] for c in row['cells']])
                if pdf_status == 'searchable_text':
                    location['pdf_location'] = locate_pdf(row['raw_text'], locator)
                else:
                    location['pdf_location'] = dict(status=pdf_status, pages=[])
                locations.append(location)
    if rows != index:
        raise ValueError('导入记录无法逐行重建发布索引，禁止猜测来源坐标')
    return index, locations, documents, digest(index_raw)


def enrich(repo, working, name_catalog, output, apply=False):
    from standard_knowledge_service_v2.data_ingestion.clause_filenames import supplemental_identity
    names = {r['standard_id']: r for r in json.loads(name_catalog.read_text(encoding='utf-8'))}
    index, locations, documents, index_hash = read_sources(repo, working, names)
    print('来源重建完成:', len(index), '行，', len(documents), '份文档', flush=True)
    by_key = {}
    for number, row in enumerate(index, 1):
        by_key.setdefault((row['standard_id'], row['text']), []).append(number)
    directory = repo / 'datasets/supplemental/分解数据/json'
    counts, plans, records, seen = Counter(), [], [], set()
    output.mkdir(parents=True, exist_ok=True)
    backup_path = output / 'original_records.zip'
    if apply and backup_path.exists():
        raise ValueError('备份已经存在；请使用新的输出目录，禁止覆盖备份')
    for path in sorted(directory.glob('*.json')):
        raw = path.read_bytes()
        original = json.loads(raw)
        data = json.loads(raw)
        meta = data['metadata']
        candidates = source_lines(data, index, by_key)
        line = candidates[0]
        if meta.get('source_index_sha256', index_hash) != index_hash:
            raise ValueError('条款索引哈希不匹配: ' + path.name)
        source, location = index[line - 1], locations[line - 1]
        location = dict(location)
        if len(candidates) > 1:
            if len({documents[locations[n-1]['document_id']]['standard_id'] for n in candidates}) > 1:
                raise ValueError('相同原文对应不同标准编号，需人工选择: ' + path.name)
            location['equivalent_source_locations'] = [locations[n-1] for n in candidates[1:]]
        original_id = meta.get('original_standard_id', data['standard_id'])
        if original_id != source['standard_id'] or data['rules'][0]['content'] != source['text']:
            raise ValueError('条款与原索引不匹配: ' + path.name)
        doc = documents[location['document_id']]
        before_identity = supplemental_identity(original)
        meta['original_standard_id'] = original_id
        meta['source_index_line'], meta['source_index_sha256'] = line, index_hash
        meta.setdefault('original_standard_name', original['standard_name'])
        data['standard_id'], data['version'] = doc['standard_id'], doc['version']
        data['standard_name'] = doc['standard_name']
        meta['source_location'] = location
        meta['standard_metadata'] = dict(document_id=doc['document_id'], catalog='datasets/supplemental/标准来源目录.json',
            identity_status=doc['status'], version_basis=doc['version_meaning'], current_validity=doc['current_validity'])
        meta['applicability'] = dict(scope_status=doc['scope_status'], scope_document_id=doc['document_id'],
            clause_condition=data['rules'][0].get('condition', ''), executable=False,
            note='标准范围原文与条款自身条件分别保留；未推导设备控制条件')
        after_identity = supplemental_identity(data)
        if before_identity != after_identity or after_identity in seen:
            raise ValueError('内部标识漂移或重复: ' + path.name)
        seen.add(after_identity)
        if data['rules'] != original['rules'] or meta.get('audit') != original['metadata'].get('audit'):
            raise ValueError('规则或专家复核状态被修改')
        counts['records'] += 1
        counts['standard_id_changed'] += data['standard_id'] != original['standard_id']
        counts['standard_name_changed'] += data['standard_name'] != original['standard_name']
        counts['version_changed'] += data['version'] != original.get('version', '')
        counts['version_available'] += bool(data['version'])
        counts['number_unresolved'] += not bool(data['standard_id'])
        counts['scope_available'] += bool(doc['scope_evidence'])
        counts['pdf_exact_location'] += location['pdf_location']['status'] == 'exact_text_match'
        counts['pdf_multiple_location'] += location['pdf_location']['status'] == 'multiple_exact_text_matches'
        record = dict(file=path.name, internal_id=after_identity, source_index_line=line, old_standard_id=original['standard_id'],
                      standard_id=data['standard_id'], version=data['version'], document_id=doc['document_id'],
                      original_sha256=digest(raw), original_location=location)
        records.append(record)
        plans.append((path, raw, data))
    summary = dict(applied=apply, date='2026-10-26', **dict(counts), source_documents=len(documents),
        document_identity_status=dict(Counter(d['status'] for d in documents.values())),
        source_index_sha256=index_hash, rule_text_unchanged=True, internal_ids_unchanged=True,
        expert_review_status_unchanged=True, source_files_unchanged=True,
        filenames_unchanged=True, source_location_note='原Excel工作表和单元格定位完整；PDF仅对全文精确匹配记录填物理页码，多匹配保留全部候选',
        backup=str(backup_path) if apply else '', exclusions='原库未改；不推定现行有效性、实施日期、条款适用性或控制授权')
    write_json(output / 'summary.json', summary)
    write_json(output / 'source_documents.json', list(documents.values()))
    with (output / 'record_changes.jsonl').open('w', encoding='utf-8') as stream:
        for row in records:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    if apply:
        # Finish and verify the complete backup before touching any live record.
        with zipfile.ZipFile(backup_path, 'x', compression=zipfile.ZIP_DEFLATED) as backup:
            for path, raw, _ in plans:
                backup.writestr(path.name, raw)
            for extra in ['publish_manifest.json', 'README.md', '标准来源目录.json']:
                file = directory.parents[1] / extra
                if file.exists():
                    backup.writestr('_snapshot_metadata/' + extra, file.read_bytes())
        with zipfile.ZipFile(backup_path) as backup:
            if backup.testzip() is not None:
                raise ValueError('备份ZIP校验失败')
        for path, _, data in plans:
            write_json(path, data)
        write_json(repo / 'datasets/supplemental/标准来源目录.json', dict(schema_version=1, date='2026-10-26',
            documents=documents, source_index_sha256=index_hash, note='范围为可追溯原文摘录；版本为年代号，未统一核验现行性；原PDF不随代码发布'))
        from standard_knowledge_service_v2.data_ingestion.complete_assistant_rebuild import snapshot_digest
        count, size, checksum = snapshot_digest(directory)
        manifest_path = repo / 'datasets/supplemental/publish_manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest.setdefault('original_publication', {key:manifest[key] for key in ('snapshot_date', 'total_bytes', 'sorted_record_hashes_sha256', 'source_byte_comparison')})
        manifest.update(file_count=count, total_bytes=size, sorted_record_hashes_sha256=checksum,
                        source_byte_comparison=False, metadata_enrichment=summary)
        manifest['publication_status'] = '2026-10-26本地补充来源元数据；本次修改尚未推送GitHub'
        write_json(manifest_path, manifest)
        summary.update(snapshot_count=count, snapshot_bytes=size, snapshot_sha256=checksum)
        write_json(output / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--working', type=Path, required=True)
    parser.add_argument('--name-catalog', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    enrich(args.repo.resolve(), args.working.resolve(), args.name_catalog.resolve(), args.output.resolve(), args.apply)
