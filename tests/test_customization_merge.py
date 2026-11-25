from copy import deepcopy


def empty(): return {'devices': [], 'instructions': [], 'bindings': []}


def test_partial_merge_keeps_current_and_deduplicates_identical_rows():
    from standard_knowledge_service_v2.instruction_engine.customization_merge import preview
    current=empty();current['devices']=[{'device_id':'SIM-A','display_name':'甲'}]
    incoming={'devices':[deepcopy(current['devices'][0]),{'device_id':'SIM-B','display_name':'乙'}]}
    before=deepcopy(current);result=preview(current,incoming)
    assert result['status']=='merged' and len(result['state']['devices'])==2
    assert result['counts']['unchanged']==1 and result['counts']['added']==1
    assert current==before


def test_same_id_difference_requires_explicit_choice_and_keeps_wire_together():
    from standard_knowledge_service_v2.instruction_engine.customization_merge import preview
    current=empty();current['bindings']=[{'device_id':'SIM-A','instruction_id':'START','wire':{'command':{'address':10}}}]
    incoming={'bindings':[{'device_id':'SIM-A','instruction_id':'START','wire':{'command':{'address':20}}}]}
    result=preview(current,incoming);assert result['status']=='conflicts'
    key=result['conflicts'][0]['key']
    assert preview(current,incoming,{key:'current'})['state']['bindings'][0]['wire']['command']['address']==10
    chosen=preview(current,incoming,{key:'incoming'})
    assert chosen['status']=='merged' and chosen['state']['bindings'][0]['wire']['command']['address']==20


def test_duplicate_ids_inside_one_import_are_not_last_write_wins():
    from standard_knowledge_service_v2.instruction_engine.customization_merge import preview
    result=preview(empty(),{'devices':[{'device_id':'SIM-A'},{'device_id':'SIM-A'}]})
    assert result['status']=='invalid'


def test_action_conflict_is_explicit_and_kept_template_is_not_overwritten():
    from standard_knowledge_service_v2.instruction_engine.customization_merge import preview
    current=empty();current['instructions']=[{'instruction_id':'OLD','action':{'action':'start'}}]
    current['bindings']=[{'device_id':'SIM-A','instruction_id':'OLD'}]
    incoming={'instructions':[{'instruction_id':'NEW','action':{'action':'start'}}],
              'bindings':[{'device_id':'SIM-A','instruction_id':'NEW'}]}
    result=preview(current,incoming);assert result['status']=='conflicts'
    key=next(c['key'] for c in result['conflicts'] if c['kind']=='action')
    result=preview(current,incoming,{key:'current'});assert result['status']=='merged'
    assert result['state']['bindings']==current['bindings']
    assert result['skipped_instructions']==['NEW']


def test_replacing_one_binding_does_not_drop_other_device_associations():
    from standard_knowledge_service_v2.instruction_engine.customization_merge import preview
    current=empty();current['instructions']=[{'instruction_id':'OLD','action':{'action':'start'}}]
    current['bindings']=[{'device_id':'SIM-A','instruction_id':'OLD'},{'device_id':'SIM-B','instruction_id':'OLD'}]
    incoming={'instructions':[{'instruction_id':'NEW','action':{'action':'start'}}],
              'bindings':[{'device_id':'SIM-A','instruction_id':'NEW'}]}
    result=preview(current,incoming);key=next(c['key'] for c in result['conflicts'] if c['kind']=='action')
    chosen=preview(current,incoming,{key:'incoming'})
    assert chosen['status']=='merged'
    assert {'device_id':'SIM-B','instruction_id':'OLD'} in chosen['state']['bindings']
    assert {'device_id':'SIM-A','instruction_id':'NEW'} in chosen['state']['bindings']
