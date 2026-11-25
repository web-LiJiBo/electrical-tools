from copy import deepcopy


def test_business_state_is_not_presented_as_semantic_execution_permission():
    from standard_knowledge_service_v2.application.operation_review import semantic_review_inputs
    parameters = {'action_parameters': {'power_kw': 120}, 'device_facts': {'BESS': {'start_permission': 0}}}
    report = {'applied': [
        {'device_id': 'BESS', 'field': 'runtime_facts.start_permission', 'value': 0, 'unit': '',
         'sources': [{'origin': 'business_parameters'}]},
        {'device_id': 'INV', 'field': 'state.active_power_kw', 'value': 500, 'unit': 'kW',
         'sources': [{'origin': 'question'}]}]}
    original = deepcopy((parameters, report))
    business, inputs = semantic_review_inputs(parameters, report)
    assert business == {'action_parameters': {'power_kw': 120}}
    assert [row['device_id'] for row in inputs['applied']] == ['INV']
    assert inputs['state_validation'] == 'backend_per_operation'
    assert (parameters, report) == original


def test_conflicting_overall_verdict_is_reported_as_model_failure_not_approval():
    from standard_knowledge_service_v2.application.operation_review import validate_review
    op = dict(device_id='FAN', action='start', parameters={}, order=None, conditions=[])
    raw = dict(approved=False, items=[dict(index=0, matches_request=True, reason='一致',
        device_id='FAN', action='start', parameters={})], missing_requests=[],
        has_negation=False, has_conditions=False, has_order=False, reason='同意')
    result = validate_review(raw, [op], query='启动FAN')
    assert result['status'] == 'failed'
    assert result['reason_code'] == 'inconsistent_review'
    raw['items'][0]['matches_request'] = False
    assert validate_review(raw, [op], query='启动FAN')['status'] == 'blocked'
