(async function(){
  const folder=$("folders"),row=folder?.closest(".row");if(!folder||!row)return;
  const params=new URLSearchParams(location.search),topicPicker=document.createElement("span");
  const data=await api("/api/topics"),topics=data.topics||[];
  topicPicker.id="topic-section-picker";topicPicker.innerHTML=`<label>Topic <select id="collage-topic"><option value="">Choose a topic…</option>${topics.map(t=>`<option value="${esc(t.id)}">${esc(t.name)}</option>`).join("")}</select></label> <label>Section <select id="collage-section" disabled><option value="">Choose a section…</option></select></label>`;
  row.insertBefore(topicPicker,row.firstChild);
  const topicSelect=$("collage-topic"),sectionSelect=$("collage-section"),originalLoad=$("load").onclick;
  async function sectionsFor(id){sectionSelect.innerHTML='<option value="">All topic photos</option>';sectionSelect.disabled=!id;if(!id)return;const result=await api(`/api/topics/${encodeURIComponent(id)}/sections`);for(const section of result.sections||[])sectionSelect.insertAdjacentHTML("beforeend",`<option value="${esc(section.id)}">${esc(section.title)} · ${section.item_count}</option>`);sectionSelect.disabled=false}
  function renderPhotos(items){state.photos=items;state.rotations={};state.selected=new Set(items.map(x=>x.asset_id));$("photos").innerHTML=items.map(x=>`<article class="photo" data-id="${esc(x.asset_id)}"><label><input type="checkbox" checked> ${esc(x.filename)}</label>${x.thumbnail?`<img loading="lazy" src="${esc(x.thumbnail)}" alt="${esc(x.filename)}">`:`<div>${esc(x.media_type)}</div>`}<button type="button" class="rotate-photo" data-rotate="${esc(x.asset_id)}">↻ Rotate</button></article>`).join("");document.querySelectorAll(".photo").forEach(card=>card.onclick=e=>{if(e.target.closest("[data-rotate]")){const id=card.dataset.id;state.rotations[id]=((state.rotations[id]||0)+90)%360;update();return}if(e.target.tagName!=="INPUT")card.querySelector("input").checked=!state.selected.has(card.dataset.id);card.querySelector("input").checked?state.selected.add(card.dataset.id):state.selected.delete(card.dataset.id);update()});update()}
  async function loadPickedScope(topicId){
    const handoff=await api(`/api/culling/${encodeURIComponent(topicId)}/photos?picks=1&limit=100`);
    if(!handoff.total)throw Error("No picked photos are available. Return to Topic Workspace and pick photos first.");
    if(handoff.total<2||handoff.total>20)throw Error(`Collage requires 2–20 picked photos; this topic has ${handoff.total}.`);
    renderPhotos(handoff.items||[]);
    $("status").textContent=`${handoff.total} picked photos loaded from Topic Workspace.`;
  }
  async function loadScope(){const topicId=topicSelect.value;if(!topicId){return originalLoad()}const result=await api(`/api/collage/photos?topic=${encodeURIComponent(topicId)}`);let items=result.items||[];if(sectionSelect.value){const membership=await api(`/api/sections/${encodeURIComponent(sectionSelect.value)}/assets`);const ids=new Set(membership.asset_ids||[]);items=items.filter(item=>ids.has(item.asset_id))}renderPhotos(items)}
  topicSelect.onchange=()=>sectionsFor(topicSelect.value).catch(e=>$("status").textContent=e.message);sectionSelect.onchange=()=>loadScope().catch(e=>$("status").textContent=e.message);$("load").onclick=()=>loadScope().catch(e=>$("status").textContent=e.message);
  if(params.get("topic")){
    topicSelect.value=params.get("topic");
    if(params.get("culling")==="picks"){
      // A culling handoff is an explicit, immutable scope. Do not let the
      // legacy folder loader replace it or silently broaden the selection.
      [...row.children].forEach(child=>{if(child!==topicPicker)child.hidden=true});
      topicPicker.insertAdjacentHTML("beforeend",` <strong class="culling-handoff">Picked photos only</strong>`);
      topicSelect.disabled=true;sectionSelect.disabled=true;
      await loadPickedScope(topicSelect.value);
    }else{
      await sectionsFor(topicSelect.value);if(params.get("section")){sectionSelect.value=params.get("section");}await loadScope();
    }
  }
})().catch(e=>{const status=$("status");if(status)status.textContent=e.message});
