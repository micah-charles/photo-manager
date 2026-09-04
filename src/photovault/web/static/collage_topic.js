// Adds Topic as a second catalog source without changing the original folder POC.
(async function addTopicSource(){
  const folderSelect=document.getElementById("folders");
  if(!folderSelect || document.getElementById("source-kind")) return;
  const label=document.createElement("label");
  label.textContent="Source ";
  const kind=document.createElement("select");
  kind.id="source-kind";
  kind.innerHTML='<option value="folder">Folder</option><option value="topic">Topic</option>';
  label.prepend(kind);
  folderSelect.parentElement.before(label);
  const response=await fetch("/api/collage/topics");
  const payload=await response.json();
  const topics=payload.topics||[];
  const appendTopics=()=>{
    topics.forEach(topic=>{
      if([...folderSelect.options].some(option=>option.dataset.topicId===topic.id)) return;
      const option=document.createElement("option");
      option.value=topic.id;
      option.textContent=`${topic.name} · ${topic.item_count} photos`;
      option.dataset.topic="true";
      option.dataset.topicId=topic.id;
      folderSelect.append(option);
    });
  };
  const setVisible=()=>{
    const isTopic=kind.value==="topic";
    [...folderSelect.options].forEach(option=>{option.hidden=Boolean(option.dataset.topic)!==isTopic});
    const first=[...folderSelect.options].find(option=>!option.hidden);
    if(first) folderSelect.value=first.value;
  };
  appendTopics();
  folderSelect.dataset.topicSourceReady="true";
  kind.onchange=setVisible;
  const originalLoad=document.getElementById("load").onclick;
  document.getElementById("load").onclick=()=>{
    if(kind.value==="folder") return originalLoad();
    const status=document.getElementById("status");
    fetch(`/api/collage/photos?topic=${encodeURIComponent(folderSelect.value)}`)
      .then(r=>r.json())
      .then(data=>{
        window.state=window.state||{};
        state.photos=data.items||[];
        state.selected=new Set(state.photos.map(x=>x.asset_id));
        document.getElementById("photos").innerHTML=state.photos.map(x=>`<article class="photo" data-id="${x.asset_id}"><label><input type="checkbox" checked> ${x.filename}</label>${x.thumbnail?`<img loading="lazy" src="${x.thumbnail}" alt="${x.filename}">`:``}</article>`).join("");
        document.querySelectorAll(".photo").forEach(x=>x.onclick=e=>{if(e.target.tagName!=="INPUT")x.querySelector("input").checked=!state.selected.has(x.dataset.id);if(x.querySelector("input").checked)state.selected.add(x.dataset.id);else state.selected.delete(x.dataset.id)});
        status.textContent=`Loaded ${state.photos.length} topic photos.`;
      })
      .catch(e=>status.textContent=e.message);
  };
  // loadFolders() may finish after this file and replace all options.
  new MutationObserver(()=>{
    if(folderSelect.dataset.topicSourceReady!=="true") return;
    const hadTopics=folderSelect.querySelector("[data-topic]");
    appendTopics();
    if(!hadTopics || kind.value==="topic") setVisible();
  }).observe(folderSelect,{childList:true});
  setVisible();
})().catch(e=>{const status=document.getElementById("status");if(status)status.textContent=e.message});
