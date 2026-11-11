import json
import re

import pytest

from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.decomposition.model_errors import ModelCallError
from test_api_first_analysis import app_for


def mixed_app(monkeypatch, *, fail_child=False, target_conditions=False, extra_state=False):
    app, params, before, _ = app_for(monkeypatch)
    calls = []
    def complete(system, user):
        q = user.split('用户问题：', 1)[1].split('\n请严格')[0]
        calls.append(q)
        if fail_child and len(calls) > 1:
            raise ModelCallError('network_timeout')
        actions = []
        for word, action in [('启动', 'start'), ('停止', 'stop'), ('有功', 'adjust_active_power'), ('无功', 'adjust_reactive_power'), ('电压', 'regulate_voltage')]:
            if word in q:
                actions.append(action)
        constraints = [{'parameter':m[1], 'operator':'=', 'value':m[2], 'unit':m[3], 'condition':''}
            for m in re.finditer(r'(有功功率|无功功率|输出电压)(?:设为|调整为)([\d.]+)(kW|MW|kvar|V)', q)]
        if target_conditions and len(calls) == 1:
            for c, target in zip(constraints, ['SIM-IEC-INVERTER-01', 'SIM-MB-INVERTER-01']):
                c['condition'] = target + ('获准后' if target_conditions == 'qualified' else '')
        if extra_state and len(calls) == 1:
            constraints.append({'parameter':'绕组热点温升','operator':'=','value':80,'unit':'K','condition':''})
        return json.dumps({'intent':'instruction', 'entities':[{'name':'主变1','type':'设备'}],
            'actions':actions, 'constraints':constraints, 'standard_refs':[],
            'scenario':{'query_kind':'operation','operating_condition':''},
            'keywords':['模拟设备'], 'confidence':0.95}, ensure_ascii=False)
    monkeypatch.setattr(app.decomposer, 'complete', complete)
    return app, params, before, calls


def test_distinct_devices_actions_are_not_cross_applied(monkeypatch):
    app, params, before, calls = mixed_app(monkeypatch)
    response = app.analyze(AnalysisRequest('启动主变1的冷却风机，同时停止主变2的油泵', parameters=params))
    assert response.status == 'generated'
    rows = response.data['simulation_batch']['items']
    assert [(r['device_id'], r['action']) for r in rows] == [
        ('SIM-IEC-FAN-01', 'start'), ('SIM-MB-PUMP-01', 'stop')]
    assert all(r['preview']['status'] == 'generated' for r in rows)
    assert len(calls) == 3
    assert app.simulation_runtime.snapshot(before['session_id']) == before


def test_same_device_independent_values_and_units_stay_per_instruction(monkeypatch):
    app, params, before, _ = mixed_app(monkeypatch)
    params['simulation_scenario_id'] = 'renewable_grid_integration'
    response = app.analyze(AnalysisRequest(
        '将SIM-IEC-INVERTER-01的有功功率设为0.12MW，同时将其无功功率设为30kvar', parameters=params))
    assert response.status == 'generated'
    rows = response.data['simulation_batch']['items']
    assert [r['device_id'] for r in rows] == ['SIM-IEC-INVERTER-01'] * 2
    assert [r['parameters'] for r in rows] == [{'power_kw':120}, {'reactive_power_kvar':30}]
    assert len({r['preview']['command_id'] for r in rows}) == 2
    assert app.simulation_runtime.snapshot(before['session_id']) == before


def test_two_devices_two_distinct_numeric_targets_do_not_conflict_globally(monkeypatch):
    app, params, _, _ = mixed_app(monkeypatch)
    params['simulation_scenario_id'] = 'renewable_grid_integration'
    data = app.analyze(AnalysisRequest('将SIM-IEC-INVERTER-01的有功功率设为120kW，同时将SIM-MB-INVERTER-01的有功功率设为80kW', parameters=params)).data
    assert [r['parameters']['power_kw'] for r in data['simulation_batch']['items']] == [120, 80]


def test_global_target_names_are_not_execution_conditions(monkeypatch):
    app, params, _, _ = mixed_app(monkeypatch, target_conditions=True)
    params['simulation_scenario_id'] = 'renewable_grid_integration'
    data = app.analyze(AnalysisRequest('将SIM-IEC-INVERTER-01的有功功率设为120kW，同时将SIM-MB-INVERTER-01的有功功率设为80kW', parameters=params)).data
    assert [r['parameters']['power_kw'] for r in data['simulation_batch']['items']] == [120,80]


