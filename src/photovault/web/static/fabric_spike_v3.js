/*
 * The Fabric canvas is the only renderer.  CollageDocument v2 is the source of
 * truth; Fabric objects are a projection of it and are never reverse-scanned
 * wholesale during save.
 */
const $ = (id) => document.getElementById(id);
const clone = (value) => JSON.parse(JSON.stringify(value));
const PX_PER_MM = window.collageGeometry?.PX_PER_MM || 4;
const state = {
  runs: [], candidates: [], doc: null, savedDocumentUrl: null,
  photos: [], assetMap: new Map(), activeId: null, mode: "layout", renderMode: "funnel", renderFallbacks: [],
  history: [], future: [], canvas: null, gestureBefore: null,
  controlBefore: null, aiSpec: null, aiPackageId: null, renderPromise: Promise.resolve(),
  layerGroups: { Text: true, Photos: true, Supporting: false, Details: false, Decorations: true, Background: false },
  layerFilter: "all", layerSearch: "",
  lastExportReport: null,
  renderValidation: { validation_status: "valid", warnings: [], repairs: [] },
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
const photoId = (element) => (element && (element.type === "photo" || !element.type) ? (element.photo_id || element.asset_id || null) : null);
const isPhotoElement = (element) => Boolean(photoId(element));
const activeElement = () => elements().find((element) => elementId(element) === state.activeId) || null;
const canvasSize = (doc = state.doc) => ({ width: Number(doc?.canvas?.width || 1200), height: Number(doc?.canvas?.height || 800) });
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
const status = (message) => { if ($("status")) $("status").textContent = message; };
function pagePixelDimensions(doc, requestedDpi) {
  const page = doc?.page_spec || {};
  const rawWidthMm = Number(page.width_mm);
  const rawHeightMm = Number(page.height_mm);
  const widthMm = (Number.isFinite(rawWidthMm) && rawWidthMm > 0 ? rawWidthMm : 300) * (page.type === "spread" ? 2 : 1);
  const heightMm = Number.isFinite(rawHeightMm) && rawHeightMm > 0 ? rawHeightMm : 200;
  const numericDpi = Number(requestedDpi);
  const dpi = Math.round(clamp(Number.isFinite(numericDpi) ? numericDpi : 300, 72, 1200));
  return {
    dpi,
    widthMm,
    heightMm,
    width: Math.max(1, Math.round(widthMm / 25.4 * dpi)),
    height: Math.max(1, Math.round(heightMm / 25.4 * dpi)),
  };
}
function exportDpiValue(id, fallback) {
  const input = $(id);
  const numericDpi = Number(input?.value);
  return Math.round(clamp(Number.isFinite(numericDpi) ? numericDpi : fallback, 72, 1200));
}
function readExportDpi(id, fallback) {
  const input = $(id);
  const dpi = exportDpiValue(id, fallback);
  if (input) input.value = String(dpi);
  return dpi;
}
function updateExportDpiSummary() {
  const summary = $("export-dpi-summary");
  if (!summary || !state.doc) return;
  const pageDpi = pagePixelDimensions(state.doc, state.doc.page_spec?.dpi || 300).dpi;
  const previewDpi = exportDpiValue("preview-dpi", 150);
  const highResDpi = exportDpiValue("hires-dpi", pageDpi);
  const preview = pagePixelDimensions(state.doc, previewDpi);
  const highRes = pagePixelDimensions(state.doc, highResDpi);
  summary.textContent = `Page ${pageDpi} DPI · Preview ${preview.dpi} DPI (${preview.width} × ${preview.height}px) · High-res ${highRes.dpi} DPI (${highRes.width} × ${highRes.height}px)`;
  const previewButton = $("export-png");
  if (previewButton) previewButton.textContent = `Export preview PNG (${preview.dpi} DPI)`;
  const highResButton = $("export-hires");
  if (highResButton) highResButton.textContent = `Export high-res PNG (${highRes.dpi} DPI)`;
}
function syncExportDpiControls() {
  if (!state.doc) return;
  const documentKey = String(state.doc.document_id || state.savedDocumentUrl || "document");
  if (state.exportDpiDocumentKey !== documentKey) {
    const pageDpi = pagePixelDimensions(state.doc, state.doc.page_spec?.dpi || 300).dpi;
    if ($("preview-dpi")) $("preview-dpi").value = "150";
    if ($("hires-dpi")) $("hires-dpi").value = String(pageDpi);
    state.exportDpiDocumentKey = documentKey;
  }
  updateExportDpiSummary();
}
function updateDocumentChrome() {
  const creatorDocument = ["ai-design", "blank"].includes(String(state.doc?.provider || ""));
  ["photo-source-control", "render-mode-help", "run-control", "candidate-control", "open"].forEach((id) => {
    const node = $(id);
    if (node) node.hidden = creatorDocument;
  });
  const summary = $("ai-document-summary");
  if (summary) {
    summary.hidden = !creatorDocument;
    if (creatorDocument) {
      const metadata = state.doc?.metadata || {};
      const kind = state.doc?.provider === "blank" ? "Start blank" : "AI Design";
      const alternative = metadata.design_id ? `Alternative ${metadata.design_id}` : "Imported alternative";
      const name = metadata.design_name || (state.doc?.provider === "blank" ? "editable grid" : alternative);
      const packageLabel = metadata.package_id && !String(metadata.package_id).startsWith("fixture:") ? ` · ${String(metadata.package_id).slice(0, 16)}` : "";
      summary.textContent = `${kind} · ${name}${packageLabel} · ${elements().length} elements`;
    }
  }
  const reports = [state.doc?.metadata?.layout_validation, state.doc?.metadata?.render_validation].filter(Boolean);
  const reportNode = $("validation-report");
  if (reportNode) {
    const warnings = reports.flatMap((report) => Array.isArray(report.warnings) ? report.warnings : []);
    const repairs = reports.flatMap((report) => Array.isArray(report.repairs) ? report.repairs : []);
    const statuses = reports.map((report) => String(report.validation_status || "valid"));
    reportNode.hidden = !warnings.length && !repairs.length;
    reportNode.textContent = reportNode.hidden ? "" : `Validation: ${statuses.join(" + ")} · ${warnings.length} warning(s) · ${repairs.length} repair(s)`;
  }
  syncExportDpiControls();
}
const photoControls = ["border-width", "border-color", "mask", "zoom", "rotate", "reset"];
function setInspectorState(element) {
  const hasSelection = Boolean(element);
  const hasPhoto = isPhotoElement(element);
  const isText = element?.type === "text";
  photoControls.forEach((control) => { if ($(control)) $(control).disabled = !hasPhoto; });
  if ($("opacity")) $("opacity").disabled = !hasSelection;
  if ($("frame-rotation")) $("frame-rotation").disabled = !hasSelection;
  ["text-content", "font-role", "font-size", "text-fit"].forEach((control) => { if ($(control)) $(control).disabled = !isText; });
  ["toggle-lock", "toggle-hide", "raise", "lower", "delete"].forEach((control) => { if ($(control)) $(control).disabled = !hasSelection; });
  if ($("toggle-lock")) $("toggle-lock").textContent = element?.locked ? "Unlock layer" : "Lock layer";
  if ($("toggle-hide")) $("toggle-hide").textContent = element?.hidden ? "Show layer" : "Hide layer";
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
  const pageWidth = Number(documentValue.page_spec.width_mm || 300) * (documentValue.page_spec.type === "spread" ? 2 : 1);
  documentValue.canvas ||= {
    width: Math.round(pageWidth * PX_PER_MM),
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

function photoUrls(assetId, context = null) {
  const assetMap = context?.assetMap || state.assetMap;
  const renderMode = context?.renderMode || state.renderMode;
  const info = assetMap.get(String(assetId));
  const thumbnail = info?.thumbnail || `/api/thumb/${encodeURIComponent(assetId)}`;
  const original = info?.original_url || `/api/original/${encodeURIComponent(assetId)}`;
  return renderMode === "view" ? [original, thumbnail] : [thumbnail];
}

function photoUrl(assetId, context = null) { return photoUrls(assetId, context)[0]; }

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

// Catalog thumbnails are generated as plain JPEGs and therefore no longer
// carry the source file's EXIF orientation. Originals may still carry it and
// the browser applies it while decoding them. Normalize the thumbnail
// projection here; the original projection is already orientation-correct.
function exifRotation(orientation) {
  return ({ 3: 180, 6: 90, 8: 270 })[Number(orientation)] || 0;
}

function sourceRotation(element, context, usedOriginal) {
  if (usedOriginal) return 0;
  const info = (context?.assetMap || state.assetMap).get(String(photoId(element))) || {};
  return exifRotation(info.orientation);
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

function designAssetUrl(element) {
  return element?.asset_url || (element?.asset_id ? `/api/collage/design-assets/${encodeURIComponent(element.asset_id)}` : "");
}

const PT_TO_PX = (25.4 / 72) * PX_PER_MM;
const FONT_STACKS = Object.freeze({
  serif: 'Georgia, "Noto Serif CJK TC", "PingFang TC", serif',
  sans: 'Arial, "Noto Sans CJK TC", "PingFang TC", sans-serif',
  script: '"Brush Script MT", "Segoe Script", cursive',
  display: 'Impact, "Arial Black", sans-serif',
});

function createRenderContext(canvas, options = {}) {
  return {
    canvas,
    doc: options.doc || state.doc,
    assetMap: options.assetMap || state.assetMap,
    renderMode: options.renderMode || state.renderMode,
    mode: options.mode || state.mode,
    activeId: options.activeId ?? state.activeId,
    interactive: Boolean(options.interactive),
    strictAssets: Boolean(options.strictAssets),
    report: options.report || { validation_status: "valid", warnings: [], repairs: [], rendered_element_ids: [], failed_element_ids: [], fallbacks: [] },
  };
}

function renderWarning(element, code, message, details = {}, context = null) {
  (context?.report || state.renderValidation).warnings.push({ element_id: elementId(element), code, message, ...details });
}

function renderRepair(element, reason, details = {}, context = null) {
  (context?.report || state.renderValidation).repairs.push({ element_id: elementId(element), reason, ...details });
}

function actualTextMetrics(object) {
  object.initDimensions?.();
  const lineCount = Math.max(1, Array.isArray(object._textLines) ? object._textLines.length : 1);
  const widths = Array.from({ length: lineCount }, (_, index) => {
    try { return Number(object.getLineWidth?.(index) || 0); } catch (_) { return 0; }
  });
  return {
    width: Math.max(0, ...widths),
    height: Number(object.getScaledHeight?.() || object.height || 0),
  };
}

function setTextFontSize(object, sizePx) {
  object.set({ fontSize: sizePx, scaleX: 1, scaleY: 1 });
  object.initDimensions?.();
  object.setCoords?.();
}

function fitTextObject(object, element, context = null) {
  const style = element.text_style || {};
  const targetWidth = Math.max(1, Number(element.width || 1));
  const targetHeight = Math.max(1, Number(element.height || 1));
  const fit = String(style.text_fit || "shrink_to_fit");
  const originalSizePx = Number(object.fontSize || 12 * PT_TO_PX);
  const minSizePx = Math.max(4, Number(style.min_font_size_pt || 6)) * PT_TO_PX;
  let sizePx = originalSizePx;

  const measureUnwrapped = () => {
    object.set({ width: Math.max(targetWidth, 100000) });
    object.initDimensions?.();
    const measured = actualTextMetrics(object);
    object.set({ width: targetWidth });
    object.initDimensions?.();
    return measured;
  };

  if (fit === "shrink_to_fit") {
    for (let attempt = 0; attempt < 80; attempt += 1) {
      setTextFontSize(object, sizePx);
      const measured = measureUnwrapped();
      if (measured.width <= targetWidth + 0.01 && measured.height <= targetHeight + 0.01) break;
      const next = Math.max(minSizePx, sizePx * 0.94);
      if (Math.abs(next - sizePx) < 0.01) break;
      sizePx = next;
    }
  } else if (fit === "wrap_and_shrink") {
    object.set({ width: targetWidth });
    for (let attempt = 0; attempt < 80; attempt += 1) {
      object.initDimensions?.();
      const measured = actualTextMetrics(object);
      if (measured.width <= targetWidth + 0.01 && measured.height <= targetHeight + 0.01) break;
      const next = Math.max(minSizePx, sizePx * 0.94);
      if (Math.abs(next - sizePx) < 0.01) break;
      sizePx = next;
      setTextFontSize(object, sizePx);
    }
  }
  object.set({ width: targetWidth });
  object.initDimensions?.();
  object.setCoords?.();
  const finalMetrics = actualTextMetrics(object);
  const finalSizePt = Number(object.fontSize || originalSizePx) / PT_TO_PX;
  if (Math.abs(finalSizePt - Number(style.font_size_pt || finalSizePt)) > 0.01) {
    const before = Number(style.font_size_pt || finalSizePt);
    element.text_style ||= {};
    element.text_style.font_size_pt = Number(finalSizePt.toFixed(2));
    renderRepair(element, "FABRIC_TEXT_SHRINK_TO_FIT", { from_font_size_pt: before, to_font_size_pt: element.text_style.font_size_pt }, context);
  }
  if (finalMetrics.width > targetWidth + 0.5 || finalMetrics.height > targetHeight + 0.5) {
    renderWarning(element, "FABRIC_TEXT_OVERFLOW", "Text still exceeds its declared box after browser-metric fitting.", { width_px: finalMetrics.width, height_px: finalMetrics.height }, context);
  }
}

function fabricBounds(object, options = {}) {
  try {
    object.setCoords?.();
    const bounds = object.getBoundingRect({ absolute: true, includeStroke: Boolean(options.includeStroke), includeShadow: Boolean(options.includeShadow) });
    return { left: Number(bounds.left || 0), top: Number(bounds.top || 0), right: Number(bounds.left || 0) + Number(bounds.width || 0), bottom: Number(bounds.top || 0) + Number(bounds.height || 0) };
  } catch (_) {
    const width = Number(object.width || 0) * Number(object.scaleX || 1);
    const height = Number(object.height || 0) * Number(object.scaleY || 1);
    return { left: Number(object.left || 0), top: Number(object.top || 0), right: Number(object.left || 0) + width, bottom: Number(object.top || 0) + height };
  }
}

function renderedObjectsByElement(canvas) {
  const objects = new Map();
  canvas?.getObjects?.().forEach((object) => {
    const id = object?._elementId;
    if (!id) return;
    const bucket = objects.get(id) || [];
    bucket.push(object);
    objects.set(id, bucket);
  });
  return objects;
}

function keepTextInsideSafeArea(object, element, context = null) {
  if (element.allow_bleed) return;
  const doc = context?.doc || state.doc;
  const page = canvasSize(doc);
  const safe = Number(doc?.page_spec?.safe_margin_mm || 8) * PX_PER_MM;
  const before = fabricBounds(object);
  let dx = 0;
  let dy = 0;
  if (before.left < safe) dx = safe - before.left;
  if (before.right > page.width - safe) dx = (page.width - safe) - before.right;
  if (before.top < safe) dy = safe - before.top;
  if (before.bottom > page.height - safe) dy = (page.height - safe) - before.bottom;
  if (dx || dy) {
    object.set({ left: Number(object.left || 0) + dx, top: Number(object.top || 0) + dy });
    object.setCoords?.();
    const oldX = Number(element.x || 0), oldY = Number(element.y || 0);
    element.x = Math.round(Number(object.left || 0));
    element.y = Math.round(Number(object.top || 0));
    if (Number.isFinite(Number(element.x_mm))) element.x_mm = Number((element.x / PX_PER_MM).toFixed(2));
    if (Number.isFinite(Number(element.y_mm))) element.y_mm = Number((element.y / PX_PER_MM).toFixed(2));
    renderRepair(element, "FABRIC_TEXT_SAFE_AREA", { from_x: oldX, from_y: oldY, to_x: element.x, to_y: element.y }, context);
  }
  const after = fabricBounds(object);
  if (after.left < safe - 0.5 || after.top < safe - 0.5 || after.right > page.width - safe + 0.5 || after.bottom > page.height - safe + 0.5) {
    renderWarning(element, "FABRIC_TEXT_OUTSIDE_SAFE_AREA", "Text remains outside the safe margin after bounded repair.", {}, context);
  }
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

function frameObject(element, context = null) {
  const style = elementStyle(element);
  const width = Number(element.width || 0);
  const height = Number(element.height || 0);
  const rounded = shapeName(element) === "rounded";
  const activeId = context?.activeId ?? state.activeId;
  const interactive = Boolean(context?.interactive);
  const mode = context?.mode || state.mode;
  const object = new fabric.Rect({
    left: Number(element.x || 0) + width / 2,
    top: Number(element.y || 0) + height / 2,
    originX: "center", originY: "center", width, height,
    fill: "rgba(40,110,103,0.035)",
    stroke: interactive && elementId(element) === activeId ? "#286e67" : (style.border.color || "#d4cbc1"),
    strokeWidth: interactive && elementId(element) === activeId ? 2 : Math.max(style.border.width_mm * PX_PER_MM, 1),
    opacity: Number(element.opacity ?? 1),
    angle: Number(element.rotation_deg || 0),
    rx: rounded ? Math.min(width, height) * 0.12 : 0,
    ry: rounded ? Math.min(width, height) * 0.12 : 0,
    shadow: createShadow(style.shadow), objectCaching: false,
    visible: !element.hidden,
    selectable: interactive && !element.locked && !element.hidden && mode === "layout",
    evented: interactive && !element.locked && !element.hidden && mode === "layout",
  });
  object._elementId = elementId(element);
  object._kind = "photo-frame";
  return object;
}

function clipPath(element, imageScale, imageRotation = imageTransform(element).rotation) {
  const width = Number(element.width || 0) / Math.max(imageScale, 0.0001);
  const height = Number(element.height || 0) / Math.max(imageScale, 0.0001);
  const shape = shapeName(element);
  if (shape === "circle") {
    return new fabric.Circle({ left: 0, top: 0, originX: "center", originY: "center", radius: Math.min(width, height) / 2, angle: -imageRotation });
  }
  if (shape === "ellipse") {
    return new fabric.Ellipse({ left: 0, top: 0, originX: "center", originY: "center", rx: width / 2, ry: height / 2, angle: -imageRotation });
  }
  return new fabric.Rect({
    left: 0, top: 0, originX: "center", originY: "center", width, height,
    rx: shape === "rounded" ? Math.min(width, height) * 0.12 : 0,
    ry: shape === "rounded" ? Math.min(width, height) * 0.12 : 0,
    angle: -imageRotation,
  });
}

async function loadPhotoImage(element, context = null) {
  let image = null;
  let usedOriginal = false;
  let lastError = null;
  for (const [index, url] of photoUrls(photoId(element), context).entries()) {
    try {
      image = await fabric.Image.fromURL(url, { crossOrigin: "anonymous" });
      if (image) { usedOriginal = (context?.renderMode || state.renderMode) === "view" && index === 0; break; }
    } catch (error) { lastError = error; }
  }
  return { image, usedOriginal, sourceRotation: sourceRotation(element, context, usedOriginal), error: image ? null : lastError || new Error(`Photo asset ${photoId(element)} could not be loaded.`) };
}

async function addPhoto(element, loaded = null, context = null) {
  const ctx = context || createRenderContext(state.canvas);
  const id = elementId(element);
  const fallbackFrame = frameObject(element, ctx);
  ctx.canvas.add(fallbackFrame);
  const transform = imageTransform(element);
  const sourceInfo = ctx.assetMap.get(String(photoId(element))) || {};
  const source = { width: Number(sourceInfo.width || 1), height: Number(sourceInfo.height || 1) };
  const loadedResult = loaded || await loadPhotoImage(element, ctx);
  const { image, usedOriginal } = loadedResult;
  if (!image) {
    ctx.report.failed_element_ids.push(id);
    if (ctx.report) ctx.report.warnings.push({ element_id: id, code: "PHOTO_ASSET_LOAD_FAILED", message: loadedResult.error?.message || "Photo asset could not be loaded." });
    return { rendered: false, usedOriginal, error: loadedResult.error };
  }
  if (ctx.renderMode === "view" && !usedOriginal) {
    ctx.report.fallbacks.push(photoId(element));
    ctx.report.warnings.push({ element_id: id, code: "PHOTO_ORIGINAL_FALLBACK", message: "Original photo unavailable; thumbnail fallback was used." });
  }
  // The editor intentionally renders the catalog thumbnail.  Catalog metadata
  // may describe the original at a different resolution, so use the loaded
  // image's intrinsic dimensions for cover scaling while preserving its
  // aspect ratio for high-resolution export.
  const loadedSource = { width: Number(image.width || source.width), height: Number(image.height || source.height) };
  const imageRotation = Number(loadedResult.sourceRotation || 0) + transform.rotation;
  const quarterTurn = Math.abs(Math.round(imageRotation / 90)) % 2 === 1;
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
    angle: Number(element.rotation_deg || 0) + imageRotation,
    opacity: Number(element.opacity ?? 1), objectCaching: false,
    visible: !element.hidden, selectable: ctx.interactive && !element.locked && !element.hidden && ctx.mode === "crop",
    evented: ctx.interactive && !element.locked && !element.hidden && ctx.mode === "crop",
  });
  image.clipPath = clipPath(element, imageScale, imageRotation);
  image._elementId = id; image._kind = "photo-image"; image._baseScale = baseScale;
  image._visualWidth = visualWidth; image._visualHeight = visualHeight;
  ctx.canvas.remove(fallbackFrame);
  ctx.canvas.add(image);
  ctx.canvas.add(frameObject(element, ctx));
  return { rendered: true, usedOriginal, image };
}

async function loadDesignAsset(element) {
  const url = designAssetUrl(element);
  if (!url) return { object: null, error: new Error("Design asset has no safe URL.") };
  if (/\.svg(?:$|[?#])/i.test(url) && typeof fabric.loadSVGFromURL === "function") {
    try {
      const parsed = await fabric.loadSVGFromURL(url);
      const objects = (parsed?.objects || []).filter(Boolean);
      if (objects.length && typeof fabric.util?.groupSVGElements === "function") {
        const object = fabric.util.groupSVGElements(objects, parsed.options || {});
        const width = Number(object?.width || 0);
        const height = Number(object?.height || 0);
        if (width > 0 && height > 0 && Number.isFinite(width) && Number.isFinite(height)) return { object, source: "svg-group", sourceWidth: width, sourceHeight: height };
      }
      throw new Error("SVG has no non-empty rendered bounds.");
    } catch (error) {
      return { object: null, error };
    }
  }
  try {
    const object = await fabric.Image.fromURL(url, { crossOrigin: "anonymous" });
    const width = Number(object?.width || 0);
    const height = Number(object?.height || 0);
    if (!object || width <= 0 || height <= 0) throw new Error("Design asset has empty rendered bounds.");
    return { object, source: "image", sourceWidth: width, sourceHeight: height };
  } catch (error) {
    return { object: null, error };
  }
}

async function addDesignAsset(element, loaded = null, context = null) {
  const ctx = context || createRenderContext(state.canvas);
  const id = elementId(element);
  const width = Number(element.width || 0);
  const height = Number(element.height || 0);
  const fallback = new fabric.Rect({
    left: Number(element.x || 0) + width / 2, top: Number(element.y || 0) + height / 2,
    originX: "center", originY: "center", width, height, fill: "rgba(192,141,88,.12)",
    stroke: "#c08d58", strokeDashArray: [6, 4], angle: Number(element.rotation_deg || 0),
    visible: !element.hidden, selectable: ctx.interactive && !element.locked && !element.hidden && ctx.mode === "layout",
    evented: ctx.interactive && !element.locked && !element.hidden && ctx.mode === "layout", objectCaching: false,
  });
  fallback._elementId = id; fallback._kind = "design-asset";
  const loadedResult = loaded || await loadDesignAsset(element);
  const image = loadedResult.object;
  if (!image) {
    ctx.canvas.add(fallback);
    ctx.report.failed_element_ids.push(id);
    ctx.report.warnings.push({ element_id: id, code: "DESIGN_ASSET_LOAD_FAILED", message: loadedResult.error?.message || "Design asset could not be loaded." });
    return { rendered: false, error: loadedResult.error };
  }
  const sourceWidth = Math.max(Number(loadedResult.sourceWidth || image.width || 1), 1);
  const sourceHeight = Math.max(Number(loadedResult.sourceHeight || image.height || 1), 1);
  const scale = Math.min(width / sourceWidth, height / sourceHeight);
  image.set({
    left: Number(element.x || 0) + width / 2, top: Number(element.y || 0) + height / 2,
    originX: "center", originY: "center", scaleX: scale, scaleY: scale,
    angle: Number(element.rotation_deg || 0), opacity: Number(element.opacity ?? 1),
    visible: !element.hidden, selectable: ctx.interactive && !element.locked && !element.hidden && ctx.mode === "layout",
    evented: ctx.interactive && !element.locked && !element.hidden && ctx.mode === "layout", objectCaching: false,
  });
  image._elementId = id; image._kind = "design-asset"; image._sourceWidth = sourceWidth; image._sourceHeight = sourceHeight; image._frameWidth = width; image._frameHeight = height;
  ctx.canvas.add(image);
  return { rendered: true, source: loadedResult.source, object: image };
}

function textOptions(element, context = null) {
  const style = element.text_style || {};
  return {
    left: Number(element.x || 0), top: Number(element.y || 0), width: Number(element.width || 240),
    fontFamily: FONT_STACKS[style.font_id] || FONT_STACKS.serif, fontSize: Number(style.font_size_pt || 12) * PT_TO_PX,
    fontWeight: style.weight || "normal", fontStyle: style.italic ? "italic" : "normal",
    textAlign: style.alignment || "left", lineHeight: Number(style.line_height || 1.15),
    charSpacing: Number(style.letter_spacing || 0) * 10, fill: style.color || "#292521",
    angle: Number(element.rotation_deg || 0), opacity: Number(element.opacity ?? 1),
    editable: false, objectCaching: false, visible: !element.hidden,
    selectable: Boolean(context?.interactive) && !element.locked && !element.hidden && (context?.mode || state.mode) === "layout",
    evented: Boolean(context?.interactive) && !element.locked && !element.hidden && (context?.mode || state.mode) === "layout",
  };
}

function addDecoration(element, context = null) {
  const ctx = context || createRenderContext(state.canvas);
  const x = Number(element.x || 0), y = Number(element.y || 0), width = Number(element.width || 0), height = Number(element.height || 0);
  let object;
  const strokeWidth = Number(element.stroke_width || 0) * PX_PER_MM;
  if (element.type === "text") {
    object = new fabric.Textbox(String(element.content || ""), textOptions(element, ctx));
    fitTextObject(object, element, ctx);
    keepTextInsideSafeArea(object, element, ctx);
  } else if (element.type === "line") object = new fabric.Line([0, 0, width, height], { left: x, top: y, stroke: element.stroke || "#292521", strokeWidth, opacity: Number(element.opacity ?? 1), angle: Number(element.rotation_deg || 0), visible: !element.hidden, selectable: ctx.interactive && !element.locked && !element.hidden, evented: ctx.interactive && !element.locked && !element.hidden, objectCaching: false });
  else if (element.type === "ellipse") object = new fabric.Ellipse({ left: x + width / 2, top: y + height / 2, originX: "center", originY: "center", rx: width / 2, ry: height / 2, fill: element.fill || "transparent", stroke: element.stroke || "transparent", strokeWidth, opacity: Number(element.opacity ?? 1), angle: Number(element.rotation_deg || 0), visible: !element.hidden, selectable: ctx.interactive && !element.locked && !element.hidden, evented: ctx.interactive && !element.locked && !element.hidden, objectCaching: false });
  else if (element.type === "polygon") {
    const points = (element.points || []).map((point) => ({ x: Number(point.x || 0), y: Number(point.y || 0) }));
    object = new fabric.Polygon(points, { left: x, top: y, fill: element.fill || "transparent", stroke: element.stroke || "transparent", strokeWidth, opacity: Number(element.opacity ?? 1), angle: Number(element.rotation_deg || 0), visible: !element.hidden, selectable: ctx.interactive && !element.locked && !element.hidden, evented: ctx.interactive && !element.locked && !element.hidden, objectCaching: false });
  } else object = new fabric.Rect({ left: x + width / 2, top: y + height / 2, originX: "center", originY: "center", width, height, fill: element.fill || "transparent", stroke: element.stroke || "transparent", strokeWidth, opacity: Number(element.opacity ?? 1), angle: Number(element.rotation_deg || 0), visible: !element.hidden, selectable: ctx.interactive && !element.locked && !element.hidden, evented: ctx.interactive && !element.locked && !element.hidden, objectCaching: false });
  object._elementId = elementId(element); object._kind = element.type === "text" ? "text" : "decoration";
  ctx.canvas.add(object);
  return { rendered: true, object };
}

function layerCategory(element) {
  if (element.type === "text") return "Text";
  if (element.type === "photo") return "Photos";
  if (element.role === "background" || element.is_background) return "Background";
  return "Decorations";
}

function photoRole(element) {
  const role = String(element.role || "supporting").toLowerCase();
  if (role === "hero") return "Hero";
  if (role === "secondary") return "Secondary";
  if (role === "detail" || role === "details") return "Details";
  return "Supporting";
}

function layerLabel(element) {
  const info = state.assetMap.get(String(photoId(element))) || {};
  if (element.type === "text") return String(element.label || element.name || element.content || "Text").replace(/\s+/g, " ").trim().slice(0, 54) || "Text";
  if (element.type === "photo") {
    const prefix = element.asset_label || element.label || info.label || info.short_label || null;
    const filename = element.filename || info.filename || "Photo";
    return `${prefix ? `${prefix} · ` : ""}${filename}`.slice(0, 54);
  }
  return String(element.label || element.name || element.asset_label || (element.type === "design_asset" ? "Design asset" : element.type || "Shape")).replace(/\s+/g, " ").trim().slice(0, 54);
}

function layerIcon(element) {
  if (element.type === "photo") return "IMG";
  if (element.type === "text") return "T";
  if (element.type === "design_asset") return "SVG";
  return "SHAPE";
}

function layerMatches(element) {
  const category = layerCategory(element);
  const filter = state.layerFilter || "all";
  if (filter === "photo" && category !== "Photos") return false;
  if (filter === "text" && category !== "Text") return false;
  if (filter === "decoration" && !["Decorations", "Background"].includes(category)) return false;
  const query = String(state.layerSearch || "").trim().toLowerCase();
  return !query || `${layerLabel(element)} ${elementId(element)} ${element.type} ${element.role || ""}`.toLowerCase().includes(query);
}

function layerGroupOpen(key, defaultOpen = true) {
  if (!(key in state.layerGroups)) state.layerGroups[key] = defaultOpen;
  return Boolean(state.layerGroups[key]);
}

function expandLayerGroupFor(element) {
  const category = layerCategory(element);
  state.layerGroups[category] = true;
  if (category === "Photos") state.layerGroups[photoRole(element)] = true;
}

function selectLayer(id) {
  const element = elements().find((candidate) => elementId(candidate) === id);
  if (!element) return;
  expandLayerGroupFor(element);
  state.activeId = id;
  const object = state.canvas?.getObjects().find((item) => item._elementId === id && (state.mode === "crop" ? item._kind === "photo-image" : item._kind !== "photo-image"));
  if (object) state.canvas.setActiveObject(object);
  inspect(object || { _elementId: id });
}

function toggleLayerAction(id, action) {
  const element = elements().find((candidate) => elementId(candidate) === id);
  if (!element) return;
  const before = snapshot();
  if (action === "hide") element.hidden = !Boolean(element.hidden);
  if (action === "lock") element.locked = !Boolean(element.locked);
  record(before);
  queueRender().then(() => status(`${action === "hide" ? (element.hidden ? "Layer hidden." : "Layer shown.") : (element.locked ? "Layer locked." : "Layer unlocked.")}`));
}

function layerRow(element) {
  const id = elementId(element);
  return `<div class="layer-row ${id === state.activeId ? "active" : ""}" data-layer-id="${esc(id)}" title="${esc(`${layerLabel(element)} · ${id}`)}" role="button" tabindex="0"><button class="layer-icon" data-layer-action="hide" aria-label="${element.hidden ? "Show" : "Hide"} layer">${element.hidden ? "◌" : "●"}</button><button class="layer-icon" data-layer-action="lock" aria-label="${element.locked ? "Unlock" : "Lock"} layer">${element.locked ? "🔒" : "🔓"}</button><span class="layer-type">${esc(layerIcon(element))}</span><span class="layer-label">${esc(layerLabel(element))}</span></div>`;
}

function layerGroup(title, key, items, defaultOpen = true) {
  if (!items.length) return "";
  const open = layerGroupOpen(key, defaultOpen);
  return `<section class="layer-group" data-layer-group="${esc(key)}"><button class="layer-group-toggle" data-group-toggle="${esc(key)}"><span>${open ? "▾" : "▸"}</span>${esc(title)}<span class="layer-group-count">${items.length}</span></button><div class="layer-group-items"${open ? "" : " hidden"}>${items.map(layerRow).join("")}</div></section>`;
}

function refreshLayers() {
  const container = $("layers");
  if (!container) return;
  const filtered = [...elements()].filter(layerMatches).sort((a, b) => (Number(b.z_index || 0) - Number(a.z_index || 0)) || elementId(a).localeCompare(elementId(b)));
  if (!filtered.length) { container.innerHTML = `<span class="muted">No matching layers</span>`; return; }
  const groups = new Map([["Text", []], ["Photos", []], ["Decorations", []], ["Background", []]]);
  filtered.forEach((element) => groups.get(layerCategory(element))?.push(element));
  const photos = groups.get("Photos") || [];
  const photoGroups = ["Hero", "Secondary", "Supporting", "Details"].map((role) => [role, photos.filter((element) => photoRole(element) === role)]).filter(([, items]) => items.length);
  const photoMarkup = photos.length ? layerGroup("Photos", "Photos", photos, true).replace(photos.map(layerRow).join(""), photoGroups.map(([role, items]) => layerGroup(role, role, items, role === "Supporting" ? items.length <= 4 : role === "Details" ? false : true)).join("")) : "";
  container.innerHTML = [layerGroup("Text", "Text", groups.get("Text") || [], true), photoMarkup, layerGroup("Decorations", "Decorations", groups.get("Decorations") || [], true), layerGroup("Background", "Background", groups.get("Background") || [], false)].join("") || `<span class="muted">No layers</span>`;
  container.querySelectorAll("[data-group-toggle]").forEach((button) => {
    button.onclick = () => { const key = button.dataset.groupToggle; state.layerGroups[key] = !layerGroupOpen(key); refreshLayers(); };
  });
  container.querySelectorAll("[data-layer-id]").forEach((row) => {
    row.onclick = (event) => { if (event.target.closest("[data-layer-action]")) return; selectLayer(row.dataset.layerId); };
    row.onkeydown = (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectLayer(row.dataset.layerId); } };
    row.querySelectorAll("[data-layer-action]").forEach((button) => { button.onclick = (event) => { event.stopPropagation(); toggleLayerAction(row.dataset.layerId, button.dataset.layerAction); }; });
  });
}

function inspect(object) {
  const id = object?._elementId || state.activeId;
  state.activeId = id || null;
  const element = activeElement();
  if (!element) {
    if ($("selection")) $("selection").textContent = "No element selected";
    setInspectorState(null);
    refreshLayers(); return;
  }
  setInspectorState(element);
  $("selection").textContent = `${element.type} · ${elementId(element)}${photoId(element) ? ` · ${photoId(element)}` : ""}`;
  const style = elementStyle(element); const transform = imageTransform(element);
  if ($("opacity")) $("opacity").value = Number(element.opacity ?? 1);
  if ($("border-width")) $("border-width").value = style.border.width_mm;
  if ($("border-color")) $("border-color").value = /^#[0-9a-f]{6}$/i.test(style.border.color) ? style.border.color : "#ffffff";
  if ($("mask")) $("mask").value = shapeName(element);
  if ($("zoom")) $("zoom").value = transform.zoom;
  if ($("frame-rotation")) $("frame-rotation").value = clamp(Number(element.rotation_deg || 0), -180, 180);
  if ($("text-content")) $("text-content").value = element.type === "text" ? String(element.content || "") : "";
  if ($("font-role")) $("font-role").value = element.type === "text" ? String(element.text_style?.font_id || "serif") : "serif";
  if ($("font-size")) $("font-size").value = element.type === "text" ? clamp(Number(element.text_style?.font_size_pt || 12), 4, 300) : 12;
  if ($("text-fit")) $("text-fit").value = element.type === "text" ? String(element.text_style?.text_fit || "shrink_to_fit") : "shrink_to_fit";
  $("text-content-wrap")?.toggleAttribute("hidden", element.type !== "text");
  $("font-role-wrap")?.toggleAttribute("hidden", element.type !== "text");
  $("font-size-wrap")?.toggleAttribute("hidden", element.type !== "text");
  $("text-fit-wrap")?.toggleAttribute("hidden", element.type !== "text");
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
  } else if (object._kind === "text") {
    const width = Number(object.width || 0) * Number(object.scaleX || 1);
    const height = Number(object.height || 0) * Number(object.scaleY || 1);
    element.x = Math.round(Number(object.left || 0)); element.y = Math.round(Number(object.top || 0));
    element.width = Math.round(width); element.height = Math.round(height); element.rotation_deg = Number(object.angle || 0);
    object.set({ scaleX: 1, scaleY: 1 });
  } else if (object._kind === "design-asset") {
    const width = Number(object.width || 0) * Number(object.scaleX || 1);
    const height = Number(object.height || 0) * Number(object.scaleY || 1);
    element.x = Math.round(Number(object.left || 0) - width / 2); element.y = Math.round(Number(object.top || 0) - height / 2);
    element.width = Math.round(width); element.height = Math.round(height); element.rotation_deg = Number(object.angle || 0);
    object.set({ scaleX: 1, scaleY: 1 });
  } else {
    const width = Number(object.width || 0) * Number(object.scaleX || 1);
    const height = Number(object.height || 0) * Number(object.scaleY || 1);
    const centered = object.originX === "center" || object.originY === "center";
    element.x = Math.round(Number(object.left || 0) - (centered ? width / 2 : 0));
    element.y = Math.round(Number(object.top || 0) - (centered ? height / 2 : 0));
    element.width = Math.round(width); element.height = Math.round(height); element.rotation_deg = Number(object.angle || 0);
    object.set({ scaleX: 1, scaleY: 1 });
  }
}

function applyInteractivity() {
  state.canvas.getObjects().forEach((object) => {
    const element = elements().find((candidate) => elementId(candidate) === object._elementId);
    const enabled = Boolean(element && !element.locked && !element.hidden);
    object.selectable = enabled && (object._kind === "photo-image" ? state.mode === "crop" : state.mode === "layout");
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
  // Resize Fabric's own wrapper, not the outer grid item. Resizing the
  // parent canvas-wrap collapses the workspace column to the page width and
  // leaves a large blank gap beside the editor at normal desktop widths.
  const container = state.canvas.wrapperEl;
  if (container) {
    container.style.width = `${page.width * scale}px`;
    container.style.height = `${page.height * scale}px`;
    container.style.maxWidth = "100%";
  }
  const guides = $("guide-overlay");
  if (guides) {
    const pageSpec = state.doc?.page_spec || {};
    const safe = Number(pageSpec.safe_margin_mm || 8) * PX_PER_MM * scale;
    guides.style.width = `${page.width * scale}px`; guides.style.height = `${page.height * scale}px`;
    guides.style.left = "50%"; guides.style.top = "14px"; guides.style.right = "auto"; guides.style.bottom = "auto";
    guides.style.transform = "translateX(-50%)";
    guides.querySelector(".safe")?.style.setProperty("inset", `${safe}px`);
    guides.querySelector(".spine")?.toggleAttribute("hidden", pageSpec.type !== "spread");
  }
}

async function renderDocument(targetCanvas, doc, options = {}) {
  const context = createRenderContext(targetCanvas, { ...options, doc });
  const page = canvasSize(doc);
  targetCanvas.setZoom?.(1);
  targetCanvas.setDimensions({ width: page.width, height: page.height });
  targetCanvas.clear();
  targetCanvas.backgroundColor = doc.background || doc.page_spec?.background || "#f5f2ed";
  if (document.fonts?.ready) await document.fonts.ready;
  const ordered = [...(doc.elements || [])].sort((a, b) => (Number(a.z_index || 0) - Number(b.z_index || 0)) || elementId(a).localeCompare(elementId(b)));
  const visible = ordered.filter((element) => !element.hidden);
  const [photoEntries, designEntries] = await Promise.all([
    Promise.all(visible.filter((element) => element.type === "photo").map(async (element) => [elementId(element), await loadPhotoImage(element, context)])),
    Promise.all(visible.filter((element) => element.type === "design_asset").map(async (element) => [elementId(element), await loadDesignAsset(element)])),
  ]);
  const photoLoads = new Map(photoEntries);
  const designLoads = new Map(designEntries);
  for (const element of visible) {
    let result;
    if (element.type === "photo") result = await addPhoto(element, photoLoads.get(elementId(element)), context);
    else if (element.type === "design_asset") result = await addDesignAsset(element, designLoads.get(elementId(element)), context);
    else result = addDecoration(element, context);
    if (result?.rendered) context.report.rendered_element_ids.push(elementId(element));
  }
  // All asset loads and bounded text repairs are complete at this point. The
  // post-render pass deliberately measures the real Fabric objects, so browser
  // font metrics, wrapping, rotation, scale and frame geometry are authoritative
  // for the final composition report. It never moves objects or changes the
  // document; safe-area/font fitting remain the only bounded render repairs.
  targetCanvas.renderAll();
  if (window.collageRenderValidation) {
    window.collageRenderValidation.validateRenderedComposition({
      elements: visible,
      objectsByElement: renderedObjectsByElement(targetCanvas),
      getBounds: (object, boundsOptions) => fabricBounds(object, boundsOptions),
      report: context.report,
      pxPerMm: PX_PER_MM,
      textPhotoClearanceMm: 2,
    });
  }
  context.report.failed_element_ids = [...new Set(context.report.failed_element_ids)];
  context.report.validation_status = context.report.failed_element_ids.length ? "failed" : (context.report.warnings.length ? "warnings" : (context.report.repairs.length ? "repaired" : "valid"));
  if (context.strictAssets && context.report.failed_element_ids.length) {
    throw new Error(`Required asset layer(s) failed to render: ${context.report.failed_element_ids.join(", ")}`);
  }
  return context.report;
}

async function renderNow() {
  if (!state.doc || !state.canvas) return;
  const activeBeforeClear = state.activeId;
  state.activeId = activeBeforeClear;
  state.renderValidation = { validation_status: "valid", warnings: [], repairs: [], rendered_element_ids: [], failed_element_ids: [], fallbacks: [] };
  const renderReport = await renderDocument(state.canvas, state.doc, {
    assetMap: state.assetMap, renderMode: state.renderMode, mode: state.mode,
    activeId: activeBeforeClear, interactive: true, report: state.renderValidation,
  });
  // Fabric emits `selection:cleared` while the shared renderer rebuilds the
  // canvas.  That event is correct for a user clearing selection, but it must
  // not erase the document-level selection that triggered a control update.
  // Restore the stable element id before projecting the selection back onto
  // the newly-created Fabric objects.
  state.activeId = activeBeforeClear;
  state.renderFallbacks = renderReport.fallbacks;
  applyInteractivity(); fitPage(); state.canvas.renderAll(); refreshLayers(); updatePhotoUsageIndicators();
  state.doc.metadata ||= {};
  state.doc.metadata.render_validation = clone(renderReport);
  updateDocumentChrome();
  $("identity").textContent = `${state.doc.provider || "document"} · ${elements().length} elements · ${state.canvas.getObjects().length} layers`;
  if (state.activeId) {
    const desired = state.canvas.getObjects().find((object) => object._elementId === state.activeId && (state.mode === "crop" ? object._kind === "photo-image" : object._kind !== "photo-image"));
    if (desired) state.canvas.setActiveObject(desired);
    inspect(desired || { _elementId: state.activeId });
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

function documentPhotoIds() {
  return elements().map(photoId).filter(Boolean).map((id) => String(id));
}

// AI packages can contain more selected photos than the chosen alternative
// uses. Keep that manifest visible in the replacement tray so the user can
// see exactly what was omitted and still use an omitted photo later.
function selectedPhotoIds() {
  const ids = [];
  const seen = new Set();
  const add = (value) => {
    const id = String(value || "");
    if (id && !seen.has(id)) { seen.add(id); ids.push(id); }
  };
  documentPhotoIds().forEach(add);
  (state.doc?.metadata?.selection_asset_ids || []).forEach(add);
  (state.aiSpec?.assets || []).forEach((asset) => add(asset?.asset_id));
  return ids;
}

function updatePhotoUsageIndicators() {
  const container = $("photos");
  if (!container) return;
  const usedIds = new Set(documentPhotoIds());
  let usedCount = 0;
  let unusedCount = 0;
  container.querySelectorAll(".photo[data-id]").forEach((node) => {
    const used = usedIds.has(String(node.dataset.id));
    node.classList.toggle("used", used);
    node.classList.toggle("unused", !used);
    const badge = node.querySelector(".photo-usage");
    if (badge) badge.textContent = used ? "✓ Used in collage" : "○ Selected · not used";
    node.title = used ? "Used in the current collage" : "Selected in the package but not used in the current collage; drag or double-click to replace a frame";
    node.setAttribute("aria-label", used ? "Used in collage" : "Selected but not used in current collage");
    if (used) usedCount += 1; else unusedCount += 1;
  });
  const summary = $("photo-usage-summary");
  if (summary) summary.textContent = selectedPhotoIds().length ? ` · ${usedCount} used · ${unusedCount} not used` : "";
}

function renderPhotosPanel() {
  const container = $("photos");
  if (!container) return;
  if (!state.photos.length) {
    container.innerHTML = `<span class="muted">No photo assets in this document.</span>`;
    updatePhotoUsageIndicators();
    return;
  }
  const usedIds = new Set(documentPhotoIds());
  container.innerHTML = state.photos.map((item) => {
    const id = String(item.asset_id);
    const used = usedIds.has(id);
    return `<div class="photo ${used ? "used" : "unused"}" draggable="true" data-id="${esc(id)}" title="${used ? "Used in the current collage" : "Selected in the package but not used in the current collage; drag or double-click to replace a frame"}" aria-label="${used ? "Used in collage" : "Selected but not used in current collage"}"><img loading="lazy" src="${item.thumbnail || photoUrl(id)}" alt="${esc(item.filename)}"><small>${esc(item.filename)}</small><span class="photo-usage">${used ? "✓ Used in collage" : "○ Selected · not used"}</span></div>`;
  }).join("");
  container.querySelectorAll(".photo").forEach((node) => {
    node.ondragstart = (event) => event.dataTransfer.setData("text/plain", node.dataset.id);
    node.ondblclick = () => replacePhoto(node.dataset.id);
  });
  updatePhotoUsageIndicators();
}

async function loadPhotos() {
  const ids = selectedPhotoIds();
  if (!ids.length) { state.photos = []; state.assetMap = new Map(); renderPhotosPanel(); return; }
  const data = await api(`/api/collage/photos?${ids.map((id) => `asset_id=${encodeURIComponent(id)}`).join("&")}`);
  const order = new Map(ids.map((id, index) => [id, index]));
  state.photos = (data.items || []).sort((a, b) => (order.get(String(a.asset_id)) ?? Number.MAX_SAFE_INTEGER) - (order.get(String(b.asset_id)) ?? Number.MAX_SAFE_INTEGER));
  state.assetMap = new Map(state.photos.map((item) => [String(item.asset_id), item]));
  renderPhotosPanel();
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
  // Keep the resolved document endpoint so Reload saved works for documents
  // opened directly from an AI-design URL as well as run candidates.
  state.savedDocumentUrl = documentUrl;
  state.doc = normalizeDocument(await api(documentUrl)); state.history = []; state.future = []; state.activeId = elements()[0] ? elementId(elements()[0]) : null;
  await loadPhotos(); await queueRender(); updateDocumentChrome(); status("Document loaded. Fabric canvas ready.");
}

function downloadBlob(name, blob) {
  const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

// Browser copies are intentionally local-only drafts. They store the editable
// document and stable asset IDs, never image bytes, so the feature is useful
// for quick iteration without silently publishing or uploading anything.
const BROWSER_SAVES_KEY = "photovault.collage.browser-saves.v1";
const MAX_BROWSER_SAVES = 30;
const MAX_BROWSER_DOCUMENT_BYTES = 2_000_000;

function browserSaveId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `browser-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function readBrowserSaves() {
  try {
    const parsed = JSON.parse(localStorage.getItem(BROWSER_SAVES_KEY) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((entry) => entry && typeof entry.id === "string" && typeof entry.name === "string" && entry.document && typeof entry.document === "object");
  } catch (_) {
    return [];
  }
}

function writeBrowserSaves(saves) {
  try {
    localStorage.setItem(BROWSER_SAVES_KEY, JSON.stringify(saves.slice(0, MAX_BROWSER_SAVES)));
    return true;
  } catch (_) {
    status("Browser memory is unavailable or full. Use Export file (JSON) instead.");
    return false;
  }
}

function formatBrowserSaveDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "saved date unavailable" : date.toLocaleString();
}

function renderBrowserSaveList() {
  const saves = readBrowserSaves();
  const select = $("browser-save-select");
  if (select) {
    select.replaceChildren();
    saves.forEach((entry) => {
      const option = document.createElement("option");
      option.value = entry.id;
      option.textContent = `${entry.name} · ${formatBrowserSaveDate(entry.saved_at)}`;
      select.appendChild(option);
    });
    select.disabled = !saves.length;
  }
  const memoryStatus = $("browser-memory-status");
  if (memoryStatus) memoryStatus.textContent = saves.length ? `${saves.length} browser ${saves.length === 1 ? "copy" : "copies"}` : "No browser copies";
  const loadButton = $("confirm-browser-load");
  if (loadButton) loadButton.disabled = !saves.length;
  return saves;
}

function openBrowserSaveDialog() {
  if (!state.doc) { status("Open a document first."); return; }
  const dialog = $("save-browser-dialog");
  const field = $("browser-save-name");
  if (!dialog || !field) { status("Browser save controls are unavailable."); return; }
  const defaultName = state.doc.metadata?.design_name || state.doc.document_id || "Untitled collage";
  field.value = defaultName;
  dialog.showModal();
  field.focus(); field.select();
}

function saveBrowserCopy() {
  if (!state.doc) { status("Open a document first."); return; }
  const name = String($("browser-save-name")?.value || "").trim();
  if (!name) { status("Give this browser copy a name first."); $("browser-save-name")?.focus(); return; }
  if (name.length > 80) { status("Browser copy names must be 80 characters or fewer."); return; }
  const documentValue = snapshot();
  const documentBytes = JSON.stringify(documentValue).length;
  if (documentBytes > MAX_BROWSER_DOCUMENT_BYTES) { status("This document is too large for browser memory. Use Export file (JSON) instead."); return; }
  const saves = readBrowserSaves();
  const existing = saves.find((entry) => entry.name === name);
  const entry = { id: existing?.id || browserSaveId(), name, saved_at: new Date().toISOString(), document: documentValue };
  const next = existing ? saves.map((item) => item.id === existing.id ? entry : item) : [entry, ...saves];
  if (!writeBrowserSaves(next)) return;
  renderBrowserSaveList();
  $("save-browser-dialog")?.close();
  status(`${existing ? "Updated" : "Saved"} browser copy “${name}”. Use Load browser copy to restore it later.`);
}

async function loadBrowserCopy() {
  const selectedId = $("browser-save-select")?.value;
  const entry = readBrowserSaves().find((item) => item.id === selectedId);
  if (!entry) { status("Choose a browser copy first."); return; }
  try {
    state.doc = normalizeDocument(clone(entry.document));
    // A browser copy must never make Reload saved overwrite it with the old
    // server revision. Save variant is an explicit publish action.
    state.savedDocumentUrl = null;
    state.history = []; state.future = []; state.controlBefore = null;
    state.activeId = elements()[0] ? elementId(elements()[0]) : null;
    await loadPhotos(); await queueRender(); updateDocumentChrome();
    $("load-browser-dialog")?.close();
    status(`Loaded browser copy “${entry.name}”. Use Save variant to publish this draft.`);
  } catch (error) {
    status(`Browser copy failed to load: ${error.message}`);
  }
}

function openBrowserLoadDialog() {
  const saves = renderBrowserSaveList();
  if (!saves.length) { status("No browser copies yet. Save a named copy first."); return; }
  $("load-browser-dialog")?.showModal();
}

function exportLayout() {
  if (!state.doc) { status("Open a document first."); return; }
  const assets = [...new Set(elements().map(photoId).filter(Boolean))].map((id) => {
    const info = state.assetMap.get(String(id)) || {}; return { asset_id: id, filename: info.filename || null, source_id: info.source_id || null, width: info.width || null, height: info.height || null };
  });
  const designAssets = elements().filter((element) => element.type === "design_asset").map((element) => ({ element_id: elementId(element), asset_id: element.asset_id || element.package_asset_id || null, asset_url: designAssetUrl(element) }));
  downloadBlob(`photomanager-collage-${state.doc.document_id || "layout"}.json`, new Blob([JSON.stringify({ format: "PhotoManager Collage Layout", schema_version: 2, exported_at: new Date().toISOString(), document: state.doc, assets, design_assets: designAssets }, null, 2)], { type: "application/json" }));
  status(`Exported layout file with ${assets.length} assets and ${elements().length} elements.`);
}

function createExportCanvas() {
  const node = document.createElement("canvas");
  node.setAttribute("aria-hidden", "true");
  node.style.position = "fixed";
  node.style.left = "-100000px";
  node.style.top = "-100000px";
  document.body.appendChild(node);
  const CanvasClass = fabric.StaticCanvas || fabric.Canvas;
  return new CanvasClass(node, { enableRetinaScaling: false, renderOnAddRemove: false, selection: false, preserveObjectStacking: true });
}

function pngCrc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function writeUint32(bytes, offset, value) {
  bytes[offset] = (value >>> 24) & 0xff;
  bytes[offset + 1] = (value >>> 16) & 0xff;
  bytes[offset + 2] = (value >>> 8) & 0xff;
  bytes[offset + 3] = value & 0xff;
}

function pngResolutionChunk(dpi) {
  const pixelsPerMeter = Math.max(1, Math.round(Number(dpi) / 0.0254));
  const type = new Uint8Array([112, 72, 89, 115]); // pHYs
  const data = new Uint8Array(9);
  writeUint32(data, 0, pixelsPerMeter); writeUint32(data, 4, pixelsPerMeter); data[8] = 1;
  const crcInput = new Uint8Array(type.length + data.length);
  crcInput.set(type); crcInput.set(data, type.length);
  const chunk = new Uint8Array(4 + crcInput.length + 4);
  writeUint32(chunk, 0, data.length); chunk.set(crcInput, 4); writeUint32(chunk, 4 + crcInput.length, pngCrc32(crcInput));
  return chunk;
}

function bytesToBase64(bytes) {
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) binary += String.fromCharCode(...bytes.subarray(offset, Math.min(offset + chunkSize, bytes.length)));
  return btoa(binary);
}

function withPngDpiMetadata(dataUrl, dpi) {
  if (!String(dataUrl).startsWith("data:image/png;base64,")) return dataUrl;
  try {
    const encoded = String(dataUrl).slice("data:image/png;base64,".length);
    const binary = atob(encoded);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    if (bytes.length < 33 || bytes[0] !== 137 || bytes[1] !== 80 || bytes[2] !== 78 || bytes[3] !== 71) return dataUrl;

    const resolution = pngResolutionChunk(dpi);
    let cursor = 8;
    let ihdrEnd = 0;
    let existingStart = -1;
    let existingEnd = -1;
    while (cursor + 12 <= bytes.length) {
      const length = ((bytes[cursor] << 24) >>> 0) | (bytes[cursor + 1] << 16) | (bytes[cursor + 2] << 8) | bytes[cursor + 3];
      const end = cursor + 12 + length;
      if (end > bytes.length) return dataUrl;
      const type = String.fromCharCode(bytes[cursor + 4], bytes[cursor + 5], bytes[cursor + 6], bytes[cursor + 7]);
      if (type === "IHDR") ihdrEnd = end;
      if (type === "pHYs" && existingStart < 0) { existingStart = cursor; existingEnd = end; }
      cursor = end;
      if (type === "IEND") break;
    }
    if (!ihdrEnd) return dataUrl;
    const before = bytes.subarray(0, existingStart >= 0 ? existingStart : ihdrEnd);
    const after = bytes.subarray(existingStart >= 0 ? existingEnd : ihdrEnd);
    const output = new Uint8Array(before.length + resolution.length + after.length);
    output.set(before); output.set(resolution, before.length); output.set(after, before.length + resolution.length);
    return `data:image/png;base64,${bytesToBase64(output)}`;
  } catch (_) {
    // Keep the export usable in browsers that do not expose atob/btoa.
    return dataUrl;
  }
}

async function exportRenderedPng({ renderMode, multiplier, filename, label, dpi }) {
  const exportDoc = normalizeDocument(clone(state.doc));
  const report = { validation_status: "valid", warnings: [], repairs: [], rendered_element_ids: [], failed_element_ids: [], fallbacks: [] };
  const exportCanvas = createExportCanvas();
  try {
    status(label);
    await renderDocument(exportCanvas, exportDoc, {
      assetMap: state.assetMap, renderMode, mode: "layout", activeId: null,
      interactive: false, strictAssets: true, report,
    });
    report.output_dpi = dpi || null;
    state.lastExportReport = clone(report);
    if (renderMode === "view" && report.fallbacks.length) {
      throw new Error(`${report.fallbacks.length} original photo(s) are offline; high-resolution export was not created.`);
    }
    const dataUrl = exportCanvas.toDataURL({ format: "png", multiplier, enableRetinaScaling: false });
    const outputDataUrl = dpi ? withPngDpiMetadata(dataUrl, dpi) : dataUrl;
    const link = document.createElement("a"); link.href = outputDataUrl; link.download = filename; link.click();
    return report;
  } finally {
    await exportCanvas.dispose?.();
    exportCanvas.lowerCanvasEl?.remove?.();
    exportCanvas.wrapperEl?.remove?.();
  }
}

async function exportPng() {
  if (!state.doc) { status("Open a document first."); return; }
  try {
    const dpi = readExportDpi("preview-dpi", 150);
    const pixels = pagePixelDimensions(state.doc, dpi);
    const logical = canvasSize(state.doc);
    const report = await exportRenderedPng({
      renderMode: state.renderMode, multiplier: pixels.width / Math.max(logical.width, 1),
      filename: `photomanager-collage-preview-${state.doc.document_id || "layout"}-${pixels.width}x${pixels.height}px-${pixels.dpi}dpi.png`,
      label: `Rendering ${pixels.dpi} DPI preview PNG…`, dpi: pixels.dpi,
    });
    status(`Exported ${pixels.dpi} DPI preview PNG · ${pixels.width} × ${pixels.height}px · ${report.rendered_element_ids.length} elements rendered.`);
  } catch (error) { status(`PNG export failed: ${error.message}`); }
}

async function exportHighResPng() {
  if (!state.doc) { status("Open a document first."); return; }
  try {
    const pageDpi = state.doc.page_spec?.dpi || 300;
    const pixels = pagePixelDimensions(state.doc, readExportDpi("hires-dpi", pageDpi));
    const logical = canvasSize(state.doc);
    const report = await exportRenderedPng({
      renderMode: "view", multiplier: pixels.width / Math.max(logical.width, 1),
      filename: `photomanager-collage-${state.doc.document_id || "layout"}-${pixels.width}x${pixels.height}px-${pixels.dpi}dpi.png`,
      label: `Loading original photos for ${pixels.dpi} DPI high-resolution export…`, dpi: pixels.dpi,
    });
    status(`Exported ${pixels.dpi} DPI high-resolution PNG ${pixels.width} × ${pixels.height}px from original photos · ${report.rendered_element_ids.length} elements rendered.`);
  } catch (error) { status(`High-resolution export failed: ${error.message}`); }
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

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("The package file could not be read."));
    reader.onload = () => {
      const value = String(reader.result || "");
      const comma = value.indexOf(",");
      resolve(comma >= 0 ? value.slice(comma + 1) : value);
    };
    reader.readAsDataURL(file);
  });
}

async function importDesignPackage(file) {
  status("Uploading and validating AI Design Package…");
  const packageZipBase64 = await readFileAsBase64(file);
  const result = await api("/api/collage/design-import-packages", {
    method: "POST",
    body: JSON.stringify({ package_zip_base64: packageZipBase64 }),
  });
  state.aiSpec = result.spec;
  state.aiPackageId = result.package_id;
  const alternatives = result.alternatives || [];
  const selector = $("alternative");
  if (!selector || !alternatives.length) throw new Error("The package contains no AI alternatives.");
  selector.innerHTML = alternatives.map((item) => `<option value="${Number(item.alternative)}">Alternative ${Number(item.alternative) + 1} · ${Number(item.photos)} photos · ${Number(item.elements)} elements</option>`).join("");
  $("alternative-picker").hidden = false;
  $("apply-ai").disabled = false;
  const report = result.validation || {};
  status(`Package validated: ${alternatives.length} alternative${alternatives.length === 1 ? "" : "s"}, ${Number(report.warnings?.length || 0)} warning(s), ${Number(report.repairs?.length || 0)} bounded repair(s). Choose one to open.`);
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
  try {
    const response = await fetch("/examples/kew-gardens-ai-design-v2.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const sample = await response.json();
    const currentAssets = [...new Set(elements().map(photoId).filter(Boolean))];
    if (currentAssets.length < 12) throw new Error("Open a candidate with at least 12 photo assets before loading the sample.");
    sample.assets = (sample.assets || []).map((asset, index) => {
      const assetId = currentAssets[index];
      const info = state.assetMap.get(String(assetId)) || {};
      return { ...asset, asset_id: assetId, filename: info.filename || `selected-image-${String(index + 1).padStart(2, "0")}.jpg` };
    });
    await validateAiSpec(sample);
  } catch (error) { status(`Sample design unavailable: ${error.message}`); }
}

function replacePhoto(assetId) {
  const element = activeElement();
  if (!element || element.type !== "photo") { status("Select a photo frame first, then replace it in Crop mode."); return; }
  if (!state.assetMap.has(String(assetId))) { status("That photo is not in this design package."); return; }
  const before = snapshot(); element.photo_id = assetId; element.asset_id = assetId; record(before); queueRender().then(() => status("Photo replaced in the selected frame."));
}

function beginControl() { if (!state.controlBefore && state.doc) state.controlBefore = snapshot(); }
function updateSelectedControl(mutator, message = "Unsaved change") {
  const element = activeElement();
  if (!element) { status("Select a layer first."); return false; }
  beginControl(); mutator(element); queueRender().then(() => status(message));
  return true;
}
function updatePhotoControl(mutator) {
  const element = activeElement();
  if (!element || element.type !== "photo") { status("Select a photo frame first."); return false; }
  return updateSelectedControl(mutator);
}
function endControl() { if (state.controlBefore) { record(state.controlBefore); state.controlBefore = null; } }

function setupControls() {
  ["opacity", "frame-rotation", "border-width", "border-color", "zoom", "font-size"].forEach((id) => {
    $(id)?.addEventListener("pointerdown", beginControl);
    $(id)?.addEventListener("change", endControl);
    $(id)?.addEventListener("blur", endControl);
  });
  $("opacity")?.addEventListener("input", (event) => updateSelectedControl((element) => { element.opacity = Number(event.target.value); }));
  $("frame-rotation")?.addEventListener("input", (event) => updateSelectedControl((element) => { element.rotation_deg = Number(event.target.value); }));
  $("border-width")?.addEventListener("input", (event) => updatePhotoControl((element) => { element.style ||= {}; element.style.border ||= {}; element.style.border.width_mm = Number(event.target.value); }));
  $("border-color")?.addEventListener("input", (event) => updatePhotoControl((element) => { element.style ||= {}; element.style.border ||= {}; element.style.border.color = event.target.value; }));
  $("zoom")?.addEventListener("input", (event) => updatePhotoControl((element) => { element.transform ||= imageTransform(element); element.transform.zoom = Number(event.target.value); element.image = element.transform; }));
  $("mask")?.addEventListener("change", (event) => { updatePhotoControl((element) => { element.clipping_shape = event.target.value; element.mask = { type: event.target.value }; }); endControl(); });
  $("rotate")?.addEventListener("click", () => { if (updatePhotoControl((element) => { element.transform ||= imageTransform(element); element.transform.rotation_deg = (Number(element.transform.rotation_deg || 0) + 90) % 360; element.image = element.transform; })) endControl(); });
  $("reset")?.addEventListener("click", () => { if (updatePhotoControl((element) => { element.transform = { zoom: 1, focus_x: 0.5, focus_y: 0.5, rotation_deg: 0 }; element.image = element.transform; })) endControl(); });
  $("raise")?.addEventListener("click", () => { if (updateSelectedControl((element) => { element.z_index = Number(element.z_index || 0) + 1; })) endControl(); });
  $("lower")?.addEventListener("click", () => { if (updateSelectedControl((element) => { element.z_index = Number(element.z_index || 0) - 1; })) endControl(); });
  $("text-content")?.addEventListener("input", (event) => updateSelectedControl((element) => { if (element.type === "text") element.content = event.target.value; }));
  $("text-content")?.addEventListener("change", endControl);
  $("font-role")?.addEventListener("change", (event) => { if (updateSelectedControl((element) => { if (element.type === "text") { element.text_style ||= {}; element.text_style.font_id = event.target.value; } })) endControl(); });
  $("font-size")?.addEventListener("change", (event) => { if (updateSelectedControl((element) => { if (element.type === "text") { element.text_style ||= {}; element.text_style.font_size_pt = clamp(Number(event.target.value) || 12, 4, 300); } })) endControl(); });
  $("text-fit")?.addEventListener("change", (event) => { if (updateSelectedControl((element) => { if (element.type === "text") { element.text_style ||= {}; element.text_style.text_fit = event.target.value; } })) endControl(); });
  $("toggle-lock")?.addEventListener("click", () => { if (updateSelectedControl((element) => { element.locked = !Boolean(element.locked); })) endControl(); });
  $("toggle-hide")?.addEventListener("click", () => { if (updateSelectedControl((element) => { element.hidden = !Boolean(element.hidden); })) endControl(); });
  $("delete")?.addEventListener("click", () => { const element = activeElement(); if (!element) return; const before = snapshot(); state.doc.elements = elements().filter((candidate) => elementId(candidate) !== elementId(element)); state.activeId = elements()[0] ? elementId(elements()[0]) : null; record(before); queueRender().then(() => status("Layer deleted. Save variant to keep the change.")); });
}

function setupCanvas() {
  state.canvas = new fabric.Canvas("canvas", { selection: false, preserveObjectStacking: true, enableRetinaScaling: true });
  state.canvas.on("selection:created", (event) => inspect(event.selected?.[0])); state.canvas.on("selection:updated", (event) => inspect(event.selected?.[0]));
  state.canvas.on("selection:cleared", () => { state.activeId = null; $("selection").textContent = "No element selected"; setInspectorState(null); refreshLayers(); });
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
  setInspectorState(null);
}

function wire() {
  $("open")?.addEventListener("click", () => openDocument().catch((error) => status(error.message)));
  $("run")?.addEventListener("change", () => loadCandidates().catch((error) => status(error.message)));
  $("layout")?.addEventListener("click", () => setMode("layout")); $("crop")?.addEventListener("click", () => setMode("crop"));
  $("render-mode")?.addEventListener("change", (event) => setRenderMode(event.target.value).catch((error) => status(`Photo source change failed: ${error.message}`)));
  $("reload")?.addEventListener("click", () => openDocument().catch((error) => status(error.message)));
  $("fit")?.addEventListener("click", () => { fitPage(); state.canvas.requestRenderAll(); status("Page fitted to the available window."); });
  $("save")?.addEventListener("click", saveVariant); $("save-browser")?.addEventListener("click", openBrowserSaveDialog); $("load-browser")?.addEventListener("click", openBrowserLoadDialog);
  $("confirm-browser-save")?.addEventListener("click", saveBrowserCopy); $("cancel-browser-save")?.addEventListener("click", () => $("save-browser-dialog")?.close());
  $("confirm-browser-load")?.addEventListener("click", () => loadBrowserCopy().catch((error) => status(`Browser copy failed: ${error.message}`))); $("cancel-browser-load")?.addEventListener("click", () => $("load-browser-dialog")?.close());
  $("browser-save-name")?.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); saveBrowserCopy(); } });
  $("export")?.addEventListener("click", exportLayout); $("export-png")?.addEventListener("click", exportPng); $("export-hires")?.addEventListener("click", exportHighResPng);
  ["preview-dpi", "hires-dpi"].forEach((id) => {
    $(id)?.addEventListener("input", updateExportDpiSummary);
    $(id)?.addEventListener("change", () => {
      readExportDpi(id, id === "preview-dpi" ? 150 : pagePixelDimensions(state.doc, state.doc?.page_spec?.dpi || 300).dpi);
      updateExportDpiSummary();
    });
  });
  $("show-guides")?.addEventListener("change", (event) => { const guides = $("guide-overlay"); if (guides) guides.style.display = event.target.checked ? "block" : "none"; fitPage(); state.canvas?.requestRenderAll(); });
  $("import-ai")?.addEventListener("click", () => $("import-ai-file")?.click()); $("import-debug")?.addEventListener("click", () => $("import-debug-file")?.click());
  $("import-ai-package")?.addEventListener("click", () => $("import-ai-package-file")?.click());
  $("import-ai-file")?.addEventListener("change", (event) => { const file = event.target.files?.[0]; if (!file) return; const reader = new FileReader(); reader.onload = () => { try { validateAiSpec(JSON.parse(String(reader.result || ""))); } catch (error) { status(`AI JSON is invalid: ${error.message}`); } }; reader.readAsText(file); event.target.value = ""; });
  $("import-ai-package-file")?.addEventListener("change", (event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) importDesignPackage(file).catch((error) => status(`AI package import failed: ${error.message}`)); });
  $("import-debug-file")?.addEventListener("change", (event) => { if (event.target.files?.[0]) importDebugDocument(event.target.files[0]); event.target.value = ""; });
  $("layers-filter")?.addEventListener("change", (event) => { state.layerFilter = event.target.value; refreshLayers(); });
  $("layers-search")?.addEventListener("input", (event) => { state.layerSearch = event.target.value; refreshLayers(); });
  $("apply-ai")?.addEventListener("click", applyAiDesign); $("load-sample")?.addEventListener("click", loadSample);
  $("undo")?.addEventListener("click", async () => { if (!state.history.length) return; state.future.push(snapshot()); state.doc = normalizeDocument(state.history.pop()); state.activeId = elements()[0] ? elementId(elements()[0]) : null; await loadPhotos(); await queueRender(); status("Undid the last operation."); });
  $("redo")?.addEventListener("click", async () => { if (!state.future.length) return; state.history.push(snapshot()); state.doc = normalizeDocument(state.future.pop()); state.activeId = elements()[0] ? elementId(elements()[0]) : null; await loadPhotos(); await queueRender(); status("Redid the last operation."); });
  renderBrowserSaveList(); setupControls(); setupCanvas();
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
