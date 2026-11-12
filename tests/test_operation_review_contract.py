"""The independent semantic reviewer can veto a plan, never repair it."""
import importlib
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass

import pytest


MODULE = 'standard_knowledge_service_v2.application.operation_review'


def reviewer():
    assert importlib.util.find_spec(MODULE) is not None, 'operation review module is missing'
    return importlib.import_module(MODULE)


def operations():
    return [
        {'device_id': 'SIM-FAN-01', 'action': 'start', 'parameters': {},
         'source_text': '启动风机1', 'target_text': '风机1', 'owner_id': '',
         'negated': False, 'conditions': [], 'order': None, 'clarification': ''},
        {'device_id': 'SIM-TAP-02', 'action': 'set_tap', 'parameters': {'tap_position': 4},
         'source_text': '将调压装置2设为4档', 'target_text': '调压装置2', 'owner_id': '',
         'negated': False, 'conditions': [], 'order': None, 'clarification': ''},
    ]


def approval(rows=None):
    rows = operations() if rows is None else rows
    return {'approved': True, 'items': [
        {'index': index, 'matches_request': True, 'reason': '与原文一致',
         'device_id': row['device_id'], 'action': row['action'],
         'parameters': deepcopy(row['parameters'])} for index, row in enumerate(rows)],
        'missing_requests': [], 'has_negation': False, 'has_conditions': False,
        'has_order': False, 'reason': '全部操作与原文一致'}


def packet(rows=None):
    return reviewer().review_packet('启动风机1，将调压装置2设为4档',
        {'operations': operations() if rows is None else rows,
         'queries': [{'query_kind': 'device_status', 'source_text': '查看油泵状态'}]},
        {'devices': [{'device_id': 'SIM-FAN-01', 'actions': {'start': {}}}],
         'ownership': []}, [{'role': 'user', 'content': '上次操作为停止'}])


@pytest.mark.parametrize('kind', ['dict', 'dataclass'])
def test_review_packet_preserves_full_original_data_without_shared_mutation(kind):
    @dataclass
    class Understanding:
        operations: list
        queries: list

    rows = operations()
    queries = [{'source_text': '查看风机状态', 'query_kind': 'device_status'}]
    understanding = {'operations': rows, 'queries': queries} if kind == 'dict' else Understanding(rows, queries)
    catalog = {'devices': [{'device_id': 'SIM-FAN-01', 'actions': {'start': {}}}], 'ownership': []}
    context = [{'role': 'user', 'content': '原始历史内容'}]
    query = '  启动风机1；将调压装置2设为4档。\n'
    actual = reviewer().review_packet(query, understanding, catalog, context)
    assert set(actual) == {'query', 'operations', 'queries', 'catalog', 'conversation_context'}
    assert actual == {'query': query, 'operations': rows, 'queries': queries,
                      'catalog': catalog, 'conversation_context': context}
    actual['operations'][1]['parameters']['tap_position'] = 9
    actual['queries'][0]['source_text'] = 'changed'
    actual['catalog']['devices'][0]['actions'].clear()
    actual['conversation_context'][0]['content'] = 'changed'
    assert rows[1]['parameters'] == {'tap_position': 4}
    assert queries[0]['source_text'] == '查看风机状态'
    assert catalog['devices'][0]['actions'] == {'start': {}}
    assert context[0]['content'] == '原始历史内容'


def test_review_packet_defaults_context_to_an_independent_empty_list():
    result = reviewer().review_packet('启动风机1', {'operations': operations(), 'queries': []}, {})
    assert result['conversation_context'] == []


@pytest.mark.parametrize('encoded', [False, True])
def test_complete_consistent_batch_can_be_approved_without_echoing_evidence(encoded):
    raw = approval()
    result = reviewer().validate_review(json.dumps(raw) if encoded else raw, operations())
    assert result['status'] == 'approved'
    assert result['reason_code'] and result['reason']
    assert result['items'] == raw['items']


def test_indexes_may_arrive_out_of_order_but_each_must_occur_once():
    raw = approval()
    raw['items'].reverse()
    assert reviewer().validate_review(raw, operations())['status'] == 'approved'


