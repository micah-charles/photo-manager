/* Adaptive art-directed compositions. Pure functions; browser and Node share
 * this engine. Output is the existing CollageDesignSpec v2, never Fabric JSON. */
((root) => {
  "use strict";
  const VERSION = 3;
  const presets = [
    ["small-square", "20 × 20 cm", 200, 200], ["square", "25 × 25 cm", 250, 250],
    ["large-square", "30 × 30 cm", 300, 300], ["a4-portrait", "A4 portrait", 210, 297],
    ["a4-landscape", "A4 landscape", 297, 210], ["large-landscape", "30 × 20 cm", 300, 200],
    ["large-portrait", "20 × 30 cm", 200, 300],
  ].map(([id, label, width, height]) => ({ id, label, width, height }));
  const families = [
    { id: "kew", name: "Kew Interlocking Scrapbook", group: "Tactile", description: "Interlocking prints, two anchors and a loose ribbon of memories.", hierarchy: ["hero", "hero", "secondary", "secondary"], paper: "#f5f2ed", ink: "#304637", font: "script", footer: true, overlap: true, border: 1.3, shadow: true },
    { id: "magazine", name: "Editorial Opening", group: "Editorial", description: "A confident opening photograph with a narrow sidebar and a closing band.", hierarchy: ["hero", "secondary"], paper: "#faf8f3", ink: "#242722", font: "display" },
    { id: "diptych", name: "Two Perspectives", group: "Editorial", description: "Two parallel stories; each anchor leads its own photographic trail.", hierarchy: ["hero", "hero"], paper: "#f1eee7", ink: "#343c41", font: "serif" },
    { id: "film", name: "Film Diary", group: "Sequence", description: "Numbered frames in film lanes, read in capture order.", hierarchy: [], chronological: true, paper: "#e8e3d8", ink: "#35352f", font: "sans" },
    { id: "architecture", name: "Architectural Spine", group: "Editorial", description: "A tall central spine connects staggered wings of architectural details.", hierarchy: ["hero", "secondary"], paper: "#ebe8e1", ink: "#393c36", font: "display" },
    { id: "journal", name: "Travel Notebook", group: "Tactile", description: "Alternating picture clusters and narrative blocks form an offset reading path.", hierarchy: ["hero", "secondary"], paper: "#f2eadc", ink: "#65533d", font: "serif", border: 1.2 },
    { id: "family", name: "Family Constellation", group: "Tactile", description: "A central family portrait connects unequal satellite clusters of candid moments.", hierarchy: ["hero", "secondary", "secondary"], paper: "#f2e7dc", ink: "#644c44", font: "script", border: 1.5, shadow: true },
    { id: "horizon", name: "Scenic Horizon", group: "Scenic", description: "An uninterrupted landscape forms the spine between two bands of moments.", hierarchy: ["hero", "secondary", "secondary"], paper: "#edf0eb", ink: "#354b48", font: "serif" },
    { id: "gallery", name: "Quiet Gallery", group: "Editorial", description: "One generous image and a deliberate white pause beside a collection of studies.", hierarchy: ["hero"], paper: "#ffffff", ink: "#353535", font: "serif" },
    { id: "mosaic", name: "Woven Mosaic", group: "Dense", description: "Interlocking rectangles at several scales, with photographs carrying the page.", hierarchy: ["secondary", "secondary", "secondary"], paper: "#f5f2ed", ink: "#343b39", font: "sans", footer: true },
    { id: "botanical", name: "Botanical Fieldnotes", group: "Scenic", description: "A chain of specimens between two detail ribbons and editable fieldnotes.", hierarchy: ["secondary", "secondary", "secondary"], paper: "#e9ede1", ink: "#465339", font: "serif", border: 0.8 },
    { id: "chapters", name: "Story Chapters", group: "Sequence", description: "Beginning, middle and ending: three connected episodes, each with a local opening beat.", hierarchy: [], chronological: true, paper: "#f8f4eb", ink: "#504538", font: "serif" },
  ];
  const semanticFamilies = {
    architecture_journey: ["architecture", "diptych", "gallery"],
    scenic_hero: ["horizon", "magazine", "gallery"],
    sequence_journey: ["chapters", "film", "journal"],
    family_memory: ["family", "diptych", "kew"],
    detail_mosaic: ["botanical", "mosaic", "journal"],
    travel_scrapbook: ["kew", "journal", "magazine", "mosaic"],
  };
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const number = (v, fallback) => v != null && Number.isFinite(Number(v)) ? Number(v) : fallback;
  const area = (r) => r.w * r.h;
  const rect = (x, y, w, h, role = "supporting", extra = {}) => ({ x, y, w, h, role, ...extra });
  const splitCounts = (n, weights) => {
    const sum = weights.reduce((a, b) => a + b, 0);
    const counts = weights.map((w) => Math.floor(n * w / sum));
    const order = weights.map((w, i) => ({ i, fraction: n * w / sum - counts[i] })).sort((a, b) => b.fraction - a.fraction || a.i - b.i);
    const remaining = n - counts.reduce((a, b) => a + b, 0);
    for (let i = 0; i < remaining; i++) counts[order[i].i]++;
    return counts;
  };

  function validBox(value) {
    const b = Array.isArray(value) ? { left:value[0], top:value[1], right:value[2], bottom:value[3] } : value;
    if (!b || ![b.left,b.top,b.right,b.bottom].every(v => typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 1) || b.left >= b.right || b.top >= b.bottom) return null;
    return { left:b.left, top:b.top, right:b.right, bottom:b.bottom };
  }

  function orientedBox(box, orientation) {
    const point = (x,y) => ({ 2:[1-x,y], 3:[1-x,1-y], 4:[x,1-y], 5:[y,x], 6:[1-y,x], 7:[1-y,1-x], 8:[y,1-x] })[orientation] || [x,y];
    const points = [[box.left,box.top],[box.right,box.top],[box.left,box.bottom],[box.right,box.bottom]].map(([x,y])=>point(x,y));
    return {left:Math.min(...points.map(p=>p[0])),top:Math.min(...points.map(p=>p[1])),right:Math.max(...points.map(p=>p[0])),bottom:Math.max(...points.map(p=>p[1]))};
  }

  function photoInfo(item, index) {
    let width = number(item.width, 0), height = number(item.height, 0);
    if ([5, 6, 7, 8].includes(Number(item.orientation))) [width, height] = [height, width];
    const analysis = item.analysis || {};
    // Cached detector coordinates describe original pixels, before EXIF rotation.
    // Explicit oriented metadata is accepted without applying rotation twice.
    const orientation = analysis.coordinate_space === "oriented" ? 1 : Number(item.orientation || analysis.orientation || 1);
    const faces = (Array.isArray(analysis.faces) ? analysis.faces : []).map(validBox).filter(Boolean).map(b=>orientedBox(b,orientation));
    const subjectTags = [item.subject_type, item.tags, analysis.subject_type, ...(Array.isArray(analysis.subjects) ? analysis.subjects.map(s=>typeof s === "string" ? s : s.label) : [])].filter(Boolean).join(" ").toLowerCase();
    const subjects = (Array.isArray(analysis.subjects) ? analysis.subjects : []).filter(s=>s && /person|people|portrait|group/i.test(s.label || "")).map(s=>validBox(s.box || s)).filter(Boolean).map(b=>orientedBox(b,orientation));
    const protectedBoxes = [...faces.map(b=>({left:Math.max(0,b.left-0.025),top:Math.max(0,b.top-0.035),right:Math.min(1,b.right+0.025),bottom:Math.min(1,b.bottom+0.025)})), ...subjects];
    const people = faces.length > 0 || subjects.length > 0 || (Array.isArray(item.people) ? item.people.length > 0 : Boolean(item.people)) || /person|people|portrait|family|group/.test(subjectTags);
    return {
      ...item, asset_id: String(item.asset_id || ""), index, width, height,
      aspect: width > 0 && height > 0 ? width / height : 1,
      dimensionsKnown: width > 0 && height > 0,
      quality: clamp(number(item.quality_score ?? analysis.quality_score, 50) / 100, 0, 1),
      preference: (item.favourite ? 0.45 : 0) + clamp(number(item.rating, 0) / 5, 0, 1) * 0.5,
      faceCount: faces.length, faces, protectedBoxes, people,
      groupPortrait: faces.length > 1 || /group/.test(subjectTags),
      subjectKind: /stained.?glass|tall.?architecture|window|tower/.test(subjectTags) ? "tall" : /wide.?interior|interior|panorama/.test(subjectTags) ? "wide" : /detail|macro|specimen/.test(subjectTags) ? "detail" : people ? "people" : "unknown",
      focus: { x: clamp(number(item.focus_x, 0.5), 0, 1), y: clamp(number(item.focus_y, 0.5), 0, 1) },
      time: String(item.captured || item.capture_datetime || ""),
    };
  }

  // Justified region, balanced across rows: a 13th photo never becomes a lonely
  // full-width last tile. Physical aspect ratio selects the number of rows.
  function pack(region, count, physicalAspect, { gap = 1.1, varied = false, role = "supporting" } = {}) {
    if (!count) return [];
    if (count === 1) return [{ ...region, role }];
    let best;
    for (let rows = 1; rows <= count; rows++) {
      const cols = count / rows;
      const aspect = (region.w - gap * (cols - 1)) / cols / ((region.h - gap * (rows - 1)) / rows) * physicalAspect;
      if (aspect <= 0) continue;
      const cost = Math.abs(Math.log(aspect / 1.15)) + (count % rows ? 0.07 : 0);
      if (!best || cost < best.cost) best = { rows, cost };
    }
    const counts = splitCounts(count, Array(best.rows).fill(1));
    const rowHeights = varied ? counts.map((_, i) => [1.15, 0.85, 1][i % 3]) : counts.map(() => 1);
    const total = rowHeights.reduce((a, b) => a + b, 0);
    const slots = [];
    let y = region.y;
    counts.forEach((n, row) => {
      const h = (region.h - gap * (best.rows - 1)) * rowHeights[row] / total;
      const weights = Array.from({ length: n }, (_, col) => varied ? [1.25, 0.85, 1.1, 0.9][(row + col) % 4] : 1);
      const sum = weights.reduce((a, b) => a + b, 0);
      let x = region.x;
      weights.forEach((weight) => {
        const w = (region.w - gap * (n - 1)) * weight / sum;
        slots.push(rect(x, y, w, h, role)); x += w + gap;
      });
      y += h + gap;
    });
    return slots;
  }

  // Adaptive partitions retain the large anchor cards; extra images subdivide
  // support regions. This is used for the interlocking families, not every style.
  function subdivide(regions, count, aspect, gap = 0.9) {
    const out = regions.map((r) => ({ ...r }));
    while (out.length < count) {
      const candidates = out.map((r, i) => ({ r, i })).filter(({ r }) => !r.protected);
      candidates.sort((a, b) => area(b.r) - area(a.r) || a.i - b.i);
      const { r, i } = candidates[0];
      const vertical = r.w * aspect / r.h > 1.22;
      const ratio = out.length % 2 ? 0.56 : 0.46;
      const first = { ...r, rotation: 0, mask: "rectangle" }, second = { ...first };
      if (vertical) {
        first.w = (r.w - gap) * ratio; second.x = r.x + first.w + gap; second.w = r.w - first.w - gap;
      } else {
        first.h = (r.h - gap) * ratio; second.y = r.y + first.h + gap; second.h = r.h - first.h - gap;
      }
      out.splice(i, 1, first, second);
    }
    return out;
  }

  // A supporting group has a local lead and a pair/trail, not a residual grid.
  // Only subdivide within the reserved region; no extra image is introduced.
  function cluster(region, count, aspect, reverse = false) {
    if (count <= 3) return pack(region, count, aspect, { varied: true, gap: 1.5 });
    const gap = 1.5;
    const wide = region.w * aspect / region.h > 1.2;
    const lead = { ...region }, tail = { ...region };
    if (wide) {
      lead.w = (region.w - gap) * 0.42; tail.w = region.w - gap - lead.w;
      if (reverse) { lead.x += tail.w + gap; } else { tail.x += lead.w + gap; }
    } else {
      lead.h = (region.h - gap) * 0.42; tail.h = region.h - gap - lead.h;
      if (reverse) { lead.y += tail.h + gap; } else { tail.y += lead.h + gap; }
    }
    // At high counts, keep a readable rhythm without protecting an oversized
    // support anchor at the expense of all other photographs.
    const leadCount = Math.max(1, Math.floor(count / 8));
    return [...pack(lead, leadCount, aspect, { varied: true, gap }), ...pack(tail, count - leadCount, aspect, { varied: true, gap })];
  }

  function captureRange(values) {
    const stamps = values.map(value => String(value || "").match(/(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/) || null).filter(Boolean);
    if (!stamps.length) return "";
    const first = stamps[0], last = stamps[stamps.length - 1];
    return first[1] === last[1] ? `${first[1]} · ${first[2]}–${last[2]}` : `${first[1]} ${first[2]} – ${last[1]} ${last[2]}`;
  }

  function layoutFamily(family, count, aspect, sequenceRoles = [], sequenceTimes = []) {
    const id = family.id;
    const wide = aspect > 1.1;
    const slots = [], decorations = [];
    const add = (...r) => slots.push(...r);
    const regions = (list, options = {}) => {
      const counts = splitCounts(count - slots.length, list.map((r) => r.weight || area(r)));
      list.forEach((r, i) => add(...(options.cluster ? cluster(r, counts[i], aspect, i % 2 === 1) : pack(r, counts[i], aspect, options))));
    };
    if (id === "kew") {
      if (count < 10) {
        return { slots: [rect(2, 2, 54, 61, "hero", { rotation: -1 }), rect(57, 4, 40, 57, "secondary", { rotation: 2 }), ...pack(rect(2, 66, 96, 32), count - 2, aspect, { varied: true })], decorations };
      }
      const cards = [
        rect(1, 2, 32, 40, "hero", { protected: true, rotation: 2.5 }),
        rect(32, 5, 31, 37, "secondary", { protected: true, rotation: -2 }),
        rect(63, 3, 27, 37, "supporting"),
        rect(1, 43, 32, 35, "secondary", { protected: true, rotation: -0.8 }),
        rect(33, 41, 40, 38, "hero", { protected: true, mask: "rounded" }),
        rect(73, 40, 26, 19, "detail", { rotation: -2 }),
        rect(73, 61, 26, 18, "supporting", { rotation: 1.5 }),
      ];
      const ribbon = pack(rect(1, 81, 98, 18), Math.min(5, count - 7), aspect, { gap: 0.9 });
      ribbon.forEach((r, i) => Object.assign(r, { rotation: [0, 2, -1.5, 2, -1][i], mask: i === 0 ? "ellipse" : "rectangle" }));
      return { slots: subdivide([...cards, ...ribbon], count, aspect), decorations };
    }
    if (id === "magazine") {
      add(rect(0, 0, 62, 58, "hero"), rect(66, 0, 34, 30, "secondary"));
      regions([rect(66, 53, 34, 47), rect(0, 61, 62, 39)], { cluster: true });
      decorations.push({ ...rect(66, 31, 34, 20), note: 0, noteType: "caption" });
    } else if (id === "diptych") {
      // The right story opens lower: two independent tracks, not a hero row.
      add(rect(0, 0, 48, 53, "hero"), rect(52, 47, 48, 53, "hero"));
      regions([rect(0, 56, 48, 44), rect(52, 0, 48, 44)], { varied: true });
      decorations.push({ ...rect(49.8, 0, 0.4, 100), fill: "#b4b6b0" });
    } else if (id === "film") {
      const lanes = Math.max(wide ? 2 : 3, Math.ceil(count / (wide ? 8 : 5)));
      const counts = splitCounts(count, Array(lanes).fill(1));
      let sequence = 0;
      counts.forEach((n, row) => {
        const h = (100 - 4 * (lanes - 1)) / lanes, y = row * (h + 4);
        decorations.push({ ...rect(0, y, 100, h), fill: "#242824" });
        const laneStart = sequence;
        if (h >= 16) decorations.push({ ...rect(2, y + 0.35, 96, 3.1), note: 0, noteType: "film", start: laneStart, count: n, timeRange: captureRange(sequenceTimes.slice(laneStart, laneStart + n)) });
        const weights = Array.from({ length: n }, (_, i) => sequenceRoles[sequence + i] === "hero" ? 1.8 : sequenceRoles[sequence + i] === "secondary" ? 1.4 : 1);
        const sum = weights.reduce((a, b) => a + b, 0); let x = 2;
        const inset = Math.min(h >= 16 ? 5.2 : 3, h * 0.22);
        weights.forEach((weight) => {
          const w = (96 - (n - 1) * 1.6) * weight / sum;
          add(rect(x, y + inset, w, h - 2 * inset, sequenceRoles[sequence] || "sequence", { sequence: sequence++, film: true })); x += w + 1.6;
        });
        // One strip of small perforations per lane, bounded to keep <200 elements.
        for (let j = 0; j < 5; j++) decorations.push({ ...rect(2 + j * 20, y + inset * 0.3, 4, inset * 0.3), fill: "#c9c7b8" });
      });
    } else if (id === "architecture") {
      add(rect(32, 0, 36, 77, "hero"), rect(0, 18, 28, 38, "secondary"));
      regions([rect(0, 0, 28, 14), rect(0, 60, 28, 40), rect(72, 0, 28, 100), rect(32, 81, 36, 19)]);
      if (wide) slots.forEach((r) => { [r.x, r.y, r.w, r.h] = [r.y, r.x, r.h, r.w]; });
    } else if (id === "journal") {
      add(rect(0, 0, 59, 42, "hero"), rect(34, 58, 66, 42, "secondary"));
      regions([rect(0, 47, 29, 53), rect(64, 24, 36, 27)], { cluster: true });
      decorations.push({ ...rect(64, 0, 36, 21), note: 0, noteType: "caption" }, { ...rect(34, 44, 25, 14), note: 1, noteType: "caption" });
    } else if (id === "family") {
      add(rect(24, 27, 52, 47, "hero"), rect(0, 0, 43, 23, "secondary", { rotation: -1 }), rect(78, 54, 21, 43, "secondary", { rotation: 1 }));
      regions([rect(47, 0, 52, 23), rect(0, 28, 20, 72), rect(24, 78, 50, 22), rect(80, 28, 19, 22)], { varied: true, gap: 2 });
    } else if (id === "horizon") {
      add(rect(0, 27, 100, 43, "hero"), rect(0, 0, 39, 24, "secondary"), rect(70, 73, 30, 27, "secondary"));
      regions([rect(42, 0, 58, 24), rect(0, 73, 67, 27)], { cluster: true });
    } else if (id === "gallery") {
      add(rect(0, 0, 64, 70, "hero"));
      // Studies run beside the main photograph, with a caption pause between
      // them. They are part of the reading path, not a footer contact sheet.
      decorations.push({ ...rect(70, 49, 30, 20), note: 0, noteType: "caption" });
      regions([rect(70, 0, 30, 44), rect(0, 77, 37, 23), rect(41, 77, 23, 23), rect(70, 76, 30, 24)], { cluster: true });
    } else if (id === "mosaic") {
      return { slots: subdivide([
        rect(0, 0, 61, 41, "secondary", { protected: true }),
        rect(62, 0, 38, 58, "secondary", { protected: true }),
        rect(0, 42, 30, 58), rect(31, 42, 30, 58), rect(62, 59, 38, 41),
      ], count, aspect, 0.8), decorations };
    } else if (id === "botanical") {
      add(rect(29, 0, 42, 31, "secondary"), rect(29, 35, 42, 30, "secondary"), rect(29, 69, 42, 31, "secondary"));
      regions([rect(0, 0, 24, 72), rect(76, 28, 24, 72)], { gap: 2.5, role: "detail" });
      decorations.push({ ...rect(0, 78, 24, 22), note: 0, noteType: "caption" }, { ...rect(76, 0, 24, 22), note: 1, noteType: "caption" });
    } else if (id === "chapters") {
      const counts = splitCounts(count, [1, 1, 1]);
      let sequence = 0;
      counts.forEach((n, i) => {
        const chapter = wide ? rect(i * 34, 0, 32, 100) : rect(0, i * 34, 100, 32);
        const start = sequence;
        const labelH = wide ? 8 : 4.6;
        decorations.push({ ...rect(wide ? chapter.x : 0, wide ? 0 : chapter.y, wide ? 32 : 100, labelH), note: 0, noteType: "chapter", start, count: n, chapter: i + 1, timeRange: captureRange(sequenceTimes.slice(start, start + n)) });
        const first = wide ? rect(chapter.x, labelH + 1, 32, 45, "sequence") : rect(0, chapter.y + labelH, 42, 32 - labelH, "sequence");
        const tail = wide ? rect(chapter.x, labelH + 49, 32, 42) : rect(45, chapter.y + labelH, 55, 32 - labelH);
        const rest = pack(tail, n - 1, aspect, { role: "sequence" });
        const anchor = Math.max(0, sequenceRoles.slice(start, start + n).findIndex((role) => role === "hero" || role === "secondary"));
        const chapterSlots = rest; chapterSlots.splice(anchor, 0, first);
        chapterSlots.forEach((r) => { r.role = sequenceRoles[sequence] || "sequence"; r.sequence = sequence++; r.chapter = i + 1; }); add(...chapterSlots);
      });
    }
    return { slots, decorations };
  }

  // Minimum-cost bijection (Hungarian algorithm). Cropping and prominence are
  // solved together, instead of greedily spending the best-fitting photo first.
  function assignment(costs) {
    const n = costs.length;
    const u = Array(n + 1).fill(0), v = Array(n + 1).fill(0), p = Array(n + 1).fill(0), way = Array(n + 1).fill(0);
    for (let i = 1; i <= n; i++) {
      p[0] = i; let j0 = 0;
      const min = Array(n + 1).fill(Infinity), used = Array(n + 1).fill(false);
      do {
        used[j0] = true; const i0 = p[j0]; let delta = Infinity, j1 = 0;
        for (let j = 1; j <= n; j++) if (!used[j]) {
          const cost = costs[i0 - 1][j - 1] - u[i0] - v[j];
          if (cost < min[j]) { min[j] = cost; way[j] = j0; }
          if (min[j] < delta) { delta = min[j]; j1 = j; }
        }
        for (let j = 0; j <= n; j++) if (used[j]) { u[p[j]] += delta; v[j] -= delta; } else min[j] -= delta;
        j0 = j1;
      } while (p[j0] !== 0);
      do { const j1 = way[j0]; p[j0] = p[j1]; j0 = j1; } while (j0 !== 0);
    }
    const out = Array(n); for (let j = 1; j <= n; j++) out[p[j] - 1] = j - 1;
    return out;
  }

  function cropRetention(photo, slot) { return Math.min(photo.aspect / (slot.w / slot.h), (slot.w / slot.h) / photo.aspect); }

  function cropPlan(photo, slot) {
    const target = slot.w / slot.h;
    const w = Math.min(1, target / photo.aspect), h = Math.min(1, photo.aspect / target);
    const boxes = photo.protectedBoxes;
    const centre = boxes.length ? {
      x:(Math.min(...boxes.map(b=>b.left))+Math.max(...boxes.map(b=>b.right)))/2,
      y:(Math.min(...boxes.map(b=>b.top))+Math.max(...boxes.map(b=>b.bottom)))/2,
    } : photo.focus;
    const x = clamp(centre.x,w/2,1-w/2), y = clamp(centre.y,h/2,1-h/2);
    const bounds = {left:x-w/2,top:y-h/2,right:x+w/2,bottom:y+h/2};
    const losses = boxes.map(b=>1-Math.max(0,Math.min(b.right,bounds.right)-Math.max(b.left,bounds.left))*Math.max(0,Math.min(b.bottom,bounds.bottom)-Math.max(b.top,bounds.top))/((b.right-b.left)*(b.bottom-b.top)));
    return {focus:{x,y},bounds,retained:w*h,protectedLoss:Math.max(0,...losses),atRisk:losses.filter(v=>v>0.001).length};
  }

  function affinity(photo, slot, prominence) {
    const crop = cropPlan(photo,slot), ratio = slot.w / slot.h;
    const resolution = photo.dimensionsKnown ? clamp(Math.sqrt(photo.width*photo.height)/4000,0,1) : 0.5;
    const preference = photo.preference + photo.quality*0.35 + resolution*0.25;
    const axisMismatch = (ratio>1.4 && photo.aspect<0.9) || (ratio<0.75 && photo.aspect>1.2);
    const subjectPenalty = photo.subjectKind === "tall" ? Math.max(0,ratio-0.8)*2
      : photo.subjectKind === "wide" ? Math.max(0,1.4-ratio)*2
      : photo.subjectKind === "people" && photo.aspect<0.95 ? Math.max(0,ratio-1.15)*3 : 0;
    const semanticFit = photo.semanticRole === slot.role ? 1.7 : photo.semanticRole === "hero" && slot.role === "secondary" ? 0.7 : 0;
    return (1-crop.retained)*(4+prominence*(photo.groupPortrait?20:photo.people?13:6))
      + crop.protectedLoss*100 + (axisMismatch?prominence*2.5:0) + subjectPenalty*prominence
      - prominence*(preference+semanticFit) + photo.index*0.00001;
  }

  function assignPhotos(photos, slots, family, overrides) {
    const heroes = overrides.heroIds || [], secondary = overrides.subheroIds || [];
    const chosen = [...heroes, ...secondary].map(String);
    if (new Set(chosen).size !== chosen.length || chosen.some((id) => !photos.some((p) => p.asset_id === id))) throw new Error("Hero choices must be distinct photos from the current source.");
    if (chosen.length > 6) throw new Error("Choose up to six prominent photos.");
    if (family.chronological) {
      const chronological = [...photos].sort((a, b) => (a.time || "~").localeCompare(b.time || "~") || a.index - b.index);
      return slots.map((slot, i) => {
        if (heroes.includes(chronological[i].asset_id)) slot.role = "hero";
        else if (secondary.includes(chronological[i].asset_id)) slot.role = "secondary";
        return chronological[i];
      });
    }
    const byArea = slots.map((slot, i) => ({ slot, i })).sort((a, b) => area(b.slot) - area(a.slot) || a.i - b.i);
    const largest = Math.max(...slots.map(area));
    const forced = new Map();
    if (chosen.length) {
      // Pick the best compatible prominent positions jointly. The first hero
      // is no longer forced into the largest (possibly panoramic) frame.
      const candidates = byArea.filter(({slot},i)=>i<chosen.length || area(slot)>=largest*0.3).slice(0,Math.max(chosen.length,6));
      const costs = candidates.map((_,i)=>candidates.map(({slot})=>i<chosen.length
        ? affinity(photos.find(p=>p.asset_id===chosen[i]),slot,1) + (1-area(slot)/largest)*2.5 : 0));
      const matched = assignment(costs);
      chosen.forEach((id,i)=>{const target=candidates[matched[i]];forced.set(target.i,id);target.slot.role=i<heroes.length?"hero":"secondary";});
    }
    if (chosen.length) slots.forEach((slot, i) => { if (!forced.has(i) && ["hero", "secondary"].includes(slot.role)) slot.role = "supporting"; });
    const costs = slots.map((slot, i) => photos.map((photo) => {
      if (forced.has(i)) return forced.get(i) === photo.asset_id ? -100 : 10000;
      if (chosen.includes(photo.asset_id)) return 10000;
      const prominence = area(slot) / largest;
      const people = family.id === "family" ? Math.min(photo.faceCount, 3) * 0.15 : 0;
      return affinity(photo,slot,prominence) - prominence*people;
    }));
    return assignment(costs).map((i) => photos[i]);
  }

  function resolvePage(page = {}) {
    const preset = presets.find((p) => p.id === (page.preset_id || page.id)) || presets.find((p) => p.id === "a4-portrait");
    return {
      type: page.type === "spread" ? "spread" : "single", preset_id: preset.id,
      width_mm: clamp(number(page.width_mm, preset.width), 80, 600), height_mm: clamp(number(page.height_mm, preset.height), 80, 600),
      bleed_mm: clamp(number(page.bleed_mm, 3), 0, 20), safe_margin_mm: clamp(number(page.safe_margin_mm, 8), 4, 30),
      gutter_mm: clamp(number(page.gutter_mm, 4), 0, 20), dpi: clamp(Math.round(number(page.dpi, 300)), 72, 1200),
      background: "#f5f2ed",
    };
  }

  function build({ familyId = "kew", photos: inputs, page: pageInput, heroIds = [], subheroIds = [], title = "Our days together", subtitle = "", caption = "", semantics = {} }) {
    const family = families.find((f) => f.id === familyId);
    if (!family) throw new Error("Unknown template family.");
    if (!Array.isArray(inputs) || inputs.length < 10 || inputs.length > 60) throw new Error("Choose a section with 10–60 photos. Larger collections can be arranged into sections.");
    const semanticRoles = roleMap(semantics);
    const photos = inputs.map(photoInfo).map((p) => ({ ...p, semanticRole: semanticRoles.get(p.asset_id) || p.role }));
    if (photos.some((p) => !p.asset_id) || new Set(photos.map((p) => p.asset_id)).size !== photos.length) throw new Error("Every source photo needs a distinct asset id.");
    const page = resolvePage(pageInput); page.background = family.paper;
    page.orientation = page.width_mm === page.height_mm ? "square" : page.width_mm > page.height_mm ? "landscape" : "portrait";
    const panels = page.type === "spread" ? 2 : 1;
    const totalWidth = page.width_mm * panels, height = page.height_mm;
    const margin = Math.max(page.safe_margin_mm + 3, Math.min(page.width_mm, height) * 0.045);
    const footer = family.footer;
    const titleHeight = 14, contextHeight = subtitle ? 7 : 0;
    const headerReserve = footer ? 0 : titleHeight + contextHeight + 7;
    const inlineNotes = ["magazine", "journal", "gallery", "botanical"].includes(family.id);
    const footerReserve = footer ? titleHeight + contextHeight + (caption ? 12 : 0) + 9 : caption && !inlineNotes ? 16 : 5;
    const photoY = margin + headerReserve, photoHeight = height - margin * 2 - headerReserve - footerReserve;
    const slots = [], decorative = [], panelCounts = splitCounts(photos.length, Array(panels).fill(1));
    const ordered = [...photos].sort((a, b) => (a.time || "~").localeCompare(b.time || "~") || a.index - b.index);
    const sequenceRoles = ordered.map((p) => heroIds.includes(p.asset_id) ? "hero" : subheroIds.includes(p.asset_id) ? "secondary" : p.semanticRole);
    let sequenceOffset = 0;
    panelCounts.forEach((count, panel) => {
      // A spread remains two designed pages separated by a real binding gutter.
      const inset = panels > 1 ? page.gutter_mm / 2 : 0;
      const x = panel * page.width_mm + margin + (panel ? inset : 0);
      const w = page.width_mm - margin * 2 - inset;
      const panelOrdered = ordered.slice(sequenceOffset, sequenceOffset + count);
      const layout = layoutFamily(family, count, w / photoHeight, sequenceRoles.slice(sequenceOffset, sequenceOffset + count), panelOrdered.map(p => p.time));
      sequenceOffset += count;
      const scale = (r) => ({ ...r, x: x + r.x / 100 * w, y: photoY + r.y / 100 * photoHeight, w: r.w / 100 * w, h: r.h / 100 * photoHeight, panel });
      slots.push(...layout.slots.map(scale)); decorative.push(...layout.decorations.map(scale));
    });
    if (slots.length !== photos.length) throw new Error(`Template produced ${slots.length} positions for ${photos.length} photos.`);
    const assigned = assignPhotos(photos, slots, family, { heroIds, subheroIds });
    const photoElements = slots.map((slot, i) => {
      const photo = assigned[i];
      const crop = cropPlan(photo,slot);
      return {
        id: `photo-${i + 1}`, type: "photo", asset_id: photo.asset_id, role: slot.role,
        x_mm: slot.x, y_mm: slot.y, width_mm: slot.w, height_mm: slot.h,
        rotation_deg: slot.rotation || 0, z_index: 20 + i,
        allow_photo_overlap: Boolean(family.overlap || slot.rotation),
        image: { focus_x: crop.focus.x, focus_y: crop.focus.y, zoom: 1 },
        mask: { type: photo.protectedBoxes.length && ["circle","ellipse"].includes(slot.mask) ? "rectangle" : slot.mask || "rectangle" },
        border: { width_mm: family.border || 0, color: "#ffffff", opacity: 1 },
        shadow: family.shadow ? { color: "#000000", opacity: 0.13, blur_mm: 1.5, offset_x_mm: 0.5, offset_y_mm: 0.7 } : {},
      };
    });
    const text = (id, content, x, y, w, h, role, style = {}) => ({
      id, type: "text", role, content: String(content).slice(0, 2000), x_mm: x, y_mm: y, width_mm: w, height_mm: h, rotation_deg: 0, z_index: 150,
      text_style: { font_id: "serif", font_size_pt: 12, weight: "normal", alignment: "left", line_height: 1.05, letter_spacing: 0, text_fit: "wrap_and_shrink", color: family.ink, ...style },
    });
    const titleY = footer ? height - margin - footerReserve + 7 : margin;
    const headerStyle = {
      magazine: { alignment: "left", titleSize: 30, subtitleSize: 12 },
      diptych: { alignment: "center", titleSize: 25, subtitleSize: 12 },
      film: { alignment: "left", titleSize: 24, subtitleSize: 10 },
      architecture: { alignment: "left", titleSize: 28, subtitleSize: 12 },
      journal: { alignment: "left", titleSize: 25, subtitleSize: 12 },
      family: { alignment: "center", titleSize: 28, subtitleSize: 12 },
      horizon: { alignment: "left", titleSize: 27, subtitleSize: 12 },
      gallery: { alignment: "left", titleSize: 26, subtitleSize: 12 },
      botanical: { alignment: "left", titleSize: 24, subtitleSize: 12 },
      chapters: { alignment: "left", titleSize: 26, subtitleSize: 12 },
    }[family.id] || { alignment: "left", titleSize: 27, subtitleSize: 12 };
    const titleInset = ["diptych", "family"].includes(family.id) ? margin + (page.width_mm - margin * 2) * 0.08 : margin;
    const titleWidth = page.width_mm - margin * 2 - (titleInset - margin);
    const texts = [text("title", title, titleInset, titleY, titleWidth, titleHeight, "title", { font_id: family.font, font_size_pt: headerStyle.titleSize, alignment: headerStyle.alignment, weight: family.font === "script" ? "normal" : "bold" })];
    if (subtitle) texts.push(text("subtitle", subtitle, titleInset, titleY + titleHeight + 1, titleWidth, contextHeight, "subtitle", { font_id: "sans", font_size_pt: headerStyle.subtitleSize, alignment: headerStyle.alignment }));
    if (caption && !inlineNotes) texts.push(text("caption", caption, margin, height - margin - 9, totalWidth - margin * 2, 9, "caption", { font_size_pt: 11, italic: true }));
    const notes = decorative.filter((r) => r.note !== undefined);
    const splitCaption = (value, count) => {
      const source = String(value || "").trim();
      if (!source || count <= 0) return [];
      const chunks = source.split(/\n\s*\n/).flatMap(paragraph => paragraph.match(/[^。！？.!?]+[。！？.!?]?/g)?.map(part=>part.trim()).filter(Boolean) || [paragraph.trim()]).filter(Boolean);
      if (chunks.length <= count) return chunks;
      const result = Array(count).fill("");
      chunks.forEach((part,index)=>{ const target=Math.min(count-1,Math.floor(index*count/chunks.length)); result[target]+=(result[target]?" ":"")+part; });
      if (result.some(part=>!part)) {
        const words=source.split(/\s+/), balanced=Array(count).fill("");
        words.forEach((word,index)=>{const target=Math.min(count-1,Math.floor(index*count/words.length));balanced[target]+=(balanced[target]?" ":"")+word;});
        return balanced.filter(Boolean);
      }
      return result;
    };
    const wrapAtWordBoundaries = (value, maxCharacters) => {
      const paragraphs = String(value).split("\n");
      return paragraphs.map(paragraph => {
        const words = paragraph.trim().split(/\s+/).filter(Boolean), lines = [];
        let line = "";
        for (const word of words) {
          if (line && line.length + 1 + word.length > maxCharacters) { lines.push(line); line = word; }
          else line += (line ? " " : "") + word;
        }
        if (line) lines.push(line);
        return lines.join("\n");
      }).join("\n");
    };
    let captionIndex = 0;
    const captionSlots = notes.filter(r=>r.noteType === "caption").length;
    const captionParts = splitCaption(caption, captionSlots);
    notes.forEach((r, i) => {
      let content = "";
      if (r.noteType === "chapter") content = `${String(r.chapter).padStart(2,"0")} · ${String(r.start+1).padStart(2,"0")}–${String(r.start+r.count).padStart(2,"0")}${r.timeRange ? ` · ${r.timeRange}` : ""}`;
      else if (r.noteType === "film") content = `${String(r.start+1).padStart(2,"0")}–${String(r.start+r.count).padStart(2,"0")}${r.timeRange ? ` · ${r.timeRange}` : ""}`;
      else content = captionParts[captionIndex++] || "";
      if (!content) return;
      const sequenceLabel = ["chapter", "film"].includes(r.noteType);
      if (!sequenceLabel) content = wrapAtWordBoundaries(content, Math.max(12, Math.floor(r.w / 2.3)));
      texts.push(text(`fieldnote-${i}`, content, r.x, r.y, r.w, r.h, "caption", { font_size_pt: sequenceLabel ? 8 : 11, italic: !sequenceLabel, weight: sequenceLabel ? "bold" : "normal", color: family.ink }));
    });
    const elements = [
      { id: "paper", type: "rectangle", role: "background", locked: true, x_mm: 0, y_mm: 0, width_mm: totalWidth, height_mm: height, fill: family.paper, z_index: 0 },
      ...decorative.filter((r) => r.note === undefined).map((r, i) => ({ id: `decoration-${i}`, type: "rectangle", role: "accent", x_mm: r.x, y_mm: r.y, width_mm: r.w, height_mm: r.h, fill: r.fill, z_index: 2 })),
      ...photoElements, ...texts,
    ];
    const diagnostics = {
      sourceCount: photos.length, placedCount: photoElements.length,
      heroes: photoElements.filter((p) => p.role === "hero").map((p) => p.asset_id),
      subheroes: photoElements.filter((p) => p.role === "secondary").map((p) => p.asset_id),
      cropWarnings: assigned.map((p, i) => ({ asset_id: p.asset_id, retained: cropRetention(p, slots[i]), role: slots[i].role })).filter((p) => p.retained < 0.55),
      safetyWarnings: assigned.map((p,i)=>({asset_id:p.asset_id,atRisk:cropPlan(p,slots[i]).atRisk,role:slots[i].role})).filter(p=>p.atRisk>0),
      faceMetadataCount: photos.filter(p=>p.faces.length).length,
      smallestEdgeMm: Math.min(...slots.map((s) => Math.min(s.w, s.h))),
      estimatedCoverage: slots.reduce((sum, s) => sum + area(s), 0) / (totalWidth * height),
      unknownDimensions: photos.filter((p) => !p.dimensionsKnown).length,
      assignmentBasis: "Aspect ratio, crop retention, resolution, ratings, optional quality/face metadata; chronological families use capture order. This is a fit recommendation, not an aesthetic judgement.",
    };
    return {
      spec: { format: "CollageDesignSpec", schema_version: 2, package_id: `fixture:template-${family.id}-v${VERSION}`, style: family.name, style_intent: family.description, mode: "from_scratch", page_spec: page,
        assets: photos.map((p, i) => ({ label: `A${String(i + 1).padStart(2, "0")}`, asset_id: p.asset_id, filename: p.filename || p.asset_id })),
        alternatives: [{ id: `${family.id}-v${VERSION}`, name: family.name, reason: `${family.description} All ${photos.length} photos appear once.`, elements }],
      }, diagnostics, family,
    };
  }

  function roleMap(semantics = {}) {
    const roles = new Map();
    const ids = (value) => (Array.isArray(value) ? value : value ? [value] : []).map(String);
    for (const [key, role] of [["details", "detail"], ["supporting", "supporting"], ["subheroes", "secondary"], ["hero_asset_ids", "hero"], ["dominant_hero", "hero"]]) {
      ids(semantics[key]).forEach((id) => roles.set(id, role));
    }
    return roles;
  }

  function recommend(inputs, page, semantics = {}) {
    if (!inputs?.length) return [];
    const infos = inputs.map(photoInfo), portrait = infos.filter((p) => p.aspect < 0.9).length / infos.length;
    const dated = infos.filter((p) => p.time).length / infos.length;
    return families.map((f) => {
      let score = 0.5, reason = "Balanced for a mixed collection.";
      if (["architecture", "family"].includes(f.id)) { score += portrait * 0.7; reason = `${Math.round(portrait * 100)}% portrait photos suit tall, generous frames.`; }
      if (f.id === "horizon") { score += (1 - portrait) * 0.65; reason = "Landscape photos suit its wide establishing image."; }
      if (f.chronological) { score += dated * 0.4; reason = dated ? "Capture times can tell the story in order." : "Keeps the source order as a visual sequence."; }
      if (f.id === "kew") { score += 0.38 - Math.abs(portrait - 0.4) * 0.2; reason = "Mixed-size cards give travel and family details a connected rhythm."; }
      if (f.id === "mosaic") { score += Math.min(infos.length / 50, 0.55); reason = "Its interlocking regions adapt well to a larger collection."; }
      if (f.id === "gallery" && infos.length > 24) { score -= 0.25; reason = "Airy gallery; a large collection will make the studies small."; }
      const compatible = semanticFamilies[semantics.layout_archetype] || [];
      const rank = compatible.indexOf(f.id);
      if (rank >= 0) { score += 3 - rank * 0.4; reason = `${semantics.layout_archetype.replaceAll("_", " ")} → ${f.description}`; }
      const roles = [...roleMap(semantics).values()];
      if (roles.filter((role) => role === "hero").length > 1 && f.id === "diptych") score += 0.45;
      if (roles.filter((role) => role === "detail").length > inputs.length / 3 && ["mosaic", "botanical"].includes(f.id)) score += 0.4;
      return { familyId: f.id, score, reason };
    }).sort((a, b) => b.score - a.score);
  }
  const api = Object.freeze({ VERSION, presets, families, semanticFamilies, build, recommend, resolvePage });
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CollageTemplateLibrary = api;
})(typeof window === "undefined" ? globalThis : window);
