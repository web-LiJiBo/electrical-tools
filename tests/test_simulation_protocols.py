from copy import deepcopy
import pytest
from standard_knowledge_service_v2.instruction_engine.simulation import SimulationInstructionService

@pytest.mark.parametrize('protocol', ['IEC', 'MB'])
@pytest.mark.parametrize('action,facts', [('trip', {'current': 120}), ('close', {'close_permission': 1})])
def test_generate_without_execution(protocol, action, facts):
    service = SimulationInstructionService()
    before = deepcopy(service.states)
    candidate = service.generate(f'SIM-{protocol}-BREAKER-01', action, facts)
    assert candidate.payload and candidate.dispatch_allowed is False
    assert service.states == before
    assert not hasattr(service, 'run')

@pytest.mark.parametrize('facts', [{}, {'current': 20}, {'current': float('nan')}])
def test_invalid_conditions_no_instruction(facts):
    assert not SimulationInstructionService().generate('SIM-IEC-BREAKER-01', 'trip', facts).payload

def test_protocol_fields_only():
    service = SimulationInstructionService()
    assert service.generate('SIM-MB-BREAKER-01', 'trip', {'current': 120}).payload['pdu_hex'] == '05 00 00 00 00'
    assert service.generate('SIM-IEC-VALVE-01', 'runback_power', service.devices['SIM-IEC-VALVE-01']['runtime_facts'], {'target_power_mw': 80}).payload['ctlVal'] == 80
