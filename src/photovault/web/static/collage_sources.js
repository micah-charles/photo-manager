(() => {
  const box = document.createElement("div");
  box.className = "providers";
  box.textContent = "Loading sources…";
  document.getElementById("count")?.before(box);
  let selected = new Set();
  fetch("/api/navigation").then(r => r.json()).then(data => {
    const sources = data.sources || [];
    selected = new Set(sources.map(source => source.id));
    box.innerHTML = `<strong>Sources</strong> ${sources.map(source => `<label><input type="checkbox" data-collage-source="${source.id}" checked> ${source.name} · ${source.item_count}</label>`).join("")}`;
    box.querySelectorAll("[data-collage-source]").forEach(input => input.addEventListener("change", () => {
      if (input.checked) selected.add(input.dataset.collageSource); else selected.delete(input.dataset.collageSource);
    }));
  }).catch(() => { box.textContent = "Sources unavailable"; });
  const originalFetch = window.fetch;
  window.fetch = (input, init) => {
    const url = new URL(typeof input === "string" ? input : input.url, window.location.href);
    if (url.pathname === "/api/collage/photos" && selected.size) selected.forEach(source => url.searchParams.append("source", source));
    return originalFetch(url, init);
  };
})();
