from test_grounded_advice import Client, setup
import pytest
from standard_knowledge_service_v2.application.grounded_advice import GroundedAdviceService


def test_direct_advice_refusal_does_not_leave_an_adopted_conclusion():
    pipeline, data, _, request = setup()
    data['answer'].update(conclusion='旧条文被误采用', source_rule_id='r1')
    data['validation'] = {'status': 'answered', 'dispatch_allowed': False}
    result = {'summary': '现有来源无法回答检修恢复问题', 'answer_supported': False,
              'support_assessments': [{'rule_id': 'r1', 'supports_answer': False, 'reason': '设备及主题不符'}],
              'unable_reason': '需要变压器检修试验适用条文', 'rule_ids': [], 'suggestions': [], 'instruction': None}
    assert GroundedAdviceService(Client(result)).enrich(pipeline, request, data) == 'uncertain'
    assert 'conclusion' not in data['answer'] and 'source_rule_id' not in data['answer']
    assert data['validation']['status'] == 'uncertain'


def test_analysis_only_blocks_model_instruction_before_conversion(monkeypatch):
    pipeline, data, proposal, request = setup()
    data['decomposition'] = {'request_controls': {'analysis_only': True, 'source_text': '不要生成设备指令'}}
    def forbidden(*args, **kwargs):
        raise AssertionError('analysis-only must not call instruction conversion')
    monkeypatch.setattr('standard_knowledge_service_v2.application.grounded_advice.convert_advice', forbidden)
    result = GroundedAdviceService(Client(proposal)).enrich(pipeline, request, data)
    assert result != 'generated'
    assert data['advice']['instruction'] is None
    assert data['advice']['summary'] == proposal['summary']
    assert data['advice']['conversion']['status'] == 'not_proposed'
    assert not data.get('simulation_preview')
    assert data['candidate_instruction'] is None


def test_missing_standard_identity_cannot_be_upgraded_by_a_supportive_model():
    pipeline, data, proposal, request = setup()
    source = pipeline.retriever.repository.unit_for_rule('r1')
    source.standard_id = '未标注标准'
    source.version = ''
    request.query = '变压器检修后试验如何合格？请引用标准编号、版本和条款。'
    proposal['instruction'] = None
    client = Client(proposal)
    assert GroundedAdviceService(client).enrich(pipeline, request, data) == 'uncertain'
    assert client.packet['clauses'][0]['source_quality']['standard_identity'] == 'missing'
    assert data['advice']['answer_supported'] is False
    assert data['advice']['sources'] == []
    assert data['source_quality']['formal_citation_ready'] is False
    assert '编号' in data['answer']['text'] and '版本' in data['answer']['text']


@pytest.mark.parametrize('failure', ['invalid_schema', 'invalid_citation', 'timeout', 'disabled'])
def test_unavailable_advice_with_unverified_formal_sources_withdraws_old_answer(failure):
    from test_answer_integrity import adopted_answer
    from standard_knowledge_service_v2.application.analysis_pipeline import AnalysisPipeline
    pipeline, _, proposal, request = setup()
    source = pipeline.retriever.repository.unit_for_rule('r1')
    source.standard_id, source.version = '未标注标准', ''
    request.query = '变压器检修试验如何判断合格？请引用适用标准的编号、版本和条款，不要生成设备指令。'
    data = adopted_answer()
    if failure == 'invalid_schema':
        client = Client({'summary': '缺少协议字段'})
    elif failure == 'invalid_citation':
        proposal['rule_ids'] = ['invented-source']
        client = Client(proposal)
    elif failure == 'timeout':
        class TimeoutClient:
            def complete(self, *args):
                raise TimeoutError('provider detail must not appear')
        client = TimeoutClient()
    else:
        client = None
    pipeline.advisor = GroundedAdviceService(client)
    pipeline.report_generator = __import__('standard_knowledge_service_v2.reporting.grounded_generator',
        fromlist=['GroundedReportGenerator']).GroundedReportGenerator()
    pipeline.knowledge_graph, pipeline.audit_store = None, None
    response = AnalysisPipeline._respond(pipeline, request, 'answered', data, [{'quote': '旧的采用证据'}], [])
    assert response.status in ('partial', 'uncertain')
    assert response.evidence == []
    assert data['advice']['status'] == 'unavailable'
    assert data['advice']['reason_code'] == ('model_disabled' if failure == 'disabled' else
        'network_timeout' if failure == 'timeout' else 'invalid_model_output')
    assert data['advice']['answer_supported'] is False
    assert 'conclusion' not in data['answer'] and 'source_rule_id' not in data['answer']
    assert 'selected_rule' not in data
    assert data['validation']['status'] == 'uncertain'
    assert data['matching']['adopted'] is False
    assert data['report']['sections']['clauses'] == []
    assert '编号' in data['answer']['text'] and '版本' in data['answer']['text']
    assert 'provider detail' not in str(data)
