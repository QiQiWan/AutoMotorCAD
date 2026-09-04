/* MotorCAD Studio V0.91.8 — native, interactive WebGL FEA field viewer.
 *
 * The viewer consumes the versioned FieldData manifest and LOD endpoints, with
 * compatibility fallback to the original FEA evidence endpoints. Geometry
 * preparation runs in a dedicated Web Worker and remains dependency-free for
 * offline Motor-CAD workstations.
 */
(() => {
  const q = (selector, root = document) => root?.querySelector?.(selector) || null;
  const qa = (selector, root = document) => [...(root?.querySelectorAll?.(selector) || [])];
  const tr = (zh, en) => window.MCS_I18N?.t?.(zh, en) ?? zh;
  const safe = value => typeof window.esc === 'function'
    ? window.esc(value)
    : String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const appState = () => window.MCSAppState || {};
  const finite = value => value !== null && value !== '' && Number.isFinite(Number(value));
  const clamp = (value, minimum, maximum) => Math.max(minimum, Math.min(maximum, value));
  const progress = options => window.MCSOperationProgress?.start?.(options) || {
    state: 'running', update() { return this; }, done() { this.state = 'done'; return this; },
    fail() { this.state = 'failed'; return this; }, close() { this.state = 'closed'; return this; },
  };
  const waitFrame = () => new Promise(resolve => requestAnimationFrame(resolve));

  const COLOR_STOPS = [
    [0.000, [0.050, 0.120, 0.330]],
    [0.180, [0.020, 0.390, 0.720]],
    [0.420, [0.000, 0.720, 0.720]],
    [0.680, [0.940, 0.830, 0.230]],
    [1.000, [0.850, 0.100, 0.080]],
  ];

  const STAGES = [
    [() => tr('模型准备', 'Model preparation'), ['STARTING_SOLVER','LOAD_TEMPLATE','MATERIALS','MODEL_VALIDATION','MECHANICAL_PREPARING','LAB_PREPARING','LAB_BUILDING']],
    [() => tr('求解（含网格）', 'Solve (including meshing)'), ['EMAG_SOLVING','EMAG_ADVANCED_SOLVING','EMAG_RESUMED','THERMAL_SOLVING','THERMAL_TRANSIENT_SOLVING','COUPLED_SOLVING','MECHANICAL_SOLVING','LAB_SOLVING','WEIGHT_SOLVING']],
    [() => tr('FEA 导出', 'FEA export'), ['EXPORTING_FEA','FEA_EXPORT_ATTEMPT','FEA_RAW_WRITTEN','FEA_EXPORT_WARNING','NATIVE_FEA_FRAME_AVAILABLE','NATIVE_SCREEN_CAPTURE_WARNING']],
    [() => tr('场标准化', 'Field normalization'), ['NORMALIZING_FEA','FEA_NORMALIZED','FEA_NORMALIZATION_WARNING']],
    [() => tr('结果提取', 'Result extraction'), ['EMAG_EXTRACTING','THERMAL_EXTRACTING','COUPLED_EXTRACTING','MECHANICAL_EXTRACTING','LAB_EXTRACTING']],
    [() => tr('完整度校验', 'Completeness validation'), ['VALIDATING_RESULTS','QUALITY_CHECK']],
    [() => tr('归档', 'Archive'), ['ARCHIVING']],
  ];

  let mountToken = 0;
  let frameAbort = null;
  let frameRequest = 0;
  let resizeObserver = null;
  let playbackTimer = null;
  let activeRenderer = null;
  let activeCleanup = [];
  let hiddenLegacySections = [];
  let activeDebugState = null;
  let activeGeometryWorker = null;
  let geometryBuildDiagnostics = {mode:'uninitialized',durationMs:null,fallbackReason:null};
  const conditionalJsonCache = new Map();

  function fieldLabel(field) {
    const labels = {
      b: tr('磁密 B', 'Flux density B'),
      bx: tr('磁密 Bx', 'Flux density Bx'),
      by: tr('磁密 By', 'Flux density By'),
      bz: tr('磁密 Bz', 'Flux density Bz'),
      pt: tr('矢量势 Pt', 'Vector potential Pt'),
      current_density: tr('电流密度 J', 'Current density J'),
      eddy_current_density: tr('涡流密度 Jeddy', 'Eddy-current density Jeddy'),
      stress: tr('等效应力', 'Equivalent stress'),
      displacement: tr('位移', 'Displacement'),
      temperature: tr('温度', 'Temperature'),
    };
    return labels[String(field || '').toLowerCase()]
      || appState().viewer?.output_schema?.[field]?.label
      || appState().registry?.outputs?.[field]?.label
      || String(field || '').replaceAll('_', ' ');
  }

  function qualityLabel(value) {
    return ({
      VALID: tr('结果可用', 'Result available'),
      WARNING: tr('结果有提示', 'Result has warnings'),
      INVALID: tr('结果不可用', 'Result unavailable'),
      UNVERIFIED: tr('待结果验证', 'Pending result validation'),
      VERIFIED: tr('已验证', 'Verified'),
      PASS: tr('通过', 'Passed'),
      COMPLETE: tr('完整', 'Complete'),
      INCOMPLETE: tr('尚不完整', 'Incomplete'),
      PARTIAL: tr('部分可用', 'Partially available'),
      RAW_ONLY: tr('仅有原始场文件', 'Raw field file only'),
      NOT_APPLICABLE: tr('本分析不需要', 'Not applicable'),
    })[String(value || '').toUpperCase()] || tr('状态待确认', 'Status pending');
  }

  function outputLabel(key) {
    return appState().viewer?.output_schema?.[key]?.label
      || appState().registry?.outputs?.[key]?.label
      || String(key || '').replaceAll('_', ' ');
  }

  function stageState(aliases) {
    const rows = (appState().viewer?.stages || []).filter(row => aliases.includes(row.stage));
    const statuses = rows.map(row => String(row.status || '').toUpperCase());
    if (statuses.some(value => ['FAILED','TIMEOUT','CANCELLED','ABORTED'].includes(value))) return 'blocked';
    if (statuses.includes('RUNNING')) return 'running';
    if (statuses.includes('SUCCEEDED')) return 'done';
    return 'pending';
  }

  function profileSummary(row) {
    const profile = row?.data_profile || {};
    if (profile.point_count != null) return tr(`${Number(profile.point_count).toLocaleString()} 点`, `${Number(profile.point_count).toLocaleString()} points`);
    if (profile.shape) return `${profile.shape[0]} × ${profile.shape[1]}`;
    if (profile.row_count != null) return tr(`${Number(profile.row_count).toLocaleString()} 行`, `${Number(profile.row_count).toLocaleString()} rows`);
    if (profile.frame_count != null) return tr(`${Number(profile.frame_count).toLocaleString()} 帧`, `${Number(profile.frame_count).toLocaleString()} frames`);
    return row?.issue || row?.extractor || row?.source || 'Motor-CAD';
  }

  function contractPanel() {
    const contract = appState().viewer?.result_contract || {};
    const extraction = contract.extraction || {};
    const fea = contract.fea || {};
    const outputs = extraction.outputs || [];
    const status = contract.qualification_eligible ? 'complete' : 'blocked';
    const pipeline = STAGES.map(([label, aliases], index) => {
      const state = stageState(aliases);
      const symbol = state === 'done' ? '✓' : state === 'running' ? '…' : state === 'blocked' ? '!' : index + 1;
      return `<div class="${state}"><span>${symbol}</span><small>${safe(label())}</small></div>`;
    }).join('');
    const archive = contract.archive_integrity || {};
    const issues = [
      ...(fea.issues || []).map(issue => `${tr('有限元场', 'FEA field')} · ${issue}`),
      ...(extraction.missing_required || []).map(id => `${tr('结果提取', 'Result extraction')} · ${tr('缺少', 'Missing')} ${outputLabel(id)}`),
      ...(extraction.invalid_required || []).map(id => `${tr('结果提取', 'Result extraction')} · ${outputLabel(id)} ${tr('的数值未通过验证', 'failed numerical validation')}`),
      ...(contract.integrity_issues || []).filter(Boolean).map(issue => `${tr('归档完整性', 'Archive integrity')} · ${issue}`),
    ];
    return `<section class="qualification-panel-v052 ${status}">
      <div class="qualification-head-v052">
        <div><span class="eyebrow">${tr('结果验证', 'RESULT VALIDATION')}</span>
          <h3>${contract.qualification_eligible ? tr('结果完整，可用于工程判断', 'Results are complete and ready for engineering decisions') : tr('结果尚不完整', 'Results are incomplete')}</h3>
          <p>${tr('自动提取', 'Automatic extraction')} ${extraction.extracted_count ?? 0}/${extraction.requested_count ?? 0} · ${tr('无效', 'invalid')} ${extraction.invalid_count ?? 0} · ${tr('必需结果覆盖', 'required-result coverage')} ${extraction.required_coverage_percent ?? contract.completeness_percent ?? 0}% · ${tr('有限元场', 'FEA field')} ${safe(qualityLabel(fea.status))} · ${tr('归档', 'archive')} ${safe(qualityLabel(archive.status))}</p>
        </div><strong>${safe(qualityLabel(appState().viewer?.case?.quality_status))}</strong>
      </div>
      <div class="fea-pipeline-v052">${pipeline}</div>
      <p class="pipeline-authority-v052">${tr('阶段状态来自当前计算记录；Motor-CAD 内部网格生成与有限元求解合并为一个工程阶段。', 'Stage states come from the active calculation record. Motor-CAD internal meshing and FEA solving are represented as one engineering stage.')}</p>
      ${issues.map(issue => `<div class="contract-issue-v052">${safe(issue)}</div>`).join('')}
      <details class="extraction-matrix-v052"><summary>${tr('自动结果提取与数值质量', 'Automatic result extraction and numerical quality')} · ${outputs.length} ${tr('项', 'items')}</summary>
        <div>${outputs.map(row => `<article class="${safe(String(row.status || '').toLowerCase())}"><span>${safe(row.label || outputLabel(row.id))}<small>${safe(row.unit || tr('无量纲', 'dimensionless'))} · ${safe(profileSummary(row))}</small></span><b>${safe(qualityLabel(row.status))}</b><em>${row.required ? tr('必需结果', 'Required result') : tr('附加结果', 'Additional result')}</em></article>`).join('') || `<p>${tr('当前历史计算记录没有可验证的提取清单，请重新计算。', 'The historical calculation has no verifiable extraction manifest. Run the calculation again.')}</p>`}</div>
      </details>
    </section>`;
  }

  function colorFor(value, minimum, maximum) {
    const t = clamp((Number(value) - minimum) / ((maximum - minimum) || 1), 0, 1);
    for (let index = 0; index < COLOR_STOPS.length - 1; index += 1) {
      const left = COLOR_STOPS[index];
      const right = COLOR_STOPS[index + 1];
      if (t > right[0]) continue;
      const f = (t - left[0]) / ((right[0] - left[0]) || 1);
      return left[1].map((channel, channelIndex) => channel + (right[1][channelIndex] - channel) * f);
    }
    return COLOR_STOPS[COLOR_STOPS.length - 1][1].slice();
  }

  function fieldValue(record, field) {
    const candidates = [record?.[field], record?.values?.[field], record?.fields?.[field], record?.field_values?.[field]];
    const value = candidates.find(finite);
    return value == null ? null : Number(value);
  }

  function nodeId(node, fallback) {
    return String(node?.id ?? node?.node_id ?? node?.index ?? fallback);
  }

  function nodeCoordinates(node, fallback = {}) {
    return {
      x: Number(node?.x ?? node?.X ?? fallback.x ?? 0),
      y: Number(node?.y ?? node?.Y ?? fallback.y ?? 0),
      z: Number(node?.z ?? node?.Z ?? fallback.z ?? 0),
      hasZ: finite(node?.z ?? node?.Z),
    };
  }

  function elementNodeIds(element) {
    const raw = element?.node_ids || element?.nodes || element?.connectivity || element?.vertex_ids || [];
    return Array.isArray(raw) ? raw.map(value => typeof value === 'object' ? nodeId(value, '') : String(value)) : [];
  }

  function elementRegion(element) {
    return element?.region ?? element?.region_name ?? element?.material_region ?? element?.part ?? '';
  }

  function calculateFieldRange(frame, field, normal, useGlobal) {
    const ranges = normal.global_ranges || {};
    const globalMinimum = finite(ranges[`${field}_min`]) ? Number(ranges[`${field}_min`]) : finite(ranges[field]?.min) ? Number(ranges[field].min) : null;
    const globalMaximum = finite(ranges[`${field}_max`]) ? Number(ranges[`${field}_max`]) : finite(ranges[field]?.max) ? Number(ranges[field].max) : null;
    if (useGlobal && globalMinimum !== null && globalMaximum !== null) return [globalMinimum, globalMaximum];
    let minimum = Infinity;
    let maximum = -Infinity;
    for (const element of frame.elements || []) {
      const value = fieldValue(element, field);
      if (!finite(value)) continue;
      minimum = Math.min(minimum, value);
      maximum = Math.max(maximum, value);
    }
    if (minimum === Infinity || maximum === -Infinity) return [0, 1];
    if (minimum === maximum) {
      const delta = Math.max(Math.abs(minimum) * 0.05, 1e-9);
      return [minimum - delta, maximum + delta];
    }
    return [minimum, maximum];
  }

  function resolveNode(frame, id) {
    return frame.nodeMap?.get(String(id)) || null;
  }

  function sourceBounds(frame) {
    let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity, zmin = Infinity, zmax = -Infinity;
    let hasPhysicalZ = false;
    const include = coordinates => {
      if (![coordinates.x, coordinates.y, coordinates.z].every(Number.isFinite)) return;
      xmin = Math.min(xmin, coordinates.x); xmax = Math.max(xmax, coordinates.x);
      ymin = Math.min(ymin, coordinates.y); ymax = Math.max(ymax, coordinates.y);
      zmin = Math.min(zmin, coordinates.z); zmax = Math.max(zmax, coordinates.z);
      hasPhysicalZ ||= coordinates.hasZ;
    };
    for (const node of frame.nodeMap?.values?.() || []) include(nodeCoordinates(node));
    if (xmin === Infinity) {
      for (const element of frame.elements || []) include(nodeCoordinates(element));
    }
    if (xmin === Infinity) return {xmin:0,xmax:1,ymin:0,ymax:1,zmin:0,zmax:0,hasPhysicalZ:false};
    const xySpan = Math.max(xmax - xmin, ymax - ymin, 1e-12);
    hasPhysicalZ = hasPhysicalZ && (zmax - zmin) > xySpan * 1e-7;
    return {xmin,xmax,ymin,ymax,zmin,zmax,hasPhysicalZ};
  }

  function vec3Subtract(a, b) { return [a[0]-b[0], a[1]-b[1], a[2]-b[2]]; }
  function vec3Cross(a, b) { return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]; }
  function vec3Length(a) { return Math.hypot(a[0], a[1], a[2]); }
  function vec3Normalize(a) { const length = vec3Length(a) || 1; return [a[0]/length, a[1]/length, a[2]/length]; }
  function triangleNormal(a, b, c) { return vec3Normalize(vec3Cross(vec3Subtract(b, a), vec3Subtract(c, a))); }

  function pushTriangle(target, a, b, c, color, shade = 1) {
    const normal = triangleNormal(a, b, c);
    const shaded = color.map(channel => clamp(channel * shade, 0, 1));
    for (const point of [a, b, c]) {
      target.positions.push(...point);
      target.colors.push(...shaded);
      target.normals.push(...normal);
    }
  }

  function pushLine(target, a, b, color) {
    target.positions.push(...a, ...b);
    target.colors.push(...color, ...color);
    target.normals.push(0,0,1,0,0,1);
  }

  function elementType(element) {
    return String(element?.element_type ?? element?.cell_type ?? element?.topology ?? element?.type ?? '').toLowerCase();
  }

  function tetraVolumeMeasure(nodes) {
    if (nodes.length < 4) return 0;
    const a = nodeCoordinates(nodes[0]);
    const b = nodeCoordinates(nodes[1]);
    const c = nodeCoordinates(nodes[2]);
    const d = nodeCoordinates(nodes[3]);
    const ab = [b.x-a.x,b.y-a.y,b.z-a.z];
    const ac = [c.x-a.x,c.y-a.y,c.z-a.z];
    const ad = [d.x-a.x,d.y-a.y,d.z-a.z];
    const volume6 = Math.abs(ab[0]*(ac[1]*ad[2]-ac[2]*ad[1])-ab[1]*(ac[0]*ad[2]-ac[2]*ad[0])+ab[2]*(ac[0]*ad[1]-ac[1]*ad[0]));
    let edge = 0;
    for (let left=0;left<4;left+=1) for (let right=left+1;right<4;right+=1) {
      const p=nodeCoordinates(nodes[left]),q=nodeCoordinates(nodes[right]);
      edge=Math.max(edge,Math.hypot(p.x-q.x,p.y-q.y,p.z-q.z));
    }
    return volume6/Math.max(edge**3,1e-30);
  }

  function topologyFaces(element, nodes) {
    const count = nodes.length;
    const type = elementType(element);
    const explicitVolume = Number(element?.dimension ?? element?.spatial_dimension ?? 0) === 3;
    if ((/tet|tetra/.test(type) || (count === 4 && (explicitVolume || tetraVolumeMeasure(nodes) > 1e-8)))) {
      return {volume:true, faces:[[0,2,1],[0,1,3],[1,2,3],[2,0,3]], topology:'tetrahedron'};
    }
    if (/hex|brick|hexa/.test(type) && count >= 8) {
      return {volume:true, faces:[[0,1,2,3],[4,7,6,5],[0,4,5,1],[1,5,6,2],[2,6,7,3],[3,7,4,0]], topology:'hexahedron'};
    }
    if (/wedge|prism/.test(type) && count >= 6) {
      return {volume:true, faces:[[0,2,1],[3,4,5],[0,1,4,3],[1,2,5,4],[2,0,3,5]], topology:'wedge'};
    }
    if (/pyramid/.test(type) && count >= 5) {
      return {volume:true, faces:[[0,3,2,1],[0,1,4],[1,2,4],[2,3,4],[3,0,4]], topology:'pyramid'};
    }
    return {volume:false, faces:[Array.from({length:count},(_,index)=>index)], topology:count === 4 ? 'quadrilateral' : 'surface'};
  }

  function buildSceneGeometry(frame, options) {
    const {field, region, mode, heightScale, minimum, maximum} = options;
    const bounds = sourceBounds(frame);
    const center = [
      (bounds.xmin + bounds.xmax) / 2,
      (bounds.ymin + bounds.ymax) / 2,
      (bounds.zmin + bounds.zmax) / 2,
    ];
    const span = Math.max(bounds.xmax-bounds.xmin, bounds.ymax-bounds.ymin, bounds.zmax-bounds.zmin, 1e-9);
    const normalizePoint = coordinates => [
      (coordinates.x-center[0])/span,
      (coordinates.y-center[1])/span,
      (coordinates.z-center[2])/span,
    ];
    const heightOf = value => ((Number(value)-minimum)/((maximum-minimum)||1)-0.5) * clamp(heightScale, 0, 1.4);
    const solidHalfThickness = 0.028;
    const fill = {positions:[], colors:[], normals:[]};
    const wire = {positions:[], colors:[], normals:[]};
    const points = {positions:[], colors:[], normals:[]};
    const probes = [];
    const edgeMap = new Map();
    let triangleCount = 0;
    let pointCount = 0;
    let considered = 0;
    const elements = (frame.elements || []).filter(element => {
      const value = fieldValue(element, field);
      return finite(value) && (!region || String(elementRegion(element)) === String(region));
    });
    const wireStride = Math.max(1, Math.ceil(elements.length / 180000));
    const boundaryEnabled = mode === 'solid' && !bounds.hasPhysicalZ && elements.length <= 220000;

    const transformCoordinate = (coordinates, value, surfaceSign = 0) => {
      const normalized = normalizePoint(coordinates);
      if (mode === 'height') normalized[2] = heightOf(value);
      else if (mode === 'solid' && !bounds.hasPhysicalZ) normalized[2] = surfaceSign * solidHalfThickness;
      return normalized;
    };

    const elementCentroid = (nodes, element, value) => {
      let coordinate;
      if (nodes.length) {
        const sum = nodes.reduce((acc, node) => {
          const point = nodeCoordinates(node);
          acc[0] += point.x; acc[1] += point.y; acc[2] += point.z;
          return acc;
        }, [0,0,0]);
        coordinate = {x:sum[0]/nodes.length,y:sum[1]/nodes.length,z:sum[2]/nodes.length,hasZ:bounds.hasPhysicalZ};
      } else coordinate = nodeCoordinates(element);
      return {source:coordinate, rendered:transformCoordinate(coordinate, value, mode === 'solid' ? 1 : 0)};
    };

    const volumeFaceMap = new Map();
    let volumeCellCount = 0;
    const renderFace = (faceNodes, faceIds, value, color, elementIndex, allowExtrusion = true) => {
      if (faceNodes.length < 3) return;
      for (let fan = 1; fan < faceNodes.length - 1; fan += 1) {
        const triNodes = [faceNodes[0], faceNodes[fan], faceNodes[fan+1]];
        const triIds = [faceIds[0], faceIds[fan], faceIds[fan+1]];
        const top = triNodes.map(node => transformCoordinate(nodeCoordinates(node), value, mode === 'solid' ? 1 : 0));
        pushTriangle(fill, top[0], top[1], top[2], color, 1);
        triangleCount += 1;
        if (allowExtrusion && mode === 'solid' && !bounds.hasPhysicalZ) {
          const bottom = triNodes.map(node => transformCoordinate(nodeCoordinates(node), value, -1));
          pushTriangle(fill, bottom[2], bottom[1], bottom[0], color, 0.54);
          triangleCount += 1;
        }
        if (elementIndex % wireStride === 0) {
          const lineColor = [0.07,0.10,0.16];
          pushLine(wire, top[0], top[1], lineColor);
          pushLine(wire, top[1], top[2], lineColor);
          pushLine(wire, top[2], top[0], lineColor);
        }
        if (allowExtrusion && boundaryEnabled) {
          for (let edge = 0; edge < 3; edge += 1) {
            const aIndex = edge;
            const bIndex = (edge + 1) % 3;
            const key = [String(triIds[aIndex]), String(triIds[bIndex])].sort().join('|');
            const existing = edgeMap.get(key);
            if (existing) existing.count += 1;
            else edgeMap.set(key, {count:1,a:triNodes[aIndex],b:triNodes[bIndex],value,color});
          }
        }
      }
    };

    for (let elementIndex = 0; elementIndex < elements.length; elementIndex += 1) {
      const element = elements[elementIndex];
      const value = fieldValue(element, field);
      const color = colorFor(value, minimum, maximum);
      const ids = elementNodeIds(element);
      const nodes = ids.map(id => resolveNode(frame, id)).filter(Boolean);
      const centroid = elementCentroid(nodes, element, value);
      if (probes.length < 50000 || elementIndex % Math.ceil(elements.length / 50000) === 0) {
        probes.push({position:centroid.rendered, coordinate:centroid.source, element, value, region:elementRegion(element)});
      }
      if (nodes.length < 3) {
        points.positions.push(...centroid.rendered);
        points.colors.push(...color);
        points.normals.push(0,0,1);
        pointCount += 1;
        continue;
      }
      considered += 1;
      const topology = topologyFaces(element,nodes);
      if (topology.volume) {
        volumeCellCount += 1;
        for (const face of topology.faces) {
          const faceNodes = face.map(index=>nodes[index]).filter(Boolean);
          const faceIds = face.map(index=>ids[index]).filter(value=>value!=null);
          if (faceNodes.length < 3 || faceIds.length !== faceNodes.length) continue;
          const key = faceIds.map(String).sort().join('|');
          const existing = volumeFaceMap.get(key);
          if (existing) existing.count += 1;
          else volumeFaceMap.set(key,{count:1,faceNodes,faceIds,value,color,elementIndex});
        }
        continue;
      }
      for (const face of topology.faces) {
        const faceNodes = face.map(index=>nodes[index]).filter(Boolean);
        const faceIds = face.map(index=>ids[index]).filter(value=>value!=null);
        renderFace(faceNodes,faceIds,value,color,elementIndex,true);
      }
    }

    // Volumetric tetrahedral/hexahedral/prismatic meshes are reduced to their
    // exterior faces. Shared internal faces are omitted, preserving a true 3D
    // shell while keeping GPU and interaction costs predictable.
    for (const face of volumeFaceMap.values()) {
      if (face.count !== 1) continue;
      renderFace(face.faceNodes,face.faceIds,face.value,face.color,face.elementIndex,false);
    }

    if (boundaryEnabled) {
      for (const edge of edgeMap.values()) {
        if (edge.count !== 1) continue;
        const aTop = transformCoordinate(nodeCoordinates(edge.a), edge.value, 1);
        const bTop = transformCoordinate(nodeCoordinates(edge.b), edge.value, 1);
        const aBottom = transformCoordinate(nodeCoordinates(edge.a), edge.value, -1);
        const bBottom = transformCoordinate(nodeCoordinates(edge.b), edge.value, -1);
        pushTriangle(fill, aTop, bTop, bBottom, edge.color, 0.66);
        pushTriangle(fill, aTop, bBottom, aBottom, edge.color, 0.66);
        pushLine(wire, aTop, aBottom, [0.05,0.08,0.13]);
        pushLine(wire, bTop, bBottom, [0.05,0.08,0.13]);
        triangleCount += 2;
      }
    }

    return {
      fill, wire, points, probes, bounds, center, span,
      sourceElementCount: elements.length,
      triangleCount,
      pointCount,
      considered,
      volumeCellCount,
      hasPhysicalZ: bounds.hasPhysicalZ,
      mode,
      minimum,
      maximum,
    };
  }

  const geometryWorkerUrl = () => {
    const version = String(window.MCS_RELEASE?.assetVersion || document.documentElement.dataset.studioVersion || 'current');
    return `/static/results/field-worker.js?v=${encodeURIComponent(version)}`;
  };

  function abortError(message = 'FEA geometry build superseded') {
    const error = new Error(message);
    error.name = 'AbortError';
    return error;
  }

  class FieldGeometryWorkerClient {
    constructor() {
      this.worker = null;
      this.pending = null;
      this.sequence = 0;
      this.supported = typeof Worker === 'function';
      this.disposed = false;
    }

    cancel(reason = 'FEA geometry build superseded') {
      if (this.worker) {
        try { this.worker.terminate(); } catch {}
      }
      this.worker = null;
      if (this.pending) {
        const reject = this.pending.reject;
        this.pending = null;
        reject(abortError(reason));
      }
    }

    async build(frame, options) {
      if (this.disposed) throw abortError('FEA geometry worker is disposed');
      if (!this.supported) {
        const started = performance.now();
        const scene = buildSceneGeometry(frame, options);
        return {scene, mode:'main-thread-fallback', durationMs:performance.now()-started};
      }
      this.cancel();
      const id = ++this.sequence;
      let worker;
      try {
        worker = new Worker(geometryWorkerUrl(), {name:'mcs-fea-geometry'});
      } catch (error) {
        this.supported = false;
        const started = performance.now();
        const scene = buildSceneGeometry(frame, options);
        return {scene, mode:'main-thread-fallback', durationMs:performance.now()-started, fallbackReason:error?.message || String(error)};
      }
      this.worker = worker;
      return new Promise((resolve, reject) => {
        this.pending = {id, reject};
        const cleanup = () => {
          if (this.worker === worker) this.worker = null;
          if (this.pending?.id === id) this.pending = null;
          try { worker.terminate(); } catch {}
        };
        worker.onmessage = event => {
          const message = event.data || {};
          if (message.id !== id) return;
          cleanup();
          if (!message.ok) {
            const error = new Error(message.error?.message || 'FEA geometry worker failed');
            error.name = message.error?.name || 'Error';
            error.stack = message.error?.stack || error.stack;
            reject(error);
            return;
          }
          resolve({scene:message.scene, mode:'web-worker', durationMs:Number(message.durationMs || 0)});
        };
        worker.onerror = event => {
          const error = new Error(event?.message || 'FEA geometry worker failed');
          cleanup();
          reject(error);
        };
        try {
          worker.postMessage({
            type:'build',
            id,
            frame:{elements:frame?.elements || [],nodeMap:frame?.nodeMap || new Map()},
            options,
          });
        } catch (error) {
          cleanup();
          reject(error);
        }
      });
    }

    dispose() {
      this.disposed = true;
      this.cancel('FEA viewer disposed');
    }
  }

  // Column-major matrix helpers compatible with WebGL uniforms.
  function mat4Perspective(fovy, aspect, near, far) {
    const f = 1 / Math.tan(fovy / 2);
    const nf = 1 / (near - far);
    return new Float32Array([
      f/aspect,0,0,0,
      0,f,0,0,
      0,0,(far+near)*nf,-1,
      0,0,2*far*near*nf,0,
    ]);
  }

  function mat4Ortho(left, right, bottom, top, near, far) {
    const lr = 1/(left-right), bt = 1/(bottom-top), nf = 1/(near-far);
    return new Float32Array([
      -2*lr,0,0,0,
      0,-2*bt,0,0,
      0,0,2*nf,0,
      (left+right)*lr,(top+bottom)*bt,(far+near)*nf,1,
    ]);
  }

  function mat4LookAt(eye, center, up) {
    let z = vec3Normalize(vec3Subtract(eye, center));
    let x = vec3Normalize(vec3Cross(up, z));
    if (vec3Length(x) < 1e-8) x = [1,0,0];
    const y = vec3Cross(z, x);
    return new Float32Array([
      x[0],y[0],z[0],0,
      x[1],y[1],z[1],0,
      x[2],y[2],z[2],0,
      -(x[0]*eye[0]+x[1]*eye[1]+x[2]*eye[2]),
      -(y[0]*eye[0]+y[1]*eye[1]+y[2]*eye[2]),
      -(z[0]*eye[0]+z[1]*eye[1]+z[2]*eye[2]),
      1,
    ]);
  }

  function mat4Multiply(a, b) {
    const out = new Float32Array(16);
    for (let column = 0; column < 4; column += 1) {
      for (let row = 0; row < 4; row += 1) {
        out[column*4+row] =
          a[0*4+row]*b[column*4+0] +
          a[1*4+row]*b[column*4+1] +
          a[2*4+row]*b[column*4+2] +
          a[3*4+row]*b[column*4+3];
      }
    }
    return out;
  }

  function transformPoint(matrix, point) {
    const x = point[0], y = point[1], z = point[2];
    const w = matrix[3]*x + matrix[7]*y + matrix[11]*z + matrix[15];
    return [
      (matrix[0]*x + matrix[4]*y + matrix[8]*z + matrix[12]) / (w || 1),
      (matrix[1]*x + matrix[5]*y + matrix[9]*z + matrix[13]) / (w || 1),
      (matrix[2]*x + matrix[6]*y + matrix[10]*z + matrix[14]) / (w || 1),
      w,
    ];
  }

  function cameraMatrices(camera, aspect) {
    const cp = Math.cos(camera.pitch), sp = Math.sin(camera.pitch);
    const sy = Math.sin(camera.yaw), cy = Math.cos(camera.yaw);
    const eye = [
      camera.target[0] + camera.distance * cp * sy,
      camera.target[1] + camera.distance * cp * cy,
      camera.target[2] + camera.distance * sp,
    ];
    const direction = vec3Normalize(vec3Subtract(camera.target, eye));
    const up = Math.abs(direction[2]) > 0.985 ? [0,1,0] : [0,0,1];
    const view = mat4LookAt(eye, camera.target, up);
    const projection = camera.projection === 'orthographic'
      ? mat4Ortho(-camera.orthoScale*aspect, camera.orthoScale*aspect, -camera.orthoScale, camera.orthoScale, -50, 50)
      : mat4Perspective(Math.PI/4, aspect, 0.02, 80);
    return {eye, view, projection, mvp: mat4Multiply(projection, view)};
  }

  function createShader(gl, type, source) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      const message = gl.getShaderInfoLog(shader) || 'Shader compilation failed';
      gl.deleteShader(shader);
      throw new Error(message);
    }
    return shader;
  }

  function createProgram(gl) {
    const vertex = createShader(gl, gl.VERTEX_SHADER, `
      attribute vec3 a_position;
      attribute vec3 a_color;
      attribute vec3 a_normal;
      uniform mat4 u_mvp;
      uniform float u_point_size;
      varying vec3 v_color;
      varying vec3 v_normal;
      void main(){
        gl_Position = u_mvp * vec4(a_position, 1.0);
        gl_PointSize = u_point_size;
        v_color = a_color;
        v_normal = a_normal;
      }
    `);
    const fragment = createShader(gl, gl.FRAGMENT_SHADER, `
      precision mediump float;
      uniform bool u_point_mode;
      uniform bool u_unlit;
      uniform float u_opacity;
      varying vec3 v_color;
      varying vec3 v_normal;
      void main(){
        if(u_point_mode){
          vec2 delta = gl_PointCoord - vec2(0.5);
          if(dot(delta, delta) > 0.25) discard;
        }
        float shade = u_unlit ? 1.0 : 0.73 + 0.27 * abs(dot(normalize(v_normal), normalize(vec3(0.45, 0.35, 0.82))));
        gl_FragColor = vec4(v_color * shade, u_opacity);
      }
    `);
    const program = gl.createProgram();
    gl.attachShader(program, vertex);
    gl.attachShader(program, fragment);
    gl.linkProgram(program);
    gl.deleteShader(vertex);
    gl.deleteShader(fragment);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      const message = gl.getProgramInfoLog(program) || 'Shader link failed';
      gl.deleteProgram(program);
      throw new Error(message);
    }
    return program;
  }

  class WebGLFieldRenderer {
    constructor(canvas) {
      this.canvas = canvas;
      this.gl = canvas.getContext('webgl2', {antialias:true, alpha:false, preserveDrawingBuffer:false})
        || canvas.getContext('webgl', {antialias:true, alpha:false, preserveDrawingBuffer:false});
      if (!this.gl) throw new Error(tr('当前浏览器未提供 WebGL。', 'WebGL is unavailable in this browser.'));
      const gl = this.gl;
      this.program = createProgram(gl);
      this.locations = {
        position: gl.getAttribLocation(this.program, 'a_position'),
        color: gl.getAttribLocation(this.program, 'a_color'),
        normal: gl.getAttribLocation(this.program, 'a_normal'),
        mvp: gl.getUniformLocation(this.program, 'u_mvp'),
        pointSize: gl.getUniformLocation(this.program, 'u_point_size'),
        pointMode: gl.getUniformLocation(this.program, 'u_point_mode'),
        unlit: gl.getUniformLocation(this.program, 'u_unlit'),
        opacity: gl.getUniformLocation(this.program, 'u_opacity'),
      };
      this.buffers = {};
      this.counts = {fill:0,wire:0,points:0,grid:0};
      this.scene = null;
      this.lastMvp = null;
      this.disposed = false;
      gl.enable(gl.DEPTH_TEST);
      gl.depthFunc(gl.LEQUAL);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      this.uploadGrid();
    }

    createAttributeBuffer(name, values) {
      const gl = this.gl;
      if (this.buffers[name]) gl.deleteBuffer(this.buffers[name]);
      const buffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      const payload = ArrayBuffer.isView(values) ? values : new Float32Array(values);
      gl.bufferData(gl.ARRAY_BUFFER, payload, gl.STATIC_DRAW);
      this.buffers[name] = buffer;
      return buffer;
    }

    uploadGroup(prefix, group) {
      this.createAttributeBuffer(`${prefix}:position`, group.positions || []);
      this.createAttributeBuffer(`${prefix}:color`, group.colors || []);
      this.createAttributeBuffer(`${prefix}:normal`, group.normals || []);
      this.counts[prefix] = Math.floor((group.positions || []).length / 3);
    }

    uploadGrid() {
      const grid = {positions:[],colors:[],normals:[]};
      const minor = [0.69,0.73,0.80];
      const major = [0.46,0.52,0.62];
      for (let index = -10; index <= 10; index += 1) {
        const p = index / 10;
        const color = index === 0 ? major : minor;
        pushLine(grid, [p,-1,-0.07], [p,1,-0.07], color);
        pushLine(grid, [-1,p,-0.07], [1,p,-0.07], color);
      }
      pushLine(grid, [-0.68,-0.68,-0.065], [0.76,-0.68,-0.065], [0.78,0.12,0.12]);
      pushLine(grid, [-0.68,-0.68,-0.065], [-0.68,0.76,-0.065], [0.10,0.62,0.26]);
      pushLine(grid, [-0.68,-0.68,-0.065], [-0.68,-0.68,0.62], [0.12,0.34,0.82]);
      this.uploadGroup('grid', grid);
    }

    upload(scene) {
      this.scene = scene;
      this.uploadGroup('fill', scene.fill);
      this.uploadGroup('wire', scene.wire);
      this.uploadGroup('points', scene.points);
    }

    bindGroup(prefix) {
      const gl = this.gl;
      const bind = (location, suffix) => {
        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffers[`${prefix}:${suffix}`]);
        gl.enableVertexAttribArray(location);
        gl.vertexAttribPointer(location, 3, gl.FLOAT, false, 0, 0);
      };
      bind(this.locations.position, 'position');
      bind(this.locations.color, 'color');
      bind(this.locations.normal, 'normal');
    }

    resize() {
      const dpr = clamp(window.devicePixelRatio || 1, 1, 2.25);
      const stage = this.canvas.parentElement;
      const cssWidth = Math.max(320, Math.floor(stage?.clientWidth || this.canvas.clientWidth || 960));
      const cssHeight = Math.max(420, Math.min(860, Math.round(cssWidth * 0.61)));
      const width = Math.round(cssWidth * dpr);
      const height = Math.round(cssHeight * dpr);
      if (this.canvas.width !== width || this.canvas.height !== height) {
        this.canvas.width = width;
        this.canvas.height = height;
        this.canvas.style.height = `${cssHeight}px`;
      }
      this.gl.viewport(0, 0, width, height);
      return {width,height,dpr,aspect:width/Math.max(1,height)};
    }

    drawGroup(prefix, mode, uniforms = {}) {
      const count = this.counts[prefix] || 0;
      if (!count) return;
      const gl = this.gl;
      this.bindGroup(prefix);
      gl.uniform1f(this.locations.pointSize, uniforms.pointSize || 5);
      gl.uniform1i(this.locations.pointMode, uniforms.pointMode ? 1 : 0);
      gl.uniform1i(this.locations.unlit, uniforms.unlit ? 1 : 0);
      gl.uniform1f(this.locations.opacity, uniforms.opacity ?? 1);
      gl.drawArrays(mode, 0, count);
    }

    render(camera, {wireframe=true, grid=true} = {}) {
      if (this.disposed) return null;
      const gl = this.gl;
      const viewport = this.resize();
      const dark = document.body.classList.contains('dark');
      const background = dark ? [0.025,0.045,0.075,1] : [0.955,0.970,0.987,1];
      gl.clearColor(...background);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.useProgram(this.program);
      const matrices = cameraMatrices(camera, viewport.aspect);
      this.lastMvp = matrices.mvp;
      gl.uniformMatrix4fv(this.locations.mvp, false, matrices.mvp);
      if (grid) this.drawGroup('grid', gl.LINES, {unlit:true, opacity:dark?0.42:0.46});
      this.drawGroup('fill', gl.TRIANGLES, {unlit:false, opacity:1});
      this.drawGroup('points', gl.POINTS, {unlit:true, pointMode:true, pointSize:Math.max(4, viewport.dpr*4.2), opacity:0.94});
      if (wireframe) {
        gl.disable(gl.BLEND);
        this.drawGroup('wire', gl.LINES, {unlit:true, opacity:0.70});
        gl.enable(gl.BLEND);
      }
      return {viewport, matrices};
    }

    project(point) {
      if (!this.lastMvp) return null;
      const clip = transformPoint(this.lastMvp, point);
      if (!Number.isFinite(clip[0]) || clip[3] <= 0) return null;
      return {
        x: (clip[0]*0.5+0.5)*this.canvas.clientWidth,
        y: (1-(clip[1]*0.5+0.5))*this.canvas.clientHeight,
        depth: clip[2],
      };
    }

    dispose() {
      if (this.disposed) return;
      this.disposed = true;
      const gl = this.gl;
      Object.values(this.buffers).forEach(buffer => gl.deleteBuffer(buffer));
      gl.deleteProgram(this.program);
      this.buffers = {};
    }
  }

  function restoreLegacyViewer() {
    hiddenLegacySections.forEach(element => {
      if (!element?.isConnected) return;
      element.hidden = false;
      delete element.dataset.hiddenByFea3d;
    });
    hiddenLegacySections = [];
    q('#viewerCanvas')?.classList.remove('fea-3d-authority-v090');
  }

  function hideLegacyViewer() {
    restoreLegacyViewer();
    const viewerCanvas = q('#viewerCanvas');
    if (!viewerCanvas) return;
    hiddenLegacySections = qa('.fea-workbench-v031,.native-fea-workbench-v035,.field-card,.heat-map', viewerCanvas)
      .filter(element => !element.closest('#nativeFieldHostV052'));
    hiddenLegacySections.forEach(element => {
      element.hidden = true;
      element.dataset.hiddenByFea3d = 'true';
    });
    viewerCanvas.classList.add('fea-3d-authority-v090');
  }

  function disposeNativeField() {
    mountToken += 1;
    frameAbort?.abort();
    frameAbort = null;
    resizeObserver?.disconnect();
    resizeObserver = null;
    if (playbackTimer) clearTimeout(playbackTimer);
    playbackTimer = null;
    activeCleanup.splice(0).forEach(cleanup => {
      try { cleanup(); } catch {}
    });
    activeGeometryWorker?.dispose?.();
    activeGeometryWorker = null;
    activeRenderer?.dispose?.();
    activeRenderer = null;
    activeDebugState = null;
    geometryBuildDiagnostics = {mode:'disposed',durationMs:null,fallbackReason:null};
    restoreLegacyViewer();
  }

  function rememberConditionalPayload(path, payload, etag) {
    conditionalJsonCache.set(path,{payload,etag,storedAt:Date.now()});
    while (conditionalJsonCache.size > 24) conditionalJsonCache.delete(conditionalJsonCache.keys().next().value);
  }

  async function apiCall(path, options = {}) {
    const {conditional = false, ...requestOptions} = options || {};
    if (!conditional && typeof window.api === 'function') return window.api(path, requestOptions);
    const cached = conditional ? conditionalJsonCache.get(path) : null;
    const headers = {'Content-Type':'application/json',...(requestOptions.headers || {})};
    if (conditional && cached?.etag) headers['If-None-Match'] = cached.etag;
    const response = await fetch(path, {
      cache:conditional?'default':'no-store',
      ...requestOptions,
      headers,
    });
    if (response.status === 304 && cached) return cached.payload;
    if (!response.ok) {
      let detail;
      try { detail = await response.json(); } catch { detail = await response.text(); }
      const message = typeof detail === 'string' ? detail : (detail?.detail?.message || detail?.detail || JSON.stringify(detail || {}));
      const error = new Error(message || `${response.status} ${response.statusText}`);
      error.status = response.status;
      throw error;
    }
    const payload = await response.json();
    if (conditional) rememberConditionalPayload(path,payload,response.headers.get('ETag'));
    return payload;
  }

  function overlay(show, title = '', detail = '', percent = null) {
    const host = q('#fieldLoadOverlayG50');
    if (!host) return;
    host.classList.toggle('hidden', !show);
    const titleNode = q('b', host);
    const detailNode = q('small', host);
    const ring = q('i', host);
    if (titleNode) titleNode.textContent = title;
    if (detailNode) detailNode.textContent = detail;
    if (ring) {
      if (Number.isFinite(percent)) ring.style.setProperty('--field-load', `${clamp(percent,0,100)}%`);
      else ring.style.removeProperty('--field-load');
    }
  }

  function modeNote(mode, hasPhysicalZ) {
    if (mode === 'height') return tr('高度图仅用于显示场值变化，不表示真实形变', 'The height map visualizes field variation and does not represent physical deformation');
    if (mode === 'solid' && !hasPhysicalZ) return tr('视觉厚度，仅用于观察平面网格', 'Visual thickness for inspecting a planar mesh');
    return hasPhysicalZ ? tr('使用原生三维坐标', 'Using native 3D coordinates') : tr('使用原生平面坐标，可自由旋转观察', 'Using native planar coordinates with free 3D orbit controls');
  }

  async function mountNativeField() {
    const token = ++mountToken;
    const viewer = appState().viewer;
    const caseId = viewer?.case?.id;
    const host = q('#nativeFieldHostV052');
    if (!caseId || !host) return;
    const mounted = () => token === mountToken && host.isConnected && appState().viewer?.case?.id === caseId && q('#nativeFieldHostV052') === host;
    const startup = progress({
      id: `fea-3d-open-${caseId}`,
      label: tr('加载 FEA 三维查看器', 'Load 3D FEA viewer'),
      stage: tr('读取原生 FEA 清单', 'Read native FEA manifest'),
      detail: tr('准备可交互 WebGL 场景', 'Prepare the interactive WebGL scene'),
      percent: 4,
      timeoutMs: 180000,
    });

    try {
      let fieldManifest = null;
      let evidence = null;
      try {
        fieldManifest = await apiCall(`/api/cases/${encodeURIComponent(caseId)}/field-data/manifest`,{conditional:true});
        evidence = fieldManifest?.compatibility?.legacy_evidence || null;
      } catch (error) {
        fieldManifest = null;
      }
      if (!evidence) evidence = await apiCall(`/api/cases/${encodeURIComponent(caseId)}/fea-evidence`);
      if (!mounted()) { startup.close(); return; }
      const normal = evidence.normalization || {};
      const frames = normal.frames || [];
      if (!evidence.available || !normal.normalized || !frames.length) {
        startup.fail(tr('没有可用的标准化 FEA 帧', 'No normalized FEA frame is available'));
        host.innerHTML = `<div class="help-empty"><b>${tr('原生有限元场暂不可绘制', 'The native FEA field cannot be rendered yet')}</b><span>${safe(normal.reason || evidence.status || tr('未生成标准化 FEA 帧', 'No normalized FEA frame was generated'))}。${tr('原始导出与原生屏幕仍保留为诊断证据。', 'Raw exports and native screenshots remain available as diagnostic evidence.')}</span></div>`;
        return;
      }

      const fields = normal.available_fields || [];
      const regions = normal.regions || [];
      const quality = normal.quality_metrics || {};
      const capabilities = normal.capabilities || {};
      const viewerContract = normal.viewer_contract || {};
      const sampling = normal.sampling_contract || {};
      const fullMeshAvailable = Boolean(fieldManifest?.full_mesh_available || (capabilities.full_region_mesh && capabilities.progressive_mesh_chunks));
      const playbackIndices = (viewerContract.playback_frame_indices || frames.map((_, index) => index)).slice(0, 30);
      const samplingComplete = Boolean(sampling.all_extrema_preserved && sampling.all_regions_preserved);

      startup.update({percent:12,stage:tr('建立三维场景','Build 3D scene'),detail:tr('初始化 WebGL、相机与工程控制','Initialize WebGL, camera, and engineering controls')});
      host.innerHTML = `<section class="native-field-v052 native-field-3d-v090">
        <div class="native-field-quality-v053 field-quality-3d-v090">
          <span class="badge ${fullMeshAvailable?'ok':'warn'}">${fullMeshAvailable?tr('完整网格','Full mesh'):tr('采样兼容视图','Sampled compatibility view')}</span>
          <b>${tr('原生有限元三维查看器','Native 3D FEA viewer')}</b>
          <span class="badge ${samplingComplete?'ok':'warn'}">${samplingComplete?tr('证据抽样完整','Evidence sampling complete'):tr('证据抽样需复核','Evidence sampling needs review')}</span>
          <span class="badge ok">${playbackIndices.length} ${tr('帧播放','frame playback')}</span>
          <span>${tr('坐标有效率','Valid coordinates')} ${Number((quality.coordinate_valid_fraction ?? 1)*100).toFixed(2)}%</span>
          <span>${Number(normal.source_point_count || 0).toLocaleString()} ${tr('个源单元','source elements')}</span>
        </div>
        <div class="field-control-shell-v090">
          <div class="native-field-toolbar-v052 native-field-toolbar-3d-v090">
            <label>${tr('着色场','Color field')}<select id="fieldSelectV052">${fields.map(field => `<option value="${safe(field)}">${safe(fieldLabel(field))}</option>`).join('')}</select></label>
            <label class="field-frame-control-v090">${tr('求解帧','Solve frame')}<span><input id="frameSliderV052" type="range" min="0" max="${Math.max(0,frames.length-1)}" value="0"><b id="frameValueV052">1 / ${frames.length}</b></span></label>
            ${regions.length ? `<label>${tr('区域','Region')}<select id="fieldRegionV052"><option value="">${tr('全部区域','All regions')}</option>${regions.map(region => `<option value="${safe(region)}">${safe(region)}</option>`).join('')}</select></label>` : ''}
            <label>${tr('色标','Color range')}<select id="fieldRangeV052"><option value="global">${tr('全帧一致','Consistent across frames')}</option><option value="frame">${tr('当前帧','Current frame')}</option></select></label>
            <label>${tr('显示模式','Display mode')}<select id="fieldGeometryModeG50"><option value="physical">${tr('物理坐标','Physical coordinates')}</option><option value="solid">${tr('薄实体','Thin solid')}</option><option value="height">${tr('场值高度','Field-value height')}</option></select></label>
            <label>${tr('投影','Projection')}<select id="fieldProjectionG50"><option value="perspective">${tr('透视','Perspective')}</option><option value="orthographic">${tr('正交','Orthographic')}</option></select></label>
            <label class="field-height-scale-v090 hidden">${tr('高度比例','Height scale')}<input id="fieldHeightScaleG50" type="range" min="5" max="120" value="45"></label>
            <label class="check-row field-edge-toggle-v090"><input id="fieldPointsV052" type="checkbox" checked>${tr('网格边线','Mesh edges')}</label>
          </div>
          <div class="field-view-actions-3d-v090" role="toolbar" aria-label="${tr('三维视图控制','3D view controls')}">
            <button id="fieldPlayG33" type="button" title="${tr('播放最多 30 个原生求解帧','Play up to 30 native solve frames')}">▶ ${tr('播放','Play')}</button>
            <button id="fieldFocusG33" type="button">${tr('自动聚焦','Fit view')}</button>
            <button type="button" data-field-view="top">${tr('顶视图','Top')}</button>
            <button type="button" data-field-view="front">${tr('前视图','Front')}</button>
            <button type="button" data-field-view="right">${tr('右视图','Right')}</button>
            <button type="button" data-field-view="iso">${tr('等轴测','Isometric')}</button>
            <button id="fieldFullscreenG50" type="button">${tr('全屏','Fullscreen')}</button>
            <a href="/api/cases/${encodeURIComponent(caseId)}/fea-raw" target="_blank" rel="noopener">${tr('打开原生 FEA 数据','Open native FEA data')}</a>
          </div>
        </div>
        <div class="native-field-help-g33">${tr('拖拽旋转 · Shift/右键拖拽平移 · 滚轮缩放 · 双击自动聚焦','Drag to orbit · Shift/right-drag to pan · wheel to zoom · double-click to fit')}</div>
        <div class="native-field-stage-v052 native-field-stage-3d-v090" id="fieldStageG50">
          <canvas id="fieldCanvasV052" width="1200" height="720" tabindex="0" role="img" aria-label="${tr('Motor-CAD 原生有限元三维自由查看器','Motor-CAD native interactive 3D FEA viewer')}"></canvas>
          <div class="field-axis-cue-v090" aria-hidden="true"><span class="x">X</span><span class="y">Y</span><span class="z">Z</span></div>
          <div id="fieldLegendV052" class="field-legend-3d-v090"></div>
          <div id="fieldLoadOverlayG50" class="field-load-overlay-g33 field-load-overlay-3d-v090 hidden"><i></i><b>${tr('正在加载场数据','Loading field data')}</b><small></small></div>
          <div id="fieldModeNoteG50" class="field-mode-note-v090"></div>
        </div>
        <div id="fieldMetaV052" class="native-field-meta-v052 field-meta-3d-v090" role="status" aria-live="polite"></div>
        <div id="fieldProbeV052" class="native-field-probe-v052 field-probe-3d-v090">${tr('点击场图探测最近单元','Select the field to probe the nearest element')}</div>
      </section>`;
      window.MCS_I18N?.apply?.(host);

      const canvas = q('#fieldCanvasV052', host);
      let renderer;
      try {
        renderer = new WebGLFieldRenderer(canvas);
      } catch (error) {
        startup.fail(error.message);
        host.innerHTML = `<div class="help-empty"><b>${tr('WebGL 不可用，已保留兼容有限元视图。','WebGL is unavailable; the compatibility FEA view remains available.')}</b><span>${safe(error.message)}</span></div>`;
        restoreLegacyViewer();
        return;
      }
      activeRenderer = renderer;

      activeGeometryWorker?.dispose?.();
      activeGeometryWorker = new FieldGeometryWorkerClient();
      geometryBuildDiagnostics = {mode:activeGeometryWorker.supported?'web-worker-ready':'main-thread-fallback',durationMs:null,fallbackReason:null};

      const camera = {yaw:Math.PI/4,pitch:Math.PI/6,distance:3.0,target:[0,0,0],projection:'perspective',orthoScale:0.78};
      const frameCache = new Map();
      let currentFrame = null;
      let currentScene = null;
      let currentFrameIndex = 0;
      let currentFrameWasFullMesh = false;
      let renderFrame = 0;
      let geometryBuild = 0;
      let playing = false;
      let playPosition = 0;
      let playbackOperation = null;
      let pointer = null;
      let pointerMoved = false;
      let lastProgressiveBuild = 0;

      const fieldControl = () => q('#fieldSelectV052', host);
      const regionControl = () => q('#fieldRegionV052', host);
      const modeControl = () => q('#fieldGeometryModeG50', host);
      const rangeControl = () => q('#fieldRangeV052', host);
      const edgeControl = () => q('#fieldPointsV052', host);
      const heightControl = () => q('#fieldHeightScaleG50', host);

      function setView(name) {
        if (name === 'top') { camera.yaw = 0; camera.pitch = Math.PI/2 - 0.002; }
        else if (name === 'front') { camera.yaw = 0; camera.pitch = 0; }
        else if (name === 'right') { camera.yaw = Math.PI/2; camera.pitch = 0; }
        else { camera.yaw = Math.PI/4; camera.pitch = Math.PI/6; }
        fitView(false);
      }

      function fitView(render = true) {
        camera.target = [0,0,0];
        camera.distance = 2.65;
        camera.orthoScale = 0.72;
        if (render) scheduleRender();
      }

      function scheduleRender() {
        cancelAnimationFrame(renderFrame);
        renderFrame = requestAnimationFrame(renderNow);
      }

      function renderNow() {
        if (!mounted() || !currentScene || renderer.disposed) return;
        renderer.render(camera, {wireframe:Boolean(edgeControl()?.checked),grid:true});
        activeDebugState = {
          caseId,
          frameIndex:currentFrameIndex,
          renderer:'webgl',
          projection:camera.projection,
          camera:{yaw:camera.yaw,pitch:camera.pitch,distance:camera.distance,target:[...camera.target],orthoScale:camera.orthoScale},
          scene:{sourceElementCount:currentScene.sourceElementCount,triangleCount:currentScene.triangleCount,pointCount:currentScene.pointCount,volumeCellCount:currentScene.volumeCellCount || 0,hasPhysicalZ:currentScene.hasPhysicalZ,mode:currentScene.mode},
          geometryBuild:{...geometryBuildDiagnostics},
          fieldDataContract:fieldManifest?.contract_version || null,
        };
        const metaHost = q('#fieldMetaV052', host);
        if (metaHost) {
          const mode = modeControl()?.value || 'physical';
          metaHost.innerHTML = `<span><b>${Number(currentFrame?.sourceCount || currentScene.sourceElementCount).toLocaleString()}</b> ${tr('源单元','source elements')}</span>
            <span><b>${Number(currentFrame?.elements?.length || 0).toLocaleString()}</b> ${tr('已载入','loaded')}</span>
            <span><b>${currentScene.sourceElementCount.toLocaleString()}</b> ${tr('当前区域','active region')}</span>
            <span><b>${currentScene.triangleCount.toLocaleString()}</b> ${tr('三角单元','triangles')}</span>
            <span><b>${currentFrame?.complete ? tr('完整区域','complete region') : tr('渐进加载','progressive loading')}</b></span>
            <span><b>${safe(currentFrame?.step ?? currentFrameIndex+1)}</b> ${tr('求解帧','solve frame')}</span>
            <span><b>${camera.projection === 'perspective' ? tr('透视','Perspective') : tr('正交','Orthographic')}</b></span>
            <span><b>${geometryBuildDiagnostics.mode === 'web-worker' ? tr('后台几何线程','Geometry worker') : tr('主线程兼容','Main-thread fallback')}</b>${Number.isFinite(geometryBuildDiagnostics.durationMs)?` ${Number(geometryBuildDiagnostics.durationMs).toFixed(1)} ms`:''}</span>
            <span><b>${safe(modeNote(mode,currentScene.hasPhysicalZ))}</b></span>`;
        }
      }

      async function rebuildGeometry({progressive=false} = {}) {
        if (!currentFrame || !mounted()) return;
        const buildToken = ++geometryBuild;
        const field = fieldControl()?.value || fields[0];
        const region = regionControl()?.value || '';
        const mode = modeControl()?.value || 'physical';
        const useGlobal = rangeControl()?.value !== 'frame';
        const [minimum, maximum] = calculateFieldRange(currentFrame, field, normal, useGlobal);
        const heightScale = Number(heightControl()?.value || 45) / 100;
        if (!progressive) overlay(true,tr('生成 GPU 几何','Build GPU geometry'),tr('构建三角面、边线和探测索引','Build triangles, edges, and probe index'),94);
        await waitFrame();
        let buildResult;
        try {
          buildResult = await activeGeometryWorker.build(currentFrame,{field,region,mode,heightScale,minimum,maximum});
        } catch (error) {
          if (error?.name === 'AbortError') return;
          const started = performance.now();
          buildResult = {
            scene:buildSceneGeometry(currentFrame,{field,region,mode,heightScale,minimum,maximum}),
            mode:'main-thread-fallback',
            durationMs:performance.now()-started,
            fallbackReason:error?.message || String(error),
          };
        }
        if (!mounted() || buildToken !== geometryBuild) return;
        geometryBuildDiagnostics = {
          mode:buildResult.mode,
          durationMs:Number(buildResult.durationMs || 0),
          fallbackReason:buildResult.fallbackReason || null,
        };
        const scene = buildResult.scene;
        currentScene = scene;
        renderer.upload(scene);
        const unit = normal.field_metadata?.[field]?.unit || '';
        const legend = q('#fieldLegendV052', host);
        if (legend) legend.innerHTML = `<b>${safe(fieldLabel(field))}</b><i></i><span>${Number(minimum).toPrecision(5)} — ${Number(maximum).toPrecision(5)}${unit?` ${safe(unit)}`:` · ${tr('单位待确认','unit pending')}`}<small>${useGlobal?tr('全帧一致','Consistent across frames'):tr('当前帧','Current frame')} · ${currentFrameWasFullMesh?tr('完整网格','Full mesh'):tr('采样兼容视图','Sampled compatibility view')}</small></span>`;
        const modeNoteHost = q('#fieldModeNoteG50', host);
        if (modeNoteHost) modeNoteHost.textContent = modeNote(mode,scene.hasPhysicalZ);
        q('.field-height-scale-v090',host)?.classList.toggle('hidden',mode!=='height');
        overlay(false);
        scheduleRender();
      }

      function cacheKey(index, field, full) { return full ? `full:${index}` : `sample:${index}:${field}`; }
      function cachePut(key, data) {
        frameCache.set(key,data);
        while (frameCache.size > 5) frameCache.delete(frameCache.keys().next().value);
      }

      async function loadFullFrame(index, requestId, operation) {
        const record = frames[index] || {};
        const field = fieldControl()?.value || fields[0];
        let manifestUrl = `/api/cases/${encodeURIComponent(caseId)}/field-data/frames/${index}/mesh-manifest`;
        let descriptorChunkTemplate = null;
        try {
          const descriptorParams = new URLSearchParams({field});
          const descriptor = await apiCall(`/api/cases/${encodeURIComponent(caseId)}/field-data/frames/${index}/lod/2?${descriptorParams}`,{signal:frameAbort?.signal,conditional:true});
          if (descriptor?.mesh_manifest_url) manifestUrl = descriptor.mesh_manifest_url;
          if (descriptor?.chunk_url_template) descriptorChunkTemplate = descriptor.chunk_url_template;
        } catch (error) {
          if (error?.name === 'AbortError') throw error;
        }
        const manifest = await apiCall(manifestUrl, {signal:frameAbort?.signal,conditional:true});
        if (!mounted() || requestId !== frameRequest) return null;
        const chunks = manifest.chunks || [];
        if (!chunks.length) throw new Error(tr('完整网格清单没有注册网格分块', 'The full-mesh manifest has no mesh chunks'));
        const data = {
          record, manifest, elements:[], nodeMap:new Map(),
          sourceCount:Number(manifest.element_count || record.source_point_count || 0),
          step:manifest.step ?? record.step,
          data_bounds:manifest.data_bounds || record.viewer_data_bounds,
          complete:false, fallback:false,
        };
        let cursor = 0;
        let completed = 0;
        const worker = async () => {
          while (cursor < chunks.length) {
            const localIndex = cursor++;
            const item = chunks[localIndex] || {};
            const chunkIndex = item.index ?? localIndex;
            const chunkTemplate = descriptorChunkTemplate || `/api/cases/${encodeURIComponent(caseId)}/field-data/frames/${index}/mesh-chunks/{chunk_index}`;
            const chunkUrl = chunkTemplate.replace('{chunk_index}', String(Number(chunkIndex)));
            const payload = await apiCall(chunkUrl, {signal:frameAbort?.signal,conditional:true});
            if (!mounted() || requestId !== frameRequest) return;
            (payload.mesh_nodes || []).forEach((node, nodeIndex) => data.nodeMap.set(nodeId(node,nodeIndex),node));
            data.elements.push(...(payload.elements || payload.points || []));
            completed += 1;
            const percent = 18 + Math.round(completed/chunks.length*70);
            const detail = tr(`网格分块 ${completed}/${chunks.length} · ${data.elements.length.toLocaleString()} 单元`, `Mesh chunk ${completed}/${chunks.length} · ${data.elements.length.toLocaleString()} elements`);
            overlay(true,tr('流式读取网格','Stream mesh chunks'),detail,percent);
            operation?.update?.({percent,stage:tr('流式读取网格','Stream mesh chunks'),detail});
            const now = performance.now();
            if ((completed === 1 || completed === chunks.length || now-lastProgressiveBuild > 480) && data.elements.length) {
              lastProgressiveBuild = now;
              currentFrame = data;
              currentFrameWasFullMesh = true;
              rebuildGeometry({progressive:true}).catch(()=>{});
            }
          }
        };
        await Promise.all(Array.from({length:Math.min(3,chunks.length)},worker));
        if (!mounted() || requestId !== frameRequest) return null;
        data.complete = Boolean(manifest.mesh_complete) && (!data.sourceCount || data.elements.length >= data.sourceCount);
        return data;
      }

      async function loadSampleFrame(index, requestId, operation) {
        const field = fieldControl()?.value || fields[0];
        const region = regionControl()?.value || '';
        const params = new URLSearchParams({field});
        if (region) params.set('region',region);
        let payload;
        try {
          payload = await apiCall(`/api/cases/${encodeURIComponent(caseId)}/field-data/frames/${index}/lod/1?${params}`, {signal:frameAbort?.signal,conditional:true});
        } catch (error) {
          if (error?.name === 'AbortError') throw error;
          params.set('max_points','30000');
          payload = await apiCall(`/api/cases/${encodeURIComponent(caseId)}/fea-frames/${index}/view?${params}`, {signal:frameAbort?.signal});
        }
        if (!mounted() || requestId !== frameRequest) return null;
        const nodeMap = new Map();
        (payload.mesh_nodes || []).forEach((node,nodeIndex) => nodeMap.set(nodeId(node,nodeIndex),node));
        operation?.update?.({percent:88,stage:tr('读取兼容场帧','Read compatibility frame'),detail:tr(`读取 ${Number(payload.point_count || 0).toLocaleString()} 个采样单元`, `Read ${Number(payload.point_count || 0).toLocaleString()} sampled elements`)});
        return {
          record:frames[index] || {}, manifest:null,
          elements:payload.points || payload.elements || [], nodeMap,
          sourceCount:Number(payload.source_point_count || payload.point_count || 0),
          step:payload.step, data_bounds:payload.data_bounds,
          complete:!payload.truncated, fallback:true,
        };
      }

      async function loadFrame(index, {fromPlayback=false, forceSample=false} = {}) {
        const numeric = clamp(Number(index) || 0,0,frames.length-1);
        const field = fieldControl()?.value || fields[0];
        const preferFull = fullMeshAvailable && !forceSample;
        const key = cacheKey(numeric,field,preferFull);
        const cached = frameCache.get(key);
        currentFrameIndex = numeric;
        const slider = q('#frameSliderV052',host);
        const frameValue = q('#frameValueV052',host);
        if (slider) slider.value = String(numeric);
        if (frameValue) frameValue.textContent = `${numeric+1} / ${frames.length}`;
        if (cached) {
          currentFrame = cached;
          currentFrameWasFullMesh = !cached.fallback;
          await rebuildGeometry();
          return cached;
        }

        frameAbort?.abort();
        frameAbort = new AbortController();
        const requestId = ++frameRequest;
        const operation = fromPlayback ? playbackOperation : progress({
          id:`fea-3d-frame-${caseId}-${numeric}`,
          label:tr(`加载 FEA 帧 ${numeric+1}/${frames.length}`,`Load FEA frame ${numeric+1}/${frames.length}`),
          stage:tr('读取原生网格清单','Read native mesh manifest'),
          detail:preferFull?tr('优先读取完整三角网格','Prefer the full triangular mesh'):tr('读取采样兼容场帧','Read the sampled compatibility frame'),
          percent:14,
          button:fromPlayback?null:q('#fieldFocusG33',host),
          disableButton:false,
        });
        overlay(true,tr('正在加载场数据','Loading field data'),tr('读取原生网格清单','Read native mesh manifest'),14);
        try {
          let data = null;
          if (preferFull) {
            try {
              data = await loadFullFrame(numeric,requestId,operation);
            } catch (error) {
              if (error?.name === 'AbortError') return null;
              window.toast?.(tr('完整网格读取失败，已切换采样兼容视图。','Full-mesh loading failed; switched to the sampled compatibility view.'),'WARNING',6500);
              data = await loadSampleFrame(numeric,requestId,operation);
            }
          } else data = await loadSampleFrame(numeric,requestId,operation);
          if (!data || !mounted() || requestId !== frameRequest) return null;
          currentFrame = data;
          currentFrameWasFullMesh = !data.fallback;
          cachePut(cacheKey(numeric,field,!data.fallback),data);
          operation?.update?.({percent:94,stage:tr('后台生成 GPU 几何','Build GPU geometry in worker'),detail:tr(`${data.elements.length.toLocaleString()} 个单元`,`${data.elements.length.toLocaleString()} elements`)});
          await rebuildGeometry();
          if (!fromPlayback) operation?.done?.(data.complete?tr('完整网格已显示','Full mesh displayed'):tr('兼容场帧已显示','Compatibility field frame displayed'));
          return data;
        } catch (error) {
          if (error?.name === 'AbortError') return null;
          overlay(false);
          if (!fromPlayback) operation?.fail?.(error.message);
          const meta = q('#fieldMetaV052',host);
          if (meta) meta.innerHTML = `<span class="field-integrity-error-v054"><b>${tr('场帧读取被阻断','Field-frame loading was blocked')}</b> ${safe(error.message)} <button id="retryFieldV055" type="button">${tr('重新加载','Reload')}</button></span>`;
          q('#retryFieldV055',host)?.addEventListener('click',()=>loadFrame(numeric));
          throw error;
        }
      }

      async function playbackStep() {
        if (!playing || !mounted()) return;
        if (playPosition >= playbackIndices.length) {
          playing = false;
          q('#fieldPlayG33',host).textContent = `▶ ${tr('播放','Play')}`;
          playbackOperation?.done?.(tr(`${playbackIndices.length} 帧播放完成`,`${playbackIndices.length}-frame playback completed`));
          playbackOperation = null;
          return;
        }
        const index = playbackIndices[playPosition++];
        playbackOperation?.update?.({
          percent:Math.round((playPosition-1)/Math.max(1,playbackIndices.length)*100),
          stage:tr(`播放 ${playPosition}/${playbackIndices.length}`,`Playback ${playPosition}/${playbackIndices.length}`),
          detail:tr(`加载求解帧 ${index+1}`,`Load solve frame ${index+1}`),
        });
        try { await loadFrame(index,{fromPlayback:true}); }
        catch (error) {
          playing = false;
          q('#fieldPlayG33',host).textContent = `▶ ${tr('播放','Play')}`;
          playbackOperation?.fail?.(error.message);
          playbackOperation = null;
          return;
        }
        if (playing) playbackTimer = setTimeout(playbackStep,180);
      }

      function togglePlayback() {
        const button = q('#fieldPlayG33',host);
        if (playing) {
          playing = false;
          if (playbackTimer) clearTimeout(playbackTimer);
          playbackTimer = null;
          if (button) button.textContent = `▶ ${tr('播放','Play')}`;
          playbackOperation?.done?.(tr('播放已暂停','Playback paused'));
          playbackOperation = null;
          return;
        }
        playing = true;
        playPosition = Math.max(0,playbackIndices.indexOf(currentFrameIndex));
        if (button) button.textContent = `Ⅱ ${tr('暂停','Pause')}`;
        playbackOperation = progress({
          id:`fea-3d-play-${caseId}`,
          label:tr(`播放 FEA 场 · ${playbackIndices.length} 帧`,`Play FEA field · ${playbackIndices.length} frames`),
          detail:tr('按原生求解帧顺序加载','Load native solve frames in sequence'),
          percent:0,button,disableButton:false,
        });
        playbackStep();
      }

      function panCamera(dx, dy) {
        const matrices = cameraMatrices(camera,canvas.width/Math.max(1,canvas.height));
        const forward = vec3Normalize(vec3Subtract(camera.target,matrices.eye));
        const worldUp = Math.abs(forward[2]) > 0.985 ? [0,1,0] : [0,0,1];
        const right = vec3Normalize(vec3Cross(forward,worldUp));
        const up = vec3Normalize(vec3Cross(right,forward));
        const scale = (camera.projection === 'orthographic' ? camera.orthoScale : camera.distance*0.5) / Math.max(280,canvas.clientHeight);
        for (let axis=0;axis<3;axis+=1) camera.target[axis] += (-dx*right[axis]+dy*up[axis])*scale*2.1;
      }

      function zoomCamera(delta) {
        const factor = Math.exp(delta*0.0012);
        if (camera.projection === 'orthographic') camera.orthoScale = clamp(camera.orthoScale*factor,0.08,6);
        else camera.distance = clamp(camera.distance*factor,0.7,18);
        scheduleRender();
      }

      function probeAt(event) {
        if (!currentScene?.probes?.length || pointerMoved) return;
        const rect = canvas.getBoundingClientRect();
        const x = event.clientX-rect.left, y = event.clientY-rect.top;
        let best = null, bestDistance = Infinity;
        for (const probe of currentScene.probes) {
          const projected = renderer.project(probe.position);
          if (!projected || projected.depth < -1 || projected.depth > 1) continue;
          const distance = (projected.x-x)**2+(projected.y-y)**2;
          if (distance < bestDistance) {bestDistance=distance;best=probe;}
        }
        const hostNode = q('#fieldProbeV052',host);
        if (!best || !hostNode) return;
        const element = best.element || {};
        const coordinate = best.coordinate || nodeCoordinates(element);
        hostNode.innerHTML = `<b>${safe(fieldLabel(fieldControl()?.value))} = ${safe(Number(best.value).toPrecision(7))}</b><span>${tr('单元','Element')} ${safe(element.element_id ?? element.id ?? '—')} · x ${safe(Number(coordinate.x).toPrecision(5))} · y ${safe(Number(coordinate.y).toPrecision(5))}${coordinate.hasZ?` · z ${safe(Number(coordinate.z).toPrecision(5))}`:''}${best.region?` · ${tr('区域','Region')} ${safe(best.region)}`:''}</span>`;
      }

      const onPointerDown = event => {
        canvas.setPointerCapture?.(event.pointerId);
        pointerMoved = false;
        pointer = {id:event.pointerId,x:event.clientX,y:event.clientY,pan:event.shiftKey||event.button===1||event.button===2};
        canvas.classList.add(pointer.pan?'panning':'orbiting');
      };
      const onPointerMove = event => {
        if (!pointer || pointer.id !== event.pointerId) return;
        const dx=event.clientX-pointer.x,dy=event.clientY-pointer.y;
        if (Math.abs(dx)+Math.abs(dy)>2) pointerMoved=true;
        pointer.x=event.clientX;pointer.y=event.clientY;
        if(pointer.pan)panCamera(dx,dy);
        else{
          camera.yaw-=dx*0.008;
          camera.pitch=clamp(camera.pitch+dy*0.006,-Math.PI/2+0.015,Math.PI/2-0.015);
        }
        scheduleRender();
      };
      const releasePointer = event => {
        if (pointer && event.pointerId === pointer.id) pointer=null;
        canvas.classList.remove('panning','orbiting');
      };
      const onContextMenu = event => event.preventDefault();
      const onWheel = event => {event.preventDefault();zoomCamera(event.deltaY);};
      const onDoubleClick = () => fitView();
      const onClick = event => probeAt(event);
      const onKeyDown = event => {
        if (event.key === 'ArrowLeft') camera.yaw += 0.12;
        else if (event.key === 'ArrowRight') camera.yaw -= 0.12;
        else if (event.key === 'ArrowUp') camera.pitch = clamp(camera.pitch-0.10,-Math.PI/2+0.015,Math.PI/2-0.015);
        else if (event.key === 'ArrowDown') camera.pitch = clamp(camera.pitch+0.10,-Math.PI/2+0.015,Math.PI/2-0.015);
        else if (event.key === '+' || event.key === '=') zoomCamera(-120);
        else if (event.key === '-') zoomCamera(120);
        else if (event.key.toLowerCase() === 'f') fitView();
        else if (event.key.toLowerCase() === 't') setView('top');
        else if (event.key.toLowerCase() === 'i') setView('iso');
        else return;
        event.preventDefault();scheduleRender();
      };
      const onContextLost = event => {
        event.preventDefault();
        window.toast?.(tr('WebGL 上下文已丢失，请重新打开有限元场。','The WebGL context was lost. Reopen the FEA field.'),'ERROR',9000);
      };
      canvas.addEventListener('pointerdown',onPointerDown);
      canvas.addEventListener('pointermove',onPointerMove);
      canvas.addEventListener('pointerup',releasePointer);
      canvas.addEventListener('pointercancel',releasePointer);
      canvas.addEventListener('contextmenu',onContextMenu);
      canvas.addEventListener('wheel',onWheel,{passive:false});
      canvas.addEventListener('dblclick',onDoubleClick);
      canvas.addEventListener('click',onClick);
      canvas.addEventListener('keydown',onKeyDown);
      canvas.addEventListener('webglcontextlost',onContextLost,false);
      activeCleanup.push(() => {
        canvas.removeEventListener('pointerdown',onPointerDown);canvas.removeEventListener('pointermove',onPointerMove);canvas.removeEventListener('pointerup',releasePointer);canvas.removeEventListener('pointercancel',releasePointer);canvas.removeEventListener('contextmenu',onContextMenu);canvas.removeEventListener('wheel',onWheel);canvas.removeEventListener('dblclick',onDoubleClick);canvas.removeEventListener('click',onClick);canvas.removeEventListener('keydown',onKeyDown);canvas.removeEventListener('webglcontextlost',onContextLost);
      });

      q('#frameSliderV052',host)?.addEventListener('input',event=>{if(playing)togglePlayback();loadFrame(event.target.value).catch(()=>{});});
      fieldControl()?.addEventListener('change',()=>{
        if (currentFrame?.fallback) loadFrame(currentFrameIndex,{forceSample:true}).catch(()=>{});
        else rebuildGeometry();
      });
      regionControl()?.addEventListener('change',()=>rebuildGeometry());
      rangeControl()?.addEventListener('change',()=>rebuildGeometry());
      edgeControl()?.addEventListener('change',scheduleRender);
      heightControl()?.addEventListener('input',()=>rebuildGeometry({progressive:true}));
      modeControl()?.addEventListener('change',()=>rebuildGeometry());
      q('#fieldProjectionG50',host)?.addEventListener('change',event=>{camera.projection=event.target.value;scheduleRender();});
      q('#fieldPlayG33',host)?.addEventListener('click',togglePlayback);
      q('#fieldFocusG33',host)?.addEventListener('click',()=>fitView());
      qa('[data-field-view]',host).forEach(button=>button.addEventListener('click',()=>setView(button.dataset.fieldView)));
      q('#fieldFullscreenG50',host)?.addEventListener('click',async()=>{
        const stage=q('#fieldStageG50',host);
        try{if(document.fullscreenElement)await document.exitFullscreen();else await stage?.requestFullscreen?.();}catch(error){window.toast?.(error.message,'WARNING',4500)}
      });
      const fullscreenHandler=()=>{const button=q('#fieldFullscreenG50',host);if(button)button.textContent=document.fullscreenElement?tr('退出全屏','Exit fullscreen'):tr('全屏','Fullscreen');scheduleRender();};
      document.addEventListener('fullscreenchange',fullscreenHandler);
      activeCleanup.push(()=>document.removeEventListener('fullscreenchange',fullscreenHandler));

      if ('ResizeObserver' in window) {
        resizeObserver = new ResizeObserver(scheduleRender);
        resizeObserver.observe(q('#fieldStageG50',host));
      }

      // Choose a genuinely spatial default when z is present; otherwise use a thin
      // visual extrusion so a planar cross-section remains readable while orbiting.
      const initialBounds = frames[0]?.viewer_data_bounds;
      if (Array.isArray(initialBounds) && initialBounds.length >= 6 && Math.abs(Number(initialBounds[5])-Number(initialBounds[4])) > 1e-9) modeControl().value='physical';
      else modeControl().value='solid';

      await loadFrame(0);
      if (!mounted()) return;
      hideLegacyViewer();
      fitView();
      startup.done(tr('三维查看器已就绪','3D viewer ready'));
    } catch (error) {
      if (error?.name === 'AbortError') return;
      startup.fail(error?.message || tr('有限元场读取失败','Failed to load the FEA field'));
      restoreLegacyViewer();
      if (mounted()) host.innerHTML = `<div class="help-empty"><b>${tr('有限元场读取失败','Failed to load the FEA field')}</b><span>${safe(error.message)}</span></div>`;
    }
  }

  const previousRenderViewerModule = window.renderViewerModule;
  if (typeof previousRenderViewerModule === 'function') {
    window.renderViewerModule = function renderViewerModuleWith3DField(key) {
      disposeNativeField();
      const result = previousRenderViewerModule.apply(this,arguments);
      const canvas = q('#viewerCanvas');
      if (!canvas || !appState().viewer) return result;
      qa('.result-contract-banner-v046',canvas).forEach(node=>node.remove());
      if (['overview','output_data','fea','graphs','thermal_schematic','temperatures','stress','nvh'].includes(key)) canvas.insertAdjacentHTML('afterbegin',contractPanel());
      if (key === 'fea') {
        canvas.insertAdjacentHTML('beforeend','<div id="nativeFieldHostV052"></div>');
        mountNativeField();
      }
      return result;
    };
  }

  window.addEventListener('mcs:route-ready',()=>{if(!q('#resultViewer')?.classList.contains('active'))disposeNativeField();});
  document.addEventListener('mcs-language-change',()=>{
    if(q('#resultViewer')?.classList.contains('active') && appState().viewer && q('#nativeFieldHostV052')) window.renderViewerModule?.('fea');
  });
  document.body?.classList.add('studio-current','results-stage-active3');
  window.MCSFieldViewer={mountNativeField,dispose:disposeNativeField,renderer:'webgl',getDebugState:()=>activeDebugState?JSON.parse(JSON.stringify(activeDebugState)):null};
})();
