/* Board-first workspace for organising permanent Picks into story Sections. */
const params = new URLSearchParams(location.search);
const topicId = params.get("topic") || "";
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));
const state = {
  topic: null,
  photos: [],
  sections: [],
  selected: new Set(),
  collapsed: new Set(),
  view: "board",
  suggestions: null,
  busy: false,
};

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.error || `Request failed (${response.status})`);
  return data;
}

function status(message, kind = "") {
  $("status").textContent = message;
  $("status").className = `status ${kind}`.trim();
}

function photoById(id) {
  return state.photos.find((photo) => photo.asset_id === id);
}

function assignmentsFor(id) {
  return state.sections.filter((section) => section.asset_ids.includes(id));
}

function unassignedIds() {
  const assigned = new Set(state.sections.flatMap((section) => section.asset_ids));
  return state.photos.map((photo) => photo.asset_id).filter((id) => !assigned.has(id));
}

function timeLabel(photo) {
  const captured = String(photo?.captured || "");
  return captured.length >= 16 ? captured.slice(0, 16).replace("T", " ") : (captured || "Unknown time");
}

function shortTime(photo) {
  const captured = String(photo?.captured || "");
  return captured.length >= 16 ? captured.slice(11, 16) : "—";
}

function photoCard(id) {
  const photo = photoById(id);
  if (!photo) return "";
  const selected = state.selected.has(id);
  const src = photo.thumbnail || "";
  return `<article class="pick-card${selected ? " selected" : ""}" data-asset-id="${esc(id)}" draggable="true" tabindex="0" role="button" aria-pressed="${selected}" aria-label="${esc(photo.filename)}">
    ${src ? `<img src="${esc(src)}" loading="lazy" decoding="async" alt="${esc(photo.filename)}">` : `<div class="photo-placeholder">No preview</div>`}
    <span class="photo-time">${esc(shortTime(photo))}</span>
    ${selected ? '<span class="selection-mark" aria-hidden="true">✓</span>' : ""}
    <span class="photo-label" title="${esc(photo.filename)}">${esc(photo.filename)}</span>
  </article>`;
}

function lane(id, title, ids, sectionIndex = null) {
  const isUnassigned = id === "__unassigned__";
  const collapsed = !isUnassigned && state.collapsed.has(id);
  const number = sectionIndex === null ? "" : `<span class="section-number">${sectionIndex + 1}</span>`;
  const actions = isUnassigned
    ? `<button data-action="select-all" data-section="__unassigned__" title="Select all unassigned picks">Select all</button>`
    : `<div class="lane-actions">
        <button data-action="select-all" data-section="${esc(id)}" title="Select all photos in this section">Select all</button>
        <button data-action="up" data-section="${esc(id)}" title="Move section earlier">↑</button>
        <button data-action="down" data-section="${esc(id)}" title="Move section later">↓</button>
        <button data-action="rename" data-section="${esc(id)}">Rename</button>
        <button data-action="split" data-section="${esc(id)}">Split</button>
        <button data-action="merge" data-section="${esc(id)}">Merge</button>
        <button data-action="delete" data-section="${esc(id)}" class="danger">Delete</button>
        <button data-action="collapse" data-section="${esc(id)}" aria-expanded="${!collapsed}">${collapsed ? "Show" : "Hide"}</button>
      </div>`;
  const collage = !isUnassigned && ids.length >= 2
    ? `<button data-action="collage" data-section="${esc(id)}" class="lane-collage">Create collage</button>` : "";
  return `<section class="lane${isUnassigned ? " unassigned" : ""}${collapsed ? " collapsed" : ""}" data-drop-target="${esc(isUnassigned ? "__unassigned__" : id)}">
    <header class="lane-header">
      ${number}<h2>${esc(title)}</h2><span class="count">${ids.length} photo${ids.length === 1 ? "" : "s"}</span>${collage}${actions}
    </header>
    <div class="lane-body">${ids.map(photoCard).join("") || '<div class="drop-hint">Drop picked photos here</div>'}</div>
  </section>`;
}

