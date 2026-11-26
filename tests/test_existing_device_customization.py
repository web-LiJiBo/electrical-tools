from copy import deepcopy
import pytest
from standard_knowledge_service_v2.instruction_engine import customization as c
from standard_knowledge_service_v2.instruction_engine.simulation_control import SimulationControlSession
from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime


def valve_alarm():
    base=c.SimulationCatalog();target=base.devices['SIM-IEC-VALVE-01']
    fields=[dict(key='local_alarm',label='补充告警',section='state',type='boolean',unit='',value=False)]
    action=dict(action='notify_local_alarm',display_name='发送补充告警',value_source='fixed',value=True,parameter='',result_field='local_alarm',minimum=None,maximum=None,conditions=[])
    wire=c.extract_wire(base.devices['SIM-IEC-FAN-01'],'start');wire['communication']=deepcopy(target['communication'])
    wire['command'].update(domain_id='LOCALVALVE',item_id='GGIO1$CO$Notify$Oper',object_reference='LOCALVALVE/GGIO1.Notify')
    wire['feedback'].update(domain_id='LOCALVALVE',item_id='GGIO1$ST$LocalAlarm$stVal',object_reference='LOCALVALVE/GGIO1.LocalAlarm',field='state.local_alarm')
    state=deepcopy(c.EMPTY);state['instructions']=[dict(instruction_id='VALVE-ALARM',display_name='换流阀补充告警',device_type='pole_controller',fields=fields,action=action)]
    state['bindings']=[dict(device_id=target['device_id'],instruction_id='VALVE-ALARM',wire=wire)]
    return state


def test_all_existing_device_types_are_available_in_unified_form(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'CUSTOM_PATH',tmp_path/'custom.json')
    runtime=SimulationRuntime(event_path=None);view=c.snapshot(SimulationControlSession(),runtime)
    assert {d['device_type'] for d in runtime.catalog.devices.values()} <= set(view['options']['device_types'])


def test_existing_valve_new_action_field_and_packet_without_legacy_page(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'CUSTOM_PATH',tmp_path/'custom.json');session=SimulationControlSession();runtime=SimulationRuntime(event_path=None)
    target='SIM-IEC-VALVE-01';original=deepcopy(runtime.catalog.devices[target])
    state=valve_alarm();payload=dict(state=state,base_revision=c.snapshot(session,runtime)['base_revision'])
    checked=c.process(session,runtime,payload);assert checked['status']=='validated',checked
    assert checked['field_additions'][0]['fields'][0]['key']=='local_alarm'
    assert c.process(session,runtime,{**payload,'revision':checked['revision']},publish=True)['status']=='published'
    after=runtime.catalog.devices[target]
    assert after['initial_state']['local_alarm'] is False
    assert after['communication']==original['communication']
    for name,action in original['actions'].items():
        for section in ('mapping','feedback_mapping'):
            for endpoint in ('host','port'):action.get(section,{}).pop(endpoint,None)
        assert after['actions'][name]==action
    sid=runtime.create_session('all_devices')['session_id'];p=runtime.preview(sid,target,'notify_local_alarm',{})
    assert p['status']=='generated',p
    assert runtime.generate_message(sid,p['command_id'],p['expected_version'],{})['bundle_base64']
    restored=SimulationControlSession();assert restored.service.devices[target]['initial_state']['local_alarm'] is False


def test_existing_fields_cannot_be_retyped_by_new_instruction():
    state=valve_alarm();state['instructions'][0]['fields'][0]['key']='active_power_mw';state['instructions'][0]['action']['result_field']='active_power_mw'
    with pytest.raises(ValueError,match='字段|类型|单位'):c._prepare(state,deepcopy(c.EMPTY))


def test_previously_added_field_cannot_silently_change_unit():
    previous=valve_alarm()
    previous['instructions'][0]['fields'].append(dict(key='local_power',label='补充功率',section='state',type='number',unit='MW',value=0))
    c._prepare(previous,deepcopy(c.EMPTY))
    current=deepcopy(previous);current['instructions'][0]['fields'][1]['unit']='kW'
    with pytest.raises(ValueError,match='已补充字段'):c._prepare(current,previous)
