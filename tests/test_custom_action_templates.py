from copy import deepcopy
import pytest
from test_customization import sample
from standard_knowledge_service_v2.instruction_engine import customization as c
from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime


def custom_state(mode='fixed',value=False,numeric=False):
    s=sample();s['instructions'][0]['display_name']='自定义滤网复位'
    a=s['instructions'][0]['action'];a.update(action='reset_filter',display_name='滤网复位',value_source=mode,value=value,parameter='')
    if numeric:
        for row in [s['devices'][0],s['instructions'][0]]:
            row['fields'][0].update(key='duty',label='送风比例',type='number',unit='%',value=10.0)
        a.update(action='set_air_ratio',display_name='设置送风比例',result_field='duty',minimum=0.0 if mode=='parameter' else None,maximum=100.0 if mode=='parameter' else None,parameter='target_ratio' if mode=='parameter' else '',value=None if mode=='parameter' else value)
        w=s['bindings'][0]['wire'];w['command'].update(function_code=16,data_type='float32');w['feedback'].update(function_code=3,data_type='float32',field='state.duty')
    return s


def iec(s):
    base=c.SimulationCatalog(legacy_service=c._base());w=c.extract_wire(base.devices['SIM-IEC-FAN-01'],'start')
    a=s['instructions'][0]['action'];numeric=a['result_field']=='duty'
    w['communication']['host']='192.0.2.244'
    w['command'].update(domain_id='ACTION',item_id='GGIO1$CO$Custom$Oper',object_reference='ACTION/GGIO1.Custom',unit='%' if numeric else '',data_type='float32' if numeric else 'bool',value_shape='analogue' if numeric else 'primitive')
    w['feedback'].update(domain_id='ACTION',item_id='GGIO1$ST$Result$stVal',object_reference='ACTION/GGIO1.Result',field='state.'+a['result_field'],unit='%' if numeric else '',data_type='float32' if numeric else 'bool')
    s['bindings'][0]['wire']=w


@pytest.mark.parametrize('value',[True,False])
@pytest.mark.parametrize('protocol',['Modbus','IEC61850'])
def test_new_fixed_boolean_action_controls_payload_and_result(value,protocol):
    s=custom_state(value=value);s['devices'][0]['fields'][0]['value']=not value
    if protocol=='IEC61850':iec(s)
    _,cat,_=c._prepare(s,deepcopy(c.EMPTY));runtime=SimulationRuntime(cat,event_path=None)
    session=runtime.create_session('all_devices');p=runtime.preview(session['session_id'],'SIM-CUSTOM-01','reset_filter',{})
    assert p['status']=='generated',p
    assert p['candidate']['payload']['engineering_value'] is value
    assert p['expected_changes']['SIM-CUSTOM-01']['state']['running'] is value
    packet=runtime.generate_message(session['session_id'],p['command_id'],p['expected_version'],{})
    if protocol=='Modbus':assert packet['details']['encoded_value']==(65280 if value else 0)
    else:assert packet['engineering_value'] is value and len(packet['requests'])>=5


@pytest.mark.parametrize('mode,value,parameters',[('fixed',25.0,{}),('parameter',None,{'target_ratio':45.0})])
@pytest.mark.parametrize('protocol',['Modbus','IEC61850'])
def test_new_numeric_action_supports_explicit_parameter_or_constant(mode,value,parameters,protocol):
    s=custom_state(mode,value,numeric=True)
    if protocol=='IEC61850':iec(s)
    _,cat,_=c._prepare(s,deepcopy(c.EMPTY));runtime=SimulationRuntime(cat,event_path=None)
    sid=runtime.create_session('all_devices')['session_id'];p=runtime.preview(sid,'SIM-CUSTOM-01','set_air_ratio',parameters)
    assert p['status']=='generated',p
    assert p['expected_changes']['SIM-CUSTOM-01']['state']['duty']==(value if mode=='fixed' else 45)
    packet=runtime.generate_message(sid,p['command_id'],p['expected_version'],{})
    assert packet['engineering_value']==(value if mode=='fixed' else 45)


def test_explicit_unconditional_custom_action_and_rejected_type():
    s=custom_state();s['instructions'][0]['action']['conditions']=[]
    _,cat,_=c._prepare(s,deepcopy(c.EMPTY));runtime=SimulationRuntime(cat,event_path=None);sid=runtime.create_session('all_devices')['session_id']
    assert runtime.preview(sid,'SIM-CUSTOM-01','reset_filter',{})['status']=='generated'
    s['instructions'][0]['action']['value']=1
    with pytest.raises(ValueError,match='类型|布尔'):c._prepare(s,deepcopy(c.EMPTY))


def test_custom_parameter_bounds_and_false_condition_still_block():
    s=custom_state('parameter',numeric=True);_,cat,_=c._prepare(s,deepcopy(c.EMPTY));runtime=SimulationRuntime(cat,event_path=None);sid=runtime.create_session('all_devices')['session_id']
    assert runtime.preview(sid,'SIM-CUSTOM-01','set_air_ratio',{'target_ratio':101})['status']=='blocked'
    s['devices'][0]['fields'][1]['value']=False
    _,cat,_=c._prepare(s,deepcopy(c.EMPTY));runtime=SimulationRuntime(cat,event_path=None);sid=runtime.create_session('all_devices')['session_id']
    assert runtime.preview(sid,'SIM-CUSTOM-01','set_air_ratio',{'target_ratio':45})['status']=='blocked'


def test_custom_action_publish_and_restart_preserve_parameter_identity(tmp_path,monkeypatch):
    from standard_knowledge_service_v2.instruction_engine.simulation_control import SimulationControlSession
    monkeypatch.setattr(c,'CUSTOM_PATH',tmp_path/'custom.json')
    session=SimulationControlSession();runtime=SimulationRuntime(c.SimulationCatalog(legacy_service=session.service),event_path=None)
    state=custom_state('parameter',numeric=True);view=c.snapshot(session,runtime);payload=dict(state=state,base_revision=view['base_revision'])
    validated=c.process(session,runtime,payload);assert validated['status']=='validated',validated
    assert c.process(session,runtime,{**payload,'revision':validated['revision']},publish=True)['status']=='published'
    restored=SimulationControlSession();action=restored.service.devices['SIM-CUSTOM-01']['actions']['set_air_ratio']
    assert action['parameter']=='target_ratio' and action['display_name']=='设置送风比例'
    assert action['simulation_effects']['state']['duty']=={'from_parameter':'target_ratio'}
