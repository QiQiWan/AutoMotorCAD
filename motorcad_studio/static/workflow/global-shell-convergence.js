/* Global shell convergence authority.
 * Keeps the project identity, Design/Validate/Decide navigation and actionable state
 * in one bounded row. Historical CSS remains load-compatible, while this module owns
 * the final geometry contract so later pages cannot stretch or crop the shell.
 */
(() => {
  const AUTHORITY='GlobalShellTypographyCopyConvergenceV2';
  const CONTRACT_VERSION='0.89-G3.4';
  const RAW_GUIDED_TOKENS=[
    'Current project','Create design in current project','Starting isolated preflight process',
    'Maximum 60 seconds','Design Revision','Motor Revision','Analysis Revision','Execution Plan','Native Binding','Native Closure','GeometryTree','NativeModelSnapshot','BindingPlan','ResultBundle'
  ];
  const allowedEnglish=/^(MotorCAD Studio|Motor-CAD|SPM|IPM|AFPM|BPM|EMag|FEA|RPM|rpm|kW|CSV|JSONL|DOE|Pareto)$/i;
  const visible=el=>{const style=getComputedStyle(el);const r=el.getBoundingClientRect();return style.display!=='none'&&style.visibility!=='hidden'&&r.width>0&&r.height>0};

  function installFinalShellAuthority(){
    if(document.getElementById('mcsShellAuthorityG34'))return;
    const style=document.createElement('style');
    style.id='mcsShellAuthorityG34';
    style.textContent=`
      @media (min-width:1181px){
        body.studio-v089g3 #projectShell.project-shell{
          display:grid!important;
          grid-template-columns:minmax(210px,240px) minmax(450px,560px) minmax(320px,1fr)!important;
          grid-template-rows:52px!important;
          width:100%!important;max-width:100vw!important;height:52px!important;min-height:52px!important;
          align-items:stretch!important;overflow:hidden!important;box-sizing:border-box!important;
        }
        body.studio-v089g3 #projectShell>.project-shell-context{grid-column:1!important;grid-row:1!important;width:auto!important;min-width:0!important;height:52px!important;overflow:hidden!important;}
        body.studio-v089g3 #projectShell>.project-stage-nav{grid-column:2!important;grid-row:1!important;width:auto!important;min-width:0!important;height:52px!important;display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr))!important;overflow:hidden!important;}
        body.studio-v089g3 #projectShell>.project-stage-nav button{min-width:0!important;width:auto!important;height:52px!important;min-height:52px!important;overflow:hidden!important;}
        body.studio-v089g3 #projectShell>.project-stage-nav button>b,body.studio-v089g3 #projectShell>.project-stage-nav button>small{min-width:0!important;white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important;}
        body.studio-v089g3 #projectShell>.engineer-focus-bar-v089f{grid-column:3!important;grid-row:1!important;width:auto!important;min-width:0!important;height:52px!important;min-height:52px!important;display:grid!important;grid-template-columns:minmax(120px,.7fr) minmax(200px,1.3fr)!important;overflow:hidden!important;border-right:0!important;}
        body.studio-v089g3 #projectShell>.engineer-focus-bar-v089f .current{display:none!important;}
        body.studio-v089g3 #projectShell>.engineer-focus-bar-v089f .status,body.studio-v089g3 #projectShell>.engineer-focus-bar-v089f .next{min-width:0!important;width:auto!important;height:52px!important;overflow:hidden!important;}
        body.studio-v089g3 #projectShell>.engineer-focus-bar-v089f b,body.studio-v089g3 #projectShell>.engineer-focus-bar-v089f small{white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important;}
        body.studio-v089g3 #projectShell>.engineering-context-breadcrumb-v089a,body.studio-v089g3 #projectShell>.engineer-journey-cue-v086r{display:none!important;}
      }
      @media (min-width:1181px) and (max-width:1380px){
        body.studio-v089g3 #projectShell.project-shell{grid-template-columns:200px minmax(420px,500px) minmax(260px,1fr)!important;}
        body.studio-v089g3 #projectShell>.engineer-focus-bar-v089f{grid-template-columns:minmax(0,1fr)!important;}
        body.studio-v089g3 #projectShell>.engineer-focus-bar-v089f .status{display:none!important;}
      }
      @media (max-width:1180px) and (min-width:821px){
        body.studio-v089g3 #projectShell.project-shell{height:auto!important;min-height:52px!important;overflow:visible!important;}
      }
      body.studio-v089g3 .global-nav,body.studio-v089g3 .operator-header{box-sizing:border-box;max-width:100vw;overflow:hidden;}
      body.studio-v089g3 .header-actions{min-width:0;}
    `;
    document.head.appendChild(style);
  }

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
      if(shell.scrollWidth>shell.clientWidth+2)issues.push('PROJECT_SHELL_HORIZONTAL_OVERFLOW');
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
    installFinalShellAuthority();
    const result=audit();
    document.dispatchEvent(new CustomEvent('mcs:global-shell-convergence-audit',{detail:result}));
    return result;
  }
  document.addEventListener('DOMContentLoaded',()=>requestAnimationFrame(refresh),{once:true});
  document.addEventListener('mcs-language-change',()=>requestAnimationFrame(refresh));
  window.addEventListener('resize',()=>requestAnimationFrame(refresh),{passive:true});
  window.addEventListener('mcs:route-ready',()=>requestAnimationFrame(refresh));
  window.MCSGlobalShellConvergence={authority:AUTHORITY,contractVersion:CONTRACT_VERSION,audit,refresh};
})();
