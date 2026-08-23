/* MotorCAD Studio V0.79-B — canonical ResultSet/Comparison Aggregate HTTP client. */
(() => {
  const CACHE_MAX=32,cache=new Map();
  const touch=(key,row)=>{cache.delete(key);cache.set(key,row);while(cache.size>CACHE_MAX)cache.delete(cache.keys().next().value)};
  const normalize=request=>{
    const ids=[...(request?.result_bundle_ids||[])].map(String).filter(Boolean);
    const baseline=String(request?.baseline_result_bundle_id||ids[0]||'');
    const objectives=(request?.objectives||[]).map(row=>({metric_id:String(row.metric_id||''),direction:String(row.direction||'')}));
    return {result_bundle_ids:ids,baseline_result_bundle_id:baseline||null,scope:String(request?.scope||'general'),objectives};
  };
  const keyOf=request=>JSON.stringify(normalize(request));
  async function compare(request,options={}){
    const body=normalize(request),key=keyOf(body),cached=cache.get(key),headers={'Content-Type':'application/json'};
    if(cached?.etag)headers['If-None-Match']=cached.etag;
    const response=await fetch('/api/result-set-aggregates/compare',{method:'POST',headers,body:JSON.stringify(body),signal:options.signal});
    if(response.status===304){if(!cached?.payload)throw new Error('ResultSet Aggregate 304 received without cached payload');touch(key,cached);return cached.payload;}
    const payload=await response.json().catch(()=>null);
    if(!response.ok)throw new Error(payload?.detail?.message||payload?.detail||payload?.message||`HTTP ${response.status}`);
    const row={etag:response.headers.get('etag'),payload};touch(key,row);return payload;
  }
  function clear(){cache.clear()}
  function info(){return {size:cache.size,max:CACHE_MAX,keys:[...cache.keys()]}}
  window.MCSResultSetAggregate=Object.freeze({compare,clear,info,normalize,CACHE_MAX});
})();
