from copy import deepcopy


def adopted_answer():
    return {'answer': {'text': '不支持当前问题', 'conclusion': '电缆绝缘合格即可合闸', 'source_rule_id': 'r1'},
            'selected_rule': {'rule_id': 'r1'}, 'semantic': {'action': 'close'},
            'three_layer_semantics': {'constraint_rules': ['cable']}, 'if_then': 'close',
            'swrl': ['close'], 'ilr': {'action': 'close'},
            'knowledge_graph_evidence': {'rule_id': 'r1'},
            'candidate_instruction': {'payload': {'close': True}},
            'simulation_preview': {'command_id': 'old'}, 'instruction_generation': {'status': 'generated'},
            'matching': {'rules': [{'rule_id': 'r1', 'content': '检索候选原文'}]},
            'validation': {'status': 'answered', 'dispatch_allowed': True, 'layers': {'source_quote': 'pass'}},
            'report': {'summary': 'answered', 'sections': {'clauses': [{'quote': '电缆绝缘合格即可合闸'}]}}}


def test_invalidation_removes_adopted_conclusions_and_report_authority():
    from standard_knowledge_service_v2.application.answer_integrity import invalidate_answer
    data = adopted_answer()
    invalidate_answer(data, '来源不适用于变压器检修')
    assert '来源不适用于变压器检修' in data['answer']['text']
    assert 'conclusion' not in data['answer'] and 'source_rule_id' not in data['answer']
    for field in ('selected_rule', 'semantic', 'three_layer_semantics', 'if_then', 'swrl', 'ilr',
                  'knowledge_graph_evidence', 'simulation_preview', 'instruction_generation'):
        assert field not in data
    assert data['candidate_instruction'] is None
    assert data['validation']['status'] == 'uncertain'
    assert data['validation']['dispatch_allowed'] is False
    assert data['validation']['adopted'] is False
    assert data['matching']['rules'][0]['content'] == '检索候选原文'
    assert data['matching']['adopted'] is False
    assert 'answered' not in data['report']['summary']
    assert data['report']['sections']['clauses'] == []


def test_invalidation_recurses_only_into_unsupported_knowledge_subresults():
    from standard_knowledge_service_v2.application.answer_integrity import invalidate_answer
    child = adopted_answer()
    child['advice'] = {'answer_supported': False, 'unable_reason': '子问题来源无关'}
    factual = {'query_kind': 'device_status', 'status': 'answered',
               'data': {'simulation_factual': True, 'answer': {'text': '风机正在运行'}}, 'evidence': []}
    successful = {'query_kind': 'knowledge', 'status': 'answered', 'data': {'answer': {'text': '真实有效的引用'}}}
    data = adopted_answer()
    data['query_results'] = [factual, successful, {'query_kind': 'knowledge', 'status': 'answered', 'data': child,
                                                 'evidence': [{'quote': '无关'}]}]
    original = deepcopy(data['query_results'][:2])
    invalidate_answer(data, '来源不足')
    assert data['query_results'][:2] == original
    assert data['query_results'][2]['status'] == 'uncertain'
    assert data['query_results'][2]['evidence'] == []
    assert 'conclusion' not in child['answer']
    before = deepcopy(data)
    invalidate_answer(data, '来源不足')
    assert data == before


def test_invalidation_withdraws_derived_device_assessment_but_keeps_measured_facts():
    from standard_knowledge_service_v2.application.answer_integrity import invalidate_answer
    data = adopted_answer()
    data.update(real_clause_evidence={'quote': '误用的限值'},
        device_assessment={'device_id': 'TEST-DEVICE', 'status': 'normal', 'rule': '误用的限值',
            'runtime_facts': {'temperature': 25}, 'checks': [{'passed': True}],
            'current_snapshot_assessment': {'status': 'normal'},
            'hypothetical_assessment': {'status': 'normal'}})
    invalidate_answer(data, '条款不适用')
    assert 'real_clause_evidence' not in data
    assert data['device_assessment']['status'] == 'uncertain'
    assert data['device_assessment']['runtime_facts'] == {'temperature': 25}
    for field in ('checks', 'current_snapshot_assessment', 'hypothetical_assessment'):
        assert field not in data['device_assessment']


def test_final_invalidation_replaces_stale_answer_text_with_refusal_analysis():
    from standard_knowledge_service_v2.application.answer_integrity import invalidate_answer
    data = adopted_answer()
    data['answer']['text'] = '根据电缆标准，变压器试验全部合格，可以合闸'
    data['advice'] = {'answer_supported': False, 'summary': '所检索来源是电缆条文',
                      'unable_reason': '不能用于变压器检修', 'suggestions': []}
    invalidate_answer(data, '不能用于变压器检修')
    assert '可以合闸' not in data['answer']['text']
    assert '所检索来源是电缆条文' in data['answer']['text']
    assert '不能用于变压器检修' in data['answer']['text']
