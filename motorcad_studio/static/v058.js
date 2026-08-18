/* MotorCAD Studio V0.58.0 — usability and reliability closure. */
(() => {
  const q=(selector,root=document)=>root.querySelector(selector);
  const qa=(selector,root=document)=>[...root.querySelectorAll(selector)];

  function simplifyViewerInspector(){
    const inspector=q('#viewerInspector');if(!inspector)return;
    qa('small',inspector).forEach(node=>{if(/PyMotorCAD API/i.test(node.textContent||''))node.remove()});
    qa('code',inspector).forEach(node=>node.remove());
    qa('.property-grid span',inspector).forEach(label=>{
      if((label.textContent||'').trim()!=='Result ID')return;
      const value=label.nextElementSibling;label.remove();value?.remove();
    });
  }

  const previousViewer=window.renderViewerModule;
  if(typeof previousViewer==='function')window.renderViewerModule=function(){
    const result=previousViewer.apply(this,arguments);simplifyViewerInspector();return result;
  };

  document.addEventListener('click',event=>{
    if(event.target.closest?.('[data-viewer-scalar]'))queueMicrotask(simplifyViewerInspector);
  });
  document.body.classList.add('studio-v058');
  window.MCSV058={simplifyViewerInspector};
})();
