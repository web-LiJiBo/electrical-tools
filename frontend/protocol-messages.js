/* Offline message files from an existing reviewed preview. No dispatch API. */
(() => {
  let owner = null;
  const forms = new Map();
  const el = id => document.getElementById(id);
  const current = () => window.originalSimulation.isPreviewCurrent();
  const field = (key, label, kind = 'text', choices) => ({key, label, kind, choices});
  const common = [field('host', '目标IP或主机名'), field('port', '目标端口', 'number')];
  const modbus = [field('unit_id', '单元标识（0～255，按设备定义）', 'number'), field('transaction_id', '事务编号', 'number'),
    field('address', '点位地址（从0计数）', 'number'),
    field('function_code', '写入功能', 'select', [[5, '05 · 写单线圈'], [6, '06 · 写单寄存器'], [16, '16（0x10）· 写多寄存器']]),
    field('data_type', '点位数据类型', 'select', ['bool', 'uint16', 'int16', 'uint32', 'int32', 'float32']),
    field('scale', '工程值转寄存器倍率', 'number'),
    field('byte_order', '寄存器内字节序', 'select', [['big', '高字节在前'], ['little', '低字节在前']]),
    field('word_order', '32位数值字序', 'select', [['big', '高字在前'], ['little', '低字在前']])];
  const iec = [field('domain_id', '逻辑设备MMS域（domain）'), field('item_id', '控制点位（LN$CO$对象$Oper）'),
    field('control_model', '实际控制模型', 'select', [
      ['direct-with-normal-security', '直接控制 · 常规安全'], ['direct-with-enhanced-security', '直接控制 · 增强安全'],
      ['sbo-with-normal-security', '先选择后操作 · 常规安全'], ['sbo-with-enhanced-security', '先选择后操作 · 增强安全']]),
    field('data_type', 'ctlVal数据类型', 'select', ['bool', 'int16', 'int32', 'uint16', 'uint32', 'float32']),
    field('value_shape', 'ctlVal结构', 'select', [['primitive', '原始值'], ['analogue', 'AnalogueValue结构']]),
    field('origin_ident', '操作来源标识'), field('timestamp_utc', '控制时间（ISO8601，含时区）')];
  const advanced = [field('invoke_id', 'MMS调用编号', 'number'), field('presentation_context_id', '已协商表示层上下文编号', 'number'),
    field('max_tpdu_size', '已协商最大TPDU字节数', 'number'), field('origin_category', '来源类别（0～8）', 'number'),
    field('include_ctl_num', '设备Oper结构包含ctlNum', 'checkbox'), field('ctl_num', '控制序号（0～255）', 'number'),
    field('include_oper_time', '设备Oper结构包含operTm', 'checkbox'), field('oper_time_utc', '计划操作时间（含时区）'),
    field('time_quality', '时间质量字节（默认32：未同步）', 'number'), field('test', '测试标志Test', 'checkbox'),
    field('synchro_check', '请求同期检查', 'checkbox'), field('interlock_check', '请求联锁检查', 'checkbox'),
    field('control_cancel_supported', '模拟对象已配置取消服务', 'checkbox'), field('selection_timeout_ms', '选择有效期（毫秒）', 'number')];
  function entries(data) {
    const usable = p => p?.status === 'generated' && p.simulation_execution_allowed === true
      && p.command_id && Number.isInteger(p.expected_version);
    const plan = data.simulation_plan;
    if (plan) return plan.status === 'active' && !plan.execution_unknown ? plan.steps.flatMap((row, i) =>
      !row.execution && plan.next_step === i + 1 && usable(row.preview)
        ? [{preview: row.preview, anchor: 'simulate-plan-execute-' + i}] : []) : [];
    if (data.simulation_batch) return data.simulation_batch.execution_unknown ? [] : data.simulation_batch.items.flatMap((row, i) =>
      !row.execution && usable(row.preview) ? [{preview: row.preview, anchor: 'simulate-batch-' + i}] : []);
    return !data.simulation_execution && usable(data.simulation_preview) ? [{preview: data.simulation_preview, anchor: 'simulate-execute'}] : [];
  }
  function inputHtml(f, value) {
    if (f.kind === 'checkbox') return `<label class="packet-check"><input data-key="${f.key}" type="checkbox" ${value ? 'checked' : ''}> ${esc(f.label)}</label>`;
    let input;
    if (f.kind === 'select') {
      const options = f.choices.map(v => Array.isArray(v) ? v : [v, v]);
      if (!options.some(v => String(v[0]) === String(value))) options.unshift([value, value + '（暂不支持）']);
      input = `<select data-key="${f.key}">${options.map(([v, label]) => `<option value="${esc(v)}" ${String(v) === String(value) ? 'selected' : ''}>${esc(label)}</option>`).join('')}</select>`;
    } else input = `<input data-key="${f.key}" type="${f.kind}" ${f.kind === 'number' ? 'step="any"' : ''} value="${esc(value ?? '')}" autocomplete="off">`;
    return `<label>${esc(f.label)}${input}</label>`;
  }
  async function request(path, payload, base) {
    const response = await fetch(base + path, {signal:AbortSignal.timeout(30000), ...(payload === undefined ? {} : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
    })});
    const value = await response.json();
    if (!response.ok) throw Error(typeof value.detail === 'string' ? value.detail : '报文参数校验未通过');
    return value;
  }
  function renderForm(root, state, live) {
    state.root=root;
    root.innerHTML = `<h3>生成完整协议请求包</h3><p class="hint">自动读取模拟设备配置。只生成和下载，不连接、不发送；后续阶段需要取得对端成功响应后才能继续。</p>`;
    const p = state.parameters;
    if (!p) {
      root.insertAdjacentHTML('beforeend', `<button class="primary" data-load ${!live() || state.busy ? 'disabled' : ''}>${state.busy ? '正在读取…' : '读取模拟协议配置'}</button><p class="notice" data-error ${state.error ? '' : 'hidden'}>${esc(state.error || '')}</p>`);
      const load = async () => {
        if (!live() || state.busy) return;
        state.busy = true; state.error = ''; renderForm(root, state, live);
        try {
          const parameters = await request(state.path + '/message-parameters?expected_version=' + state.version, undefined, state.base);
          if (live()) { state.parameters = parameters; state.values = {...parameters.defaults}; }
        } catch (e) { if (live()) state.error = e.message; }
        finally { state.busy = false; if (live() && state.root?.isConnected) renderForm(state.root,state,live); }
      };
      root.querySelector('[data-load]').onclick = load;
      if (!state.attempted && live()) { state.attempted = true; queueMicrotask(load); }
      return;
    }
    const isIEC = p.protocol === 'IEC61850';
    const fields = [...common, ...(isIEC ? [...iec, ...advanced, field('structure_confirmed', '模拟点位与控制结构已完整配置', 'checkbox')] : modbus)];
    root.insertAdjacentHTML('beforeend', `<p><strong>${esc(p.protocol === 'Modbus' ? 'Modbus TCP' : 'IEC 61850 / MMS')}</strong> · ${esc(p.device_id)} · ${esc(p.action)} · 原目标值：<code>${esc(JSON.stringify(p.engineering_value))} ${esc(p.unit || '')}</code>（只读）</p>`
      + `<div class="packet-grid">${[...common, ...(isIEC ? iec : modbus)].map(f => inputHtml(f, state.values[f.key])).join('')}</div>`
      + (isIEC ? `<div class="packet-advanced"><h4>控制结构、时间与关联参数</h4><div class="packet-grid">${advanced.map(f => inputHtml(f, state.values[f.key])).join('')}</div><h4>模拟连接配置</h4><div class="packet-grid">${Object.entries(p.association_profile || {}).map(([key,value]) => `<label>${esc(key)}<input readonly value="${esc(value)}"></label>`).join('')}</div></div><p class="hint">按配置生成连接建立、选择（需要时）、操作、读回及取消/释放分支请求。模拟关联值不代表真实协商结果；增强安全模型还需要最终完成反馈。默认Test=true、时钟未同步。</p>${inputHtml(fields[fields.length - 1], state.values.structure_confirmed)}` : '<p class="hint">地址从0计数；倍率计算方式：寄存器值 = 原工程值 × 倍率。点位和编码来自设备动作配置，时间及请求编号由程序管理。</p>')
      + `<button class="primary" data-generate ${!live() || state.busy ? 'disabled' : ''}>${state.busy ? '正在生成…' : '校验并生成报文'}</button><p class="notice" data-error ${state.error ? '' : 'hidden'}>${esc(state.error || '')}</p><div data-packet></div>`);
    const output = root.querySelector('[data-packet]');
    function showPacket() {
      const m = state.packet;
      const packets = m?.requests || (m ? [{id:'operate',title:'操作请求',branch:'main',hex:m.hex,byte_length:m.byte_length}] : []);
      const branches = {main:'正常流程',on_cancel:'取消时使用',release:'释放连接时使用'};
      output.innerHTML = m && live() ? `<p><strong>已生成${packets.length}项完整请求 · 未发送</strong></p><p class="hint">${esc(m.details.scope)}</p>`
        + packets.map((packet,index) => `<section class="packet-request"><h4>${index+1}. ${esc(packet.title)} · ${esc(branches[packet.branch] || packet.branch)} · ${packet.byte_length}字节</h4><p class="hint">前提：${esc((packet.requires || []).join('；') || '按请求包说明建立通信')}</p><textarea class="${packet.id==='operate'?'packet-hex':'packet-frame-hex'}" readonly aria-label="${esc(packet.title)}十六进制">${esc(packet.hex)}</textarea><p class="hint">应核验响应：${esc(JSON.stringify(packet.expected_response || {}))}</p></section>`).join('')
        + (m.warnings.length ? `<p class="notice">${m.warnings.map(esc).join('<br>')}</p>` : '')
        + `${m.bundle_base64 ? '<button class="primary" data-download="zip">下载完整请求包ZIP</button> ' : ''}<button data-download="json">下载全部参数与报文JSON</button> <button data-download="bin">下载操作请求BIN</button>` : '';
      for (const button of output.querySelectorAll('[data-download]')) button.onclick = () => {
        if (!live() || state.packet !== m) return;
        const extension = button.dataset.download, binary = extension !== 'json';
        const content = binary ? Uint8Array.from(atob(extension === 'zip' ? m.bundle_base64 : m.base64), c => c.charCodeAt(0)) : JSON.stringify(m, null, 2);
        const url = URL.createObjectURL(new Blob([content], {type: binary ? 'application/octet-stream' : 'application/json'}));
        const a = document.createElement('a'); a.href = url;
        a.download = `${m.device_id}-${m.command_id}.${extension}`.replace(/[^a-zA-Z0-9_.-]/g, '_');
        a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      };
    }
    for (const input of root.querySelectorAll('[data-key]')) {
      const update = () => {
        const f = fields.find(f => f.key === input.dataset.key);
        state.values[f.key] = f.kind === 'checkbox' ? input.checked : input.value;
        state.revision++; state.packet = null; state.error = '';
        root.querySelector('[data-error]').hidden = true; showPacket();
      };
      input.oninput = update; input.onchange = update;
      input.disabled = !live() || [...(p.managed_fields || []), ...(p.bound_fields || [])].includes(input.dataset.key);
      if (input.dataset.key === 'oper_time_utc' && !p.defaults.include_oper_time) input.disabled = true;
    }
    root.querySelector('[data-generate]').onclick = async () => {
      if (!live() || state.busy) return;
      const revision = state.revision;
      state.packet = null; state.error = '';
      try {
        const options = {...state.values};
        for (const f of fields) if (f.kind === 'number' || f.key === 'function_code') {
          if (String(options[f.key]).trim() === '' || !Number.isFinite(Number(options[f.key]))) throw Error(f.label + '须填写数字');
          options[f.key] = Number(options[f.key]);
        }
        state.busy = true; renderForm(root, state, live);
        const packet = await request(state.path + '/message', {expected_version: state.version, options}, state.base);
        if (live() && revision === state.revision) {
          state.packet = packet;
          for (const key of p.managed_fields || []) state.values[key] = packet.parameters[key];
        }
      } catch (e) { if (live() && revision === state.revision) state.error = e.message; }
      finally { state.busy = false; if (live() && state.root?.isConnected) renderForm(state.root,state,live); }
    };
    showPacket();
  }
  const originalRender = render;
  render = function () {
    originalRender();
    if (owner !== result) { owner = result; forms.clear(); }
    if (!current()) for (const state of forms.values()) state.packet = null;
    const data = result?.data;
    if (tab !== 'instruction' || !data?.simulation_session_id) return;
    for (const [index, entry] of entries(data).entries()) {
      const p = entry.preview, identity = JSON.stringify([data.simulation_session_id, p.command_id, p.expected_version]);
      if (!forms.has(identity)) forms.set(identity, {version: p.expected_version, revision: 0, base: el('api').value,
        path: '/simulation/sessions/' + encodeURIComponent(data.simulation_session_id) + '/commands/' + encodeURIComponent(p.command_id)});
      const state = forms.get(identity), capturedResult = result;
      const live = () => result === capturedResult && current() && entries(result.data).some(e => e.preview.command_id === p.command_id && e.preview.expected_version === p.expected_version);
      const anchor = el(entry.anchor), host = data.simulation_batch || data.simulation_plan ? anchor?.closest('section') : el('output');
      if (!host) continue;
      host.insertAdjacentHTML('beforeend', `<div class="section packet-form" id="packet-form-${index}"></div>`);
      const root = el('packet-form-' + index);
      renderForm(root, state, live);
    }
  };
  for (const id of ['query', 'params', 'scenario', 'simulation-mode', 'api']) {
    for (const event of ['input', 'change']) el(id).addEventListener(event, () => {
      for (const state of forms.values()) { state.packet = null; state.revision++; }
      for (const root of document.querySelectorAll('.packet-form')) {
        for (const control of root.querySelectorAll('button,input,select')) control.disabled = true;
        const output = root.querySelector('[data-packet]'); if (output) output.textContent = '输入已变化，请重新分析后生成报文。';
      }
    });
  }
  const style = document.createElement('style');
  style.textContent = '.packet-form{border-top:1px solid #dbe4e1;padding-top:20px}.packet-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(260px,100%),1fr));gap:12px;margin:16px 0}.packet-grid label{font-size:14px}.packet-grid input,.packet-grid select{display:block;width:100%;box-sizing:border-box;margin-top:6px}.packet-check{display:flex!important;align-items:center;gap:8px;margin:12px 0}.packet-check input{width:auto!important;margin:0!important}.packet-advanced{margin:16px 0}.packet-hex{width:100%;min-height:100px;box-sizing:border-box;font:14px monospace;overflow-wrap:anywhere}.packet-form button{margin:8px 0}';
  document.head.appendChild(style);
})();
