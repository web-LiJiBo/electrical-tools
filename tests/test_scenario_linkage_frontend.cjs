/* Run with node --test tests/test_scenario_linkage_frontend.cjs. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../frontend/original-simulation.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));

test('configuration change preserves the answer while stopping old operations and new questions',async()=>{
 const app=fixture({fullPage:true});await flush();
 app.context.window.configurationEvents={isStale:()=>false,check:async()=>{}};
 app.element('query').value='查询状态';await app.element('run').onclick();
 const before=vm.runInContext('result',app.context),html=app.element('output').innerHTML;
 app.context.window.configurationEvents.isStale=()=>true;
 app.context.window.originalSimulation.configurationChanged();
 assert.equal(vm.runInContext('result',app.context),before);
 assert.equal(app.element('output').innerHTML,html);
 const count=app.requests.length;await app.element('run').onclick();
 assert.equal(app.requests.length,count);assert.equal(app.element('output').innerHTML,html);
});

test('late analysis cannot restore active operations after a configuration change',async()=>{
 const held=deferred(),app=fixture({fullPage:true,delayAnalyze:held});await flush();
 app.element('query').value='查询运行状态';
 app.context.window.configurationEvents={isStale:()=>false,check:async()=>{}};
 const waiting=app.element('run').onclick();await flush();
 app.context.window.configurationEvents.isStale=()=>true;
 app.context.window.originalSimulation.configurationChanged();held.resolve();await waiting;
 assert.equal(vm.runInContext('result',app.context),null);
 assert.equal(app.element('run').disabled,true);
});

test('answer completion releases the question button even when the state refresh is slow',async()=>{
 const app=fixture({fullPage:true});await flush();app.element('query').value='查询状态';
 const original=app.context.loadDeviceState;let release;
 app.context.loadDeviceState=()=>new Promise(r=>release=r);
 const waiting=app.element('run').onclick();await flush();
 assert.equal(app.element('run').disabled,false);release();await waiting;app.context.loadDeviceState=original;
});

test('a stalled analysis times out and allows the user to ask again',async()=>{
 const app=fixture({fullPage:true});await flush();app.element('query').value='查询状态';
 app.context.AbortSignal={timeout:()=>AbortSignal.timeout(10)};
 const fetch=app.context.fetch;
 app.context.fetch=(url,options)=>url.endsWith('/analyze')?new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(options.signal.reason))):fetch(url,options);
 await Promise.race([app.element('run').onclick(),new Promise(resolve=>setTimeout(resolve,200))]);
 assert.equal(app.element('run').disabled,false);assert.equal(app.element('status').textContent,'请求失败');
});

test('batch revalidation is bounded and stops scheduling old work after inputs change',async()=>{
 const app=fixture();await flush();app.element('query').value='启动多个风机';await app.context.window.originalSimulation.prepare({simulation_mode:true});
 app.context.result={data:{simulation_session_id:'session-all_devices',simulation_batch:{items:Array.from({length:7},(_,i)=>({device_id:'FAN-'+i,action:'start',parameters:{},preview:{status:'generated',command_id:'c'+i,expected_version:0,simulation_execution_allowed:true}}))}}};
 app.context.tab='instruction';app.context.render();let count=0;const held=[],fetch=app.context.fetch;
 app.context.fetch=async(url,opts)=>{
  if(url.endsWith('/execute'))return {ok:true,json:async()=>({status:'succeeded',explanation:'ok'})};
  if(url.endsWith('/preview')){count++;return new Promise(resolve=>held.push(()=>resolve({ok:true,json:async()=>({status:'generated',command_id:'new',expected_version:1,simulation_execution_allowed:true})})));}
  return fetch(url,opts);
 };
 const action=app.element('simulate-batch-0').onclick();await flush();assert.equal(count,3);
 app.element('query').value='另一问';for(const fn of app.element('query').listeners.input)fn();
 for(const release of held)release();await action;assert.equal(count,3);assert.equal(app.element('run').disabled,false);
});

test('same-device mixed actions display one device and two distinct instructions', async () => {
  const app = fixture();
  await flush();
  app.element('query').value = '同一设备调整有功与无功';
  await app.context.window.originalSimulation.prepare({simulation_mode:true});
  app.context.result = {status:'generated', data:{simulation_session_id:'session-all_devices', simulation_batch:{items:[
    {device_id:'SIM-MB-INVERTER-01', display_name:'新能源逆变器', action:'adjust_active_power', source_query:'有功设为120kW',
     parameters:{power_kw:120}, parameter_unit:'kW', preview:{status:'generated', command_id:'one', expected_version:0, simulation_execution_allowed:true}},
    {device_id:'SIM-MB-INVERTER-01', display_name:'新能源逆变器', action:'adjust_reactive_power', source_query:'无功设为30kvar',
     parameters:{reactive_power_kvar:30}, parameter_unit:'kvar', preview:{status:'generated', command_id:'two', expected_version:0, simulation_execution_allowed:true}}
  ]}}};
  app.context.tab = 'instruction';
  app.context.render();
  const html = app.element('output').innerHTML;
  assert.match(html, /共1台设备、2条指令/);
  assert.match(html, /有功设为120kW/);
  assert.match(html, /无功设为30kvar/);
  assert.equal(app.element('simulate-batch-0').disabled, false);
  assert.equal(app.element('simulate-batch-1').disabled, false);
});

test('multi-device cards retain blocked rows and input changes disable every command', async () => {
  const app = fixture();
  await flush();
  app.element('query').value = '启动冷却风机1和冷却风机2';
  await app.context.window.originalSimulation.prepare({simulation_mode: true});
  app.context.result = {status: 'generated', data: {simulation_session_id: 'session-all_devices',
    simulation_batch: {items: [
      {device_id: 'SIM-IEC-FAN-01', display_name: '冷却风机1', action: 'start', parameters: {},
       preview: {status: 'generated', command_id: 'one', expected_version: 0,
         simulation_execution_allowed: true, candidate: {payload: {ctlVal: true}}}},
      {device_id: 'SIM-MB-FAN-01', display_name: '冷却风机2', action: 'start', parameters: {},
       preview: {status: 'blocked', explanation: '检修闭锁', simulation_execution_allowed: false}}
    ]}}};
  app.context.tab = 'instruction';
  app.context.render();
  assert.match(app.element('output').innerHTML, /SIM-IEC-FAN-01/);
  assert.match(app.element('output').innerHTML, /SIM-MB-FAN-01/);
  assert.match(app.element('output').innerHTML, /检修闭锁/);
  assert.equal(app.element('status').textContent, '1项可预览，1项受阻/待澄清');
  assert.equal(app.element('simulate-batch-0').disabled, false);
  assert.equal(app.element('simulate-batch-1').disabled, true);
  assert.equal(app.requests.some(r => r.route.endsWith('/execute')), false);
  app.element('query').value = '其他问题';
  for (const fn of app.element('query').listeners.input) fn();
  assert.equal(app.element('simulate-batch-0').disabled, true);
});
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
};

test('failed second analysis cannot restore the previous answer on tab change', async () => {
  const app = fixture({fullPage:true}); await flush();
  app.element('query').value = '第一问'; await app.element('run').onclick();
  app.element('params').value = '{坏'; await app.element('run').onclick();
  vm.runInContext("tab='summary';render()", app.context);
  assert.doesNotMatch(app.element('output').innerHTML, /旧场景结果/);
  assert.equal(app.element('status').textContent, '请求失败');
});

test('late state snapshot cannot replace a newer response in the same scene', async () => {
  const app = fixture(); await flush();
  const held = deferred(), original = app.context.fetch;
  let count = 0;
  app.context.fetch = async (url, options) => {
    if (new URL(url).pathname === '/simulation/sessions/session-all_devices') {
      const snapshot = structuredClone(app.sessions.get('session-all_devices'));
      if (++count === 1) await held.promise;
      return {ok:true,json:async()=>snapshot};
    }
    return original(url, options);
  };
  const pending = app.context.loadDeviceState(); await flush();
  const state = app.sessions.get('session-all_devices');
  state.version = 1; state.devices[0].state.running = true;
  await app.context.loadDeviceState(); held.resolve(); await pending;
  assert.match(app.element('device-state').innerHTML, /"running":true/);
});

test('aggregate normal resets a changed child scenario', async () => {
  const app = fixture(); await flush();
  app.sessions.get('session-all_devices').scenario_conditions = {substation_maintenance:'high_temperature'};
  await app.context.window.originalSimulation.prepare({simulation_mode:true,simulation_condition:'normal'});
  assert.equal(app.requests.some(r=>r.route.endsWith('/condition')), true);
});

test('lost single-command response is unknown on both answer and operation tabs', async () => {
  const app = fixture({fullPage:true}); await flush();
  const original = app.context.fetch;
  app.context.fetch = async (url, opts) => {
    if(new URL(url).pathname.endsWith('/execute'))throw Error('connection lost');
    if(new URL(url).pathname === '/analyze')return {ok:true,json:async()=>({status:'generated',data:{
      answer:{text:'已生成预览，尚未执行'},simulation_session_id:'session-all_devices',
      simulation_preview:{status:'generated',command_id:'one',expected_version:0,simulation_execution_allowed:true}}})};
    return original(url,opts);
  };
  await app.element('run').onclick();
  vm.runInContext("tab='instruction';render()",app.context);
  await app.element('simulate-execute').onclick();
  vm.runInContext("if(globalThis.result)result=globalThis.result;tab='summary';render()",app.context);
  assert.match(app.element('output').innerHTML,/执行结果未确认/);
  assert.doesNotMatch(app.element('output').innerHTML,/尚未执行/);
  assert.equal(app.element('status').textContent,'执行结果未确认');
});

test('editing during analysis clears processing status when obsolete response returns', async () => {
  const slow = deferred(); const app=fixture({fullPage:true,delayAnalyze:slow}); await flush();
  const pending=app.element('run').onclick(); await flush();
  app.element('query').value='新问题'; slow.resolve();await pending;
  assert.equal(app.element('status').textContent,'等待重新分析');
});

function fixture({delayCreate, fullPage = false, delayAnalyze, delayLegacy, storage = new Map(), restoredSessions = new Map(), restoreError} = {}) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      value: '', checked: false, _html: '', _text: '', disabled: false,
      get innerHTML() { return this._html; },
      set innerHTML(value) { this._html = value; this._text = value; },
      get textContent() { return this._text; },
      set textContent(value) { this._text = value; this._html = value; },
      listeners: {}, addEventListener(event, fn) {
        (this.listeners[event] ||= []).push(fn);
      }, insertAdjacentHTML(_position, html) { this.innerHTML += html; },
    });
    return elements.get(id);
  }
  element('api').value = 'http://localhost:8000';
  element('simulation-mode').checked = true;
  element('params').value = '{}';
  const devices = {
    fan: {device_id: 'SIM-IEC-FAN-01', display_name: '主变冷却风机', device_type: 'cooling_fan',
      protocol: 'IEC61850', state: {running: false}, runtime_facts: {start_permission: 1}},
    inverter: {device_id: 'SIM-MB-INVERTER-01', display_name: '并网逆变器', device_type: 'inverter',
      protocol: 'Modbus', state: {active_power: 20}, runtime_facts: {power_available: 1}},
    valve: {device_id: 'SIM-IEC-VALVE-01', display_name: '调度换流阀', device_type: 'pole_controller',
      protocol: 'IEC61850', state: {power: 100}, runtime_facts: {available: 1}},
  };
  const profiles = {
    all_devices: ['fan', 'inverter', 'valve'],
    substation_maintenance: ['fan'],
    renewable_grid_integration: ['inverter'],
    power_grid_operation: ['valve'],
  };
  const sessions = restoredSessions, requests = [];
  const catalog = {simulation_only: true, dispatch_allowed: false,
    devices: Object.values(devices), device_templates: [], action_templates: [],
    scenarios: Object.keys(profiles).map(scenario_id => ({scenario_id,
      display_name: scenario_id, device_ids: profiles[scenario_id].map(key => devices[key].device_id),
      groups: {}, conditions: {normal: {}}}))};
  async function fetch(url, options = {}) {
    const payload = options.body ? JSON.parse(options.body) : undefined;
    const route = new URL(url).pathname;
    requests.push({route, payload});
    if (route === '/simulation/catalog') return response(catalog);
    if (route === '/simulation/sessions') {
      const name = payload.scenario_id || 'substation_maintenance';
      if (delayCreate?.[name]) await delayCreate[name].promise;
      const snapshot = {session_id: 'session-' + name, scenario_id: name, condition: 'normal',
        version: 0, simulation_only: true, dispatch_allowed: false,
        devices: profiles[name].map(key => structuredClone(devices[key]))};
      sessions.set(snapshot.session_id, snapshot);
      return response(snapshot);
    }
    const id = route.split('/')[3];
    if (sessions.has(id)) { if(restoreError) throw Error(restoreError); return response(sessions.get(id)); }
    if (route === '/simulation/state') {
      if (delayLegacy) await delayLegacy.promise;
      return response({devices: Object.values(devices)});
    }
    if (route === '/analyze') {
      if (delayAnalyze) await delayAnalyze.promise;
      return response({status: 'answered', data: {answer: {text: '旧场景结果'},
        simulation_session_id: payload.parameters.simulation_session_id}, warnings: []});
    }
    throw new Error('Unexpected API request: ' + route);
  }
  function response(data) { return {ok: true, json: async () => structuredClone(data)}; }
  const context = vm.createContext({document: {getElementById: element, querySelector: () => null,
      querySelectorAll: () => [], addEventListener() {}},
    window: {addEventListener() {}}, sessionStorage: {getItem:key=>storage.get(key) || null, setItem:(key,value)=>storage.set(key,value), removeItem:key=>storage.delete(key)}, fetch, AbortSignal, URL, URLSearchParams, location: {search: ''}, console,
    result: null, tab: 'summary', render() {},
    esc: value => String(value ?? ''), loadDeviceState() {},
    scenarioNames: {offshore_wind: '海上风电', substation_maintenance: '变电站设备运维'}});
  if (fullPage) {
    const html = fs.readFileSync(path.join(__dirname, '../frontend/index.html'), 'utf8');
    vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
  }
  vm.runInContext(script, context);
  async function select(name) {
    element('scenario').value = name;
    for (const fn of element('scenario').listeners.change || []) fn();
    await flush();
  }
  return {context, element, requests, sessions, select};
}

test('automatic mode displays all registered devices, not the default substation subset', async () => {
  const app = fixture();
  await flush();
  assert.match(app.element('device-state').innerHTML, /并网逆变器/);
  assert.match(app.element('device-state').innerHTML, /主变冷却风机/);
  assert.equal(app.requests.find(r => r.route === '/simulation/sessions').payload.scenario_id, 'all_devices');
});

test('changing business scenario updates devices and analysis uses the same session', async () => {
  const app = fixture();
  await flush();
  await app.select('substation_maintenance');
  assert.match(app.element('device-state').innerHTML, /主变冷却风机/);
  assert.doesNotMatch(app.element('device-state').innerHTML, /并网逆变器/);
  await app.select('renewable_grid_integration');
  assert.match(app.element('device-state').innerHTML, /并网逆变器/);
  assert.doesNotMatch(app.element('device-state').innerHTML, /主变冷却风机/);
  const prepared = await app.context.window.originalSimulation.prepare({simulation_mode: true});
  assert.equal(prepared.simulation_session_id, 'session-all_devices');
  assert.equal(prepared.simulation_scenario_id, 'renewable_grid_integration');
});

test('business and automatic views share the same device state without creating a second session', async () => {
  const app = fixture();
  await flush();
  await app.select('substation_maintenance');
  app.sessions.get('session-all_devices').devices[0].state.running = true;
  await app.select('power_grid_operation');
  assert.match(app.element('device-state').innerHTML, /调度换流阀/);
  await app.select('substation_maintenance');
  assert.match(app.element('device-state').innerHTML, /"running":true/);
  await app.select('');
  assert.match(app.element('device-state').innerHTML, /"running":true/);
  assert.equal(app.requests.filter(r => r.route === '/simulation/sessions').length, 1);
});

test('an unsupported scenario clears devices and does not silently use a substation session', async () => {
  const app = fixture();
  await flush();
  await app.select('offshore_wind');
  const panel = app.element('device-state');
  assert.match(panel.textContent, /未配置模拟设备/);
  const prepared = await app.context.window.originalSimulation.prepare({simulation_mode: true});
  assert.equal(prepared.simulation_mode, false);
  assert.equal(prepared.simulation_session_id, undefined);
});

test('a slow earlier scene request cannot replace the most recently selected scene', async () => {
  const slow = deferred();
  const app = fixture({delayCreate: {all_devices: slow}});
  await flush();
  assert.equal(app.requests.some(r => r.route === '/simulation/sessions'
    && r.payload.scenario_id === 'all_devices'), true);
  await app.select('substation_maintenance');
  slow.resolve();
  await flush();
  assert.match(app.element('device-state').innerHTML, /主变冷却风机/);
  assert.doesNotMatch(app.element('device-state').innerHTML, /并网逆变器/);
  const prepared = await app.context.window.originalSimulation.prepare({simulation_mode: true});
  assert.equal(prepared.simulation_session_id, 'session-all_devices');
  assert.equal(prepared.simulation_scenario_id, 'substation_maintenance');
});

test('an old analysis response cannot restore results after the scene changes', async () => {
  const slow = deferred();
  const app = fixture({fullPage: true, delayAnalyze: slow});
  await flush();
  app.element('query').value = '查询当前设备状态';
  const pending = app.element('run').onclick();
  await flush();
  assert.equal(app.requests.some(r => r.route === '/analyze'), true);
  await app.select('renewable_grid_integration');
  slow.resolve();
  await pending;
  assert.equal(vm.runInContext('result', app.context), null);
  assert.doesNotMatch(app.element('output').innerHTML, /旧场景结果/);
  assert.match(app.element('device-state').innerHTML, /并网逆变器/);
});

test('a legacy startup state response cannot overwrite a selected scene', async () => {
  const slow = deferred();
  const app = fixture({fullPage: true, delayLegacy: slow});
  await flush();
  await app.select('substation_maintenance');
  slow.resolve();
  await flush();
  assert.doesNotMatch(app.element('device-state').innerHTML, /逆变器/);
});

test('an explicit session for a different selected scene is rejected', async () => {
  const app = fixture();
  await flush();
  await app.select('substation_maintenance');
  await app.select('renewable_grid_integration');
  app.sessions.set('session-substation_maintenance', {...app.sessions.get('session-all_devices'),
    session_id:'session-substation_maintenance', scenario_id:'substation_maintenance'});
  await assert.rejects(app.context.window.originalSimulation.prepare({simulation_mode: true,
    simulation_session_id: 'session-substation_maintenance'}), /全设备会话/);
});

test('switching scenes clears previous results and disables the old execute button', async () => {
  const app = fixture();
  await flush();
  app.context.result = {data: {simulation_session_id: 'session-all_devices'}};
  await app.select('substation_maintenance');
  assert.equal(app.context.result, null);
  assert.equal(app.element('simulate-execute').disabled, true);
});

 test('navigation restores the same server session and its changed state', async () => {
 const storage = new Map(), restoredSessions = new Map();
 const first=fixture({storage,restoredSessions}); await flush();
 restoredSessions.get('session-all_devices').devices[0].state.running=true;
 const second=fixture({storage,restoredSessions}); await flush();
 assert.equal(second.requests.filter(r=>r.route==='/simulation/sessions').length,0);
 assert.match(second.element('device-state').innerHTML,/"running":true/);
 });

test('temporary restore failure preserves the identity and never creates another world', async () => {
 const storage = new Map(), restoredSessions = new Map();
 fixture({storage,restoredSessions}); await flush();
 const second=fixture({storage,restoredSessions,restoreError:'offline'}); await flush();
 assert.equal(storage.get('electrical-tools:simulation-session:http://localhost:8000'),'session-all_devices');
 assert.equal(second.requests.some(r=>r.route==='/simulation/sessions'),false);
 await assert.rejects(second.context.window.originalSimulation.prepare({simulation_mode:true}),/offline/);
});

test('indeterminate hypothesis is shown separately from a proven violation', async () => {
 const app=fixture({fullPage:true}); await flush();
 app.context.assessmentData={real_clause_evidence:{},device_assessment:{basis:'user_hypothesis',checks:[{parameter:'温升',actual:'<95',unit:'K',limit:78,passed:null}]}};
 const html=vm.runInContext('groundedDetail(assessmentData)',app.context);
 assert.match(html,/无法确定/); assert.match(html,/假设/);
 assert.doesNotMatch(html,/· 越限/);
});

test('operation review status and its reason are visible in processing details', async () => {
 const app=fixture({fullPage:true}); await flush();
 app.context.reviewData={processing:{source_result_status:'uncertain',decomposition_source:'model_api',advice_status:'not_requested',instruction_status:'blocked',instruction_reason:'待澄清'},operation_review:{status:'blocked',reason:'原文启动与停止不一致'}};
 const html=vm.runInContext('processingDetail(reviewData)',app.context);
 assert.match(html,/操作语义复核/); assert.match(html,/未通过/);
 assert.match(html,/原文启动与停止不一致/);
});

test('maintenance plan only exposes the first step and requires a separate next-step preview', async () => {
  const app = fixture(); await flush();
  await app.context.window.originalSimulation.prepare({simulation_mode: true});
  const plan = {plan_id:'plan-one',status:'active',next_step:1,expected_version:0,steps:[
    {device_id:'SIM-IEC-FAN-01',display_name:'风机1',action:'start',conditions:['device_fault == 0'],
      preview:{status:'generated',command_id:'first',expected_version:0,simulation_execution_allowed:true}},
    {device_id:'SIM-MB-FAN-01',display_name:'风机2',action:'start',conditions:[],preview:null}
  ]};
  app.context.result = {status:'generated',data:{simulation_session_id:'session-all_devices',simulation_plan:plan}};
  app.context.tab='instruction'; app.context.render();
  assert.match(app.element('output').innerHTML,/逐步确认/);
  assert.match(app.element('output').innerHTML,/device_fault == 0/);
  assert.equal(app.element('simulate-plan-execute-0').disabled,false);
  assert.equal(app.element('simulate-plan-execute-1').disabled,true);
  assert.equal(app.requests.some(r=>r.route.endsWith('/execute')),false);
  const original=app.context.fetch;
  app.context.fetch=async(url,opts)=>{
    const route=new URL(url).pathname;
    if(route.endsWith('/execute')) {
      plan.steps[0].execution={status:'succeeded',feedback:{status:'succeeded'},after:{version:1}};
      plan.next_step=2;plan.expected_version=1;
      return {ok:true,json:async()=>plan.steps[0].execution};
    }
    if(route.endsWith('/plans/plan-one'))return {ok:true,json:async()=>structuredClone(plan)};
    if(route.endsWith('/plans/plan-one/preview')) {
      const p={status:'generated',command_id:'second',expected_version:1,simulation_execution_allowed:true};
      plan.steps[1].preview=p;
      return {ok:true,json:async()=>p};
    }
    return original(url,opts);
  };
  await app.element('simulate-plan-execute-0').onclick();
  assert.equal(plan.steps[1].preview,null);
  assert.equal(app.element('simulate-plan-preview-1').disabled,false);
  await app.element('simulate-plan-preview-1').onclick();
  assert.equal(app.element('simulate-plan-execute-1').disabled,false);
  app.element('query').value='更改请求';
  for(const fn of app.element('query').listeners.input)fn();
  assert.equal(app.element('simulate-plan-execute-1').disabled,true);
});

test('lost plan execution response stops later steps and replaces the answer with unknown result', async () => {
  const app=fixture({fullPage:true});await flush();
  await app.context.window.originalSimulation.prepare({simulation_mode:true});
  const plan={plan_id:'plan-lost',status:'active',next_step:1,expected_version:0,steps:[
    {device_id:'SIM-IEC-FAN-01',display_name:'风机1',action:'start',conditions:[],
     preview:{status:'generated',command_id:'first',expected_version:0,simulation_execution_allowed:true}},
    {device_id:'SIM-MB-FAN-01',display_name:'风机2',action:'start',conditions:[],preview:null}]};
  app.context.planCase={status:'generated',data:{answer:{text:'已准备第1步预览，尚未执行'},simulation_session_id:'session-all_devices',simulation_plan:plan}};
  vm.runInContext("result=planCase;tab='instruction';render()",app.context);
  const original=app.context.fetch;
  app.context.fetch=async(url,opts)=>{
    if(new URL(url).pathname.endsWith('/execute'))throw Error('lost result');
    return original(url,opts);
  };
  await app.element('simulate-plan-execute-0').onclick();
  assert.equal(app.element('simulate-plan-preview-1').disabled,true);
  assert.equal(app.requests.some(r=>r.route.endsWith('/plans/plan-lost/preview')),false);
  vm.runInContext("if(globalThis.result)result=globalThis.result;tab='summary';render()",app.context);
  assert.match(app.element('output').innerHTML,/执行结果未确认/);
  assert.doesNotMatch(app.element('output').innerHTML,/尚未执行/);
});


test('answer reports mixed batch counts without claiming all commands generated', async () => {
  const app = fixture({fullPage:true}); await flush();
  app.context.result = {status:'generated',data:{answer:{text:'候选操作'},simulation_batch:{items:[
    {preview:{status:'generated',command_id:'one',expected_version:0,simulation_execution_allowed:true}},
    {preview:{status:'blocked',explanation:'缺少设备状态'}}
  ]}}};
  vm.runInContext("if(globalThis.result)result=globalThis.result;tab='summary';render()",app.context);
  assert.equal(app.element('status').textContent,'1项可预览，1项受阻/待澄清');
  assert.equal(app.element('status').className,'status warn');
  assert.match(app.element('output').innerHTML,new RegExp('1项可预览，1项受阻/待澄清'));
  assert.match(app.element('output').innerHTML,/生成指令未执行/);
});

test('sequential future steps remain drafts before their preview', async () => {
  const app = fixture({fullPage:true}); await flush();
  app.context.result = {status:'generated',data:{answer:{text:'顺序计划'},simulation_plan:{status:'active',next_step:1,steps:[{},{}]}}};
  vm.runInContext("if(globalThis.result)result=globalThis.result;tab='summary';render()",app.context);
  assert.equal(app.element('status').textContent,'0项可预览，0项受阻/待澄清，2项步骤草案待开放');
  assert.match(app.element('output').innerHTML,/前一步成功反馈后重新预览/);
  assert.doesNotMatch(app.element('status').textContent,/完成|已生成/);
});

test('applied facts have a compact answer notice and detailed understanding table', async () => {
  const app = fixture({fullPage:true}); await flush();
  app.context.result = {status:'uncertain',data:{simulation_factual:true,clarification_required:true,
    simulation_inputs:{applied:[{device_id:'FAN-01',field:'running',value:false,original_value:true,conflict:true}]}}};
  vm.runInContext("if(globalThis.result)result=globalThis.result;tab='summary';render()",app.context);
  assert.equal(app.element('status').textContent,'设备条件待澄清');
  assert.match(app.element('output').innerHTML,/本次补充已更新模拟会话；生成指令未执行/);
  assert.match(app.element('output').innerHTML,/差异及采用来源请查看“系统理解”/);
  assert.doesNotMatch(app.element('output').innerHTML,/<table/);
  assert.doesNotMatch(app.element('output').innerHTML,/可靠条款/);
  vm.runInContext("tab='decomposition';render()",app.context);
  assert.match(app.element('output').innerHTML,/本次采用的补充参数/);
  assert.match(app.element('output').innerHTML,/<table/);
});
