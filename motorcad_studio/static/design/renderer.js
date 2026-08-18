/* V0.64 Design renderer facade. Stable modules own presentation; controllers own state and lifecycle. */
(() => {
  function renderWorkbenchView(view,ctx){
    const geometry=window.MCSDesignGeometry?.render?.(view,ctx);if(geometry!==null&&geometry!==undefined)return geometry;
    const winding=window.MCSDesignWinding?.render?.(view,ctx);if(winding!==null&&winding!==undefined)return winding;
    const materials=window.MCSDesignMaterials?.render?.(view,ctx);if(materials!==null&&materials!==undefined)return materials;
    return null;
  }
  function renderAuxiliaryView(view,data){return window.MCSDesignValidation?.render?.(view,data)??null}
  function renderReadOnlyPanel(view,data,options){return window.MCSDesignParameterInspector?.readOnlyPanel?.(view,data,options)||''}
  window.MCSDesignRenderer={renderWorkbenchView,renderAuxiliaryView,renderReadOnlyPanel};
})();