function renderBoard() {
  const unassigned = unassignedIds();
  $("board").innerHTML = lane("__unassigned__", "Unassigned picks", unassigned) + state.sections.map((section, index) => lane(section.id, section.title, section.asset_ids, index)).join("");
}

function renderTimeline() {
  const photos = [...state.photos].sort((left, right) => String(left.captured || "").localeCompare(String(right.captured || "")));
  $("timeline").innerHTML = `<div class="timeline-intro"><strong>Timeline view</strong> · Picks are shown chronologically. Use Board to move photos between story sections.</div>${photos.map((photo) => {
    const groups = assignmentsFor(photo.asset_id).map((section) => esc(section.title));
    return `<article class="timeline-item"><span class="timeline-time">${esc(timeLabel(photo))}</span>${photo.thumbnail ? `<img src="${esc(photo.thumbnail)}" loading="lazy" alt="${esc(photo.filename)}">` : '<div class="photo-placeholder">No preview</div>'}<div class="timeline-copy"><strong>${esc(photo.filename)}</strong><span>${groups.length ? "Assigned to:" : "Unassigned pick"}</span>${groups.map((name) => `<span class="assignment">${name}</span>`).join("")}</div></article>`;
  }).join("") || '<div class="timeline-intro">There are no Picks to show yet.</div>'}`;
}

function renderSuggestions() {
  const panel = $("suggestion-panel");
  if (!state.suggestions) {
    panel.hidden = true;
    panel.replaceChildren();
    return;
  }
  panel.hidden = false;
  const groups = state.suggestions;
  panel.innerHTML = `<div class="suggestion-header"><div><h2 id="suggestion-title">Suggested organisation</h2><p>Draft only · nothing is saved until you choose Apply suggestions.</p></div><div class="suggestion-actions"><button data-suggestion-action="cancel">Cancel</button><button data-suggestion-action="apply" class="apply">Apply suggestions</button></div></div><div class="suggestion-list">${groups.map((group, index) => `<article class="suggestion-group"><strong>${esc(group.title)}</strong><span>${group.asset_ids.length} photos · ${esc(shortTime(photoById(group.asset_ids[0])))}–${esc(shortTime(photoById(group.asset_ids.at(-1))))}</span><div class="suggestion-thumbs">${group.asset_ids.slice(0, 6).map((id) => { const photo = photoById(id); return photo?.thumbnail ? `<img src="${esc(photo.thumbnail)}" alt="${esc(photo.filename)}">` : ""; }).join("")}</div><small>Suggestion ${index + 1}</small></article>`).join("")}</div>`;
}

function render() {
  const unassigned = unassignedIds();
  const selected = state.selected.size ? ` · ${state.selected.size} selected` : "";
  $("counts").textContent = `${state.photos.length} Picks · ${state.sections.length} Sections · ${unassigned.length} Unassigned${selected}`;
  $("move-selected").disabled = !state.selected.size || state.busy;
  $("clear-selection").disabled = !state.selected.size || state.busy;
  const target = $("move-target");
  target.innerHTML = '<option value="">Move selected to…</option><option value="__unassigned__">Unassigned picks</option>' + state.sections.map((section) => `<option value="${esc(section.id)}">${esc(section.title)}</option>`).join("");
  if (state.view === "timeline") {
    $("board").hidden = true;
    $("timeline").hidden = false;
    renderTimeline();
  } else {
    $("board").hidden = false;
    $("timeline").hidden = true;
    renderBoard();
  }
  $("board-view").setAttribute("aria-pressed", String(state.view === "board"));
  $("timeline-view").setAttribute("aria-pressed", String(state.view === "timeline"));
  renderSuggestions();
}

