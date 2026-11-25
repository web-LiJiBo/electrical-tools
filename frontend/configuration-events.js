(() => {
 const port=new URLSearchParams(location.search).get('backend_port')==='8001'?'8001':'8000';
 const key='electrical-tools:configuration:'+port;
 let known;try{known=localStorage.getItem(key);}catch(_){}
 let stale=false, stopped=false, timer=null, pending=null;
 const revisions=new Map();
 const endpoint=()=>String(document.getElementById('api')?.value||'http://127.0.0.1:'+port).replace(/\/+$/,'');
 const initialEndpoint=endpoint();
 revisions.set(initialEndpoint,known);
 const channel=typeof BroadcastChannel==='function'?new BroadcastChannel(key):null;
 function stopTimer(){if(timer!==null){clearTimeout(timer);timer=null;}}
 function notice(){
  if(stale)return;stale=true;stopTimer();pending?.controller.abort();
  try{for(const k of Object.keys(sessionStorage))if(k.startsWith('electrical-tools:simulation-session:'))sessionStorage.removeItem(k);}catch(_){}
  window.originalSimulation?.configurationChanged?.();
  for(const control of document.querySelectorAll('#run,[id^="simulate-"].primary,.packet-form button,.packet-form input,.packet-form select'))control.disabled=true;
  const banner=document.createElement('section');banner.id='configuration-update-notice';banner.setAttribute('role','status');
  banner.style.cssText='position:sticky;top:0;z-index:1000;padding:12px 20px;background:#fff3e7;color:#784007;border-bottom:1px solid #e8c9a8;line-height:1.6';
  banner.innerHTML='配置已更新。当前答案仅供阅读，旧候选和报文操作已停用；请刷新后重新问答。未保存的配置草稿请先导出备份。 <button type="button">刷新并使用新配置</button>';
  banner.querySelector('button').onclick=()=>location.reload();
  document.body.prepend(banner);
 }
 function check(base=endpoint()){
  if(stale)return Promise.reject(Error('配置已更新，请重新问答。'));
  base=String(base).replace(/\/+$/,'');
  if(pending){if(pending.base===base)return pending.promise;return pending.promise.catch(()=>{}).then(()=>check(base));}
  const controller=new AbortController(),request={base,controller};
  pending=request;
  const timeout=setTimeout(()=>controller.abort(),10000);
  request.promise=(async()=>{
   try{
    const response=await fetch(base+'/simulation/configuration',{cache:'no-store',signal:controller.signal});
    if(!response.ok)throw Error('无法核对配置版本，请稍后重试。');
    const data=await response.json(),next=data.configuration_revision;
    if(controller.signal.aborted||stopped)return;
    const previous=revisions.get(base);
    if(next){revisions.set(base,next);if(base===initialEndpoint){known=next;try{localStorage.setItem(key,next);}catch(_){}}}
    if(previous&&next&&previous!==next){notice();throw Error('配置已更新，请手动刷新后重新问答。');}
   }finally{clearTimeout(timeout);if(pending===request)pending=null;}
  })();
  return request.promise;
 }
 function schedule(){stopTimer();if(!stopped&&!stale&&document.visibilityState!=='hidden')timer=setTimeout(poll,15000);}
 async function poll(){
  stopTimer();if(stopped||stale||document.visibilityState==='hidden')return;
  try{await check();}catch(_){/* Background failures leave the current answer intact; retry next interval. */}
  schedule();
 }
 window.configurationEvents={check,isStale:()=>stale,published(data){
  const next=data.configuration_revision;if(!next)throw Error('保存结果缺少配置版本，请刷新。');
  known=next;try{localStorage.setItem(key,next);}catch(_){}channel?.postMessage(next);notice();
 }};
 if(channel)channel.onmessage=e=>{if(e.data&&e.data!==known)notice();};
 window.addEventListener('storage',e=>{if(e.key===key&&e.newValue&&e.newValue!==known)notice();});
 window.addEventListener('focus',poll);
 document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden'){stopTimer();}else{poll();}});
 window.addEventListener('pagehide',()=>{stopped=true;stopTimer();pending?.controller.abort();});
 window.addEventListener('pageshow',()=>{if(stopped){stopped=false;poll();}});
 schedule();
})();
