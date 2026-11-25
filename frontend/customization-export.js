(() => {
  'use strict';
  // Expand only explicit selections, not the whole connected device/action graph.
  window.buildCustomizationExport = (state, deviceIds, instructionIds) => {
    const devices = new Set(state.devices.filter(d => deviceIds.includes(d.device_id)).map(d => d.device_id));
    const instructions = new Set(state.instructions.filter(i => instructionIds.includes(i.instruction_id)).map(i => i.instruction_id));
    if (!devices.size && !instructions.size) throw Error('请至少选择一台自定义设备或一条自定义指令。');
    const bindings = state.bindings.filter(b => devices.has(b.device_id) || instructions.has(b.instruction_id));
    const neededDevices = new Set([...devices, ...bindings.map(b => b.device_id)]);
    const neededInstructions = new Set([...instructions, ...bindings.map(b => b.instruction_id)]);
    return structuredClone({
      devices: state.devices.filter(d => neededDevices.has(d.device_id)),
      instructions: state.instructions.filter(i => neededInstructions.has(i.instruction_id)),
      bindings
    });
  };
  window.createCustomizationExport = (container, getState) => {
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    container.innerHTML = `<h3>选择导出自定义配置</h3>
      <p class="hint">从当前工作区导出（包含未保存草稿）。可逐项选择设备或指令；自动带上所选项的直接关联、配套定义和完整报文配置。预置设备与指令保留编号引用，不复制预置库；本文件不包含本地条款。</p>
      <div class="button-row"><button type="button" data-all>全选</button><button type="button" data-none>清空选择</button></div>
      <div class="form-grid"><fieldset><legend>自定义设备</legend><div class="relations" data-devices></div></fieldset><fieldset><legend>自定义指令</legend><div class="relations" data-instructions></div></fieldset></div>
      <p data-summary role="status" aria-live="polite"></p><button type="button" class="primary" data-download disabled>导出所选配置</button>`;
    const find = selector => container.querySelector(selector);
    const selected = kind => [...find(`[data-${kind}]`).querySelectorAll('input:checked')].map(input => input.value);
    const payload = () => window.buildCustomizationExport(getState(), selected('devices'), selected('instructions'));
    function update() {
      try {
        const out = payload();
        const presetDevices = new Set(out.bindings.filter(b => !out.devices.some(d => d.device_id === b.device_id)).map(b => b.device_id));
        const presetInstructions = new Set(out.bindings.filter(b => !out.instructions.some(i => i.instruction_id === b.instruction_id)).map(b => b.instruction_id));
        find('[data-summary]').textContent = `实际导出：${out.devices.length} 台设备、${out.instructions.length} 条指令、${out.bindings.length} 项关联（含报文）。${presetDevices.size || presetInstructions.size ? `另引用 ${presetDevices.size} 台预置设备、${presetInstructions.size} 条预置指令，导入环境需有对应编号。` : ''}导入后仍需校验，未完成的草稿不会因导出自动补齐。`;
        find('[data-download]').disabled = false;
      } catch (error) { find('[data-summary]').textContent = error.message; find('[data-download]').disabled = true; }
    }
    function render() {
      const current = getState();
      for (const [kind, key] of [['devices','device_id'], ['instructions','instruction_id']]) {
        const previous = new Set(selected(kind));
        find(`[data-${kind}]`).innerHTML = current[kind].map(row => `<label class="relation"><input type="checkbox" value="${esc(row[key])}" ${previous.has(row[key]) ? 'checked' : ''}>${esc(row.display_name || row[key])}<small>${esc(row[key])}</small></label>`).join('') || '<p class="hint">暂无自定义内容</p>';
      }
      update();
    }
    container.onchange = update;
    for (const [selector, checked] of [['[data-all]',true], ['[data-none]',false]]) {
      find(selector).onclick = () => { container.querySelectorAll('input[type=checkbox]').forEach(input => { input.checked = checked; }); update(); };
    }
    find('[data-download]').onclick = () => {
      const out = payload(), url = URL.createObjectURL(new Blob([JSON.stringify(out,null,2)], {type:'application/json'}));
      const link = document.createElement('a'); link.href = url; link.download = 'customization-selected.json'; link.click();
      setTimeout(() => URL.revokeObjectURL(url),1000);
    };
    return {render};
  };
})();
