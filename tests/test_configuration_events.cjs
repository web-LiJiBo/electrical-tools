const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm'),fs=require('node:fs');
const script=fs.readFileSync('frontend/configuration-events.js','utf8');
function app(stored='old', options={}) {
 const events={},documentEvents={},local=new Map([['electrical-tools:configuration:8000',stored]]),timers=new Map();
 let reloads=0,clears=0,requests=0,sequence=0;
 const session={'electrical-tools:simulation-session:base':'session-old',other:'keep',removeItem(k){delete this[k];}};
 const api={value:options.api||'http://127.0.0.1:8000'};
 const nodes=new Map();
 function node(){return {disabled:false,style:{},setAttribute(){},querySelector(){return this.button ||= node();}};}
 const body={prepend(n){nodes.set(n.id,n);}};
 const context={window:{addEventListener:(k,fn)=>events[k]=fn,originalSimulation:{invalidate(){}}},URLSearchParams,AbortController,
 setTimeout(fn,delay){const id=++sequence;timers.set(id,{fn,delay});return id;},clearTimeout(id){timers.delete(id);},
 location:{search:options.search||'',reload(){reloads++;}},
 document:{body,createElement:node,querySelectorAll:()=>[],visibilityState:'visible',addEventListener:(k,fn)=>documentEvents[k]=fn,getElementById:id=>id==='api'?(options.noInput?null:api):id==='configuration-update-notice'?nodes.get(id):{replaceChildren(){clears++;}}},
 localStorage:{getItem:k=>local.get(k),setItem:(k,v)=>local.set(k,v)},sessionStorage:session,result:{data:{answer:'obsolete'}},
 fetch:async(...args)=>{requests++;return options.fetch?options.fetch(...args):{ok:true,json:async()=>({configuration_revision:'new'})};}};
 vm.runInNewContext(script,context);
 return {context,events,documentEvents,local,session,timers,api,nodes,get requests(){return requests;},get reloads(){return reloads;},get clears(){return clears;}};
}
const check=a=>a.context.window.configurationEvents.check('http://127.0.0.1:8000');
const flush=()=>new Promise(resolve=>setImmediate(resolve));

test('configuration change keeps reading and editing intact until the refresh button is clicked',()=>{
 const a=app();a.context.window.configurationEvents.published({configuration_revision:'new'});
 assert.equal(a.reloads,0);assert.equal(a.clears,0);assert.equal(a.context.result.data.answer,'obsolete');
 assert.equal(a.context.window.configurationEvents.isStale(),true);
 assert.equal(a.nodes.size,1);a.nodes.get('configuration-update-notice').querySelector('button').onclick();assert.equal(a.reloads,1);
});
test('successful publication removes all old session references and question result until manual refresh',()=>{const a=app();a.context.window.configurationEvents.published({configuration_revision:'new'});assert.equal(a.context.result.data.answer,'obsolete');assert.equal(a.session['electrical-tools:simulation-session:base'],undefined);assert.equal(a.session.other,'keep');assert.equal(a.reloads,0);assert.equal(a.clears,0);});
test('revision check rejects old configuration and remembers new revision until manual refresh',async()=>{const a=app();await assert.rejects(check(a),/配置已更新/);assert.equal(a.local.get('electrical-tools:configuration:8000'),'new');assert.equal(a.reloads,0);});
test('cross-tab version event invalidates existing answer once',()=>{const a=app();a.events.storage({key:'electrical-tools:configuration:8000',newValue:'new'});a.events.storage({key:'electrical-tools:configuration:8000',newValue:'new'});assert.equal(a.reloads,0);assert.equal(a.context.result.data.answer,'obsolete');});
test('matching configuration can proceed without reload',async()=>{const a=app('new');await check(a);assert.equal(a.reloads,0);});
test('focus discovers remote publication and prompts once',async()=>{const a=app();a.events.focus();a.events.focus();await flush();assert.equal(a.requests,1);assert.equal(a.reloads,0);assert.equal(a.timers.size,0);});
test('visible polling runs every 15 seconds and stops while hidden',async()=>{const a=app('new');const timer=[...a.timers.values()].find(t=>t.delay===15000);await timer.fn();assert.equal(a.requests,1);a.context.document.visibilityState='hidden';a.documentEvents.visibilitychange();assert.equal(a.timers.size,0);await a.events.focus();assert.equal(a.requests,1);a.context.document.visibilityState='visible';a.documentEvents.visibilitychange();await flush();assert.equal(a.requests,2);assert.equal([...a.timers.values()].filter(t=>t.delay===15000).length,1);});
test('network failure preserves answer and retries silently on next poll',async()=>{let fail=true;const a=app('old',{fetch:async()=>{if(fail)throw Error('offline');return {ok:true,json:async()=>({configuration_revision:'new'})};}});await a.events.focus();assert.notEqual(a.context.result,null);assert.equal(a.reloads,0);assert.equal(a.session['electrical-tools:simulation-session:base'],'session-old');assert.equal(a.timers.size,1);fail=false;await [...a.timers.values()][0].fn();assert.equal(a.reloads,0);});
test('foreground and background checks share a single pending request',async()=>{let resolve;const a=app('new',{fetch:()=>new Promise(r=>resolve=r)});const pending=check(a);a.events.focus();assert.equal(a.requests,1);resolve({ok:true,json:async()=>({configuration_revision:'new'})});await pending;await flush();assert.equal(a.requests,1);});
test('poll uses current API input, falling back to URL backend port without an input',async()=>{const urls=[];const fetch=async url=>{urls.push(url);return {ok:true,json:async()=>({configuration_revision:'same'})};};const a=app(undefined,{fetch});a.api.value='http://example.test:8001/';await a.events.focus();assert.equal(urls[0],'http://example.test:8001/simulation/configuration');const b=app(undefined,{fetch,noInput:true,search:'?backend_port=8001'});await b.events.focus();assert.equal(urls[1],'http://127.0.0.1:8001/simulation/configuration');});
test('pagehide aborts a pending request and pageshow restarts monitoring',async()=>{let resolve,signal;const a=app('old',{fetch:(_,options)=>{signal=options.signal;return new Promise(r=>resolve=r);}});const polling=a.events.focus();a.events.pagehide();assert.equal(signal.aborted,true);assert.equal(a.timers.size,1);resolve({ok:true,json:async()=>({configuration_revision:'new'})});await polling;assert.equal(a.reloads,0);assert.equal(a.timers.size,0);});
test('pageshow resumes checks after a cached page returns',async()=>{const a=app('new');a.events.pagehide();assert.equal(a.timers.size,0);a.events.pageshow();await flush();assert.equal(a.requests,1);assert.equal([...a.timers.values()].filter(t=>t.delay===15000).length,1);});
test('request timeout aborts the request without discarding state',async()=>{let signal;const a=app('old',{fetch:(_,options)=>{signal=options.signal;return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(Error('timeout'))));}});const polling=a.events.focus();[...a.timers.values()].find(t=>t.delay===10000).fn();await polling;assert.equal(signal.aborted,true);assert.equal(a.reloads,0);assert.notEqual(a.context.result,null);assert.equal([...a.timers.values()].filter(t=>t.delay===15000).length,1);});
