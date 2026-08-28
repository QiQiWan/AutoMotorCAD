/* V0.89-C in-page floating dialogs.
 * Browser alert/confirm/prompt are intentionally not used for Studio-owned flow.
 * Dialog teardown is transaction-safe: actions are single-fire, close has a hard
 * fallback timer, route commits may close every orphaned dialog, and focus returns
 * to the element that opened the dialog when it is still connected.
 */
(() => {
  const activeByKey=new Map();
  function ensureLayer(){
    let layer=document.getElementById('studioDialogLayer');
    if(layer)return layer;
    layer=document.createElement('div');layer.id='studioDialogLayer';layer.className='studio-dialog-layer';layer.setAttribute('aria-live','polite');document.body.appendChild(layer);return layer;
  }
  function removeElement(el){
    if(!el)return;
    const key=el.dataset.dialogKey;if(key&&activeByKey.get(key)===el)activeByKey.delete(key);
    if(el.isConnected)el.remove();
    const opener=el._opener;if(opener?.isConnected){try{opener.focus({preventScroll:true})}catch{}}
  }
  function close(id,value=false){
    const el=document.getElementById(id);if(!el||el.dataset.closing==='1')return;
    el.dataset.closing='1';el.classList.add('closing');
    el.querySelectorAll('button,input,select,textarea').forEach(node=>{node.disabled=true});
    let removed=false;const remove=()=>{if(removed)return;removed=true;removeElement(el)};
    el.addEventListener('transitionend',remove,{once:true});
    // A missing transitionend event previously left invisible dialogs mounted and
    // intercepting later clicks. The bounded fallback makes close deterministic.
    window.setTimeout(remove,320);
    requestAnimationFrame(()=>{try{if(getComputedStyle(el).transitionDuration==='0s')remove()}catch{remove()}});
    const resolve=el._resolve;if(resolve){el._resolve=null;resolve(value)}
  }
  function closeAll({reason='close-all'}={}){
    const rows=[...document.querySelectorAll('.studio-floating-dialog')];
    rows.forEach(el=>close(el.id,false));
    return {reason,count:rows.length};
  }
  function open({title='提示',message='',html='',tone='info',actions=null,width='520px',sheet=false,key=null}={}){
    const dialogKey=String(key||'').trim();
    const existing=dialogKey?activeByKey.get(dialogKey):null;
    if(existing?.isConnected&&existing._promise)return existing._promise;
    const layer=ensureLayer(),id=`studio-dialog-${Date.now()}-${Math.random().toString(36).slice(2,7)}`;
    const box=document.createElement('section');box.id=id;box.className=`studio-floating-dialog ${sheet?'sheet':''} ${tone}`;box.style.setProperty('--dialog-width',width);box.setAttribute('role','dialog');box.setAttribute('aria-modal','true');box.setAttribute('aria-label',title);if(dialogKey)box.dataset.dialogKey=dialogKey;
    const safeBody=html||`<p>${typeof esc==='function'?esc(message):String(message)}</p>`;
    const normalized=actions||[{label:'知道了',value:true,primary:true}];
    box.innerHTML=`<header><div><span class="dialog-kicker">页内浮窗</span><h3>${typeof esc==='function'?esc(title):title}</h3></div><button type="button" class="dialog-close" aria-label="关闭">×</button></header><div class="dialog-body">${safeBody}</div><footer>${normalized.map((a,i)=>`<button type="button" data-dialog-action="${i}" class="${a.primary?'primary':''} ${a.danger?'danger':''}">${typeof esc==='function'?esc(a.label):a.label}</button>`).join('')}</footer>`;
    box._opener=document.activeElement;layer.appendChild(box);if(dialogKey)activeByKey.set(dialogKey,box);
    box.querySelector('.dialog-close').addEventListener('click',()=>close(id,false),{once:true});
    box.querySelectorAll('[data-dialog-action]').forEach(btn=>btn.addEventListener('click',()=>{
      if(box.dataset.actionFired==='1')return;box.dataset.actionFired='1';
      const a=normalized[Number(btn.dataset.dialogAction)];const value=typeof a?.getValue==='function'?a.getValue(box):a?.value;close(id,value);
    },{once:true}));
    requestAnimationFrame(()=>{box.classList.add('open');const focusable=box.querySelector('input:not([disabled]),textarea:not([disabled]),select:not([disabled]),button:not([disabled])');try{focusable?.focus({preventScroll:true})}catch{}});
    const promise=new Promise(resolve=>{box._resolve=resolve});box._promise=promise;return promise;
  }
  function confirmDialog({title='请确认',message='',html='',confirmText='确认',cancelText='取消',danger=false,key=null}={}){return open({title,message,html,tone:danger?'danger':'warning',key,actions:[{label:cancelText,value:false},{label:confirmText,value:true,primary:!danger,danger}]})}
  function sheet(opts={}){return open({...opts,sheet:true,width:opts.width||'560px'})}
  window.StudioDialog={open,confirm:confirmDialog,sheet,close,closeAll,activeCount:()=>document.querySelectorAll('.studio-floating-dialog').length};
  document.addEventListener('keydown',e=>{if(e.key!=='Escape')return;const rows=[...document.querySelectorAll('.studio-floating-dialog:not(.closing)')];const last=rows.at(-1);if(last){e.preventDefault();close(last.id,false)}});
})();
