/* MotorCAD Studio V0.79-A — canonical ResultBundle Aggregate HTTP client. */
(() => {
  const CACHE_MAX=64,cache=new Map();
  const clean=value=>String(value??'').trim();
  const normalizeInclude=value=>{
    const tokens=String(value||'').split(',').map(x=>x.trim().toLowerCase()).filter(Boolean);
    return [...new Set(tokens)].sort().join(',');
  };
  const keyFor=(bundleId,include)=>`${clean(bundleId)}|${normalizeInclude(include)}`;
  const touch=(key,value)=>{cache.delete(key);cache.set(key,value);while(cache.size>CACHE_MAX)cache.delete(cache.keys().next().value);};
  async function parseError(response){let body=null;try{body=await response.json()}catch{try{body={detail:await response.text()}}catch{body={}}}const detail=body?.detail;const message=typeof detail==='string'?detail:(detail?.message||detail?.code||`HTTP ${response.status}`);const error=new Error(message);error.status=response.status;error.detail=detail;return error;}
  async function get(resultBundleId,options={}){
    const bundleId=clean(resultBundleId);if(!bundleId)throw new Error('resultBundleId is required');
    const include=normalizeInclude(options.include),key=keyFor(bundleId,include),cached=cache.get(key)||null;
    const query=include?`?include=${encodeURIComponent(include)}`:'';
    const headers={Accept:'application/json',...(options.headers||{})};if(cached?.etag)headers['If-None-Match']=cached.etag;
    const response=await fetch(`/api/result-bundles/${encodeURIComponent(bundleId)}/aggregate${query}`,{signal:options.signal,headers});
    if(response.status===304){if(!cached?.payload)throw new Error('Aggregate 304 received without cached payload');touch(key,cached);return cached.payload;}
    if(!response.ok)throw await parseError(response);
    const payload=await response.json(),etag=response.headers.get('ETag');touch(key,{etag,payload});return payload;
  }
  function clear(resultBundleId=null){if(!resultBundleId){cache.clear();return;}const prefix=`${clean(resultBundleId)}|`;for(const key of [...cache.keys()])if(key.startsWith(prefix))cache.delete(key);}
  function info(){return{entries:cache.size,maxEntries:CACHE_MAX,keys:[...cache.keys()]};}
  window.MCSResultBundleAggregate=Object.freeze({get,clear,info,CACHE_MAX});
})();
