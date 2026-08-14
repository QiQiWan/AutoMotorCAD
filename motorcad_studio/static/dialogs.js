/* V0.20 in-page floating dialogs. Browser alert/confirm/prompt are intentionally not used. */
(() => {
  function ensureLayer(){
    let layer=document.getElementById('studioDialogLayer');
    if(layer)return layer;
    layer=document.createElement('div');layer.id='studioDialogLayer';layer.className='studio-dialog-layer';layer.setAttribute('aria-live','polite');document.body.appendChild(layer);return layer;
  }
  function close(id,value=false){const el=document.getElementById(id);if(!el)return;el.classList.add('closing');setTimeout(()=>el.remove(),140);const resolve=el._resolve;if(resolve){el._resolve=null;resolve(value)}}
  function open({title='提示',message='',html='',tone='info',actions=null,width='520px',sheet=false}={}){
    const layer=ensureLayer(),id=`studio-dialog-${Date.now()}-${Math.random().toString(36).slice(2,7)}`;
    const box=document.createElement('section');box.id=id;box.className=`studio-floating-dialog ${sheet?'sheet':''} ${tone}`;box.style.setProperty('--dialog-width',width);box.setAttribute('role','dialog');box.setAttribute('aria-label',title);
    const safeBody=html||`<p>${typeof esc==='function'?esc(message):String(message)}</p>`;
    const normalized=actions||[{label:'知道了',value:true,primary:true}];
    box.innerHTML=`<header><div><span class="dialog-kicker">页内浮窗</span><h3>${typeof esc==='function'?esc(title):title}</h3></div><button type="button" class="dialog-close" aria-label="关闭">×</button></header><div class="dialog-body">${safeBody}</div><footer>${normalized.map((a,i)=>`<button type="button" data-dialog-action="${i}" class="${a.primary?'primary':''} ${a.danger?'danger':''}">${typeof esc==='function'?esc(a.label):a.label}</button>`).join('')}</footer>`;
    layer.appendChild(box);box.querySelector('.dialog-close').addEventListener('click',()=>close(id,false));box.querySelectorAll('[data-dialog-action]').forEach(btn=>btn.addEventListener('click',()=>{const a=normalized[Number(btn.dataset.dialogAction)];const value=typeof a?.getValue==='function'?a.getValue(box):a?.value;close(id,value)}));
    requestAnimationFrame(()=>box.classList.add('open'));
    return new Promise(resolve=>{box._resolve=resolve});
  }
  function confirmDialog({title='请确认',message='',html='',confirmText='确认',cancelText='取消',danger=false}={}){return open({title,message,html,tone:danger?'danger':'warning',actions:[{label:cancelText,value:false},{label:confirmText,value:true,primary:!danger,danger}]})}
  function sheet(opts={}){return open({...opts,sheet:true,width:opts.width||'560px'})}
  window.StudioDialog={open,confirm:confirmDialog,sheet,close};
  document.addEventListener('keydown',e=>{if(e.key!=='Escape')return;const rows=[...document.querySelectorAll('.studio-floating-dialog')];const last=rows.at(-1);if(last)close(last.id,false)});
})();
