/* V0.64 read-only Design Viewer controller.
 * Owns Design view lifecycle, route restoration and stale-request cancellation.
 * Stable renderer modules own markup; Draft editing remains in the compatibility controller for now.
 */
(() => {
  const $q=(selector,root=document)=>root.querySelector(selector);
  const safe=value=>window.MCSDesignRenderUtils?.safe?.(value)??String(value??'');
  const visualState={designId:null,revisionId:null,data:null,view:'radial',visualSource:'auto',selectedParameter:null,requestedView:null,requestToken:0,abortController:null};

  function designStageForView(view){return window.MCSAppCore?.stageForView?.(view)||(view==='winding'||view==='slot'?'winding':view==='materials'?'materials':['evidence','native'].includes(view)?'validation':view==='compare'?'compare':'geometry')}
  function availableDesignViews(data){return new Set((data?.design_views||[]).filter(row=>row.available).map(row=>row.id))}
  function stageSubviewRows(stage,data){
    const available=availableDesignViews(data),lookup=new Map((data?.design_views||[]).map(row=>[row.id,row]));
    const ids=stage==='geometry'?['radial','axial']:stage==='winding'?['winding','slot']:stage==='materials'?['materials']:stage==='validation'?['evidence']:[];
    const labelOverride={winding:'绕组连接',slot:'槽内定义',materials:'材料配置',evidence:'模型检查'};
    return ids.filter(id=>available.has(id)).map(id=>({...lookup.get(id),label:labelOverride[id]||lookup.get(id)?.label||id}));
  }
  function renderDesignNavigation(){
    const data=visualState.data,stageBox=$q('#designStageNavV062'),subBox=$q('#designSubviewNavV062');if(!data||!stageBox||!subBox)return;
    if(window.MCSDesignNavigation?.render){window.MCSDesignNavigation.render({stageBox,subBox,data,view:visualState.view,mode:'read',variant:'viewer'});return;}
    const stage=designStageForView(visualState.view),available=availableDesignViews(data),stages=[
      ['geometry','几何','径向与纵向装配',['radial','axial']],['winding','绕组','相槽连接与槽内布置',['winding','slot']],['materials','材料','部件材料绑定',['materials']],['validation','设计验证','模型检查与计算依据',['evidence']],
    ];
    stageBox.innerHTML=`<div class="design-stage-main-v062">${stages.map(([id,label,desc,views],index)=>{const enabled=views.some(v=>available.has(v));return`<button type="button" data-design-stage-v062="${id}" class="${stage===id?'active':''}" ${enabled?'':'disabled'}><span>${index+1}</span><b>${label}</b><small>${desc}</small></button>`}).join('')}</div>`;
    const rows=stageSubviewRows(stage,data);subBox.innerHTML=rows.length>1?rows.map(row=>`<button type="button" data-design-view-v031="${safe(row.id)}" class="${row.id===visualState.view?'active':''}">${safe(row.label)}</button>`).join(''):'';
  }
  function chooseStage(stage,data){return window.MCSDesignNavigation?.defaultViewForStage?.(stage,data,{mode:'read'})||stageSubviewRows(stage,data)[0]?.id||null}
  function designNextStep(view,data){
    const next=window.MCSDesignNavigation?.next?.(view,data,{mode:'read'});if(!next)return'';
    return`<div class="design-next-step-v061 design-next-step-v062 design-next-step-v063 design-next-step-v064"><div><span>推荐下一步</span><b>${safe(next.label)}</b><small>按“几何 → 绕组 → 材料 → 设计验证 → 分析设置”的单一路径继续。</small></div><button type="button" class="primary" data-design-next-v061="${safe(next.target)}">${safe(next.label)} →</button></div>`;
  }

  function savedTransactionStrip(data){
    const tx=data?.editor_transaction||{},native=data?.native_reconciliation||{};
    const status=String(native.status||'UNCHECKED').toUpperCase();
    const label={CURRENT:'保存时已与 Motor-CAD 对齐',DRIFT:'保存时 Native 存在漂移',PARTIAL:'保存时 Native 证据不完整',FAILED:'保存时 Native 检查失败',UNCHECKED:'保存时未取得 Native 证据'}[status]||status;
    const tone=status==='CURRENT'?'current':(['DRIFT','FAILED'].includes(status)?'error':'pending');
    return `<div class="saved-transaction-strip-v088d"><div><span>当前设计</span><b>已保存 · 不可变历史</b></div><div class="${safe(tone)}"><span>Motor-CAD 协调状态</span><b>${safe(label)}</b></div><div><span>来源事务</span><b>${tx.transaction_id?safe(String(tx.transaction_id).replace(/^EDT-/,'').slice(-8)):'历史版本'}</b></div><div><span>模板</span><b>只读</b></div></div>`;
  }

  function renderDesignView(){
    const data=visualState.data,stage=$q('#designViewStageV031'),panel=$q('#designParamPanelV031');if(!data||!stage||!panel)return;
    window.MCSDesignStore?.setContext?.({projectId:state.activeProjectId||null,designId:visualState.designId,revisionId:visualState.revisionId,mode:'read',view:visualState.view,selectedParameter:visualState.selectedParameter,data},{source:'viewer-render'});
    renderDesignNavigation();
    const reconciliation=data.visualization_reconciliation||{};
    const effectiveSource=window.MCSDesignRenderer?.resolveVisualSource?.(reconciliation,visualState.visualSource,'read')||'design';
    const ctx={data,values:data.effective_parameters||{},precheck:data.precheck||{},editable:false,selected:visualState.selectedParameter,visualSource:effectiveSource,visualizationReconciliation:reconciliation};
    const auxiliary=window.MCSDesignRenderer?.renderAuxiliaryView?.(visualState.view,data);
    const toolbar=['radial','axial','winding','slot','materials'].includes(visualState.view)?(window.MCSDesignRenderer?.toolbar?.(data,{source:visualState.visualSource,mode:'read',reconciliation})||''):'';
    const rendered=auxiliary??window.MCSDesignRenderer?.renderWorkbenchView?.(visualState.view,ctx)??'<div class="native-empty-v031">当前视图不可用。</div>';
    stage.innerHTML=toolbar+rendered;
    panel.innerHTML=window.MCSDesignRenderer?.renderReadOnlyPanel?.(visualState.view,data,{selectedParameter:visualState.selectedParameter})||'';
    stage.insertAdjacentHTML('beforeend',designNextStep(visualState.view,data));
    window.MCSAppCore?.emit?.('mcs:workspace-rendered',{designId:visualState.designId,revisionId:visualState.revisionId,view:visualState.view,editing:false});
  }

  async function openEvidenceCase(caseId){
    if(!caseId)return;
    const taskId=String(caseId).split('-C')[0],projectId=state.activeProjectId;
    if(projectId&&taskId&&window.MCSRouter?.navigate){
      await window.MCSRouter.navigate(`/app/projects/${encodeURIComponent(projectId)}/results/tasks/${encodeURIComponent(taskId)}/cases/${encodeURIComponent(caseId)}`);
      return;
    }
    if(typeof window.showTab==='function')await Promise.resolve(window.showTab('resultViewer'));
    const taskSelect=$q('#viewerTaskSelect');if(taskSelect&&taskId){taskSelect.value=taskId;await window.loadViewerCases?.(taskId,null,{autoOpen:false});}
    const caseSelect=$q('#viewerCaseSelect');if(caseSelect&&[...caseSelect.options].some(option=>option.value===caseId)){caseSelect.value=caseId;await window.openCaseViewer?.();}
  }

  function setView(target,{source='viewer',replace=true}={}){
    if(!target||!availableDesignViews(visualState.data).has(target))return false;
    visualState.view=target;visualState.requestedView=target;visualState.selectedParameter=null;
    window.MCSDesignStore?.setView?.(target,{source});renderDesignView();window.MCSRouter?.syncDesignView?.(target,{replace});return true;
  }

  function bindDesignViewer(root){
    if(root.dataset.designViewerBoundV064)return;root.dataset.designViewerBoundV064='1';
    root.addEventListener('click',event=>{
      const sourceButton=event.target.closest('[data-visual-source-v088e]');if(sourceButton){visualState.visualSource=sourceButton.dataset.visualSourceV088e||'auto';renderDesignView();return;}
      const caseButton=event.target.closest('[data-open-evidence-case-v057]');if(caseButton){openEvidenceCase(caseButton.dataset.openEvidenceCaseV057);return;}
      const stageButton=event.target.closest('[data-design-stage-v062]');if(stageButton){const target=chooseStage(stageButton.dataset.designStageV062,visualState.data);if(target)setView(target,{source:'viewer-stage'});return;}
      const tab=event.target.closest('[data-design-view-v031]');if(tab){setView(tab.dataset.designViewV031,{source:'viewer-tab'});return;}
      const next=event.target.closest('[data-design-next-v061]');if(next){const target=next.dataset.designNextV061;if(target==='input_data'){const id=window.MCSEngineeringContext?.get?.().analysisId;if(id&&state.activeProjectId)return window.MCSRouter?.navigate?.(`/app/projects/${encodeURIComponent(state.activeProjectId)}/simulation/analyses/${encodeURIComponent(id)}/configure/inputs`);return window.showTab?.('analysisConfig');}setView(target,{source:'viewer-next'});return;}
      const parameter=event.target.closest('[data-design-parameter-v031]');if(parameter){visualState.selectedParameter=parameter.dataset.designParameterV031;window.MCSDesignStore?.selectParameter?.(visualState.selectedParameter,{source:'viewer-parameter'});renderDesignView();return;}
      const edit=event.target.closest('[data-edit-view-v031]');if(edit){const spec=(visualState.data?.design_views||[]).find(row=>row.id===edit.dataset.editViewV031),first=visualState.selectedParameter||(spec?.parameter_ids||[])[0]||null;window.MCSDesignEditor?.openView?.(edit.dataset.editViewV031,first);}
    });
  }

  function abortPending(){if(visualState.abortController){visualState.abortController.abort();visualState.abortController=null}}
  async function decorateDesignViewer(routeCtx=null){
    if(routeCtx?.signal?.aborted)return;
    const revision=state.workspaceRevision,layout=$q('#workspaceCanvas .design-visual-layout');if(!revision||!layout)return;
    abortPending();const controller=new AbortController();visualState.abortController=controller;
    if(routeCtx?.signal)routeCtx.signal.addEventListener('abort',()=>controller.abort(),{once:true});
    const token=++visualState.requestToken,revisionId=revision.id;
    try{
      const data=await api(`/api/design-revisions/${encodeURIComponent(revisionId)}/workbench`,{signal:controller.signal});
      if(controller.signal.aborted||token!==visualState.requestToken||state.workspaceRevision?.id!==revisionId||(routeCtx&&!window.MCSPageRuntime?.isContextActive?.(routeCtx)))return;
      const designId=state.workspaceDesign?.id||null,available=availableDesignViews(data),preferred=(data.design_views||[]).find(row=>row.preferred&&row.available)?.id||(data.design_views||[]).find(row=>row.available)?.id||'radial';
      const requested=visualState.requestedView&&available.has(visualState.requestedView)?visualState.requestedView:null;
      const routed=available.has(window.MCSDesignStore?.currentView?.())?window.MCSDesignStore.currentView():null;
      const preserved=visualState.designId===designId&&visualState.revisionId===revisionId&&available.has(visualState.view)?visualState.view:null;
      const identityChanged=visualState.designId!==designId||visualState.revisionId!==revisionId;
      if(identityChanged)visualState.visualSource='auto';
      visualState.designId=designId;visualState.revisionId=revisionId;visualState.data=data;visualState.view=requested||routed||preserved||preferred;visualState.requestedView=null;if(identityChanged)visualState.selectedParameter=null;
      window.MCSDesignStore?.setContext?.({projectId:state.activeProjectId||null,designId,revisionId,mode:'read',view:visualState.view,selectedParameter:visualState.selectedParameter,data},{source:'viewer-load'});
      const oldCard=layout.querySelector('.design-schematic-card');let root=$q('#designViewerV031');
      if(!root){root=document.createElement('section');root.id='designViewerV031';root.className='design-viewer-v031 design-viewer-v064';oldCard?.replaceWith(root);bindDesignViewer(root)}
      layout.classList.add('design-visual-layout-v031');
      root.innerHTML=`${savedTransactionStrip(data)}<div class="design-navigation-v062"><div id="designStageNavV062" class="design-stage-nav-v062" aria-label="电机设计步骤"></div><div id="designSubviewNavV062" class="design-subview-nav-v062" aria-label="当前设计步骤视图"></div></div><div class="design-view-body-v031"><div id="designViewStageV031" class="design-view-stage-v031"></div><div id="designParamPanelV031"></div></div>`;
      const summary=$q('#workspaceRevisionSummary');if(summary&&!summary.dataset.v031Wrapped){const original=summary.innerHTML;summary.innerHTML=`<details class="revision-trace-v031"><summary><span><b>设计版本参数与追溯信息</b><small>完整参数快照、内容哈希与创建时间</small></span></summary><div>${original}</div></details>`;summary.dataset.v031Wrapped='1'}
      renderDesignView();
    }catch(error){if(controller.signal.aborted||window.MCSPageRuntime?.isAbortError?.(error))return;console.warn('design visual workspace',error)}
    finally{if(visualState.abortController===controller)visualState.abortController=null}
  }

  function applyRouteView(route){
    let requested=route?.designView||window.MCSAppCore?.viewForRoute?.(route?.designSection,route?.designSubview);if(requested==='native')requested='evidence';if(!requested)return;
    visualState.requestedView=requested;window.MCSDesignStore?.setView?.(requested,{source:'route-view'});
    if(visualState.data&&availableDesignViews(visualState.data).has(requested)){visualState.view=requested;visualState.selectedParameter=null;renderDesignView()}
  }

  const previousOpenWorkspaceDesign=window.openWorkspaceDesign;
  let ownedOpenWorkspaceDesign=previousOpenWorkspaceDesign;
  if(typeof previousOpenWorkspaceDesign==='function'){
    ownedOpenWorkspaceDesign=async function(){
      const args=[...arguments],routeCtx=args[1]&&typeof args[1]==='object'?args[1]:null,result=await previousOpenWorkspaceDesign.apply(this,args);
      if(result&&(!routeCtx||window.MCSPageRuntime?.isContextActive?.(routeCtx)))await decorateDesignViewer(routeCtx);return result;
    };
    window.openWorkspaceDesign=ownedOpenWorkspaceDesign;
  }
  const previousSelectWorkspaceRevision=window.selectWorkspaceRevision;
  let ownedSelectWorkspaceRevision=previousSelectWorkspaceRevision;
  if(typeof previousSelectWorkspaceRevision==='function'){
    ownedSelectWorkspaceRevision=function(){
      const result=previousSelectWorkspaceRevision.apply(this,arguments),summary=$q('#workspaceRevisionSummary');if(summary)delete summary.dataset.v031Wrapped;decorateDesignViewer();return result;
    };
    window.selectWorkspaceRevision=ownedSelectWorkspaceRevision;
  }

  window.addEventListener('mcs:route-ready',event=>{const route=event.detail?.route||event.detail||null;if(route?.designView&&route.designView!==visualState.view)applyRouteView(route);if($q('.tab.active')?.id==='workspace'&&state.workspaceRevision&&(!visualState.data||visualState.revisionId!==state.workspaceRevision.id))decorateDesignViewer()});
  document.addEventListener('mcs-language-change',()=>{if(visualState.data)renderDesignView()});
  window.MCSDesignViewer={state:visualState,decorate:decorateDesignViewer,render:renderDesignView,applyRouteView,setView,abort:abortPending,openWorkspaceDesign:ownedOpenWorkspaceDesign,selectWorkspaceRevision:ownedSelectWorkspaceRevision};
  // Compatibility boundary for callers cached from pre-V0.64 runtime layers.
  // Keep one stable global alias until the remaining historical scripts are removed.
  window.decorateDesignViewer=decorateDesignViewer;
})();
