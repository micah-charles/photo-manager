(() => {
  document.addEventListener("click", event => {
    if (!event.target.matches("[data-crop]")) return;
    setTimeout(() => {
      const dialog = event.target.closest("dialog");
      if (!dialog) return;
      const showingNaive = event.target.textContent.includes("Show smart");
      dialog.querySelectorAll("[data-frame] img").forEach(image => {
        image.style.objectPosition = showingNaive ? "0% 0%" : "50% 50%";
        image.style.outline = showingNaive ? "2px dashed #b64b3b" : "none";
      });
    }, 0);
  });
})();