async function load() {
  if (!topicId) throw Error("Missing topic in URL");
  const [topics, data] = await Promise.all([api("/api/topics"), api(`/api/topics/${encodeURIComponent(topicId)}/organise-picks`)]);
  state.topic = (topics.topics || []).find((topic) => topic.id === topicId);
  if (!state.topic) throw Error("Topic not found");
  state.photos = data.photos || [];
  state.sections = data.sections || [];
  const valid = new Set(state.photos.map((photo) => photo.asset_id));
  state.selected = new Set([...state.selected].filter((id) => valid.has(id)));
  $("back-link").href = `/topic-workspace?topic=${encodeURIComponent(topicId)}`;
  $("title").textContent = `Organise Picks · ${state.topic.name}`;
  $("topic-summary").textContent = `${state.topic.item_count} topic photos · organise your Picks into story Sections before creating a collage.`;
  render();
}

async function run(action, successMessage) {
  if (state.busy) return;
  state.busy = true;
  render();
  try {
    await action();
    state.selected.clear();
    state.suggestions = null;
    await load();
    status(successMessage, "success");
  } catch (error) {
    status(error.message, "error");
  } finally {
    state.busy = false;
    render();
  }
}

function selectedForSection(sectionId) {
  const ids = sectionId === "__unassigned__" ? unassignedIds() : (state.sections.find((section) => section.id === sectionId)?.asset_ids || []);
  return ids.filter((id) => state.selected.has(id));
}

function moveSelected(target) {
  if (!state.selected.size) return;
  if (!target) {
    status("Choose a destination before moving selected photos.", "error");
    return;
  }
  const targetSectionId = target === "__unassigned__" ? null : target;
  return run(() => api(`/api/topics/${encodeURIComponent(topicId)}/organise-picks/move`, { method: "POST", body: JSON.stringify({ asset_ids: [...state.selected], target_section_id: targetSectionId }) }), "Photos moved. Pick decisions are unchanged.");
}

function openNewSection() {
  $("section-dialog-title").textContent = "New section";
  $("section-dialog-help").textContent = state.selected.size ? `${state.selected.size} selected Pick${state.selected.size === 1 ? "" : "s"} will be assigned.` : "Create an empty section, then drag Picks into it.";
  $("section-form").dataset.mode = "create";
  $("section-name").value = "";
  $("section-description").value = "";
  $("section-dialog").showModal();
  $("section-name").focus();
}

async function submitNewSection(event) {
  event.preventDefault();
  const title = $("section-name").value.trim();
  const description = $("section-description").value.trim();
  $("section-dialog").close();
  await run(() => api(`/api/topics/${encodeURIComponent(topicId)}/organise-picks/sections`, { method: "POST", body: JSON.stringify({ title, description, asset_ids: [...state.selected] }) }), "Section created.");
}

function openRename(sectionId) {
  const section = state.sections.find((item) => item.id === sectionId);
  if (!section) return;
  $("rename-form").dataset.section = sectionId;
  $("rename-name").value = section.title;
  $("rename-dialog").showModal();
  $("rename-name").focus();
}

async function submitRename(event) {
  event.preventDefault();
  const sectionId = $("rename-form").dataset.section;
  const title = $("rename-name").value.trim();
  $("rename-dialog").close();
  await run(() => api(`/api/sections/${encodeURIComponent(sectionId)}`, { method: "PUT", body: JSON.stringify({ title }) }), "Section renamed.");
}

function openSplit(sectionId) {
  const ids = selectedForSection(sectionId);
  if (!ids.length) {
    status("Select one or more photos in this section before splitting.", "error");
    return;
  }
  $("split-form").dataset.section = sectionId;
  $("split-help").textContent = `${ids.length} selected photo${ids.length === 1 ? "" : "s"} will move into a new section. Pick state stays unchanged.`;
  $("split-name").value = "";
  $("split-dialog").showModal();
  $("split-name").focus();
}

