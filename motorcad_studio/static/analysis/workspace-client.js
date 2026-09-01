/* V0.89-G4.1 bounded Analysis workspace transport.
 * UI controllers consume one editor bundle and one commit response instead of
 * assembling the same state through multiple sequential history-heavy calls.
 */
(() => {
  const encode=value=>encodeURIComponent(String(value??''));
  function create(apiCall){
    if(typeof apiCall!=='function')throw new Error('Analysis workspace client requires an API function');
    return Object.freeze({
      bootstrap(projectId,selectedRevisionId=null){return apiCall(`/api/projects/${encode(projectId)}/analysis-workspace${selectedRevisionId?`?selected_revision_id=${encode(selectedRevisionId)}`:''}`)},
      editor(analysisId){return apiCall(`/api/analysis-definitions/${encode(analysisId)}/editor`)},
      createRevision(analysisId,payload){return apiCall(`/api/analysis-definitions/${encode(analysisId)}/editor/revisions`,{method:'POST',body:JSON.stringify(payload)})},
      updateInputDomain(analysisId,domainId,payload){return apiCall(`/api/analysis-definitions/${encode(analysisId)}/editor/input-domains/${encode(domainId)}`,{method:'PUT',body:JSON.stringify(payload)})},
    });
  }
  window.MCSAnalysisWorkspaceClient=Object.freeze({create});
})();
