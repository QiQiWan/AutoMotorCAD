(function(){
  const EN={
    '运行驾驶舱':'Dashboard','工程工作区':'Engineering workspace','模板库':'Template library','新建任务':'New task','实时监控':'Live monitor','任务中心':'Tasks','结果分析':'Analytics','结果查看器':'Result viewer','数据工厂':'Data factory','日志与问题':'Logs & issues','系统诊断':'System diagnostics',
    '工程参数编辑器':'Engineering parameter editor','基础':'Basic','工程':'Engineering','仅显示已修改':'Changed only','重置改动':'Reset changes','快速几何预览':'Quick geometry preview','参数驱动示意 · 非FEA几何':'Parameter-driven schematic · not FEA geometry',
    '材料与高级 Motor-CAD 设置':'Materials & advanced Motor-CAD settings','常用材料快速选择':'Common material selection','专家参数':'Expert parameters','高级求解配置':'Advanced solver controls','开发者：其他求解器原生参数':'Developer: raw solver parameters',
    '运行场景与边界条件':'Scenario & boundary conditions','自动化任务':'Automation task','单次计算':'Single run','一维扫描':'1D sweep','CSV矩阵':'CSV matrix','结果请求':'Requested results','预检查':'Preflight','提交任务':'Submit task',
    '运行环境诊断':'Runtime diagnostics','浅检查':'Shallow check','Motor-CAD深度检查':'Motor-CAD deep check','系统配置':'System configuration','重新扫描':'Rescan','刷新能力':'Refresh capabilities','刷新覆盖率':'Refresh coverage',
    '仿真数据工厂':'Simulation data factory','原始索引':'Raw index','标准化':'Curated','派生特征':'Features','数据集':'Dataset','构建数据集版本':'Build dataset version','数据集名称':'Dataset name','已有数据集':'Existing dataset','新建数据集':'Create dataset','质量门禁':'Quality gate','来源任务':'Source tasks','包含Mock结果':'Include Mock results','按输入指纹去重':'Deduplicate by input fingerprint','稳定数据分区':'Stable partitions','开发集':'Development','验证集':'Validation','留出集':'Holdout','随机种子':'Seed','构建不可变版本':'Build immutable version','工厂状态':'Factory status','数据集注册表':'Dataset registry','数据集版本详情':'Dataset version detail',
    '工程结果查看器':'Engineering result viewer','打开结果':'Open result','结果总览':'Overview','输入与模型快照':'Inputs & model snapshot','电磁波形':'Electromagnetic waveforms','谐波频谱':'Harmonics','FEA场结果':'FEA fields','热结果':'Thermal results','Lab性能图谱':'Lab performance maps','机械与NVH':'Mechanical & NVH','原生结果与审计':'Native results & audit',
    '项目名称':'Project name','任务名称':'Task name','模板':'Template','求解器':'Solver','分析类型':'Analysis','质量检查':'Quality check','环境温度 / °C':'Ambient temperature / °C','初始温度 / °C':'Initial temperature / °C','冷却方式':'Cooling method','海拔 / m':'Altitude / m','刷新':'Refresh','新建项目':'New project','删除项目':'Delete project','从当前模板创建设计':'Create design from template','复制为新Revision':'Duplicate as new revision','作为任务起点':'Use as task starting point',
    '项目与设计版本':'Projects & design revisions','当前工程对象':'Current engineering object','选择一个项目或设计':'Select a project or design','中央工作区将显示电机示意、Revision和相关任务。':'The workspace shows the motor schematic, revisions and related tasks.',
    '实时通道连接中':'Connecting live channel','实时通道已连接':'Live channel connected','实时通道重连中':'Reconnecting live channel','实时通道不可用':'Live channel unavailable','实时通道已切换轮询':'Live channel fallback: polling',
    '基础模式':'Operator mode','工程模式':'Engineering mode','专家模式':'Expert mode','开发者模式':'Developer mode','当前项目':'Current project','沿用模板材料':'Keep template material','沿用模板介质':'Keep template fluid','常用材料快速选择':'Common material selection','定子叠片':'Stator lamination','转子叠片':'Rotor lamination','永磁体':'Magnet','绕组导体':'Winding conductor','转轴':'Shaft','机壳':'Housing','转子套筒':'Rotor sleeve','回收站':'Trash','任务向导':'Task wizard','检查材料映射':'Validate material mapping','模板运行资格检查':'Template runtime qualification','运行资格检查':'Run qualification','问题诊断':'Issue diagnostics','日志过滤器':'Log filters','结构化运行日志':'Structured runtime logs','导出诊断包':'Export diagnostics bundle','实时':'Live','全部组件':'All components','最低级别':'Minimum level','组件':'Component','关键词':'Keyword'
  };
  const ZH_FROM_EN={'Properties':'属性','Design Revisions':'设计版本','Traceability':'可追溯性','Parameter Snapshot':'参数快照','Revision':'版本','Created':'创建时间','Template':'模板','Materials':'材料','Verification':'验证状态','Designs':'设计','Scenarios':'场景','Experiments':'试验','Project':'项目','Dataset':'数据集','Rows':'数据行','Version':'版本','Quality distribution':'质量分布','Stable partitions':'稳定数据分区','Lineage':'数据血缘','Quarantine':'隔离区'};
  const KEYS={...(window.MCS_LOCALES||{}),
    'workspace.properties':{'zh':'属性','en':'Properties'},'workspace.revisions':{'zh':'设计版本','en':'Design revisions'},'workspace.traceability':{'zh':'可追溯性','en':'Traceability'},
    'mode.operator':{'zh':'基础模式','en':'Operator mode'},'mode.engineering':{'zh':'工程模式','en':'Engineering mode'},'mode.expert':{'zh':'专家模式','en':'Expert mode'},'mode.developer':{'zh':'开发者模式','en':'Developer mode'}
  };
  const originalText=new WeakMap(), originalAttr=new WeakMap();
  const lang=()=>window.localStorage.getItem('motorcad-studio-language')||'zh';
  function mapText(text){const trimmed=text.trim(); if(!trimmed)return text; const mapped=EN[trimmed]; if(!mapped)return text; return text.replace(trimmed,mapped);}
  function mapTextZh(text){const trimmed=text.trim();if(!trimmed)return text;const mapped=ZH_FROM_EN[trimmed];return mapped?text.replace(trimmed,mapped):text;}
  function translateNode(node){
    if(node.nodeType===Node.TEXT_NODE){if(!originalText.has(node))originalText.set(node,node.nodeValue); const src=originalText.get(node); node.nodeValue=lang()==='en'?mapText(src):mapTextZh(src); return;}
    if(node.nodeType!==Node.ELEMENT_NODE)return;
    ['placeholder','title','aria-label'].forEach(attr=>{if(!node.hasAttribute(attr))return; let rec=originalAttr.get(node)||{}; if(!(attr in rec))rec[attr]=node.getAttribute(attr); originalAttr.set(node,rec); const src=rec[attr]; node.setAttribute(attr,lang()==='en'?(EN[src]||src):(ZH_FROM_EN[src]||src))});
    [...node.childNodes].forEach(translateNode);
  }
  function applyKeyElements(root=document){(root||document).querySelectorAll?.('[data-i18n-key]').forEach(el=>{const row=KEYS[el.dataset.i18nKey];if(row)el.textContent=lang()==='en'?row.en:row.zh})}
  function apply(root=document.body){if(root)translateNode(root);applyKeyElements(root?.ownerDocument||document); const b=document.getElementById('languageToggle'); if(b)b.textContent=lang()==='en'?'中':'EN'; document.documentElement.lang=lang()==='en'?'en':'zh-CN';}
  window.MCS_I18N={get language(){return lang()}, t:(zh,en)=>lang()==='en'?(en||zh):zh, tKey:(key)=>{const row=KEYS[key];return row?(lang()==='en'?row.en:row.zh):key}, apply, toggle(){window.localStorage.setItem('motorcad-studio-language',lang()==='en'?'zh':'en');apply();document.dispatchEvent(new CustomEvent('mcs-language-change',{detail:{language:lang()}}));}};
  document.addEventListener('DOMContentLoaded',()=>{apply();document.getElementById('languageToggle')?.addEventListener('click',()=>window.MCS_I18N.toggle()); const obs=new MutationObserver(ms=>{if(lang()!=='en')return; ms.forEach(m=>m.addedNodes.forEach(n=>translateNode(n)))});obs.observe(document.body,{childList:true,subtree:true});});
})();
