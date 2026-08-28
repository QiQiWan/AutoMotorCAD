/* V0.89-G1 Global Shell + Typography + Copy Cleanup.
 * Presentation-only authority: it audits Guided copy/layout hooks and never rewrites domain IDs.
 */
(() => {
  const AUTHORITY='GlobalShellTypographyCopyConvergenceV1';
  const CONTRACT_VERSION='0.89-G3.1';
  const RAW_GUIDED_TOKENS=[
    'Current project','Create design in current project','Starting isolated preflight process',
    'Maximum 60 seconds','Design Revision','Motor Revision','Analysis Revision','Execution Plan','Native Binding','Native Closure','GeometryTree','NativeModelSnapshot','BindingPlan','ResultBundle'
  ];
  const allowedEnglish=/^(MotorCAD Studio|Motor-CAD|SPM|IPM|AFPM|BPM|EMag|FEA|RPM|rpm|kW|CSV|JSONL|DOE|Pareto)$/i;
  const visible=el=>{const style=getComputedStyle(el);const r=el.getBoundingClientRect();return style.display!=='none'&&style.visibility!=='hidden'&&r.width>0&&r.height>0};
  function audit(root=document){
    const mode=document.body?.dataset?.userMode||'operator';
    const lang=window.MCS_I18N?.language||document.documentElement.lang||'zh-CN';
    const issues=[];
    const shell=document.querySelector('#projectShell');
    const focus=document.querySelector('#engineerFocusBarV089F');
    if(shell&&focus&&visible(shell)&&visible(focus)){
      const sr=shell.getBoundingClientRect(),fr=focus.getBoundingClientRect();
      if(fr.right>sr.right+3||fr.left<sr.left-3)issues.push('FOCUS_BAR_OUTSIDE_SHELL');
      if(focus.scrollWidth>focus.clientWidth+2)issues.push('FOCUS_BAR_HORIZONTAL_OVERFLOW');
    }
    if(mode==='operator'&&String(lang).toLowerCase().startsWith('zh')){
      root.querySelectorAll?.('button,[role="button"],h1,h2,h3,p,span,small').forEach(el=>{
        if(!visible(el)||el.closest('.expert-only,.developer-only,code,pre'))return;
        const text=(el.textContent||'').trim();if(!text)return;
        RAW_GUIDED_TOKENS.forEach(token=>{if(text.includes(token))issues.push(`RAW_GUIDED_COPY:${token}`)});
        if(el.matches('button,[role="button"]')&&/[A-Za-z]{4,}/.test(text)&&!/[\u4e00-\u9fff]/.test(text)&&!allowedEnglish.test(text)){
          const normalized=text.replace(/[→←＋+×✓○·0-9\s/()_.:-]/g,'').trim();
          if(normalized&&/[A-Za-z]{4,}/.test(normalized)&&!/Motor-CAD|SPM|IPM|AFPM|BPM|EMag|FEA|CSV|DOE|Pareto/i.test(text))issues.push(`UNTRANSLATED_PRIMARY_ACTION:${text.slice(0,80)}`);
        }
      });
    }
    return {authority:AUTHORITY,contract_version:CONTRACT_VERSION,passed:issues.length===0,issues:[...new Set(issues)]};
  }
  function refresh(){
    document.body?.classList.add('studio-v089g1','studio-v089g3');
    const result=audit();
    document.dispatchEvent(new CustomEvent('mcs:global-shell-convergence-audit',{detail:result}));
    return result;
  }
  document.addEventListener('DOMContentLoaded',()=>requestAnimationFrame(refresh),{once:true});
  document.addEventListener('mcs-language-change',()=>requestAnimationFrame(refresh));
  window.addEventListener('mcs:route-ready',()=>requestAnimationFrame(refresh));
  window.MCSGlobalShellConvergence={authority:AUTHORITY,contractVersion:CONTRACT_VERSION,audit,refresh};
})();
