import {DisposableScope} from '../../core/disposable-scope.js';

const MAGIC = 'MCFD';
const textDecoder = new TextDecoder('utf-8');

function clamp(value, minimum, maximum) { return Math.min(maximum, Math.max(minimum, value)); }
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  }[character]));
}
function query(params) {
  const value = new URLSearchParams();
  for (const [key, item] of Object.entries(params)) {
    if (item !== null && item !== undefined && item !== '') value.set(key, String(item));
  }
  return value.toString();
}
async function sha256(buffer) {
  if (!crypto?.subtle) return null;
  const digest = await crypto.subtle.digest('SHA-256', buffer);
  return [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('');
}

class BinaryFieldDataClient {
  constructor({api, signal}) {
    this.api = api;
    this.signal = signal;
    this.cache = new Map();
    this.metrics = {requests: 0, bytes: 0, topologyBytes: 0, scalarBytes: 0, cacheHits: 0};
  }

  async json(url) {
    this.metrics.requests += 1;
    const response = await fetch(url, {signal: this.signal, headers: {'Accept': 'application/json'}});
    if (!response.ok) {
      const body = await response.text().catch(() => '');
      const error = new Error(`FieldData request failed (${response.status})`);
      error.status = response.status;
      error.body = body;
      throw error;
    }
    return response.json();
  }

  async manifest(caseId) {
    return this.json(`/api/cases/${encodeURIComponent(caseId)}/field-data/manifest`);
  }

  async binaryManifest(caseId, frameIndex, field, region) {
    const suffix = query({field, region});
    return this.json(`/api/cases/${encodeURIComponent(caseId)}/field-data/frames/${frameIndex}/binary-manifest?${suffix}`);
  }

  async range(url, start, end, expectedHash, kind) {
    const key = `${url}|${start}-${end}`;
    if (this.cache.has(key)) {
      this.metrics.cacheHits += 1;
      return this.cache.get(key).slice(0);
    }
    this.metrics.requests += 1;
    const response = await fetch(url, {
      signal: this.signal,
      headers: {Range: `bytes=${start}-${end}`, Accept: 'application/vnd.motorcad.fielddata'},
    });
    if (!(response.status === 206 || response.status === 200)) {
      throw new Error(`FieldData range request failed (${response.status})`);
    }
    const raw = await response.arrayBuffer();
    const base = response.status === 206 ? start : 0;
    const relativeStart = start - base;
    const relativeEnd = end - base + 1;
    if (relativeStart < 0 || relativeEnd > raw.byteLength) {
      throw new Error('FieldData range response did not contain the requested bytes');
    }
    const selected = raw.slice(relativeStart, relativeEnd);
    if (expectedHash) {
      const actual = await sha256(selected);
      if (actual && actual !== expectedHash) {
        throw new Error(`${kind} payload hash mismatch`);
      }
    }
    this.metrics.bytes += selected.byteLength;
    if (kind === 'topology') this.metrics.topologyBytes += selected.byteLength;
    if (kind === 'scalar') this.metrics.scalarBytes += selected.byteLength;
    this.cache.set(key, selected.slice(0));
    return selected;
  }

  async frame(binaryManifest, previousTopologyHash = null) {
    const arrays = binaryManifest.arrays || {};
    const position = arrays.positions;
    const index = arrays.indices;
    const scalar = arrays.scalars;
    if (!position || !index || !scalar || !binaryManifest.binary_url) {
      throw new Error('Binary FieldData manifest is incomplete');
    }
    const url = binaryManifest.binary_url;
    let positions = null;
    let indices = null;
    const topologyChanged = previousTopologyHash !== binaryManifest.topology_hash;
    if (topologyChanged) {
      const topologyStart = Number(position.offset);
      const topologyEnd = Number(index.offset) + Number(index.byte_length) - 1;
      const topologyBuffer = await this.range(
        url,
        topologyStart,
        topologyEnd,
        binaryManifest.topology_hash,
        'topology',
      );
      const positionOffset = 0;
      const indexOffset = Number(index.offset) - topologyStart;
      positions = new Float32Array(topologyBuffer, positionOffset, Number(position.byte_length) / 4).slice();
      indices = new Uint32Array(topologyBuffer, indexOffset, Number(index.byte_length) / 4).slice();
    }
    const scalarStart = Number(scalar.offset);
    const scalarEnd = scalarStart + Number(scalar.byte_length) - 1;
    const scalarBuffer = await this.range(
      url,
      scalarStart,
      scalarEnd,
      binaryManifest.scalar_hash,
      'scalar',
    );
    const scalars = new Float32Array(scalarBuffer, 0, Number(scalar.byte_length) / 4).slice();
    return {manifest: binaryManifest, positions, indices, scalars, topologyChanged};
  }
}

function mat4Multiply(a, b) {
  const out = new Float32Array(16);
  for (let column = 0; column < 4; column += 1) {
    for (let row = 0; row < 4; row += 1) {
      out[column * 4 + row] =
        a[0 * 4 + row] * b[column * 4 + 0] +
        a[1 * 4 + row] * b[column * 4 + 1] +
        a[2 * 4 + row] * b[column * 4 + 2] +
        a[3 * 4 + row] * b[column * 4 + 3];
    }
  }
  return out;
}
function perspective(fov, aspect, near, far) {
  const f = 1 / Math.tan(fov / 2);
  const nf = 1 / (near - far);
  return new Float32Array([
    f / aspect, 0, 0, 0,
    0, f, 0, 0,
    0, 0, (far + near) * nf, -1,
    0, 0, (2 * far * near) * nf, 0,
  ]);
}
function orthographic(scale, aspect, near, far) {
  const right = scale * aspect;
  const left = -right;
  const top = scale;
  const bottom = -top;
  return new Float32Array([
    2 / (right - left), 0, 0, 0,
    0, 2 / (top - bottom), 0, 0,
    0, 0, -2 / (far - near), 0,
    -(right + left) / (right - left),
    -(top + bottom) / (top - bottom),
    -(far + near) / (far - near),
    1,
  ]);
}
function normalize3(vector) {
  const length = Math.hypot(vector[0], vector[1], vector[2]) || 1;
  return [vector[0] / length, vector[1] / length, vector[2] / length];
}
function cross3(a, b) {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}
function lookAt(eye, center, up) {
  const z = normalize3([eye[0] - center[0], eye[1] - center[1], eye[2] - center[2]]);
  const x = normalize3(cross3(up, z));
  const y = cross3(z, x);
  return new Float32Array([
    x[0], y[0], z[0], 0,
    x[1], y[1], z[1], 0,
    x[2], y[2], z[2], 0,
    -(x[0] * eye[0] + x[1] * eye[1] + x[2] * eye[2]),
    -(y[0] * eye[0] + y[1] * eye[1] + y[2] * eye[2]),
    -(z[0] * eye[0] + z[1] * eye[1] + z[2] * eye[2]),
    1,
  ]);
}

class IndexedFieldRenderer {
  constructor(canvas, scope, statusCallback) {
    this.canvas = canvas;
    this.scope = scope;
    this.status = statusCallback;
    this.gl = null;
    this.program = null;
    this.vao = null;
    this.positionBuffer = null;
    this.indexBuffer = null;
    this.scalarBuffer = null;
    this.frame = null;
    this.topologyHash = null;
    this.indexCount = 0;
    this.vertexCount = 0;
    this.scalarRange = [0, 1];
    this.bounds = [-1, 1, -1, 1, -1, 1];
    this.projection = 'perspective';
    this.camera = {yaw: -0.75, pitch: 0.55, distance: 3.2, panX: 0, panY: 0};
    this.pendingFrame = 0;
    this.contextLost = false;
    this.metrics = {fullTopologyUploads: 0, scalarOnlyUpdates: 0, contextRestores: 0, drawCalls: 0};
    this._installContextLifecycle();
    this._initialize();
    this._installInteraction();
  }

  _installContextLifecycle() {
    this.scope.listen(this.canvas, 'webglcontextlost', event => {
      event.preventDefault();
      this.contextLost = true;
      this.status('GPU 上下文已丢失，等待恢复', 'WARNING');
    });
    this.scope.listen(this.canvas, 'webglcontextrestored', () => {
      this.contextLost = false;
      this.metrics.contextRestores += 1;
      this._initialize();
      if (this.frame) this._upload(this.frame, true);
      this.status('GPU 上下文已恢复', 'PASS');
    });
  }

  _shader(type, source) {
    const shader = this.gl.createShader(type);
    this.gl.shaderSource(shader, source);
    this.gl.compileShader(shader);
    if (!this.gl.getShaderParameter(shader, this.gl.COMPILE_STATUS)) {
      const error = this.gl.getShaderInfoLog(shader);
      this.gl.deleteShader(shader);
      throw new Error(`WebGL2 shader compilation failed: ${error}`);
    }
    return shader;
  }

  _initialize() {
    const gl = this.canvas.getContext('webgl2', {
      antialias: true, depth: true, alpha: false, preserveDrawingBuffer: false,
    });
    if (!gl) throw new Error('当前浏览器或显卡驱动不支持 WebGL2');
    this.gl = gl;
    const vertex = this._shader(gl.VERTEX_SHADER, `#version 300 es
      precision highp float;
      layout(location=0) in vec3 aPosition;
      layout(location=1) in float aScalar;
      uniform mat4 uMvp;
      uniform vec3 uCenter;
      uniform float uScale;
      out float vScalar;
      void main(){
        vec3 p=(aPosition-uCenter)*uScale;
        gl_Position=uMvp*vec4(p,1.0);
        gl_PointSize=3.0;
        vScalar=aScalar;
      }
    `);
    const fragment = this._shader(gl.FRAGMENT_SHADER, `#version 300 es
      precision highp float;
      in float vScalar;
      uniform vec2 uRange;
      out vec4 outColor;
      vec3 turbo(float x){
        x=clamp(x,0.0,1.0);
        vec3 c0=vec3(0.19,0.07,0.23);
        vec3 c1=vec3(0.10,0.55,0.85);
        vec3 c2=vec3(0.20,0.82,0.45);
        vec3 c3=vec3(0.98,0.87,0.18);
        vec3 c4=vec3(0.80,0.08,0.10);
        if(x<0.25)return mix(c0,c1,x/0.25);
        if(x<0.50)return mix(c1,c2,(x-0.25)/0.25);
        if(x<0.75)return mix(c2,c3,(x-0.50)/0.25);
        return mix(c3,c4,(x-0.75)/0.25);
      }
      void main(){
        float span=max(1e-20,uRange.y-uRange.x);
        outColor=vec4(turbo((vScalar-uRange.x)/span),1.0);
      }
    `);
    const program = gl.createProgram();
    gl.attachShader(program, vertex);
    gl.attachShader(program, fragment);
    gl.linkProgram(program);
    gl.deleteShader(vertex);
    gl.deleteShader(fragment);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      const error = gl.getProgramInfoLog(program);
      gl.deleteProgram(program);
      throw new Error(`WebGL2 program link failed: ${error}`);
    }
    this._deleteGpuObjects();
    this.program = program;
    this.vao = gl.createVertexArray();
    this.positionBuffer = gl.createBuffer();
    this.indexBuffer = gl.createBuffer();
    this.scalarBuffer = gl.createBuffer();
    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.CULL_FACE);
    gl.cullFace(gl.BACK);
    gl.clearColor(0.035, 0.055, 0.085, 1);
  }

  _deleteGpuObjects() {
    const gl = this.gl;
    if (!gl) return;
    if (this.positionBuffer) gl.deleteBuffer(this.positionBuffer);
    if (this.indexBuffer) gl.deleteBuffer(this.indexBuffer);
    if (this.scalarBuffer) gl.deleteBuffer(this.scalarBuffer);
    if (this.vao) gl.deleteVertexArray(this.vao);
    if (this.program) gl.deleteProgram(this.program);
    this.positionBuffer = this.indexBuffer = this.scalarBuffer = this.vao = this.program = null;
  }

  _installInteraction() {
    let pointer = null;
    this.scope.listen(this.canvas, 'pointerdown', event => {
      this.canvas.setPointerCapture?.(event.pointerId);
      pointer = {x: event.clientX, y: event.clientY, pan: event.button === 2 || event.shiftKey};
    });
    this.scope.listen(this.canvas, 'pointermove', event => {
      if (!pointer) return;
      const dx = event.clientX - pointer.x;
      const dy = event.clientY - pointer.y;
      pointer.x = event.clientX;
      pointer.y = event.clientY;
      if (pointer.pan) {
        this.camera.panX += dx * 0.0025 * this.camera.distance;
        this.camera.panY -= dy * 0.0025 * this.camera.distance;
      } else {
        this.camera.yaw += dx * 0.008;
        this.camera.pitch = clamp(this.camera.pitch + dy * 0.008, -1.48, 1.48);
      }
      this.requestRender();
    });
    const release = () => { pointer = null; };
    this.scope.listen(this.canvas, 'pointerup', release);
    this.scope.listen(this.canvas, 'pointercancel', release);
    this.scope.listen(this.canvas, 'contextmenu', event => event.preventDefault());
    this.scope.listen(this.canvas, 'wheel', event => {
      event.preventDefault();
      this.camera.distance = clamp(this.camera.distance * Math.exp(event.deltaY * 0.001), 0.35, 20);
      this.requestRender();
    }, {passive: false});
    this.scope.listen(this.canvas, 'dblclick', () => this.setView('iso'));
    const observer = new ResizeObserver(() => this.requestRender());
    observer.observe(this.canvas);
    this.scope.defer(() => observer.disconnect());
    this.scope.defer(() => this.dispose());
  }

  setView(view) {
    const table = {
      iso: [-0.75, 0.55], top: [0, -1.48], front: [0, 0], right: [Math.PI / 2, 0],
    };
    const [yaw, pitch] = table[view] || table.iso;
    Object.assign(this.camera, {yaw, pitch, distance: 3.2, panX: 0, panY: 0});
    this.requestRender();
  }

  setProjection(value) {
    this.projection = value === 'orthographic' ? 'orthographic' : 'perspective';
    this.requestRender();
  }

  setFrame(frame) {
    const forceTopology = !this.topologyHash || frame.topologyChanged;
    this.frame = frame;
    this._upload(frame, forceTopology);
  }

  _upload(frame, forceTopology) {
    if (this.contextLost || !this.gl) return;
    const gl = this.gl;
    const manifest = frame.manifest;
    if (forceTopology) {
      if (!frame.positions || !frame.indices) throw new Error('Topology data is required for the first frame');
      gl.bindVertexArray(this.vao);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.positionBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, frame.positions, gl.STATIC_DRAW);
      gl.enableVertexAttribArray(0);
      gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indexBuffer);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, frame.indices, gl.STATIC_DRAW);
      this.indexCount = frame.indices.length;
      this.vertexCount = frame.positions.length / 3;
      this.topologyHash = manifest.topology_hash;
      this.bounds = Array.isArray(manifest.bounds) && manifest.bounds.length >= 6
        ? manifest.bounds.map(Number)
        : this._bounds(frame.positions);
      this.metrics.fullTopologyUploads += 1;
    } else {
      this.metrics.scalarOnlyUpdates += 1;
    }
    gl.bindVertexArray(this.vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.scalarBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, frame.scalars, gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(1);
    gl.vertexAttribPointer(1, 1, gl.FLOAT, false, 0, 0);
    this.scalarRange = Array.isArray(manifest.scalar_range) ? manifest.scalar_range.map(Number) : [0, 1];
    gl.bindVertexArray(null);
    this.requestRender();
  }

  _bounds(positions) {
    let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity, zmin = Infinity, zmax = -Infinity;
    for (let i = 0; i < positions.length; i += 3) {
      xmin = Math.min(xmin, positions[i]); xmax = Math.max(xmax, positions[i]);
      ymin = Math.min(ymin, positions[i + 1]); ymax = Math.max(ymax, positions[i + 1]);
      zmin = Math.min(zmin, positions[i + 2]); zmax = Math.max(zmax, positions[i + 2]);
    }
    return [xmin, xmax, ymin, ymax, zmin, zmax].map(value => Number.isFinite(value) ? value : 0);
  }

  requestRender() {
    if (this.pendingFrame || this.contextLost) return;
    this.pendingFrame = requestAnimationFrame(() => {
      this.pendingFrame = 0;
      this.render();
    });
  }

  render() {
    if (!this.gl || !this.program || !this.frame || this.contextLost) return;
    const gl = this.gl;
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    const width = Math.max(1, Math.floor(this.canvas.clientWidth * ratio));
    const height = Math.max(1, Math.floor(this.canvas.clientHeight * ratio));
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
    }
    gl.viewport(0, 0, width, height);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    const aspect = width / height;
    const camera = this.camera;
    const cp = Math.cos(camera.pitch);
    const eye = [
      Math.sin(camera.yaw) * cp * camera.distance,
      Math.sin(camera.pitch) * camera.distance,
      Math.cos(camera.yaw) * cp * camera.distance,
    ];
    const center = [camera.panX, camera.panY, 0];
    const view = lookAt(eye, center, [0, 1, 0]);
    const projection = this.projection === 'orthographic'
      ? orthographic(camera.distance * 0.48, aspect, 0.01, 100)
      : perspective(Math.PI / 4, aspect, 0.01, 100);
    const mvp = mat4Multiply(projection, view);
    const [xmin, xmax, ymin, ymax, zmin, zmax] = this.bounds;
    const modelCenter = [(xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2];
    const extent = Math.max(xmax - xmin, ymax - ymin, zmax - zmin, 1e-12);
    gl.useProgram(this.program);
    gl.uniformMatrix4fv(gl.getUniformLocation(this.program, 'uMvp'), false, mvp);
    gl.uniform3fv(gl.getUniformLocation(this.program, 'uCenter'), modelCenter);
    gl.uniform1f(gl.getUniformLocation(this.program, 'uScale'), 2 / extent);
    gl.uniform2fv(gl.getUniformLocation(this.program, 'uRange'), this.scalarRange);
    gl.bindVertexArray(this.vao);
    if (this.indexCount > 0) gl.drawElements(gl.TRIANGLES, this.indexCount, gl.UNSIGNED_INT, 0);
    else gl.drawArrays(gl.POINTS, 0, this.vertexCount);
    gl.bindVertexArray(null);
    this.metrics.drawCalls += 1;
  }

  snapshot() {
    return {
      authority: 'IndexedFieldRendererSnapshotV1',
      topologyHash: this.topologyHash,
      vertexCount: this.vertexCount,
      triangleCount: this.indexCount / 3,
      projection: this.projection,
      contextLost: this.contextLost,
      metrics: {...this.metrics},
    };
  }

  dispose() {
    if (this.pendingFrame) cancelAnimationFrame(this.pendingFrame);
    this.pendingFrame = 0;
    this._deleteGpuObjects();
    this.frame = null;
  }
}

