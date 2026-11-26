from copy import deepcopy
import pytest
from test_custom_action_templates import custom_state
from standard_knowledge_service_v2.instruction_engine import customization as c


def state():
    s = custom_state('parameter', numeric=True)
    s['definitions'] = dict(device_types=[dict(code='insulation_monitor', name='绝缘监测装置')],
                            units=[dict(symbol='Runit', base_unit='', scale=1, offset=0),
                                   dict(symbol='kRunit', base_unit='Runit', scale=1000, offset=0)])
    for row in [s['devices'][0], s['instructions'][0]]:
        row['device_type'] = 'insulation_monitor'
        row['fields'][0].update(unit='Runit', label='绝缘测量值')
    s['devices'][0]['aliases'] = ['绝缘监测甲', '监测一号']
    s['instructions'][0]['action'].update(display_name='设置模拟测量值', maximum=100000)
    for mapping in ('command', 'feedback'):
        s['bindings'][0]['wire'][mapping]['unit'] = 'Runit'
    return s


def test_registered_type_aliases_units_compile_and_convert():
    s=state();_,cat,_=c._prepare(s,deepcopy(c.EMPTY));device=cat.devices['SIM-CUSTOM-01']
    assert device['device_type']=='insulation_monitor' and {'绝缘监测甲','监测一号'} <= set(device['aliases'])
    from standard_knowledge_service_v2.application.action_parameters import resolve_action_parameters
    template=device['actions']['set_air_ratio']
    evidence=dict(parameter_evidence=[dict(parameter='target_ratio',value_text='2',unit_text='kRunit',source_text='设为2kRunit',role='target')])
    values,error=resolve_action_parameters('设为2kRunit',template,{},evidence)
    assert not error and values['target_ratio']==2000


@pytest.mark.parametrize('alias',['模拟冷却风机1','SIM-IEC-FAN-01','定制风机一号'])
def test_alias_cannot_impersonate_existing_identity(alias):
    s=state();s['devices'][0]['aliases']=[alias]
    with pytest.raises(ValueError,match='别名|重复'):c._prepare(s,deepcopy(c.EMPTY))


def test_unknown_type_or_unit_still_requires_registration():
    s=state();s.pop('definitions')
    with pytest.raises(ValueError):c._prepare(s,deepcopy(c.EMPTY))


def test_definitions_merge_and_conflict_preview():
    from standard_knowledge_service_v2.instruction_engine.customization_merge import preview
    original=state(); incoming={'definitions':dict(device_types=[dict(code='insulation_monitor',name='监测设备')],units=[])}
    result=preview(original,incoming)
    assert result['status']=='conflicts'
    key=result['conflicts'][0]['key']
    chosen=preview(original,incoming,{key:'incoming'})
    assert chosen['state']['definitions']['device_types'][0]['name']=='监测设备'
    assert len(chosen['state']['definitions']['units'])==2


def test_registered_unit_offset_and_fact_input_use_same_conversion():
    from standard_knowledge_service_v2.application.action_parameters import _convert
    from standard_knowledge_service_v2.instruction_engine.simulation_inputs import normalize_value
    rows=[dict(symbol='K',base_unit='℃',scale=1,offset=-273.15)]
    assert float(_convert(300,'K','℃',rows))==pytest.approx(26.85)
    assert normalize_value(2,'kRunit',dict(type='number',unit='Runit',unit_definitions=state()['definitions']['units']))==2000


@pytest.mark.parametrize('change',['cycle','builtin','negative','unknown_base'])
def test_invalid_unit_definitions_cannot_publish(change):
    s=state();rows=s['definitions']['units']
    if change=='cycle':rows[0]['base_unit']='kRunit'
    if change=='builtin':rows[0]['symbol']='MW'
    if change=='negative':rows[1]['scale']=-1
    if change=='unknown_base':rows[1]['base_unit']='missing'
    with pytest.raises(ValueError):c._prepare(s,deepcopy(c.EMPTY))


def test_used_unit_dependency_cannot_change_meaning():
    previous=state()
    for row in [previous['devices'][0],previous['instructions'][0]]:row['fields'][0]['unit']='kRunit'
    for name in ('command','feedback'):previous['bindings'][0]['wire'][name]['unit']='kRunit'
    c._prepare(previous,deepcopy(c.EMPTY))
    incoming=deepcopy(previous);incoming['definitions']['units'][0]['base_unit']='W'
    with pytest.raises(ValueError,match='换算定义'):c._prepare(incoming,previous)


def test_publish_restart_preserves_definitions_and_alias_bindings(tmp_path,monkeypatch):
    from standard_knowledge_service_v2.instruction_engine.simulation_control import SimulationControlSession
    from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime
    from standard_knowledge_service_v2.application.semantic_operations import bind_target
    monkeypatch.setattr(c,'CUSTOM_PATH',tmp_path/'custom.json')
    session=SimulationControlSession();runtime=SimulationRuntime(event_path=None)
    s=state();payload=dict(state=s,base_revision=c.snapshot(session,runtime)['base_revision'])
    checked=c.process(session,runtime,payload);assert checked['status']=='validated',checked
    assert c.process(session,runtime,{**payload,'revision':checked['revision']},publish=True)['status']=='published'
    restored=SimulationControlSession();profile=restored.service.devices['SIM-CUSTOM-01']
    assert '绝缘监测甲' in profile['aliases'] and profile['unit_definitions']
    row=dict(device_id='SIM-CUSTOM-01',target_text='绝缘监测甲',source_text='设置绝缘监测甲',owner_id='',clarification='')
    assert bind_target(row,'设置绝缘监测甲',[profile],{})==('SIM-CUSTOM-01','')
    options=c.snapshot(session,runtime)['options']
    assert options['device_types']['insulation_monitor']=='绝缘监测装置' and 'kRunit' in options['units']
