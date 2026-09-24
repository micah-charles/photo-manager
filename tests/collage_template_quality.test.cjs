const assert = require("node:assert/strict");
const library = require("../src/photovault/web/static/collage_template_library.js");

const photos = Array.from({length: 12}, (_, i) => ({
  asset_id: `q-${i}`, filename: `${i}.jpg`, width: 4000, height: 3000,
  captured: `2026-04-16 ${String(12 + Math.floor(i / 4)).padStart(2, "0")}:${String(i % 4 * 12).padStart(2, "0")}:00`,
}));
const elements = result => result.spec.alternatives[0].elements;
const photoElements = result => elements(result).filter(item => item.type === "photo");
const textElements = result => elements(result).filter(item => item.type === "text");

// Chapter and film labels expose actual sequence ranges and capture times.
for (const familyId of ["film", "chapters"]) {
  const result = library.build({familyId, photos, title: "The visit", subtitle: "16 April 2026"});
  const labels = textElements(result).filter(item => item.id.startsWith("fieldnote-")).map(item => item.content);
  assert.ok(labels.length > 0, `${familyId} has visible narrative structure`);
  assert.ok(labels.some(label => /\d{2}–\d{2}/.test(label)), `${familyId} labels image sequence ranges`);
  assert.ok(labels.some(label => /2026-04-16/.test(label)), `${familyId} uses source capture times`);
  assert.ok(!labels.some(label => /photographs/i.test(label)), "no filler photo-count copy");
}

// The two notebook text islands preserve the section caption without repeating
// the title or replacing part of the user's text with generated filler.
const caption = "沿著老屋的窗與門，慢慢走進旅途中的一頁。 A quiet walk through the house and its details.";
const notes = textElements(library.build({familyId:"journal", photos, caption})).filter(item=>item.id.startsWith("fieldnote-")).map(item=>item.content).join(" ");
for (const word of caption.split(/\s+/).filter(Boolean)) assert.ok(notes.includes(word), `caption word retained: ${word}`);
assert.ok(!/photographs/i.test(notes));

// Face boxes from original-pixel analysis are rotated into oriented coordinates
// once, influence prominent assignment, and produce explicit crop diagnostics.
const portraitFace = {
  asset_id:"face-hero", filename:"portrait.jpg", width:3000, height:4000,
  orientation:6, rating:5,
  analysis:{coordinate_space:"original",faces:[{left:0.12,top:0.18,right:0.25,bottom:0.34,confidence:0.98}]},
};
const faceSet = [...photos.slice(0, 6), portraitFace, ...photos.slice(7)];
const faceResult = library.build({familyId:"magazine", photos:faceSet, page:{preset_id:"a4-landscape"}, heroIds:["face-hero"]});
const assignedFace = photoElements(faceResult).find(item=>item.asset_id === "face-hero");
assert.equal(assignedFace.role,"hero");
assert.ok(assignedFace.height_mm > assignedFace.width_mm * 0.55, "manual hero receives a compatible prominent frame");
assert.equal(faceResult.diagnostics.faceMetadataCount,1);
assert.ok(faceResult.diagnostics.safetyWarnings.every(item=>item.asset_id));
assert.deepEqual(new Set(photoElements(faceResult).map(item=>item.asset_id)),new Set(faceSet.map(item=>item.asset_id)));

// A poor or missing detector result falls back safely and keeps all coordinates finite.
const malformed = {...portraitFace, analysis:{faces:[{left:0.8,top:0.8,right:0.2,bottom:0.2},null]}};
const fallback = library.build({familyId:"family",photos:[...photos.slice(0,6),malformed,...photos.slice(7)]});
assert.equal(fallback.diagnostics.faceMetadataCount,0);
assert.ok(photoElements(fallback).every(item=>Number.isFinite(item.image.focus_x)&&Number.isFinite(item.image.focus_y)));

console.log("Narrative families use real sequence metadata; captions and photo assignments remain intact.");
