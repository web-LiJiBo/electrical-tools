from standard_knowledge_service_v2.application.analysis_pipeline import AnalysisPipeline
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.decomposition import RawTextFallback
from standard_knowledge_service_v2.retrieval_engine import JsonClauseRepository, LocalLunwenRetrievalAdapter


def pipeline():
    return AnalysisPipeline(LocalLunwenRetrievalAdapter(JsonClauseRepository([])),
                            decomposer=RawTextFallback())


def test_device_facts_answer_without_any_standard_or_action_binding():
    app = pipeline()
    result = app.analyze(AnalysisRequest('SIM-IEC-FAN-01当前状态和运行数据是什么？',
                                        parameters={'simulation_mode': True}))
    assert result.status == 'answered'
    assert result.data['devices'][0]['device_id'] == 'SIM-IEC-FAN-01'
    assert result.data['devices'][0]['state']['running'] is False
    assert result.data['candidate_instruction'] is None
    assert not result.evidence


def test_multiple_devices_can_be_compared_without_action_target():
    app = pipeline()
    result = app.analyze(AnalysisRequest('比较主变1和主变2的当前状态和温升数据',
                                        parameters={'simulation_mode': True}))
    assert result.status == 'answered'
    assert {d['device_id'] for d in result.data['devices']} == {'SIM-TRANSFORMER-01', 'SIM-TRANSFORMER-02'}
    assert '温升' in result.data['answer']['text']


def test_available_operations_are_answered_without_control_payload():
    app = pipeline()
    result = app.analyze(AnalysisRequest('SIM-IEC-FAN-01支持哪些操作？',
                                        parameters={'simulation_mode': True}))
    assert result.status == 'answered'
    assert {'start', 'stop'} <= {a['action'] for a in result.data['device_capabilities'][0]['actions']}
    assert result.data['candidate_instruction'] is None


def test_generic_device_query_does_not_consume_standard_questions():
    app = pipeline()
    result = app.analyze(AnalysisRequest('冷却风机启动有哪些标准要求？',
                                        parameters={'simulation_mode': True}))
    assert result.status == 'uncertain'
    assert not result.data.get('devices')


def test_unknown_device_is_explained_without_using_some_other_device():
    result = pipeline().analyze(AnalysisRequest('SIM-NOT-REGISTERED-01现在状态如何？',
                                               parameters={'simulation_mode': True}))
    assert result.status == 'uncertain'
    assert '未登记' in result.data['answer']['text']
    assert result.data.get('devices', []) == []


def test_natural_language_action_previews_without_executing_or_sources():
    app = pipeline()
    result = app.analyze(AnalysisRequest('启动主变1的冷却风机',
                                        parameters={'simulation_mode': True}))
    assert result.status == 'generated'
    assert result.data['simulation_preview']['status'] == 'generated'
    assert result.data['candidate_instruction']['payload']['requested_action'] == 'start'
    followup = app.analyze(AnalysisRequest('SIM-IEC-FAN-01现在状态如何？',
                                          parameters={'simulation_mode': True}))
    assert followup.data['devices'][0]['state']['running'] is False


def test_query_reads_executed_session_and_never_executes_again():
    app = pipeline()
    from standard_knowledge_service_v2.application.simulation_access import simulation_runtime
    runtime = simulation_runtime(app)
    session = runtime.create_session()
    sid = session['session_id']
    preview = runtime.preview(sid, 'SIM-IEC-FAN-01', 'start', {})
    runtime.execute(sid, preview['command_id'], preview['expected_version'])
    before = runtime.snapshot(sid)
    result = app.analyze(AnalysisRequest('SIM-IEC-FAN-01现在状态如何？',
        parameters={'simulation_mode': True, 'simulation_session_id': sid}))
    assert result.data['devices'][0]['state']['running'] is True
    assert runtime.snapshot(sid) == before


def test_temperature_assessment_can_retrieve_source_without_fixed_clause_hint():
    import json
    from pathlib import Path
    source = Path(__file__).resolve().parents[1] / 'datasets/lunwen/verified_json/json/11_clause2.json'
    unit = JsonClauseRepository._from_payload(source, json.loads(source.read_text(encoding='utf-8')))
    app = AnalysisPipeline(LocalLunwenRetrievalAdapter(JsonClauseRepository([unit])),
                           decomposer=RawTextFallback())
    app.simulation_session.service.devices['SIM-TRANSFORMER-01'].pop('assessment_clause_id')
    result = app.analyze(AnalysisRequest('主变1温升状态是否正常？', parameters={'simulation_mode': True}))
    assert result.status == 'answered'
    assert result.data['device_assessment']['status'] == 'normal'
    assert result.evidence
    assert result.data['retrieval_trace']['device_bound_clause_id'] is None


def test_standard_status_question_uses_requested_session_instead_of_legacy_seed():
    import json
    from pathlib import Path
    from standard_knowledge_service_v2.application.simulation_access import simulation_runtime
    source = Path(__file__).resolve().parents[1] / 'datasets/lunwen/verified_json/json/11_clause2.json'
    unit = JsonClauseRepository._from_payload(source, json.loads(source.read_text(encoding='utf-8')))
    app = AnalysisPipeline(LocalLunwenRetrievalAdapter(JsonClauseRepository([unit])), decomposer=RawTextFallback())
    runtime = simulation_runtime(app)
    # Legacy seed for transformer 1 is hot; this session explicitly starts normal.
    sid = runtime.create_session(condition='normal')['session_id']
    result = app.analyze(AnalysisRequest('SIM-TRANSFORMER-01状态是否正常，符合标准吗？',
        parameters={'simulation_mode': True, 'simulation_session_id': sid}))
    assert result.data['device_assessment']['status'] == 'normal'
    assert result.data['device_assessment']['runtime_facts']['winding_hotspot_rise_k'] == 50
    runtime.set_condition(sid, 'high_temperature')
    result = app.analyze(AnalysisRequest('SIM-TRANSFORMER-01状态是否正常，符合标准吗？',
        parameters={'simulation_mode': True, 'simulation_session_id': sid}))
    assert result.data['device_assessment']['status'] == 'abnormal'
    by_alias = app.analyze(AnalysisRequest('主变1状态是否正常，符合标准吗？',
        parameters={'simulation_mode': True, 'simulation_session_id': sid}))
    assert by_alias.data['device_assessment']['device_id'] == 'SIM-TRANSFORMER-01'
    assert by_alias.data['device_assessment']['status'] == 'abnormal'


def test_invalid_session_has_an_explanation_for_both_fact_and_standard_questions():
    app = pipeline()
    for query in ['主变1现在状态如何？', '主变1状态是否正常，符合标准吗？']:
        result = app.analyze(AnalysisRequest(query, parameters={
            'simulation_mode': True, 'simulation_session_id': 'missing'}))
        assert result.status == 'uncertain'
        assert '会话不存在' in result.data['answer']['text']
