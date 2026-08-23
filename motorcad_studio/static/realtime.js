(function(){
  class RealtimeChannel {
    constructor({name,badge,onState,onMessage,poll,maxFailures=3,pollInterval=5000}){
      this.name=name;this.badge=badge;this.onState=onState||(()=>{});this.onMessage=onMessage||(()=>{});this.poll=poll||null;this.maxFailures=maxFailures;this.pollInterval=pollInterval;this.failures=0;this.es=null;this.timer=null;this.url=null;this.events=[];
    }
    _state(code,detail=''){this.onState(code,detail);if(!this.badge)return;const labels={CONNECTING:['连接中','connection-pulse'],CONNECTED:['实时已连接','ok'],RECONNECTING:[`实时重连中 (${this.failures}/${this.maxFailures})`,'warn connection-pulse'],POLLING:['轮询模式','warn'],OFFLINE:['实时不可用','error']};const [text,cls]=labels[code]||[code,''];this.badge.textContent=text;this.badge.className=`badge ${cls}`;this.badge.title=detail||''}
    stop(){if(this.es){try{this.es.close()}catch{}this.es=null}if(this.timer){clearInterval(this.timer);this.timer=null}}
    async _pollOnce(){if(!this.poll)return;try{await this.poll();this._state('POLLING','SSE不可用，当前使用HTTP轮询。')}catch(e){this._state('OFFLINE',e?.message||String(e))}}
    _startPolling(){if(!this.poll){this._state('OFFLINE');return}if(this.es){try{this.es.close()}catch{}this.es=null}if(this.timer)clearInterval(this.timer);this._pollOnce();this.timer=setInterval(()=>this._pollOnce(),this.pollInterval)}
    connect(url,events){this.stop();this.url=url;this.events=events||[];this.failures=0;this._state('CONNECTING');try{const es=new EventSource(url);this.es=es;for(const eventName of this.events){es.addEventListener(eventName,e=>this.onMessage(eventName,e))}es.onopen=()=>{this.failures=0;if(this.timer){clearInterval(this.timer);this.timer=null}this._state('CONNECTED')};es.onerror=()=>{this.failures+=1;if(this.failures>=this.maxFailures){this._startPolling()}else this._state('RECONNECTING')};}catch(e){this._startPolling()}}
    retry(){if(this.url)this.connect(this.url,this.events)}
  }
  window.MCSRealtime={RealtimeChannel};
})();
