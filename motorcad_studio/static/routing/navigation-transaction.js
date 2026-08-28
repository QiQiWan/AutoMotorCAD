/* V0.89-C Navigation Transaction Authority
 *
 * Serializes route-changing intent, consults registered editor guards before a
 * transition is committed, exposes a reusable single-flight action lock, and
 * protects browser unload when an editor still has local-only changes.
 *
 * A guard PREPARES a leave (for example by flushing an autosaved Draft). It must
 * not dispose the current UI. Disposal belongs to the committed transition so a
 * failed route load cannot strand the operator on a half-unmounted editor.
 */
(() => {
  const AUTHORITY='NavigationTransactionAuthorityV1';
  const CONTRACT_VERSION='0.89-C';
  const guards=new Map();
  const actionLocks=new Map();
  const inflightTargets=new Map();
  const history=[];
  let sequence=0;
  let latestIntent=0;

  const now=()=>new Date().toISOString();
  const clone=value=>{try{return JSON.parse(JSON.stringify(value))}catch{return value}};
  const emit=(name,detail)=>window.dispatchEvent(new CustomEvent(name,{detail}));
  const guardRows=()=>[...guards.values()].sort((a,b)=>Number(b.priority||0)-Number(a.priority||0));

  function registerGuard(guard={}){
    const id=String(guard.id||'').trim();
    if(!id)throw new Error('navigation guard id is required');
    guards.set(id,{...guard,id});
    emit('mcs:navigation-guard-registered',{authority:AUTHORITY,id});
    return ()=>guards.delete(id);
  }

  function inspect(){
    const rows=guardRows().map(guard=>{
      let active=false,unsafe=false,state=null;
      try{active=guard.isActive?Boolean(guard.isActive()):true}catch(error){state={error:String(error?.message||error)}}
      if(active){try{unsafe=guard.unsafe?Boolean(guard.unsafe()):false}catch(error){state={...(state||{}),unsafe_error:String(error?.message||error)}}}
      if(active&&guard.inspect){try{state=guard.inspect()}catch(error){state={...(state||{}),inspect_error:String(error?.message||error)}}}
      return {id:guard.id,priority:Number(guard.priority||0),active,unsafe,state:clone(state)};
    });
    return {authority:AUTHORITY,contract_version:CONTRACT_VERSION,guards:rows,unsafe:rows.some(row=>row.active&&row.unsafe),action_locks:[...actionLocks.keys()],inflight_targets:[...inflightTargets.keys()],history:history.slice(-30)};
  }

  async function prepare(target,meta={}){
    for(const guard of guardRows()){
      let active=true;
      try{active=guard.isActive?Boolean(guard.isActive()):true}catch(error){
        console.error('navigation guard active check failed',guard.id,error);
        return false;
      }
      if(!active||typeof guard.prepare!=='function')continue;
      try{
        const allowed=await guard.prepare(target,meta);
        if(allowed===false){
          const row={sequence:++sequence,status:'BLOCKED',guard_id:guard.id,target:clone(target),source:meta.source||'unknown',at:now()};
          history.push(row);if(history.length>100)history.splice(0,history.length-100);
          emit('mcs:navigation-transaction-blocked',row);
          return false;
        }
      }catch(error){
        const row={sequence:++sequence,status:'GUARD_ERROR',guard_id:guard.id,target:clone(target),source:meta.source||'unknown',message:String(error?.message||error),at:now()};
        history.push(row);if(history.length>100)history.splice(0,history.length-100);
        console.error('navigation guard prepare failed',guard.id,error);
        emit('mcs:navigation-transaction-blocked',row);
        return false;
      }
    }
    return true;
  }

  async function run({target,key=null,source='navigation',meta={},prepare:prepareFn=null,commit,rollback=null}={}){
    if(typeof commit!=='function')throw new Error('navigation transaction commit callback is required');
    const targetKey=String(key||target||source||'navigation');
    if(inflightTargets.has(targetKey))return inflightTargets.get(targetKey);
    const intent=++latestIntent;
    const from=location.pathname;
    const record={sequence:++sequence,intent,status:'PREPARING',source,target:clone(target),from,at:now()};
    history.push(record);if(history.length>100)history.splice(0,history.length-100);
    emit('mcs:navigation-transaction-started',clone(record));

    const promise=(async()=>{
      try{
        const allowed=prepareFn?await prepareFn():await prepare(target,{...meta,source});
        if(allowed===false){record.status='BLOCKED';record.completed_at=now();return false}
        // Fast repeated navigation is last-intent-wins while a guard is awaiting I/O.
        // This prevents an older click from winning after a later click was made.
        if(intent!==latestIntent){record.status='SUPERSEDED';record.completed_at=now();return false}
        try{window.StudioDialog?.closeAll?.({reason:'navigation-commit'})}catch{}
        record.status='COMMITTING';
        const result=await commit();
        if(result===false){record.status='FAILED';record.completed_at=now();if(typeof rollback==='function')await rollback({from,target,reason:'commit-returned-false'});return false}
        record.status='COMMITTED';record.completed_at=now();
        const detail={...clone(record),meta:clone(meta),to:location.pathname};
        emit('mcs:navigation-transaction-committed',detail);
        return result===undefined?true:result;
      }catch(error){
        record.status='FAILED';record.message=String(error?.message||error);record.completed_at=now();
        if(typeof rollback==='function'){try{await rollback({from,target,error})}catch(rollbackError){console.error('navigation rollback failed',rollbackError)}}
        emit('mcs:navigation-transaction-failed',{...clone(record),meta:clone(meta)});
        throw error;
      }
    })().finally(()=>inflightTargets.delete(targetKey));
    inflightTargets.set(targetKey,promise);
    return promise;
  }

  function withActionLock(key,operation){
    const id=String(key||'action');
    if(actionLocks.has(id))return actionLocks.get(id);
    const promise=Promise.resolve().then(operation).finally(()=>{if(actionLocks.get(id)===promise)actionLocks.delete(id)});
    actionLocks.set(id,promise);
    return promise;
  }

  function hasUnsafeChanges(){
    for(const guard of guardRows()){
      try{if((guard.isActive?guard.isActive():true)&&guard.unsafe?.())return true}catch{return true}
    }
    return false;
  }

  window.addEventListener('beforeunload',event=>{
    if(!hasUnsafeChanges())return;
    event.preventDefault();
    event.returnValue='';
  });

  window.MCSNavigationTransaction={AUTHORITY,CONTRACT_VERSION,registerGuard,prepare,run,inspect,withActionLock,hasUnsafeChanges};
})();
