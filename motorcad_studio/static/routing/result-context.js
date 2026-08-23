/* V0.78 ResultBundle-first Result Context
 * Result identity is ExecutionPlan -> Task -> Case -> ResultBundle. An authoritative
 * backend EngineeringLineage is applied atomically to the Engineering Context Store,
 * with browser-side ETag revalidation for lineage requests.
 */
(() => {
  let cached=null;
  const httpCache=new Map(),HTTP_CACHE_MAX=128;
  function cacheHttp(path,entry){httpCache.delete(path);httpCache.set(path,entry);while(httpCache.size>HTTP_CACHE_MAX)httpCache.delete(httpCache.keys().next().value)}
  const store=()=>window.MCSEngineeringContext;
  async function requestLineage(path,ctx){
    const cachedHttp=httpCache.get(path)||null;
    const canUseHttp=typeof fetch==='function'&&/^https?:$/.test(location.protocol||'');
    if(canUseHttp){
      const headers={Accept:'application/json'};if(cachedHttp?.etag)headers['If-None-Match']=cachedHttp.etag;
      const response=await fetch(path,{method:'GET',headers,signal:ctx?.signal,cache:'no-cache'});ctx?.assertActive?.();
      if(response.status===304&&cachedHttp?.lineage)return cachedHttp.lineage;
      if(!response.ok){let body={};try{body=await response.json()}catch{}const error=new Error(body?.detail||`Lineage request failed (${response.status})`);error.status=response.status;throw error}
      const lineage=await response.json(),etag=response.headers.get('ETag');
      if(etag&&lineage?.integrity?.valid!==false)cacheHttp(path,{etag,lineage});else httpCache.delete(path);
      return lineage;
    }
    const api=ctx?.api||window.api;if(typeof api!=='function')throw new Error('API client unavailable');
    return api(path);
  }
  async function fetchLineage(path,ctx){
    const lineage=await requestLineage(path,ctx);ctx?.assertActive?.();
    if(lineage?.integrity?.valid===false){const error=new Error(`Engineering lineage invalid: ${(lineage.integrity.issues||[]).join('; ')}`);error.code='ENGINEERING_LINEAGE_INVALID';error.lineage=lineage;throw error}
    if(!lineage?.identity)throw new Error('Engineering lineage identity missing');return lineage;
  }
  function commit(lineage,source){const snapshot=store()?.applyLineage?.(lineage,{source})||null;cached=lineage;window.dispatchEvent(new CustomEvent('mcs:result-context-resolved',{detail:{lineage,context:snapshot,source}}));return snapshot}
  async function resolve(path,ctx,{source='result-context'}={}){return commit(await fetchLineage(path,ctx),source)}
  const q=value=>encodeURIComponent(String(value));
  async function resolveExecutionPlan(id,ctx,options={}){return resolve(`/api/execution-plans/${q(id)}/engineering-lineage`,ctx,{source:options.source||'result-context:execution-plan'})}
  async function resolveTask(id,ctx,options={}){return resolve(`/api/tasks/${q(id)}/engineering-lineage`,ctx,{source:options.source||'result-context:task'})}
  async function resolveCase(id,ctx,options={}){return resolve(`/api/cases/${q(id)}/engineering-lineage`,ctx,{source:options.source||'result-context:case'})}
  async function resolveBundle(id,ctx,options={}){return resolve(`/api/result-bundles/${q(id)}/engineering-lineage`,ctx,{source:options.source||'result-context:bundle'})}
  async function resolveIdentity(identity,ctx,options={}){const params=new URLSearchParams();for(const [key,value] of Object.entries(identity||{}))if(value)params.set(key,value);return resolve(`/api/engineering-lineage?${params}`,ctx,{source:options.source||'result-context:identity'})}
  function current(){const s=store()?.get?.()||{};return{projectId:s.projectId,solutionId:s.solutionId,motorRevisionId:s.motorRevisionId,analysisId:s.analysisId,analysisRevisionId:s.analysisRevisionId,executionPlanId:s.executionPlanId,taskId:s.taskId,caseId:s.caseId,resultBundleId:s.resultBundleId,lineage:s.lineage||cached}}
  function clear({http=false}={}){cached=null;if(http)httpCache.clear();store()?.invalidate?.('results',{source:'result-context:clear'})}
  function httpCacheInfo(){return{entries:httpCache.size,maxEntries:HTTP_CACHE_MAX,keys:[...httpCache.keys()]}}
  window.MCSResultContext=Object.freeze({resolveExecutionPlan,resolveTask,resolveCase,resolveBundle,resolveIdentity,current,clear,httpCacheInfo});
})();
