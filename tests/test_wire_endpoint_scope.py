from copy import deepcopy
import pytest
from test_customization import sample
from test_customization_wire import wire
from standard_knowledge_service_v2.instruction_engine import customization as c


@pytest.mark.parametrize('overlap',['feedback','other_device'])
def test_multi_register_occupancy_rejects_overlapping_ranges(overlap):
    state=sample();d=state['devices'][0];d['device_type']='dispatch_unit';d['fields']=d['fields'][:1]
    d['fields'][0].update(key='output',type='number',unit='MW',value=0.0)
    i=state['instructions'][0];i.update(device_type='dispatch_unit',fields=deepcopy(d['fields']))
    i['action']=dict(action='adjust_active_power',result_field='output',minimum=0.0,maximum=100.0,conditions=[dict(field='output',operator='>=',value=0.0)])
    w=wire();w['command'].update(function_code=16,data_type='float32')
    w['feedback'].update(function_code=3,data_type='float32',field='state.output');state['bindings'][0]['wire']=w
    if overlap=='feedback':w['feedback']['address']=55001
    else:
        state['devices'].append(dict(deepcopy(d),device_id='SIM-CUSTOM-02',display_name='第二数值设备'))
        b=deepcopy(state['bindings'][0]);b['device_id']='SIM-CUSTOM-02'
        b['wire']['command']['address']=55001;b['wire']['feedback']['address']=55012;state['bindings'].append(b)
    with pytest.raises(ValueError,match='重叠|冲突|分开'):c._prepare(state,deepcopy(c.EMPTY))


@pytest.mark.parametrize('protocol',['Modbus','IEC61850'])
@pytest.mark.parametrize('endpoint_field',['host','port'])
def test_same_points_on_different_endpoints_are_distinct_but_same_endpoint_conflicts(protocol, endpoint_field):
    state=sample()
    if protocol=='Modbus':w=wire()
    else:
        base=c.SimulationCatalog(legacy_service=c._base());w=c.extract_wire(base.devices['SIM-IEC-FAN-01'],'start')
        w['command'].update(domain_id='SCOPE',item_id='GGIO1$CO$SPCSO1$Oper',object_reference='SCOPE/GGIO1.SPCSO1')
        w['feedback'].update(domain_id='SCOPE',item_id='GGIO1$ST$Ind1$stVal',object_reference='SCOPE/GGIO1.Ind1',field='state.running')
    w['communication']['host']='192.0.2.240';state['bindings'][0]['wire']=w
    state['devices'].append(dict(deepcopy(state['devices'][0]),device_id='SIM-SCOPE-02',display_name='第二主机风机'))
    second=deepcopy(state['bindings'][0]);second['device_id']='SIM-SCOPE-02'
    second['wire']['communication'][endpoint_field]='192.0.2.241' if endpoint_field=='host' else w['communication']['port']+1
    state['bindings'].append(second)
    c._prepare(state,deepcopy(c.EMPTY))
    second['wire']['communication'][endpoint_field]=w['communication'][endpoint_field]
    with pytest.raises(ValueError,match='点位冲突'):c._prepare(state,deepcopy(c.EMPTY))


@pytest.mark.parametrize('section',['command','feedback'])
def test_iec_reference_cannot_disagree_with_encoded_identifier(section):
    base=c.SimulationCatalog(legacy_service=c._base());w=c.extract_wire(base.devices['SIM-IEC-FAN-01'],'start')
    w['communication']['host']='192.0.2.240';w['command'].update(domain_id='REF',item_id='GGIO1$CO$SPCSO1$Oper',object_reference='REF/GGIO1.SPCSO1')
    w['feedback'].update(domain_id='REF',item_id='GGIO1$ST$Ind1$stVal',object_reference='REF/GGIO1.Ind1',field='state.running')
    w[section]['object_reference']='OTHER/GGIO9.Other'
    state=sample();state['bindings'][0]['wire']=w
    with pytest.raises(ValueError,match='标识'):c._prepare(state,deepcopy(c.EMPTY))


def test_iec_long_and_short_references_to_same_mms_variable_conflict():
    state=sample()
    base=c.SimulationCatalog(legacy_service=c._base())
    w=c.extract_wire(base.devices['SIM-IEC-FAN-01'],'start')
    w['communication']['host']='192.0.2.240'
    w['command'].update(domain_id='REF',item_id='GGIO1$CO$SPCSO1$Oper',object_reference='REF/GGIO1.SPCSO1')
    w['feedback'].update(domain_id='REF',item_id='GGIO1$ST$Ind1$stVal',object_reference='REF/GGIO1.Ind1',field='state.running')
    state['bindings'][0]['wire']=w
    state['devices'].append(dict(deepcopy(state['devices'][0]),device_id='SIM-SCOPE-02',display_name='第二台风机'))
    second=deepcopy(state['bindings'][0]);second['device_id']='SIM-SCOPE-02'
    second['wire']['command']['object_reference']+='Alt'
    second['wire']['command']['item_id']='GGIO1$CO$SPCSO1Alt$Oper'
    second['wire']['feedback']['object_reference']+='.stVal'
    state['bindings'].append(second)
    with pytest.raises(ValueError,match='点位冲突'):c._prepare(state,deepcopy(c.EMPTY))
