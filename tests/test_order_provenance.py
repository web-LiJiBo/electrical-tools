"""Order provenance contracts, independent of model output quality."""
from copy import deepcopy
from standard_knowledge_service_v2.application.operation_review import validate_review

QUERY = '启动风机1，并启动风机2。请生成这两项指令。'

def packet(evidence=None):
    ops = [dict(device_id=f'FAN-{i}', action='start', parameters={}, order=i,
                conditions=[], negated=False, clarification='') for i in (1, 2)]
    if evidence is not None:
        for row in ops:
            row['order_evidence'] = evidence
    raw = dict(approved=True, items=[dict(index=i, matches_request=True, reason='一致',
        device_id=row['device_id'], action=row['action'], parameters={}) for i,row in enumerate(ops)],
        missing_requests=[], has_negation=False, has_conditions=False, has_order=True, reason='支持顺序')
    support = dict(order=True, operations=deepcopy(ops))
    return ops,raw,support

def test_missing_order_source_cannot_be_approved_by_server_support():
    ops,raw,support = packet()
    assert validate_review(raw, ops, support)['status'] == 'blocked'

def test_cited_dependency_still_requires_current_query():
    ops,raw,support = packet('前步反馈成功才执行下一步')
    assert validate_review(raw, ops, support)['reason_code'] == 'review_order_evidence'


def test_forged_dependency_cannot_pass_even_with_affirmative_review():
    ops,raw,support = packet('前步反馈成功才执行下一步')
    assert validate_review(raw, ops, support, QUERY)['reason_code'] == 'review_order_evidence'


def test_true_dependency_matches_current_query_and_is_not_erased():
    evidence = '前步反馈成功才执行下一步'
    ops,raw,support = packet(evidence)
    assert validate_review(raw, ops, support, QUERY + evidence)['status'] == 'approved'
    assert [row['order'] for row in ops] == [1, 2]


def test_independent_operations_need_no_new_field():
    ops,raw,_ = packet()
    for row in ops:
        row['order'] = None
    raw['has_order'] = False
    assert validate_review(raw, ops, query=QUERY)['status'] == 'approved'


def test_normalization_preserves_unproven_dependency_as_clarification():
    from types import SimpleNamespace
    from standard_knowledge_service_v2.application.semantic_resolution import normalize_plan
    from standard_knowledge_service_v2.decomposition.models import DecompositionResult
    ops,_,_ = packet()
    for row in ops:
        row.update(source_text=QUERY, target_text=row['device_id'], owner_id='')
    understanding = DecompositionResult(intent='instruction', operations=ops, queries=[])
    normalized = normalize_plan(understanding, QUERY, SimpleNamespace(devices={}))
    assert [row['order'] for row in normalized.operations] == [1, 2]
    assert all(row['clarification'] for row in normalized.operations)
    assert all(not row['clarification'] for row in understanding.operations)



def test_literal_listing_is_not_semantic_proof_when_review_rejects():
    ops,raw,support = packet(QUERY)
    raw.update(approved=False, has_order=False, reason='Only a list, no execution dependency')
    assert validate_review(raw, ops, support, QUERY)['status'] == 'blocked'


def test_valid_dependency_is_preserved_through_normalization_and_packet():
    from types import SimpleNamespace
    from standard_knowledge_service_v2.application.semantic_resolution import normalize_plan
    from standard_knowledge_service_v2.application.operation_review import review_packet
    from standard_knowledge_service_v2.decomposition.models import DecompositionResult
    evidence = 'Proceed only after successful feedback'
    query = QUERY + evidence
    ops,_,_ = packet(evidence)
    for row in ops:
        row.update(source_text=query, target_text=row['device_id'], owner_id='')
    normalized = normalize_plan(DecompositionResult(intent='instruction', operations=ops, queries=[]),
                                query, SimpleNamespace(devices={}))
    packet_copy = review_packet(query, normalized, {})
    assert all(row['order_evidence'] == evidence and not row['clarification']
               for row in packet_copy['operations'])
    packet_copy['operations'][0]['order_evidence'] = 'changed'
    assert normalized.operations[0]['order_evidence'] == evidence
