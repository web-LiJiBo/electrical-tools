const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function app(){const c={window:{},structuredClone};vm.runInNewContext(fs.readFileSync('frontend/definition-editor.js','utf8'),c);return c.window;}
const base={device_types:{cooling_fan:'风机'},actions:{cooling_fan:{start:'启动'}},units:['W','kW']};
test('registering a type enables custom actions without inventing predefined actions',()=>{
 const a=app(),original={devices:[],instructions:[],bindings:[]};
 const state=a.addCustomDefinition(original,'device_types',{code:'monitor',name:'监测装置'},base);
 const options=a.definitionOptions(base,state.definitions);
 assert.equal(options.device_types.monitor,'监测装置');assert.equal(Object.keys(options.actions.monitor).length,0);assert.equal(original.definitions,undefined);
 assert.throws(()=>a.addCustomDefinition(state,'device_types',{code:'monitor',name:'另一个'},base),/重复/);
});
test('unit registration survives export and keeps original options intact',()=>{
 const a=app(),state=a.addCustomDefinition({devices:[],instructions:[],bindings:[]},'units',{symbol:'GW',base_unit:'MW',scale:1000,offset:0},base);
 assert.ok(a.definitionOptions(base,state.definitions).units.includes('GW'));assert.equal(base.units.includes('GW'),false);
 assert.throws(()=>a.addCustomDefinition(state,'units',{symbol:'W',base_unit:'',scale:1,offset:0},base),/重复/);
});

test('inline unit form reads conversion or standalone values without changing a parent form',()=>{
 const a=app(),fields=Object.fromEntries(Object.entries({symbol:' GW ',base_unit:'MW',scale:'1000',offset:'0'}).map(([k,value])=>[k,{value}]));
 const row=a.readDefinitionForm({elements:fields},'units');assert.equal(row.symbol,'GW');assert.equal(row.scale,1000);
 fields.base_unit.value='';fields.scale.value='';fields.offset.value='';
 assert.equal(a.readDefinitionForm({elements:fields},'units').scale,1);
});

test('inline definition body contains no nested form and escapes available unit names',()=>{
 const a=app(),esc=v=>String(v).replaceAll('<','&lt;').replaceAll('"','&quot;');
 const body=a.definitionFormMarkup('units',['<unit>'],esc);
 assert.doesNotMatch(body,/<form/);assert.match(body,/&lt;unit>/);assert.match(body,/name="base_unit"/);
});
