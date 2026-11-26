const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
test('unified editor can retry initial connection failure without losing the workspace',async()=>{
 const nodes=new Map(),element=id=>{if(!nodes.has(id))nodes.set(id,{value:'',dataset:{},disabled:true,after(){},replaceChildren(){}});return nodes.get(id)};
 const storage={getItem:()=>null,setItem(){},removeItem(){}};let connected=false;
 const data={state:{devices:[],instructions:[],bindings:[]},devices:[],instructions:[],base_revision:'revision',options:{device_types:{cooling_fan:'风机'},actions:{cooling_fan:{}},scenarios:{},units:[]}};
 const context={window:{},document:{getElementById:element,querySelectorAll:()=>[],createElement:()=>({replaceChildren(){}})},structuredClone,URL,URLSearchParams,AbortSignal,location:{search:'',href:'http://localhost/customization.html'},history:{replaceState(){}},localStorage:storage,sessionStorage:storage,fetch:async()=>{if(!connected)throw Error('offline');return {ok:true,json:async()=>data}}};
 vm.runInNewContext(fs.readFileSync('frontend/customization.js','utf8'),context);await new Promise(setImmediate);
 assert.match(element('status').textContent,/无法读取/);connected=true;await element('refresh').onclick();
 assert.equal(element('new-device').disabled,false);assert.equal(element('new-instruction').disabled,false);assert.equal(element('validate').disabled,false);
});
