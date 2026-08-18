/* MotorCAD Studio V0.62 — frontend convergence primitives.
 * This module owns route/view semantics shared by the legacy-compatible design UI.
 * New code should depend on this API rather than introducing another DOM observer.
 */
(() => {
  const VIEW_ROUTES = Object.freeze({
    radial: ['geometry','radial'],
    axial: ['geometry','longitudinal'],
    winding: ['winding','pattern'],
    slot: ['winding','slot'],
    materials: ['materials'],
    native: ['validation'],
    evidence: ['validation'],
    compare: ['compare'],
  });
  const ROUTE_VIEWS = Object.freeze({
    'geometry/radial':'radial',
    'geometry/longitudinal':'axial',
    'geometry/axial':'axial',
    'winding/pattern':'winding',
    'winding/layout':'winding',
    'winding/slot':'slot',
    'materials':'materials',
    'validation':'evidence',
    'compare':'compare',
  });
  const STAGES = Object.freeze({
    geometry:{id:'geometry',label:'几何',description:'径向截面与纵向装配关系',views:['radial','axial'],defaultView:'radial'},
    winding:{id:'winding',label:'绕组',description:'相槽连接与槽内布置',views:['winding','slot'],defaultView:'winding'},
    materials:{id:'materials',label:'材料',description:'部件材料绑定与来源追溯',views:['materials'],defaultView:'materials'},
    validation:{id:'validation',label:'设计验证',description:'静态约束与 Motor-CAD 模型检查',views:['evidence','native'],defaultView:'native'},
  });
  function stageForView(view){return Object.values(STAGES).find(stage=>stage.views.includes(view))?.id||(view==='compare'?'compare':'geometry')}
  function routeSegmentsForView(view){return VIEW_ROUTES[view]||VIEW_ROUTES.radial}
  function viewForRoute(section,subview){return ROUTE_VIEWS[[section,subview].filter(Boolean).join('/')]||null}
  function emit(name,detail={}){window.dispatchEvent(new CustomEvent(name,{detail}))}
  window.MCSAppCoreV062={VIEW_ROUTES,ROUTE_VIEWS,STAGES,stageForView,routeSegmentsForView,viewForRoute,emit};
  document.documentElement.dataset.frontendConvergence='v062';
  document.body?.classList.add('studio-v062');
})();
