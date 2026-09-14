/*
 * The Fabric canvas is the only renderer.  CollageDocument v2 is the source of
 * truth; Fabric objects are a projection of it and are never reverse-scanned
 * wholesale during save.
 */
const $ = (id) => document.getElementById(id);
const clone = (value) => JSON.parse(JSON.stringify(value));
const PX_PER_MM = 4;
const state = {
  runs: [], candidates: [], doc: null, savedDocumentUrl: null,
  photos: [], assetMap: new Map(), activeId: null, mode: "layout", renderMode: "funnel", renderFallbacks: [],
  history: [], future: [], canvas: null, gestureBefore: null,
  controlBefore: null, aiSpec: null, aiPackageId: null, renderPromise: Promise.resolve(),
};
window.fabricSpikeState = state;

const api = async (url, options = {}) => {
  const response = await fetch(url, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
};
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
const elements = () => state.doc?.elements || [];
const elementId = (element) => String(element?.element_id || element?.id || `element-${Math.random().toString(36).slice(2)}`);
const photoId = (element) => element?.photo_id || element?.asset_id || null;
const activeElement = () => elements().find((element) => elementId(element) === state.activeId) || null;
const canvasSize = () => ({ width: Number(state.doc?.canvas?.width || 1200), height: Number(state.doc?.canvas?.height || 800) });
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
const status = (message) => { if ($("status")) $("status").textContent = message; };
const photoControls = ["opacity", "border-width", "border-color", "mask", "zoom", "rotate", "reset", "raise", "lower"];
function setInspectorState(hasPhoto) {
  photoControls.forEach((control) => { if ($(control)) $(control).disabled = !hasPhoto; });
  if ($("delete")) $("delete").disabled = !Boolean(activeElement());
}
const snapshot = () => clone(state.doc);
const snapshotString = () => JSON.stringify(state.doc);
const record = (before) => {
  if (before && JSON.stringify(before) !== snapshotString()) {
    state.history.push(before);
    state.future = [];
  }
};
const queueRender = () => {
  state.renderPromise = state.renderPromise.then(() => renderNow(), () => renderNow());
  return state.renderPromise;
};

function normalizeDocument(raw) {
  const documentValue = clone(raw || {});
  documentValue.document_type ||= "CollageDocument";
  documentValue.schema_version ||= 2;
  documentValue.page_spec ||= { type: "single", width_mm: 300, height_mm: 200, background: "#f5f2ed" };
  documentValue.canvas ||= {
    width: Math.round(Number(documentValue.page_spec.width_mm || 300) * PX_PER_MM),
    height: Math.round(Number(documentValue.page_spec.height_mm || 200) * PX_PER_MM),
  };
  const source = Array.isArray(documentValue.elements)
    ? documentValue.elements
    : (documentValue.frames || documentValue.cells || []);
  documentValue.elements = source.map((item, index) => ({
    ...item,
    type: item.type || (item.photo_id || item.asset_id ? "photo" : "rectangle"),
    element_id: item.element_id || item.id || `element-${index + 1}`,
    z_index: Number(item.z_index ?? index),
  }));
  documentValue.frames = documentValue.elements.filter((item) => item.type === "photo");
  documentValue.cells = documentValue.frames;
  return documentValue;
}

function photoUrls(assetId) {
  const info = state.assetMap.get(String(assetId));
  const thumbnail = info?.thumbnail || `/api/thumb/${encodeURIComponent(assetId)}`;
  const original = info?.original_url || `/api/original/${encodeURIComponent(assetId)}`;
  return state.renderMode === "view" ? [original, thumbnail] : [thumbnail];
}

function photoUrl(assetId) { return photoUrls(assetId)[0]; }

function sourceSize(element) {
  const info = state.assetMap.get(String(photoId(element))) || {};
  return { width: Number(info.width || 1), height: Number(info.height || 1) };
}

function imageTransform(element) {
  const transform = element.transform || element.image || {};
  return {
    zoom: clamp(Number(transform.zoom || 1), 0.5, 10),
    rotation: Number(transform.rotation_deg ?? transform.rotation ?? 0) || 0,
    focus_x: Number.isFinite(Number(transform.focus_x)) ? clamp(Number(transform.focus_x), 0, 1) : 0.5,
    focus_y: Number.isFinite(Number(transform.focus_y)) ? clamp(Number(transform.focus_y), 0, 1) : 0.5,
  };
}

function elementStyle(element) {
  const style = element.style || {};
  const oldBorder = typeof element.border === "object" ? element.border : {};
  const border = style.border || oldBorder || {};
  const shadow = style.shadow || element.shadow || {};
  return {
    border: {
      width_mm: Number(style.border_width ?? border.width_mm ?? 0),
      color: border.color || style.border_color || (typeof element.border === "string" ? element.border : "#ffffff"),
      opacity: Number(border.opacity ?? 1),
    },
    shadow,
  };
}

function rgba(hex, opacity = 1) {
  const value = String(hex || "#000000").replace("#", "");
  if (value.length !== 6) return hex;
  return `rgba(${parseInt(value.slice(0, 2), 16)},${parseInt(value.slice(2, 4), 16)},${parseInt(value.slice(4, 6), 16)},${clamp(Number(opacity), 0, 1)})`;
}

function createShadow(shadow) {
  if (!shadow || !shadow.color || !Number(shadow.opacity || 0)) return undefined;
  return new fabric.Shadow({
    color: rgba(shadow.color, Number(shadow.opacity ?? 0.16)),
    blur: Number(shadow.blur_mm || 0) * PX_PER_MM,
    offsetX: Number(shadow.offset_x_mm || 0) * PX_PER_MM,
    offsetY: Number(shadow.offset_y_mm || 0) * PX_PER_MM,
  });
}

function shapeName(element) {
  return element.clipping_shape || element.mask?.type || "rectangle";
}

function frameObject(element) {
  const style = elementStyle(element);
  const width = Number(element.width || 0);
  const height = Number(element.height || 0);
  const rounded = shapeName(element) === "rounded";
  const object = new fabric.Rect({
    left: Number(element.x || 0) + width / 2,
    top: Number(element.y || 0) + height / 2,
    originX: "center", originY: "center", width, height,
    fill: "rgba(40,110,103,0.035)",
    stroke: elementId(element) === state.activeId ? "#286e67" : (style.border.color || "#d4cbc1"),
    strokeWidth: elementId(element) === state.activeId ? 2 : Math.max(style.border.width_mm * PX_PER_MM, 1),
    opacity: Number(element.opacity ?? 1),
    angle: Number(element.rotation_deg || 0),
    rx: rounded ? Math.min(width, height) * 0.12 : 0,
    ry: rounded ? Math.min(width, height) * 0.12 : 0,
    shadow: createShadow(style.shadow), objectCaching: false,
    visible: !element.hidden,
    selectable: !element.locked && !element.hidden && state.mode === "layout",
    evented: !element.locked && !element.hidden && state.mode === "layout",
  });
  object._elementId = elementId(element);
  object._kind = "photo-frame";
  return object;
}

function clipPath(element, imageScale) {
  const width = Number(element.width || 0) / Math.max(imageScale, 0.0001);
  const height = Number(element.height || 0) / Math.max(imageScale, 0.0001);
  const shape = shapeName(element);
  const transform = imageTransform(element);
  if (shape === "circle") {
    return new fabric.Circle({ left: 0, top: 0, originX: "center", originY: "center", radius: Math.min(width, height) / 2, angle: -transform.rotation });
  }
  if (shape === "ellipse") {
    return new fabric.Ellipse({ left: 0, top: 0, originX: "center", originY: "center", rx: width / 2, ry: height / 2, angle: -transform.rotation });
  }
  return new fabric.Rect({
    left: 0, top: 0, originX: "center", originY: "center", width, height,
    rx: shape === "rounded" ? Math.min(width, height) * 0.12 : 0,
    ry: shape === "rounded" ? Math.min(width, height) * 0.12 : 0,
    angle: -transform.rotation,
  });
}

async function addPhoto(element) {
  const id = elementId(element);
  const fallbackFrame = frameObject(element);
  state.canvas.add(fallbackFrame);
  const transform = imageTransform(element);
  const source = sourceSize(element);
  let image = null;
  let usedOriginal = false;
  for (const [index, url] of photoUrls(photoId(element)).entries()) {
    image = await fabric.Image.fromURL(url, { crossOrigin: "anonymous" }).catch(() => null);
    if (image) { usedOriginal = state.renderMode === "view" && index === 0; break; }
  }
  if (!image) return;
  if (state.renderMode === "view" && !usedOriginal) state.renderFallbacks.push(photoId(element));
  // The editor intentionally renders the catalog thumbnail.  Catalog metadata
  // may describe the original at a different resolution, so use the loaded
  // image's intrinsic dimensions for cover scaling while preserving its
  // aspect ratio for high-resolution export.
  const loadedSource = { width: Number(image.width || source.width), height: Number(image.height || source.height) };
  const quarterTurn = Math.abs(Math.round(transform.rotation / 90)) % 2 === 1;
  const visualWidth = quarterTurn ? loadedSource.height : loadedSource.width;
  const visualHeight = quarterTurn ? loadedSource.width : loadedSource.height;
  const frameWidth = Number(element.width || 0);
  const frameHeight = Number(element.height || 0);
  const baseScale = Math.max(frameWidth / Math.max(visualWidth, 1), frameHeight / Math.max(visualHeight, 1));
  const imageScale = baseScale * transform.zoom;
  const centerX = Number(element.x || 0) + frameWidth / 2;
  const centerY = Number(element.y || 0) + frameHeight / 2;
  image.set({
    left: centerX + (0.5 - transform.focus_x) * visualWidth * imageScale,
    top: centerY + (0.5 - transform.focus_y) * visualHeight * imageScale,
    originX: "center", originY: "center", scaleX: imageScale, scaleY: imageScale,
    angle: Number(element.rotation_deg || 0) + transform.rotation,
    opacity: Number(element.opacity ?? 1), objectCaching: false,
    visible: !element.hidden, selectable: !element.locked && !element.hidden && state.mode === "crop",
    evented: !element.locked && !element.hidden && state.mode === "crop",
  });
  image.clipPath = clipPath(element, imageScale);
  image._elementId = id; image._kind = "photo-image"; image._baseScale = baseScale;
  image._visualWidth = visualWidth; image._visualHeight = visualHeight;
  state.canvas.remove(fallbackFrame);
  state.canvas.add(image);
  state.canvas.add(frameObject(element));
}

function textOptions(element) {
  const style = element.text_style || {};
  const fontMap = { serif: "Georgia", sans: "Arial", script: "cursive" };
  return {
    left: Number(element.x || 0), top: Number(element.y || 0), width: Number(element.width || 240),
    fontFamily: fontMap[style.font_id] || "Georgia", fontSize: Number(style.font_size_pt || 12) * 1.333,
    fontWeight: style.weight || "normal", fontStyle: style.italic ? "italic" : "normal",
    textAlign: style.alignment || "left", lineHeight: Number(style.line_height || 1.15),
    charSpacing: Number(style.letter_spacing || 0) * 10, fill: style.color || "#292521",
    angle: Number(element.rotation_deg || 0), opacity: Number(element.opacity ?? 1),
    editable: false, objectCaching: false, visible: !element.hidden,
    selectable: !element.locked && !element.hidden && state.mode === "layout",
    evented: !element.locked && !element.hidden && state.mode === "layout",
  };
}

function addDecoration(element) {
  const x = Number(element.x || 0), y = Number(element.y || 0), width = Number(element.width || 0), height = Number(element.height || 0);
  let object;
  if (element.type === "text") object = new fabric.Textbox(String(element.content || ""), textOptions(element));
  else if (element.type === "line") object = new fabric.Line([0, 0, width, height], { left: x, top: y, stroke: element.stroke || "#292521", strokeWidth: Number(element.stroke_width || 1), opacity: Number(element.opacity ?? 1), angle: Number(element.rotation_deg || 0), visible: !element.hidden, selectable: !element.locked && !element.hidden, evented: !element.locked && !element.hidden, objectCaching: false });
  else if (element.type === "ellipse") object = new fabric.Ellipse({ left: x + width / 2, top: y + height / 2, originX: "center", originY: "center", rx: width / 2, ry: height / 2, fill: element.fill || "transparent", stroke: element.stroke || "transparent", strokeWidth: Number(element.stroke_width || 1), opacity: Number(element.opacity ?? 1), angle: Number(element.rotation_deg || 0), visible: !element.hidden, selectable: !element.locked && !element.hidden, evented: !element.locked && !element.hidden, objectCaching: false });
  else if (element.type === "polygon") {
    const points = (element.points || []).map((point) => ({ x: Number(point.x || 0), y: Number(point.y || 0) }));
    object = new fabric.Polygon(points, { left: x, top: y, fill: element.fill || "transparent", stroke: element.stroke || "transparent", strokeWidth: Number(element.stroke_width || 1), opacity: Number(element.opacity ?? 1), angle: Number(element.rotation_deg || 0), visible: !element.hidden, selectable: !element.locked && !element.hidden, evented: !element.locked && !element.hidden, objectCaching: false });
  } else object = new fabric.Rect({ left: x + width / 2, top: y + height / 2, originX: "center", originY: "center", width, height, fill: element.fill || "transparent", stroke: element.stroke || "transparent", strokeWidth: Number(element.stroke_width || 1), opacity: Number(element.opacity ?? 1), angle: Number(element.rotation_deg || 0), visible: !element.hidden, selectable: !element.locked && !element.hidden, evented: !element.locked && !element.hidden, objectCaching: false });
  object._elementId = elementId(element); object._kind = element.type === "text" ? "text" : "decoration";
  state.canvas.add(object);
}

function refreshLayers() {
  const container = $("layers");
  if (!container) return;
  const ordered = [...elements()].sort((a, b) => (Number(b.z_index || 0) - Number(a.z_index || 0)) || elementId(a).localeCompare(elementId(b)));
  container.innerHTML = ordered.map((element) => `<button class="layer-row ${elementId(element) === state.activeId ? "active" : ""}" data-layer-id="${esc(elementId(element))}">${element.hidden ? "◌" : "●"} ${esc(element.type)} · ${esc(elementId(element))}${element.locked ? " 🔒" : ""}</button>`).join("") || `<span class="muted">No layers</span>`;
  container.querySelectorAll("[data-layer-id]").forEach((button) => {
    button.onclick = () => {
      const id = button.dataset.layerId; state.activeId = id;
      const object = state.canvas.getObjects().find((item) => item._elementId === id && (state.mode === "crop" ? item._kind === "photo-image" : item._kind !== "photo-image"));
      if (object) state.canvas.setActiveObject(object);
      inspect(object || { _elementId: id });
    };
  });
}

function inspect(object) {
  const id = object?._elementId || state.activeId;
  state.activeId = id || null;
  const element = activeElement();
  if (!element) {
    if ($("selection")) $("selection").textContent = "No element selected";
    setInspectorState(false);
    refreshLayers(); return;
  }
  const isPhoto = element.type === "photo" || photoId(element);
  setInspectorState(isPhoto);
  $("selection").textContent = `${element.type} · ${elementId(element)}${photoId(element) ? ` · ${photoId(element)}` : ""}`;
  const style = elementStyle(element); const transform = imageTransform(element);
  if ($("opacity")) $("opacity").value = Number(element.opacity ?? 1);
  if ($("border-width")) $("border-width").value = style.border.width_mm;
  if ($("border-color")) $("border-color").value = /^#[0-9a-f]{6}$/i.test(style.border.color) ? style.border.color : "#ffffff";
  if ($("mask")) $("mask").value = shapeName(element);
  if ($("zoom")) $("zoom").value = transform.zoom;
  state.canvas.getObjects().forEach((item) => {
    if (item._kind !== "photo-frame") return;
    const source = elements().find((candidate) => elementId(candidate) === item._elementId);
    item.set({ stroke: item._elementId === state.activeId ? "#286e67" : (elementStyle(source || {}).border.color || "#d4cbc1") });
  });
  state.canvas.requestRenderAll(); refreshLayers();
}

function syncObject(object) {
  const element = elements().find((candidate) => elementId(candidate) === object?._elementId);
  if (!element || !object) return;
  if (object._kind === "photo-frame") {
    const width = Number(object.width || 0) * Number(object.scaleX || 1);
    const height = Number(object.height || 0) * Number(object.scaleY || 1);
    element.x = Math.round(Number(object.left || 0) - width / 2); element.y = Math.round(Number(object.top || 0) - height / 2);
    element.width = Math.round(width); element.height = Math.round(height); element.rotation_deg = Number(object.angle || 0);
    object.set({ scaleX: 1, scaleY: 1 });
  } else if (object._kind === "photo-image") {
    const transform = element.transform || (element.transform = imageTransform(element));
    const sourceWidth = Number(object._visualWidth || 1) * Number(object._baseScale || 1);
    const sourceHeight = Number(object._visualHeight || 1) * Number(object._baseScale || 1);
    const centreX = Number(element.x || 0) + Number(element.width || 0) / 2;
    const centreY = Number(element.y || 0) + Number(element.height || 0) / 2;
    transform.focus_x = clamp(0.5 - (Number(object.left || 0) - centreX) / Math.max(sourceWidth * Number(transform.zoom || 1), 1), 0, 1);
    transform.focus_y = clamp(0.5 - (Number(object.top || 0) - centreY) / Math.max(sourceHeight * Number(transform.zoom || 1), 1), 0, 1);
    transform.zoom = clamp(Number(object.scaleX || 1) / Math.max(Number(object._baseScale || 1), 0.0001), 0.5, 10);
    transform.rotation_deg = Number(object.angle || 0) - Number(element.rotation_deg || 0);
    element.transform = transform; element.image = transform;
  } else {
    element.x = Math.round(Number(object.left || 0)); element.y = Math.round(Number(object.top || 0)); element.rotation_deg = Number(object.angle || 0);
  }
}

function applyInteractivity() {
  state.canvas.getObjects().forEach((object) => {
    const element = elements().find((candidate) => elementId(candidate) === object._elementId);
    const enabled = Boolean(element && !element.locked && !element.hidden);
    object.selectable = enabled && (object._kind === "photo-image" ? state.mode === "crop" : object._kind === "photo-frame" ? state.mode === "layout" : true);
    object.evented = object.selectable;
  });
}

function fitPage() {
  if (!state.canvas || !state.doc) return;
  const wrap = $("canvas-wrap") || $("canvas")?.closest(".canvas-wrap");
  if (!wrap) return;
  const page = canvasSize();
  const availableWidth = Math.max(260, wrap.clientWidth - 28);
  const availableHeight = Math.max(260, Math.floor(window.innerHeight * 0.72));
  const scale = Math.max(0.15, Math.min(1, availableWidth / page.width, availableHeight / page.height));
  state.pageScale = scale;
  // Fabric's viewport owns the coordinate conversion.  Keep the wrapper at
  // the same CSS size as the scaled page so the lower and upper canvases share
  // one hit-test/render viewport.
  state.canvas.setZoom(scale);
  state.canvas.setDimensions({ width: page.width * scale, height: page.height * scale });
  const container = state.canvas.wrapperEl?.parentElement;
  if (container) {
    container.style.width = `${page.width * scale}px`;
    container.style.height = `${page.height * scale}px`;
    container.style.maxWidth = "100%";
  }
}

async function renderNow() {
  if (!state.doc || !state.canvas) return;
  const activeBeforeClear = state.activeId;
  state.canvas.clear(); state.activeId = activeBeforeClear; state.canvas.backgroundColor = state.doc.background || state.doc.page_spec?.background || "#f5f2ed";
  const ordered = [...elements()].sort((a, b) => (Number(a.z_index || 0) - Number(b.z_index || 0)) || elementId(a).localeCompare(elementId(b)));
  state.renderFallbacks = [];
  for (const element of ordered) {
    if (element.hidden) continue;
    if (element.type === "photo" || photoId(element)) await addPhoto(element);
    else addDecoration(element);
  }
  applyInteractivity(); fitPage(); state.canvas.renderAll(); refreshLayers();
  $("identity").textContent = `${state.doc.provider || "document"} · ${state.renderMode} · ${elements().length} elements · ${state.canvas.getObjects().length} layers`;
  if (state.activeId) {
    const desired = state.canvas.getObjects().find((object) => object._elementId === state.activeId && (state.mode === "crop" ? object._kind === "photo-image" : object._kind !== "photo-image"));
    if (desired) state.canvas.setActiveObject(desired); inspect(desired || { _elementId: state.activeId });
  }
  state.canvas.requestRenderAll();
}

function setMode(nextMode) {
  state.mode = nextMode;
  $("layout")?.classList.toggle("primary", nextMode === "layout"); $("crop")?.classList.toggle("primary", nextMode === "crop");
  applyInteractivity(); state.canvas.discardActiveObject(); state.canvas.requestRenderAll(); status(`${nextMode === "crop" ? "Crop" : "Layout"} mode — select an element`); refreshLayers();
}

async function setRenderMode(nextMode) {
  if (!["funnel", "view"].includes(nextMode)) return;
  state.renderMode = nextMode;
  if ($("render-mode")) $("render-mode").value = nextMode;
  if (!state.doc) { status(nextMode === "view" ? "View mode ready: connected originals will be used." : "Fast funnel mode ready."); return; }
  status(nextMode === "view" ? "Loading connected original photos…" : "Loading fast thumbnail preview…");
  await queueRender();
  if (nextMode === "view" && state.renderFallbacks.length) {
    status(`View mode loaded with ${state.renderFallbacks.length} thumbnail fallback(s); original unavailable.`);
  } else {
    status(nextMode === "view" ? "View mode · original photos loaded." : "Fast funnel mode · thumbnail preview loaded.");
  }
}

async function loadPhotos() {
  const ids = [...new Set(elements().map(photoId).filter(Boolean))];
  if (!ids.length) { state.photos = []; state.assetMap = new Map(); $("photos").innerHTML = `<span class="muted">No photo assets in this document.</span>`; return; }
  const data = await api(`/api/collage/photos?${ids.map((id) => `asset_id=${encodeURIComponent(id)}`).join("&")}`);
  state.photos = data.items || []; state.assetMap = new Map(state.photos.map((item) => [String(item.asset_id), item]));
  $("photos").innerHTML = state.photos.map((item) => `<div class="photo" draggable="true" data-id="${esc(item.asset_id)}" title="Drag onto a frame in Crop mode"><img loading="lazy" src="${item.thumbnail || photoUrl(item.asset_id)}" alt="${esc(item.filename)}"><small>${esc(item.filename)}</small></div>`).join("");
  $("photos").querySelectorAll(".photo").forEach((node) => {
    node.ondragstart = (event) => event.dataTransfer.setData("text/plain", node.dataset.id);
    node.ondblclick = () => replacePhoto(node.dataset.id);
  });
}

async function loadCandidates() {
  const runId = $("run")?.value; if (!runId) return;
  const data = await api(`/api/collage/runs/${encodeURIComponent(runId)}`);
  state.candidates = data.candidates || [];
  // Keep the editor's source mode aligned with the run that produced the
  // candidate. Older runs have no mode metadata and intentionally stay fast.
  const runMode = data.render_mode === "view" ? "view" : "funnel";
  state.renderMode = runMode;
  if ($("render-mode")) $("render-mode").value = runMode;
  $("candidate").innerHTML = state.candidates.map((candidate, index) => `<option value="${index}">${esc(candidate.provider)} #${candidate.candidate_number}</option>`).join("") || `<option value="">No candidates</option>`;
  const queryIndex = Number(new URLSearchParams(location.search).get("candidate"));
  if (Number.isInteger(queryIndex) && queryIndex >= 0 && queryIndex < state.candidates.length) $("candidate").value = queryIndex;
}

async function openDocument(url) {
  const documentUrl = url || state.savedDocumentUrl || state.candidates[Number($("candidate")?.value)]?.document;
  if (!documentUrl) { status("Choose a candidate first, or import an AI design."); return; }
  state.doc = normalizeDocument(await api(documentUrl)); state.history = []; state.future = []; state.activeId = elements()[0] ? elementId(elements()[0]) : null;
  await loadPhotos(); await queueRender(); status("Document loaded. Fabric canvas ready.");
}

function downloadBlob(name, blob) {
  const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function exportLayout() {
  if (!state.doc) { status("Open a document first."); return; }
  const assets = [...new Set(elements().map(photoId).filter(Boolean))].map((id) => {
    const info = state.assetMap.get(String(id)) || {}; return { asset_id: id, filename: info.filename || null, source_id: info.source_id || null, width: info.width || null, height: info.height || null };
  });
  downloadBlob(`photomanager-collage-${state.doc.document_id || "layout"}.json`, new Blob([JSON.stringify({ format: "PhotoManager Collage Layout", schema_version: 2, exported_at: new Date().toISOString(), document: state.doc, assets }, null, 2)], { type: "application/json" }));
  status(`Exported ${assets.length} assets and ${elements().length} elements.`);
}

function exportPng() {
  if (!state.doc) { status("Open a document first."); return; }
  try { const dataUrl = state.canvas.toDataURL({ format: "png", multiplier: 2 }); const link = document.createElement("a"); link.href = dataUrl; link.download = `photomanager-collage-preview-${state.doc.document_id || "layout"}.png`; link.click(); status("Exported 2× preview PNG."); } catch (error) { status(`PNG export failed: ${error.message}`); }
}

async function exportHighResPng() {
  if (!state.doc) { status("Open a document first."); return; }
  const previousMode = state.renderMode;
  try {
    state.renderMode = "view";
    if ($("render-mode")) $("render-mode").value = "view";
    status("Loading original photos for high-resolution export…");
    await queueRender();
    if (state.renderFallbacks.length) throw new Error(`${state.renderFallbacks.length} original photo(s) are offline; high-resolution export was not created.`);
    const page = state.doc.page_spec || {};
    const widthMm = Number(page.width_mm || 300) * (page.type === "spread" ? 2 : 1);
    const heightMm = Number(page.height_mm || 200);
    const dpi = clamp(Number(page.dpi || 300), 72, 1200);
    const targetWidth = Math.max(1, Math.round(widthMm / 25.4 * dpi));
    const targetHeight = Math.max(1, Math.round(heightMm / 25.4 * dpi));
    const logical = canvasSize();
    // fitPage() deliberately changes Fabric's backing canvas to the on-screen
    // size. Export from logical document coordinates so the requested physical
    // DPI is not multiplied from a 724px (or similarly fitted) viewport.
    const fittedWidth = state.canvas.getWidth();
    const fittedHeight = state.canvas.getHeight();
    const fittedViewport = state.canvas.viewportTransform ? state.canvas.viewportTransform.slice() : null;
    let dataUrl;
    try {
      state.canvas.setZoom(1);
      state.canvas.setDimensions({ width: logical.width, height: logical.height });
      const multiplier = targetWidth / Math.max(logical.width, 1);
      dataUrl = state.canvas.toDataURL({ format: "png", multiplier, enableRetinaScaling: false });
    } finally {
      state.canvas.setDimensions({ width: fittedWidth, height: fittedHeight });
      if (fittedViewport) state.canvas.setViewportTransform(fittedViewport);
      fitPage();
      state.canvas.requestRenderAll();
    }
    const link = document.createElement("a"); link.href = dataUrl;
    link.download = `photomanager-collage-${state.doc.document_id || "layout"}-${targetWidth}x${targetHeight}px.png`; link.click();
    status(`Exported high-resolution PNG ${targetWidth} × ${targetHeight}px from original photos.`);
  } catch (error) {
    status(`High-resolution export failed: ${error.message}`);
  } finally {
    if (previousMode !== "view") {
      state.renderMode = previousMode;
      if ($("render-mode")) $("render-mode").value = previousMode;
      await queueRender();
    }
  }
}

async function saveVariant() {
  if (!state.doc) { status("Open a document first."); return; }
  try {
    const payload = snapshot(); payload.elements = elements(); payload.frames = elements().filter((element) => element.type === "photo"); payload.cells = payload.frames;
    const result = await api("/api/collage/documents", { method: "POST", body: JSON.stringify(payload) });
    state.doc = normalizeDocument(result.document); state.savedDocumentUrl = result.document_url; state.activeId = elements()[0] ? elementId(elements()[0]) : null; await loadPhotos(); await queueRender(); status(`Saved editable variant ${result.document.document_id}.`);
  } catch (error) { status(`Save failed: ${error.message}`); }
}

function importDebugDocument(file) {
  const reader = new FileReader(); reader.onload = async () => {
    try { const payload = JSON.parse(String(reader.result || "")); state.doc = normalizeDocument(payload.document || payload); state.savedDocumentUrl = null; state.history = []; state.future = []; state.activeId = elements()[0] ? elementId(elements()[0]) : null; await loadPhotos(); await queueRender(); status("Debug CollageDocument imported locally; use AI Design for validated imports."); }
    catch (error) { status(`Debug import failed: ${error.message}`); }
  }; reader.readAsText(file);
}

async function validateAiSpec(spec) {
  status("Validating AI design…");
  const result = await api("/api/collage/design-imports/validate", { method: "POST", body: JSON.stringify({ spec, package_id: spec.package_id }) });
  state.aiSpec = result.spec; state.aiPackageId = result.package_id || spec.package_id || null;
  const selector = $("alternative"); selector.innerHTML = (result.alternatives || []).map((item) => `<option value="${item.alternative}">Alternative ${item.alternative + 1} · ${item.photos} photos · ${item.elements} elements</option>`).join("");
  $("alternative-picker").hidden = (result.alternatives || []).length < 2; $("apply-ai").disabled = false; status(`Validated ${result.alternatives?.length || 0} AI design alternative(s).`);
  if ((result.alternatives || []).length === 1) await applyAiDesign();
}

async function applyAiDesign() {
  if (!state.aiSpec) { status("Validate an AI design first."); return; }
  try {
    status("Opening validated AI design…");
    const result = await api("/api/collage/design-imports", { method: "POST", body: JSON.stringify({ spec: state.aiSpec, package_id: state.aiPackageId, alternative_index: Number($("alternative")?.value || 0) }) });
    state.doc = normalizeDocument(result.document); state.savedDocumentUrl = result.document_url; state.history = []; state.future = []; state.activeId = elements()[0] ? elementId(elements()[0]) : null; await loadPhotos(); await queueRender(); status(`AI design opened as editable variant ${result.document.document_id}.`);
  } catch (error) { status(`AI design import failed: ${error.message}`); }
}

async function loadSample() {
  try { const response = await fetch("/examples/kew-gardens-ai-design-v1.json"); if (!response.ok) throw new Error(`HTTP ${response.status}`); await validateAiSpec(await response.json()); }
  catch (error) { status(`Sample design unavailable: ${error.message}`); }
}

function replacePhoto(assetId) {
  const element = activeElement();
  if (!element || element.type !== "photo") { status("Select a photo frame first, then replace it in Crop mode."); return; }
  if (!state.assetMap.has(String(assetId))) { status("That photo is not in this design package."); return; }
  const before = snapshot(); element.photo_id = assetId; element.asset_id = assetId; record(before); queueRender().then(() => status("Photo replaced in the selected frame."));
}

function beginControl() { if (!state.controlBefore && state.doc) state.controlBefore = snapshot(); }
function updatePhotoControl(mutator) {
  const element = activeElement(); if (!element || element.type !== "photo") { status("Select a photo frame first."); return; }
  beginControl(); mutator(element); queueRender().then(() => status("Unsaved change"));
}
function endControl() { if (state.controlBefore) { record(state.controlBefore); state.controlBefore = null; } }

function setupControls() {
  ["opacity", "border-width", "border-color", "zoom"].forEach((id) => $(id)?.addEventListener("pointerdown", beginControl));
  $("opacity")?.addEventListener("input", (event) => updatePhotoControl((element) => { element.opacity = Number(event.target.value); }));
  $("border-width")?.addEventListener("input", (event) => updatePhotoControl((element) => { element.style ||= {}; element.style.border ||= {}; element.style.border.width_mm = Number(event.target.value); }));
  $("border-color")?.addEventListener("input", (event) => updatePhotoControl((element) => { element.style ||= {}; element.style.border ||= {}; element.style.border.color = event.target.value; }));
  $("zoom")?.addEventListener("input", (event) => updatePhotoControl((element) => { element.transform ||= imageTransform(element); element.transform.zoom = Number(event.target.value); element.image = element.transform; }));
  ["opacity", "border-width", "border-color", "zoom"].forEach((id) => $(id)?.addEventListener("change", endControl));
  $("mask")?.addEventListener("change", (event) => { updatePhotoControl((element) => { element.clipping_shape = event.target.value; element.mask = { type: event.target.value }; }); endControl(); });
  $("rotate")?.addEventListener("click", () => { updatePhotoControl((element) => { element.transform ||= imageTransform(element); element.transform.rotation_deg = (Number(element.transform.rotation_deg || 0) + 90) % 360; element.image = element.transform; }); endControl(); });
  $("reset")?.addEventListener("click", () => { updatePhotoControl((element) => { element.transform = { zoom: 1, focus_x: 0.5, focus_y: 0.5, rotation_deg: 0 }; element.image = element.transform; }); endControl(); });
  $("raise")?.addEventListener("click", () => { updatePhotoControl((element) => { element.z_index = Number(element.z_index || 0) + 1; }); endControl(); });
  $("lower")?.addEventListener("click", () => { updatePhotoControl((element) => { element.z_index = Number(element.z_index || 0) - 1; }); endControl(); });
  $("delete")?.addEventListener("click", () => { const element = activeElement(); if (!element) return; const before = snapshot(); state.doc.elements = elements().filter((candidate) => elementId(candidate) !== elementId(element)); state.activeId = elements()[0] ? elementId(elements()[0]) : null; record(before); queueRender().then(() => status("Layer deleted. Save variant to keep the change.")); });
}

function setupCanvas() {
  state.canvas = new fabric.Canvas("canvas", { selection: false, preserveObjectStacking: true, enableRetinaScaling: true });
  state.canvas.on("selection:created", (event) => inspect(event.selected?.[0])); state.canvas.on("selection:updated", (event) => inspect(event.selected?.[0]));
  state.canvas.on("selection:cleared", () => { state.activeId = null; $("selection").textContent = "No element selected"; setInspectorState(false); refreshLayers(); });
  state.canvas.on("mouse:down", (event) => { if (event.target) { state.activeId = event.target._elementId; state.gestureBefore = snapshot(); } });
  state.canvas.on("object:moving", (event) => { if (state.mode === "crop" && event.target?._kind === "photo-image") { syncObject(event.target); state.canvas.requestRenderAll(); } });
  state.canvas.on("object:modified", (event) => { const before = state.gestureBefore || snapshot(); syncObject(event.target); record(before); state.gestureBefore = null; queueRender().then(() => status("Unsaved change")); });
  state.canvas.on("mouse:wheel", (event) => {
    if (state.mode !== "crop") return; const object = state.canvas.getActiveObject(); if (!object || object._kind !== "photo-image") return;
    event.e.preventDefault(); const element = elements().find((candidate) => elementId(candidate) === object._elementId); if (!element) return;
    if (!state.gestureBefore) state.gestureBefore = snapshot(); const transform = element.transform || (element.transform = imageTransform(element)); transform.zoom = clamp(Number(transform.zoom || 1) + (event.e.deltaY < 0 ? 0.05 : -0.05), 0.5, 10); element.image = transform; queueRender();
  });
  const upper = state.canvas.upperCanvasEl;
  upper?.addEventListener("dragover", (event) => event.preventDefault());
  upper?.addEventListener("drop", (event) => { event.preventDefault(); const id = event.dataTransfer.getData("text/plain"); if (id) replacePhoto(id); });
  setInspectorState(false);
}

function wire() {
  $("open")?.addEventListener("click", () => openDocument().catch((error) => status(error.message)));
  $("run")?.addEventListener("change", () => loadCandidates().catch((error) => status(error.message)));
  $("layout")?.addEventListener("click", () => setMode("layout")); $("crop")?.addEventListener("click", () => setMode("crop"));
  $("render-mode")?.addEventListener("change", (event) => setRenderMode(event.target.value).catch((error) => status(`Photo source change failed: ${error.message}`)));
  $("reload")?.addEventListener("click", () => openDocument().catch((error) => status(error.message)));
  $("fit")?.addEventListener("click", () => { fitPage(); state.canvas.requestRenderAll(); status("Page fitted to the available window."); });
  $("save")?.addEventListener("click", saveVariant); $("export")?.addEventListener("click", exportLayout); $("export-png")?.addEventListener("click", exportPng); $("export-hires")?.addEventListener("click", exportHighResPng);
  $("import-ai")?.addEventListener("click", () => $("import-ai-file")?.click()); $("import-debug")?.addEventListener("click", () => $("import-debug-file")?.click());
  $("import-ai-file")?.addEventListener("change", (event) => { const file = event.target.files?.[0]; if (!file) return; const reader = new FileReader(); reader.onload = () => { try { validateAiSpec(JSON.parse(String(reader.result || ""))); } catch (error) { status(`AI JSON is invalid: ${error.message}`); } }; reader.readAsText(file); event.target.value = ""; });
  $("import-debug-file")?.addEventListener("change", (event) => { if (event.target.files?.[0]) importDebugDocument(event.target.files[0]); event.target.value = ""; });
  $("apply-ai")?.addEventListener("click", applyAiDesign); $("load-sample")?.addEventListener("click", loadSample);
  $("undo")?.addEventListener("click", async () => { if (!state.history.length) return; state.future.push(snapshot()); state.doc = normalizeDocument(state.history.pop()); state.activeId = elements()[0] ? elementId(elements()[0]) : null; await loadPhotos(); await queueRender(); status("Undid the last operation."); });
  $("redo")?.addEventListener("click", async () => { if (!state.future.length) return; state.history.push(snapshot()); state.doc = normalizeDocument(state.future.pop()); state.activeId = elements()[0] ? elementId(elements()[0]) : null; await loadPhotos(); await queueRender(); status("Redid the last operation."); });
  setupControls(); setupCanvas();
}

async function populate() {
  const data = await api("/api/collage/runs"); const query = new URLSearchParams(location.search); state.runs = data.runs || [];
  $("run").innerHTML = state.runs.map((run) => `<option value="${esc(run.run_id)}">${esc(run.run_id.slice(0, 8))} · ${run.candidate_count} candidates</option>`).join("") || `<option value="">No saved runs</option>`;
  if (query.get("run")) $("run").value = query.get("run");
  if (query.get("document")) await openDocument(query.get("document"));
  else { await loadCandidates(); if (query.has("candidate")) await openDocument(); }
}

wire(); populate().catch((error) => status(`Unable to load collage data: ${error.message}`));
window.addEventListener("resize", () => { fitPage(); state.canvas?.requestRenderAll(); });
