/* Simulation uses the existing analysis form and operation-advice tab. */
(() => {
  let sessionId = '', submitted = '', lastResult = null, revision = 0;
  const sessions = new Map(), creating = new Map(), catalogs = new Map();
  let validPreview = false, executing = false, stateRequest = 0;
  const stateVersions = new Map();
  const api = () => document.getElementById('api').value;
  const scenario = () => document.getElementById('scenario').value || 'all_devices';
  const sessionKey = () => api();
  const storageKey = base => 'electrical-tools:simulation-session:' + base;
  function remember(base, identifier) {
    sessions.set(base, identifier);
    try { sessionStorage.setItem(storageKey(base), identifier); } catch (_) { /* Storage can be disabled. */ }
  }
  async function restore(base) {
    let identifier;
    try { identifier = sessionStorage.getItem(storageKey(base)); } catch (_) { return ''; }
    if (!identifier) return '';
    try {
      const snapshot = await request('/simulation/sessions/' + encodeURIComponent(identifier), undefined, base);
      if (snapshot.scenario_id !== 'all_devices' || snapshot.session_id !== identifier) throw Error('已保存的模拟会话类型不匹配，请明确重新建立会话。');
      remember(base, identifier);
      return identifier;
    } catch (error) {
      if (error.status !== 404) throw error;
      try { sessionStorage.removeItem(storageKey(base)); } catch (_) {}
      return '';
    }
  }
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
    if (!response.ok) { const error = Error(typeof value.detail === 'string' ? value.detail : '模拟请求未完成'); error.status = response.status; throw error; }
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
      creating.set(key, (async () => {
        const restored = await restore(base);
        if (restored) return restored;
        const snapshot = await request('/simulation/sessions', {scenario_id: 'all_devices'}, base);
        remember(key, snapshot.session_id);
        return snapshot.session_id;
      })().finally(() => { creating.delete(key); }));
    }
    return creating.get(key);
  }
  function invalidate() {
    validPreview = false;
    for (const [index] of (lastResult?.data?.simulation_plan?.steps || []).entries()) {
      for (const kind of ['execute', 'preview']) {
        const planButton = document.getElementById('simulate-plan-' + kind + '-' + index);
        if (planButton) planButton.disabled = true;
      }
    }
    for (const [index] of (lastResult?.data?.simulation_batch?.items || []).entries()) {
      const batchButton = document.getElementById('simulate-batch-' + index);
      if (batchButton) batchButton.disabled = true;
    }
    const button = document.getElementById('simulate-execute');
    if (button) button.disabled = true;
    const hint = document.getElementById('simulate-hint');
    if (hint && !executing) hint.textContent = '输入或状态已变化，请重新分析后再模拟下发。';
  }
  window.originalSimulation = {
    invalidate,
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
      remember(key, identifier);
      sessionId = identifier;
      const prepared = {...parameters, simulation_session_id: identifier, simulation_scenario_id: name};
      if (Object.prototype.hasOwnProperty.call(prepared, 'simulation_condition')) {
        const snapshot = await request('/simulation/sessions/' + encodeURIComponent(identifier), undefined, base);
        if (current !== signature()) throw Error('场景或输入已变化，请重新分析。');
        const currentCondition = snapshot.scenario_conditions?.[name] || snapshot.condition;
        const childChanged = name === 'all_devices' && Object.values(snapshot.scenario_conditions || {})
          .some(condition => condition !== prepared.simulation_condition);
        if (currentCondition !== prepared.simulation_condition || childChanged) {
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
    const current = revision, key = sessionKey(), base = api(), sequence = ++stateRequest;
    const panel = document.getElementById('device-state');
    const isCurrent = () => current === revision && key === sessionKey() && sequence === stateRequest;
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
      const versionKey = JSON.stringify([base, identifier]);
      if (Number.isInteger(snapshot.version)) {
        if (snapshot.version < (stateVersions.get(versionKey) ?? -1)) return;
        stateVersions.set(versionKey, snapshot.version);
      }
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
  function feedbackHtml(execution, id = 'simulation-result') {
    const names = {succeeded: '模拟下发完成', blocked: '模拟下发被阻止', failed: '模拟下发失败', unknown: '执行结果未确认'};
    const before = execution.before?.devices?.find(d => d.device_id === execution.target);
    const after = execution.after?.devices?.find(d => d.device_id === execution.target);
    return `<div id="${id}" class="section"><h3>${esc(names[execution.status] || '模拟请求未完成')}</h3><p>${esc(execution.explanation || '')}</p>${before && after ? `<dl class="kv"><dt>执行前状态</dt><dd><code>${esc(JSON.stringify(before.state))}</code></dd><dt>执行后状态</dt><dd><code>${esc(JSON.stringify(after.state))}</code></dd><dt>模拟反馈</dt><dd>${esc(execution.feedback?.explanation || '无')}</dd></dl>` : ''}</div>`;
  }
  const originalRender = render;
  const usable = p => p?.status === 'generated' && p.simulation_execution_allowed === true
    && p.command_id && Number.isInteger(p.expected_version);
  function batchProgress(data) {
    const rows = data.simulation_batch.items;
    const done = rows.filter(row => row.execution?.status === 'succeeded').length;
    const pending = rows.filter(row => !row.execution && usable(row.preview)).length;
    const deviceCount = new Set(rows.map(row => row.device_id)).size;
    return `共${deviceCount}台设备、${rows.length}条指令：${done}条模拟下发完成，${pending}条待逐条确认，其余请查看各条反馈。`
      + (data.simulation_batch.execution_unknown ? '存在结果未确认的请求，请查询设备状态并重新分析。' : '未点击的指令不会自动执行。');
  }
  function renderBatch(data) {
    const rows = data.simulation_batch.items;
    document.getElementById('output').innerHTML = `<div class="answer-box"><div class="answer-label">多指令预览 · 逐条确认</div><p class="answer">${esc(batchProgress(data))}</p></div>`
      + rows.map((row, index) => {
        const preview = row.preview, candidate = preview?.candidate;
        const state = row.execution ? {succeeded: '已执行', blocked: '执行被阻止', failed: '执行失败', unknown: '执行结果未确认'}[row.execution.status]
          : usable(preview) ? '待确认' : '已阻断';
        return `<section class="rule" style="margin:16px 0;padding:18px;border:1px solid #dbe4e1;border-radius:6px"><h3>${index + 1}. ${esc(row.display_name)} · ${esc(state || '请核对反馈')}</h3><p><code>${esc(row.device_id)}</code> · ${esc(row.protocol)} · ${esc(row.action_name || row.action || '无匹配动作')}</p>`
          + (row.source_query ? `<p class="hint">对应请求：${esc(row.source_query)}</p>` : '')
          + `<p>${esc(row.execution?.explanation || preview?.explanation || '请核对预览')}</p><p>动作参数：${Object.keys(row.parameters || {}).length ? esc(Object.values(row.parameters).map(value => String(value) + (row.parameter_unit || candidate?.payload?.unit || '')).join('、')) : '无需额外参数'}</p>`
          + `<details style="margin:12px 0"><summary>查看协议载荷与联锁校验</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(JSON.stringify({payload: candidate?.payload || {}, checks: candidate?.precondition_trace || []}, null, 2))}</pre></details>`
          + `<button id="simulate-batch-${index}" class="primary">${executing ? '正在处理…' : '模拟下发本条'}</button><p class="hint">${esc(row.execution ? '本条已处理；再次操作请重新分析。' : row.preview_notice || '仅此按钮执行本条模拟指令；不会自动执行其他设备。')}</p>`
          + (row.execution ? feedbackHtml(row.execution, 'simulation-result-' + index) : '') + '</section>';
      }).join('');
    rows.forEach((row, index) => {
      const button = document.getElementById('simulate-batch-' + index);
      button.disabled = !validPreview || executing || Boolean(row.execution) || !usable(row.preview);
      button.onclick = async () => {
        if (button.disabled || executing || !validPreview || signature() !== submitted || result !== lastResult) return;
        const currentResult = result, current = signature(), base = api(), preview = row.preview;
        executing = true;
        document.getElementById('run').disabled = true;
        render();
        try {
          row.execution = await request('/simulation/sessions/' + encodeURIComponent(data.simulation_session_id) + '/execute',
            {command_id: preview.command_id, expected_version: preview.expected_version}, base);
          // Successful or blocked commands are immutable. Only pending items get
          // a NEW preview against current state, never an automatic execution.
          if (result === currentResult && signature() === current) {
            for (const pending of rows.filter(item => !item.execution && usable(item.preview))) {
              try {
                pending.preview = await request('/simulation/sessions/' + encodeURIComponent(data.simulation_session_id) + '/preview',
                  {device_id: pending.device_id, action: pending.action, parameters: pending.parameters}, base);
                pending.preview_notice = '已按最新设备状态重新校验，请再次核对后下发本条。';
              } catch (error) {
                pending.preview = {status: 'blocked', explanation: '重新校验未完成：' + error.message};
              }
            }
            await loadDeviceState();
          }
        } catch (error) {
          row.execution = {status: 'unknown', explanation: '请求结果未确认，请查询设备状态：' + error.message};
          data.simulation_batch.execution_unknown = true;
          validPreview = false;
        } finally {
          data.answer = {...data.answer, text: batchProgress(data)};
          executing = false;
          document.getElementById('run').disabled = false;
          if (result === currentResult) render();
        }
      };
    });
  }
  function renderPlan(data) {
    const plan = data.simulation_plan;
    const stopped = plan.status === 'stopped' || plan.execution_unknown;
    const progress = plan.execution_unknown ? '执行结果未确认，计划停止；请核对设备状态并重新分析。'
      : plan.status === 'completed' ? '所有步骤已取得成功模拟反馈。'
      : stopped ? '计划已停止：' + (plan.stop_reason || '请核对当前条件')
      : `共${plan.steps.length}步，当前开放第${plan.next_step}步。前一步成功反馈后才可预览下一步；每一步分别确认。`;
    document.getElementById('output').innerHTML = `<div class="answer-box"><div class="answer-label">顺序计划 · 逐步确认</div><p class="answer">${esc(progress)}</p></div>`
      + plan.steps.map((row, index) => {
        const preview = row.preview, candidate = preview?.candidate;
        const state = row.execution ? {succeeded:'已取得成功反馈',failed:'执行失败',blocked:'执行被阻止',unknown:'结果未确认'}[row.execution.status]
          : usable(preview) ? '等待本步确认' : index + 1 === plan.next_step && !stopped ? '等待预览' : '尚未开放';
        return `<section class="rule" style="margin:16px 0;padding:18px;border:1px solid #dbe4e1;border-radius:6px"><h3>${index + 1}. ${esc(row.display_name || row.device_id)} · ${esc(state || '')}</h3>`
          + `<p><code>${esc(row.device_id)}</code> · ${esc(row.action_name || row.action)}</p>`
          + (row.source_query ? `<p class="hint">对应请求：${esc(row.source_query)}</p>` : '')
          + `<p>执行条件：${esc((row.conditions || []).join(' 且 ') || '无附加用户条件')}。将在预览和执行前重新核验。</p>`
          + `<p>${esc(row.execution?.explanation || preview?.explanation || '等待前一步成功反馈')}</p>`
          + `<details><summary>查看本步参数与校验</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(JSON.stringify({parameters:row.parameters || {},payload:candidate?.payload || {},conditions:preview?.condition_checks || row.condition_checks || [],checks:preview?.relation_checks || []},null,2))}</pre></details>`
          + `<button id="simulate-plan-preview-${index}" class="primary">预览第${index + 1}步</button> <button id="simulate-plan-execute-${index}" class="primary">确认模拟下发第${index + 1}步</button>`
          + (row.execution ? feedbackHtml(row.execution,'simulation-plan-result-' + index) : '') + '</section>';
      }).join('');
    const route = '/simulation/sessions/' + encodeURIComponent(data.simulation_session_id) + '/plans/' + encodeURIComponent(plan.plan_id);
    async function act(index, execute) {
      if (executing || !validPreview || signature() !== submitted || result !== lastResult) return;
      const row = plan.steps[index], currentResult = result, current = signature(), base = api();
      if (stopped || plan.status !== 'active' || plan.next_step !== index + 1 || row.execution) return;
      if (execute && !usable(row.preview)) return;
      executing = true;
      document.getElementById('run').disabled = true;
      render();
      try {
        if (execute) {
          row.execution = await request('/simulation/sessions/' + encodeURIComponent(data.simulation_session_id) + '/execute',
            {command_id:row.preview.command_id,expected_version:row.preview.expected_version},base);
        } else {
          row.preview = await request(route + '/preview',{step:index + 1,expected_version:plan.expected_version},base);
        }
        // Reading progress never previews or executes any further step.
        const latest = await request(route,undefined,base);
        if (result === currentResult && signature() === current) {
          data.simulation_plan = latest;
          await loadDeviceState();
        }
      } catch (error) {
        if (execute) row.execution = {status:'unknown',explanation:'请求结果未确认，请查询设备状态：' + error.message};
        plan.execution_unknown = execute;
        plan.status = 'stopped';
        plan.stop_reason = execute ? '执行结果未确认，禁止继续后续步骤。' : '步骤预览未完成：' + error.message;
        validPreview = false;
      } finally {
        const latest = data.simulation_plan;
        const text = latest.execution_unknown ? '执行结果未确认，计划已停止；请查询设备状态并重新分析。'
          : latest.status === 'completed' ? '所有步骤已完成并取得成功模拟反馈。'
          : latest.status === 'stopped' ? '计划已停止：' + (latest.stop_reason || '请核对当前状态。')
          : `当前开放第${latest.next_step}步，请先预览并单独确认；后续步骤不会自动执行。`;
        data.answer = {...data.answer,text};
        executing = false;
        document.getElementById('run').disabled = false;
        if (result === currentResult) render();
      }
    }
    plan.steps.forEach((row,index) => {
      const canOpen = validPreview && !executing && !stopped && plan.status === 'active'
        && plan.next_step === index + 1 && !row.execution;
      const previewButton = document.getElementById('simulate-plan-preview-' + index);
      const executeButton = document.getElementById('simulate-plan-execute-' + index);
      previewButton.disabled = !canOpen || usable(row.preview);
      executeButton.disabled = !canOpen || !usable(row.preview);
      previewButton.onclick = () => { if (!previewButton.disabled) return act(index,false); };
      executeButton.onclick = () => { if (!executeButton.disabled) return act(index,true); };
    });
  }
  render = function () {
    if (result !== lastResult) {
      lastResult = result;
      validPreview = (Boolean(selectedPreview()) || result?.data?.simulation_batch?.items?.some(row => usable(row.preview))
        || result?.data?.simulation_plan?.status === 'active')
        && signature() === submitted;
    }
    if (result?.data?.simulation_preview && result.data.answer?.text) {
      result.data.answer.text = result.data.answer.text.replace('模拟工作台', '“操作建议”');
    }
    originalRender();
    const data = result?.data;
    if (data?.simulation_plan) {
      const plan = data.simulation_plan;
      document.getElementById('status').textContent = plan.execution_unknown ? '执行结果未确认'
        : plan.status === 'completed' ? '计划模拟完成' : plan.status === 'stopped' ? '计划已停止' : '逐步确认计划';
      document.getElementById('status').className = 'status ' + (plan.status === 'stopped' ? 'warn' : 'ok');
      if (tab === 'instruction') { renderPlan(data); return; }
    }
    if (data?.simulation_batch) {
      const rows = data.simulation_batch.items;
      const blocked = rows.some(row => !usable(row.preview));
      const status = data.simulation_batch.execution_unknown ? '执行结果未确认'
        : rows.every(row => row.execution?.status === 'succeeded') ? '模拟下发完成'
        : rows.some(row => row.execution) ? '部分指令已处理'
        : rows.every(row => !usable(row.preview)) ? '指令均被阻止'
        : blocked ? '部分指令可用' : '指令已生成';
      document.getElementById('status').textContent = status;
      document.getElementById('status').className = 'status ' + (blocked || data.simulation_batch.execution_unknown ? 'warn' : 'ok');
    }
    if (data?.simulation_execution?.status === 'unknown') {
      document.getElementById('status').textContent = '执行结果未确认';
      document.getElementById('status').className = 'status warn';
    }
    if (tab === 'instruction' && data?.simulation_batch) {
      renderBatch(data);
      return;
    }
    if (tab !== 'instruction' || !data?.simulation_preview) return;
    const preview = selectedPreview();
    const scope = document.querySelector('#output > .kv dd:last-child');
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
        data.simulation_execution = {status: 'unknown', explanation: '执行结果未确认，请查询当前状态并重新分析：' + error.message};
        data.answer = {...data.answer, text: data.simulation_execution.explanation};
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
