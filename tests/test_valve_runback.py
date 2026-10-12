import json
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace

import pytest
from standard_knowledge_service_v2.application.grounded_advice import GroundedAdviceService
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.instruction_engine.simulation import SimulationInstructionService
from standard_knowledge_service_v2.instruction_engine.simulation_control import SimulationControlSession
from standard_knowledge_service_v2.instruction_engine.semantic_extractor import SemanticExtractor
from standard_knowledge_service_v2.instruction_engine.instruction_generator import InstructionGenerationService
from standard_knowledge_service_v2.retrieval_engine.clause_retriever import JsonClauseRepository
from standard_knowledge_service_v2.validation.applicability_validator import ApplicabilityValidator

DEVICE = 'SIM-IEC-VALVE-01'
RID = '1626_clause2:rule:1'
ROOT = Path(__file__).resolve().parents[1]


def prepare():
    repository = JsonClauseRepository.from_directory(ROOT / 'datasets/lunwen/verified_json/json', limit=None)
    session = SimulationControlSession()
    pipeline = SimpleNamespace(retriever=SimpleNamespace(repository=repository), simulation_session=session,
        applicability=ApplicabilityValidator(), extractor=SemanticExtractor(), generator=InstructionGenerationService())
    data = {'selected_rule': {'rule_id': RID}, 'candidate_instruction': None, 'answer': {'text': '来源回答'}}
    class Stub:
        def complete(self, system, user):
            packet = json.loads(user)
            assert packet['device']['state']['active_power_mw'] == 100
            assert packet['action_templates']['runback_power']['unit'] == 'MW'
            return json.dumps({'summary': '按来源要求进行模拟功率回降，不闭锁直流。', 'rule_ids': [RID],
                'suggestions': [{'text': '使用模拟配置的80 MW目标；不是温度定值。', 'rule_ids': [RID]}],
                'instruction': {'text': '建议模拟换流阀1功率回降至80 MW', 'device_id': DEVICE,
                                'action': 'runback_power', 'parameters': {'target_power_mw': 80}, 'rule_ids': [RID]}}, ensure_ascii=False)
    request = AnalysisRequest('模拟换流阀1的阀出水温度保护动作后，应如何处理？', parameters={'simulation_mode': True})
    return pipeline, data, request, Stub()


def test_real_source_runback_template_confirm():
    pipeline, data, request, client = prepare()
    assert GroundedAdviceService(client).enrich(pipeline, request, data) == 'generated'
    session = pipeline.simulation_session
    assert session.service.states[DEVICE]['active_power_mw'] == 100
    assert data['candidate_instruction']['payload']['ctlVal'] == 80
    assert not hasattr(session, 'confirm')

@pytest.mark.parametrize('field,value', [('outlet_temperature_protection_operated', 0),
    ('runback_permission', 0), ('runback_target_configured', 0), ('runback_applied', 1),
    ('runback_target_mw', 90), ('runback_target_mw', None), ('dc_blocked', 1)])
def test_invalid_runback_facts_no_payload(field, value):
    service = SimulationInstructionService()
    facts = deepcopy(service.devices[DEVICE]['runtime_facts'])
    facts[field] = value
    candidate = service.generate(DEVICE, 'runback_power', facts, {'target_power_mw': 80})
    assert not candidate.payload
    assert service.states[DEVICE]['active_power_mw'] == 100


def test_runback_does_not_increase_power():
    service = SimulationInstructionService()
    service.states[DEVICE]['active_power_mw'] = 70
    assert not service.generate(DEVICE, 'runback_power', service.devices[DEVICE]['runtime_facts'], {'target_power_mw': 80}).payload


@pytest.mark.parametrize('text', ['功率回降至90MW', '功率回降至80MW并直流闭锁'])
def test_runback_text_mismatch_rejected(text):
    source = {'1626_clause2:rule:1': None}
    raw = {'summary': 'test', 'rule_ids': [RID], 'suggestions': [],
        'instruction': {'text': text, 'device_id': DEVICE, 'action': 'runback_power',
                        'parameters': {'target_power_mw': 80}, 'rule_ids': [RID]}}
    with pytest.raises(ValueError): GroundedAdviceService._validate(raw, source)
