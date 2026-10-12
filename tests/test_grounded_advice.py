import json
from copy import deepcopy
from types import SimpleNamespace
import pytest

from standard_knowledge_service_v2.application.grounded_advice import GroundedAdviceService
from standard_knowledge_service_v2.application.analysis_pipeline import AnalysisPipeline
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.decomposition import RawTextFallback
from standard_knowledge_service_v2.domain import ClauseKnowledgeUnit, Rule, Entity
from standard_knowledge_service_v2.instruction_engine.simulation_control import SimulationControlSession
from standard_knowledge_service_v2.instruction_engine.semantic_extractor import SemanticExtractor
from standard_knowledge_service_v2.instruction_engine.instruction_generator import InstructionGenerationService
from standard_knowledge_service_v2.validation.applicability_validator import ApplicabilityValidator


class Client:
    def __init__(self, result):
        self.result = result
        self.packet = None
    def complete(self, system, user):
        self.packet = json.loads(user)
        return json.dumps(self.result, ensure_ascii=False)


def setup(action='trip', condition='current >= 100', reviewed=True):
    # Explicit synthetic source binding exists only in this test, never in the real database.
    unit = ClauseKnowledgeUnit('TEST-SYNTHETIC', 'TEST-NOT-A-STANDARD', '1', '1', '模拟断路器测试过流分闸规则',
        [Entity('e1', '断路器', '设备')],
        [Rule('r1', '断路器', action, condition, content='测试条件满足时模拟分闸')],
        metadata={'audit': {'manual_review_required': not reviewed}})
    repo = SimpleNamespace(unit_for_rule=lambda rid: unit if rid == 'r1' else None)
    pipeline = SimpleNamespace(retriever=SimpleNamespace(repository=repo), simulation_session=SimulationControlSession(),
                               applicability=ApplicabilityValidator(), extractor=SemanticExtractor(), generator=InstructionGenerationService())
    pipeline.simulation_session.service.devices['SIM-IEC-BREAKER-01']['actions']['trip']['source_rule_ids'] = ['r1']
    data = {'selected_rule': {'rule_id': 'r1'}, 'answer': {'text': '原文结论'}, 'candidate_instruction': None}
    proposal = {'summary': '按提供的测试规则和电流事实给出建议', 'rule_ids': ['r1'],
                'suggestions': [{'text': '核对测试条件和设备状态', 'rule_ids': ['r1']}],
                'instruction': {'text': '建议模拟断路器分闸', 'device_id': 'SIM-IEC-BREAKER-01',
                                'action': 'trip', 'parameters': {}, 'rule_ids': ['r1']}}
    request = AnalysisRequest('模拟断路器1目前状态是否正常？', parameters={'simulation_mode': True, 'current': 999})
    return pipeline, data, proposal, request


def test_model_advice_template_confirm_closed_loop():
    pipeline, data, proposal, request = setup()
    client = Client(proposal)
    before = pipeline.simulation_session.snapshot()
    assert GroundedAdviceService(client).enrich(pipeline, request, data) == 'generated'
    assert client.packet['device']['runtime_facts']['current'] == 120  # Never user-injected 999.
    assert client.packet['clauses'][0]['quote'] == '测试条件满足时模拟分闸'
    assert before == pipeline.simulation_session.snapshot()
    assert data['candidate_instruction']['payload']['requested_action'] == 'trip'
    assert before == pipeline.simulation_session.snapshot()

@pytest.mark.parametrize('kwargs', [{'action': ''}, {'condition': 'current >= 200'}, {'condition': '无法编译的自然语言'}, {'reviewed': False}])
def test_invalid_basis_or_condition_no_payload(kwargs):
    pipeline, data, proposal, request = setup(**kwargs)
    GroundedAdviceService(Client(proposal)).enrich(pipeline, request, data)
    assert not (data.get('candidate_instruction') or {}).get('payload')
    assert not hasattr(pipeline.simulation_session, 'tasks')


@pytest.mark.parametrize('mutation', ['citation', 'target', 'extra_parameter', 'extra_field', 'text_mismatch', 'no_binding'])
def test_invalid_model_output_or_mapping_blocks(mutation):
    pipeline, data, proposal, request = setup()
    if mutation == 'citation': proposal['rule_ids'] = ['fake']
    if mutation == 'target': proposal['instruction']['device_id'] = 'REAL-01'
    if mutation == 'extra_parameter': proposal['instruction']['parameters'] = {'payload': 'untrusted'}
    if mutation == 'extra_field': proposal['instruction']['payload'] = {'execute': True}
    if mutation == 'text_mismatch': proposal['instruction']['text'] = '建议合闸'
    if mutation == 'no_binding': pipeline.simulation_session.service.devices['SIM-IEC-BREAKER-01']['actions']['trip'].pop('source_rule_ids')
    GroundedAdviceService(Client(proposal)).enrich(pipeline, request, data)
    assert not (data.get('candidate_instruction') or {}).get('payload')
    assert not hasattr(pipeline.simulation_session, 'tasks')


def test_unavailable_model_does_not_fake_advice():
    pipeline, data, _, request = setup()
    GroundedAdviceService().enrich(pipeline, request, data)
    assert data['advice']['source'] == 'not_generated'
    assert data['answer']['text'] == '原文结论'


def test_model_failure_and_empty_sources_fail_closed():
    pipeline, data, _, request = setup()
    data['candidate_instruction'] = {'payload': {'old': 'candidate'}}
    GroundedAdviceService(Client({'bad': True})).enrich(pipeline, request, data)
    assert data['advice']['status'] == 'unavailable'
    assert data['candidate_instruction']['payload'] == {}
    data['selected_rule']['rule_id'] = 'absent'
    GroundedAdviceService(Client({'bad': True})).enrich(pipeline, request, data)
    assert data['candidate_instruction']['payload'] == {}


def test_inspection_only_advice_and_ambiguous_target():
    pipeline, data, proposal, request = setup(action='')
    proposal['instruction'] = None
    GroundedAdviceService(Client(proposal)).enrich(pipeline, request, data)
    assert data['advice']['status'] == 'generated'
    assert data['candidate_instruction'] is None
    pipeline, data, proposal, request = setup()
    request.query = '模拟断路器1和模拟断路器2目前状态如何？'
    GroundedAdviceService(Client(proposal)).enrich(pipeline, request, data)
    assert data['advice']['conversion']['status'] == 'blocked'


def test_pipeline_status_question_can_propose_without_execution_request():
    base, _, proposal, request = setup()
    class Retriever:
        repository = base.retriever.repository
        def match(self, *args):
            unit = self.repository.unit_for_rule('r1')
            return SimpleNamespace(rules=[SimpleNamespace(rule=unit.rules[0], rank=1, combined_score=1)])
    pipeline = AnalysisPipeline(Retriever(), decomposer=RawTextFallback())
    pipeline.simulation_session = base.simulation_session
    pipeline.advisor = GroundedAdviceService(Client(proposal))
    result = pipeline.analyze(request)
    assert result.status == 'generated'
    assert result.data['advice']['source'] == 'llm'
    assert result.data['instruction_generation']['status'] == 'generated'
