const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const code=fs.readFileSync('frontend/clause-import.js','utf8');
function fixture(){
 const nodes=new Map(),node=id=>{if(!nodes.has(id))nodes.set(id,{value:'',disabled:false,textContent:'',dataset:{},innerHTML:'',addEventListener(name,fn){this[name]=fn;}});return nodes.get(id);};
 node('clause-format').value='text';let previewResolve;
 const context={window:{},document:{getElementById:node,querySelectorAll:()=>[]},URLSearchParams,location:{search:''},AbortSignal,Blob,URL,
 sessionStorage:{getItem:()=>null,setItem(){}},fetch:async(url)=>url.endsWith('/preview')||url.endsWith('/import')?new Promise(resolve=>previewResolve=resolve):{ok:true,json:async()=>({clauses:[]})}};
 vm.runInNewContext(code,context);return {context,node,resolve:value=>previewResolve({ok:true,json:async()=>value})};
}
test('JSON single row, array and wrapper preserve explicit metadata and accept BOM',()=>{
 const f=fixture(),parse=f.context.window.parseClauseImport;
 for(const value of [{content:'正文'},[{content:'正文'}],{clauses:[{content:'正文'}]}]){
  const rows=parse('\uFEFF'+JSON.stringify(value),'json',{standard_id:'LOCAL',version:'2026',clause_number:'1'});
  assert.equal(rows[0].standard_id,'LOCAL');assert.equal(rows[0].content,'正文');
 }
 assert.equal(parse('多段\n\n原文','text',{})[0].content,'多段\n\n原文');
});
test('edited input cannot publish an old preview returned later',async()=>{
 const f=fixture();f.node('clause-input').value='原文';const pending=f.node('clause-preview').onclick();
 f.node('clause-input').value='新原文';f.node('clause-input').input();
 f.resolve({status:'validated',revision:'old',clauses:[{content:'原文'}],added:1,unchanged:0});await pending;
 assert.equal(f.node('clause-publish').disabled,true);assert.doesNotMatch(f.node('clause-review').innerHTML,/原文/);
});

test('editing while importing never hides a failed publication',async()=>{
 const f=fixture();f.node('clause-input').value='原文';let pending=f.node('clause-preview').onclick();
 f.resolve({status:'validated',revision:'old',clauses:[],added:1,unchanged:0});await pending;
 pending=f.node('clause-publish').onclick();f.node('clause-input').value='新输入';f.node('clause-input').input();
 f.resolve({status:'invalid',errors:[{message:'磁盘保存失败'}]});await pending;
 assert.match(f.node('clause-status').textContent,/磁盘保存失败/);assert.equal(f.node('clause-input').value,'新输入');
});
