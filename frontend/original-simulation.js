/* Simulation uses the existing analysis form and operation-advice tab. */
(() => {
  let sessionId = '', creating = null, submitted = '', lastResult = null;
  let validPreview = false, executing = false;
  const api = () => document.getElementById('api').value;
  const signature = () => JSON.stringify(['query', 'params', 'scenario'].map(id => document.getElementById(id).value)
    .concat(document.getElementById('simulation-mode').checked));
  const selectedPreview = () => {
    const data = result?.data, preview = data?.simulation_preview;
    return data?.simulation_session_id && preview?.status === 'generated'
      && preview.simulation_execution_allowed === true && preview.command_id
      && Number.isInteger(preview.expected_version) ? preview : null;
  };
  async function request(path, payload) {
    const response = await fetch(api() + path, payload === undefined ? {} : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
    });
    const value = await response.json();
    if (!response.ok) throw Error(typeof value.detail === 'string' ? value.detail : '模拟请求未完成');
    return value;
  }
  async function ensureSession() {
    if (sessionId) return sessionId;
    if (!creating) creating = request('/simulation/sessions', {}).then(snapshot => {
      if (!sessionId) sessionId = snapshot.session_id;
      return sessionId;
    }).finally(() => { creating = null; });
    return creating;
  }
  function invalidate() {
    validPreview = false;
    const button = document.getElementById('simulate-execute');
    if (button) button.disabled = true;
    const hint = document.getElementById('simulate-hint');
    if (hint && !executing) hint.textContent = '输入或状态已变化，请重新分析后再模拟下发。';
  }
  window.originalSimulation = {
    async prepare(parameters) {
      invalidate();
      submitted = signature();
      if (!parameters.simulation_mode) return parameters;
      if (parameters.simulation_session_id) {
        if (typeof parameters.simulation_session_id !== 'string') throw Error('模拟会话编号必须为文本');
        sessionId = parameters.simulation_session_id;
      } else await ensureSession();
      const prepared = {...parameters, simulation_session_id: sessionId};
      if (Object.prototype.hasOwnProperty.call(prepared, 'simulation_condition')) {
        const snapshot = await request('/simulation/sessions/' + encodeURIComponent(sessionId));
        if (snapshot.condition !== prepared.simulation_condition) {
          await request('/simulation/sessions/' + encodeURIComponent(sessionId) + '/condition', {
            condition: prepared.simulation_condition
          });
        }
        delete prepared.simulation_condition;
      }
      return prepared;
    }
  };
  const labels = {transformer: '变压器', breaker: '断路器', cooling_fan: '冷却风机',
    oil_pump: '油泵', disconnector: '隔离开关', earthing_switch: '接地开关',
    tap_changer: '有载调压装置', inverter: '逆变器', pole_controller: '换流阀控制器'};
  loadDeviceState = async function () {
    try {
      const path = sessionId && document.getElementById('simulation-mode').checked
        ? '/simulation/sessions/' + encodeURIComponent(sessionId) : '/simulation/state';
      const snapshot = await request(path);
      document.getElementById('device-state').innerHTML = snapshot.devices.map(device => {
        const name = device.display_name || labels[device.device_type] || device.device_type;
        return `<div class="rule"><strong>${esc(name)}</strong> · ${esc(device.protocol)}<br><code>${esc(device.device_id)}<br>${esc(JSON.stringify(device.state))}<br>${esc(JSON.stringify(device.runtime_facts))}</code></div>`;
      }).join('');
    } catch (error) {
      document.getElementById('device-state').textContent = '无法读取模拟状态：' + error.message;
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
      if (result?.data?.simulation_session_id) sessionId = result.data.simulation_session_id;
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
  // A state seed is not an executed command. Nothing calls execute on load/query.
  ensureSession().then(() => loadDeviceState()).catch(() => {});
})();
