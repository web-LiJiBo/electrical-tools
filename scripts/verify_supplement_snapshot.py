"""Read-only verification of the published supplemental snapshot; never calls models."""
import argparse
import hashlib
import json
import os
from pathlib import Path

from standard_knowledge_service_v2.data_ingestion.clause_filenames import supplemental_identity


def verify(directory: Path, source: Path | None = None):
    record_hashes = []
    identities = set()
    count = total = reviewed = rules = 0
    # Stream directory entries rather than retaining tens of thousands of Path objects.
    for entry in scan_json(directory):
        path = Path(entry.path)
        raw = path.read_bytes()
        payload = json.loads(raw.decode('utf-8'))
        if not isinstance(payload, dict) or not isinstance(payload.get('rules'), list):
            raise ValueError('条款结构异常：' + path.name)
        identity = supplemental_identity(payload)
        if not identity or identity in identities:
            raise ValueError('内部标识缺失或重复：' + path.name)
        identities.add(identity)
        if source is not None and raw != (source / path.name).read_bytes():
            raise ValueError('复制后内容变化：' + path.name)
        record_hashes.append(hashlib.sha256(path.name.encode('utf-8') + b'\0' + hashlib.sha256(raw).digest()).digest())
        count += 1
        total += len(raw)
        rules += len(payload['rules'])
        reviewed += payload.get('metadata', {}).get('audit', {}).get('manual_review_required') is True
    if source is not None and count != sum(1 for _ in scan_json(source)):
        raise ValueError('源目录与快照数量不同')
    if not count:
        raise ValueError('快照为空')
    return {'file_count': count, 'total_bytes': total, 'rule_count': rules,
            'manual_review_required_count': reviewed, 'unique_clause_ids': len(identities),
            'sorted_record_hashes_sha256': hashlib.sha256(b''.join(sorted(record_hashes))).hexdigest(),
            'source_byte_comparison': source is not None, 'all_json_valid': True}


def scan_json(directory):
    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.name.endswith('.json') and entry.is_file(follow_symlinks=False):
                yield entry


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, default=Path(__file__).resolve().parents[1] / 'datasets/supplemental/分解数据/json')
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.directory, args.source), ensure_ascii=False))
