from standard_knowledge_service_v2.domain import ClauseKnowledgeUnit, Entity, Rule
from standard_knowledge_service_v2.retrieval import LunwenMatchingInput
from standard_knowledge_service_v2.retrieval_engine import JsonClauseRepository, LocalLunwenRetrievalAdapter


def unit(identifier, subject, text, *, condition='', entities=()):
    # Deliberately synthetic identities, never added to a production dataset.
    return ClauseKnowledgeUnit('TEST-' + identifier, 'TEST-NOT-A-STANDARD', 'TEST', '', text,
        [Entity(identifier + str(i), name, '设备') for i, name in enumerate((subject, *entities))],
        [Rule(identifier, subject, 'inspect', condition, content=text)],
        metadata={'source': {'source_text': text}})


def retrieve(units, query, **parsed):
    adapter = LocalLunwenRetrievalAdapter(JsonClauseRepository(units))
    result = adapter.match(LunwenMatchingInput(query, {'intent': 'search', **parsed}))
    return result, adapter.last_trace


def test_transformer_insulation_query_excludes_cable_test_and_unrelated_grounding():
    result, trace = retrieve([
        unit('cable', '电缆', '电缆绝缘电阻试验合格后可恢复送电', entities=('变压器',)),
        unit('ground', '变压器', '变压器中性点接地应增加绝缘防护'),
        unit('transformer', '变压器', '应提供变压器绝缘电阻实测值')],
        '变压器检修后绝缘电阻试验如何判断合格？',
        entities=[{'name': '变压器', 'type': '设备'}], keywords=['绝缘电阻'])
    assert [hit.rule.rule_id for hit in result.rules] == ['transformer']
    assert trace.parameters['applicability_rejections']['device_mismatch'] == 1
    assert trace.parameters['applicability_rejections']['topic_mismatch'] == 1


def test_maintenance_query_does_not_use_factory_test_or_tap_changer_oil_as_transformer_basis():
    result, _ = retrieve([
        unit('factory', '三相变压器', '变压器绕组直流电阻试验要求', condition='变压器出厂前'),
        unit('tap', '油浸式真空有载分接开关', '独立油室绝缘油试验周期与变压器本体一致'),
        unit('maintenance', '变压器', '变压器检修后应检查绝缘电阻实测值')],
        '变压器检修后恢复送电前，直流电阻、绝缘电阻和绝缘油试验如何判定？',
        entities=[{'name': '变压器', 'type': '设备'}], keywords=['直流电阻', '绝缘电阻', '绝缘油试验'])
    assert [hit.rule.rule_id for hit in result.rules] == ['maintenance']


def test_general_scope_and_cable_questions_remain_available():
    cable = unit('cable', '电缆', '电缆绝缘电阻试验应测量实测值')
    result, _ = retrieve([cable], '电缆绝缘电阻试验如何检查？', entities=[{'name': '电缆', 'type': '设备'}])
    assert result.rules[0].rule.rule_id == 'cable'
    result, _ = retrieve([cable], '绝缘电阻试验要求是什么？')
    assert result.rules[0].rule.rule_id == 'cable'


def test_topic_coverage_distinguishes_absence_mismatch_and_recall_limit():
    units = [unit('ir', '变压器', '变压器绝缘电阻试验实测值'),
             unit('dc', '变压器', '变压器直流电阻试验实测值')]
    adapter = LocalLunwenRetrievalAdapter(JsonClauseRepository(units))
    adapter.match(LunwenMatchingInput('变压器绝缘电阻、直流电阻和绝缘油试验要求',
        {'intent': 'search', 'entities': [{'name': '变压器', 'type': '设备'}]}, top_k_rules=1))
    coverage = adapter.last_trace.parameters['topic_coverage']
    assert coverage['insulating_oil']['status'] == 'missing_from_repository'
    assert sorted(item['status'] for key, item in coverage.items() if key != 'insulating_oil') == ['not_recalled', 'recalled']
    adapter = LocalLunwenRetrievalAdapter(JsonClauseRepository([unit('cable', '电缆', '电缆绝缘电阻试验')]))
    adapter.match(LunwenMatchingInput('变压器绝缘电阻试验要求', {'intent': 'search'}))
    assert adapter.last_trace.parameters['topic_coverage']['insulation_resistance']['status'] == 'no_applicable_candidates'


def test_canonical_english_device_context_filters_cable_and_unknown_equipment():
    result, trace = retrieve([
        unit('cable', '电缆', '电缆绝缘电阻实测值'),
        unit('unknown', '接线端子', '接线端子绝缘电阻试验要求'),
        unit('transformer', '变压器', '变压器绝缘电阻实测值')],
        '检修后绝缘电阻试验如何判定？', context_device_type='transformer',
        entities=[{'name': '电力变压器', 'type': 'transformer'}])
    assert [hit.rule.rule_id for hit in result.rules] == ['transformer']
