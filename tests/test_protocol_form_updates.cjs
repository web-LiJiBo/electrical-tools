const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
test('a late protocol configuration updates only its own form, preserving other edits',async()=>{
 const nodes=new Map(),held=[];let renders=0;
 function element(id){if(!nodes.has(id))nodes.set(id,{id,isConnected:true,innerHTML:'',value:'',disabled:false,
  addEventListener(){},closest(){return this;},insertAdjacentHTML(){},querySelector(selector){return element(id+selector);},querySelectorAll(){return [];}});return nodes.get(id);}
 const context=vm.createContext({document:{getElementById:element,querySelectorAll:()=>[],createElement:()=>({}),head:{appendChild(){}}},
 window:{originalSimulation:{isPreviewCurrent:()=>true}},result:{data:{simulation_session_id:'s',simulation_batch:{items:[0,1].map(i=>({preview:{status:'generated',simulation_execution_allowed:true,command_id:'c'+i,expected_version:0}}))}}},
 tab:'instruction',render(){renders++;},esc:String,queueMicrotask,AbortSignal,
 fetch:()=>new Promise(resolve=>held.push(resolve))});
 vm.runInContext(fs.readFileSync('frontend/protocol-messages.js','utf8'),context);context.render();await flush();
 assert.equal(held.length,2);
 const first=element('packet-form-0');first.userEditing='draft';
 held[1]({ok:true,json:async()=>({protocol:'Modbus',defaults:{},managed_fields:[],bound_fields:[]})});await flush();
 assert.equal(renders,1);assert.equal(element('packet-form-0'),first);assert.equal(first.userEditing,'draft');
 held[0]({ok:true,json:async()=>({protocol:'Modbus',defaults:{},managed_fields:[],bound_fields:[]})});await flush();assert.equal(renders,1);
});

test('a pending parameter request updates the replacement form after switching tabs',async()=>{
 const nodes=new Map();let complete;
 function element(id){if(!nodes.has(id))nodes.set(id,{isConnected:true,innerHTML:'',addEventListener(){},closest(){return this;},insertAdjacentHTML(_,html){this.innerHTML+=html;},querySelector(s){return element(id+s);},querySelectorAll(){return [];}});return nodes.get(id);}
 const context=vm.createContext({document:{getElementById:element,querySelectorAll:()=>[],createElement:()=>({}),head:{appendChild(){}}},window:{originalSimulation:{isPreviewCurrent:()=>true}},
 result:{data:{simulation_session_id:'s',simulation_preview:{status:'generated',simulation_execution_allowed:true,command_id:'c',expected_version:0}}},tab:'instruction',render(){},esc:String,queueMicrotask,AbortSignal,
 fetch:()=>new Promise(resolve=>complete=resolve)});
 vm.runInContext(fs.readFileSync('frontend/protocol-messages.js','utf8'),context);context.render();await flush();
 element('packet-form-0').isConnected=false;nodes.delete('packet-form-0');context.render();
 const replacement=element('packet-form-0');complete({ok:true,json:async()=>({protocol:'Modbus',defaults:{},managed_fields:[],bound_fields:[]})});await flush();
 assert.match(replacement.innerHTML,/Modbus TCP/);assert.doesNotMatch(replacement.innerHTML,/正在读取/);
});