class BinaryFieldViewerSession {
  constructor({host, caseId, namespace, parentScope, manifest, initialBinaryManifest}) {
    this.host = host;
    this.caseId = caseId;
    this.namespace = namespace;
    this.scope = parentScope.child(`binary-field:${caseId}`);
    this.controller = this.scope.abortController();
    this.client = new BinaryFieldDataClient({api: namespace.api, signal: this.controller.signal});
    this.manifest = manifest;
    this.initialBinaryManifest = initialBinaryManifest;
    this.frameIndex = Number(initialBinaryManifest.frame_index ?? manifest.frames?.[0]?.frame_index ?? 0);
    this.field = String(initialBinaryManifest.field || manifest.available_fields?.[0] || 'b');
    this.region = initialBinaryManifest.region || '';
    this.playTimer = null;
    this.loadingToken = 0;
    this.renderer = null;
    this._renderShell();
    this._bind();
  }

  _renderShell() {
    const frames = this.manifest.frames || [];
    const fields = this.manifest.available_fields?.length ? this.manifest.available_fields : ['b'];
    const regions = this.manifest.regions || [];
    this.host.innerHTML = `
      <section class="mcs-binary-field-viewer" data-field-viewer="binary-v1">
        <header class="mcs-field-toolbar">
          <div class="mcs-field-controls">
            <label>场变量<select data-field-select>${fields.map(value => `<option value="${escapeHtml(value)}"${value === this.field ? ' selected' : ''}>${escapeHtml(value)}</option>`).join('')}</select></label>
            <label>区域<select data-region-select><option value="">全部区域</option>${regions.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join('')}</select></label>
            <button type="button" data-view="iso">等轴测</button>
            <button type="button" data-view="top">顶视</button>
            <button type="button" data-view="front">前视</button>
            <button type="button" data-view="right">右视</button>
            <button type="button" data-projection="perspective" class="active">透视</button>
            <button type="button" data-projection="orthographic">正交</button>
          </div>
          <div class="mcs-field-playback">
            <button type="button" data-play>${frames.length > 1 ? '播放' : '单帧'}</button>
            <input data-frame type="range" min="0" max="${Math.max(0, frames.length - 1)}" value="0" ${frames.length <= 1 ? 'disabled' : ''}>
            <span data-frame-label>帧 1 / ${Math.max(1, frames.length)}</span>
          </div>
        </header>
        <div class="mcs-field-stage">
          <canvas data-field-canvas tabindex="0" aria-label="可交互三维有限元云图"></canvas>
          <aside class="mcs-field-legend"><span data-max>—</span><div></div><span data-min>—</span></aside>
          <div class="mcs-field-status" data-status>准备二进制 FieldData</div>
        </div>
        <footer class="mcs-field-footer">
          <span>左键旋转 · Shift/右键平移 · 滚轮缩放 · 双击复位</span>
          <span data-metrics></span>
        </footer>
      </section>`;
    this.canvas = this.host.querySelector('[data-field-canvas]');
    this.statusNode = this.host.querySelector('[data-status]');
    this.metricsNode = this.host.querySelector('[data-metrics]');
    this.frameInput = this.host.querySelector('[data-frame]');
    this.frameLabel = this.host.querySelector('[data-frame-label]');
    this.renderer = new IndexedFieldRenderer(this.canvas, this.scope, (message, state) => this._status(message, state));
  }

