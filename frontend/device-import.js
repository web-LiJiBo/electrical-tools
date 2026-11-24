(() => {
  const get = id => document.getElementById(id);
  const port = new URLSearchParams(location.search).get('backend_port') === '8001' ? '8001' : '8000';
  const api = `http://127.0.0.1:${port}/simulation/device-import`;
  if (port === '8001') {
    for (const id of ['home', 'templates', 'open-home', 'device-config']) {
      const url = new URL(get(id).href);
      url.searchParams.set('backend_port', port);
      get(id).href = url.href;
    }
  }
  const facts = new Map(), actions = new Map();
  let config, validated, busy = false, bulk = false, fileRevision = 0;

  function status(message, error = false) {
    get('status').dataset.tone = error ? 'error' : 'info';
    get('status').textContent = message;
  }

  function setBusy(value) {
    busy = value;
    for (const id of ['manual', 'bulk']) get(id).disabled = value;
    for (const id of ['manual-panel', 'bulk-panel']) get(id).inert = value;
    get('validate').disabled = busy || !config || Boolean(config.load_error);
    get('publish').disabled = busy || !validated;
  }

  function clearReview() {
    validated = undefined;
    get('publish').disabled = true;
    for (const id of ['errors', 'preview', 'report-scope', 'open-home']) get(id).hidden = true;
  }

  function changed() {
    clearReview();
    status(config?.load_error || '填写设备信息后，点击“校验并预览”。', Boolean(config?.load_error));
  }

  function toggle(isBulk) {
    if (bulk === isBulk) return;
    bulk = isBulk;
    get('manual').setAttribute('aria-pressed', String(!bulk));
    get('bulk').setAttribute('aria-pressed', String(bulk));
    get('manual-panel').hidden = bulk;
    get('bulk-panel').hidden = !bulk;
    changed();
  }

  function configureChecks(groups, labels, target) {
    for (const [key, title] of Object.entries(labels)) {
      const label = document.createElement('label');
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      label.append(checkbox, document.createTextNode(title));
      get(target).append(label);
      groups.set(key, checkbox);
    }
  }

  function fillExample(fillIdentity = true) {
    const sample = config.sample;
    if (fillIdentity) {
      get('device-id').value = sample.device_id;
      get('device-name').value = sample.display_name;
    }
    for (const [key, checkbox] of facts) checkbox.checked = sample.initial_values[key];
    for (const [key, checkbox] of actions) checkbox.checked = sample.actions.includes(key);
    changed();
  }

  async function request(suffix, body) {
    const options = {signal: AbortSignal.timeout(30000)};
    if (body) Object.assign(options, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
    });
    const response = await fetch(api + suffix, options);
    const data = await response.json();
    if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : `请求失败（HTTP ${response.status}）`);
    return data;
  }

  function records() {
    if (bulk) {
      const source = get('json-input').value;
      if (new TextEncoder().encode(source).length > config.max_file_size) throw Error('JSON 内容超过大小限制。');
      const data = JSON.parse(source.replace(/^\uFEFF/, ''));
      if (Array.isArray(data)) return data;
      if (data && Object.keys(data).length === 1 && Array.isArray(data.devices)) return data.devices;
      throw Error('请提供设备数组，或仅包含 devices 数组的对象。');
    }
    const {scenario_id, template_id} = config.sample;
    return [{
      device_id: get('device-id').value.trim(), display_name: get('device-name').value.trim(), scenario_id, template_id,
      initial_values: Object.fromEntries([...facts].map(([key, checkbox]) => [key, checkbox.checked])),
      actions: [...actions].filter(([, checkbox]) => checkbox.checked).map(([key]) => key),
    }];
  }

  function show(data) {
    const errors = get('errors'), preview = get('preview');
    errors.replaceChildren(...data.errors.map(error => {
      const item = document.createElement('li');
      item.textContent = `${error.row == null ? '' : `第 ${error.row} 条：`}${error.message}`;
      return item;
    }));
    preview.replaceChildren(...data.devices.map(device => {
      const item = document.createElement('li');
      const name = document.createElement('strong'), identity = document.createElement('small');
      name.textContent = device.display_name;
      const actionLabels = {...config.action_labels, ...Object.assign({}, ...Object.values(config.manual_configuration?.actions || {}))};
      identity.textContent = `${device.device_id} · ${device.actions.map(action => actionLabels[action] || action).join('、')}`;
      const details = document.createElement('details'), summary = document.createElement('summary');
      const state = document.createElement('small');
      summary.textContent = '核对初始状态';
      state.textContent = (device.fields ? device.fields.map(field =>
        `${field.label}：${typeof field.value === 'boolean' ? (field.value ? '是' : '否') : field.value} ${field.unit}`)
        : Object.entries(config.fact_labels).map(([key, label]) =>
          `${label}：${device.initial_values[key] ? '是' : '否'}`)).join('；');
      details.append(summary, state);
      item.append(name, identity, details);
      return item;
    }));
    errors.hidden = !data.errors.length;
    preview.hidden = !data.devices.length;
    get('report-scope').hidden = !data.devices.length;
    if (data.status === 'invalid') status('本批校验未通过。请修正下方错误，再重新校验。', true);
    else if (data.status === 'validated') status(`${data.devices.length} 台设备校验通过，等待确认发布。`);
    else {
      status(`已发布 ${data.devices.length} 台模拟设备。返回首页后在对应业务场景中查看。`);
      get('open-home').hidden = false;
    }
  }

  async function submit(publish) {
    if (!config || busy || (publish && !validated)) return;
    const previous = validated;
    clearReview();
    setBusy(true);
    try {
      const devices = publish ? previous.devices : records();
      const body = publish ? {devices, revision: previous.revision} : {devices};
      status(publish ? '正在发布…' : '正在校验…');
      const data = await request(publish ? '/publish' : '/validate', body);
      show(data);
      if (data.status === 'validated') validated = {devices, revision: data.revision};
    } catch (error) {
      status(error instanceof SyntaxError ? '无法读取 JSON，请检查文件格式或后端连接。' :
        publish && error.name === 'TimeoutError' ? '发布结果暂未确认，请重新校验该批设备。' : error.message, true);
    } finally {
      setBusy(false);
    }
  }

  get('manual').onclick = () => toggle(false);
  get('bulk').onclick = () => toggle(true);
  get('manual-panel').addEventListener('input', changed);
  get('json-input').addEventListener('input', () => { fileRevision++; changed(); });
  get('fill-example').onclick = () => fillExample();
  get('download').onclick = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify({devices: [config.sample]}, null, 2)], {type: 'application/json'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'simulation-device-example.json';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  get('json-file').onchange = async event => {
    const file = event.target.files[0];
    const revision = ++fileRevision;
    event.target.value = '';
    if (!file || !config || busy) return;
    changed();
    get('json-input').value = '';
    if (file.size > config.max_file_size) { status('文件超过大小限制。', true); return; }
    try {
      const source = await file.text();
      if (revision === fileRevision && !busy) { get('json-input').value = source; changed(); }
    } catch {
      if (revision === fileRevision && !busy) status('文件读取失败，请重新选择。', true);
    }
  };
  get('validate').onclick = () => submit(false);
  get('publish').onclick = () => submit(true);

  request('').then(data => {
    config = data;
    configureChecks(facts, config.fact_labels, 'facts');
    configureChecks(actions, config.action_labels, 'actions');
    for (const [action, rules] of Object.entries(config.conditions)) {
      const item = document.createElement('li');
      const trigger = /^(\w+) == ([01])$/.exec(rules.condition);
      const checks = rules.constraints.map(rule => `${config.fact_labels[rule.parameter] || rule.parameter}${rule.value ? '：是' : '：否'}`);
      if (trigger) checks.unshift(`${config.fact_labels[trigger[1]] || trigger[1]}${trigger[2] === '1' ? '：是' : '：否'}`);
      else checks.unshift(rules.condition);
      item.textContent = `${config.action_labels[action]}：${checks.join('；')}`;
      get('conditions').append(item);
    }
    get('file-limit').textContent = `单批最多 ${config.max_batch} 台，文件不超过 ${config.max_file_size / 1024} KB。`;
    get('fill-example').disabled = get('download').disabled = false;
    fillExample(false);
    setBusy(false);
  }).catch(() => status('无法读取设备模板，请确认最新版后端已启动，再刷新页面。', true));
})();
