/* MotorCAD Studio V0.80-A — Chunk-native Result Data Gateway V2 browser client. */
(()=>{
  const CACHE_MAX=48,cache=new Map(),manifestCache=new Map(),chunkCache=new Map();
  function key(bundleId,resultId,offset,limit){return `${bundleId}:${resultId}:${offset??0}:${limit??'all'}`}
  function remember(store,k,v,max=CACHE_MAX){store.delete(k);store.set(k,v);while(store.size>max)store.delete(store.keys().next().value)}
  async function requestJson(url,prior,signal){
    const headers={};if(prior?.etag)headers['If-None-Match']=prior.etag;
    const response=await fetch(url,{headers,signal,credentials:'same-origin'});
    if(response.status===304&&prior)return prior;
    if(!response.ok){let detail='';try{const body=await response.json();detail=typeof body?.detail==='string'?body.detail:JSON.stringify(body?.detail||body)}catch(_){detail=await response.text()}throw new Error(detail||`HTTP ${response.status}`)}
    return {etag:response.headers.get('ETag'),payload:await response.json()};
  }
  async function get(bundleId,resultId,{offset=0,limit=null,signal=null,force=false}={}){
    if(!bundleId||!resultId)throw new Error('result bundle/result id required');
    const k=key(bundleId,resultId,offset,limit),prior=force?null:cache.get(k),params=new URLSearchParams();
    if(offset)params.set('offset',String(offset));if(limit!==null&&limit!==undefined)params.set('limit',String(limit));
    const url=`/api/result-bundles/${encodeURIComponent(bundleId)}/results/${encodeURIComponent(resultId)}/data${params.size?`?${params}`:''}`;
    const entry=await requestJson(url,prior,signal);remember(cache,k,entry);return entry.payload;
  }
  async function manifest(bundleId,resultId,{signal=null,force=false}={}){
    if(!bundleId||!resultId)throw new Error('result bundle/result id required');
    const k=`${bundleId}:${resultId}`,prior=force?null:manifestCache.get(k);
    const url=`/api/result-bundles/${encodeURIComponent(bundleId)}/results/${encodeURIComponent(resultId)}/data/manifest`;
    const entry=await requestJson(url,prior,signal);remember(manifestCache,k,entry,24);return entry.payload;
  }
  async function chunk(bundleId,resultId,chunkIndex,{signal=null,force=false}={}){
    if(!bundleId||!resultId)throw new Error('result bundle/result id required');
    const index=Number(chunkIndex);if(!Number.isInteger(index)||index<0)throw new Error('valid chunk index required');
    const k=`${bundleId}:${resultId}:${index}`,prior=force?null:chunkCache.get(k);
    const url=`/api/result-bundles/${encodeURIComponent(bundleId)}/results/${encodeURIComponent(resultId)}/data/chunks/${index}`;
    const entry=await requestJson(url,prior,signal);remember(chunkCache,k,entry,48);return entry.payload;
  }
  function clear(bundleId=null){
    if(!bundleId){cache.clear();manifestCache.clear();return}
    for(const store of [cache,manifestCache,chunkCache])for(const k of [...store.keys()])if(k.startsWith(`${bundleId}:`))store.delete(k);
  }
  function info(){return {entries:cache.size,manifestEntries:manifestCache.size,chunkEntries:chunkCache.size,max:CACHE_MAX,contract:'0.80-A',chunkNative:true}}
  window.MCSResultDataGateway=Object.freeze({get,manifest,chunk,clear,info,CACHE_MAX});
})();