  _bind() {
    this.scope.listen(this.host.querySelector('[data-field-select]'), 'change', event => {
      this.field = event.target.value;
      this.loadCurrent({forceTopology: false});
    });
    this.scope.listen(this.host.querySelector('[data-region-select]'), 'change', event => {
      this.region = event.target.value;
      this.renderer.topologyHash = null;
      this.loadCurrent({forceTopology: true});
    });
    for (const button of this.host.querySelectorAll('[data-view]')) {
      this.scope.listen(button, 'click', () => this.renderer.setView(button.dataset.view));
    }
    for (const button of this.host.querySelectorAll('[data-projection]')) {
      this.scope.listen(button, 'click', () => {
        this.renderer.setProjection(button.dataset.projection);
        for (const peer of this.host.querySelectorAll('[data-projection]')) peer.classList.toggle('active', peer === button);
      });
    }
    this.scope.listen(this.frameInput, 'input', () => {
      const row = (this.manifest.frames || [])[Number(this.frameInput.value)];
      if (!row) return;
      this.frameIndex = Number(row.frame_index);
      this.loadCurrent();
    });
    this.scope.listen(this.host.querySelector('[data-play]'), 'click', event => {
      if ((this.manifest.frames || []).length <= 1) return;
      if (this.playTimer) this.stopPlayback(event.currentTarget);
      else this.startPlayback(event.currentTarget);
    });
  }

