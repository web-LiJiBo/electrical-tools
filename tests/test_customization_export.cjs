const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function build(){const ctx={window:{},structuredClone};vm.runInNewContext(fs.readFileSync('frontend/customization-export.js','utf8'),ctx);return ctx.window.buildCustomizationExport;}
const state=()=>({devices:[{device_id:'D1'},{device_id:'D2'}],instructions:[{instruction_id:'I1',action:{value:false}},{instruction_id:'I2'}],bindings:[{device_id:'D1',instruction_id:'I1',wire:{command:{address:1}}},{device_id:'D2',instruction_id:'I1',wire:{command:{address:2}}},{device_id:'D2',instruction_id:'I2',wire:{command:{address:3}}}]});
test('device selection includes its instructions and full mappings without unrelated devices',()=>{
 const s=state(),out=build()(s,['D1'],[]);
 assert.deepEqual(Array.from(out.devices,d=>d.device_id),['D1']);assert.deepEqual(Array.from(out.instructions,i=>i.instruction_id),['I1']);assert.equal(out.bindings.length,1);assert.equal(out.instructions[0].action.value,false);
 out.bindings[0].wire.command.address=99;assert.equal(s.bindings[0].wire.command.address,1);
});
test('instruction selection includes all bound devices but not their unrelated actions',()=>{
 const out=build()(state(),[],['I1']);assert.equal(out.devices.length,2);assert.equal(out.instructions.length,1);assert.equal(out.bindings.length,2);
});
test('mixed selection deduplicates dependencies; preset references remain references',()=>{
 const s=state();s.bindings.push({device_id:'BUILTIN',instruction_id:'I1',wire:{}});s.bindings.push({device_id:'D1',instruction_id:'PRESET:D1:start',wire:{}});
 const out=build()(s,['D1'],['I1']);assert.equal(out.devices.length,2);assert.equal(out.instructions.length,1);assert.equal(out.bindings.length,4);assert.deepEqual(Object.keys(out).sort(),['bindings','devices','instructions']);
});
test('empty or removed selections never silently export everything',()=>{
 const fn=build();assert.throws(()=>fn(state(),[],[]),/选择/);assert.throws(()=>fn(state(),['DELETED'],[]),/选择/);
});
