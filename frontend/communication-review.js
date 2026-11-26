(() => {
  window.communicationChangesMarkup = (changes, esc) => changes.map(row => `<article class="card">
    <h3>整台设备通信配置变化 · ${esc(row.device_id)}</h3>
    <p>此变化会影响该设备的所有动作，包括本次没有编辑的动作。</p>
    <p>受影响动作：${(row.affected_action_names || row.affected_actions).map(esc).join('、')}</p>
    <p>原通信配置</p><pre>${esc(JSON.stringify(row.before,null,2))}</pre>
    <p>新通信配置</p><pre>${esc(JSON.stringify(row.after,null,2))}</pre>
    <label><input type="checkbox" data-communication-confirmation value="${esc(row.device_id)}">我确认以上动作全部使用新的通信配置</label>
  </article>`).join('');
  window.readCommunicationConfirmations = (root, changes) => {
    const selected = [...root.querySelectorAll('[data-communication-confirmation]:checked')].map(input => input.value);
    if (changes.some(row => !selected.includes(row.device_id))) throw Error('请先核对整台设备受影响动作，并勾选确认通信配置变化。');
    return selected;
  };
})();
