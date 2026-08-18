/* V0.70 stable module; migrated from historical v054.js. */
/* MotorCAD Studio V0.57.0 — engineering table viewer and archive trust UX. */
(() => {
  const q=(s,r=document)=>r.querySelector(s);
  const safe=v=>typeof window.esc==='function'?window.esc(v):String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const format=value=>{if(value===null||value===undefined||value==='')return'—';if(typeof value==='number')return Number.isInteger(value)?value.toLocaleString():Number(value).toPrecision(7);return String(value)};

  function nativeTableSection(id,table){
    if(!table||!Array.isArray(table.columns)||!Array.isArray(table.rows)||!table.rows.length)return'';
    const columns=table.columns.slice(0,80),rows=table.rows.slice(0,200),meta=state.viewer?.output_schema?.[id]||{},caseId=state.viewer?.case?.id;
    const sourceCount=Number(table.source_row_count||table.row_count||rows.length);
    return `<section class="native-table-v054"><header><div><span class="eyebrow">MOTOR-CAD NATIVE TABLE</span><h3>${safe(meta.label||id)}</h3><p>${safe(table.authority||'native export')} · SHA ${safe(String(table.source_sha256||'').slice(0,12)||'未登记')}</p></div><div class="native-table-stats-v054"><span><b>${sourceCount.toLocaleString()}</b> 源数据行</span><span><b>${columns.length}</b> 列</span><span class="${table.truncated?'warn':'ok'}"><b>${table.truncated?'流式索引':'完整结构化'}</b></span>${caseId?`<a href="/api/cases/${encodeURIComponent(caseId)}/native-tables/${encodeURIComponent(id)}" target="_blank">验证并下载原生文件</a>`:''}</div></header><div class="native-table-scroll-v054"><table><thead><tr>${columns.map(column=>`<th>${safe(column)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${columns.map(column=>`<td>${safe(format(row?.[column]))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>${sourceCount>rows.length?`<footer data-native-table-footer-v055>已加载 ${rows.length.toLocaleString()} / ${sourceCount.toLocaleString()} 行。<button type="button" data-native-table-page-v055="${safe(id)}" data-offset-v055="${rows.length}" data-source-count-v055="${sourceCount}">加载下一页</button></footer>`:''}</section>`;
  }

  async function loadTablePage(button){
    const section=button.closest('.native-table-v054'),id=button.dataset.nativeTablePageV055,caseId=state.viewer?.case?.id,table=state.viewer?.results?.tables?.[id],columns=(table?.columns||[]).slice(0,80),offset=Number(button.dataset.offsetV055||0),sourceCount=Number(button.dataset.sourceCountV055||0);if(!section||!caseId||!id||!columns.length)return;
    const original=button.textContent;button.disabled=true;button.textContent='读取并验证…';
    try{const page=await api(`/api/cases/${encodeURIComponent(caseId)}/native-tables/${encodeURIComponent(id)}/rows?offset=${offset}&limit=200`),rows=page.rows||[],tbody=q('tbody',section);if(!tbody)return;tbody.insertAdjacentHTML('beforeend',rows.map(row=>`<tr>${columns.map(column=>`<td>${safe(format(row?.[column]))}</td>`).join('')}</tr>`).join(''));const next=Number(page.next_offset||offset+rows.length),footer=q('[data-native-table-footer-v055]',section);button.dataset.offsetV055=String(next);if(!rows.length||next>=sourceCount){button.remove();if(footer)footer.firstChild.textContent=`已加载全部 ${sourceCount.toLocaleString()} 行。`}else{button.disabled=false;button.textContent=original;if(footer)footer.firstChild.textContent=`已加载 ${next.toLocaleString()} / ${sourceCount.toLocaleString()} 行。`}}catch(error){button.disabled=false;button.textContent='重试加载';button.title=error.message}
  }

  function renderNativeTables(filter=()=>true){
    return Object.entries(state.viewer?.results?.tables||{}).filter(([id])=>filter(id)).map(([id,table])=>nativeTableSection(id,table)).join('');
  }

  const previous=window.renderViewerModule;
  if(typeof previous==='function')window.renderViewerModule=function(key){
    const result=previous.apply(this,arguments),canvas=q('#viewerCanvas');if(!canvas||!state.viewer)return result;
    let html='';
    if(key==='output_data')html=renderNativeTables();
    else if(key==='nvh')html=renderNativeTables(id=>/force|nvh|modal|campbell/i.test(id));
    else if(key==='lab')html=renderNativeTables(id=>/lab|duty|performance/i.test(id));
    if(html){canvas.insertAdjacentHTML('beforeend',html);canvas.querySelectorAll('[data-native-table-page-v055]').forEach(button=>button.addEventListener('click',()=>loadTablePage(button)))}
    return result;
  };
  document.body.classList.add('studio-v054');
  window.MCSV054={renderNativeTables};
})();
