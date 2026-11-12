const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../frontend/template-editor.html'), 'utf8');
const source = html.slice(html.indexOf('function updateMapping()'), html.indexOf('const actionNames='));

function editor(devices) {
  const elements = new Map();
  const $ = id => {
    if (!elements.has(id)) elements.set(id, {value: '', hidden: false});
    return elements.get(id);
  };
  $('kind').value = 'bool';
  $('action').value = 'alarm';
  const context = vm.createContext({$, devices});
  vm.runInContext(source, context);
  return (device, action = 'alarm') => {
    $('device').value = device;
    $('action').value = action;
    context.updateMapping();
    return JSON.parse($('mapping').value);
  };
}

test('different IEC devices and actions receive independent default command points', () => {
  const mapping = editor([
    {device_id: 'SIM-IEC-FAN-01', protocol: 'IEC61850', mapping: {}, actions: {}},
    {device_id: 'SIM-IEC-PUMP-01', protocol: 'IEC61850', mapping: {}, actions: {}},
  ]);
  const points = [mapping('SIM-IEC-FAN-01'), mapping('SIM-IEC-PUMP-01'),
    mapping('SIM-IEC-FAN-01', 'adjust_active_power')].map(item => item.object_reference);
  assert.equal(new Set(points).size, 3);
  assert.match(points[0], /^SIM_EDITOR/);
});

test('Modbus defaults avoid existing command and inferred feedback addresses', () => {
  const mapping = editor([{device_id: 'SIM-MB-FAN-01', protocol: 'Modbus',
    mapping: {slave_id: 3, address: 10}, actions: {
      start: {mapping: {address: 3000}},
      stop: {mapping: {address: 3001}},
    }}]);
  const point = mapping('SIM-MB-FAN-01');
  assert.equal(point.slave_id, 3);
  assert.equal(point.data_type, 'bool');
  assert.equal(point.function_code, 5);
  assert.ok(![10, 1010, 3000, 3001, 4000, 4001].includes(point.address));
  assert.ok(![10, 1010, 3000, 3001, 4000, 4001].includes(point.address + 1000));
});

test('action changes regenerate their distinct IEC default mapping', () => {
  assert.ok(/\$\('action'\)\.onchange=updateMapping/.test(html), 'action change must refresh its point');
});
