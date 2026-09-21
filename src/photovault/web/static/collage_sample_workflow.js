/*
 * Built-in sample workflow for the Fabric editor.
 *
 * The sample is deliberately generated from a template contract rather than
 * by slicing a 12-photo fixture.  A section's ordered membership is the
 * source of truth, the template declares its required photo count and page
 * size, and the role controls only affect prominence.  The final spec still
 * contains every section asset exactly once.
 */
(() => {
  const workflow = { topics: [], sections: [], assets: [], topicId: "", sectionId: "" };
  state.sampleWorkflow = workflow;

  const sizes = [
    { id: "square", label: "Square", width: 300, height: 300, orientation: "square", preset: "large-square" },
    { id: "a4-portrait", label: "A4 portrait", width: 210, height: 297, orientation: "portrait", preset: "a4-portrait" },
    { id: "a4-landscape", label: "A4 landscape", width: 297, height: 210, orientation: "landscape", preset: "a4-landscape" },
  ];
  const sampleTemplates = [
    { id: "kew-square-12", label: "Kew Gardens · Square · 12 photos", count: 12, size: sizes[0] },
    ...sizes.slice(1).flatMap((size) => Array.from({ length: 11 }, (_, index) => {
      const count = index + 10;
      return { id: `kew-${size.id}-${count}`, label: `Kew Gardens · ${size.label} · ${count} photos`, count, size };
    })),
  ];

  const templateById = (id) => sampleTemplates.find((item) => item.id === id) || sampleTemplates[0];
  const node = (id) => document.getElementById(id);
  const workflowStatus = (message, error = false) => {
    const target = node("sample-workflow-status");
    if (target) {
      target.textContent = message;
      target.style.color = error ? "#9b3d2b" : "";
    }
  };
  const option = (value, label, selected = false) => `<option value="${esc(value)}"${selected ? " selected" : ""}>${esc(label)}</option>`;

  function renderTemplateOptions() {
    const select = node("sample-template");
    if (!select) return;
    select.innerHTML = sizes.map((size) => {
      const items = sampleTemplates.filter((template) => template.size.id === size.id);
      return `<optgroup label="${esc(size.label)}">${items.map((template) => option(template.id, template.label)).join("")}</optgroup>`;
    }).join("");
    select.value = "kew-square-12";
    renderMatchingTemplates();
  }

  function selectedTemplate() {
    return templateById(node("sample-template")?.value || "kew-square-12");
  }

  function renderMatchingTemplates() {
    const select = node("sample-template-match");
    if (!select) return;
    const count = workflow.assets.length;
    const matching = sampleTemplates.filter((template) => template.count === count);
    select.innerHTML = matching.length
      ? matching.map((template) => option(template.id, `${template.size.label} · ${template.count} photos`)).join("")
      : option("", `No built-in template for ${count} photos`);
    const current = selectedTemplate();
    if (matching.some((template) => template.id === current.id)) select.value = current.id;
    else if (matching.length) select.value = matching[0].id;
    select.disabled = !matching.length;
    updateWorkflowState();
  }

  function selectedRoleIds() {
    const primary = String(node("sample-hero")?.value || "");
    const extras = [...(node("sample-subheroes")?.selectedOptions || [])].map((item) => String(item.value));
    const mode = node("sample-hero-mode")?.value || "single";
    if (mode === "single") return { heroIds: primary ? [primary] : [], subheroIds: [] };
    if (mode === "hero-subhero") return { heroIds: primary ? [primary] : [], subheroIds: extras.slice(0, 1) };
    return { heroIds: primary ? [primary, ...extras.slice(0, 3)] : extras.slice(0, 3), subheroIds: [] };
  }

  function renderRoleOptions() {
    const hero = node("sample-hero");
    const extras = node("sample-subheroes");
    const ids = workflow.assets.map((item) => String(item.asset_id));
    if (!hero || !extras) return;
    hero.innerHTML = ids.length ? workflow.assets.map((item, index) => option(item.asset_id, `${String(index + 1).padStart(2, "0")} · ${item.filename || item.asset_id}`, index === 0)).join("") : option("", "Choose a section first…");
    const primary = hero.value;
    extras.innerHTML = workflow.assets.filter((item) => String(item.asset_id) !== primary).map((item) => option(item.asset_id, item.filename || item.asset_id)).join("");
    extras.disabled = !ids.length;
    if (ids.length > 1) {
      const firstExtra = extras.options[0];
      if (firstExtra) firstExtra.selected = true;
    }
    updateRoleVisibility();
  }

  function refreshSubheroOptions() {
    const hero = node("sample-hero");
    const extras = node("sample-subheroes");
    if (!hero || !extras) return;
    const primary = String(hero.value || "");
    const previouslySelected = new Set([...extras.selectedOptions].map((item) => String(item.value)));
    extras.innerHTML = workflow.assets.filter((item) => String(item.asset_id) !== primary).map((item) => {
      const id = String(item.asset_id);
      return option(id, item.filename || id, previouslySelected.has(id));
    }).join("");
    extras.disabled = !workflow.assets.length;
    updateRoleVisibility();
  }

  function updateRoleVisibility() {
    const mode = node("sample-hero-mode")?.value || "single";
    const wrap = node("sample-subhero-wrap");
    if (wrap) wrap.hidden = mode === "single";
    const extras = node("sample-subheroes");
    if (extras) extras.title = mode === "multiple" ? "Choose up to three additional hero photos" : "Choose one sub-hero photo";
    updateWorkflowState();
  }

  function updateWorkflowState() {
    const template = selectedTemplate();
    const sectionCount = workflow.assets.length;
    const hasSection = Boolean(workflow.sectionId && sectionCount);
    const match = sectionCount === template.count;
    const roleIds = selectedRoleIds();
    const mode = node("sample-hero-mode")?.value || "single";
    const enoughRoles = roleIds.heroIds.length >= 1 && (mode === "single" || roleIds.subheroIds.length >= 1 || mode === "multiple" && roleIds.heroIds.length >= 2);
    const button = node("generate-from-section");
    if (button) button.disabled = !(hasSection && match && enoughRoles);
    const expected = hasSection ? `${sectionCount} photos in section · ${template.size.label} template expects ${template.count}` : "Choose a topic and section to begin.";
    workflowStatus(match && hasSection ? `${expected} · ready to generate.` : expected, Boolean(hasSection && !match));
  }

  async function loadTopics() {
    const data = await api("/api/topics");
    workflow.topics = data.topics || [];
    const select = node("sample-topic");
    if (!select) return;
    select.innerHTML = option("", "Choose a topic…") + workflow.topics.map((topic) => option(topic.id, `${topic.name} · ${topic.item_count} photos`)).join("");
    const preferred = state.doc?.metadata?.topic_id;
    if (preferred && workflow.topics.some((topic) => topic.id === preferred)) select.value = preferred;
    if (select.value) await loadSections(select.value);
    else updateWorkflowState();
  }

  async function loadSections(topicId) {
    workflow.topicId = topicId || "";
    workflow.sectionId = "";
    workflow.assets = [];
    const select = node("sample-section");
    if (!select) return;
    if (!topicId) {
      select.disabled = true;
      select.innerHTML = option("", "Choose a topic first…");
      renderRoleOptions(); renderMatchingTemplates(); return;
    }
    const data = await api(`/api/topics/${encodeURIComponent(topicId)}/sections`);
    workflow.sections = data.sections || [];
    select.innerHTML = option("", "Choose a section…") + workflow.sections.map((section) => option(section.id, `${section.title} · ${section.item_count} photos`)).join("");
    select.disabled = !workflow.sections.length;
    renderRoleOptions(); renderMatchingTemplates();
  }

  async function loadSectionAssets(sectionId) {
    workflow.sectionId = sectionId || "";
    workflow.assets = [];
    if (!sectionId) { renderRoleOptions(); renderMatchingTemplates(); return; }
    const idData = await api(`/api/sections/${encodeURIComponent(sectionId)}/assets`);
    const ids = (idData.asset_ids || []).map(String);
    if (!ids.length) { renderRoleOptions(); renderMatchingTemplates(); return; }
    const data = await api(`/api/collage/photos?${ids.map((id) => `asset_id=${encodeURIComponent(id)}`).join("&")}`);
    const byId = new Map((data.items || []).map((item) => [String(item.asset_id), item]));
    workflow.assets = ids.map((id) => byId.get(id)).filter(Boolean);
    renderRoleOptions(); renderMatchingTemplates();
  }

  function pageSpecFor(template) {
    return {
      type: "single", width_mm: template.size.width, height_mm: template.size.height,
      orientation: template.size.orientation, bleed_mm: 3, safe_margin_mm: 8, gutter_mm: 4,
      dpi: 300, background: "#f5f2ed", preset_id: template.size.preset,
    };
  }

  function textElement(id, content, x, y, width, height, style, role, zIndex) {
    return { id, type: "text", role, content, x_mm: x, y_mm: y, width_mm: width, height_mm: height, rotation_deg: 0, text_style: style, z_index: zIndex };
  }

  function photoElement(label, role, x, y, width, height, zIndex, rotation = 0, mask = "rectangle") {
    return {
      id: `photo-${label.toLowerCase()}`, type: "photo", asset_id: label, role,
      x_mm: x, y_mm: y, width_mm: width, height_mm: height, rotation_deg: rotation,
      image: { focus_x: 0.5, focus_y: 0.48, zoom: 1 }, mask: { type: mask },
      border: { width_mm: 1.8, color: "#ffffff", opacity: 1 },
      shadow: { color: "#000000", opacity: 0.15, blur_mm: 2, offset_x_mm: 0.6, offset_y_mm: 1 }, z_index: zIndex,
    };
  }

  function weightedRow(y, height, weights, width, margin, gap) {
    const totalWeight = weights.reduce((sum, weight) => sum + weight, 0);
    const available = width - margin * 2 - gap * (weights.length - 1);
    let x = margin;
    return weights.map((weight) => {
      const item = { x, y, width: available * (weight / totalWeight), height };
      x += item.width + gap;
      return item;
    });
  }

  function editorialSlots(template, count, prominentCount) {
    const { width, height, orientation } = template.size;
    const margin = 12;
    const gap = 4;

    // This is the original Kew scrapbook rhythm: three large cards above a
    // loose row of smaller cards, with the title living in the quiet footer.
    // It deliberately keeps the same varied proportions instead of falling
    // back to a uniform contact sheet for the common 10–12 photo case.
    if (orientation === "square" && count <= 12) {
      return [
        { x: 10, y: 8, width: 94, height: 94, rotation: 4, mask: "rectangle" },
        { x: 97, y: 18, width: 89, height: 88, rotation: -3, mask: "rectangle" },
        { x: 183, y: 19, width: 69, height: 80, rotation: 1, mask: "rectangle" },
        { x: 9, y: 102, width: 93, height: 88, rotation: 1, mask: "rectangle" },
        { x: 102, y: 101, width: 117, height: 95, rotation: 1, mask: "rounded" },
        { x: 217, y: 85, width: 76, height: 56, rotation: -4, mask: "rectangle" },
        { x: 216, y: 139, width: 76, height: 57, rotation: 4, mask: "rectangle" },
        { x: 14, y: 184, width: 51, height: 53, rotation: -2, mask: "circle" },
        { x: 64, y: 188, width: 57, height: 52, rotation: 4, mask: "rectangle" },
        { x: 122, y: 187, width: 55, height: 53, rotation: -2, mask: "rectangle" },
        { x: 176, y: 195, width: 57, height: 52, rotation: 5, mask: "ellipse" },
        { x: 234, y: 195, width: 56, height: 53, rotation: -3, mask: "rectangle" },
      ].slice(0, count);
    }

    // Larger sets still use a scrapbook composition: a weighted lead row,
    // then alternating weighted rows. The row heights adapt to the number of
    // photos, so every asset fits without being reduced to identical tiles.
    const leadCount = Math.max(2, Math.min(3, prominentCount || 2));
    const leadWeights = leadCount === 2 ? [1.55, 1] : [1.4, 0.95, 1];
    const slots = weightedRow(orientation === "portrait" ? 39 : 33, orientation === "landscape" ? 60 : 72, leadWeights, width, margin, gap)
      .map((slot, index) => ({ ...slot, rotation: index % 2 ? -2 : 2, mask: index === 0 ? "rounded" : index === 2 ? "ellipse" : "rectangle" }));
    const remainder = Math.max(0, count - leadCount);
    const columns = orientation === "landscape" ? 5 : 4;
    const rows = Math.max(1, Math.ceil(remainder / columns));
    const gridTop = slots[0].y + slots[0].height + gap + 3;
    const footer = orientation === "landscape" ? 22 : 27;
    const gridHeight = Math.max(25, height - gridTop - footer);
    const rowHeight = (gridHeight - gap * (rows - 1)) / rows;
    const rowPatterns = [[1.35, 0.9, 1.15, 0.8, 1], [0.85, 1.25, 0.95, 1.2, 0.8], [1.1, 0.8, 1.35, 0.9, 1.05], [0.9, 1.15, 0.85, 1.3, 0.95]];
    let remaining = remainder;
    for (let row = 0; row < rows; row += 1) {
      const rowCount = Math.min(columns, remaining);
      const weights = rowPatterns[row % rowPatterns.length].slice(0, rowCount);
      weightedRow(gridTop + row * (rowHeight + gap), rowHeight, weights, width, margin, gap)
        .forEach((slot, index) => slots.push({
          ...slot,
          rotation: (row + index) % 3 === 0 ? -2 : (row + index) % 3 === 1 ? 1 : 0,
          mask: (row * columns + index) % 7 === 0 ? "rounded" : (row * columns + index) % 11 === 0 ? "ellipse" : "rectangle",
        }));
      remaining -= rowCount;
    }
    return slots.slice(0, count);
  }

  function buildTemplateSpec(template, assetItems, roleIds, section, topic) {
    const page = pageSpecFor(template);
    const assets = assetItems.map((item, index) => ({ label: `A${String(index + 1).padStart(2, "0")}`, asset_id: String(item.asset_id), filename: item.filename || String(item.asset_id) }));
    const labelByAsset = new Map(assets.map((item) => [item.asset_id, item.label]));
    const heroIds = [...new Set(roleIds.heroIds)].filter((id) => labelByAsset.has(id));
    const subheroIds = [...new Set(roleIds.subheroIds)].filter((id) => labelByAsset.has(id) && !heroIds.includes(id));
    const width = page.width_mm, height = page.height_mm;
    const selectedTopIds = [...heroIds, ...subheroIds];
    const availableIds = assetItems.map((item) => String(item.asset_id)).filter((id) => !selectedTopIds.includes(id));
    // Even when the user chooses one hero, promote one or two neighbours into
    // the editorial lead row. They remain supporting photos, so all role
    // choices are honoured without making the page look like a plain grid.
    const prominentIds = [...selectedTopIds, ...availableIds.slice(0, Math.max(0, 2 - selectedTopIds.length))].slice(0, 3);
    const orderedIds = [...prominentIds, ...availableIds.filter((id) => !prominentIds.includes(id))];
    const slots = editorialSlots(template, template.size.orientation === "square" && assets.length <= 12 ? 12 : orderedIds.length, prominentIds.length);
    const squareSlotOrder = [4, 0, 1, 3, 2, 5, 6, 7, 8, 9, 10, 11];
    const visualSlots = template.size.orientation === "square" && assets.length <= 12
      ? squareSlotOrder.slice(0, orderedIds.length).map((index) => slots[index])
      : slots;
    const topRole = (assetId) => heroIds.includes(assetId) ? "hero" : subheroIds.includes(assetId) ? "secondary" : "supporting";
    const photos = orderedIds.map((assetId, index) => {
      const slot = visualSlots[index];
      const role = topRole(assetId);
      return photoElement(labelByAsset.get(assetId), role, slot.x, slot.y, slot.width, slot.height, 20 + index * 10, slot.rotation, slot.mask);
    });
    const topicName = topic?.name || "Photo story";
    const sectionTitle = section?.title || "Kew Gardens";
    const caption = section?.description || (section ? `${sectionTitle} · ${assets.length} photographs` : "A beautiful day with Mum.");
    const squarePoster = template.size.orientation === "square" && assets.length <= 12;
    const titleY = squarePoster ? 246 : 8;
    const contextY = squarePoster ? 275 : 25;
    const captionY = squarePoster ? 264 : height - 19;
    const taglineY = squarePoster ? 285 : height - 9;
    const titleStyle = { font_id: "script", font_size_pt: 30, weight: "normal", italic: false, alignment: "left", line_height: 1, letter_spacing: 0, text_fit: "shrink_to_fit", color: "#304637" };
    const smallStyle = { font_id: "serif", font_size_pt: 8, weight: "normal", italic: false, alignment: "left", line_height: 1, letter_spacing: 1, text_fit: "shrink_to_fit", color: "#304637" };
    const elements = [
      { id: "paper", type: "rectangle", role: "background", x_mm: 0, y_mm: 0, width_mm: width, height_mm: height, fill: "#f5f2ed", z_index: 0 },
      ...photos,
      textElement("title", sectionTitle, 14, titleY, squarePoster ? 183 : width - 28, squarePoster ? 28 : 16, { ...titleStyle, font_size_pt: squarePoster ? 44 : 30 }, "title", 120),
      textElement("context", topicName, squarePoster ? 21 : 14, contextY, width - 28, 7, smallStyle, "subtitle", 121),
      textElement("caption", caption, squarePoster ? Math.max(14, width - 48) : 14, captionY, squarePoster ? 34 : width - 28, squarePoster ? 16 : 11, { ...smallStyle, font_size_pt: 9, italic: true }, "caption", 122),
      textElement("tagline", `PHOTO STORY · ${assets.length} PHOTOS`, squarePoster ? 21 : 14, taglineY, width - 28, 5, { ...smallStyle, font_size_pt: 7, letter_spacing: 2 }, "metadata", 123),
    ];
    return {
      format: "CollageDesignSpec", schema_version: 2, package_id: `fixture:kew-gardens-${template.id}`,
      catalog_id: "photo-manager", style: "kew-gardens-editorial-scrapbook", style_intent: "A calm editorial garden scrapbook with a clear hero and a complete supporting contact sheet.", mode: "from_scratch",
      page_spec: page, assets, alternatives: [{ id: template.id, name: template.label, reason: `${assets.length} section photos · ${heroIds.length} hero${heroIds.length === 1 ? "" : "es"}${subheroIds.length ? ` · ${subheroIds.length} sub-hero` : ""} · every section photo is included exactly once.`, elements }],
    };
  }

  async function loadSelectedSample() {
    const template = selectedTemplate();
    const section = workflow.sections.find((item) => item.id === workflow.sectionId);
    const topic = workflow.topics.find((item) => item.id === workflow.topicId);
    if (section && workflow.assets.length) {
      if (workflow.assets.length !== template.count) {
        workflowStatus(`Cannot generate: this template expects ${template.count} photos but “${section.title}” has ${workflow.assets.length}. Choose the matching template.`, true);
        return;
      }
      const roles = selectedRoleIds();
      const spec = buildTemplateSpec(template, workflow.assets, roles, section, topic);
      await validateAiSpec(spec);
      return;
    }
    const currentAssets = [...new Set(elements().map(photoId).filter(Boolean))];
    if (currentAssets.length !== template.count) {
      status(`Open a section with exactly ${template.count} photo assets, or choose a matching topic section first.`);
      return;
    }
    if (template.id === "kew-square-12") {
      const response = await fetch("/examples/kew-gardens-ai-design-v2.json");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const sample = await response.json();
      sample.assets = (sample.assets || []).map((asset, index) => {
        const assetId = currentAssets[index]; const info = state.assetMap.get(String(assetId)) || {};
        return { ...asset, asset_id: assetId, filename: info.filename || `selected-image-${String(index + 1).padStart(2, "0")}.jpg` };
      });
      await validateAiSpec(sample);
      return;
    }
    const items = currentAssets.map((id) => state.assetMap.get(String(id)) || { asset_id: id, filename: id });
    await validateAiSpec(buildTemplateSpec(template, items, selectedRoleIds(), null, null));
  }

  async function initialise() {
    renderTemplateOptions();
    node("sample-topic")?.addEventListener("change", (event) => loadSections(event.target.value).catch((error) => workflowStatus(`Topic load failed: ${error.message}`, true)));
    node("sample-section")?.addEventListener("change", (event) => loadSectionAssets(event.target.value).catch((error) => workflowStatus(`Section load failed: ${error.message}`, true)));
    node("sample-template")?.addEventListener("change", () => { renderMatchingTemplates(); updateWorkflowState(); });
    node("sample-template-match")?.addEventListener("change", (event) => { if (event.target.value) { node("sample-template").value = event.target.value; updateWorkflowState(); } });
    node("sample-hero")?.addEventListener("change", () => { refreshSubheroOptions(); updateWorkflowState(); });
    node("sample-subheroes")?.addEventListener("change", updateWorkflowState);
    node("sample-hero-mode")?.addEventListener("change", updateRoleVisibility);
    node("generate-from-section")?.addEventListener("click", () => loadSelectedSample().catch((error) => workflowStatus(`Template generation failed: ${error.message}`, true)));
    node("load-sample")?.addEventListener("click", () => loadSelectedSample().catch((error) => status(`Sample design unavailable: ${error.message}`)));
    await loadTopics();
  }

  initialise().catch((error) => workflowStatus(`Template workflow unavailable: ${error.message}`, true));
})();
