const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const context={window:{}};vm.runInNewContext(fs.readFileSync('frontend/action-definition.js','utf8'),context);
test('a custom false assignment is preserved instead of inferred from the action name',()=>{
 const a=context.window.readActionDefinition({definition:'custom',action:'reset_filter',display_name:'滤网复位',result_field:'alarm',value_source:'fixed',value:false},[]);
 assert.equal(a.value,false);assert.equal(a.value_source,'fixed');assert.equal(a.minimum,null);assert.equal(a.parameter,'');
});
test('custom parameter identity and numeric bounds are independent of result field',()=>{
 const a=context.window.readActionDefinition({definition:'custom',action:'set_air_ratio',display_name:'设置送风比例',result_field:'duty',value_source:'parameter',parameter:'target_ratio',minimum:'0',maximum:'100'},[]);
 assert.equal(a.parameter,'target_ratio');assert.equal(a.result_field,'duty');assert.equal(a.minimum,0);assert.equal(a.maximum,100);assert.equal(a.value,null);
});
