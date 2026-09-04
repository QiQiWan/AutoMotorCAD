/* MotorCAD Studio V0.70 — typed motor-domain browser boundary.
 * The server owns MotorSnapshot semantics.  Browser code consumes immutable
 * snapshots/change-impact contracts and no longer needs to infer ownership from
 * ad-hoc parameter-name conditions.
 */
(() => {
  const catalogCache={value:null,promise:null};
  const snapshots=new Map();
  const safeId=value=>encodeURIComponent(String(value||''));

  async function catalog(options={}){
    if(catalogCache.value&&!options.refresh)return catalogCache.value;
    if(catalogCache.promise&&!options.refresh)return catalogCache.promise;
    catalogCache.promise=api('/api/motor-domain/catalog',options.signal?{signal:options.signal}:{})
      .then(payload=>{catalogCache.value=payload;return payload})
      .finally(()=>{catalogCache.promise=null});
    return catalogCache.promise;
  }
  async function snapshot(revisionId,options={}){
    const key=String(revisionId||'');if(!key)throw new Error('design revision id is required');
    if(snapshots.has(key)&&!options.refresh)return snapshots.get(key);
    const payload=await api(`/api/design-revisions/${safeId(key)}/motor-snapshot`,options.signal?{signal:options.signal}:{});
    snapshots.set(key,payload);
    return payload;
  }
  async function previewChangeImpact(revisionId,parameters,explicitParameterIds=[],options={}){
    const payload=await api(`/api/design-revisions/${safeId(revisionId)}/motor-snapshot/change-impact`,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({parameters:parameters||{},explicit_parameter_ids:explicitParameterIds||[]}),
      ...(options.signal?{signal:options.signal}:{})
    });
    window.dispatchEvent(new CustomEvent('mcs:motor-domain-impact',{detail:payload}));
    return payload;
  }
  async function backfillProject(projectId,options={}){
    return api(`/api/projects/${safeId(projectId)}/motor-domain/backfill`,{
      method:'POST',
      ...(options.signal?{signal:options.signal}:{})
    });
  }
  function invalidateRevision(revisionId){snapshots.delete(String(revisionId||''))}
  function identityOf(value){return value?.snapshot?.identity||value?.motor_snapshot?.identity||value?.identity||null}
  function parameterValue(value,parameterId,fallback=null){
    const snapshotValue=value?.snapshot||value?.motor_snapshot||value;
    const parameters=snapshotValue?.parameters||{};
    if(Object.prototype.hasOwnProperty.call(parameters.values||{},parameterId))return parameters.values[parameterId];
    if(Object.prototype.hasOwnProperty.call(parameters.unknown_values||{},parameterId))return parameters.unknown_values[parameterId];
    return fallback;
  }
  window.MCSMotorDomain={catalog,snapshot,previewChangeImpact,backfillProject,invalidateRevision,identityOf,parameterValue};
})();
