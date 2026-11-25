import pytest
from standard_knowledge_service_v2.instruction_engine.simulation_catalog import SimulationCatalog
from standard_knowledge_service_v2.application.semantic_operations import bind_target


@pytest.mark.parametrize('target,key,fragment', [
    ('逆变器','SIM-MB-INVERTER-01','分别查询逆变器当前无功'),
    ('储能','SIM-IEC-BESS-01','储能当前运行状态')])
def test_generic_type_reference_uses_unique_explicit_same_request_device(target,key,fragment):
    catalog=SimulationCatalog();devices=list(catalog.devices.values())
    query='请把SIM-MB-INVERTER-01无功设为80 kvar，启动SIM-IEC-BESS-01，并分别查询逆变器当前无功和储能当前运行状态。'
    row=dict(device_id=key,target_text=target,source_text=fragment,owner_id='',query_kind='device_status')
    actual,reason=bind_target(row,query,devices,catalog.scenarios['all_devices'])
    assert not reason
    assert actual==key


def test_generic_type_reference_does_not_select_between_two_explicit_inverters():
    catalog=SimulationCatalog();query='请比较SIM-MB-INVERTER-01和SIM-IEC-INVERTER-01，查询逆变器当前无功。'
    row=dict(device_id='SIM-MB-INVERTER-01',target_text='逆变器',source_text='查询逆变器当前无功',owner_id='',query_kind='device_status')
    actual,reason=bind_target(row,query,list(catalog.devices.values()),catalog.scenarios['all_devices'])
    assert not actual and reason
