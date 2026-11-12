"""Controlled model replies for legacy tests; never used by the application."""
import re
from decimal import Decimal


def add_semantic_plan(payload, query, catalog, scenario_id="all_devices"):
    operations, questions = [], []
    prior = None
    fragments = [s.strip() for s in re.split(r'，同时|，然后|，再|，|同时|；', query) if s.strip()]
    for source in fragments:
        found=[]
        compact=re.sub(r"\s+", "", source)
        allowed=catalog.scenarios.get(scenario_id,{}).get('device_ids',list(catalog.devices))
        for key,d in catalog.devices.items():
            if key not in allowed: continue
            aliases=[key,d.get('display_name',''),*d.get('aliases',[])]
            if any(a and re.search(re.escape(re.sub(r"\s+", "", a))+r'(?!\d)',compact,re.I) for a in aliases): found.append(key)
        owners=[key for key in found if catalog.devices[key]['device_type']=='transformer']
        role=next((r for r,w in [('cooling_fan','风机'),('oil_pump','油泵'),('tap_changer','调压装置')] if w in source),None)
        if role:
            selected=[key for key in found if catalog.devices[key]['device_type']==role]
            for profile in catalog.scenarios.values():
                groups=profile.get('groups',{})
                for group in groups.values() if isinstance(groups,dict) else groups:
                    if group.get('transformer') in owners and group.get(role) not in selected: selected.append(group[role])
            found=selected
        if not found and prior and re.search('其|它|该设备',source): found=[prior]
        if not found and len(fragments)==1:
            found=[e['name'] for e in payload.get('entities',[]) if e.get('name') in catalog.devices]
        unknown=re.search(r'(?:主变|冷却风机|油泵)99|SIM-[A-Z-]+99|神秘',source)
        if not found: found=['SIM-UNKNOWN-99']
        actions=payload.get('actions',[])
        if len(fragments)>1:
            choices=[a for word,a in [('启动','start'),('停止','stop'),('有功','adjust_active_power'),('无功','adjust_reactive_power'),('电压','regulate_voltage')] if word in source]
            if choices: actions=choices
        kind=payload['scenario']['query_kind']
        for key in dict.fromkeys(found):
            owner=owners[0] if len(owners)==1 and role else ''
            if role and not owner:
                for profile in catalog.scenarios.values():
                    groups=profile.get('groups',{})
                    for group in groups.values() if isinstance(groups,dict) else groups:
                        if group.get(role)==key and group.get('transformer') in owners: owner=group['transformer']
            if key in source and owner:
                matched=False
                for profile in catalog.scenarios.values():
                    groups=profile.get('groups',{})
                    for group in groups.values() if isinstance(groups,dict) else groups:
                        if group.get('transformer')==owner and group.get(role)==key: matched=True
                if not matched: owner=''
            target = source
            if owner and role:
                owner_name='主变'+('1' if owner.endswith('01') else '2')
                match=re.search(re.escape(owner_name)+r'的?(?:冷却风机|油泵|调压装置)',source)
                if match: target=match[0]
            if (not role or not owner) and key in catalog.devices:
                labels=[a for a in [key,catalog.devices[key].get('display_name',''),*catalog.devices[key].get('aliases',[])] if a and a in source]
                if labels: target=max(labels,key=len)
            common=dict(device_id=key,target_text=target,owner_id=owner,source_text=source,clarification='目标未登记' if unknown else '')
            if kind=='operation':
                for action in actions or ['start']:
                    if role=='tap_changer' and action=='regulate_voltage': action='set_tap'
                    parameters={}
                    template=catalog.devices.get(key,{}).get('actions',{}).get(action,{})
                    field=template.get('parameter')
                    for c in payload.get('constraints',[]):
                        if len(fragments)>1 and str(c.get('value')) not in source: continue
                        if c.get('operator') not in ('=','==') or c.get('condition'): continue
                        aliases={'power_kw':['有功功率','目标功率','目标有功功率','power_kw'],'reactive_power_kvar':['无功功率','无功功率设定值','reactive_power_kvar'],'voltage_v':['输出电压','目标电压','电压','voltage_v'],'power_limit_kw':['功率上限','功率限制','power_limit_kw'],'tap_position':['档位','目标档位','调压档位','tap_position']}
                        if c.get('parameter') not in aliases.get(field,[]): continue
                        factors={'W':Decimal(1),'kW':Decimal(1000),'MW':Decimal(1000000),'mW':Decimal('.001'),'V':Decimal(1),'kV':Decimal(1000),'var':Decimal(1),'kvar':Decimal(1000),'档':Decimal(1)}
                        unit=c.get('unit') or template.get('unit')
                        if unit in factors and template.get('unit') in factors:
                            number=Decimal(str(c['value']))*factors[unit]/factors[template['unit']]
                            parameters[field]=int(number) if number==number.to_integral_value() else float(number)
                    operations.append(dict(**common,action=action,parameters=parameters,negated=False,conditions=[],order=None))
            else:
                questions.append(dict(**common,query_kind=kind))
        if len(found)==1: prior=found[0]
    if operations: payload['actions']=list(dict.fromkeys(item['action'] for item in operations))
    payload.update(operations=operations,queries=questions)
    return payload
