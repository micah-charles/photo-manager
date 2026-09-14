// One browser-side physical page transform. Documents stay in mm-derived logical
// pixels; viewport fitting never changes document geometry.
(() => {
  const PX_PER_MM = 4;
  window.collageGeometry = Object.freeze({
    PX_PER_MM,
    mmToPx: (value) => Math.round(Number(value || 0) * PX_PER_MM),
    pxToMm: (value) => Number(value || 0) / PX_PER_MM,
    pageDimensionsPx: (page) => ({
      width: Math.round(Number(page?.width_mm || 300) * (page?.type === "spread" ? 2 : 1) * PX_PER_MM),
      height: Math.round(Number(page?.height_mm || 300) * PX_PER_MM),
    }),
  });
})();