  _status(message, state = '') {
    if (!this.statusNode) return;
    this.statusNode.textContent = message;
    this.statusNode.dataset.state = state;
  }

  startPlayback(button) {
    button.textContent = '暂停';
    this.playTimer = setInterval(() => {
      const length = (this.manifest.frames || []).length;
      const next = (Number(this.frameInput.value) + 1) % length;
      this.frameInput.value = String(next);
      const row = this.manifest.frames[next];
      this.frameIndex = Number(row.frame_index);
      this.loadCurrent();
    }, 500);
    this.scope.defer(() => this.stopPlayback(button));
  }

  stopPlayback(button) {
    if (this.playTimer) clearInterval(this.playTimer);
    this.playTimer = null;
    if (button?.isConnected) button.textContent = '播放';
  }

  async loadCurrent({initialManifest = null} = {}) {
    const token = ++this.loadingToken;
    this._status('正在读取二进制 FieldData…', 'LOADING');
    try {
      const binaryManifest = initialManifest || await this.client.binaryManifest(
        this.caseId, this.frameIndex, this.field, this.region,
      );
      const frame = await this.client.frame(binaryManifest, this.renderer.topologyHash);
      if (token !== this.loadingToken || this.scope.disposed) return;
      this.renderer.setFrame(frame);
      const rowIndex = Math.max(0, (this.manifest.frames || []).findIndex(row => Number(row.frame_index) === this.frameIndex));
      this.frameInput.value = String(rowIndex);
      this.frameLabel.textContent = `帧 ${rowIndex + 1} / ${Math.max(1, this.manifest.frames.length)}`;
      const range = binaryManifest.scalar_range || [0, 0];
      this.host.querySelector('[data-min]').textContent = Number(range[0] || 0).toPrecision(4);
      this.host.querySelector('[data-max]').textContent = Number(range[1] || 0).toPrecision(4);
      const renderer = this.renderer.snapshot();
      this.metricsNode.textContent = `${renderer.vertexCount.toLocaleString()} 节点 · ${renderer.triangleCount.toLocaleString()} 三角面 · ${frame.topologyChanged ? '完整拓扑上传' : '仅更新场值'}`;
      this._status('三维有限元云图已就绪', 'PASS');
      this.namespace.diagnostics?.record?.('INFO', 'BINARY_FIELD_FRAME_READY', {
        caseId: this.caseId,
        frameIndex: this.frameIndex,
        field: this.field,
        topologyChanged: frame.topologyChanged,
        renderer,
        transfer: {...this.client.metrics},
      });
    } catch (error) {
      if (error?.name === 'AbortError' || token !== this.loadingToken) return;
      this._status(`二进制云图读取失败：${error.message}`, 'FAIL');
      this.namespace.diagnostics?.record?.('ERROR', 'BINARY_FIELD_FRAME_FAILED', {message: error.message});
    }
  }

