const assert = require("node:assert/strict");
const library = require("../src/photovault/web/static/collage_template_library.js");
const photoSet = (count, shape = "mixed") => Array.from({ length: count }, (_, i) => ({
  asset_id: `image-${i}`, filename: `${i}.jpg`,
  width: shape === "portrait" || (shape === "mixed" && i % 3 === 0) ? 2400 : 4000,
  height: shape === "landscape" || (shape === "mixed" && i % 3 !== 0) ? 2600 : 3600,
  captured: `2026-04-16 12:${String(i).padStart(2, "0")}:00`,
}));

let cases = 0;
for (const family of library.families) for (const preset of library.presets) {
  for (const count of [10, 11, 12, 13, 15, 18, 20, 24, 33, 48, 60]) {
    for (const type of ["single", "spread"]) for (const shape of ["mixed", "portrait", "landscape"]) {
      const source = photoSet(count, shape);
      const snapshot = JSON.stringify(source);
      const result = library.build({ familyId: family.id, photos: source, page: { preset_id: preset.id, type }, title: "A spring journey", subtitle: "16 APRIL 2026", caption: "Our memories together." });
      const elements = result.spec.alternatives[0].elements, photos = elements.filter((e) => e.type === "photo");
      assert.equal(photos.length, source.length);
      assert.deepEqual(new Set(photos.map((e) => e.asset_id)), new Set(source.map((e) => e.asset_id)), `${family.id} ${count}: no omitted or repeated source`);
      assert.equal(JSON.stringify(source), snapshot, "never mutate catalog metadata");
      assert.ok(elements.length <= 200, "existing schema element limit");
      const width = preset.width * (type === "spread" ? 2 : 1), height = preset.height;
      for (const e of elements) {
        assert.ok([e.x_mm, e.y_mm, e.width_mm, e.height_mm].every(Number.isFinite));
        assert.ok(e.width_mm > 0 && e.height_mm > 0);
        assert.ok(e.x_mm >= 0 && e.y_mm >= 0 && e.x_mm + e.width_mm <= width + 0.001 && e.y_mm + e.height_mm <= height + 0.001, `${family.id} ${type} ${e.id}: on-page`);
      }
      if (type === "spread") for (const e of photos) assert.ok(e.x_mm + e.width_mm <= preset.width || e.x_mm >= preset.width, "frames do not cross the binding");
      if (family.chronological) assert.deepEqual(photos.map((e) => e.asset_id), source.map((e) => e.asset_id));
      cases++;
    }
  }
}

// Regression: the previous generator silently dropped the fourth manual hero.
for (const family of library.families) {
  const heroIds = ["image-2", "image-5", "image-9", "image-12"];
  const result = library.build({ familyId: family.id, photos: photoSet(18), heroIds, subheroIds: ["image-7"] });
  for (const id of heroIds) assert.ok(result.spec.alternatives[0].elements.some((e) => e.asset_id === id && e.role === "hero"));
  assert.equal(result.diagnostics.placedCount, 18);
}
assert.throws(() => library.build({ photos: [...photoSet(10), photoSet(10)[0]] }), /distinct/);
assert.throws(() => library.build({ photos: photoSet(18), heroIds: ["absent"] }), /current source/);
assert.throws(() => library.build({ photos: photoSet(18), heroIds: ["image-1"], subheroIds: ["image-1"] }), /distinct/);
for (const familyId of ["film", "chapters"]) {
  const baseline = library.build({ familyId, photos: photoSet(18) });
  const overridden = library.build({ familyId, photos: photoSet(18), heroIds: ["image-4"] });
  const photos = overridden.spec.alternatives[0].elements.filter((e) => e.type === "photo");
  assert.deepEqual(photos.map((e) => e.asset_id), photoSet(18).map((p) => p.asset_id));
  const prior = baseline.spec.alternatives[0].elements.find((e) => e.asset_id === "image-4");
  const chosen = photos.find((e) => e.asset_id === "image-4");
  assert.ok(chosen.width_mm * chosen.height_mm > prior.width_mm * prior.height_mm, "hero selection changes sequence geometry without reordering photos");
}
assert.throws(() => library.build({ photos: photoSet(61) }), /10–60/);

// Assignment must be based on fit, not the filename or current enumeration.
const matching = photoSet(12, "portrait"); matching[11].width = 8000; matching[11].height = 2500;
const scenic = library.build({ familyId: "horizon", photos: matching });
assert.equal(scenic.diagnostics.heroes[0], "image-11", "wide source should receive the wide hero frame");
const chronological = library.build({ familyId: "film", photos: photoSet(12).reverse() });
assert.deepEqual(chronological.spec.alternatives[0].elements.filter((e) => e.type === "photo").map((e) => e.asset_id), photoSet(12).map((p) => p.asset_id));
const shapes = library.families.map((f) => library.build({ familyId: f.id, photos: photoSet(18) }).spec.alternatives[0].elements.filter((e) => e.type === "photo").map((e) => [e.x_mm, e.y_mm, e.width_mm, e.height_mm]));
assert.equal(new Set(shapes.map(JSON.stringify)).size, library.families.length, "families must have different spatial plans");
assert.equal(library.families.length, 12);
for (const [layout_archetype, compatible] of Object.entries(library.semanticFamilies)) {
  assert.ok(compatible.includes(library.recommend(photoSet(18), {}, { layout_archetype })[0].familyId), layout_archetype);
}
const rolePhotos = photoSet(12, "landscape");
const semantic = library.build({ familyId: "magazine", photos: rolePhotos, semantics: { dominant_hero: "image-10" } });
assert.ok(semantic.diagnostics.heroes.includes("image-10"), "existing hero metadata affects assignment");
console.log(`${cases} adaptive layouts: all-photo, finite geometry, page, spread, chronological and role invariants passed.`);
