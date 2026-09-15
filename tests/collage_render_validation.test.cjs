const assert = require("node:assert/strict");
const validation = require("../src/photovault/web/static/collage_render_validation.js");

const rect = (left, top, right, bottom) => ({ left, top, right, bottom });

function reportFor(elements, bounds, pxPerMm = 4) {
  const objects = new Map();
  for (const [id, kinds] of Object.entries(bounds)) {
    objects.set(id, Object.entries(kinds).map(([kind, value]) => ({ _kind: kind, visible: true, bounds: value, setCoords() {} })));
  }
  const report = { validation_status: "valid", warnings: [], repairs: [] };
  validation.validateRenderedComposition({
    elements,
    objectsByElement: objects,
    getBounds: (object) => object.bounds,
    report,
    pxPerMm,
  });
  return report;
}

// Basic rectangle contract.
assert.equal(validation.rectIntersection(rect(0, 0, 10, 10), rect(20, 20, 30, 30)), null);
assert.equal(validation.rectIntersection(rect(0, 0, 10, 10), rect(10, 0, 20, 10)), null, "touching edges are not area overlap");
assert.equal(validation.rectIntersection(rect(0, 0, 10, 10), rect(9, 9, 20, 20)).area, 1, "one-pixel overlap is measurable");
assert.equal(validation.rectIntersection(rect(0, 0, 10, 10), rect(2, 2, 4, 4)).area, 4, "contained rectangle is measurable");
assert.equal(validation.boundsDistance(rect(0, 0, 10, 10), rect(10, 0, 20, 10)), 0);
assert.equal(validation.boundsDistance(rect(0, 0, 10, 10), rect(13, 14, 20, 20)), 5);
const rotated = validation.rotatedElementBounds({ x: 0, y: 0, width: 10, height: 20, rotation_deg: 90 });
assert.deepEqual({ left: rotated.left, right: rotated.right, bottom: rotated.bottom, width: Math.round(rotated.width), height: Math.round(rotated.height) }, {
  left: -5, right: 15, bottom: 15, width: 20, height: 10,
});
assert.ok(Math.abs(rotated.top - 5) < 1e-9);

const photo = (id = "photo-1", extra = {}) => ({ id, type: "photo", x: 0, y: 20, width: 100, height: 100, z_index: 10, ...extra });
const text = (id = "text-1", extra = {}) => ({ id, type: "text", x: 0, y: 0, width: 100, height: 20, rotation_deg: 0, z_index: 20, text_style: { font_size_pt: 12 }, ...extra });

// Text safely above a photo: no collision and no 2 mm clearance warning.
let report = reportFor([text(), photo()], {
  "text-1": { text: rect(0, 0, 100, 20) },
  "photo-1": { "photo-frame": rect(0, 40, 100, 140) },
});
assert.equal(report.warnings.length, 0);

// Critical regression: the declared box ends at y=20, but actual Fabric text
// bounds end at y=21 and enter the photo beginning at y=20.
report = reportFor([text(), photo()], {
  "text-1": { text: rect(0, 0, 100, 21) },
  "photo-1": { "photo-frame": rect(0, 20, 100, 120) },
});
assert.ok(report.warnings.some((item) => item.code === "FABRIC_TEXT_PHOTO_COLLISION"));
assert.ok(report.warnings.some((item) => item.code === "FABRIC_TEXT_DECLARED_BOX_OVERFLOW"));
const collision = report.warnings.find((item) => item.code === "FABRIC_TEXT_PHOTO_COLLISION");
assert.equal(collision.covered_by, "photo-1");
assert.ok(collision.intersection_bounds && collision.text_bounds && collision.photo_frame_bounds);
assert.equal(report.warnings.find((item) => item.code === "FABRIC_TEXT_DECLARED_BOX_OVERFLOW").element_id, "text-1");

// Intentional overlay is explicit and is not confused with page bleed.
report = reportFor([text("text-1", { allow_photo_overlap: true }), photo()], {
  "text-1": { text: rect(0, 0, 100, 30) },
  "photo-1": { "photo-frame": rect(0, 20, 100, 120) },
});
assert.equal(report.warnings.filter((item) => item.code === "FABRIC_TEXT_PHOTO_COLLISION").length, 0);

// A foreground photo produces the stronger occlusion warning.
report = reportFor([text("text-1", { z_index: 1 }), photo("photo-1", { z_index: 2 })], {
  "text-1": { text: rect(0, 0, 100, 30) },
  "photo-1": { "photo-frame": rect(0, 20, 100, 120) },
});
assert.ok(report.warnings.some((item) => item.code === "FABRIC_TEXT_COVERED_BY_PHOTO"));

// A gap at or below 2 mm is a clearance warning, not a collision.
report = reportFor([text(), photo()], {
  "text-1": { text: rect(0, 0, 100, 20) },
  "photo-1": { "photo-frame": rect(0, 27.5, 100, 127.5) },
});
assert.equal(report.warnings.some((item) => item.code === "FABRIC_TEXT_PHOTO_COLLISION"), false);
assert.ok(report.warnings.some((item) => item.code === "FABRIC_TEXT_PHOTO_CLEARANCE"));
assert.equal(report.warnings.find((item) => item.code === "FABRIC_TEXT_PHOTO_CLEARANCE").distance_mm, 1.88);

// Physical clearance conversion follows the configured renderer scale.
report = reportFor([text(), photo()], {
  "text-1": { text: rect(0, 0, 100, 20) },
  "photo-1": { "photo-frame": rect(0, 27.5, 100, 127.5) },
}, 5);
assert.equal(report.warnings.find((item) => item.code === "FABRIC_TEXT_PHOTO_CLEARANCE").distance_mm, 1.5);

// Production documents use element_id rather than the AI spec's id.
report = reportFor([{ ...text("ignored", { element_id: "text-prod" }), id: undefined }, { ...photo("ignored-photo", { element_id: "photo-prod" }), id: undefined }], {
  "text-prod": { text: rect(0, 0, 100, 21) },
  "photo-prod": { "photo-frame": rect(0, 20, 100, 120) },
});
assert.equal(report.warnings.find((item) => item.code === "FABRIC_TEXT_DECLARED_BOX_OVERFLOW").element_id, "text-prod");
assert.equal(report.warnings.find((item) => item.code === "FABRIC_TEXT_PHOTO_COLLISION").element_id, "text-prod");

// Significant unrelated text overlap is reported; a declared typographic
// group can explicitly suppress it.
report = reportFor([text("text-1"), text("text-2", { x: 10, y: 10, z_index: 21 })], {
  "text-1": { text: rect(0, 0, 100, 40) },
  "text-2": { text: rect(10, 10, 110, 50) },
});
assert.ok(report.warnings.some((item) => item.code === "FABRIC_TEXT_TEXT_COLLISION"));
report = reportFor([text("text-1", { allow_text_overlap: true }), text("text-2", { x: 10, y: 10 })], {
  "text-1": { text: rect(0, 0, 100, 40) },
  "text-2": { text: rect(10, 10, 110, 50) },
});
assert.equal(report.warnings.some((item) => item.code === "FABRIC_TEXT_TEXT_COLLISION"), false);

console.log("collage render validation tests passed");
