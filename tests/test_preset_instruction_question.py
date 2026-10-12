"""Reproducible status-question case; synthetic source and model stub only."""
import json
from pathlib import Path

from standard_knowledge_service_v2.application.analysis_pipeline import AnalysisPipeline
from standard_knowledge_service_v2.application.grounded_advice import GroundedAdviceService
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.decomposition import RawTextFallback
from standard_knowledge_service_v2.domain import ClauseKnowledgeUnit, Entity, Rule
from standard_knowledge_service_v2.retrieval_engine.clause_retriever import JsonClauseRepository
from standard_knowledge_service_v2.retrieval_engine.lunwen_adapter import LocalLunwenRetrievalAdapter


def test_preset_status_question_retrieval_advice_confirm():
    case = json.loads((Path(__file__).parent / 'fixtures/instruction_question.json').read_text(encoding='utf-8'))
    source = case['source']
    unit = ClauseKnowledgeUnit(source['clause_id'], source['standard_id'], 'TEST', 'TEST-1', source['text'],
        entities=[Entity('TEST-breaker', '断路器', '设备')],
        rules=[Rule(source['rule_id'], '断路器', source['action'], source['condition'], content=source['text'])],
        metadata={'audit': {'manual_review_required': False}, 'synthetic_test_only': True})
    # Isolated repository: no production standards or global template files modified.
    pipeline = AnalysisPipeline(LocalLunwenRetrievalAdapter(JsonClauseRepository([unit])), decomposer=RawTextFallback())
    session = pipeline.simulation_session
    session.service.devices[case['device_id']]['actions']['trip']['source_rule_ids'] = [source['rule_id']]

    class AdviceStub:
        def complete(self, system, user):
            packet = json.loads(user)
            assert packet['device']['runtime_facts']['current'] == case['expected']['current']
            assert any(c['rule_id'] == source['rule_id'] and c['quote'] == source['text'] for c in packet['clauses'])
            return json.dumps({
                'summary': '依据独立测试规则，电流120 A满足测试分闸条件100 A；当前开关仍合闸。',
                'rule_ids': [source['rule_id']],
                'suggestions': [{'text': '建议核对模拟过流状态，并确认模拟分闸。', 'rule_ids': [source['rule_id']]}],
                'instruction': {'text': '建议模拟断路器1分闸', 'device_id': case['device_id'],
                                'action': 'trip', 'parameters': {}, 'rule_ids': [source['rule_id']]}
            }, ensure_ascii=False)

    pipeline.advisor = GroundedAdviceService(AdviceStub())
    response = pipeline.analyze(AnalysisRequest(case['question'], parameters=case['parameters']))
    assert source['rule_id'] in [r['rule_id'] for r in response.data['matching']['rules']]
    assert response.status == 'generated'
    assert response.data['instruction_generation']['status'] == 'generated'
    assert response.data['candidate_instruction']['payload']['requested_action'] == 'trip'
    assert session.service.states[case['device_id']]['position'] == 'closed'
    assert not hasattr(session, 'confirm')
