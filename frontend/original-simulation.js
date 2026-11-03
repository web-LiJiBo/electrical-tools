/* Simulation uses the existing analysis form and operation-advice tab. */
(() => {
  let sessionId = '', submitted = '', lastResult = null, revision = 0;
  const sessions = new Map(), creating = new Map(), catalogs = new Map();
  let validPreview = false, executing = false;
  const api = () => document.getElementById('api').value;
  const scenario = () => document.getElementById('scenario').value || 'all_devices';
  const sessionKey = () => api();
  const signature = () => JSON.stringify(['query', 'params', 'scenario', 'api'].map(id => document.getElementById(id).value)
    .concat(document.getElementById('simulation-mode').checked, revision));
  const selectedPreview = () => {
    const data = result?.data, preview = data?.simulation_preview;
    return data?.simulation_session_id && preview?.status === 'generated'
      && preview.simulation_execution_allowed === true && preview.command_id
      && Number.isInteger(preview.expected_version) ? preview : null;
  };
  async function request(path, payload, base = api()) {
    const response = await fetch(base + path, payload === undefined ? {} : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
    });
    const value = await response.json();
    if (!response.ok) throw Error(typeof value.detail === 'string' ? value.detail : '模拟请求未完成');
    return value;
  }
  async function catalog(base) {
    if (!catalogs.has(base)) {
      const pending = request('/simulation/catalog', undefined, base).catch(error => {
        catalogs.delete(base);
        throw error;
      });
      catalogs.set(base, pending);
    }
    return catalogs.get(base);
  }
  async function ensureSession() {
    const base = api(), name = scenario(), key = sessionKey();
    const available = await catalog(base);
    if (!available.scenarios.some(item => item.scenario_id === name && item.device_ids.length)) return '';
    if (sessions.has(key)) return sessions.get(key);
    if (!creating.has(key)) {
      creating.set(key, request('/simulation/sessions', {scenario_id: 'all_devices'}, base).then(snapshot => {
        sessions.set(key, snapshot.session_id);
        return snapshot.session_id;
      }).finally(() => { creating.delete(key); }));
    }
    return creating.get(key);
  }
  function invalidate() {
    validPreview = false;
    const button = document.getElementById('simulate-execute');
    if (button) button.disabled = true;
    const hint = document.getElementById('simulate-hint');
    if (hint && !executing) hint.textContent = '输入或状态已变化，请重新分析后再模拟下发。';
  }
  window.originalSimulation = {
    context: signature,
    async prepare(parameters) {
      invalidate();
      submitted = signature();
      if (!parameters.simulation_mode) return parameters;
      const current = submitted, base = api(), name = scenario(), key = sessionKey();
      const selectedSession = await ensureSession();
      if (current !== signature()) throw Error('场景或输入已变化，请重新分析。');
      if (!selectedSession) {
        const prepared = {...parameters, simulation_mode: false};
        delete prepared.simulation_session_id;
        delete prepared.simulation_condition;
        delete prepared.simulation_scenario_id;
        return prepared;
      }
      let identifier = selectedSession;
      if (parameters.simulation_session_id) {
        if (typeof parameters.simulation_session_id !== 'string') throw Error('模拟会话编号必须为文本');
        const snapshot = await request('/simulation/sessions/' + encodeURIComponent(parameters.simulation_session_id), undefined, base);
        if (snapshot.scenario_id !== 'all_devices') throw Error('页面联动需要全设备会话，请刷新页面或提供全设备会话编号。');
        identifier = snapshot.session_id;
      }
      if (current !== signature()) throw Error('场景或输入已变化，请重新分析。');
      sessions.set(key, identifier);
      sessionId = identifier;
      const prepared = {...parameters, simulation_session_id: identifier, simulation_scenario_id: name};
      if (Object.prototype.hasOwnProperty.call(prepared, 'simulation_condition')) {
        const snapshot = await request('/simulation/sessions/' + encodeURIComponent(identifier), undefined, base);
        if (current !== signature()) throw Error('场景或输入已变化，请重新分析。');
        const currentCondition = snapshot.scenario_conditions?.[name] || snapshot.condition;
        if (currentCondition !== prepared.simulation_condition) {
          await request('/simulation/sessions/' + encodeURIComponent(identifier) + '/condition', {
            condition: prepared.simulation_condition, scenario_id: name
          }, base);
        }
        delete prepared.simulation_condition;
      }
      if (current !== signature()) throw Error('场景或输入已变化，请重新分析。');
      return prepared;
    }
  };
  const labels = {transformer: '变压器', breaker: '断路器', cooling_fan: '冷却风机',
    oil_pump: '油泵', disconnector: '隔离开关', earthing_switch: '接地开关',
    tap_changer: '有载调压装置', inverter: '逆变器', pole_controller: '换流阀控制器'};
  loadDeviceState = async function () {
    const current = revision, key = sessionKey(), base = api();
    const panel = document.getElementById('device-state');
    const isCurrent = () => current === revision && key === sessionKey();
    if (!document.getElementById('simulation-mode').checked) {
      panel.textContent = '模拟模式未开启，当前查询不使用模拟设备状态。';
      return;
    }
    panel.textContent = '正在读取当前场景的模拟设备…';
    try {
      const identifier = await ensureSession();
      if (!isCurrent()) return;
      if (!identifier) {
        sessionId = '';
        panel.textContent = '当前业务场景未配置模拟设备，可继续进行标准知识查询。';
        return;
      }
      const snapshot = await request('/simulation/sessions/' + encodeURIComponent(identifier), undefined, base);
      if (!isCurrent()) return;
      sessionId = identifier;
      const available = await catalog(base);
      if (!isCurrent()) return;
      const ids = new Set(available.scenarios.find(item => item.scenario_id === scenario()).device_ids);
      const devices = snapshot.devices.filter(device => ids.has(device.device_id));
      panel.innerHTML = `<p class="hint">当前场景共有 ${devices.length} 台模拟设备，状态与自动选择同步。</p>` + devices.map(device => {
        const name = device.display_name || labels[device.device_type] || device.device_type;
        return `<div class="rule"><strong>${esc(name)}</strong> · ${esc(device.protocol)}<br><code>${esc(device.device_id)}<br>${esc(JSON.stringify(device.state))}<br>${esc(JSON.stringify(device.runtime_facts))}</code></div>`;
      }).join('');
    } catch (error) {
      if (isCurrent()) panel.textContent = '无法读取模拟状态：' + error.message;
    }
  };
  function feedbackHtml(execution) {
    const names = {succeeded: '模拟下发完成', blocked: '模拟下发被阻止', failed: '模拟下发失败'};
    const before = execution.before?.devices?.find(d => d.device_id === execution.target);
    const after = execution.after?.devices?.find(d => d.device_id === execution.target);
    return `<div id="simulation-result" class="section"><h3>${esc(names[execution.status] || '模拟请求未完成')}</h3><p>${esc(execution.explanation || '')}</p>${before && after ? `<dl class="kv"><dt>执行前状态</dt><dd><code>${esc(JSON.stringify(before.state))}</code></dd><dt>执行后状态</dt><dd><code>${esc(JSON.stringify(after.state))}</code></dd><dt>模拟反馈</dt><dd>${esc(execution.feedback?.explanation || '无')}</dd></dl>` : ''}</div>`;
  }
  const originalRender = render;
  render = function () {
    if (result !== lastResult) {
      lastResult = result;
      validPreview = Boolean(selectedPreview()) && signature() === submitted;
    }
    if (result?.data?.simulation_preview && result.data.answer?.text) {
      result.data.answer.text = result.data.answer.text.replace('模拟工作台', '“操作建议”');
    }
    originalRender();
    const data = result?.data;
    if (tab !== 'instruction' || !data?.simulation_preview) return;
    const preview = selectedPreview();
    const scope = document.querySelector('#output .kv dd:last-child');
    if (scope) scope.textContent = data.simulation_execution ? '模拟执行结果；真实设备下发关闭' : '仅预览；尚未模拟下发';
    document.getElementById('output').insertAdjacentHTML('beforeend',
      `<div class="section"><button id="simulate-execute" class="primary" ${!preview || !validPreview || executing || data.simulation_execution ? 'disabled' : ''}>${executing ? '正在模拟下发…' : '模拟下发'}</button><p id="simulate-hint" class="hint">${data.simulation_execution ? '本条指令已处理，再次操作请重新分析。' : validPreview ? '仅点击此按钮才更新当前模拟设备状态。' : '请重新分析，获取当前输入和状态对应的有效预览。'}</p></div>`
      + (data.simulation_execution ? feedbackHtml(data.simulation_execution) : ''));
    document.getElementById('simulate-execute').onclick = async () => {
      if (executing || !validPreview || !preview || signature() !== submitted || result !== lastResult) return;
      const currentResult = result;
      executing = true;
      validPreview = false;
      document.getElementById('run').disabled = true;
      render();
      try {
        const execution = await request('/simulation/sessions/' + encodeURIComponent(data.simulation_session_id) + '/execute', {
          command_id: preview.command_id, expected_version: preview.expected_version
        });
        data.simulation_execution = execution;
        data.answer = {...data.answer, text: (execution.status === 'succeeded' ? '模拟下发已完成。' : '模拟下发未完成。') + execution.explanation};
        await loadDeviceState();
      } catch (error) {
        data.simulation_execution = {status: 'failed', explanation: '请求未确认，请查询当前状态：' + error.message};
      } finally {
        executing = false;
        document.getElementById('run').disabled = false;
        if (result === currentResult) render();
      }
    };
  };
  for (const id of ['query', 'params', 'scenario', 'simulation-mode']) {
    document.getElementById(id).addEventListener('input', invalidate);
    document.getElementById(id).addEventListener('change', invalidate);
  }
  function changeContext() {
    revision += 1;
    invalidate();
    sessionId = '';
    result = null;
    lastResult = null;
    document.getElementById('status').textContent = '等待分析';
    document.getElementById('status').className = 'status';
    document.getElementById('output').innerHTML = '<div class="empty">场景或模拟模式已切换，请重新分析问题。</div>';
    loadDeviceState();
  }
  for (const id of ['scenario', 'simulation-mode', 'api']) {
    document.getElementById(id).addEventListener('change', changeContext);
  }
  // A state seed is not an executed command. Nothing calls execute on load/query.
  loadDeviceState();
})();
