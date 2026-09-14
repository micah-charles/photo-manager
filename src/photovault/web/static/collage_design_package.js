async function exportDesignPackage() {
  const appState = window.collageState;
  const statusNode = document.querySelector("#status");
  if (!appState?.selected?.size) {
    if (statusNode) statusNode.textContent = "Select at least one photo first.";
    return null;
  }
  const page = typeof readPageSpec === "function" ? readPageSpec() : {};
  if (statusNode) statusNode.textContent = "Building design package…";
  try {
    const query = new URLSearchParams(location.search);
    const sourceKind = document.querySelector("#source-kind")?.value;
    const topicId = query.get("topic") || (sourceKind === "topic" ? document.querySelector("#folders")?.value : document.querySelector("#collage-topic")?.value) || null;
    const sectionId = query.get("section") || document.querySelector("#collage-section")?.value || null;
    const response = await fetch("/api/collage/design-packages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        asset_ids: [...appState.selected],
        page_spec: page,
        style: "organic",
        mode: "from_scratch",
        topic_id: topicId,
        section_id: sectionId,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    const link = document.createElement("a");
    link.href = data.download;
    link.download = `${data.package_id}.zip`;
    link.click();
    if (statusNode) statusNode.textContent = `Exported ${data.asset_count} assets. Upload the ZIP and contact sheet to ChatGPT.`;
    return data;
  } catch (error) {
    if (statusNode) statusNode.textContent = `Design package export failed: ${error.message}`;
    return null;
  }
}

window.exportDesignPackage = exportDesignPackage;
document.querySelector("#export-design")?.addEventListener("click", exportDesignPackage);