@pytest.mark.parametrize('change', ['missing_item', 'duplicate_index', 'extra_index',
    'boolean_index', 'float_index', 'string_index', 'negative_index'])
def test_omitted_duplicate_or_invalid_item_indexes_block_the_whole_batch(change):
    raw = approval()
    if change == 'missing_item':
        raw['items'].pop()
    elif change == 'duplicate_index':
        raw['items'][1]['index'] = 0
    elif change == 'extra_index':
        raw['items'].append(deepcopy(raw['items'][0]))
    else:
        raw['items'][0]['index'] = {'boolean_index': False, 'float_index': 0.0,
                                   'string_index': '0', 'negative_index': -1}[change]
    assert reviewer().validate_review(raw, operations())['status'] == 'blocked'


@pytest.mark.parametrize('field,value', [
    ('device_id', 'SIM-FAN-99'), ('action', 'stop'), ('parameters', {'extra': 1}),
    ('matches_request', False), ('matches_request', 1), ('reason', None),
])
def test_reviewer_cannot_replace_device_action_parameters_or_disagreement(field, value):
    raw = approval()
    raw['items'][0][field] = value
    original = operations()
    assert reviewer().validate_review(raw, original)['status'] == 'blocked'
    assert original == operations()


@pytest.mark.parametrize('original,proposed', [
    (0, False), (1, True), (False, 0), (True, 1),
    (4, '4'), (4, 5), (4, float('nan')), (4, float('inf')),
    ({'levels': [1, {'tap': 0}]}, {'levels': [True, {'tap': False}]}),
])
def test_parameter_comparison_does_not_equate_booleans_and_numbers(original, proposed):
    rows = operations()
    rows[1]['parameters']['tap_position'] = original
    raw = approval(rows)
    raw['items'][1]['parameters']['tap_position'] = proposed
    assert reviewer().validate_review(raw, rows)['status'] == 'blocked'


@pytest.mark.parametrize('field,value', [
    ('approved', False), ('approved', 1), ('approved', 'true'),
    ('has_negation', True), ('has_conditions', True), ('has_order', True),
    ('has_negation', 0), ('has_conditions', 'false'), ('has_order', None),
    ('missing_requests', ['还有停止油泵的诉求']), ('missing_requests', ''),
    ('missing_requests', [None]), ('reason', None), ('items', {}),
])
def test_rejected_missing_or_restricted_request_never_allows_preview(field, value):
    raw = approval()
    raw[field] = value
    assert reviewer().validate_review(raw, operations())['status'] == 'blocked'


@pytest.mark.parametrize('scope,field', [
    ('root', 'approved'), ('root', 'items'), ('root', 'missing_requests'),
    ('root', 'has_negation'), ('root', 'has_conditions'), ('root', 'has_order'),
    ('root', 'reason'), ('item', 'index'), ('item', 'matches_request'),
    ('item', 'reason'), ('item', 'device_id'), ('item', 'action'), ('item', 'parameters'),
])
def test_all_protocol_fields_are_required(scope, field):
    raw = approval()
    del (raw if scope == 'root' else raw['items'][0])[field]
    assert reviewer().validate_review(raw, operations())['status'] == 'blocked'


@pytest.mark.parametrize('raw', [None, [], '[]', '', '{"approved":true',
    '{"approved":true} trailing', 'prefix {"approved":true}', '```json\n{}\n```'])
def test_malformed_or_truncated_outputs_fail_closed(raw):
    result = reviewer().validate_review(raw, operations())
    assert result['status'] == 'blocked'
    assert result['reason_code'] == 'invalid_model_output'


def test_duplicate_json_keys_cannot_hide_a_rejection():
    raw = json.dumps(approval()).replace('"approved": true', '"approved": false, "approved": true', 1)
    assert reviewer().validate_review(raw, operations())['status'] == 'blocked'


def test_strict_json_parser_supports_the_combined_review_and_advice_envelope():
    raw = {'operation_review': approval(), 'advice': {'summary': '条款说明'}}
    assert reviewer().parse_review_json(json.dumps(raw)) == raw


@pytest.mark.parametrize('suffix', [' trailing', '\n{}'])
def test_strict_json_parser_does_not_discard_content_after_the_first_object(suffix):
    with pytest.raises(ValueError):
        reviewer().parse_review_json(json.dumps({'operation_review': approval()}) + suffix)


