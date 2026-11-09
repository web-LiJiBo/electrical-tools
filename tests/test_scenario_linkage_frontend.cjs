/* Run with node --test tests/test_scenario_linkage_frontend.cjs. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../frontend/original-simulation.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));

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
  assert.equal(app.element('status').textContent, '部分指令可用');
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

function fixture({delayCreate, fullPage = false, delayAnalyze, delayLegacy} = {}) {
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
  const sessions = new Map(), requests = [];
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
    if (sessions.has(id)) return response(sessions.get(id));
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
      querySelectorAll: () => []},
    window: {}, fetch, URL, URLSearchParams, location: {search: ''}, console,
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
