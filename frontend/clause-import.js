/* Imported clauses are knowledge resources, not device/action bindings. */
(() => {
 const $=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const port=new URLSearchParams(location.search).get('backend_port')==='8001'?'8001':'8000';
 const api='http://127.0.0.1:'+port+'/knowledge/local-clauses',key='electrical-local-clauses-draft:'+port;
 const fields=['standard_id','standard_name','version','clause_number','subject','keywords'];
 let review=null,epoch=0,busy=false;
 window.parseClauseImport=(raw,format,common)=>{
  if(format==='text')return [{...common,content:raw.trim()}];
  const data=JSON.parse(raw.replace(/^\uFEFF/,'')),rows=Array.isArray(data)?data:data?.clauses??[data];
  if(!Array.isArray(rows)||rows.some(r=>!r||typeof r!=='object'||Array.isArray(r)))throw Error('JSON须为条款对象、数组或包含clauses数组的对象。');
  return rows.map(row=>({...common,...row}));
 };
 function common(){return Object.fromEntries(fields.map(name=>[name,name==='keywords'?$('clause-'+name).value.split(/[,，、\n]/).map(s=>s.trim()).filter(Boolean):$('clause-'+name).value.trim()]));}
 function snapshot(){return JSON.stringify({format:$('clause-format').value,raw:$('clause-input').value,common:common()});}
 function status(message,error=false){$('clause-status').textContent=message;$('clause-status').dataset.error=String(error);}
 function persist(){try{sessionStorage.setItem(key,snapshot());}catch(_){}}
 function invalidate(){epoch++;review=null;$('clause-publish').disabled=true;$('clause-review').innerHTML='';persist();}
 function freeze(value){busy=value;$('clause-preview').disabled=value;$('clause-publish').disabled=value||!review;}
 async function request(suffix='',body){
  const response=await fetch(api+suffix,{signal:AbortSignal.timeout(suffix==='/import'?120000:30000),...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{cache:'no-store'})});
  const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'条款请求未完成');return data;
 }
 function rowsHtml(rows){return rows.map(r=>`<article class="card"><h3>${esc(r.standard_id)} · ${esc(r.version)} · ${esc(r.clause_number)}</h3><p>${esc(r.standard_name)}</p><pre>${esc(r.content)}</pre></article>`).join('');}
 async function load(){
  const data=await request();$('clause-list').innerHTML=rowsHtml((data.clauses||[]).slice(-30).reverse());
  $('clause-count').textContent=`本地共 ${data.clauses.length} 条；显示最近30条。`;
 }
 async function perform(publish){
  if(busy||publish&&!review)return;
  const current=snapshot(),sequence=epoch,previous=review;freeze(true);
  try{
   const parsed=JSON.parse(current),rows=publish?previous.rows:window.parseClauseImport(parsed.raw,parsed.format,parsed.common);
   if(publish&&previous.snapshot!==current)throw Error('条款输入已变化，请重新预览。');
   status(publish?'正在保存并更新条款索引…':'正在校验条款…');
   const data=await request(publish?'/import':'/preview',{clauses:rows,...(publish?{revision:previous.revision}:{})});
   if(!publish&&(sequence!==epoch||snapshot()!==current))return;
   if(data.status==='conflicts'){
    $('clause-review').innerHTML=(data.conflicts||[]).map(c=>`<article class="card"><h3>内容冲突：${esc(c.standard_id)} · ${esc(c.version)} · ${esc(c.clause_number)}</h3><p>已有内容</p><pre>${esc(c.current)}</pre><p>本次内容</p><pre>${esc(c.incoming)}</pre></article>`).join('');
    throw Error('同版本同条款号内容不同，本批未保存。请核对版本或条款号后重新预览。');
   }
   if(data.status!== (publish?'published':'validated'))throw Error((data.errors||[]).map(e=>e.message).join('；')||'未收到明确的条款处理结果');
   if(publish){review=null;status(`本批已处理：新增${data.added||0}条，重复${data.unchanged||0}条。已保存在本地，新问答可使用。`);await load();
    if(sequence!==epoch||snapshot()!==current){status('条款已导入，新输入已保留；如需继续导入请重新预览。');return;}
    $('clause-review').innerHTML='<p>本批导入完成；原问答结果保持不变，重新提问时使用更新后的知识库。</p>';}
   else{review={rows,revision:data.revision,snapshot:current};$('clause-review').innerHTML=`<p>新增${data.added}条，重复${data.unchanged}条。核对原文后确认导入。</p><div class="cards">${rowsHtml(data.clauses)}</div>`;status('预览完成，尚未写入本地文件。');}
  }catch(error){if(publish||sequence===epoch)status(error.message,true);review=null;}
  finally{freeze(false);}
 }
 for(const id of [...fields.map(f=>'clause-'+f),'clause-format','clause-input']){
  $(id).addEventListener('input',invalidate);$(id).addEventListener('change',invalidate);
 }
 $('clause-preview').onclick=()=>perform(false);$('clause-publish').onclick=()=>perform(true);
 $('clause-file').onchange=async event=>{
  const file=event.target.files[0];event.target.value='';if(!file)return;invalidate();const sequence=epoch;
  if(!/\.(txt|json)$/i.test(file.name)){status('当前支持TXT正文和JSON条款文件。',true);return;}
  if(file.size>2*1024*1024){status('文件超过2MB，请拆分后导入。',true);return;}
  try{const text=await file.text();if(sequence!==epoch)return;$('clause-format').value=file.name.toLowerCase().endsWith('.json')?'json':'text';$('clause-input').value=text;invalidate();status('文件已载入，请补齐来源信息后预览。');}
  catch(error){status('读取失败：'+error.message,true);}
 };
 $('clause-example').onclick=()=>{
  const example={clauses:[{standard_id:'填写标准编号',standard_name:'填写标准名称',version:'填写版本',clause_number:'填写条款号',content:'粘贴完整条款原文',subject:'',keywords:[]}]};
  const url=URL.createObjectURL(new Blob([JSON.stringify(example,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='clause-import-template.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 };
 try{const saved=JSON.parse(sessionStorage.getItem(key)||'null');if(saved){$('clause-format').value=saved.format;$('clause-input').value=saved.raw;for(const f of fields)$('clause-'+f).value=f==='keywords'?(saved.common[f]||[]).join('、'):saved.common[f]||'';}}catch(_){}
 load().catch(error=>status('无法读取本地条款：'+error.message,true));
})();
