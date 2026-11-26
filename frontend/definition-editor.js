(() => {
  window.definitionOptions = (base, definitions={}) => {
    const options=structuredClone(base);
    for(const row of definitions.device_types||[]){options.device_types[row.code]=row.name;options.actions[row.code]||={};}
    options.units=[...new Set([...options.units,...(definitions.units||[]).map(row=>row.symbol)])];
    return options;
  };
  window.addCustomDefinition = (state, kind, row, base) => {
    const definitions=state.definitions||{device_types:[],units:[]};
    if(kind==='device_types'){
      if(!/^[a-z][a-z0-9_]{0,47}$/.test(row.code)||!row.name.trim()||row.name.length>40)throw Error('请填写有效的类型编号和名称。');
      if(base.device_types[row.code]||(definitions.device_types||[]).some(r=>r.code===row.code||r.name===row.name)||Object.values(base.device_types).includes(row.name))throw Error('设备类型编号或名称重复。');
    }else{
      if(!row.symbol||row.symbol.length>24||/[\s<>"'`{}\\,;，；]/.test(row.symbol))throw Error('请填写不含空白和分隔符的单位符号。');
      if(base.units.includes(row.symbol)||(definitions.units||[]).some(r=>r.symbol===row.symbol))throw Error('单位符号重复。');
      if(!Number.isFinite(row.scale)||row.scale<=0||!Number.isFinite(row.offset))throw Error('请填写有限正数倍率及有效偏移。');
      if(row.symbol===row.base_unit)throw Error('单位不能以自身作为换算基准。');
    }
    if((definitions[kind]||[]).length>=100)throw Error('类型与单位各最多100项。');
    const next=structuredClone(state);next.definitions=structuredClone(definitions);next.definitions[kind]||=[];next.definitions[kind].push(row);return next;
  };

  window.definitionFormMarkup=(kind,units,esc)=>kind==='device_types'
    ? `<div class="form-grid"><label>类型编号<input name="code" required pattern="[a-z][a-z0-9_]{0,47}" maxlength="48" placeholder="如 insulation_monitor"></label><label>类型名称<input name="name" required maxlength="40" placeholder="如 绝缘监测装置"></label></div><p class="hint">新增后直接回选，其他设备也可复用；动作和报文仍需明确配置。</p>`
    : `<div class="form-grid"><label>单位符号<input name="symbol" required maxlength="24" placeholder="如 GW、pu"></label><label>换算基准<select name="base_unit"><option value="">不自动换算</option>${units.map(unit=>`<option value="${esc(unit)}">${esc(unit)}</option>`).join('')}</select></label><label>倍率<input name="scale" required type="number" step="any" min="0.000000000001" max="1000000000000" value="1"></label><label>偏移<input name="offset" required type="number" step="any" value="0"></label></div><p class="hint">基准值 = 新单位数值 × 倍率 + 偏移。不登记换算关系时只接受相同单位。</p>`;
  window.readDefinitionForm=(form,kind)=>{
    const e=form.elements;
    return kind==='device_types'?{code:e.code.value.trim(),name:e.name.value.trim()}
      :{symbol:e.symbol.value.trim(),base_unit:e.base_unit.value,scale:e.base_unit.value?Number(e.scale.value):1,offset:e.base_unit.value?Number(e.offset.value):0};
  };
  window.syncDefinitionUnitMode=form=>{
    const standalone=!form.elements.base_unit.value;
    for(const key of ['scale','offset']){form.elements[key].disabled=standalone;if(standalone)form.elements[key].value=key==='scale'?'1':'0';}
  };
})();
