"""Inventory remaining source records without claiming semantic decomposition."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from .clause_filenames import clause_filename
from .supplemental_excel import DEFAULT_ROOT, _write_json


def inventory(index: Path, completed: Path) -> dict:
    raw = index.read_bytes()
    rows = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
    seen = set()
    occupied = set()
    for path in completed.glob('*.json'):
        payload = json.loads(path.read_text(encoding='utf-8'))
        occupied.add(path.name.casefold())
        seen.update((payload['standard_id'], rule['content']) for rule in payload.get('rules', []))
    canonical = {}
    pending = []
    covered = []
    filenames = {}
    for line, row in enumerate(rows, 1):
        key = (row['standard_id'], row['text'])
        if key in seen:
            covered.append(line)
            continue
        if key in canonical:
            canonical[key]['duplicate_source_lines'].append(line)
            continue
        number = re.match(r'^\s*(\d+(?:\.\d+)*)(?=\s|$)', row['text'])
        issues = []
        candidate = ''
        if number:
            try:
                candidate = clause_filename(row['standard_id'], number[1])
            except ValueError:
                issues.append('filename_not_valid')
        else:
            issues.append('no_unambiguous_leading_numeric_clause_number')
        if candidate:
            filename = candidate.casefold()
            if filename in occupied:
                issues.append('filename_conflicts_with_completed_record')
            filenames.setdefault(filename, []).append(line)
        item = {'index_line': line, **row,
                'duplicate_source_lines': [], 'candidate_filename': candidate,
                'preflight_issues': issues, 'status': 'pending_semantic_decomposition'}
        canonical[key] = item
        pending.append(item)
    collisions = {name: lines for name, lines in filenames.items() if len(lines) > 1}
    for item in pending:
        if item['candidate_filename'].casefold() in collisions:
            item['preflight_issues'].append('filename_conflicts_with_other_pending_record')
    duplicate_count = sum(len(item['duplicate_source_lines']) for item in pending)
    counts = Counter(issue for item in pending for issue in item['preflight_issues'])
    return {
        'status': 'inventory_only_not_decomposed_not_published',
        'source_index_sha256': hashlib.sha256(raw).hexdigest(),
        'source_row_count': len(rows), 'completed_source_row_count': len(covered),
        'remaining_source_row_count': len(rows) - len(covered),
        'remaining_unique_record_count': len(pending),
        'remaining_duplicate_source_row_count': duplicate_count,
        'covered_source_lines': covered,
        'preflight_issue_record_counts': dict(counts),
        'filename_collision_group_count': len(collisions),
        'policy': '仅做来源清单与重复/文件名检查，不进行语义分解，不修正文号、原文、数字或单位，不写入知识库',
        'items': pending,
    }


def main():
    output = DEFAULT_ROOT / '分解数据' / '剩余补充条款待分解清单.json'
    result = inventory(DEFAULT_ROOT / '子条款' / '子条款索引.jsonl',
                       DEFAULT_ROOT / '分解数据' / 'json')
    _write_json(output, result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('items', 'covered_source_lines')},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
