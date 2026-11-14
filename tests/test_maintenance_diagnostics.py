"""Controlled semantic fixtures; these tests do not substitute real API acceptance."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from standard_knowledge_service_v2.application.semantic_operations import (
    catalog_context, operation_previews, plan_coverage,
)
from standard_knowledge_service_v2.application.simulation_query import answer_simulation_query
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.decomposition import RemoteModelConfig, RemoteModelDecomposer
from standard_knowledge_service_v2.decomposition.intent_classifier import IntentClassifier
from standard_knowledge_service_v2.decomposition.models import DecompositionResult
from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime
from standard_knowledge_service_v2.llm_decomposition import validate_decomposition


def diagnostic_plan(source, **changes):
    row = {'device_id': 'SIM-IEC-FAN-01', 'target_text': '主变1的冷却风机',
           'owner_id': 'SIM-TRANSFORMER-01', 'query_kind': 'device_readiness',
           'requested_action': 'start', 'source_text': source, 'clarification': ''}
    row.update(changes)
    return DecompositionResult(intent='search', entities=[{'name': '主变1'}],
        actions=['start'], operations=[], queries=[row],
        scenario={'query_kind': 'device_readiness'}, source='model_api', valid=True)


def world():
    runtime = SimulationRuntime(event_path=None)
    snapshot = runtime.create_session('all_devices')
    app = SimpleNamespace(simulation_runtime=runtime)
    devices = [{**deepcopy(runtime.catalog.devices[item['device_id']]), **item}
               for item in snapshot['devices']]
    params = {'simulation_mode': True, 'simulation_session_id': snapshot['session_id'],
              'simulation_scenario_id': 'all_devices'}
    return app, snapshot, devices, params


def test_readiness_is_a_diagnostic_not_an_operation_even_with_model_instruction():
    result = IntentClassifier().classify('请启动主变1的冷却风机',
        'instruction', ['start'], query_kind='device_readiness')
    assert result.intent == 'search'


def test_readiness_schema_accepts_requested_action_and_controls(monkeypatch):
    source = '判断主变1的冷却风机能否启动'
    plan = diagnostic_plan(source)
    payload = plan.to_dict()
    payload['request_controls'] = {'analysis_only': True, 'source_text': '不要生成控制指令'}
    output = validate_decomposition(payload)
    assert output.valid, output.errors
    client = RemoteModelDecomposer(RemoteModelConfig('https://example.test', 'fixture'))
    monkeypatch.setattr(client, 'complete', lambda *_: json.dumps(payload, ensure_ascii=False))
    result = client.decompose(source + '，不要生成控制指令')
    assert result.valid
    assert result.request_controls == payload['request_controls']
    assert result.queries[0]['requested_action'] == 'start'


@pytest.mark.parametrize('value', [{}, {'analysis_only': 'true', 'source_text': '只分析'},
    {'analysis_only': True, 'source_text': ''}, {'analysis_only': True, 'source_text': 42}])
def test_malformed_controls_are_rejected(value):
    payload = diagnostic_plan('主变1的冷却风机能否启动').to_dict()
    payload['request_controls'] = value
    output = validate_decomposition(payload)
    assert not output.valid
    assert any('request_controls' in error for error in output.errors)


def test_readiness_action_is_required():
    payload = diagnostic_plan('主变1的冷却风机能否启动').to_dict()
    payload.pop('request_controls', None)
    payload['queries'][0].pop('requested_action')
    assert not validate_decomposition(payload).valid


def test_legacy_controls_remain_unknown_instead_of_asserting_no_restriction(monkeypatch):
    payload = diagnostic_plan('查询主变1的冷却风机状态', query_kind='device_status').to_dict()
    payload.pop('request_controls', None)
    payload['scenario']['query_kind'] = 'device_status'
    client = RemoteModelDecomposer(RemoteModelConfig('https://example.test', 'fixture'))
    monkeypatch.setattr(client, 'complete', lambda *_: json.dumps(payload))
    result = client.decompose('查询主变1的冷却风机状态')
    assert result.request_controls is None


def test_controls_source_covers_only_actual_fragment_not_arbitrary_uncovered_words():
    app, snapshot, devices, _ = world()
    plan = diagnostic_plan('判断主变1的冷却风机能否启动')
    plan.request_controls = {'analysis_only': True, 'source_text': '不要生成控制指令'}
    query = '判断主变1的冷却风机能否启动，不要生成控制指令'
    profile = app.simulation_runtime.catalog.scenarios['all_devices']
    assert plan_coverage(plan, query, devices, profile) == ''
    from standard_knowledge_service_v2.application.semantic_operations import untraced_text
    extended = query + '，并导出全部检修记录'
    assert plan_coverage(plan, extended, devices, profile) == ''
    assert '导出全部检修记录' in untraced_text(plan, extended)
    plan.request_controls['source_text'] = '仅限分析'
    assert plan_coverage(plan, query, devices, profile)


@pytest.mark.parametrize('field,value,want', [
    ('device_fault', 0, 'ready'), ('device_fault', 1, 'blocked'),
    ('maintenance_lockout', 1, 'blocked'), ('power_available', None, 'unknown'),
])
def test_readiness_uses_individual_current_facts_without_preview(monkeypatch, field, value, want):
    app, snapshot, _, params = world()
    runtime = app.simulation_runtime
    entry = runtime._sessions[snapshot['session_id']].devices['SIM-IEC-FAN-01']
    entry['runtime_facts'][field] = value
    before = runtime.snapshot(snapshot['session_id'])
    source = '判断主变1的冷却风机能否启动'
    def forbidden(*_, **__):
        pytest.fail('A diagnostic query must never call preview')
    monkeypatch.setattr(runtime, 'preview', forbidden)
    result = answer_simulation_query(app, AnalysisRequest(source, parameters=params),
                                    decomposed=diagnostic_plan(source))
    assert result is not None
    status, data, _, _ = result
    assert status == 'answered'
    readiness = data['query_results'][0]['readiness']
    assert readiness['status'] == want
    by_field = {item.get('field'): item for item in readiness['checks']}
    assert {'start_permission', 'power_available', 'maintenance_lockout', 'device_fault'} <= set(by_field)
    assert by_field[field]['status'] == want
    assert by_field[field]['actual'] == value
    assert by_field['start_permission']['expression'] == 'start_permission == 1'
    assert by_field['maintenance_lockout']['expected'] == 0
    assert not data.get('simulation_preview') and not data.get('simulation_batch')
    assert data['candidate_instruction'] is None
    assert runtime.snapshot(snapshot['session_id']) == before
    assert runtime._sessions[snapshot['session_id']].commands == {}


def test_analysis_only_prevents_preview_even_when_model_keeps_explicit_operation():
    app, snapshot, devices, params = world()
    source = '启动主变1的冷却风机'
    row = {'device_id': 'SIM-IEC-FAN-01', 'target_text': '主变1的冷却风机',
           'owner_id': 'SIM-TRANSFORMER-01', 'action': 'start', 'parameters': {},
           'source_text': source, 'clarification': '', 'negated': False,
           'conditions': [], 'order': None}
    plan = DecompositionResult(operations=[row], queries=[], actions=['start'])
    plan.request_controls = {'analysis_only': True, 'source_text': '启动'}
    result = operation_previews(app, AnalysisRequest(source, parameters=params), snapshot,
        devices, app.simulation_runtime.catalog.scenarios['all_devices'], plan)
    assert result[0] == 'uncertain'
    assert not result[1].get('simulation_preview')
    assert app.simulation_runtime._sessions[snapshot['session_id']].commands == {}


def test_absent_live_fact_does_not_fall_back_to_catalog_seed():
    app, snapshot, _, params = world()
    runtime = app.simulation_runtime
    runtime._sessions[snapshot['session_id']].devices['SIM-IEC-FAN-01']['runtime_facts'].pop('power_available')
    assert runtime.catalog.devices['SIM-IEC-FAN-01']['runtime_facts']['power_available'] == 1
    query = '判断主变1的冷却风机能否启动'
    _, data, _, _ = answer_simulation_query(app, AnalysisRequest(query, parameters=params),
                                          decomposed=diagnostic_plan(query))
    readiness = data['query_results'][0]['readiness']
    assert readiness['status'] == 'unknown'
    check = next(item for item in readiness['checks'] if item['field'] == 'power_available')
    assert check['status'] == 'unknown' and check['actual'] is None


def test_readiness_uses_refreshed_action_template_with_shared_live_facts():
    app, snapshot, _, params = world()
    runtime = app.simulation_runtime
    catalog = deepcopy(runtime.catalog)
    catalog.devices['SIM-IEC-FAN-01']['actions']['start']['condition'] = 'start_permission == 0'
    runtime.refresh_catalog(catalog)
    query = '判断主变1的冷却风机能否启动'
    _, data, _, _ = answer_simulation_query(app, AnalysisRequest(query, parameters=params),
                                          decomposed=diagnostic_plan(query))
    result = data['query_results'][0]['readiness']
    assert result['status'] == 'blocked'
    check = next(item for item in result['checks'] if item['field'] == 'start_permission')
    assert check['actual'] == 1 and check['expected'] == 0


@pytest.mark.parametrize('running,label', [(False, '未运行'), (True, '运行中')])
def test_readiness_answer_states_live_running_state_and_readable_preconditions(running, label):
    app, snapshot, _, params = world()
    entry = app.simulation_runtime._sessions[snapshot['session_id']].devices['SIM-IEC-FAN-01']
    entry['state']['running'] = running
    entry['runtime_facts']['device_fault'] = 1
    query = '检查主变1的冷却风机启动条件和当前运行状态'
    _, data, _, _ = answer_simulation_query(app, AnalysisRequest(query, parameters=params),
                                          decomposed=diagnostic_plan(query))
    text = data['answer']['text']
    assert '运行状态：' + label in text
    for evidence in ('供电可用：当前1', '设备故障：当前1', '检修闭锁：当前0', '启动许可：当前1'):
        assert evidence in text
    assert next(item for item in data['query_results'][0]['readiness']['checks']
                if item['field'] == 'device_fault')['actual'] == 1
    assert not data.get('simulation_preview')


def test_readiness_answer_keeps_a_missing_state_unknown():
    app, snapshot, _, params = world()
    app.simulation_runtime._sessions[snapshot['session_id']].devices['SIM-IEC-FAN-01']['state'] = {}
    query = '检查主变1的冷却风机启动条件和当前运行状态'
    _, data, _, _ = answer_simulation_query(app, AnalysisRequest(query, parameters=params),
                                          decomposed=diagnostic_plan(query))
    assert '当前运行状态：待核验' in data['answer']['text']
    assert '未运行' not in data['answer']['text']


def test_tap_readiness_answer_includes_current_tap_position():
    app, snapshot, _, params = world()
    query = '检查主变1的调压装置升一档条件和当前档位'
    plan = diagnostic_plan(query, device_id='SIM-IEC-TAP-01',
        target_text='主变1的调压装置', requested_action='raise')
    _, data, _, _ = answer_simulation_query(app, AnalysisRequest(query, parameters=params), decomposed=plan)
    assert '当前档位：8' in data['answer']['text']


def test_undeclared_or_unsupported_conditions_stay_unknown():
    from standard_knowledge_service_v2.application.device_readiness import evaluate_device_readiness
    device = {'device_id': 'FIXTURE-ONLY', 'state': {}, 'runtime_facts': {'permission': 1},
              'actions': {'start': {'condition': 'permission == 1',
                  'constraints': [{'parameter': 'maintenance_lockout', 'operator': '==', 'value': 0}]}}}
    result = evaluate_device_readiness(device, 'start')
    assert result['status'] == 'unknown'
    assert any(item['status'] == 'unknown' for item in result['checks'])
    device['actions']['start'] = {'condition': '检修许可已完成'}
    assert evaluate_device_readiness(device, 'start')['status'] == 'unknown'
    assert evaluate_device_readiness(device, 'restart')['status'] == 'unknown'


def test_catalog_exposes_action_preconditions_without_current_fact_values():
    app, _, _, params = world()
    data = catalog_context(app, AnalysisRequest('只分析', parameters=params))
    fan = next(item for item in data['devices'] if item['device_id'] == 'SIM-IEC-FAN-01')
    assert fan['actions']['start']['condition'] == 'start_permission == 1'
    assert any(item['parameter'] == 'maintenance_lockout'
               for item in fan['actions']['start']['constraints'])
    assert 'runtime_facts' not in fan and 'state' not in fan


def test_restricted_row_validation_has_no_preview_side_effects():
    from standard_knowledge_service_v2.application import semantic_operations
    validator = getattr(semantic_operations, 'validate_operation_rows', None)
    assert validator is not None, 'Restricted plans need the same pure validation as simple previews'
    app, snapshot, devices, params = world()
    source = '仅在无故障时启动主变1的冷却风机'
    row = {'device_id': 'SIM-IEC-FAN-01', 'target_text': '主变1的冷却风机',
           'owner_id': 'SIM-TRANSFORMER-01', 'action': 'start', 'parameters': {},
           'source_text': source, 'clarification': '', 'negated': False,
           'conditions': ['device_fault == 0'], 'order': None}
    plan = DecompositionResult(operations=[row], queries=[], actions=['start'])
    rows, facts, error = validator(app, AnalysisRequest(source, parameters=params), snapshot,
        devices, app.simulation_runtime.catalog.scenarios['all_devices'], plan,
        allow_restrictions=True)
    assert not error
    assert rows[0]['device_id'] == 'SIM-IEC-FAN-01'
    assert rows[0]['semantic_operation']['conditions'] == ['device_fault == 0']
    assert app.simulation_runtime._sessions[snapshot['session_id']].commands == {}


def test_order_support_does_not_discard_undeclared_external_condition():
    from standard_knowledge_service_v2.application.semantic_operations import validate_operation_rows
    app, snapshot, devices, params = world()
    source = '经许可后先启动主变1的冷却风机'
    row = {'device_id': 'SIM-IEC-FAN-01', 'target_text': '主变1的冷却风机',
           'owner_id': 'SIM-TRANSFORMER-01', 'action': 'start', 'parameters': {},
           'source_text': source, 'clarification': '', 'negated': False,
           'conditions': [], 'order': 1}
    plan = DecompositionResult(operations=[row], queries=[], actions=['start'],
                              scenario={'operating_condition': '经许可后'})
    rows, _, reason = validate_operation_rows(app, AnalysisRequest(source, parameters=params),
        snapshot, devices, app.simulation_runtime.catalog.scenarios['all_devices'], plan,
        allow_restrictions=True)
    assert reason and not rows
    assert app.simulation_runtime._sessions[snapshot['session_id']].commands == {}


def test_global_condition_cannot_be_satisfied_by_another_devices_condition():
    from standard_knowledge_service_v2.application.semantic_operations import validate_operation_rows
    app, snapshot, devices, params = world()
    source = '无故障时启动主变1的冷却风机，同时启动主变2的冷却风机'
    first = {'device_id': 'SIM-IEC-FAN-01', 'target_text': '主变1的冷却风机',
           'owner_id': 'SIM-TRANSFORMER-01', 'action': 'start', 'parameters': {},
           'source_text': '无故障时启动主变1的冷却风机', 'clarification': '', 'negated': False,
           'conditions': ['device_fault == 0'], 'order': None}
    second = {**deepcopy(first), 'device_id': 'SIM-MB-FAN-01', 'owner_id': 'SIM-TRANSFORMER-02',
              'target_text': '主变2的冷却风机', 'source_text': '启动主变2的冷却风机', 'conditions': []}
    plan = DecompositionResult(operations=[first, second], queries=[], actions=['start'],
        constraints=[{'parameter': 'device_fault', 'operator': '==', 'value': 0,
                      'condition': '主变2的冷却风机'}])
    rows, _, reason = validate_operation_rows(app, AnalysisRequest(source, parameters=params),
        snapshot, devices, app.simulation_runtime.catalog.scenarios['all_devices'], plan,
        allow_restrictions=True)
    assert reason and not rows