@pytest.mark.parametrize('raw', [
    '{"operation_review":{"approved":false,"approved":true}}',
    '{"operation_review":{},"operation_review":{}}',
    '{"advice":{"value":NaN}}', '[]', '{} trailing',
])
def test_strict_json_parser_rejects_duplicate_nested_keys_and_non_json_values(raw):
    with pytest.raises(ValueError):
        reviewer().parse_review_json(raw)


@pytest.mark.parametrize('rows', [[], None, {}, [None], [{'device_id': 'SIM-FAN-01'}]])
def test_empty_or_invalid_input_plan_cannot_be_vacuously_approved(rows):
    raw = approval([])
    result = reviewer().validate_review(raw, rows)
    assert result['status'] == 'blocked'


@pytest.mark.parametrize('field,value', [
    ('negated', True), ('conditions', ['获得许可后']), ('order', 1),
    ('clarification', '无法确认目标设备'),
])
def test_reviewer_cannot_erase_restrictions_already_present_in_original_plan(field, value):
    rows = operations()
    rows[0][field] = value
    assert reviewer().validate_review(approval(rows), rows)['status'] == 'blocked'


def test_review_operations_makes_one_batch_call_with_original_request_and_catalog():
    calls = []
    class Client:
        def complete(self, system, user):
            calls.append((system, json.loads(user)))
            return json.dumps(approval())
    original = packet()
    result = reviewer().review_operations(Client(), original)
    assert result['status'] == 'approved'
    assert len(calls) == 1
    assert 'OPERATION_PLAN_REVIEW' in calls[0][0]
    assert calls[0][1] == original
    assert len(calls[0][1]['operations']) == 2


@pytest.mark.parametrize('exc,code', [
    (RuntimeError('provider leaked Bearer sk-secret-value'), 'model_error'),
    (TimeoutError('secret from provider response'), 'network_timeout'),
    (PermissionError('secret endpoint'), 'network_permission_denied'),
])
def test_api_errors_are_secret_free_failures_without_retry(exc, code):
    class Client:
        calls = 0
        def complete(self, *_):
            self.calls += 1
            raise exc
    client = Client()
    result = reviewer().review_operations(client, packet())
    assert result['status'] == 'failed'
    assert result['reason_code'] == code
    assert client.calls == 1
    assert not any(secret in json.dumps(result) for secret in ['sk-secret', 'secret', 'Bearer', 'provider'])


def test_unavailable_client_fails_without_calling_or_approving():
    result = reviewer().review_operations(None, packet())
    assert result['status'] == 'failed'
    assert result['reason_code'] == 'model_disabled'


def test_invalid_model_json_is_a_failed_review_and_is_not_retried():
    class Client:
        calls = 0
        def complete(self, *_):
            self.calls += 1
            return '{"approved":true,"items":['
    client = Client()
    result = reviewer().review_operations(client, packet())
    assert result['status'] == 'failed'
    assert result['reason_code'] == 'invalid_model_output'
    assert client.calls == 1


def test_valid_semantic_rejection_stays_blocked_and_does_not_repair_input_plan():
    class Client:
        def complete(self, *_):
            raw = approval()
            raw['items'][0].update(matches_request=False, reason='原文要求停止，而清单为启动')
            raw['approved'] = False
            return json.dumps(raw)
    original = packet()
    before = deepcopy(original)
    result = reviewer().review_operations(Client(), original)
    assert result['status'] == 'blocked'
    assert original == before


def test_review_results_are_not_shared_across_concurrent_requests():
    class Client:
        def complete(self, _system, user):
            rows = json.loads(user)['operations']
            raw = approval(rows)
            if rows[0]['action'] == 'stop':
                raw.update(approved=False, reason='不符合原文')
            return json.dumps(raw)
    first = packet([operations()[0]])
    second = deepcopy(first)
    second['operations'][0]['action'] = 'stop'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda p: reviewer().review_operations(Client(), p), [first, second]))
    assert [result['status'] for result in results] == ['approved', 'blocked']
    results[0]['items'][0]['parameters']['new'] = 1
    assert results[1]['items'][0]['parameters'] == {}
