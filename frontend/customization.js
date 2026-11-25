(() => {
  'use strict';
  const $ = id => document.getElementById(id), clone = value => structuredClone(value);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const port = new URLSearchParams(location.search).get('backend_port') === '8001' ? '8001' : '8000';
  const api = `http://127.0.0.1:${port}/simulation`, storageKey = `electrical-customization-${port}`;
  if (port === '8001') { $('home').href += '?backend_port=8001'; $('advanced').href += '?backend_port=8001'; }
  const transactions=[];
  let state = {devices:[],instructions:[],bindings:[]}, baseRevision, catalog = [], library = [], options, review, legacyReview, busy = false, dirty = false, loadWarning = '';
  const exportPanel = window.createCustomizationExport?.($('selective-export'), () => state);
  const types = {number:'数字',integer:'整数',boolean:'是 / 否',enum:'枚举文本'};
  const actionName = (kind, action) => options?.actions?.[kind]?.[action] || action;
  const merged = (published, draft, key) => [...new Map([...published,...draft].map(row => [row[key], row])).values()];
  const allDevices = () => merged(catalog,state.devices,'device_id');
  const allInstructions = () => merged(library.filter(i=>i.readonly),state.instructions,'instruction_id');
  const device = id => allDevices().find(row => row.device_id === id);
  const instruction = id => allInstructions().find(row => row.instruction_id === id);
  function status(message,error = false) { $('status').textContent=message; $('status').dataset.error=String(error); }
  function invalidate() { review=undefined; $('publish').disabled=true; $('review').replaceChildren(); }
  function changed() { invalidate(); dirty=true; persist(); render(); status('草稿已更新。请校验全部配置并核对保存。'); }
  function persist() { try {sessionStorage.setItem(storageKey,JSON.stringify({state,base_revision:baseRevision,dirty}));} catch { $('draft-note').textContent='浏览器无法保存草稿，请导出文件留存。'; } }
  function switchTab(tab) { if (!['devices','instructions','catalog','bulk','clauses'].includes(tab)) tab='devices'; document.querySelectorAll('[data-tab]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.tab===tab))); for(const id of ['devices','instructions','catalog','bulk','clauses']) $(id).hidden=id!==tab; $('configuration-review').hidden=tab==='clauses';const url=new URL(location.href);url.searchParams.set('tab',tab);history.replaceState(null,'',url); }
  async function request(path,body) { if(body&&window.configurationEvents?.isStale())throw Error('配置已更新，请先导出未保存草稿，再手动刷新。'); const response=await fetch(api+path,{...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{cache:'no-store'}),signal:AbortSignal.timeout(30000)}); const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:`请求失败（${response.status}）`);return data; }
  function freeze(value) {busy=value; $('validate').disabled=value||!options; $('publish').disabled=value||!review; $('refresh').disabled=$('reload').disabled=value; $('new-device').disabled=$('new-instruction').disabled=value||!options; for(const id of ['devices','instructions','catalog','bulk','clauses']) $(id).inert=value; }
  async function load(preserve=false) {
    const data=await request('/customization'); if(data.load_error) throw Error(data.load_error);
    loadWarning=data.load_warning||'';catalog=data.devices||[];library=data.instructions||[];options=data.options;
    if(!preserve) {state=clone(data.state);baseRevision=data.base_revision;dirty=false;}
    invalidate(); render(); freeze(false);persist();return data;
  }
  function fieldsOf(row) { if(Array.isArray(row?.fields))return row.fields; return ['state','runtime_facts'].flatMap(section=>Object.entries(row?.[section==='state'?'state_fields':'runtime_fact_fields']||{}).map(([key,spec])=>({key,label:spec.display_name||key,section,type:spec.type,unit:spec.unit||''}))); }
  function compatible(d,i) {if(d.device_type!==i.device_type)return '设备类型不一致'; const fields=fieldsOf(d);const missing=(i.fields||[]).filter(field=>!fields.some(other=>['key','section','type','unit'].every(key=>(other[key]||'')===(field[key]||''))));return missing.length?'字段不匹配：'+missing.map(field=>field.label||field.key).join('、'):'';}
  function render() {
    $('draft-note').textContent=`${loadWarning?'配置提示：'+loadWarning+' · ':''}${dirty?'有待保存草稿 · ':''}${state.devices.length} 台自定义设备 · ${state.instructions.length} 条自定义指令 · ${state.bindings.length} 项关联`;
    $('device-list').innerHTML=allDevices().map(d=>{const refs=state.bindings.filter(b=>b.device_id===d.device_id).map(b=>instruction(b.instruction_id)?.display_name||b.instruction_id);const editable=state.devices.some(row=>row.device_id===d.device_id);return `<article class="card"><h3>${esc(d.display_name)}</h3><div class="identity">${esc(d.device_id)}</div><p>${esc(options?.scenarios?.[d.scenario_id||d.scenario]||d.scenario_id||d.scenario)} · ${esc(options?.device_types?.[d.device_type]||d.device_type)}</p><p>${esc(refs.length?'关联：'+refs.join('、'):'尚无新增关联；原有动作继续可用')}</p><button data-edit-device="${esc(d.device_id)}">${editable?'编辑设备与关联':'查看设备与关联'}</button></article>`;}).join('')||'<p class="empty">还没有设备，点击“新增设备”开始。</p>';
    $('instruction-list').innerHTML=allInstructions().map(i=>`<article class="card"><h3>${esc(i.display_name)}</h3><div class="identity">${esc(i.instruction_id)}</div><p>${esc(options?.device_types?.[i.device_type]||i.device_type)} · ${esc(i.action?.display_name||actionName(i.device_type,i.action?.action))} ${i.readonly?'<span class="badge">预置只读</span>':''}</p><p>${state.bindings.filter(b=>b.instruction_id===i.instruction_id).length} 项新增关联</p><button data-edit-instruction="${esc(i.instruction_id)}">${i.readonly?'查看 / 关联设备':'编辑指令与关联'}</button>${i.readonly?'':`<button data-delete-instruction="${esc(i.instruction_id)}">从草稿删除</button>`}</article>`).join('')||'<p class="empty">还没有指令，点击“新增指令”定义动作与适用设备。</p>';
    renderCatalog();
    exportPanel?.render();
  }
  let catalogRows=[];
  function renderCatalog() {const keyword=$('catalog-search').value.trim().toLowerCase();catalogRows=catalog.flatMap(d=>Object.entries(d.actions||{}).map(([a,t])=>({d,a,t})));$('catalog-list').innerHTML=catalogRows.map((row,index)=>({row,index})).filter(({row})=>JSON.stringify(row).toLowerCase().includes(keyword)).map(({row:{d,a,t},index})=>`<article class="card"><h3>${esc(d.display_name)} · ${esc(t.display_name||actionName(d.device_type,a))}</h3><div class="identity">${esc(d.device_id)} · ${esc(d.protocol)}</div><p>${esc(t.source_rule_ids?.length?'已配置条款来源':'尚无条款来源')} · ${esc(t.unit||'开关量')}</p><button data-detail="${index}">查看详情与适用说明</button></article>`).join('')||'<p class="empty">没有匹配的有效模板。</p>'; }
  function optionMarkup(items,selected) {return Object.entries(items).map(([key,label])=>`<option value="${esc(key)}" ${key===selected?'selected':''}>${esc(label)}</option>`).join('');}
  function finishDialog(d,commit=false) {
    const transaction=d._transaction;
    if(transaction&&!transaction.finished){
      transaction.finished=true;
      if(!commit)state=transaction.previous;
      const index=transactions.indexOf(transaction);
      if(index!==-1)transactions.splice(index,1);
      invalidate();
      // Nested edits remain inside their parent's private copy. Only the outer
      // successful form may replace and persist the main workspace draft.
      if(commit&&transactions.length===0)changed();
      else if(transactions.length===0)render();
    }
  }
  function commitDialog(d){finishDialog(d,true);d.close();}
  function dialog(title,transactional=false) {
    const d=document.createElement('dialog');
    if(transactional){const transaction={previous:state,finished:false};state=clone(state);transactions.push(transaction);d._transaction=transaction;}
    d.innerHTML=`<form><h2>${esc(title)}</h2><p class="dialog-error error" role="alert"></p><div class="dialog-body"></div><div class="dialog-footer"><button type="button" data-cancel>取消</button><button type="submit" class="primary">加入草稿</button></div></form>`;
    $('dialogs').append(d);d.querySelector('[data-cancel]').onclick=()=>{finishDialog(d);d.close();};
    d.addEventListener('cancel',()=>finishDialog(d));
    d.addEventListener('close',()=>{finishDialog(d);d.remove();});
    d.addEventListener('input',invalidate);d.showModal();return d;
  }
  function scalarMarkup(type,value) {return type==='boolean'?`<select data-value>${optionMarkup({'false':'否','true':'是'},String(value??false))}</select>`:`<input data-value ${type==='enum'?'':'type="number"'} step="${type==='integer'?'1':'any'}" required value="${esc(value??(type==='enum'?'':0))}">`;}
  function scalarRead(element,type) { const text=element.value;if(type==='boolean')return text==='true';if(type==='enum')return text.trim();if(text.trim()===''||!Number.isFinite(Number(text)))throw Error('请填写有效数值。');return Number(text); }
  function fieldEditor(container,initial=[]) {
    const notify=()=>container.dispatchEvent(new CustomEvent('fields-change',{bubbles:true}));
    container.addEventListener('change',event=>{if(event.target.matches('[data-key],[data-label],[data-section],[data-type],[data-unit]'))notify();});
    container.addEventListener('input',event=>{if(event.target.matches('[data-key],[data-label]'))notify();});
    const rows=document.createElement('div'),add=document.createElement('button');add.type='button';add.textContent='添加状态字段';container.append(rows,add);
    function append(value={key:'',label:'',section:'state',type:'number',unit:'',value:0}) {const row=document.createElement('div');row.className='editor-row';row.innerHTML=`<div class="field-grid"><label>英文名<input data-key required pattern="[a-z][a-z0-9_]{0,39}" value="${esc(value.key)}"></label><label>显示名称<input data-label required maxlength="40" value="${esc(value.label)}"></label><label>归类<select data-section>${optionMarkup({state:'设备状态',runtime_facts:'许可或运行事实'},value.section)}</select></label><label>类型<select data-type>${optionMarkup(types,value.type)}</select></label><label>单位<select data-unit>${optionMarkup({'':'无',...Object.fromEntries(options.units.map(unit=>[unit,unit]))},value.unit)}</select></label><label>初始值 / 默认值<span data-scalar>${scalarMarkup(value.type,value.value)}</span></label></div><button type="button" data-remove>移除字段</button>`;rows.append(row);const update=()=>{const type=row.querySelector('[data-type]').value;row.querySelector('[data-scalar]').innerHTML=scalarMarkup(type);row.querySelector('[data-unit]').disabled=['boolean','enum'].includes(type);if(row.querySelector('[data-unit]').disabled)row.querySelector('[data-unit]').value='';};row.querySelector('[data-type]').onchange=update;row.querySelector('[data-remove]').onclick=()=>{row.remove();invalidate();notify();};}
    add.onclick=()=>{append();invalidate();notify();};initial.forEach(append);
    const read=()=>[...rows.children].map(row=>Object.fromEntries(['key','label','section','type','unit'].map(key=>[key,row.querySelector(`[data-${key}]`).value.trim()]).concat([['value',scalarRead(row.querySelector('[data-value]'),row.querySelector('[data-type]').value)]])));
    return {read,prefill(fields){const keys=new Set([...rows.querySelectorAll('[data-key]')].map(el=>el.value));fields.forEach(field=>{if(!keys.has(field.key)){append(field);keys.add(field.key);}});notify();},metadata(){return [...rows.children].map(row=>Object.fromEntries(['key','label','section','type','unit'].map(key=>[key,row.querySelector(`[data-${key}]`).value.trim()])));}};
  }
  function actionEditor(container,kind,initial,fields) {
    return window.createActionEditor(container,{kind,initial,fields,actions:options.actions,optionMarkup,scalarMarkup,scalarRead,invalidate,esc});
  }
  function wireEditor(target,item,initial,done){return window.openWireEditor(target,item,initial,done,options.wire_presets||[],state.bindings);}
  function bindingWire(deviceId,instructionId){return state.bindings.find(b=>b.device_id===deviceId&&b.instruction_id===instructionId)?.wire;}
  function setBindings(mode,id,selected,wires=new Map()) {
    if(mode==='device_id'&&state.devices.some(d=>d.device_id===id)&&!selected.size)throw Error('设备至少需要保留一条指令，请先关联替代指令。');
    const previous=state.bindings,next=previous.filter(b=>b[mode]!==id);
    for(const other of selected){const pair=mode==='device_id'?{device_id:id,instruction_id:other}:{device_id:other,instruction_id:id};const wire=wires.get(other)||previous.find(b=>b.device_id===pair.device_id&&b.instruction_id===pair.instruction_id)?.wire||options.wire_presets?.find(p=>p.device_id===pair.device_id&&p.action===instruction(pair.instruction_id)?.action?.action&&instruction(pair.instruction_id)?.readonly)?.wire;if(!wire)throw Error('请为每台所选设备配置完整写入与读回报文。');next.push({...pair,wire});}
    const orphaned=state.instructions.filter(i=>previous.some(b=>b.instruction_id===i.instruction_id)&&!next.some(b=>b.instruction_id===i.instruction_id));
    if(orphaned.length&&!window.confirm('以下指令将没有关联设备，是否同时从草稿中删除：'+orphaned.map(i=>i.display_name).join('、')+'？'))throw Error('已取消解除关联，原配置保持不变。');
    state.bindings=next;state.instructions=state.instructions.filter(i=>!orphaned.includes(i));
  }
  function removeInstruction(id) {
    const item=state.instructions.find(i=>i.instruction_id===id);if(!item)return;
    const next=state.bindings.filter(b=>b.instruction_id!==id);
    const stranded=state.devices.filter(d=>state.bindings.some(b=>b.device_id===d.device_id&&b.instruction_id===id)&&!next.some(b=>b.device_id===d.device_id));
    if(stranded.length)throw Error('请先为以下设备关联替代指令，再删除：'+stranded.map(d=>d.display_name).join('、'));
    if(!window.confirm('从草稿中删除“'+item.display_name+'”及其设备关联？校验保存前不会改变已生效配置。'))return;
    state.bindings=next;state.instructions=state.instructions.filter(i=>i!==item);changed();
  }
  function assertBindings(d,selected) {const actions=new Set();for(const id of selected){const i=instruction(id);if(!i)throw Error('所选指令已不存在。');const reason=compatible(d,i);if(reason)throw Error(`${i.display_name}：${reason}`);const action=i.action?.action;if(actions.has(action))throw Error(`动作冲突：同一设备不能关联两条“${actionName(d.device_type,action)}”指令，请仅保留一条。`);actions.add(action);}}
  function editDevice(existing,done,seedKind) {
    const editable=!existing||state.devices.some(d=>d.device_id===existing.device_id),d=dialog(existing?(editable?'编辑设备':'查看设备与关联'):'新增设备',true);
    const body=d.querySelector('.dialog-body');const value=existing||{device_id:'',display_name:'',scenario_id:Object.keys(options.scenarios)[0],device_type:seedKind||Object.keys(options.device_types)[0],fields:[]};
    const wires=new Map();const selected=new Set(existing?state.bindings.filter(b=>b.device_id===existing.device_id).map(b=>b.instruction_id):[]);
    body.innerHTML=`<fieldset ${editable?'':'disabled'}><div class="form-grid"><label>设备编号<input data-id required pattern="SIM-[A-Z0-9]+(?:-[A-Z0-9]+)*" maxlength="48" placeholder="SIM-CUSTOM-FAN-01" title="以 SIM- 开头，使用大写字母、数字和连字符，最多 48 个字符" value="${esc(value.device_id)}" ${existing?'readonly':''}></label><label>设备名称<input data-name required minlength="2" maxlength="40" value="${esc(value.display_name)}"></label><label>所属场景<select data-scene>${optionMarkup(options.scenarios,value.scenario_id||value.scenario)}</select></label><label>设备类型<select data-kind>${optionMarkup(options.device_types,value.device_type)}</select></label></div><h3>设备初始状态</h3><p class="hint">选择指令可补齐其字段默认值，以下初始值由你确认；不会复制其他设备的实时状态。</p><div data-fields></div></fieldset><div class="section-head"><h3>选择适用指令</h3><button type="button" data-inline>＋ 新增指令</button></div><div class="relations" data-relations></div><div data-wires></div>`;
    const kind=body.querySelector('[data-kind]');if(!editable&&!options.device_types[value.device_type])kind.add(new Option(value.device_type,value.device_type));kind.value=value.device_type;
    const editor=fieldEditor(body.querySelector('[data-fields]'),editable?value.fields:fieldsOf(value));
    d.addEventListener('prefill-fields',event=>{editor.prefill(event.detail);relations();});
    function current(){return {device_id:body.querySelector('[data-id]').value.trim(),display_name:body.querySelector('[data-name]').value.trim(),scenario_id:body.querySelector('[data-scene]').value,device_type:kind.value,fields:editor.read()};}
    function relations(){const supported=Boolean(options.actions[kind.value]);const inline=body.querySelector('[data-inline]');inline.disabled=!supported;inline.title=supported?'':'此设备类型暂不支持普通指令编辑';let support=body.querySelector('[data-type-support]');if(!support){support=document.createElement('p');support.dataset.typeSupport='';support.className='hint';body.querySelector('[data-relations]').before(support);}support.textContent=supported?'':'此设备类型暂不支持新增普通指令，可在有效模板目录查看现有动作，或进入高级协议模板补充配置。';support.hidden=supported;const probe={device_type:kind.value,fields:editor.metadata()};body.querySelector('[data-relations]').innerHTML=allInstructions().map(i=>{const typeMismatch=i.device_type!==kind.value;const reason=compatible(probe,i);return `<label class="relation"><input type="checkbox" data-ref="${esc(i.instruction_id)}" ${selected.has(i.instruction_id)?'checked':''} ${typeMismatch||(!editable&&reason)?'disabled':''}>${esc(i.display_name)} · ${esc(i.action?.display_name||actionName(i.device_type,i.action?.action))}${i.readonly?'（预置）':''}<small>${esc(typeMismatch?'设备类型不一致':reason?(editable?reason+'；勾选可补齐缺少的字段，冲突字段需手动修正':reason):'字段兼容')}</small></label>`;}).join('')||`<p class="empty">${supported?'还没有可选指令，可在此新增。':'此类型暂无可复用指令，请查看有效模板目录或高级协议模板。'}</p>`;wireButtons();}
    function wireButtons(){const root=body.querySelector('[data-wires]');root.replaceChildren();for(const id of selected){const i=instruction(id);if(!i)continue;const button=document.createElement('button');button.type='button';button.textContent='配置完整报文 · '+i.display_name;button.onclick=()=>{try{wireEditor(editable?current():value,i,wires.get(id)||bindingWire(value.device_id,id),wire=>wires.set(id,wire));}catch(e){d.querySelector('.dialog-error').textContent=e.message;}};root.append(button);}}
    body.querySelector('[data-relations]').onchange=event=>{const id=event.target.dataset.ref;if(!id)return;if(event.target.checked){selected.add(id);if(editable)editor.prefill(instruction(id).fields||[]);}else selected.delete(id);relations();};
    kind.onchange=()=>{selected.clear();relations();invalidate();};body.querySelector('[data-fields]').addEventListener('fields-change',relations);
    body.querySelector('[data-inline]').onclick=()=>{try{const parent=current();if(!parent.device_id||!parent.display_name)throw Error('请先填写父设备编号和名称。');if(!existing&&[...catalog,...d._transaction.previous.devices].some(row=>row.device_id===parent.device_id))throw Error('设备编号已存在，请使用独立编号。');state.devices=state.devices.filter(row=>row.device_id!==parent.device_id);state.devices.push(parent);editInstruction(null,id=>{selected.add(id);const i=instruction(id);if(editable)editor.prefill(i.fields||[]);relations();},kind.value,parent.device_id);}catch(e){d.querySelector('.dialog-error').textContent=e.message;}};
    relations();d.querySelector('form').onsubmit=event=>{event.preventDefault();try{const row=editable?current():value;if(!row.device_id||!row.display_name)throw Error('请填写设备编号和名称。');if(!existing&&[...catalog,...d._transaction.previous.devices].some(item=>item.device_id===row.device_id))throw Error('设备编号已存在，请使用独立编号。');assertBindings(editable?row:{...value,fields:fieldsOf(value)},selected);setBindings('device_id',row.device_id,selected,wires);if(editable){state.devices=state.devices.filter(item=>item.device_id!==row.device_id);state.devices.push(row);}commitDialog(d);done?.(row.device_id);}catch(error){d.querySelector('.dialog-error').textContent=error.message;}};
  }
  function editInstruction(existing,done,seedKind,seedDevice) {
    if(!existing&&seedKind&&!options.actions[seedKind]){status('此设备类型暂不支持新增普通指令，请在有效模板目录或高级协议模板中查看配置。',true);return;}
    const readonly=Boolean(existing?.readonly),d=dialog(existing?(readonly?'预置指令与设备关联':'编辑指令'):'新增指令',true),body=d.querySelector('.dialog-body');
    const value=existing||{instruction_id:'',display_name:'',device_type:seedKind||Object.keys(options.device_types)[0],fields:[],action:null};
    const wires=new Map();const selected=new Set(existing?state.bindings.filter(b=>b.instruction_id===existing.instruction_id).map(b=>b.device_id):[]);
    if(seedDevice)selected.add(seedDevice);
    body.innerHTML=`<fieldset ${readonly?'disabled':''}><div class="form-grid"><label>指令编号<input data-id required maxlength="80" value="${esc(value.instruction_id)}" ${existing?'readonly':''}></label><label>指令名称<input data-name required maxlength="80" value="${esc(value.display_name)}"></label><label>适用设备类型<select data-kind>${optionMarkup(options.device_types,value.device_type)}</select></label></div><h3>必需状态字段与默认值</h3><p class="hint">关联设备须有相同字段名、归类、类型和单位；默认值仅用于新建设备时预填。</p><div data-fields></div><h3>动作定义</h3><div data-action-editor></div></fieldset><div class="section-head"><h3>选择适用设备（可多选）</h3><button type="button" data-inline>＋ 新建设备</button></div><div class="relations" data-relations></div><div data-wires></div>`;
    const kind=body.querySelector('[data-kind]');if(readonly&&!options.device_types[value.device_type])kind.add(new Option(value.device_type,value.device_type));kind.value=value.device_type;
    const editor=fieldEditor(body.querySelector('[data-fields]'),value.fields||[]);
    // Unsupported legacy types are displayed as an effective template, without translating protocol definitions.
    let action;
    if((options.actions[kind.value]&&value.action?.result_field!==undefined) || !existing){action=actionEditor(body.querySelector('[data-action-editor]'),kind.value,value.action,()=>editor.metadata());}
    else {body.querySelector('[data-action-editor]').innerHTML=`<pre>${esc(JSON.stringify(value.action,null,2))}</pre>`;}
    function current(){return {instruction_id:body.querySelector('[data-id]').value.trim(),display_name:body.querySelector('[data-name]').value.trim(),device_type:kind.value,fields:editor.read(),action:action?action.read():value.action};}
    function relations(){const probe=readonly?value:{...value,device_type:kind.value,fields:editor.metadata()};body.querySelector('[data-relations]').innerHTML=allDevices().map(row=>{const reason=compatible(row,probe);return `<label class="relation"><input type="checkbox" data-ref="${esc(row.device_id)}" ${selected.has(row.device_id)?'checked':''} ${reason?'disabled':''}>${esc(row.display_name)} <span class="identity">${esc(row.device_id)}</span><small>${esc(reason||'字段兼容，可关联')}</small></label>`;}).join('')||'<p class="empty">还没有设备，可在此新建。</p>';wireButtons();}
    function wireButtons(){const root=body.querySelector('[data-wires]');root.replaceChildren();for(const id of selected){const target=device(id);if(!target)continue;const button=document.createElement('button');button.type='button';button.textContent='配置完整报文 · '+target.display_name;button.onclick=()=>wireEditor(target,readonly?value:current(),wires.get(id)||bindingWire(id,value.instruction_id),wire=>wires.set(id,wire));root.append(button);}}
    body.querySelector('[data-relations]').onchange=event=>{const id=event.target.dataset.ref;if(!id)return;if(event.target.checked)selected.add(id);else selected.delete(id);wireButtons();};
    body.querySelector('[data-fields]').addEventListener('fields-change',()=>{action?.refresh();relations();});
    kind.onchange=()=>{selected.clear();action?.setKind(kind.value);relations();invalidate();};
    body.querySelector('[data-inline]').onclick=()=>{try{const currentFields=editor.read();editDevice(null,id=>{const row=device(id);const reason=compatible(row,{...value,device_type:kind.value,fields:currentFields});if(reason)d.querySelector('.dialog-error').textContent=`设备已加入草稿，但不能关联：${reason}`;else selected.add(id);relations();},kind.value);const latest=$('dialogs').lastElementChild;latest.dispatchEvent(new CustomEvent('prefill-fields',{detail:currentFields}));}catch(error){d.querySelector('.dialog-error').textContent=error.message;}};
    relations();d.querySelector('form').onsubmit=event=>{event.preventDefault();try{const row=readonly?value:current();if(!readonly&&(!row.instruction_id||!row.display_name))throw Error('请填写指令编号和名称。');if(!existing&&allInstructions().some(item=>item.instruction_id===row.instruction_id))throw Error('指令编号已存在，请更换。');if(!selected.size)throw Error('请至少选择一台设备并配置完整报文。');if(seedDevice){const parent=state.devices.find(p=>p.device_id===seedDevice);if(parent){const keys=new Set(parent.fields.map(f=>f.key));parent.fields.push(...clone(row.fields.filter(f=>!keys.has(f.key))));}}for(const id of selected){const target=device(id);const reason=compatible(target,row);if(reason)throw Error(`${target.display_name}：${reason}`);const other=state.bindings.filter(b=>b.device_id===id&&b.instruction_id!==row.instruction_id).map(b=>instruction(b.instruction_id));if(other.some(i=>i?.action?.action===row.action?.action))throw Error(`${target.display_name} 已关联相同动作的其他指令，请先解除该关联。`);}setBindings('instruction_id',row.instruction_id,selected,wires);if(!readonly){state.instructions=state.instructions.filter(item=>item.instruction_id!==row.instruction_id);state.instructions.push(row);}commitDialog(d);done?.(row.instruction_id);}catch(error){d.querySelector('.dialog-error').textContent=error.message;}};
  }
  function detail(index) {const row=catalogRows[index];if(!row)return;const d=dialog('有效模板详情');d.querySelector('.dialog-body').innerHTML=`<p>${esc(row.d.display_name)} · ${esc(row.d.device_id)}</p><p class="hint">协议点位、条件、来源及说明均来自已生效模板。请选择字段兼容的设备建立关联。</p><pre>${esc(JSON.stringify({设备:row.d.display_name,设备编号:row.d.device_id,协议:row.d.protocol,动作:row.a,有效协议点位:{...row.d.mapping,...row.t.mapping},完整模板:row.t},null,2))}</pre>`;d.querySelector('[type=submit]').textContent='查看指令与关联';d.querySelector('form').onsubmit=event=>{event.preventDefault();const i=instruction(`PRESET:${row.d.device_id}:${row.a}`);d.close();if(i)editInstruction(i);else status('此模板暂无可复用字段定义，请使用高级协议模板查看补充配置。',true);};}
  function renderReview(data,snapshot) {const affected=data.affected_devices||[];$('review').innerHTML=`<p><strong>校验通过</strong> · ${snapshot.devices.length} 台自定义设备 / ${snapshot.instructions.length} 条指令 / ${snapshot.bindings.length} 项关联</p><p>受影响设备：${esc(affected.map(row=>typeof row==='string'?row:row.display_name||row.device_id).join('、')||'详见配置')}</p><details open><summary>核对设备、指令与关联</summary><div>${snapshot.devices.map(row=>`<p><strong>${esc(row.display_name)} · ${esc(row.device_id)}</strong> · ${esc(options.scenarios[row.scenario_id])}<br>${row.fields.map(f=>`${esc(f.label)}：${esc(f.value)} ${esc(f.unit)}`).join('；')}</p>`).join('')}${snapshot.instructions.map(row=>`<p><strong>${esc(row.display_name)} · ${esc(row.instruction_id)}</strong><br>${esc(row.action.display_name||actionName(row.device_type,row.action.action))} → ${esc(row.action.result_field)} ${row.action.value_source==='fixed'?'固定值 '+esc(row.action.value):row.action.minimum==null?'':'参数 '+esc(row.action.parameter||row.action.result_field)+'，范围 '+esc(row.action.minimum)+' 至 '+esc(row.action.maximum)}<br>条件：${row.action.conditions.map(rule=>esc(`${rule.field} ${rule.operator} ${rule.value}`)).join('；')}</p>`).join('')}${snapshot.bindings.map(b=>`<p>${esc(device(b.device_id)?.display_name||b.device_id)} → ${esc(instruction(b.instruction_id)?.display_name||b.instruction_id)}</p>`).join('')}</div></details>`;}
  async function submit(publish) {if(busy||!options||publish&&!review)return;const previous=review;freeze(true);invalidate();try{const snapshot=publish?previous.state:clone(state),base=publish?previous.base_revision:baseRevision;const data=await request('/customization/'+(publish?'publish':'validate'),{state:snapshot,base_revision:base,...(publish?{revision:previous.revision}:{})});if(data.status==='invalid'){throw Error((data.errors||[]).map(e=>e.message).join('；')||'配置校验未通过。');}if(data.status!==(publish?'published':'validated'))throw Error('没有收到明确结果，请重新校验。');if(publish){dirty=false;baseRevision=data.base_revision;persist();if(data.changed===false){status('配置内容没有变化，无需保存；当前会话和候选继续有效。');}else{window.configurationEvents.published(data);status('已保存到本地。请手动刷新页面后使用新配置；其他窗口会提示更新。');}}else{review={state:snapshot,base_revision:base,revision:data.revision};renderReview(data,snapshot);status('校验通过，请核对设备初始值、动作条件和关联后确认保存。');}}catch(error){status(error.message,true);persist();}finally{freeze(false);}}
  document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>switchTab(button.dataset.tab));
  $('new-device').onclick=()=>editDevice();$('new-instruction').onclick=()=>editInstruction();$('validate').onclick=()=>submit(false);$('publish').onclick=()=>submit(true);
  $('device-list').onclick=event=>{const target=event.target.closest('[data-edit-device]');if(target)editDevice(device(target.dataset.editDevice));};
  $('instruction-list').onclick=event=>{const remove=event.target.closest('[data-delete-instruction]');if(remove){try{removeInstruction(remove.dataset.deleteInstruction);}catch(error){status(error.message,true);}return;}const target=event.target.closest('[data-edit-instruction]');if(target)editInstruction(instruction(target.dataset.editInstruction));};
  $('catalog-list').onclick=event=>{const target=event.target.closest('[data-detail]');if(target)detail(Number(target.dataset.detail));};$('catalog-search').oninput=renderCatalog;
  $('refresh').onclick=async()=>{if(busy)return;freeze(true);try{await load(dirty);status(dirty?'目录已刷新，当前草稿已保留。':'目录已刷新。');}catch(error){status(error.message,true);}finally{freeze(false);}};
  $('reload').onclick=async()=>{
    if(busy||!window.confirm('将放弃当前未保存草稿，并重新读取最新配置。需要保留的修改请先到“批量导入 / 导出”导出当前草稿备份。确认放弃并重载？'))return;
    freeze(true);
    try{await load(false);clearLegacy();status('已读取最新保存版本，可以重新编辑；如需合并旧草稿，请先核对备份再导入。');}
    catch(error){status('重新载入失败，原草稿已保留：'+error.message,true);}
    finally{freeze(false);}
  };
  $('export').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(state,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='customization-state.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  let mergeEpoch=0;const mergePanel=document.createElement('div');$('json-input').after(mergePanel);
  async function previewMerge(incoming,resolutions={}) {
    const epoch=++mergeEpoch,snapshot=clone(state),data=await request('/customization/merge-preview',{state:snapshot,incoming,base_revision:baseRevision,resolutions});
    if(epoch!==mergeEpoch)return;if(data.status==='invalid')throw Error((data.errors||[]).map(e=>e.message||e).join('；'));
    mergePanel.innerHTML=`${data.skipped_instructions?.length?'<p>以下指令因未采用该关联而不会保留：'+data.skipped_instructions.map(esc).join('、')+'</p>':''}<h3>合并预览</h3><p>新增 ${esc(data.counts?.added||0)} · 相同去重 ${esc(data.counts?.unchanged||0)} · 冲突 ${esc(data.conflicts?.length||0)}</p>`;
    for(const conflict of data.conflicts||[]) {
      const row=document.createElement('section');row.innerHTML=`<h4>${esc(conflict.kind)} · ${esc(conflict.id)}</h4><details><summary>比较当前与导入内容</summary><h5>当前</h5><pre>${esc(JSON.stringify(conflict.current,null,2))}</pre><h5>导入</h5><pre>${esc(JSON.stringify(conflict.incoming,null,2))}</pre></details><label>冲突处理<select><option value="">请选择</option><option value="current">保留当前</option><option value="incoming">采用导入</option></select></label>`;
      row.querySelector('select').value=resolutions[conflict.key]||'';row.querySelector('select').onchange=event=>{if(event.target.value)resolutions[conflict.key]=event.target.value;else delete resolutions[conflict.key];apply.disabled=true;};mergePanel.append(row);
    }
    const rerun=document.createElement('button');rerun.textContent='更新合并预览';rerun.onclick=()=>previewMerge(incoming,resolutions).catch(e=>status(e.message,true));mergePanel.append(rerun);
    const apply=document.createElement('button');apply.textContent='确认合并到草稿';apply.disabled=data.status!=='merged';apply.onclick=()=>{if(JSON.stringify(state)!==JSON.stringify(snapshot)){status('草稿已变化，请重新生成合并预览。',true);return;}state=clone(data.state);changed();mergePanel.replaceChildren();};mergePanel.append(apply);
  }
  $('import').onclick=async()=>{if(busy)return;freeze(true);try{const parsed=JSON.parse($('json-input').value.replace(/^\uFEFF/,''));await previewMerge(parsed.state||parsed);}catch(error){status('导入失败：'+error.message,true);}finally{freeze(false);}};
  function clearLegacy(){legacyReview=undefined;$('legacy-publish').disabled=true;$('legacy-review').textContent='';}
  $('json-input').oninput=()=>{invalidate();clearLegacy();mergeEpoch++;mergePanel.replaceChildren();};
  $('json-file').onchange=async event=>{const file=event.target.files[0];event.target.value='';if(!file)return;if(file.size>2*1024*1024){status('文件超过 2 MB，请减少本批内容。',true);return;}try{$('json-input').value=await file.text();invalidate();clearLegacy();mergeEpoch++;mergePanel.replaceChildren();}catch(error){status('文件读取失败：'+error.message,true);}};
  async function legacy(publish){if(busy||publish&&!legacyReview)return;const previous=legacyReview;freeze(true);clearLegacy();invalidate();try{const parsed=publish?null:JSON.parse($('json-input').value.replace(/^\uFEFF/,''));const devices=publish?previous.devices:Array.isArray(parsed)?parsed:parsed.devices;if(!Array.isArray(devices))throw Error('请提供旧风机设备数组。');const data=await request('/device-import/'+(publish?'publish':'validate'),{devices,...(publish?{revision:previous.revision}:{})});$('legacy-review').textContent=JSON.stringify(data,null,2);if(data.status==='invalid')throw Error((data.errors||[]).map(e=>e.message).join('；'));if(data.status===(publish?'published':'validated')){if(publish){persist();window.configurationEvents.published(data);status(dirty?'旧风机设备已导入，未保存草稿仍保留。请先导出备份，再手动刷新后合并。':'旧风机设备已导入，请手动刷新后使用新配置。');}else{legacyReview={devices,revision:data.revision};$('legacy-publish').disabled=false;status('旧风机文件校验通过，请核对后确认导入。');}}else throw Error('未收到明确结果。');}catch(error){status(error.message,true);}finally{freeze(false);}}
  $('legacy-validate').onclick=()=>legacy(false);$('legacy-publish').onclick=()=>legacy(true);
  switchTab(new URLSearchParams(location.search).get('tab'));
  let saved;try{
    let content=sessionStorage.getItem(storageKey);
    if(!content){content=localStorage.getItem(storageKey);if(content){sessionStorage.setItem(storageKey,content);localStorage.removeItem(storageKey);}}
    saved=JSON.parse(content||'null');
  }catch{}
  load().then(()=>{if(saved?.dirty&&saved.state){state=saved.state;baseRevision=saved.base_revision;dirty=true;render();persist();status('已恢复浏览器中的未保存草稿。请重新校验；如版本冲突，请先导出备份，再点击“放弃草稿并重载”读取最新版本后合并。');}else status('选择设备或指令开始编辑，全部修改统一校验保存。');}).catch(error=>{if(saved?.dirty&&saved.state){state=saved.state;baseRevision=saved.base_revision;dirty=true;render();}status('无法读取自定义配置：'+error.message+'。草稿已保留，可先导出备份。',true);freeze(false);});
})();