def test_target_name_with_approval_condition_is_not_exempted(monkeypatch):
    app, params, _, _ = mixed_app(monkeypatch, target_conditions='qualified')
    params['simulation_scenario_id'] = 'renewable_grid_integration'
    response = app.analyze(AnalysisRequest('将SIM-IEC-INVERTER-01的有功功率设为120kW，同时将SIM-MB-INVERTER-01的有功功率设为80kW', parameters=params))
    assert not response.data.get('simulation_batch')


def test_global_state_constraint_is_not_dropped_as_a_target_assignment(monkeypatch):
    app, params, _, _ = mixed_app(monkeypatch, extra_state=True)
    response = app.analyze(AnalysisRequest('启动主变1的冷却风机，同时停止主变2的油泵', parameters=params))
    assert not response.data.get('simulation_batch')


@pytest.mark.parametrize('query', [
    '先启动主变1的冷却风机，再停止主变2的油泵',
    '启动主变1的冷却风机，同时禁止停止主变2的油泵',
    '如果温升过高，启动主变1的冷却风机，同时停止主变2的油泵',
    '启动主变1的冷却风机，同时停止主变99的油泵',
    '启动主变1的冷却风机，同时停止神秘设备',
    '启动主变1的冷却风机，同时停止主变1的冷却风机',
    '将SIM-IEC-INVERTER-01的有功功率设为120kW，同时将其有功功率设为80kW',
    '启动冷却风机1和冷却风机2，同时将其输出电压设为400V',
])
def test_restrictions_unknown_conflicting_or_ambiguous_targets_do_not_produce_commands(monkeypatch, query):
    app, params, before, _ = mixed_app(monkeypatch)
    params['simulation_scenario_id'] = 'all_devices'
    response = app.analyze(AnalysisRequest(query, parameters=params))
    assert not response.data.get('simulation_batch')
    assert not (response.data.get('candidate_instruction') or {}).get('payload')
    assert app.simulation_runtime.snapshot(before['session_id']) == before


def test_child_model_failure_does_not_return_a_partial_understood_batch(monkeypatch):
    app, params, _, _ = mixed_app(monkeypatch, fail_child=True)
    response = app.analyze(AnalysisRequest('启动主变1的冷却风机，同时停止主变2的油泵', parameters=params))
    assert not response.data.get('simulation_batch')
    assert response.data['model_understanding']['status'] == 'failed'


def test_valid_and_interlock_blocked_mixed_rows_both_visible(monkeypatch):
    app, params, before, _ = mixed_app(monkeypatch)
    app.simulation_runtime._sessions[before['session_id']].devices['SIM-MB-PUMP-01']['runtime_facts']['maintenance_lockout'] = 1
    data = app.analyze(AnalysisRequest('启动主变1的冷却风机，同时停止主变2的油泵', parameters=params)).data
    assert data['simulation_batch']['status'] == 'partial'
    assert [r['preview']['status'] for r in data['simulation_batch']['items']] == ['generated','blocked']


def test_same_device_actions_execute_independently_with_fresh_versions(monkeypatch):
    app, params, before, _ = mixed_app(monkeypatch)
    params['simulation_scenario_id'] = 'renewable_grid_integration'
    data = app.analyze(AnalysisRequest('将SIM-IEC-INVERTER-01的有功功率设为120kW，同时将其无功功率设为30kvar', parameters=params)).data
    runtime, sid = app.simulation_runtime, before['session_id']
    first, second = data['simulation_batch']['items']
    p = first['preview']
    assert runtime.execute(sid, p['command_id'], p['expected_version'])['status'] == 'succeeded'
    state = next(d['state'] for d in runtime.snapshot(sid)['devices'] if d['device_id'] == first['device_id'])
    assert state['active_power_kw'] == 120
    p = runtime.preview(sid, second['device_id'], second['action'], second['parameters'])
    assert p['expected_version'] == 1
    assert runtime.execute(sid, p['command_id'], p['expected_version'])['status'] == 'succeeded'
    state = next(d['state'] for d in runtime.snapshot(sid)['devices'] if d['device_id'] == first['device_id'])
    assert (state['active_power_kw'], state['reactive_power_kvar']) == (120, 30)


def test_blocked_numeric_row_keeps_its_requested_value_and_unit(monkeypatch):
    app, params, _, _ = mixed_app(monkeypatch)
    params['simulation_scenario_id'] = 'renewable_grid_integration'
    data = app.analyze(AnalysisRequest('将SIM-IEC-INVERTER-01的有功功率设为1500kW，同时将其无功功率设为30kvar', parameters=params)).data
    rows = data['simulation_batch']['items']
    assert [r['preview']['status'] for r in rows] == ['blocked', 'generated']
    assert rows[0]['parameters'] == {'power_kw':1500}
    assert rows[0]['parameter_unit'] == 'kW'
