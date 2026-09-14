(() => {
  const byId = (id) => document.getElementById(id);
  const statusNode = byId("status");
  const importStatus = byId("ai-status");
  let validatedSpec = null;
  let packageId = null;

  const setStatus = (message) => {
    if (statusNode) statusNode.textContent = message;
    if (importStatus) importStatus.textContent = message;
  };

  function setMethod(method) {
    const isAi = method === "ai";
    const isAutomatic = !isAi;
    byId("ai-method")?.classList.toggle("hidden", !isAi);
    byId("automatic-method")?.classList.toggle("hidden", !isAutomatic);
    if (isAutomatic) {
      document.querySelectorAll('input[name="provider"]').forEach((input) => { input.checked = input.value === method; });
    }
    window.collageCreationMethod = method;
    if (typeof update === "function") update();
  }

  async function validateImportedSpec(spec) {
    setStatus("Validating AI design…");
    if (!spec || typeof spec !== "object" || Array.isArray(spec)) throw new Error("The JSON root must be an object.");
    const response = await fetch("/api/collage/design-imports/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spec, package_id: spec.package_id }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    validatedSpec = result.spec;
    packageId = result.package_id || spec.package_id || null;
    const alternatives = result.alternatives || [];
    const selector = byId("creator-alternative");
    if (!selector || !alternatives.length) throw new Error("The AI design contains no alternatives.");
    selector.innerHTML = alternatives.map((item) => `<option value="${Number(item.alternative)}">Alternative ${Number(item.alternative) + 1} · ${Number(item.photos)} photos · ${Number(item.elements)} elements</option>`).join("");
    byId("creator-import-panel")?.classList.remove("hidden");
    setStatus(`Validated ${alternatives.length} AI design alternative${alternatives.length === 1 ? "" : "s"}. Choose one to open.`);
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
    setStatus("Uploading and validating AI Design Package…");
    const packageZipBase64 = await readFileAsBase64(file);
    const response = await fetch("/api/collage/design-import-packages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ package_zip_base64: packageZipBase64 }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    validatedSpec = result.spec;
    packageId = result.package_id;
    const selector = byId("creator-alternative");
    const alternatives = result.alternatives || [];
    if (!alternatives.length) throw new Error("The package contains no AI alternatives.");
    selector.innerHTML = alternatives.map((item) => `<option value="${Number(item.alternative)}">Alternative ${Number(item.alternative) + 1} · ${Number(item.photos)} photos · ${Number(item.elements)} elements</option>`).join("");
    byId("creator-import-panel")?.classList.remove("hidden");
    const report = result.validation || {};
    setStatus(`Package validated: ${alternatives.length} alternative${alternatives.length === 1 ? "" : "s"}, ${Number(report.warnings?.length || 0)} warning(s), ${Number(report.repairs?.length || 0)} bounded repair(s). Choose one to open.`);
  }

  async function openImportedDesign() {
    if (!validatedSpec) { setStatus("Choose an AI design JSON first."); return; }
    const alternativeIndex = Number(byId("creator-alternative")?.value || 0);
    setStatus("Opening AI design as an editable variant…");
    const response = await fetch("/api/collage/design-imports", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spec: validatedSpec, package_id: packageId, alternative_index: alternativeIndex }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    window.location.href = `/experimental/collage/fabric-v2?document=${encodeURIComponent(result.document_url)}&source=ai-design`;
  }

  function buildBlankDocument() {
    const appState = window.collageState;
    const selected = [...(appState?.selected || [])];
    if (!selected.length) throw new Error("Select at least one photo first.");
    const page = typeof readPageSpec === "function" ? readPageSpec() : { type: "single", width_mm: 300, height_mm: 300, background: "#f5f2ed", gutter_mm: 4 };
    const pageWidth = Number(page.width_mm || 300) * (page.type === "spread" ? 2 : 1);
    const pageHeight = Number(page.height_mm || 300);
    const margin = Math.max(Number(page.safe_margin_mm || 8), 4);
    const gap = Math.max(Number(page.gutter_mm || 4), 2);
    const columns = Math.max(1, Math.ceil(Math.sqrt(selected.length * pageWidth / pageHeight)));
    const rows = Math.ceil(selected.length / columns);
    const cellWidth = (pageWidth - margin * 2 - gap * (columns - 1)) / columns;
    const cellHeight = (pageHeight - margin * 2 - gap * (rows - 1)) / rows;
    if (cellWidth <= 1 || cellHeight <= 1) throw new Error("The selected page format is too small for a blank grid.");
    const elements = selected.map((assetId, index) => ({
      element_id: `blank-photo-${index + 1}`,
      type: "photo",
      photo_id: assetId,
      asset_id: assetId,
      x: window.collageGeometry.mmToPx(margin + (index % columns) * (cellWidth + gap)),
      y: window.collageGeometry.mmToPx(margin + Math.floor(index / columns) * (cellHeight + gap)),
      width: window.collageGeometry.mmToPx(cellWidth),
      height: window.collageGeometry.mmToPx(cellHeight),
      rotation_deg: 0,
      z_index: index,
      opacity: 1,
      clipping_shape: "rectangle",
      transform: { zoom: 1, focus_x: 0.5, focus_y: 0.5, rotation_deg: 0 },
      style: { border: { width_mm: 0, color: "#ffffff", opacity: 1 }, shadow: {} },
    }));
    return {
      document_type: "CollageDocument",
      schema_version: 2,
      document_id: `blank-${Date.now()}`,
      page_spec: page,
      canvas: { width: window.collageGeometry.mmToPx(pageWidth), height: window.collageGeometry.mmToPx(pageHeight), gutter: window.collageGeometry.mmToPx(Number(page.gutter_mm || 4)) },
      background: page.background || "#f5f2ed",
      elements,
      frames: elements,
      cells: elements,
      provider: "blank",
      style: "blank-grid",
      metadata: { source: "Creator Mode · Start Blank" },
    };
  }

  async function startBlank() {
    try {
      setStatus("Creating blank editable collage…");
      const response = await fetch("/api/collage/documents", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(buildBlankDocument()) });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
      window.location.href = `/experimental/collage/fabric-v2?document=${encodeURIComponent(result.document_url)}&source=blank`;
    } catch (error) {
      setStatus(`Start blank failed: ${error.message}`);
    }
  }

  byId("method-ai")?.addEventListener("change", () => setMethod("ai"));
  byId("method-native")?.addEventListener("change", () => setMethod("native"));
  byId("method-cewe")?.addEventListener("change", () => setMethod("cewe-genetic"));
  byId("method-bsp")?.addEventListener("change", () => setMethod("bsp"));
  byId("import-ai-design")?.addEventListener("click", () => byId("import-ai-file")?.click());
  byId("import-ai-package")?.addEventListener("click", () => byId("import-ai-package-file")?.click());
  byId("import-ai-file")?.addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try { validateImportedSpec(JSON.parse(String(reader.result || ""))).catch((error) => setStatus(`AI design validation failed: ${error.message}`)); }
      catch (error) { setStatus(`AI JSON is invalid: ${error.message}`); }
    };
    reader.readAsText(file);
  });
  byId("import-ai-package-file")?.addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) importDesignPackage(file).catch((error) => setStatus(`AI package import failed: ${error.message}`));
  });
  byId("creator-open")?.addEventListener("click", () => openImportedDesign().catch((error) => setStatus(`AI design import failed: ${error.message}`)));
  byId("start-blank")?.addEventListener("click", () => startBlank());
  setMethod("ai");
})();
