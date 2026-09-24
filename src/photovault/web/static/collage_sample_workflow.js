/*
 * Built-in sample workflow for the Fabric editor.
 *
 * Existing source/import/save workflow; composition is delegated to the pure
 * template library. Section membership remains the source of truth. Every
 * section photo is included exactly once; original reference remains available.
 */
(() => {
  const library = window.CollageTemplateLibrary;
  const workflow = { topics: [], sections: [], assets: [], topicId: "", sectionId: "", request: 0, busy: false };
  state.sampleWorkflow = workflow;

  const sampleTemplates = [
    ...library.families.map((family) => ({ id: family.id, label: family.name, family })),
    { id: "kew-square-12", label: "Original Kew reference · 12 photos", count: 12 },
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
    select.innerHTML = sampleTemplates.map((template) => option(template.id, template.label)).join("");
    select.value = "kew";
    renderMatchingTemplates();
  }

  function selectedTemplate() {
    return templateById(node("sample-template")?.value || "kew-square-12");
  }

  function renderMatchingTemplates() {
    const select = node("sample-template-match");
    if (!select) return;
    const previous = select.value || state.doc?.page_spec?.preset_id || "a4-portrait";
    select.innerHTML = library.presets.map((preset) => option(preset.id, preset.label)).join("");
    select.value = library.presets.some((p) => p.id === previous) ? previous : "a4-portrait";
    select.disabled = selectedTemplate().id === "kew-square-12";
    updateWorkflowState();
  }

  function selectedRoleIds() {
    const primary = String(node("sample-hero")?.value || "");
    const extras = [...(node("sample-subheroes")?.selectedOptions || [])].map((item) => String(item.value));
    const mode = node("sample-hero-mode")?.value || "single";
    if (mode === "auto") return { heroIds: [], subheroIds: [] };
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
    if (wrap) wrap.hidden = mode === "single" || mode === "auto";
    if (node("sample-hero")) node("sample-hero").disabled = mode === "auto";
    const extras = node("sample-subheroes");
    if (extras) extras.title = mode === "multiple" ? "Choose up to three additional hero photos" : "Choose one sub-hero photo";
    updateWorkflowState();
  }

  function updateWorkflowState() {
    const template = selectedTemplate();
    const sectionCount = workflow.assets.length;
    const hasSection = Boolean(workflow.sectionId && sectionCount);
    const match = template.count ? sectionCount === template.count : sectionCount >= 10 && sectionCount <= 60;
    const roleIds = selectedRoleIds();
    const mode = node("sample-hero-mode")?.value || "single";
    const enoughRoles = mode === "auto" || (roleIds.heroIds.length >= 1 && (mode === "single" || roleIds.subheroIds.length >= 1 || mode === "multiple" && roleIds.heroIds.length >= 2));
    const button = node("generate-from-section");
    if (button) button.disabled = !(hasSection && match && enoughRoles) || workflow.busy;
    const expected = hasSection ? `${sectionCount} photos · ${template.label} · ${template.count ? "requires 12 photos" : "adapts to 10–60 photos"}` : "Choose a topic and section to begin.";
    renderRecommendations();
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
    ++workflow.request;
    renderRoleOptions(); renderMatchingTemplates();
    const select = node("sample-section");
    if (!select) return;
    if (!topicId) {
      select.disabled = true;
      select.innerHTML = option("", "Choose a topic first…");
      renderRoleOptions(); renderMatchingTemplates(); return;
    }
    const data = await api(`/api/topics/${encodeURIComponent(topicId)}/sections`);
    if (workflow.topicId !== topicId) return;
    workflow.sections = data.sections || [];
    select.innerHTML = option("", "Choose a section…") + workflow.sections.map((section) => option(section.id, `${section.title} · ${section.item_count} photos`)).join("");
    select.disabled = !workflow.sections.length;
    renderRoleOptions(); renderMatchingTemplates();
  }

  async function loadSectionAssets(sectionId) {
    workflow.sectionId = sectionId || "";
    workflow.assets = [];
    const request = ++workflow.request;
    renderRoleOptions(); renderMatchingTemplates();
    if (!sectionId) { renderRoleOptions(); renderMatchingTemplates(); return; }
    const idData = await api(`/api/sections/${encodeURIComponent(sectionId)}/assets`);
    if (request !== workflow.request) return;
    const ids = (idData.asset_ids || []).map(String);
    if (!ids.length) { renderRoleOptions(); renderMatchingTemplates(); return; }
    const data = await api(`/api/collage/photos?${ids.map((id) => `asset_id=${encodeURIComponent(id)}`).join("&")}`);
    if (request !== workflow.request) return;
    const byId = new Map((data.items || []).map((item) => [String(item.asset_id), item]));
    if (ids.some((id) => !byId.has(id))) throw new Error("Some section photos could not be loaded. Nothing was omitted; reload the section before generating.");
    workflow.assets = ids.map((id) => byId.get(id));
    renderRoleOptions(); renderMatchingTemplates();
  }

  function pageSpecFor() {
    return library.resolvePage({ preset_id: node("sample-template-match")?.value || "a4-portrait" });
  }

  function sourceSemantics(section) {
    const metadata = state.doc?.metadata || {};
    if ((!section && !workflow.sectionId) || section?.id === metadata.section_id) {
      return { ...metadata.composition, hero_asset_ids: metadata.hero_asset_ids || metadata.composition?.hero_asset_ids };
    }
    // Use the same semantic vocabulary as the existing section adviser. Titles
    // are a fallback hint, never a claim to have recognised faces or locations.
    if (section?.layout_archetype || section?.composition) return section.composition || section;
    const title = (section?.title || "").toLowerCase();
    const layout_archetype = /flower|botan|tulip|花/.test(title) ? "detail_mosaic"
      : /cathedral|church|castle|architecture/.test(title) ? "architecture_journey"
      : /railway|cable|journey/.test(title) ? "sequence_journey"
      : /family|mum|mika|micah|母|家人/.test(title) ? "family_memory"
      : /summit|mountain|landscape|scenic/.test(title) ? "scenic_hero" : "travel_scrapbook";
    return { layout_archetype };
  }

  function renderRecommendations() {
    const target = node("sample-recommendations");
    if (!target) return;
    const section = workflow.sections.find((item) => item.id === workflow.sectionId);
    const recommendations = library.recommend(workflow.assets, pageSpecFor(), sourceSemantics(section)).slice(0, 3);
    target.replaceChildren();
    for (const entry of recommendations) {
      const button = document.createElement("button");
      button.type = "button"; button.className = "small";
      button.textContent = library.families.find((f) => f.id === entry.familyId).name;
      button.title = entry.reason;
      button.addEventListener("click", () => { node("sample-template").value = entry.familyId; renderMatchingTemplates(); });
      target.append(button);
    }
    const description = document.createElement("span");
    description.className = "muted";
    const family = selectedTemplate().family;
    description.textContent = family ? family.description + (family.chronological ? " Hero choices keep capture order." : "") : "Unchanged original 12-photo Kew reference.";
    target.append(description);
  }

  function buildTemplateSpec(template, assetItems, roleIds, section, topic) {
    const sameSection = !section || section.id === state.doc?.metadata?.section_id;
    const existingText = (role) => sameSection ? elements().find((e) => e.type === "text" && e.role === role)?.content : "";
    const result = library.build({
      familyId: template.id, photos: assetItems, page: pageSpecFor(), ...roleIds,
      semantics: sourceSemantics(section),
      title: existingText("title") || section?.title || "Our photo story",
      subtitle: existingText("subtitle") || topic?.name || "",
      caption: existingText("caption") || section?.description || "",
    });
    workflow.diagnostics = result.diagnostics;
    return result.spec;
  }

  async function openBuiltSpec(spec, section, topic) {
    const semantics = sourceSemantics(section);
    const templateId = selectedTemplate().id;
    const opened = await validateAiSpec(spec);
    if (!opened) return;
    opened.metadata ||= {};
    Object.assign(opened.metadata, {
      template_family: templateId, template_version: library.VERSION,
      ...(section ? { section_id: section.id, section_title: section.title, topic_id: topic.id, topic_name: topic.name } : {}),
      composition: {
        ...semantics, template_family: templateId,
        hero_asset_ids: workflow.diagnostics?.heroes || [], subheroes: workflow.diagnostics?.subheroes || [],
        all_asset_ids: spec.assets.map((a) => a.asset_id),
      },
    });
    const d = workflow.diagnostics;
    workflowStatus(`Opened ${spec.assets.length} photos, each exactly once. Save variant to keep this editable design.` +
      (d?.cropWarnings.length ? ` ${d.cropWarnings.length} crops need review in Crop mode.` : "") +
      (d?.safetyWarnings?.length ? ` ${d.safetyWarnings.length} crop${d.safetyWarnings.length === 1 ? "" : "s"} may cut through a detected face or person; review those frames in Crop mode.` : "") +
      (d?.smallestEdgeMm < 15 ? " Small print frames: consider a larger page." : ""));
  }

  async function loadSelectedSample() {
    const template = selectedTemplate();
    const section = workflow.sections.find((item) => item.id === workflow.sectionId);
    const topic = workflow.topics.find((item) => item.id === workflow.topicId);
    if (workflow.sectionId && !workflow.assets.length) throw new Error("Wait for every section photo to finish loading.");
    if (section && workflow.assets.length && template.id !== "kew-square-12") {
      if (workflow.assets.length < 10 || workflow.assets.length > 60) {
        workflowStatus(`Choose a section with 10–60 photos. “${section.title}” has ${workflow.assets.length}; none will be omitted.`, true);
        return;
      }
      const roles = selectedRoleIds();
      const spec = buildTemplateSpec(template, workflow.assets, roles, section, topic);
      await openBuiltSpec(spec, section, topic);
      return;
    }
    const currentAssets = section ? workflow.assets.map((item) => item.asset_id) : [...new Set(elements().map(photoId).filter(Boolean))];
    if (template.count ? currentAssets.length !== template.count : currentAssets.length < 10 || currentAssets.length > 60) {
      status(`Open a source with ${template.count || "10–60"} photo assets, or choose a topic section first.`);
      return;
    }
    if (template.id === "kew-square-12") {
      const response = await fetch("/examples/kew-gardens-ai-design-v2.json");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const sample = await response.json();
      sample.assets = (sample.assets || []).map((asset, index) => {
        const assetId = currentAssets[index]; const info = workflow.assets.find((p) => p.asset_id === assetId) || state.assetMap.get(String(assetId)) || {};
        return { ...asset, asset_id: assetId, filename: info.filename || `selected-image-${String(index + 1).padStart(2, "0")}.jpg` };
      });
      await validateAiSpec(sample);
      return;
    }
    const items = currentAssets.map((id) => state.assetMap.get(String(id)) || { asset_id: id, filename: id });
    await openBuiltSpec(buildTemplateSpec(template, items, { heroIds: [], subheroIds: [] }, null, null), null, null);
  }

  async function generateSafely() {
    if (workflow.busy) return;
    workflow.busy = true; updateWorkflowState();
    const controls = ["sample-topic", "sample-section", "sample-template", "sample-template-match", "sample-hero-mode", "sample-hero", "sample-subheroes", "load-sample"];
    const disabledBefore = controls.map((id) => node(id).disabled);
    controls.forEach((id) => { node(id).disabled = true; });
    try { await loadSelectedSample(); }
    finally {
      workflow.busy = false;
      controls.forEach((id, i) => { node(id).disabled = disabledBefore[i]; });
      const message = node("sample-workflow-status").textContent;
      const color = node("sample-workflow-status").style.color;
      updateWorkflowState();
      node("sample-workflow-status").textContent = message;
      node("sample-workflow-status").style.color = color;
    }
  }

  async function initialise() {
    renderTemplateOptions();
    node("sample-topic")?.addEventListener("change", (event) => loadSections(event.target.value).catch((error) => workflowStatus(`Topic load failed: ${error.message}`, true)));
    node("sample-section")?.addEventListener("change", (event) => loadSectionAssets(event.target.value).catch((error) => workflowStatus(`Section load failed: ${error.message}`, true)));
    node("sample-template")?.addEventListener("change", () => { renderMatchingTemplates(); updateWorkflowState(); });
    node("sample-template-match")?.addEventListener("change", updateWorkflowState);
    node("sample-hero")?.addEventListener("change", () => { refreshSubheroOptions(); updateWorkflowState(); });
    node("sample-subheroes")?.addEventListener("change", updateWorkflowState);
    node("sample-hero-mode")?.addEventListener("change", updateRoleVisibility);
    node("generate-from-section")?.addEventListener("click", () => generateSafely().catch((error) => workflowStatus(`Template generation failed: ${error.message}`, true)));
    node("load-sample")?.addEventListener("click", () => generateSafely().catch((error) => status(`Sample design unavailable: ${error.message}`)));
    await loadTopics();
  }

  initialise().catch((error) => workflowStatus(`Template workflow unavailable: ${error.message}`, true));
})();
