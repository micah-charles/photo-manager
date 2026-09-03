// Adds Topic as a second catalog source without changing the original folder POC.
(async function addTopicSource(){
  const sourceKind=document.getElementById("source-kind");
  if(sourceKind)return;
  const folderSelect=document.getElementById("folders");
  if(!folderSelect)return;
  const label=document.createElement("label");
  label.textContent="Source ";
  const kind=document.createElement("select");
  kind.id="source-kind";
  kind.innerHTML='<option value="folder">Folder</option><option value="topic">Topic</option>';
  label.prepend(kind);
  folderSelect.parentElement.before(label);
  const topics=await (await fetch("/api/collage/topics")).json();
  const topicOptions=(topics.topics||[]).map(x=>{const o=document.createElement("option");o.value=x.id;o.textContent=`${x.name} · ${x.item_count} photos`;o.dataset.topic="true";return o});
  topicOptions.forEach(o=>folderSelect.append(o));
  const setVisible=()=>{const isTopic=kind.value==="topic";[...folderSelect.options].forEach(o=>{o.hidden=Boolean(o.dataset.topic)!==isTopic});const first=[...folderSelect.options].find(o=>!o.hidden);if(first)folderSelect.value=first.value};
  kind.onchange=setVisible;
  const originalLoad=document.getElementById("load").onclick;
  document.getElementById("load").onclick=()=>{if(kind.value==="folder")return originalLoad();const d=document.getElementById("status");fetch(`/api/collage/photos?topic=${encodeURIComponent(folderSelect.value)}`).then(r=>r.json()).then(data=>{window.state=window.state||{};state.photos=data.items||[];state.selected=new Set(state.photos.map(x=>x.asset_id));document.getElementById("photos").innerHTML=state.photos.map(x=>`<article class="photo" data-id="${x.asset_id}"><label><input type="checkbox" checked> ${x.filename}</label>${x.thumbnail?`<img loading="lazy" src="${x.thumbnail}" alt="${x.filename}">`:``}</article>`).join("");document.querySelectorAll(".photo").forEach(x=>x.onclick=e=>{if(e.target.tagName!=="INPUT")x.querySelector("input").checked=!state.selected.has(x.dataset.id);if(x.querySelector("input").checked)state.selected.add(x.dataset.id);else state.selected.delete(x.dataset.id)});d.textContent=`Loaded ${state.photos.length} topic photos.`}).catch(e=>d.textContent=e.message)};
  setVisible();
})().catch(e=>{const s=document.getElementById("status");if(s)s.textContent=e.message});
