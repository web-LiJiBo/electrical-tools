const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function app(){
 const nodes=new Map(),node=id=>{if(!nodes.has(id))nodes.set(id,{value:'',dataset:{},after(){},replaceChildren(){}});return nodes.get(id)};
 const storage={getItem:()=>null,setItem(){},removeItem(){}};
 const c={window:{},document:{getElementById:node,querySelectorAll:()=>[],createElement:()=>({})},structuredClone,URL,URLSearchParams,AbortSignal,location:{search:'',href:'http://localhost/customization.html'},history:{replaceState(){}},localStorage:storage,sessionStorage:storage,fetch:()=>new Promise(()=>{})};
 const source=fs.readFileSync('frontend/customization.js','utf8').replace(/\}\)\(\);\s*$/,'window.check={compatible,compatibilityHint};})();');vm.runInNewContext(source,c);return c.window.check;
}
const field={key:'local_alarm',label:'本地告警',section:'state',type:'boolean',unit:'',value:false};
test('existing device can accept an explicit new field and displays its default',()=>{
 const a=app(),d={device_type:'pole_controller',readonly:true,fields:[]},i={device_type:'pole_controller',fields:[field]};
 assert.equal(a.compatible(d,i),'');assert.match(a.compatibilityHint(d,i),/补充字段.*本地告警=false/);
 assert.match(a.compatible({...d,readonly:false},i),/字段不匹配/);
});
test('existing device field metadata cannot be silently changed through association',()=>{
 const a=app(),d={device_type:'pole_controller',readonly:true,fields:[{...field,type:'number'}]},i={device_type:'pole_controller',fields:[field]};
 assert.match(a.compatible(d,i),/冲突/);
});
