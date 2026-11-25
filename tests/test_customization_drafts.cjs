const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('frontend/customization.js','utf8').replace(/\}\)\(\);\s*$/,
 'window.review={save(s){state=s;dirty=true;persist();},seedLibrary(v){library=v;},allInstructions,read:()=>state,setBindings,removeInstruction:typeof removeInstruction==="function"?removeInstruction:undefined};})();');
function tab(local=new Map(),session=new Map(),confirm=()=>true){
 const nodes=new Map(),node=id=>{if(!nodes.has(id))nodes.set(id,{value:'',dataset:{},after(){},replaceChildren(){}});return nodes.get(id);};
 const storage=map=>({getItem:k=>map.get(k)||null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k)});
 const ctx={window:{confirm},document:{getElementById:node,querySelectorAll:()=>[],createElement:()=>({})},structuredClone,URL,URLSearchParams,
 location:{search:'',href:'http://localhost/customization.html'},history:{replaceState(){}},AbortSignal,localStorage:storage(local),sessionStorage:storage(session),fetch:()=>new Promise(()=>{})};
 vm.runInNewContext(source,ctx);return ctx.window.review;
}
const draft=id=>({devices:[],instructions:[{instruction_id:id,display_name:id}],bindings:[]});
test('two local windows preserve separate drafts through refresh',()=>{
 const local=new Map(),sa=new Map(),sb=new Map();const a=tab(local,sa),b=tab(local,sb);a.save(draft('A'));b.save(draft('B'));
 assert.equal(JSON.parse(sa.get('electrical-customization-8000')).state.instructions[0].instruction_id,'A');
 assert.equal(JSON.parse(sb.get('electrical-customization-8000')).state.instructions[0].instruction_id,'B');
});
test('unlinking the last use asks before removing the orphan instruction',()=>{
 const a=tab();a.save({devices:[],instructions:[{instruction_id:'I',display_name:'启动'}],bindings:[{device_id:'D',instruction_id:'I',wire:{}}]});
 a.setBindings('device_id','D',new Set());assert.equal(a.read().instructions.length,0);assert.equal(a.read().bindings.length,0);
});
test('declining removal keeps the original associations and instruction',()=>{
 const a=tab(new Map(),new Map(),()=>false);a.save({devices:[],instructions:[{instruction_id:'I',display_name:'启动'}],bindings:[{device_id:'D',instruction_id:'I',wire:{}}]});
 assert.throws(()=>a.setBindings('device_id','D',new Set()));assert.equal(a.read().instructions.length,1);assert.equal(a.read().bindings.length,1);
});
test('delete an unbound draft instruction without changing other entries',()=>{
 const a=tab();const d=draft('I');d.instructions.push({instruction_id:'OTHER',display_name:'Other'});a.save(d);a.removeInstruction('I');
 assert.equal(a.read().instructions.length,1);assert.equal(a.read().instructions[0].instruction_id,'OTHER');
});

test('deleted custom instructions cannot reappear from the published library',()=>{
 const a=tab(),d=draft('I');a.save(d);a.seedLibrary([{instruction_id:'I',display_name:'I'},{instruction_id:'PRESET:D:start',readonly:true}]);
 a.removeInstruction('I');assert.equal(a.allInstructions().length,1);assert.equal(a.allInstructions()[0].instruction_id,'PRESET:D:start');
});

test('the old shared local draft is migrated once without overwriting another window',()=>{
 const content=JSON.stringify({state:draft('LEGACY'),dirty:true}),local=new Map([['electrical-customization-8000',content]]),session=new Map();
 tab(local,session);assert.equal(session.get('electrical-customization-8000'),content);assert.equal(local.has('electrical-customization-8000'),false);
});

test('removing an instruction cannot strand a custom device without any action',()=>{
 const a=tab();a.save({devices:[{device_id:'D',display_name:'设备D'}],instructions:[{instruction_id:'I',display_name:'启动'}],bindings:[{device_id:'D',instruction_id:'I',wire:{}}]});
 assert.throws(()=>a.removeInstruction('I'),/替代指令/);assert.equal(a.read().bindings.length,1);
});