  snapshot() {
    return {
      authority: 'BinaryFieldViewerSessionV1',
      caseId: this.caseId,
      frameIndex: this.frameIndex,
      field: this.field,
      region: this.region,
      transfer: {...this.client.metrics},
      renderer: this.renderer?.snapshot?.(),
    };
  }

  dispose() { this.scope.dispose(); }
}

/**
 * Installs one controlled bridge at the current Result Viewer render boundary.
 * Legacy JSON/WebGL rendering remains available until the binary manifest succeeds;
 * then the old viewer is deterministically disposed and replaced.
 */
export function installBinaryFieldViewer({namespace, scope}) {
  const compat = namespace.compat;
  if (!compat || typeof compat.renderViewerModule !== 'function') {
    namespace.diagnostics?.record?.('WARNING', 'BINARY_FIELD_VIEWER_BRIDGE_SKIPPED');
    return {dispose() {}, snapshot: () => ({available: false})};
  }
  const original = compat.renderViewerModule;
  let active = null;
  let mountToken = 0;

  const disposeActive = () => {
    mountToken += 1;
    active?.dispose?.();
    active = null;
  };

  const tryMount = async () => {
    const token = ++mountToken;
    const caseId = String(compat.MCSAppState?.viewer?.case?.id || '');
    const host = document.querySelector('#nativeFieldHostV052');
    if (!caseId || !host) return;
    const probeController = new AbortController();
    const cleanup = () => probeController.abort();
    scope.defer(cleanup);
    try {
      const client = new BinaryFieldDataClient({api: namespace.api, signal: probeController.signal});
      const manifest = await client.manifest(caseId);
      if (!manifest?.available || !(manifest.frames || []).length) return;
      const firstFrame = Number(manifest.frames[0].frame_index || 0);
      const field = String(manifest.available_fields?.[0] || 'b');
      const binaryManifest = await client.binaryManifest(caseId, firstFrame, field, '');
      if (token !== mountToken || !host.isConnected) return;
      compat.MCSFieldViewer?.dispose?.();
      active?.dispose?.();
      active = new BinaryFieldViewerSession({
        host, caseId, namespace, parentScope: scope, manifest, initialBinaryManifest: binaryManifest,
      });
      namespace.binaryFieldViewer = Object.freeze({
        snapshot: () => active?.snapshot?.() || {available: false},
        dispose: disposeActive,
      });
      await active.loadCurrent({initialManifest: binaryManifest});
    } catch (error) {
      if (error?.name === 'AbortError') return;
      namespace.diagnostics?.record?.('WARNING', 'BINARY_FIELD_VIEWER_FALLBACK', {
        caseId, message: error.message, status: error.status,
      });
      // The legacy JSON/LOD viewer stays mounted when the binary endpoint is unavailable.
    }
  };

  const bridge = function renderViewerModuleWithBinaryField(...args) {
    const result = original.apply(this, args);
    const key = String(args[0] || '');
    if (key === 'fea') queueMicrotask(tryMount);
    else disposeActive();
    return result;
  };
  compat.renderViewerModule = bridge;

  scope.defer(() => {
    disposeActive();
    if (compat.renderViewerModule === bridge) compat.renderViewerModule = original;
  });
  return {dispose: disposeActive, snapshot: () => active?.snapshot?.() || {available: false}};
}
