"""Knowledge retrieval must work for supplemental clauses without control fields."""
from types import SimpleNamespace
import json
from pathlib import Path

import pytest
from fastapi import FastAPI

from standard_knowledge_service_v2.api.routes import register_routes
from standard_knowledge_service_v2.application.analysis_pipeline import AnalysisPipeline
from standard_knowledge_service_v2.application.grounded_advice import GroundedAdviceService
from standard_knowledge_service_v2.application.search_service import SearchService
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.decomposition.fallback import RawTextFallback
from standard_knowledge_service_v2.domain import ClauseKnowledgeUnit, Entity, Rule
from standard_knowledge_service_v2.retrieval import LunwenMatchingInput
from standard_knowledge_service_v2.retrieval_engine import JsonClauseRepository, LocalLunwenRetrievalAdapter


def unit(identifier, content, *, action='', reasons=(), dataset='supplemental_excel'):
    return ClauseKnowledgeUnit(
        identifier, 'TEST-2026', '2026', '5.1', content,
        entities=[Entity(identifier + ':entity', '监测井', '设备')],
        rules=[Rule(identifier + ':rule', '监测井', action, '', content=content,
                    operation=content, constraints=[])],
        metadata={'dataset': dataset, 'audit': {'manual_review_required': True, 'reasons': list(reasons)}},
    )


@pytest.mark.parametrize('intent', ['search', 'compliance', 'difference'])
def test_knowledge_score_does_not_depend_on_control_action_field(intent):
    text = '监测井建设时应检查井管和成井质量。'
    parsed = {'intent': intent, 'actions': ['inspect'], 'keywords': ['成井质量']}
    def score(action):
        adapter = LocalLunwenRetrievalAdapter(JsonClauseRepository([unit('a', text, action=action)]))
        return adapter.match(LunwenMatchingInput('如何检查监测井成井质量？', parsed)).rules[0].combined_score
    assert score('') == pytest.approx(score('inspect'))


def test_explicit_instruction_keeps_action_matching():
    text = '监测井建设时应检查井管和成井质量。'
    def score(action):
        adapter = LocalLunwenRetrievalAdapter(JsonClauseRepository([unit('a', text, action=action)]))
        return adapter.match(LunwenMatchingInput(text, {'intent': 'instruction', 'actions': ['inspect']})).rules[0].combined_score
    assert score('inspect') > score('')


def test_generated_action_code_does_not_match_english_term_in_knowledge_query():
    old_path = Path(__file__).resolve().parents[1] / 'datasets/lunwen/verified_json/json/1000_clause1.json'
    old = JsonClauseRepository._from_payload(old_path, json.loads(old_path.read_text(encoding='utf-8')))
    term = unit('unrelated', '2.0.3 基线检测 baseline inspection')
    term.entities = [Entity('term', '基线检测 baseline inspection', '条款对象')]
    adapter = LocalLunwenRetrievalAdapter(JsonClauseRepository([old, term]))
    query = '电流互感器红外热像检测巡检周期如何规定？'
    parsed = RawTextFallback().decompose(query).to_lunwen_parsed_json() | {'intent': 'search'}
    with_code = adapter.match(LunwenMatchingInput(query, parsed))
    without_code = adapter.match(LunwenMatchingInput(query, {**parsed, 'actions': [], 'keywords': []}))
    assert with_code.rules[0].rule.rule_id == old.rules[0].rule_id
    assert with_code.rules[0].combined_score == pytest.approx(without_code.rules[0].combined_score)
    pipeline = AnalysisPipeline(adapter, decomposer=RawTextFallback())
    response = pipeline.analyze(AnalysisRequest(query))
    assert response.data['selected_rule']['rule_id'] == old.rules[0].rule_id


def test_reviewed_heading_is_not_returned_as_answer_evidence():
    title = unit('heading', '5.1 环境监测井建设', reasons=['助手语义初稿；仅标题'])
    body = unit('body', '环境监测井建设时应检查井管和成井质量。')
    adapter = LocalLunwenRetrievalAdapter(JsonClauseRepository([title, body]))
    result = adapter.match(LunwenMatchingInput('环境监测井应如何建设？', {'intent': 'search'}))
    assert [hit.rule.rule_id for hit in result.rules] == ['body:rule']
    assert len(adapter.repository.units) == 2  # Keep headings in the source library.


