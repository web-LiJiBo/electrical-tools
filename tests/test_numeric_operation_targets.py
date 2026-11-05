"""Numeric operation targets reach the real template without weakening guards."""
import pytest

from standard_knowledge_service_v2.contracts import AnalysisRequest
from test_api_first_analysis import app_for


@pytest.mark.parametrize('device,action,phrase,field,parameter,value,unit,expected,extra', [
    ('SIM-IEC-INVERTER-01', 'adjust_active_power', '有功功率设为120kW', 'power_kw', '有功功率', 120, 'kW', 120, {}),
    ('SIM-MB-INVERTER-01', 'adjust_active_power', '有功功率设为120kW', 'power_kw', '有功功率', 120, 'kW', 120, {'power_kw': 120}),
    ('SIM-IEC-INVERTER-01', 'adjust_active_power', '有功功率设为0.12MW', 'power_kw', 'power_kw', 120000, 'W', 120, {}),
    ('SIM-MB-INVERTER-01', 'adjust_active_power', '有功功率设为120千瓦', 'power_kw', '目标有功功率', 120000, 'W', 120, {}),
    ('SIM-IEC-INVERTER-01', 'regulate_voltage', '输出电压设为400V', 'voltage_v', '输出电压', 400, 'V', 400, {}),
    ('SIM-MB-INVERTER-01', 'regulate_voltage', '输出电压设为0.4kV', 'voltage_v', '目标电压', 400, 'V', 400, {'voltage_v': 400}),
    ('SIM-IEC-INVERTER-01', 'adjust_reactive_power', '无功功率设为30kvar', 'reactive_power_kvar', '无功功率', 30000, 'var', 30, {}),
    ('SIM-IEC-BESS-01', 'limit_power', '功率上限设为100kW', 'power_limit_kw', '功率上限', 100000, 'W', 100, {}),
    ('SIM-MB-BESS-01', 'adjust_active_power', '有功功率设为120.5kW', 'power_kw', '目标功率', 120500, 'W', 120.5, {}),
])
def test_target_assignment_generates_template_value(monkeypatch, device, action, phrase, field,
                                                    parameter, value, unit, expected, extra):
    app, parameters, before, _ = app_for(monkeypatch, intent='instruction', actions=[action],
        constraints=[{'parameter': parameter, 'operator': '=', 'value': value, 'unit': unit, 'condition': ''}])
    parameters.update(simulation_scenario_id='renewable_grid_integration', action_parameters=extra)
    response = app.analyze(AnalysisRequest(f'将{device}的{phrase}', parameters=parameters))
    assert response.status == 'generated', response.data.get('answer')
    payload = response.data['candidate_instruction']['payload']
    assert payload['engineering_value'] == expected
    assert response.data['simulation_preview']['simulation_execution_allowed']
    assert app.simulation_runtime.snapshot(before['session_id']) == before


def test_text_target_fills_parameter_even_when_model_omits_constraint(monkeypatch):
    app, parameters, _, _ = app_for(monkeypatch, intent='instruction', actions=['adjust_active_power'])
    parameters['simulation_scenario_id'] = 'renewable_grid_integration'
    response = app.analyze(AnalysisRequest('将SIM-MB-INVERTER-01的有功功率设为120kW', parameters=parameters))
    assert response.status == 'generated'
    assert response.data['candidate_instruction']['payload']['engineering_value'] == 120


@pytest.mark.parametrize('text,constraints', [
    ('1,200kW', []),
    ('−120kW', [{'parameter': '有功功率', 'operator': '=', 'value': 120, 'unit': 'kW'}]),
    ('120kW/s', [{'parameter': '有功功率', 'operator': '=', 'value': 120, 'unit': 'kW'}]),
])
def test_complete_numeric_token_cannot_be_truncated(monkeypatch, text, constraints):
    app, parameters, _, _ = app_for(monkeypatch, intent='instruction', actions=['adjust_active_power'], constraints=constraints)
    parameters['simulation_scenario_id'] = 'renewable_grid_integration'
    response = app.analyze(AnalysisRequest(f'将SIM-IEC-INVERTER-01的有功功率设为{text}', parameters=parameters))
    assert response.status != 'generated'
    assert not (response.data.get('candidate_instruction') or {}).get('payload')


def test_milliwatt_is_not_interpreted_as_megawatt(monkeypatch):
    app, parameters, _, _ = app_for(monkeypatch, intent='instruction', actions=['adjust_active_power'])
    parameters['simulation_scenario_id'] = 'renewable_grid_integration'
    response = app.analyze(AnalysisRequest('将SIM-IEC-INVERTER-01的有功功率设为0.12mW', parameters=parameters))
    assert response.status == 'generated'
    assert response.data['candidate_instruction']['payload']['engineering_value'] == 0.00000012


