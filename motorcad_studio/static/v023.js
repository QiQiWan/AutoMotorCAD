/* V0.23 Native FEA evidence + Motor-CAD session ownership view. */
(() => {
  const q = (s) => document.querySelector(s);
  const escapeHtml = (value) => typeof window.esc === 'function'
    ? window.esc(value)
    : String(value ?? '').replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

  const native = {
    mode: 'live',
    caseId: null,
    evidence: null,
    frame: null,
    frameIndex: 0,
    field: 'b',
    playing: false,
    timer: 0,
    evidenceAbort: null,
    frameAbort: null,
    lastEvidenceFetch: 0,
    lastSessionFetch: 0,
  };

  function modeButton(mode) {
    return document.querySelector(`[data-fea-mode-v022="${mode}"]`);
  }

  function setNativeMode(active) {
    native.mode = active ? 'native' : (native.mode === 'native' ? 'live' : native.mode);
    const panel = q('#solverVisualPanelV022');
    panel?.classList.toggle('native-fea-mode-v023', active);
    q('#nativeFEAStageV023')?.classList.toggle('hidden', !active);
    q('#nativeFEAControlsV023')?.classList.toggle('hidden', !active || !native.evidence?.normalization?.normalized);
    q('#nativeFEAAuthorityV023')?.classList.toggle('hidden', !active);
    q('#solverVisualAuthorityBoxV022')?.classList.toggle('hidden', active);
    if (active) {
      modeButton('native')?.classList.add('active');
      if (native.caseId) loadEvidence(native.caseId, true);
    } else {
      stopPlayback();
    }
  }

  function status(message, tone = '') {
    const box = q('#nativeFEAStatusV023');
    if (!box) return;
    box.innerHTML = `<span class="badge ${tone}">${escapeHtml(message)}</span>`;
  }

  function showEmpty(message) {
    const box = q('#nativeFEAEmptyV023');
    if (!box) return;
    box.textContent = message;
    box.classList.remove('hidden');
    q('#nativeFEACanvasV023')?.classList.add('hidden');
    q('#nativeFEAControlsV023')?.classList.add('hidden');
  }

  function hideEmpty() {
    q('#nativeFEAEmptyV023')?.classList.add('hidden');
    q('#nativeFEACanvasV023')?.classList.remove('hidden');
  }

  async function loadEvidence(caseId, force = false) {
    if (!caseId) return;
    const now = Date.now();
    if (!force && native.evidence?.case_id === caseId && now - native.lastEvidenceFetch < 2500) return;
    native.lastEvidenceFetch = now;
    native.evidenceAbort?.abort();
    const controller = new AbortController();
    native.evidenceAbort = controller;
    try {
      const response = await fetch(`/api/cases/${encodeURIComponent(caseId)}/fea-evidence`, {signal: controller.signal, cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if (caseId !== native.caseId) return;
      native.evidence = payload;
      renderEvidenceState();
    } catch (error) {
      if (error?.name === 'AbortError') return;
      native.evidence = null;
      if (native.mode === 'native') showEmpty(`原生 FEA 证据读取失败：${error.message || error}`);
    }
  }

  function renderEvidenceState() {
    if (native.mode !== 'native') return;
    const evidence = native.evidence;
    if (!evidence?.available) {
      status('等待原生 FEA 证据', 'warn');
      showEmpty('当前 Case 尚未生成 Motor-CAD 原生 FEA 数据。正在运行的 Case 会在电磁求解完成后导出；V0.22 及更早历史 Case 需要重新计算。');
      return;
    }
    const normalized = evidence.normalization || {};
    if (!normalized.normalized) {
      status(evidence.status === 'RAW_ONLY' ? '原始 FEA 已保存 · 暂不可视化' : `FEA ${evidence.status || '未解析'}`, 'warn');
      showEmpty(`已保存 Motor-CAD 原生导出，但当前解析器未识别可视化坐标/场列。原因：${normalized.reason || '未知'}。可从 Case 成果下载原始 FEA CSV。`);
      return;
    }
    hideEmpty();
    const frames = normalized.frames || [];
    const slider = q('#nativeFEASliderV023');
    if (slider) {
      slider.max = String(Math.max(0, frames.length - 1));
      slider.value = String(Math.min(native.frameIndex, Math.max(0, frames.length - 1)));
    }
    q('#nativeFEAControlsV023')?.classList.remove('hidden');
    status(`Motor-CAD 原生 FEA · ${frames.length} 帧`, 'ok');
    if (!native.frame || native.frame.caseId !== native.caseId) loadFrame(Math.min(native.frameIndex, Math.max(0, frames.length - 1)));
    else drawFrame();
  }

  async function loadFrame(index) {
    const evidence = native.evidence;
    if (!native.caseId || !evidence?.normalization?.normalized) return;
    const frames = evidence.normalization.frames || [];
    if (!frames.length) return;
    const bounded = Math.max(0, Math.min(frames.length - 1, Number(index) || 0));
    native.frameAbort?.abort();
    const controller = new AbortController();
    native.frameAbort = controller;
    try {
      const response = await fetch(`/api/cases/${encodeURIComponent(native.caseId)}/fea-frames/${bounded}`, {signal: controller.signal, cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const frame = await response.json();
      if (native.caseId !== evidence.case_id) return;
      native.frameIndex = bounded;
      native.frame = {...frame, caseId: native.caseId};
      const slider = q('#nativeFEASliderV023');
      if (slider) slider.value = String(bounded);
      const step = q('#nativeFEAStepV023');
      if (step) step.textContent = `${bounded + 1} / ${frames.length}`;
      drawFrame();
    } catch (error) {
      if (error?.name === 'AbortError') return;
      showEmpty(`FEA 帧读取失败：${error.message || error}`);
    }
  }

  function fieldValue(point) {
    const direct = Number(point?.[native.field]);
    if (Number.isFinite(direct)) return direct;
    if (native.field === 'b') {
      const bx = Number(point?.bx), by = Number(point?.by);
      if (Number.isFinite(bx) && Number.isFinite(by)) return Math.hypot(bx, by);
    }
    return null;
  }

  function colorFor(value, min, max) {
    if (!Number.isFinite(value)) return 'rgba(140,150,165,.35)';
    const span = Math.max(1e-12, max - min);
    const t = Math.max(0, Math.min(1, (value - min) / span));
    const hue = 245 - 245 * t;
    return `hsl(${hue.toFixed(1)} 78% 52%)`;
  }

  function drawFrame() {
    if (native.mode !== 'native') return;
    const canvas = q('#nativeFEACanvasV023');
    const frame = native.frame;
    if (!canvas || !frame?.points?.length) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const points = frame.points;
    const xs = points.map(p => Number(p.x)).filter(Number.isFinite);
    const ys = points.map(p => Number(p.y)).filter(Number.isFinite);
    if (!xs.length || !ys.length) return;
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const values = points.map(fieldValue).filter(Number.isFinite);
    const evidenceRanges = native.evidence?.normalization?.global_ranges || {};
    const rangeMin = native.field === 'b' ? Number(evidenceRanges.b_min) : Number(evidenceRanges.pt_min);
    const rangeMax = native.field === 'b' ? Number(evidenceRanges.b_max) : Number(evidenceRanges.pt_max);
    const minV = Number.isFinite(rangeMin) ? rangeMin : (values.length ? Math.min(...values) : 0);
    const maxV = Number.isFinite(rangeMax) ? rangeMax : (values.length ? Math.max(...values) : 1);

    const w = canvas.width, h = canvas.height, pad = 34;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, w, h);
    const spanX = Math.max(1e-9, maxX - minX), spanY = Math.max(1e-9, maxY - minY);
    const scale = Math.min((w - 2 * pad) / spanX, (h - 2 * pad) / spanY);
    const ox = (w - spanX * scale) / 2 - minX * scale;
    const oy = (h - spanY * scale) / 2 + maxY * scale;
    const radius = Math.max(1.1, Math.min(3.2, 750 / Math.sqrt(points.length)));

    for (const point of points) {
      const x = Number(point.x), y = Number(point.y);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      const value = fieldValue(point);
      ctx.fillStyle = colorFor(value, minV, maxV);
      ctx.beginPath();
      ctx.arc(ox + x * scale, oy - y * scale, radius, 0, Math.PI * 2);
      ctx.fill();
    }

    // Compact legend; values remain evidence-derived.
    const grad = ctx.createLinearGradient(w - 210, 0, w - 40, 0);
    for (let i = 0; i <= 10; i++) grad.addColorStop(i / 10, colorFor(minV + (maxV - minV) * i / 10, minV, maxV));
    ctx.fillStyle = 'rgba(15,23,42,.75)';
    ctx.fillRect(w - 242, h - 74, 220, 54);
    ctx.fillStyle = grad;
    ctx.fillRect(w - 220, h - 50, 168, 12);
    ctx.fillStyle = '#e5e7eb';
    ctx.font = '13px system-ui, sans-serif';
    ctx.fillText(`${native.field === 'b' ? 'B' : 'Pt'} ${Number(minV).toPrecision(3)}`, w - 220, h - 56);
    ctx.textAlign = 'right';
    ctx.fillText(Number(maxV).toPrecision(3), w - 52, h - 56);
    ctx.textAlign = 'left';

    const meta = q('#nativeFEAStatusV023');
    if (meta) meta.innerHTML = `<span class="badge ok">Motor-CAD 原生 FEA</span><span>Step ${escapeHtml(frame.step ?? native.frameIndex)} · ${Number(frame.point_count || points.length).toLocaleString()} 显示点 / ${Number(frame.source_point_count || points.length).toLocaleString()} 原始点 · ${native.field === 'b' ? '磁密 B' : '矢量势 Pt'}</span>`;
  }

  function stopPlayback() {
    native.playing = false;
    if (native.timer) window.clearInterval(native.timer);
    native.timer = 0;
    const button = q('#nativeFEAPlayV023');
    if (button) button.textContent = '播放';
  }

  function togglePlayback() {
    const frames = native.evidence?.normalization?.frames || [];
    if (frames.length < 2) return;
    if (native.playing) {
      stopPlayback();
      return;
    }
    native.playing = true;
    const button = q('#nativeFEAPlayV023');
    if (button) button.textContent = '暂停';
    native.timer = window.setInterval(() => {
      const next = (native.frameIndex + 1) % frames.length;
      loadFrame(next);
    }, 180);
  }

  async function refreshSessionEvidence(caseId, force = false) {
    if (!caseId) return;
    const now = Date.now();
    if (!force && now - native.lastSessionFetch < 2200) return;
    native.lastSessionFetch = now;
    const box = q('#motorcadSessionEvidenceV023');
    try {
      const response = await fetch('/api/runtime/motorcad-sessions?limit=50', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      const session = (payload.items || []).find(row => row.case_id === caseId);
      if (!box) return;
      if (!session) {
        box.innerHTML = '<span class="eyebrow">Motor-CAD 会话</span><p class="hint">当前 Case 尚未建立会话所有权证据。</p>';
        return;
      }
      const process = session.process || {};
      box.innerHTML = `<span class="eyebrow">Motor-CAD 会话所有权</span><div class="session-grid-v023"><div><span>Session</span><b>${escapeHtml(session.id)}</b></div><div><span>状态</span><b>${escapeHtml(session.state)}</b></div><div><span>Motor-CAD PID</span><b>${escapeHtml(session.motorcad_pid ?? '-')}</b></div><div><span>内存</span><b>${process.rss_mb != null ? `${escapeHtml(process.rss_mb)} MB` : '-'}</b></div></div><small>${session.reuse_requested && !session.reuse_effective ? '检测到实例复用请求；当前Case仍采用隔离Worker并强制冷释放。待持久Worker池上线后再启用跨Case复用。' : (session.reuse_effective ? '当前会话由持久Owner管理并允许实例复用。' : '默认隔离模式：一个 Case 拥有一个 Motor-CAD 进程树，完成后释放。')}</small>`;
    } catch (error) {
      if (box) box.innerHTML = `<span class="eyebrow">Motor-CAD 会话</span><p class="hint">会话证据读取失败：${escapeHtml(error.message || error)}</p>`;
    }
  }

  function handleSnapshot(snapshot) {
    const caseId = snapshot?.visualization?.case_id || null;
    if (caseId !== native.caseId) {
      stopPlayback();
      native.caseId = caseId;
      native.evidence = null;
      native.frame = null;
      native.frameIndex = 0;
      native.lastEvidenceFetch = 0;
    }
    if (caseId) {
      loadEvidence(caseId, snapshot?.status === 'COMPLETED');
      refreshSessionEvidence(caseId);
    }
    if (native.mode === 'native') renderEvidenceState();
  }

  document.addEventListener('click', (event) => {
    const mode = event.target.closest('[data-fea-mode-v022]')?.dataset.feaModeV022;
    if (mode) {
      native.mode = mode;
      setNativeMode(mode === 'native');
    }
    if (event.target.closest('#nativeFEAPlayV023')) togglePlayback();
  });

  document.addEventListener('input', (event) => {
    if (event.target.id === 'nativeFEASliderV023') {
      stopPlayback();
      loadFrame(Number(event.target.value) || 0);
    }
  });

  document.addEventListener('change', (event) => {
    if (event.target.id === 'nativeFEAFieldV023') {
      native.field = event.target.value === 'pt' ? 'pt' : 'b';
      drawFrame();
    }
  });

  window.addEventListener('mcs:monitor-cases', (event) => {
    const items = event.detail?.items || [];
    const preferred = items.find(row => row.id === native.caseId) || items.find(row => row.execution_status === 'RUNNING') || items.find(row => ['SUCCEEDED','CACHED'].includes(row.execution_status));
    if (preferred?.id && !native.caseId) native.caseId = preferred.id;
    if (native.caseId) loadEvidence(native.caseId);
  });

  if (typeof window.renderMonitorSnapshot === 'function') {
    const previousRender = window.renderMonitorSnapshot;
    window.renderMonitorSnapshot = function(snapshot) {
      previousRender(snapshot);
      handleSnapshot(snapshot);
    };
  }

  window.MCSNativeFEA = {
    loadEvidence,
    loadFrame,
    setMode(mode) {
      native.mode = mode;
      setNativeMode(mode === 'native');
    },
  };
})();
