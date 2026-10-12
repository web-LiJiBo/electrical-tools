"""Readable Windows filenames; keep supplemental internal IDs independent of paths."""
import hashlib
import json
from pathlib import Path
import re

from .supplemental_excel import DEFAULT_ROOT, _write_json

_REPLACEMENTS = str.maketrans({'/': '／', '\\': '＼', ':': '：', '*': '＊', '?': '？',
                              '"': '＂', '<': '＜', '>': '＞', '|': '｜'})
_PREFIXES = {'assistant_first100': 'supp100_', 'assistant_additional1000': 'supp1000_',
             'assistant_additional1000_v2': 'supp1000v2_'}


def clause_filename(standard_id: str, chapter_path: str) -> str:
    parts = []
    for value in (standard_id, chapter_path):
        part = str(value).strip().translate(_REPLACEMENTS)
        if not part or re.search(r'[\x00-\x1f]', part):
            raise ValueError('标准编号和条款编号必须为非空文本且不能含控制字符')
        parts.append(part)
    stem = ' '.join(parts).rstrip(' .')
    if len(stem) > 240:
        raise ValueError('标准编号与条款编号组合超过安全文件名长度')
    if re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', stem, re.I):
        raise ValueError('文件名为Windows保留名称')
    return stem + '.json'


def supplemental_identity(payload: dict) -> str | None:
    metadata = payload.get('metadata', {})
    if not isinstance(metadata, dict):
        return None
    batch = metadata.get('batch', '')
    prefix = _PREFIXES.get(batch)
    if isinstance(batch, str) and re.fullmatch(r'assistant_remaining_\d{3}', batch):
        prefix = 'supp_remaining_' + batch.rsplit('_', 1)[1] + '_'
    if not prefix or metadata.get('dataset') != 'supplemental_excel':
        return None
    rules = payload.get('rules', [])
    if len(rules) != 1 or not isinstance(rules[0], dict):
        raise ValueError('已知补充批次须有一条完整原文规则')
    key = str(payload['standard_id']) + '\0' + str(rules[0]['content'])
    return prefix + hashlib.sha256(key.encode('utf-8')).hexdigest()[:32]


def rename_supplemental_files(directory: Path, *, apply: bool = False) -> dict:
    directory = Path(directory).resolve()
    expected = (DEFAULT_ROOT / '分解数据' / 'json').resolve()
    if directory != expected:
        raise ValueError('本次重命名只允许明确的独立补充库目录')
    plans, targets = [], set()
    for path in sorted(directory.glob('*.json')):
        raw = path.read_bytes()
        payload = json.loads(raw.decode('utf-8'))
        identity = supplemental_identity(payload)
        if identity is None:
            raise ValueError(f'不属于已确认补充批次：{path.name}')
        filename = clause_filename(payload['standard_id'], payload['chapter_path'])
        folded = filename.casefold()
        if folded in targets:
            raise ValueError(f'目标名称重名，拒绝覆盖：{filename}')
        targets.add(folded)
        target = directory / filename
        if target.parent != directory or (target.exists() and target != path):
            raise ValueError(f'目标已存在或越界：{filename}')
        plans.append({'old_name': path.name, 'new_name': filename,
                      'internal_id': identity, 'batch': payload['metadata']['batch'],
                      'sha256': hashlib.sha256(raw).hexdigest()})
    report = {'directory': str(directory), 'file_count': len(plans),
              'renamed_count': sum(p['old_name'] != p['new_name'] for p in plans),
              'applied': apply, 'content_unchanged': True, 'items': plans}
    if not apply:
        return report
    if report['renamed_count'] == 0:
        return report  # retain the original old-to-new audit mapping on repeat runs
    done = []
    try:
        for plan in plans:
            if plan['old_name'] != plan['new_name']:
                (directory / plan['old_name']).rename(directory / plan['new_name'])
                done.append(plan)
        for plan in plans:
            if hashlib.sha256((directory / plan['new_name']).read_bytes()).hexdigest() != plan['sha256']:
                raise ValueError('重命名后正文内容哈希发生变化')
    except Exception:
        for plan in reversed(done):
            (directory / plan['new_name']).rename(directory / plan['old_name'])
        raise
    for batch, summary_name in (('assistant_first100', '首批100条入库汇总.json'),
                                ('assistant_additional1000', '新增1000条入库汇总.json')):
        summary_path = directory.parent / summary_name
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding='utf-8'))
            mapping = {p['old_name']: p['new_name'] for p in plans if p['batch'] == batch}
            summary['clause_files'] = [mapping.get(name, name) for name in summary['clause_files']]
            summary['filename_format'] = 'standard_id chapter_path.json（Windows禁用字符替换为全角字符）'
            _write_json(summary_path, summary)
    _write_json(directory.parent / 'JSON文件重命名记录.json', report)
    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    result = rename_supplemental_files(DEFAULT_ROOT / '分解数据' / 'json', apply=args.apply)
    print(json.dumps({k: v for k, v in result.items() if k != 'items'}, ensure_ascii=False, indent=2))
