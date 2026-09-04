/* Collapse low-frequency page guidance without removing it from the workflow. */
(() => {
  const SELECTORS='.canonical-stage-hero,.project-manager-toolbar,.template-stage-header,.monitor-toolbar,.analytics-toolbar';
  const tr=(zh,en)=>window.MCS_I18N?.t?.(zh,en)??zh;
  function summaryLabel(){return tr('说明','Help')}
  function enhance(host){
    if(!host||host.dataset.compactFlowHeaderV089g4==='1')return;
    const lead=host.firstElementChild,description=lead?.querySelector?.(':scope > p');
    if(!lead||!description)return;
    let actions=[...host.children].find(node=>node.classList?.contains('actions'));
    if(!actions){actions=document.createElement('div');actions.className='actions';[...host.children].slice(1).forEach(node=>actions.appendChild(node));host.appendChild(actions)}
    const details=document.createElement('details');details.className='compact-flow-help-v089g4';
    const summary=document.createElement('summary');summary.textContent=summaryLabel();summary.dataset.compactHelpLabelV089g4='1';
    details.append(summary,description);actions.prepend(details);
    host.classList.add('compact-flow-header-v089g4');host.dataset.compactFlowHeaderV089g4='1';
  }
  function refresh(root=document){root.querySelectorAll?.(SELECTORS).forEach(enhance);root.querySelectorAll?.('[data-compact-help-label-v089g4]').forEach(node=>{node.textContent=summaryLabel()})}
  document.addEventListener('DOMContentLoaded',()=>{refresh();new MutationObserver(records=>records.forEach(record=>record.addedNodes.forEach(node=>{if(node.nodeType===Node.ELEMENT_NODE){if(node.matches?.(SELECTORS))enhance(node);refresh(node)}}))).observe(document.body,{childList:true,subtree:true})},{once:true});
  document.addEventListener('mcs-language-change',()=>refresh());
  window.MCSCompactFlowHeader={refresh};
})();
