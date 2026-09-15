// Pure render-space geometry and composition checks shared by the interactive
// Fabric renderer and its export renderer.  The helper intentionally accepts a
// bounds resolver so the geometry can be unit-tested without a browser while
// production passes Fabric's public getBoundingRect() result.
(() => {
  const root = typeof window !== "undefined" ? window : globalThis;

  const RENDER_GEOMETRY_EPSILON_PX = 0.5;
  const TEXT_PHOTO_CLEARANCE_MM = 2;
  const MIN_INTERSECTION_AREA_PX = 1;
  const TEXT_PHOTO_COLLISION_RATIO = 0.01;
  const TEXT_TEXT_COLLISION_RATIO = 0.1;
  const TEXT_TEXT_COLLISION_AREA_PX = 16;

  const finite = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;

  function normaliseBounds(bounds) {
    if (!bounds) return null;
    const left = finite(bounds.left);
    const top = finite(bounds.top);
    const right = finite(bounds.right, left + finite(bounds.width));
    const bottom = finite(bounds.bottom, top + finite(bounds.height));
    if (![left, top, right, bottom].every(Number.isFinite) || right < left || bottom < top) return null;
    return { left, top, right, bottom, width: Math.max(0, right - left), height: Math.max(0, bottom - top) };
  }

  function rectArea(bounds) {
    const rect = normaliseBounds(bounds);
    return rect ? rect.width * rect.height : 0;
  }

  function rectIntersection(first, second, epsilon = 0) {
    const a = normaliseBounds(first);
    const b = normaliseBounds(second);
    if (!a || !b) return null;
    const left = Math.max(a.left, b.left);
    const top = Math.max(a.top, b.top);
    const right = Math.min(a.right, b.right);
    const bottom = Math.min(a.bottom, b.bottom);
    const width = right - left;
    const height = bottom - top;
    if (width <= Number(epsilon) || height <= Number(epsilon)) return null;
    return { left, top, right, bottom, width, height, area: width * height };
  }

  function expandBounds(bounds, amount) {
    const rect = normaliseBounds(bounds);
    const padding = Math.max(0, finite(amount));
    if (!rect) return null;
    return { left: rect.left - padding, top: rect.top - padding, right: rect.right + padding, bottom: rect.bottom + padding,
      width: rect.width + padding * 2, height: rect.height + padding * 2 };
  }

  // Returns the shortest gap between two axis-aligned bounds.  Touching edges
  // have distance zero, but still have no area intersection.
  function boundsDistance(first, second) {
    const a = normaliseBounds(first);
    const b = normaliseBounds(second);
    if (!a || !b) return Infinity;
    const dx = Math.max(a.left - b.right, b.left - a.right, 0);
    const dy = Math.max(a.top - b.bottom, b.top - a.bottom, 0);
    return Math.hypot(dx, dy);
  }

  function rotatedElementBounds(element) {
    const x = finite(element?.x);
    const y = finite(element?.y);
    const width = Math.max(0, finite(element?.width));
    const height = Math.max(0, finite(element?.height));
    const radians = finite(element?.rotation_deg) * Math.PI / 180;
    const cosine = Math.abs(Math.cos(radians));
    const sine = Math.abs(Math.sin(radians));
    const boundWidth = width * cosine + height * sine;
    const boundHeight = width * sine + height * cosine;
    return {
      left: x + width / 2 - boundWidth / 2,
      top: y + height / 2 - boundHeight / 2,
      right: x + width / 2 + boundWidth / 2,
      bottom: y + height / 2 + boundHeight / 2,
      width: boundWidth,
      height: boundHeight,
    };
  }

  function roundedBounds(bounds) {
    const rect = normaliseBounds(bounds);
    if (!rect) return null;
    return Object.fromEntries(Object.entries(rect).map(([key, value]) => [key, Number(value.toFixed(2))]));
  }

  function objectsFor(objectsByElement, id) {
    if (objectsByElement instanceof Map) return objectsByElement.get(id) || [];
    return objectsByElement?.[id] || [];
  }

  function objectForKind(objectsByElement, id, kind) {
    return objectsFor(objectsByElement, id).find((object) => object && object._kind === kind) || null;
  }

  function warningKey(warning) {
    return [warning.element_id, warning.code, warning.covered_by || warning.other_element_id || ""].join("|");
  }

  function pushWarning(report, warning) {
    if (!report || !Array.isArray(report.warnings)) return;
    const key = warningKey(warning);
    if (report.warnings.some((item) => warningKey(item) === key)) return;
    report.warnings.push(warning);
  }

  function overflowSides(actual, declared, epsilon = RENDER_GEOMETRY_EPSILON_PX) {
    const sides = [];
    if (actual.left < declared.left - epsilon) sides.push("left");
    if (actual.top < declared.top - epsilon) sides.push("top");
    if (actual.right > declared.right + epsilon) sides.push("right");
    if (actual.bottom > declared.bottom + epsilon) sides.push("bottom");
    return sides;
  }

  function augmentOrPushTextOverflow(report, element, details) {
    const elementId = String(element.element_id || element.id || "");
    const existing = report.warnings?.find((warning) => warning.element_id === elementId && warning.code === "FABRIC_TEXT_OVERFLOW");
    if (existing) {
      Object.assign(existing, { ...details, render_space: true });
      return;
    }
    pushWarning(report, {
      element_id: elementId,
      code: "FABRIC_TEXT_DECLARED_BOX_OVERFLOW",
      message: "Rendered text extends beyond its declared box after browser-metric fitting.",
      ...details,
    });
  }

  function textPhotoDetails(text, photo, textBounds, photoBounds, intersection, distancePx = null, pxPerMm = 4) {
    const textArea = Math.max(rectArea(textBounds), 0.001);
    const photoArea = Math.max(rectArea(photoBounds), 0.001);
    return {
      other_element_id: photo.id,
      covered_by: photo.id,
      text_bounds: roundedBounds(textBounds),
      photo_frame_bounds: roundedBounds(photoBounds),
      intersection_bounds: roundedBounds(intersection),
      intersection_area_px: intersection ? Number(intersection.area.toFixed(2)) : 0,
      text_coverage_ratio: intersection ? Number((intersection.area / textArea).toFixed(4)) : 0,
      photo_coverage_ratio: intersection ? Number((intersection.area / photoArea).toFixed(4)) : 0,
      text_rotation_deg: finite(text.rotation_deg),
      photo_rotation_deg: finite(photo.rotation_deg),
      text_z_index: finite(text.z_index),
      photo_z_index: finite(photo.z_index),
      ...(distancePx == null ? {} : { distance_px: Number(distancePx.toFixed(2)), distance_mm: Number((distancePx / Math.max(finite(pxPerMm, 4), 0.001)).toFixed(2)) }),
    };
  }

  /**
   * Validate final rendered bounds, after Fabric has created every object and
   * after safe-area/font repairs.  This reports only; it never moves elements.
   */
  function validateRenderedComposition({ elements = [], objectsByElement, getBounds, report,
    pxPerMm = 4, textPhotoClearanceMm = TEXT_PHOTO_CLEARANCE_MM,
    geometryEpsilonPx = RENDER_GEOMETRY_EPSILON_PX } = {}) {
    if (!Array.isArray(elements) || typeof getBounds !== "function" || !report) return report;
    const visible = elements.filter((element) => !element.hidden);
    const texts = [];
    const photos = [];
    for (const element of visible) {
      const id = String(element.element_id || element.id || "");
      if (!id) continue;
      const kind = element.type === "text" ? "text" : element.type === "photo" ? "photo-frame" : null;
      if (!kind) continue;
      const object = objectForKind(objectsByElement, id, kind);
      if (!object || object.visible === false) continue;
      object.setCoords?.();
      const actual = normaliseBounds(getBounds(object, { includeStroke: kind === "photo-frame" }));
      if (!actual) continue;
      const record = { ...element, id, rendered: actual, rotation_deg: finite(element.rotation_deg), z_index: finite(element.z_index) };
      if (kind === "text") {
        const declared = rotatedElementBounds(element);
        const sides = overflowSides(actual, declared, geometryEpsilonPx);
        if (sides.length) {
          augmentOrPushTextOverflow(report, element, {
            declared_bounds: roundedBounds(declared), rendered_bounds: roundedBounds(actual), overflow_sides: sides,
            font_size_pt: finite(element.text_style?.font_size_pt), rotation_deg: finite(element.rotation_deg),
          });
        }
        texts.push(record);
      } else {
        photos.push(record);
      }
    }

    const textPhotoClearancePx = Math.max(0, finite(textPhotoClearanceMm, TEXT_PHOTO_CLEARANCE_MM)) * finite(pxPerMm, 4);
    for (const text of texts) {
      for (const photo of photos) {
        const intersection = rectIntersection(text.rendered, photo.rendered, geometryEpsilonPx);
        const textArea = Math.max(rectArea(text.rendered), 0.001);
        const photoArea = Math.max(rectArea(photo.rendered), 0.001);
        const ratio = intersection ? intersection.area / Math.min(textArea, photoArea) : 0;
        const details = textPhotoDetails(text, photo, text.rendered, photo.rendered, intersection, null, pxPerMm);
        // Text can be deliberately printed over a photograph, but the intent
        // must be explicit in the document. allow_bleed is unrelated.
        if (intersection && intersection.area >= MIN_INTERSECTION_AREA_PX && ratio >= TEXT_PHOTO_COLLISION_RATIO && !text.allow_photo_overlap) {
          pushWarning(report, { element_id: text.id, code: "FABRIC_TEXT_PHOTO_COLLISION",
            message: "Rendered text intersects a photo frame.", ...details });
          if (photo.z_index > text.z_index) {
            pushWarning(report, { element_id: text.id, code: "FABRIC_TEXT_COVERED_BY_PHOTO",
              message: "Rendered text is behind a foreground photo frame.", ...details });
          }
        } else if (!intersection && !text.allow_photo_overlap) {
          const distancePx = boundsDistance(text.rendered, photo.rendered);
          if (distancePx <= textPhotoClearancePx + geometryEpsilonPx) {
            pushWarning(report, { element_id: text.id, code: "FABRIC_TEXT_PHOTO_CLEARANCE",
              message: "Rendered text is too close to a photo frame.", ...textPhotoDetails(text, photo, text.rendered, photo.rendered, null, distancePx, pxPerMm) });
          }
        }
      }
    }

    for (let index = 0; index < texts.length; index += 1) {
      for (const other of texts.slice(index + 1)) {
        if (texts[index].allow_text_overlap || other.allow_text_overlap) continue;
        const intersection = rectIntersection(texts[index].rendered, other.rendered, geometryEpsilonPx);
        if (!intersection) continue;
        const ratio = intersection.area / Math.max(Math.min(rectArea(texts[index].rendered), rectArea(other.rendered)), 0.001);
        if (intersection.area < TEXT_TEXT_COLLISION_AREA_PX && ratio < TEXT_TEXT_COLLISION_RATIO) continue;
        pushWarning(report, { element_id: texts[index].id, code: "FABRIC_TEXT_TEXT_COLLISION",
          message: "Rendered text elements significantly intersect.", other_element_id: other.id,
          text_bounds: roundedBounds(texts[index].rendered), other_text_bounds: roundedBounds(other.rendered),
          intersection_bounds: roundedBounds(intersection), intersection_area_px: Number(intersection.area.toFixed(2)),
          text_rotation_deg: texts[index].rotation_deg, other_rotation_deg: other.rotation_deg,
          text_z_index: texts[index].z_index, other_z_index: other.z_index });
      }
    }
    return report;
  }

  const api = Object.freeze({
    RENDER_GEOMETRY_EPSILON_PX, TEXT_PHOTO_CLEARANCE_MM, rectArea, rectIntersection,
    expandBounds, boundsDistance, rotatedElementBounds, validateRenderedComposition,
  });
  root.collageRenderValidation = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