async function submitSplit(event) {
  event.preventDefault();
  const sectionId = $("split-form").dataset.section;
  const assetIds = selectedForSection(sectionId);
  const title = $("split-name").value.trim();
  $("split-dialog").close();
  await run(() => api(`/api/sections/${encodeURIComponent(sectionId)}/split`, { method: "POST", body: JSON.stringify({ title, asset_ids: assetIds }) }), "Section split.");
}

function openMerge(sourceId) {
  const choices = state.sections.filter((section) => section.id !== sourceId);
  if (!choices.length) {
    status("Create another section before merging.", "error");
    return;
  }
  $("merge-form").dataset.source = sourceId;
  $("merge-target").innerHTML = choices.map((section) => `<option value="${esc(section.id)}">${esc(section.title)}</option>`).join("");
  $("merge-name").value = "";
  $("merge-help").textContent = "The source section will be removed; its photos will be added to the destination without duplicates.";
  $("merge-dialog").showModal();
}

async function submitMerge(event) {
  event.preventDefault();
  const sourceId = $("merge-form").dataset.source;
  const targetId = $("merge-target").value;
  const title = $("merge-name").value.trim();
  $("merge-dialog").close();
  await run(() => api(`/api/sections/${encodeURIComponent(targetId)}/merge`, { method: "POST", body: JSON.stringify({ source_section_id: sourceId, new_title: title || null }) }), "Sections merged.");
}

function reorder(sectionId, direction) {
  const ids = state.sections.map((section) => section.id);
  const index = ids.indexOf(sectionId);
  const next = index + direction;
  if (index < 0 || next < 0 || next >= ids.length) return;
  [ids[index], ids[next]] = [ids[next], ids[index]];
  return run(() => api(`/api/topics/${encodeURIComponent(topicId)}/organise-picks/reorder`, { method: "POST", body: JSON.stringify({ section_ids: ids }) }), "Section order saved.");
}

function suggestSections() {
  const ids = unassignedIds();
  if (!ids.length) {
    status("All Picks are already assigned to Sections.");
    return;
  }
  const photos = ids.map(photoById).filter(Boolean).sort((left, right) => String(left.captured || "").localeCompare(String(right.captured || "")));
  const groups = [];
  let current = [];
  for (const photo of photos) {
    const previous = current.at(-1);
    const gapMinutes = previous && photo.captured && previous.captured ? (Date.parse(photo.captured) - Date.parse(previous.captured)) / 60000 : 0;
    const shouldSplit = current.length >= 6 && gapMinutes > 20 || current.length >= 10;
    if (shouldSplit) {
      groups.push(current);
      current = [];
    }
    current.push(photo);
  }
  if (current.length) groups.push(current);
  state.suggestions = groups.map((group, index) => ({ title: `Section ${index + 1} · ${shortTime(group[0])}–${shortTime(group.at(-1))}`, asset_ids: group.map((photo) => photo.asset_id) }));
  render();
  status("Suggestions are ready for review. Nothing has been saved.");
}

function applySuggestions() {
  if (!state.suggestions?.length) return;
  return run(() => api(`/api/topics/${encodeURIComponent(topicId)}/organise-picks/apply-suggestions`, { method: "POST", body: JSON.stringify({ suggestions: state.suggestions }) }), "Suggestions applied as Sections.");
}

function toggleSelection(id) {
  if (state.selected.has(id)) state.selected.delete(id); else state.selected.add(id);
  render();
}

$("new-section").onclick = openNewSection;
$("suggest-sections").onclick = suggestSections;
$("clear-selection").onclick = () => { state.selected.clear(); render(); };
$("move-selected").onclick = () => moveSelected($("move-target").value);
$("board-view").onclick = () => { state.view = "board"; render(); };
$("timeline-view").onclick = () => { state.view = "timeline"; render(); };
$("section-form").onsubmit = (event) => submitNewSection(event).catch((error) => status(error.message, "error"));
$("rename-form").onsubmit = (event) => submitRename(event).catch((error) => status(error.message, "error"));
$("split-form").onsubmit = (event) => submitSplit(event).catch((error) => status(error.message, "error"));
$("merge-form").onsubmit = (event) => submitMerge(event).catch((error) => status(error.message, "error"));
["cancel-section", "cancel-rename", "cancel-split", "cancel-merge"].forEach((id) => $(id).onclick = () => $(id.replace("cancel-", "") === "section" ? "section-dialog" : `${id.replace("cancel-", "")}-dialog`).close());

