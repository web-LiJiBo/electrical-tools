const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
for(const [file,search] of [['customization-advanced.html',''],['customization-advanced.html','?backend_port=8001'],['template-editor.html','?backend_port=8001']]){
 test(`retired ${file} redirects to unified instructions ${search}`,()=>{
  const html=fs.readFileSync('frontend/'+file,'utf8');assert.doesNotMatch(html,/<select id="action"/);
  let replaced;const link={};const source=html.match(/<script>([\s\S]*?)<\/script>/)[1];
  vm.runInNewContext(source,{URL,URLSearchParams,location:{href:'http://127.0.0.1:5500/'+file+search,search,replace:url=>replaced=url},document:{getElementById:()=>link}});
  const target=new URL(replaced);assert.equal(target.pathname,'/customization.html');assert.equal(target.searchParams.get('tab'),'instructions');assert.equal(target.searchParams.get('backend_port'),search?'8001':null);
 });
}