def test_scope_question_returns_scope_paragraph_instead_of_term_name():
    term = unit('term', '电力软交换系统 powersoftswitch system')
    scope = unit('scope', '本标准规定了电力软交换系统的组成，明确各部分的功能要求。本标准适用于电力软交换系统的规划设计、工程建设及设备研制。')
    adapter = LocalLunwenRetrievalAdapter(JsonClauseRepository([term, scope]))
    decomposed = RawTextFallback().decompose('电力软交换系统适用于哪些工作？')
    parsed = decomposed.to_lunwen_parsed_json() | {'intent': 'search'}
    result = adapter.match(LunwenMatchingInput('电力软交换系统适用于哪些工作？', parsed))
    assert result.rules[0].rule.rule_id == 'scope:rule'


def test_published_standard_scope_question_returns_applicability_body():
    directory = Path(__file__).resolve().parents[1] / 'datasets/supplemental/分解数据/json'
    units = []
    for path in directory.glob('F 21 *.json'):
        payload = json.loads(path.read_text(encoding='utf-8'))
        if payload.get('standard_id') == 'GB/T 31998-2015':
            units.append(JsonClauseRepository._from_payload(path, payload))
    assert units, '发布的电力软交换系统标准应能被读取'
    pipeline = AnalysisPipeline(LocalLunwenRetrievalAdapter(JsonClauseRepository(units)), decomposer=RawTextFallback())
    response = pipeline.analyze(AnalysisRequest('电力软交换系统适用于哪些工作？',
        parameters={'standard_id': 'GB/T 31998-2015'}))
    assert response.status == 'answered'
    assert '适用于电力软交换系统的规划设计' in response.data['answer']['text']
    assert response.data['candidate_instruction'] is None


def test_analysis_passes_query_intent_and_answers_without_control_fields(monkeypatch):
    body = unit('new', '监测井建设时应检查井管和成井质量。')
    adapter = LocalLunwenRetrievalAdapter(JsonClauseRepository([body]))
    captured = []
    original = adapter.match
    def record(request):
        captured.append(request.parsed_json)
        return original(request)
    monkeypatch.setattr(adapter, 'match', record)
    pipeline = AnalysisPipeline(adapter, decomposer=RawTextFallback())
    result = pipeline.analyze(AnalysisRequest('监测井建设时应如何检查成井质量？'))
    assert captured[0].get('intent') == 'search'
    assert result.status == 'answered'
    assert result.data['candidate_instruction'] is None
    assert result.evidence[0]['clause_id'] == 'new'
    assert result.data['selected_rule']['content'] == body.text


def test_search_service_marks_search_without_mutating_caller_input():
    captured = []
    adapter = SimpleNamespace(match=lambda request: captured.append(request))
    parsed = {'actions': ['inspect']}
    SearchService(adapter).search('监测井如何检查？', parsed)
    assert captured[0].parsed_json.get('intent') == 'search'
    assert 'intent' not in parsed


def test_search_endpoint_marks_search_even_when_query_mentions_actions():
    captured = []
    adapter = SimpleNamespace(match=lambda request: captured.append(request) or SimpleNamespace(matched_entities=[], rules=[], warnings=[]))
    facade = SimpleNamespace(decomposer=RawTextFallback(), retriever=adapter)
    app = FastAPI()
    register_routes(app, SimpleNamespace(facade=facade, audit_store=None))
    endpoint = next(route.endpoint for route in app.routes if getattr(route, 'path', '') == '/search')
    endpoint({'query': '监测井如何检测？'})
    assert captured[0].parsed_json.get('intent') == 'search'


def test_model_analysis_accepts_new_clause_without_control_fields():
    body = unit('new', '监测井建设时应检查井管和成井质量。')
    class SourceAnalysisClient:
        def complete(self, prompt, payload):
            packet = json.loads(payload)
            source = packet['clauses'][0]
            assert source['action'] == '' and source['condition'] == ''
            return json.dumps({'summary': '依据检索条款，应核对井管及成井质量。',
                'rule_ids': [source['rule_id']],
                'suggestions': [{'text': '核对井管和成井质量记录。', 'rule_ids': [source['rule_id']]}],
                'instruction': None}, ensure_ascii=False)
    pipeline = AnalysisPipeline(LocalLunwenRetrievalAdapter(JsonClauseRepository([body])), decomposer=RawTextFallback())
    pipeline.advisor = GroundedAdviceService(SourceAnalysisClient())
    response = pipeline.analyze(AnalysisRequest('监测井建设时应如何检查成井质量？'))
    assert response.status == 'answered'
    assert response.data['advice']['status'] == 'generated'
    assert response.data['advice']['sources'][0]['quote'] == body.text
    assert response.data['advice']['sources'][0]['manual_review_required'] is True
    assert response.data['candidate_instruction'] is None
