const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
test('template refresh re-enables controls after initial connection failure', async () => {
  const nodes = new Map();
  const element = id => {if(!nodes.has(id))nodes.set(id,{value:'',options:[],innerHTML:'',textContent:'',disabled:false,setAttribute(){},addEventListener(){}});return nodes.get(id);};
  let connected = false;
  const context = vm.createContext({document:{getElementById:element},URLSearchParams,location:{search:''},
    fetch:async()=>{if(!connected)throw Error('offline');return {ok:true,json:async()=>({devices:[]})};}});
  const script = fs.readFileSync(require('node:path').join(__dirname,'../frontend/template-editor.html'),'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
  vm.runInContext(script, context); await new Promise(setImmediate);
  assert.equal(element('save').disabled,true);
  connected = true; await element('refresh').onclick();
  assert.equal(element('save').disabled,false);
  assert.equal(element('test').disabled,false);
});
