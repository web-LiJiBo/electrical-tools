const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function app(){const c={window:{}};vm.runInNewContext(fs.readFileSync('frontend/communication-review.js','utf8'),c);return c.window;}
test('communication confirmation is required for each affected device, not other devices',()=>{
 const a=app(),changes=[{device_id:'D1'},{device_id:'D2'}],root={querySelectorAll:()=>[{value:'D1'}]};
 assert.throws(()=>a.readCommunicationConfirmations(root,changes),/确认/);
 root.querySelectorAll=()=>[{value:'D1'},{value:'D2'}];assert.deepEqual(Array.from(a.readCommunicationConfirmations(root,changes)),['D1','D2']);
});
test('communication review shows full before/after values and affected actions with escaped text',()=>{
 const a=app(),esc=v=>String(v).replaceAll('<','&lt;').replaceAll('"','&quot;');
 const html=a.communicationChangesMarkup([{device_id:'D"1',before:{host:'old'},after:{host:'<new>'},affected_actions:['start','stop']}],esc);
 assert.match(html,/old/);assert.match(html,/&lt;new>/);assert.match(html,/start/);assert.match(html,/stop/);assert.match(html,/D&quot;1/);
});
test('new devices and unchanged endpoints need no extra confirmation',()=>{
 assert.equal(app().communicationChangesMarkup([],String),'');
 assert.equal(app().readCommunicationConfirmations({querySelectorAll:()=>[]},[]).length,0);
});
