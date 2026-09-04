/* MotorCAD Studio V0.75-B — generic Motor Object provider boundary.
 * Core Design modules resolve/render by topology provider registration. They do not
 * need family-specific branches when a new MotorFamilyPlugin contributes a browser object.
 */
(() => {
  const providers=new Map(), renderers=new Map();
  const ids=value=>Array.isArray(value)?value:[value];
  function register(topologyIds,resolver){for(const id of ids(topologyIds))if(id&&typeof resolver==='function')providers.set(String(id),resolver)}
  function registerVisualization(topologyIds,renderer){for(const id of ids(topologyIds))if(id&&typeof renderer==='function')renderers.set(String(id),renderer)}
  function topologyOf(data={},base=null){return String(base?.topology_id||base?.identity?.topology_id||data?.motor_snapshot?.identity?.topology_id||data?.motor_object?.topology_id||'')}
  function resolve(data={},values={},materials=null){
    const topology=topologyOf(data,data?.motor_object),resolver=providers.get(topology);
    if(resolver)return resolver(data,values,materials);
    return data?.motor_object||null;
  }
  function renderVisualization(view,motorObject,ctx={}){
    const topology=topologyOf(ctx?.data||{},motorObject),renderer=renderers.get(topology);
    return renderer?renderer(view,motorObject,ctx):null;
  }
  function supported(){return [...providers.keys()].sort()}
  window.MCSMotorObject={register,registerVisualization,resolve,renderVisualization,supported,topologyOf};
})();
