import hashlib
import json
from pathlib import Path

import pytest

from standard_knowledge_service_v2.bootstrap import build_application
from standard_knowledge_service_v2.data_ingestion.reviewed_batch import SOURCE_SHA256, publish_reviewed_batch
from standard_knowledge_service_v2.data_ingestion.supplemental_excel import DEFAULT_ROOT
from standard_knowledge_service_v2.retrieval import LunwenMatchingInput
from standard_knowledge_service_v2.retrieval_engine.clause_retriever import JsonClauseRepository


ROOT = Path(__file__).resolve().parents[1]
INDEX = DEFAULT_ROOT / '子条款' / '子条款索引.jsonl'
ANNOTATIONS = DEFAULT_ROOT / '分解数据' / '首批100条助手语义分解.json'
DATA = DEFAULT_ROOT / '分解数据' / 'json'


@pytest.mark.skipif(not INDEX.exists(), reason='本地独立补充数据未安装')
def test_hundred_decompositions_preserve_original_number_text_and_metadata():
    assert hashlib.sha256(INDEX.read_bytes()).hexdigest() == SOURCE_SHA256
    sources = [json.loads(line) for line in INDEX.read_text(encoding='utf-8').splitlines()]
    annotations = json.loads(ANNOTATIONS.read_text(encoding='utf-8'))['items']
    payloads = [json.loads(p.read_text(encoding='utf-8')) for p in DATA.glob('*.json')]
    payloads = [p for p in payloads if p.get('metadata', {}).get('batch') == 'assistant_first100']
    assert len(payloads) == len(annotations) == 100
    keyed = {(p['standard_id'], p['rules'][0]['content']): p for p in payloads}
    for line, subject, operation, condition, quote, reason in annotations:
        source = sources[line - 1]
        payload = keyed[(source['standard_id'], source['text'])]
        assert payload['standard_name'] == source['standard_name']
        assert payload['chapter_path'] == source['text'].split()[0]
        assert payload['rules'][0]['subject'] == subject
        assert payload['rules'][0]['operation'] == operation
        assert payload['rules'][0]['condition'] == condition
        assert payload['metadata']['audit']['manual_review_required'] == bool(reason)
        assert payload['rules'][0]['action'] == ''


@pytest.mark.skipif(not INDEX.exists(), reason='本地独立补充数据未安装')
def test_ocr_bad_rate_not_rewritten_or_enabled_as_control():
    payloads = [json.loads(p.read_text(encoding='utf-8')) for p in DATA.glob('*.json')]
    rate = next(p for p in payloads if p['standard_id'] == 'DEC-OTP-G-IS-001-2025-2' and p['chapter_path'] == '4.2.4')
    assert '1000' in rate['rules'][0]['constraint']
    assert '100%' not in rate['rules'][0]['content']
    assert rate['metadata']['audit']['manual_review_required'] is True
    assert rate['rules'][0]['constraint_role'] == 'informational'


@pytest.mark.skipif(not INDEX.exists(), reason='本地独立补充数据未安装')
def test_same_loader_combines_original_and_supplemental_and_retrieves_new_clause():
    app = build_application(ROOT / 'configs/settings.offline.yaml')
    repo = app.facade.retriever.repository
    original = JsonClauseRepository.from_directory(ROOT / 'datasets/lunwen/verified_json/json')
    supplemental = JsonClauseRepository.from_directory(DATA)
    assert len(repo.units) == len(original.units) + len(supplemental.units)
    assert sum(u.metadata.get('dataset') == 'supplemental_excel' for u in repo.units) == len(supplemental.units)
    assert len({u.clause_id for u in repo.units}) == len(repo.units)
    result = app.facade.retriever.match(LunwenMatchingInput(
        '空气压缩机能效试验吸气温度范围',
        {'entities': [{'name': '空气压缩机', 'type': '设备'}], 'keywords': ['吸气温度', '试验方法']}, top_k_rules=5))
    unit = repo.unit_for_rule(result.rules[0].rule.rule_id)
    assert unit.standard_id == 'GB 19153-2019'
    assert unit.chapter_path == '6.2'
    assert '5 ℃~40 ℃' in result.rules[0].rule.content
    assert result.rules[0].rule.action == ''


@pytest.mark.skipif(not INDEX.exists(), reason='本地独立补充数据未安装')
def test_repeat_publish_is_idempotent_and_rejects_changed_source(tmp_path):
    output = tmp_path / 'json'
    first = publish_reviewed_batch(INDEX, ANNOTATIONS, output)
    second = publish_reviewed_batch(INDEX, ANNOTATIONS, output)
    assert first['clause_files'] == second['clause_files']
    assert len(list(output.glob('*.json'))) == 100
    changed = tmp_path / 'changed.jsonl'
    changed.write_text('{}\n', encoding='utf-8')
    with pytest.raises(ValueError, match='来源索引已变化'):
        publish_reviewed_batch(changed, ANNOTATIONS, output)
    assert len(list(output.glob('*.json'))) == 100
