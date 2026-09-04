/* Current stable runtime ownership map. Production code must bind only stable controller names. */
(() => {
  const ownership = {release:'current',policy:'stable-owner-only',owners:{},rebound:[],missing:[]};
  const own=(key,name)=>{if(window[name]) ownership.owners[key]=name; else ownership.missing.push(name)};
  const bind=(globalName,controllerName,methodName)=>{
    const controller=window[controllerName];
    if(controller && typeof controller[methodName]==='function'){
      window[globalName]=(...args)=>controller[methodName](...args);
      ownership.rebound.push(globalName);
    }
  };
  bind('openCaseViewer','MCSCaseViewer','openCaseViewer');
  bind('closeCaseViewer','MCSCaseViewer','closeCaseViewer');
  bind('loadCaseViewer','MCSCaseViewer','loadCaseViewer');
  bind('renderCaseViewer','MCSCaseViewer','renderCaseViewer');
  bind('startEditDesign','MCSDesignViewer','startEditDesign');
  bind('saveRevision','MCSDesignViewer','saveRevision');
  bind('cancelEditDesign','MCSDesignViewer','cancelEditDesign');
  bind('selectWorkspaceRevision','MCSDesignViewer','selectWorkspaceRevision');
  bind('decorateDesignViewer','MCSDesignViewer','decorate');
  [
    ['appCore','MCSAppCore'],['engineeringWorkflow','MCSEngineeringWorkflow'],
    ['resultsWorkbench','MCSResultsWorkbench'],['caseCompare','MCSCaseCompare'],
    ['revisionCompare','MCSRevisionCompare'],['resultTrust','MCSResultsTrust'],
    ['caseViewer','MCSCaseViewer'],['optimizationWorkbench','MCSOptimizationWorkbench'],
    ['experimentLifecycle','MCSExperimentLifecycle'],['routeControllers','MCSRouteControllers'],
    ['operatorFlow','MCSOperatorFlow'],['analysisMonitor','MCSAnalysisMonitor'],
    ['motorDomain','MCSMotorDomain'],['motorObject','MCSMotorObject'],
    ['pmMotorObject','MCSPMMotorObject'],['inductionMotorObject','MCSInductionMotorObject'],
    ['nativeQualification','MCSNativeClosure'],['runtimeLifecycleQualification','MCSRuntimeLifecycleQualification']
  ].forEach(([key,name])=>own(key,name));
  window.MCSRuntimeOwnership=Object.freeze(ownership);
  window.dispatchEvent(new CustomEvent('mcs:runtime-ownership-ready',{detail:ownership}));
})();
