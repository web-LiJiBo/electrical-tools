/* A user-defined action is an explicit typed assignment, not executable script. */
(() => {
 window.readActionDefinition=(form,conditions)=>{
  const base={action:form.action,result_field:form.result_field,minimum:null,maximum:null,conditions};
  const numeric=value=>{if(value==null||String(value).trim()===''||!Number.isFinite(Number(value)))throw Error('请填写有效的最小和最大目标值。');return Number(value);};
  if(form.definition==='preset')return {...base,minimum:form.binary?null:numeric(form.minimum),maximum:form.binary?null:numeric(form.maximum)};
  return {...base,display_name:form.display_name,value_source:form.value_source,
   parameter:form.value_source==='parameter'?form.parameter:'',
   value:form.value_source==='fixed'?form.value:null,
   minimum:form.value_source==='parameter'?numeric(form.minimum):null,
   maximum:form.value_source==='parameter'?numeric(form.maximum):null};
 };
 window.createActionEditor=(container,{kind,initial,fields,actions,optionMarkup,scalarMarkup,scalarRead,invalidate,esc})=>{
  const spec=initial||{action:'',result_field:'',minimum:0,maximum:100,conditions:[],value_source:'fixed',value:false};
  const custom=Boolean(spec.value_source);let currentKind=kind;
  container.innerHTML=`<div class="form-grid"><label>动作定义方式<select data-definition>${optionMarkup({custom:'自定义新动作',preset:'使用已有动作'},custom?'custom':'preset')}</select></label><label data-preset>已有动作<select data-action></select></label><label data-custom>动作编号<input data-code required pattern="[a-z][a-z0-9_]{0,47}" maxlength="48" placeholder="如 reset_filter" value="${custom?esc(spec.action):''}"></label><label data-custom>动作名称<input data-label required maxlength="80" value="${custom?esc(spec.display_name||''):''}" placeholder="如 滤网复位"></label><label data-custom>状态值来源<select data-source>${optionMarkup({fixed:'写入固定值',parameter:'使用提问中的数值参数'},spec.value_source||'fixed')}</select></label><label>状态变化写入字段<select data-result required></select></label><label data-fixed>固定目标值<span data-fixed-value></span></label><label data-parameter>参数编号<input data-parameter-name required pattern="[a-z][a-z0-9_]{0,39}" maxlength="40" placeholder="如 target_ratio" value="${custom?esc(spec.parameter||''):''}"></label><label data-range>最小目标值<input data-min required type="number" step="any" value="${esc(spec.minimum??0)}"></label><label data-range>最大目标值<input data-max required type="number" step="any" value="${esc(spec.maximum??100)}"></label></div><p class="hint">新动作按所选结果字段的类型和单位写入固定值或参数值。每个模板对应一个控制值和一个状态字段，报文映射在下方按设备配置。自定义动作未添加条件时表示无前置条件。</p><h3>前置条件（全部满足）</h3><div data-rules></div><button type="button" data-add-rule>添加条件</button>`;
  const get=s=>container.querySelector(s);
  function toggle(selector,visible){for(const node of container.querySelectorAll(selector)){node.hidden=!visible;for(const control of node.querySelectorAll('input,select'))control.disabled=!visible;}}
  function updateRule(row){
   const selector=row.querySelector('[data-field]'),previous=selector.value||row.dataset.initial;
   selector.innerHTML='<option value="">选择检查字段</option>'+optionMarkup(Object.fromEntries(fields().filter(f=>f.type!=='enum').map(f=>[f.key,f.label||f.key])),previous);
   const type=fields().find(f=>f.key===selector.value)?.type||'number';
   if(row.dataset.type!==type){row.querySelector('[data-expected]').innerHTML=scalarMarkup(type,row._initial);row.dataset.type=type;}
   const op=row.querySelector('[data-op]'),old=op.value;op.innerHTML=optionMarkup(Object.fromEntries((type==='boolean'?['==','!=']:['==','!=','<','<=','>','>=']).map(x=>[x,x])),old||row.dataset.operator);
  }
  function refresh(){
   const preset=get('[data-definition]').value==='preset',action=get('[data-action]'),old=action.value;
   action.innerHTML=optionMarkup(actions[currentKind]||{},old||spec.action);
   const binary=preset&&['start','stop'].includes(action.value),parameter=!preset&&get('[data-source]').value==='parameter';
   toggle('[data-preset]',preset);toggle('[data-custom]',!preset);toggle('[data-fixed]',!preset&&!parameter);toggle('[data-parameter]',parameter);toggle('[data-range]',preset?!binary:parameter);
   const result=get('[data-result]'),previous=result.value;
   result.innerHTML='<option value="">选择字段</option>'+optionMarkup(Object.fromEntries(fields().filter(f=>binary?f.type==='boolean':!preset&&!parameter?['boolean','number','integer'].includes(f.type):['number','integer'].includes(f.type)).map(f=>[f.key,f.label||f.key])),previous||spec.result_field);
   const field=fields().find(f=>f.key===result.value),type=field?.type||'boolean',holder=get('[data-fixed-value]');
   if(holder.dataset.type!==type){const value=type==='boolean'?(typeof spec.value==='boolean'?spec.value:false):(typeof spec.value==='number'?spec.value:0);holder.innerHTML=scalarMarkup(type,value);holder.dataset.type=type;}
   for(const control of holder.querySelectorAll('input,select'))control.disabled=preset||parameter;
   container.querySelectorAll('[data-rule]').forEach(updateRule);
  }
  function addRule(rule={field:'',operator:'==',value:0}){
   const row=document.createElement('div');row.dataset.rule='';row.dataset.initial=rule.field;row.dataset.operator=rule.operator;row._initial=rule.value;row.className='editor-row';
   row.innerHTML='<div class="form-grid"><label>检查字段<select data-field required></select></label><label>比较方式<select data-op></select></label><label>要求值<span data-expected></span></label></div><button type="button">移除条件</button>';
   get('[data-rules]').append(row);updateRule(row);row.querySelector('[data-field]').onchange=()=>updateRule(row);row.querySelector('button').onclick=()=>{row.remove();invalidate();};
  }
  for(const selector of ['[data-definition]','[data-action]','[data-source]','[data-result]'])get(selector).onchange=refresh;
  get('[data-add-rule]').onclick=()=>{addRule();invalidate();};spec.conditions.forEach(addRule);refresh();
  return {refresh,setKind(value){currentKind=value;refresh();},read(){
   const preset=get('[data-definition]').value==='preset',source=get('[data-source]').value;
   const conditions=[...container.querySelectorAll('[data-rule]')].map(row=>({field:row.querySelector('[data-field]').value,operator:row.querySelector('[data-op]').value,value:scalarRead(row.querySelector('[data-value]'),row.dataset.type)}));
   return window.readActionDefinition({definition:preset?'preset':'custom',action:preset?get('[data-action]').value:get('[data-code]').value.trim(),display_name:get('[data-label]').value.trim(),result_field:get('[data-result]').value,
    binary:['start','stop'].includes(get('[data-action]').value),value_source:source,parameter:get('[data-parameter-name]').value.trim(),
    value:!preset&&source==='fixed'?scalarRead(get('[data-fixed-value] [data-value]'),get('[data-fixed-value]').dataset.type):null,
    minimum:get('[data-min]').value,maximum:get('[data-max]').value},conditions);
  }};
 };
})();
