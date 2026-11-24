(() => {
  const get = id => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const alternate = params.get('backend_port') === '8001';
  const api = `http://127.0.0.1:${alternate ? '8001' : '8000'}/simulation/device-import`;
  for (const id of ['home', 'quick']) if (alternate) get(id).href += '?backend_port=8001';
  const types = {number: '小数或整数', integer: '整数', boolean: '是 / 否', enum: '枚举文本'};
  const selectOptions = (select, options, placeholder) => {
    const previous = select.value;
    select.replaceChildren(...(placeholder ? [new Option(placeholder, '')] : []),
      ...Object.entries(options).map(([key, label]) => new Option(label, key)));
    if ([...select.options].some(item => item.value === previous)) select.value = previous;
  };
  let config, review, busy = false;
  const stateCards = () => [...get('state-list').children];
  const actionCards = () => [...get('action-list').children];
  const find = (element, key) => element.querySelector(`[data-field="${key}"]`);
  const selectedKind = () => get('kind').value;
  const show = (message, error = false) => {
    get('status').textContent = message;
    get('status').dataset.tone = error ? 'error' : 'info';
  };
  const invalidate = () => {
    review = undefined;
    get('save').disabled = true;
    get('open-home').hidden = true;
    get('details').replaceChildren();
    show('填写完成后点击“校验并预览”。');
  };
  function scalar(container, type) {
    if (container.dataset.type === type) return;
    container.dataset.type = type;
    const input = document.createElement(type === 'boolean' ? 'select' : 'input');
    input.required = true;
    if (type === 'boolean') selectOptions(input, {yes: '是', no: '否'}, '请选择');
    else if (type === 'enum') {
      input.maxLength = 40;
      input.placeholder = '例如 manual';
    } else {
      input.type = 'number';
      input.step = type === 'integer' ? '1' : 'any';
    }
    container.replaceChildren(input);
  }
  function scalarValue(container) {
    const input = container.firstElementChild;
    if (!input.value.trim()) throw Error('请填全状态值、检查条件或数值范围。');
    if (container.dataset.type === 'boolean') return input.value === 'yes';
    if (container.dataset.type === 'enum') return input.value.trim();
    if (!Number.isFinite(input.valueAsNumber)) throw Error('请填写有效数字。');
    return input.valueAsNumber;
  }
  function fieldOptions(filter = () => true) {
    const results = {};
    for (const card of stateCards()) {
      const key = find(card, 'key').value.trim();
      if (/^[a-z][a-z0-9_]{0,39}$/.test(key) && filter(card)) {
        results[key] = (find(card, 'label').value.trim() || key) + '（' + key + '）';
      }
    }
    return results;
  }
  function fieldType(key) {
    const card = stateCards().find(row => find(row, 'key').value.trim() === key);
    return card && find(card, 'type').value;
  }
  function updateAction(card) {
    const action = find(card, 'action');
    selectOptions(action, config.actions[selectedKind()]);
    const binary = ['start', 'stop'].includes(action.value);
    selectOptions(find(card, 'result'), fieldOptions(row => binary ? find(row, 'type').value === 'boolean' :
      ['number', 'integer'].includes(find(row, 'type').value)), '请选择状态字段');
    const ranges = find(card, 'ranges');
    ranges.hidden = binary;
    for (const input of ranges.querySelectorAll('input')) input.disabled = binary;
    for (const rule of find(card, 'rules').children) {
      const field = find(rule, 'field');
      selectOptions(field, fieldOptions(row => find(row, 'type').value !== 'enum'), '请选择要检查的字段');
      const kind = fieldType(field.value);
      const ops = kind === 'boolean' ? ['==', '!='] : ['==', '!=', '<', '<=', '>', '>='];
      selectOptions(find(rule, 'operator'), Object.fromEntries(ops.map(op => [op, op])));
      scalar(find(rule, 'expected'), kind || 'number');
    }
  }
  function updateState(card) {
    const kind = find(card, 'type').value;
    const unit = find(card, 'unit');
    unit.disabled = ['boolean', 'enum'].includes(kind);
    if (unit.disabled) unit.value = '';
    scalar(find(card, 'value'), kind);
  }
  function createCard(parent, markup) {
    const div = document.createElement('div');
    div.className = 'edit-card';
    div.innerHTML = markup;
    parent.append(div);
    div.querySelector(':scope > button[data-remove]').onclick = () => {
      div.remove();
      actionCards().forEach(updateAction);
      invalidate();
    };
    return div;
  }
  function addState() {
    if (stateCards().length >= 30) return show('最多录入 30 个状态字段。', true);
    const card = createCard(get('state-list'), `
      <div class="fields">
        <label>字段名（英文） <input data-field="key" required pattern="[a-z][a-z0-9_]{0,39}" placeholder="active_power_mw"></label>
        <label>显示名称 <input data-field="label" required maxlength="40" placeholder="当前有功出力"></label>
        <label>字段归类 <select data-field="section"><option value="state">设备状态</option><option value="runtime_facts">许可或运行事实</option></select></label>
        <label>数据类型 <select data-field="type"></select></label>
        <label>单位 <select data-field="unit"></select></label>
        <label>初始值 <span data-field="value"></span></label>
      </div><button type="button" data-remove>移除字段</button>`);
    selectOptions(find(card, 'type'), types);
    selectOptions(find(card, 'unit'), {'': '无', ...Object.fromEntries(config.units.map(unit => [unit, unit]))});
    updateState(card);
    actionCards().forEach(updateAction);
    invalidate();
  }
  function addRule(action) {
    const rules = find(action, 'rules');
    if (rules.children.length >= 10) return show('每个动作最多录入 10 条条件。', true);
    createCard(rules, `
      <div class="fields">
        <label>要检查的字段 <select data-field="field" required></select></label>
        <label>比较方式 <select data-field="operator"></select></label>
        <label>要求值 <span data-field="expected"></span></label>
      </div><button type="button" data-remove>移除条件</button>`);
    updateAction(action);
    invalidate();
  }
  function addAction() {
    if (actionCards().length >= Object.keys(config.actions[selectedKind()]).length) {
      return show('已达到该设备类型可配置的动作数量。', true);
    }
    const card = createCard(get('action-list'), `
      <div class="fields">
        <label>动作 <select data-field="action"></select></label>
        <label>结果写入哪个字段 <select data-field="result" required></select></label>
        <div class="fields" data-field="ranges">
          <label>最小目标值 <input data-field="minimum" type="number" step="any" required></label>
          <label>最大目标值 <input data-field="maximum" type="number" step="any" required></label>
        </div>
      </div>
      <h3>前置条件（全部满足）</h3><div data-field="rules"></div>
      <button type="button" data-add-rule>添加条件</button>
      <button type="button" data-remove>移除动作</button>`);
    card.querySelector('[data-add-rule]').onclick = () => addRule(card);
    addRule(card);
  }
  function record() {
    return {
      device_id: get('device-id').value.trim(), display_name: get('device-name').value.trim(),
      scenario_id: get('scene').value, device_type: selectedKind(), template_id: 'manual_iec61850',
      fields: stateCards().map(card => ({
        ...Object.fromEntries(['key', 'label', 'section', 'type', 'unit'].map(key => [key, find(card, key).value.trim()])),
        value: scalarValue(find(card, 'value')),
      })),
      actions: actionCards().map(card => ({
        action: find(card, 'action').value, result_field: find(card, 'result').value,
        ...Object.fromEntries(['minimum', 'maximum'].map(key => {
          const input = find(card, key);
          return [key, input.disabled ? null : input.valueAsNumber];
        })),
        conditions: [...find(card, 'rules').children].map(rule => ({
          field: find(rule, 'field').value, operator: find(rule, 'operator').value,
          value: scalarValue(find(rule, 'expected')),
        })),
      })),
    };
  }
  async function request(path, body) {
    const response = await fetch(api + path, body ? {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
      signal: AbortSignal.timeout(30000),
    } : {cache: 'no-store', signal: AbortSignal.timeout(10000)});
    const data = await response.json();
    if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : '后端请求失败。');
    return data;
  }
  function item(message) {
    const row = document.createElement('li');
    row.textContent = message;
    get('details').append(row);
  }
  async function submit(save) {
    if (busy || !config || (save && !review)) return;
    const previous = review;
    invalidate();
    busy = true;
    get('form-fields').disabled = get('validate').disabled = true;
    show(save ? '正在保存…' : '正在校验…');
    try {
      const device = save ? previous.device : record();
      const data = await request(save ? '/publish' : '/validate',
        {devices: [device], ...(save ? {revision: previous.revision} : {})});
      if (data.status === 'invalid') {
        show('校验未通过，没有写入本地。', true);
        data.errors.forEach(error => item(error.message));
        return;
      }
      if (data.status !== (save ? 'published' : 'validated')) throw Error('未收到明确的结果，请重新校验。');
      item(`${device.display_name}（${device.device_id}） · ${config.scenarios[device.scenario_id]}`);
      for (const field of device.fields) {
        const value = typeof field.value === 'boolean' ? (field.value ? '是' : '否') : field.value;
        item(`${field.label}：${value} ${field.unit}`);
      }
      for (const action of device.actions) {
        const spec = device.fields.find(field => field.key === action.result_field);
        const range = action.minimum == null ? '固定值' : `${action.minimum} 至 ${action.maximum} ${spec.unit}`;
        const checks = action.conditions.map(rule => {
          const conditionField = device.fields.find(field => field.key === rule.field);
          const expected = typeof rule.value === 'boolean' ? (rule.value ? '是' : '否') : rule.value;
          return `${conditionField.label} ${rule.operator} ${expected}`;
        });
        item(`${config.actions[device.device_type][action.action]}：${range}；条件：${checks.join('、')}`);
      }
      if (!save) {
        review = {device, revision: data.revision};
        show('校验通过，请核对后点击“确认保存”。');
      } else {
        const url = new URL(get('home').href);
        url.searchParams.set('from', 'device-import');
        url.searchParams.set('scenario', device.scenario_id);
        get('open-home').href = url.href;
        get('open-home').hidden = false;
        show('已保存到本地，模拟目录已更新。');
      }
    } catch (error) {
      show(error.name === 'TimeoutError' && save ? '保存结果未确认，请先去首页检查设备是否已加入。' : error.message, true);
    } finally {
      busy = false;
      get('form-fields').disabled = get('validate').disabled = false;
      get('save').disabled = !review;
    }
  }
  get('device-form').addEventListener('input', event => {
    const stateCard = stateCards().find(card => card.contains(event.target));
    if (stateCard) updateState(stateCard);
    if (stateCard || event.target.matches('select')) actionCards().forEach(updateAction);
    invalidate();
  });
  get('device-form').addEventListener('submit', event => { event.preventDefault(); submit(false); });
  get('save').onclick = () => submit(true);
  get('add-state').onclick = addState;
  get('add-action').onclick = addAction;
  request('').then(data => {
    if (data.load_error) throw Error(data.load_error);
    if (!data.manual_configuration) throw Error('当前后端没有手工配置入口，请重启到最新版。');
    config = data.manual_configuration;
    selectOptions(get('scene'), config.scenarios);
    selectOptions(get('kind'), config.device_types);
    get('form-fields').disabled = get('validate').disabled = false;
    addState();
    addAction();
  }).catch(error => show(error.message || '无法读取配置。请确认本地后端已启动。', true));
})();