$("board").addEventListener("click", (event) => {
  const actionButton = event.target.closest("[data-action]");
  if (actionButton) {
    const action = actionButton.dataset.action;
    const sectionId = actionButton.dataset.section;
    if (action === "select-all") {
      selectedForSection(sectionId).forEach((id) => state.selected.add(id));
      const ids = sectionId === "__unassigned__" ? unassignedIds() : (state.sections.find((section) => section.id === sectionId)?.asset_ids || []);
      ids.forEach((id) => state.selected.add(id));
      render();
    } else if (action === "rename") openRename(sectionId);
    else if (action === "split") openSplit(sectionId);
    else if (action === "merge") openMerge(sectionId);
    else if (action === "collapse") { state.collapsed.has(sectionId) ? state.collapsed.delete(sectionId) : state.collapsed.add(sectionId); render(); }
    else if (action === "up") reorder(sectionId, -1);
    else if (action === "down") reorder(sectionId, 1);
    else if (action === "collage") location.href = `/experimental/collage?topic=${encodeURIComponent(topicId)}&section=${encodeURIComponent(sectionId)}&culling=picks`;
    else if (action === "delete") {
      if (window.confirm("Delete this Section? Photos and Pick decisions will remain safe.")) run(() => api(`/api/sections/${encodeURIComponent(sectionId)}`, { method: "DELETE" }), "Section deleted; its photos are now Unassigned.");
    }
    return;
  }
  const card = event.target.closest("[data-asset-id]");
  if (card) toggleSelection(card.dataset.assetId);
});

$("board").addEventListener("keydown", (event) => {
  const card = event.target.closest("[data-asset-id]");
  if (card && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); toggleSelection(card.dataset.assetId); }
});

$("board").addEventListener("dragstart", (event) => {
  const card = event.target.closest("[data-asset-id]");
  if (!card) return;
  const id = card.dataset.assetId;
  if (!state.selected.has(id)) state.selected = new Set([id]);
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", id);
  card.classList.add("dragging");
});

$("board").addEventListener("dragend", (event) => event.target.closest("[data-asset-id]")?.classList.remove("dragging"));
$("board").addEventListener("dragover", (event) => { const laneTarget = event.target.closest("[data-drop-target]"); if (laneTarget) { event.preventDefault(); laneTarget.classList.add("drop-target"); } });
$("board").addEventListener("dragleave", (event) => { const laneTarget = event.target.closest("[data-drop-target]"); if (laneTarget && !laneTarget.contains(event.relatedTarget)) laneTarget.classList.remove("drop-target"); });
$("board").addEventListener("drop", (event) => {
  const laneTarget = event.target.closest("[data-drop-target]");
  if (!laneTarget) return;
  event.preventDefault();
  laneTarget.classList.remove("drop-target");
  const draggedId = event.dataTransfer.getData("text/plain");
  if (draggedId && !state.selected.has(draggedId)) state.selected = new Set([draggedId]);
  moveSelected(laneTarget.dataset.dropTarget);
});

$("suggestion-panel").addEventListener("click", (event) => {
  const action = event.target.closest("[data-suggestion-action]")?.dataset.suggestionAction;
  if (action === "cancel") { state.suggestions = null; render(); status("Suggestion draft cancelled."); }
  if (action === "apply") applySuggestions();
});

load().then(() => status("Select Picks, then drag them into a Section. Unassigned Picks are valid." )).catch((error) => status(error.message, "error"));
