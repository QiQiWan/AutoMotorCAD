/* MotorCAD Studio V0.91.8 — off-main-thread FEA geometry preparation worker. */
'use strict';

const COLOR_STOPS = [
  [0.000, [0.050, 0.120, 0.330]],
  [0.180, [0.020, 0.390, 0.720]],
  [0.420, [0.000, 0.720, 0.720]],
  [0.680, [0.940, 0.830, 0.230]],
  [1.000, [0.850, 0.100, 0.080]],
];

const finite = value => value !== null && value !== '' && Number.isFinite(Number(value));
const clamp = (value, minimum, maximum) => Math.max(minimum, Math.min(maximum, value));

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

function nodeMapGet(frame, id) {
  const nodeMap = frame?.nodeMap;
  if (nodeMap instanceof Map) return nodeMap.get(String(id)) || null;
  if (Array.isArray(nodeMap)) {
    const entry = nodeMap.find(row => Array.isArray(row) && String(row[0]) === String(id));
    return entry?.[1] || null;
  }
  return nodeMap?.[String(id)] || null;
}

function nodeMapValues(frame) {
  const nodeMap = frame?.nodeMap;
  if (nodeMap instanceof Map) return nodeMap.values();
  if (Array.isArray(nodeMap)) return nodeMap.map(row => Array.isArray(row) ? row[1] : row).values();
  return Object.values(nodeMap || {}).values();
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
  for (const node of nodeMapValues(frame)) include(nodeCoordinates(node));
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
    return {volume:true, faces:[[0,2,1],[0,1,3],[1,2,3],[2,0,3]]};
  }
  if (/hex|brick|hexa/.test(type) && count >= 8) {
    return {volume:true, faces:[[0,1,2,3],[4,7,6,5],[0,4,5,1],[1,5,6,2],[2,6,7,3],[3,7,4,0]]};
  }
  if (/wedge|prism/.test(type) && count >= 6) {
    return {volume:true, faces:[[0,2,1],[3,4,5],[0,1,4,3],[1,2,5,4],[2,0,3,5]]};
  }
  if (/pyramid/.test(type) && count >= 5) {
    return {volume:true, faces:[[0,3,2,1],[0,1,4],[1,2,4],[2,3,4],[3,0,4]]};
  }
  return {volume:false, faces:[Array.from({length:count},(_,index)=>index)]};
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
    const nodes = ids.map(id => nodeMapGet(frame, id)).filter(Boolean);
    const centroid = elementCentroid(nodes, element, value);
    if (probes.length < 50000 || elementIndex % Math.ceil(elements.length / 50000) === 0) {
      probes.push({
        position:centroid.rendered,
        coordinate:centroid.source,
        element:{element_id:element?.element_id ?? element?.id ?? elementIndex,id:element?.id ?? element?.element_id ?? elementIndex},
        value,
        region:elementRegion(element),
      });
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

  const typed = group => ({
    positions:new Float32Array(group.positions),
    colors:new Float32Array(group.colors),
    normals:new Float32Array(group.normals),
  });
  return {
    fill:typed(fill), wire:typed(wire), points:typed(points), probes, bounds, center, span,
    sourceElementCount:elements.length,
    triangleCount,
    pointCount,
    considered,
    volumeCellCount,
    hasPhysicalZ:bounds.hasPhysicalZ,
    mode,
    minimum,
    maximum,
  };
}

self.onmessage = event => {
  const message = event.data || {};
  if (message.type !== 'build') return;
  const started = performance.now();
  try {
    const scene = buildSceneGeometry(message.frame || {}, message.options || {});
    const transfer = [
      scene.fill.positions.buffer, scene.fill.colors.buffer, scene.fill.normals.buffer,
      scene.wire.positions.buffer, scene.wire.colors.buffer, scene.wire.normals.buffer,
      scene.points.positions.buffer, scene.points.colors.buffer, scene.points.normals.buffer,
    ];
    self.postMessage({
      id:message.id,
      ok:true,
      durationMs:Math.round((performance.now()-started)*1000)/1000,
      scene,
    }, transfer);
  } catch (error) {
    self.postMessage({
      id:message.id,
      ok:false,
      error:{name:error?.name || 'Error',message:error?.message || String(error),stack:error?.stack || null},
    });
  }
};
