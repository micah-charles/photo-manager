(() => {
  const state = window.collageState;
  if (!state) return;
  const toolbar = document.querySelector("#results .row");
  if (!toolbar) return;
  const select = document.createElement("select");
  select.innerHTML = '<option value="">Open previous run…</option>';
  const button = document.createElement("button");
  button.textContent = "Open run";
  toolbar.append(select, button);
  fetch("/api/collage/runs").then(response => response.json()).then(data => {
    (data.runs || []).forEach(run => {
      const option = document.createElement("option");
      option.value = run.run_id;
      option.textContent = `${run.run_id.slice(0, 8)} · ${run.candidate_count} candidates · seed ${run.seed}`;
      select.append(option);
    });
  });
  button.onclick = async () => {
    if (!select.value) return;
    const payload = await (await fetch(`/api/collage/runs/${select.value}`)).json();
    state.lastRun = payload;
    state.candidates = payload.candidates || [];
    document.querySelector("#results")?.classList.remove("hidden");
    document.querySelector("#metrics").textContent = `run ${payload.run_id} · ${state.candidates.length} candidates · reopened`;
    document.dispatchEvent(new Event("collage:render"));
  };
})();
