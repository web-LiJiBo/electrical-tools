from types import SimpleNamespace

import pytest

from standard_knowledge_service_v2.application.real_clause_assessment import _hypothetical_values
from standard_knowledge_service_v2.application.action_parameters import matches_action_parameter
from standard_knowledge_service_v2.application.action_request import action_request_restriction


@pytest.mark.parametrize('mode', ['ON', 'OF', 'OD'])
def test_hypothesis_preserves_cooling_mode(mode):
    request = SimpleNamespace(parameters={}, query=f'假设主变1绕组平均温升70K，{mode}冷却')
    parsed = SimpleNamespace(constraints=[
        {'parameter': '绕组平均温升', 'operator': '=', 'value': 70},
        {'parameter': '冷却方式', 'operator': '=', 'value': mode}])
    assert _hypothetical_values(request, parsed) == {'winding_average_rise_k': 70, 'cooling_mode': mode}


def test_explicit_hypothetical_mode():
    assert _hypothetical_values(SimpleNamespace(parameters={'hypothetical_facts': {'cooling_mode': 'OD'}}, query='假设'), None)['cooling_mode'] == 'OD'


def test_tap_full_alias():
    assert matches_action_parameter('调压装置档位', 'tap_position')


@pytest.mark.parametrize('query', ['先别启动主变1的冷却风机', '暂缓将主变1调压装置设为8档'])
def test_deferred_actions_block_even_when_model_drops_condition(query):
    assert action_request_restriction(query, {'actions': ['start'], 'constraints': []}, instruction_request=True)