def test_target_aliases_do_not_relax_other_preview_entry_points():
    from standard_knowledge_service_v2.application.action_request import action_request_restriction
    reason = action_request_restriction('将逆变器有功功率设为120kW',
        {'constraints': [{'parameter': '有功功率', 'operator': '=', 'value': 120, 'unit': 'kW'}]},
        instruction_request=True, action_parameter='power_kw')
    assert reason, 'Only the direct branch with target reconciliation may opt into extra target aliases'


def test_advice_cannot_use_new_target_alias_to_override_user_value():
    from test_grounded_advice import setup, Client
    from standard_knowledge_service_v2.application.grounded_advice import GroundedAdviceService
    from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime
    app, data, proposal, request = setup(action='adjust_active_power')
    app.simulation_runtime = SimulationRuntime(event_path=None)
    snapshot = app.simulation_runtime.create_session('all_devices')
    request.query = '依据标准，将SIM-IEC-INVERTER-01的有功功率设为120kW'
    request.parameters.update(simulation_session_id=snapshot['session_id'],
                              action_parameters={'power_kw': 120})
    data['decomposition'] = {'constraints': [{'parameter': '有功功率', 'operator': '=', 'value': 120, 'unit': 'kW'}]}
    proposal['instruction'] = {'text': '将模拟逆变器的有功功率调整为130kW',
        'device_id': 'SIM-IEC-INVERTER-01', 'action': 'adjust_active_power',
        'parameters': {'power_kw': 130}, 'rule_ids': ['r1']}
    GroundedAdviceService(Client(proposal)).enrich(app, request, data)
    assert not (data.get('candidate_instruction') or {}).get('payload')


@pytest.mark.parametrize('query,constraint,extra', [
    ('将SIM-IEC-INVERTER-01的有功功率设为120kW', {'parameter': '有功功率', 'operator': '=', 'value': 120, 'unit': 'kW'}, {'power_kw': 130}),
    ('将SIM-IEC-INVERTER-01的有功功率设为120kW', {'parameter': '有功功率', 'operator': '=', 'value': 130, 'unit': 'kW'}, {}),
    ('将SIM-IEC-INVERTER-01的有功功率设为1500kW', {'parameter': '有功功率', 'operator': '=', 'value': 1500, 'unit': 'kW'}, {}),
    ('将SIM-IEC-INVERTER-01的有功功率设为120V', {'parameter': '有功功率', 'operator': '=', 'value': 120, 'unit': 'V'}, {'power_kw': 120}),
    ('将SIM-IEC-INVERTER-01的有功功率设为120kW', {'parameter': '当前有功功率', 'operator': '=', 'value': 120, 'unit': 'kW'}, {'power_kw': 120}),
    ('将SIM-IEC-INVERTER-01的有功功率设为120kW', {'parameter': '有功功率', 'operator': '>', 'value': 120, 'unit': 'kW'}, {'power_kw': 120}),
    ('如果并网允许，将SIM-IEC-INVERTER-01的有功功率设为120kW', {'parameter': '有功功率', 'operator': '=', 'value': 120, 'unit': 'kW'}, {}),
    ('将SIM-IEC-INVERTER-01的有功功率设为120kW', {'parameter': '有功功率', 'operator': '=', 'value': 120, 'unit': 'kW', 'condition': '负责人许可'}, {}),
    ('将SIM-IEC-INVERTER-01的有功功率设为120kW', {'parameter': '有功功率', 'operator': '=', 'value': 120, 'unit': 'kW'}, {'power_kw': True}),
    ('将SIM-IEC-INVERTER-01的有功功率设为120kW', {'parameter': '有功功率', 'operator': '=', 'value': 120, 'unit': 'kW'}, {'power_kw': 'NaN'}),
])
def test_ambiguous_invalid_or_conditional_targets_stay_blocked(monkeypatch, query, constraint, extra):
    app, parameters, before, _ = app_for(monkeypatch, intent='instruction', actions=['adjust_active_power'],
                                       constraints=[constraint])
    parameters.update(simulation_scenario_id='renewable_grid_integration', action_parameters=extra)
    response = app.analyze(AnalysisRequest(query, parameters=parameters))
    assert response.status != 'generated'
    assert not (response.data.get('candidate_instruction') or {}).get('payload')
    assert app.simulation_runtime.snapshot(before['session_id']) == before
