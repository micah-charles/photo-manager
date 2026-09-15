const state={data:null,topics:[],places:[],navigation:{people:[],places:[],tags:[],categories:[],sources:[]},month:"",year:"",view:"months",page:"library",pageTitle:"",filters:{},selected:new Set(),topicId:"",cursor:"",hasMore:false,loading:false,collapsedDays:new Set(),anchorId:"",androidSessionToken:"",androidFingerprint:""};
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const dateOnly=value=>String(value||"").slice(0,10);
async function api(url,options={}){const res=await fetch(url,{headers:{"Content-Type":"application/json",...(options.headers||{})},...options});const data=await res.json();if(!res.ok)throw new Error(data.error||`Request failed (${res.status})`);return data}
async function loadTopics(){const data=await api("/api/topics");state.topics=data.topics||[];state.places=data.places||[];state.navigation=await api("/api/navigation")}
function libraryQuery({day="",includeCursor=true}={}){const q=new URLSearchParams();if(day)q.set("day",day);else if(state.month)q.set("month",state.month);if(!day&&state.year){q.set("from",`${state.year}-01-01`);q.set("to",`${state.year}-12-31`)}if(state.topicId)q.set("event",state.topicId);Object.entries(state.filters).forEach(([key,value])=>{if(value)q.set(key,value)});if(includeCursor&&state.cursor)q.set("cursor",state.cursor);if($("search").value)q.set("search",$("search").value);q.set("type",$("media").value);return q}
async function load(reset=true){if(state.loading)return null;state.loading=true;const q=libraryQuery({includeCursor:!reset});q.set("limit","150");try{const page=await api(`/api/library?${q}`);if(reset||!state.data)state.data=page;else{state.data.items.push(...page.items);Object.entries(page.days||{}).forEach(([day,items])=>{state.data.days[day]=[...(state.data.days[day]||[]),...items]});state.data.day_counts={...(state.data.day_counts||{}),...(page.day_counts||{})}}state.cursor=page.next_cursor||"";state.hasMore=Boolean(page.has_more);state.loading=false;render();return page}catch(error){$("timeline").innerHTML=`<div class="empty-inspector">${esc(error.message)}</div>`;return null}finally{state.loading=false}}
async function loadMore(){if(state.hasMore&&!state.loading){let page=null;let guard=0;do{page=await load(false);guard++}while(state.hasMore&&guard<100&&page&&Object.keys(page.days||{}).every(day=>state.collapsedDays.has(day)));}}
async function refresh(){await loadTopics();state.cursor="";await load()}
function render(){const d=state.data;if(!d||d.error){$("timeline").innerHTML=`<div class="empty-inspector">${esc(d?.error||"Unable to load catalog")}</div>`;return}const topic=state.topics.find(x=>x.id===state.topicId);$("page-title").textContent=state.pageTitle||topic?.name||(state.year?state.year:(state.month?new Date(`${state.month}-01T00:00:00`).toLocaleDateString(undefined,{month:"long",year:"numeric"}):"All Photos"));$("summary").textContent=`${d.total.toLocaleString()} items · ${d.items.length.toLocaleString()} loaded · organised by capture day`;renderRail(d);const groupedView=Boolean(state.month||state.year||state.topicId);const days=groupedView?[...new Set([...Object.keys(d.day_counts||{}),...Object.keys(d.days||{})])]:Object.keys(d.days||{});const groups=days.map(day=>{const items=d.days?.[day]||[];const collapsed=state.collapsedDays.has(day);const total=d.day_counts?.[day]??items.length;const loaded=total>items.length?` · ${items.length.toLocaleString()} loaded`:"";return `<section class="day-group ${collapsed?"collapsed":""}" data-day="${esc(day)}"><div class="day-header"><div>${formatDay(day)} <span class="day-place">⌖ ${esc(items.find(x=>x.places)?.places||"")}</span></div><div class="day-tools"><button class="day-select" type="button" data-select-day="${esc(day)}">Select day</button><small>${total.toLocaleString()} items${loaded}</small><button class="day-toggle" type="button" data-toggle-day="${esc(day)}" aria-expanded="${!collapsed}">${collapsed?"＋":"−"}</button></div></div><div class="photo-grid">${items.map(card).join("")}</div></section>`}).join("");$("timeline").innerHTML=(groups||"<div class='empty-inspector'>No media in this view</div>")+`<div id="load-more" class="load-more ${state.hasMore?"":"hidden"}"><button class="outline">${state.hasMore?`Load more (${Math.max(d.total-d.items.length,0).toLocaleString()} remaining)`:"Load more"}</button></div>`;renderTopics();document.querySelectorAll(".month").forEach(x=>x.onclick=()=>{state.view="months";state.pageTitle="";state.topicId="";state.year="";state.month=x.dataset.month;state.selected.clear();state.cursor="";state.collapsedDays.clear();load()});document.querySelectorAll(".year").forEach(x=>x.onclick=()=>{state.view="years";state.pageTitle="";state.topicId="";state.month="";state.year=x.dataset.year;state.selected.clear();state.cursor="";state.collapsedDays.clear();load()});document.querySelectorAll(".rail-topic").forEach(x=>x.onclick=()=>{state.view="topics";state.pageTitle="";state.topicId=x.dataset.topicId;state.month="";state.year="";state.selected.clear();state.cursor="";state.collapsedDays.clear();load()});document.querySelectorAll(".day-toggle").forEach(x=>x.onclick=()=>{const day=x.dataset.toggleDay;state.collapsedDays.has(day)?state.collapsedDays.delete(day):state.collapsedDays.add(day);render()});document.querySelectorAll("[data-select-day]").forEach(x=>x.onclick=async()=>{const day=x.dataset.selectDay;const button=x;button.disabled=true;button.textContent="Selecting…";try{const result=await api(`/api/library/ids?${libraryQuery({day,includeCursor:false})}`);result.asset_ids.forEach(id=>state.selected.add(id));state.anchorId=state.data.days[day]?.at(-1)?.asset_id||state.anchorId;updateSelectionUI();showToast(`${result.count.toLocaleString()} photos selected for ${formatDay(day)}`)}catch(error){showToast(error.message,true)}finally{button.disabled=false;button.textContent="Select day"}});document.querySelectorAll(".photo-card").forEach(x=>{x.draggable=true;x.onclick=event=>select(x.dataset.id,event);x.ondragstart=event=>event.dataTransfer.setData("text/plain",x.dataset.id)});attachMarquee();updateSelectionUI();$("load-more")?.querySelector("button")?.addEventListener("click",loadMore);loadThumbnailStatus()}
function renderRail(d){const rail=$("month-list");if(state.view==="topics"){rail.innerHTML=state.topics.length?state.topics.map(x=>`<div class="month rail-topic" data-topic-id="${esc(x.id)}">${esc(x.name)}<span>›</span></div>`).join(""):"<div class=\"muted\">No Topics yet</div>";return}if(state.view==="years"){rail.innerHTML=(d.years||[]).map(year=>`<div class="month year ${year.key===state.year?"active":""}" data-year="${esc(year.key)}">${esc(year.label)}<span>${year.item_count.toLocaleString()} ›</span></div>`).join("")||"<div class=\"muted\">No dated media</div>";return}rail.innerHTML=(d.months||[]).map(m=>`<div class="month ${m.key===state.month&&!state.topicId?"active":""}" data-month="${esc(m.key)}">${esc(m.label)}<span>${m.item_count.toLocaleString()} ›</span></div>`).join("")}
function renderTopics(){$("topics-list").innerHTML=state.topics.length?state.topics.map(topicCard).join(""):"<div class=\"muted\">No Topics yet</div>";$("add-selected-topic").innerHTML=`<option value="">Add selected to Topic…</option>${state.topics.map(x=>`<option value="${esc(x.id)}">${esc(x.name)}</option>`).join("")}`;document.querySelectorAll(".topic-card").forEach(card=>{card.ondragover=e=>{e.preventDefault();card.classList.add("drop-target")};card.ondragleave=()=>card.classList.remove("drop-target");card.ondrop=async e=>{e.preventDefault();card.classList.remove("drop-target");await addAssets(card.dataset.id,[e.dataTransfer.getData("text/plain")])};card.onclick=e=>{if(e.target.closest("button"))return;state.topicId=card.dataset.id;state.month="";state.selected.clear();load()}});document.querySelectorAll("[data-edit-topic]").forEach(button=>button.onclick=e=>{e.stopPropagation();openTopic(state.topics.find(x=>x.id===button.dataset.editTopic))})}
function topicCard(x){const range=x.start_datetime?(dateOnly(x.start_datetime)+(x.end_datetime&&dateOnly(x.end_datetime)!==dateOnly(x.start_datetime)?` – ${dateOnly(x.end_datetime)}`:"")):"No date range";return `<article class="topic-card" data-id="${esc(x.id)}"><div class="topic-thumb ${x.item_count%2?"warm":"blue"}"></div><div class="topic-copy"><b>${esc(x.name)}</b><small>${esc(range)} · ${x.item_count} items</small><div class="topic-actions"><button class="text-button" data-edit-topic="${esc(x.id)}">Edit</button><button class="text-button danger-button" data-delete-topic="${esc(x.id)}">Delete</button><span>Drop photos here</span></div></div></article>`}
function formatDay(day){if(day==="Undated")return day;return new Date(`${day}T00:00:00`).toLocaleDateString(undefined,{weekday:"short",day:"2-digit",month:"short",year:"numeric"})}
function card(x){return `<article class="photo-card ${state.selected.has(x.asset_id)?"selected":""}" data-id="${esc(x.asset_id)}" title="Drag this photo onto a Topic">${x.thumbnail?`<img loading="lazy" src="${x.thumbnail}" alt="${esc(x.filename)}">`:`<div class="placeholder">${esc(x.media_type)}</div>`}<div class="photo-meta">${esc((x.captured||"").slice(11,16)||"—")} <span class="type-pill">${x.media_type==="VIDEO"?"◉":""}</span></div></article>`}
function select(id,event){const ordered=state.data?.items||[];if(event?.shiftKey&&state.anchorId){const a=ordered.findIndex(x=>x.asset_id===state.anchorId),b=ordered.findIndex(x=>x.asset_id===id);if(a>=0&&b>=0){ordered.slice(Math.min(a,b),Math.max(a,b)+1).forEach(x=>state.selected.add(x.asset_id))}}else state.selected.has(id)?state.selected.delete(id):state.selected.add(id);state.anchorId=id;updateSelectionUI();if(state.selected.size===1){const x=ordered.find(i=>i.asset_id===id);if(x)showInspector(x)}}
function updateSelectionUI(){document.querySelectorAll(".photo-card").forEach(x=>x.classList.toggle("selected",state.selected.has(x.dataset.id)));$("select-button").textContent=state.selected.size?`${state.selected.size.toLocaleString()} selected`:"Select";$("selection-count").textContent=state.selected.size?`${state.selected.size.toLocaleString()} selected photos`:"Selected photos";$("selection-bar").classList.toggle("hidden",!state.selected.size);let remove=$("remove-selected-topic");if(!remove){remove=document.createElement("button");remove.id="remove-selected-topic";remove.className="ghost danger-button";remove.textContent="Remove from Topic";$("selection-bar").insertBefore(remove,$("clear-selection"));remove.onclick=()=>removeAssets(state.topicId,[...state.selected])}remove.classList.toggle("hidden",!state.topicId);populateFolders()}
function populateFolders(){const select=$("folder-select");if(!select)return;const folders=[...new Set((state.data?.items||[]).map(x=>String(x.relative_path||"").split("/").slice(0,-1).join("/")).filter(Boolean))].sort();const current=select.value;select.innerHTML=`<option value="">Select a folder…</option>${folders.map(folder=>`<option value="${esc(folder)}">${esc(folder)}</option>`).join("")}`;select.value=folders.includes(current)?current:""}
async function selectFolder(){const folder=$("folder-select").value;if(!folder){showToast("Choose a folder first",true);return}try{const result=await api(`/api/library/ids?folder=${encodeURIComponent(folder)}`);result.asset_ids.forEach(id=>state.selected.add(id));updateSelectionUI();showToast(`${result.count.toLocaleString()} files selected from ${folder}`)}catch(error){showToast(error.message,true)}}
function attachMarquee(){document.querySelectorAll(".photo-grid").forEach(grid=>{let drag=null;grid.onpointerdown=e=>{if(e.button!==0||e.target.closest(".photo-card,.button,button,select"))return;drag={x:e.clientX,y:e.clientY,base:new Set(state.selected),moved:false};grid.setPointerCapture?.(e.pointerId)};grid.onpointermove=e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.hypot(dx,dy)<6)return;drag.moved=true;const left=Math.min(drag.x,e.clientX),right=Math.max(drag.x,e.clientX),top=Math.min(drag.y,e.clientY),bottom=Math.max(drag.y,e.clientY),box=$("marquee");box.classList.remove("hidden");box.style.left=`${left}px`;box.style.top=`${top}px`;box.style.width=`${right-left}px`;box.style.height=`${bottom-top}px`;const selected=new Set(drag.base);grid.querySelectorAll(".photo-card").forEach(card=>{const r=card.getBoundingClientRect();if(r.right>=left&&r.left<=right&&r.bottom>=top&&r.top<=bottom)selected.add(card.dataset.id)});state.selected=selected;updateSelectionUI()};grid.onpointerup=()=>{if(drag){$("marquee").classList.add("hidden");drag=null}}})}
function showInspector(x){$("inspector-empty").classList.add("hidden");const c=$("inspector-content");c.classList.remove("hidden");c.innerHTML=`${x.thumbnail?`<img src="${x.thumbnail}" alt="${esc(x.filename)}">`:""}<h2>${esc(x.filename)}</h2>${row("Date / Time",x.captured)}${row("Source",x.source||"—")}${row("Dimensions",x.width?`${x.width} × ${x.height}`:"—")}${row("File size",`${(x.size_bytes/1048576).toFixed(1)} MB`)}${row("Type",x.media_type)}<div class="section-title">ORGANISATION</div>${row("Topic",x.topics||"—")}${row("Place",x.places||"—")}${row("Tags",x.tags||"—")}${row("People",x.people||"—")}${row("Review",`${x.review_status||"UNREVIEWED"}${x.rating?` · ${x.rating}★`:""}`)}`}
function row(a,b){return `<div class="info-row"><span>${a}</span><b>${esc(b)}</b></div>`}
async function addAssets(topicId,assetIds){const ids=assetIds.filter(Boolean);if(!ids.length)return;try{const result=await api(`/api/topics/${encodeURIComponent(topicId)}/assets`,{method:"POST",body:JSON.stringify({asset_ids:ids})});state.selected.clear();state.anchorId="";showToast(`${result.added} photo${result.added===1?"":"s"} added to Topic`);await refresh()}catch(error){showToast(error.message,true)}}
async function removeAssets(topicId,assetIds){const ids=assetIds.filter(Boolean);if(!topicId||!ids.length)return;try{const result=await api(`/api/topics/${encodeURIComponent(topicId)}/assets`,{method:"DELETE",body:JSON.stringify({asset_ids:ids})});state.selected.clear();state.anchorId="";showToast(`${result.removed} photo${result.removed===1?"":"s"} removed from Topic`);await refresh()}catch(error){showToast(error.message,true)}}
async function deleteTopic(topicId){if(!topicId||!window.confirm("Delete this Topic? Photos will not be deleted."))return;try{await api(`/api/topics/${encodeURIComponent(topicId)}`,{method:"DELETE"});state.topicId="";state.selected.clear();showToast("Topic deleted");await refresh()}catch(error){showToast(error.message,true)}}
function openTopic(topic){$("topic-id").value=topic?.id||"";$("topic-name").value=topic?.name||"";$("topic-start").value=dateOnly(topic?.start_datetime);$("topic-end").value=dateOnly(topic?.end_datetime);$("topic-error").textContent="";$("topic-dialog").querySelector("h2").textContent=topic?"Edit Topic":"Create Topic";$("topic-dialog").showModal()}
async function saveTopic(event){event.preventDefault();const id=$("topic-id").value;const selected=[...state.selected];const body={name:$("topic-name").value,start_date:$("topic-start").value||null,end_date:$("topic-end").value||null};try{const result=await api(id?`/api/topics/${encodeURIComponent(id)}`:"/api/topics",{method:id?"PUT":"POST",body:JSON.stringify(body)});if(!id&&selected.length)await api(`/api/topics/${encodeURIComponent(result.id)}/assets`,{method:"POST",body:JSON.stringify({asset_ids:selected})});$("topic-dialog").close();showToast(id?"Topic updated":selected.length?`Topic created with ${selected.length} photos`:"Topic created");state.topicId=id||"";await refresh()}catch(error){$("topic-error").textContent=error.message}}
function showToast(message,error=false){const t=$("toast");t.textContent=message;t.className=`toast ${error?"error":""}`;clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>t.className="toast hidden",2800)}
$("filter-button").onclick=()=>$("filter-panel").classList.toggle("hidden");$("apply-filter").onclick=()=>{state.month="";state.topicId="";load()};$("sort-button").onclick=()=>showToast("Sort options will be added to the local catalog view.");$("create-topic").onclick=()=>openTopic();$("create-selected-topic").onclick=()=>openTopic();$("topic-form").onsubmit=saveTopic;$("topic-cancel").onclick=()=>$("topic-dialog").close();$("add-selected-topic").onchange=e=>{if(e.target.value)addAssets(e.target.value,[...state.selected]);e.target.value=""};loadTopics().then(load).catch(error=>showToast(error.message,true));
async function loadThumbnailStatus(){try{const d=await api("/api/thumbnails/status");$("thumbnail-status").textContent=`Previews ${d.ready.toLocaleString()} / ${d.total.toLocaleString()} · ${d.pending.toLocaleString()} pending`;if(d.job?.status==="running")setTimeout(loadThumbnailStatus,1500)}catch(error){$("thumbnail-status").textContent="Preview status unavailable"}}
$("build-thumbnails").onclick=async()=>{try{await api("/api/thumbnails/build",{method:"POST",body:"{}"});showToast("Preview generation started");loadThumbnailStatus()}catch(error){showToast(error.message,true)}};
function setActiveNav(index){document.querySelectorAll(".nav").forEach((item,i)=>item.classList.toggle("active",i===index))}
function showTopicsPage(){setActiveNav(2);$("page-title").textContent="Topics";$("summary").textContent=`${state.topics.length} Topics · choose one to open its photos`;$("timeline").innerHTML=state.topics.length?`<div class="topic-directory">${state.topics.map(x=>`<article class="topic-directory-card" data-topic-id="${esc(x.id)}"><div class="topic-thumb ${x.item_count%2?"warm":"blue"}"></div><div><h2>${esc(x.name)}</h2><p>${esc(dateOnly(x.start_datetime))}${x.end_datetime?` – ${esc(dateOnly(x.end_datetime))}`:""} · ${x.item_count} items</p><button class="text-button" data-edit-topic="${esc(x.id)}">Edit Topic</button></div></article>`).join("")}</div>`:`<div class="empty-inspector">No Topics yet. Use Create Topic to make one.</div>`;document.querySelectorAll(".topic-directory-card").forEach(card=>card.onclick=e=>{if(e.target.closest("button"))return;state.topicId=card.dataset.topicId;state.month="";state.cursor="";load()});document.querySelectorAll(".topic-directory-card [data-edit-topic]").forEach(button=>button.onclick=e=>{e.stopPropagation();openTopic(state.topics.find(x=>x.id===button.dataset.editTopic))})}
document.querySelectorAll(".rail-tab").forEach((tab,index)=>tab.onclick=()=>{state.view=["years","months","topics"][index];document.querySelectorAll(".rail-tab").forEach((item,i)=>item.classList.toggle("selected",i===index));state.selected.clear();state.topicId="";state.pageTitle="";state.filters={};state.cursor="";if(state.view==="years"){state.year="";state.month="";load();return}if(state.view==="months"){state.year="";state.month="";load();return}render()});
function showDirectory(title,entries,key){state.page="directory";state.pageTitle=title;setActiveNav({People:6,Places:7,Categories:8,Tags:9,Sources:10}[title]);$("page-title").textContent=title;$("summary").textContent=`${entries.length} available · choose one to browse`;$("timeline").innerHTML=entries.length?`<div class="topic-directory">${entries.map(x=>`<article class="topic-directory-card nav-entry" data-filter-key="${key}" data-filter-id="${esc(x.id)}"><div><h2>${esc(x.name)}</h2><p>${x.detail?`${esc(x.detail)} · `:""}${x.item_count} items</p></div></article>`).join("")}</div>`:`<div class="empty-inspector">No ${esc(title.toLowerCase())} in this catalog yet.</div>`;document.querySelectorAll(".nav-entry").forEach(entry=>entry.onclick=()=>{state.page="library";state.pageTitle=title;state.view="months";state.filters={[key]:entry.dataset.filterId};state.month="";state.year="";state.topicId="";state.selected.clear();state.cursor="";load()})}
function showStatusPage(title,message,index){state.page="status";state.pageTitle=title;setActiveNav(index);$("page-title").textContent=title;$("summary").textContent="PhotoVault local web interface";$("timeline").innerHTML=`<div class="empty-inspector">${esc(message)}</div>`}
function showBackupPage(){setActiveNav(12);$("page-title").textContent="Android Backup";$("summary").textContent="Plan and monitor a verified Wi-Fi backup";$("timeline").innerHTML=`<section class="backup-panel"><h2>Verified Android backup</h2><p class="dialog-help">The phone is read-only. Files are copied atomically, SHA-256 verified, and already verified files are skipped.</p><label>Companion URL<input id="backup-url" placeholder="http://192.168.x.x:8765"></label><label>Legacy token <span class="muted">(only for manual/older Companion)</span><input id="backup-token" type="password" placeholder="Token shown on the phone"></label><label>Secure session token <span class="muted">(filled after secure pairing)</span><input id="backup-session-token" type="password" placeholder="Optional 15-minute pairing session"></label><label>Android identity fingerprint <span class="muted">(needed for auto-reconnect)</span><input id="backup-android-fingerprint" placeholder="Filled after pairing"></label><label>Source folders<textarea id="backup-folders">DCIM/Camera</textarea></label><label>Destination directory<input id="backup-destination" placeholder="/path/to/PhotoVault-Backup"></label><div class="backup-row"><label>Media<select id="backup-media"><option value="ALL">Images and videos</option><option value="IMAGE">Images only</option><option value="VIDEO">Videos only</option></select></label><label>Workers<input id="backup-workers" type="number" min="1" max="8" value="5"></label></div><div class="dialog-actions"><button id="backup-plan" class="outline">Create plan</button><button id="backup-start" class="primary" disabled>Start backup</button><button id="backup-cancel" class="ghost" disabled>Cancel</button></div><pre id="backup-status" class="backup-status">No backup job created.</pre></section>`;$("backup-session-token").value=state.androidSessionToken;$("backup-android-fingerprint").value=state.androidFingerprint;$("backup-plan").onclick=async()=>{try{const job=await api("/api/backup/jobs",{method:"POST",body:JSON.stringify({url:$("backup-url").value,token:$("backup-token").value,session_token:$("backup-session-token").value||null,android_fingerprint:$("backup-android-fingerprint").value||null,folders:$("backup-folders").value.split(/\n|,/).map(x=>x.trim()).filter(Boolean),destination:$("backup-destination").value,media_filter:$("backup-media").value,workers:Number($("backup-workers").value),fsync_mode:"batch",batch_files:25})});state.backupJobId=job.job_id;$("backup-start").disabled=false;$("backup-status").textContent=JSON.stringify(job,null,2)}catch(error){$("backup-status").textContent=error.message}};$("backup-start").onclick=async()=>{await api(`/api/backup/jobs/${state.backupJobId}/start`,{method:"POST"});$("backup-start").disabled=true;$("backup-cancel").disabled=false;pollBackup()};$("backup-cancel").onclick=async()=>{await api(`/api/backup/jobs/${state.backupJobId}/cancel`,{method:"POST"});pollBackup()}}
async function pollBackup(){if(!state.backupJobId)return;try{const job=await api(`/api/backup/jobs/${state.backupJobId}`);$("backup-status").textContent=JSON.stringify(job,null,2);if(["RUNNING","PLANNED"].includes(job.status))setTimeout(pollBackup,1500)}catch(error){$("backup-status").textContent=error.message}}
function navigate(index){if(index===2){showTopicsPage();return}if(index===11){showStatusPage("Import","Import controls are not connected in this build. Existing catalog media remains unchanged.",index);return}if(index===12){showBackupPage();return}if(index===13){showStatusPage("Settings","Settings are not connected in this build. The local catalog and originals are unchanged.",index);return}if(index>=6&&index<=10){const names=["People","Places","Categories","Tags","Sources"];const key={People:"people",Places:"places",Categories:"categories",Tags:"tags",Sources:"sources"}[names[index-6]];const filterKey={people:"person",places:"place",categories:"category",tags:"tag",sources:"source"}[key];showDirectory(names[index-6],state.navigation[key]||[],filterKey);return}setActiveNav(index);state.page="library";state.pageTitle=index===3?"Recently Added":index===4?"Review":index===5?"Rejected":"";state.view="months";document.querySelectorAll(".rail-tab").forEach((tab,i)=>tab.classList.toggle("selected",i===1));state.topicId="";state.year="";state.month="";state.cursor="";state.filters=index===3?{recent:"1"}:index===4?{review:"UNREVIEWED"}:index===5?{review:"REJECTED",include_rejected:"1"}:{};load()}
document.querySelectorAll(".nav").forEach((item,index)=>item.onclick=()=>navigate(index));
$("select-folder").onclick=selectFolder;$("clear-selection").onclick=()=>{state.selected.clear();state.anchorId="";updateSelectionUI()};
document.addEventListener("click",async event=>{if(event.target?.id!=="backup-start")return;event.stopImmediatePropagation();const status=$("backup-status"),button=$("backup-start");if(!state.backupJobId){status.textContent="Create a backup plan first.";return}button.disabled=true;status.textContent="Starting backup job…";try{await api(`/api/backup/jobs/${encodeURIComponent(state.backupJobId)}/start`,{method:"POST"});$("backup-cancel").disabled=false;pollBackup()}catch(error){button.disabled=false;status.textContent=`Unable to start backup: ${error.message}`;showToast(error.message,true)}},true);
document.addEventListener("click",event=>{const button=event.target.closest?.("[data-delete-topic]");if(button){event.preventDefault();event.stopPropagation();deleteTopic(button.dataset.deleteTopic)}});

async function loadAndroidDevices(){
  const host=$("android-devices"); if(!host)return;
  try{
    const [result,trustedResult]=await Promise.all([api("/api/android/devices"),api("/api/android/trusted")]);
    const devices=result.devices||[], trusted=trustedResult.devices||[];
    const trustedHtml=trusted.map(device=>`<article class="android-device-card trusted"><div><strong>${esc(device.display_name)}</strong><p>Trusted identity · last authenticated ${esc(device.last_authenticated_at||"never")}</p></div><button class="ghost danger-button" data-revoke-device="${esc(device.device_id)}">Forget</button></article>`).join("");
    const deviceHtml=devices.map(device=>`<article class="android-device-card"><div><strong>${esc(device.display_name)}</strong><p>${esc(device.host)}:${device.port} · ${esc(device.status)} · ${device.pairing?"Ready to pair":"Legacy/manual connection"}</p></div><button class="outline" data-pair-host="${esc(device.host)}" data-pair-port="${device.port}" ${device.pairing?"":"disabled"}>${device.pairing?"Pair":"Advanced"}</button></article>`).join("");
    host.innerHTML=(trustedHtml?"<h4>Trusted devices</h4>"+trustedHtml:"")+(deviceHtml?"<h4>Discovered devices</h4>"+deviceHtml:"<p class=\"dialog-help\">Looking for your phones… Make sure PhotoVault Companion is open and both devices are on the same network.</p>");
    host.querySelectorAll("[data-revoke-device]").forEach(button=>button.onclick=async()=>{if(!window.confirm("Forget this trusted Android device? You can pair it again later."))return;button.disabled=true;try{await api(`/api/android/trusted/${encodeURIComponent(button.dataset.revokeDevice)}`,{method:"DELETE"});showToast("Android device forgotten");loadAndroidDevices()}catch(error){button.disabled=false;showToast(error.message,true)}});
    host.querySelectorAll("[data-pair-host]").forEach(button=>button.onclick=async()=>{button.disabled=true;button.textContent="Pairing…";try{const pair=await api("/api/android/pair",{method:"POST",body:JSON.stringify({host:button.dataset.pairHost,port:Number(button.dataset.pairPort)})});button.dataset.androidFingerprint=pair.fingerprint||"";state.androidFingerprint=pair.fingerprint||"";showToast(`Check both devices: ${pair.sas}`);button.textContent="Confirm number";button.onclick=async()=>{const confirmed=await api(`/api/android/pair/${encodeURIComponent(pair.session_id)}/confirm`,{method:"POST",body:"{}"});if(confirmed.paired&&confirmed.session_token){state.androidSessionToken=confirmed.session_token;if($("backup-session-token"))$("backup-session-token").value=confirmed.session_token;showToast("Secure transfer session ready; long backups will reconnect automatically")}button.textContent=confirmed.paired?"Securely paired":"Waiting for phone confirmation";button.disabled=confirmed.paired}}catch(error){button.disabled=false;button.textContent="Pair";showToast(error.message,true)}});
  }
  catch(error){host.textContent="Automatic discovery unavailable; use Advanced manual connection."}
  if(document.getElementById("android-devices")) setTimeout(loadAndroidDevices,3000);
}
const legacyShowBackupPage=showBackupPage;
showBackupPage=function(){legacyShowBackupPage();const panel=document.querySelector(".backup-panel");if(!panel)return;const devices=document.createElement("section");devices.className="android-devices";devices.innerHTML="<h3>Your Android devices</h3><div id=\"android-devices\"><p class=\"dialog-help\">Searching…</p></div>";panel.parentNode.insertBefore(devices,panel);loadAndroidDevices()};

function sourceClass(value){let hash=0;for(const char of String(value||""))hash=(hash*31+char.charCodeAt(0))%5;return `source-${hash}`}
function card(x){const source=esc(x.source||"Unknown source");const sourceKey=esc((x.source_id||"").slice(-6));return `<article class="photo-card ${state.selected.has(x.asset_id)?"selected":""} ${sourceClass(x.source_id||x.source)}" data-id="${esc(x.asset_id)}" data-source-id="${esc(x.source_id||"")}" title="Drag this photo onto a Topic">${x.thumbnail?`<img loading="lazy" src="${x.thumbnail}" alt="${esc(x.filename)}">`:`<div class="placeholder">${esc(x.media_type)}</div>`}<span class="source-badge" title="${source} (${sourceKey})"><span class="source-dot"></span>${source} · ${sourceKey}</span><div class="photo-meta">${esc((x.captured||"").slice(11,16)||"—")} <span class="type-pill">${x.media_type==="VIDEO"?"◉":""}</span></div></article>`}
function ensureSourceFilter(){const panel=$("filter-panel");if(!panel||$("source-filter"))return;const label=document.createElement("label");label.innerHTML=`Source <select id="source-filter"><option value="">All sources</option></select>`;panel.insertBefore(label,panel.querySelector("button"));$("source-filter").onchange=e=>{state.filters.source=e.target.value;state.cursor="";load()}}
function syncSourceFilter(){ensureSourceFilter();const select=$("source-filter");if(!select)return;const current=select.value;const sources=(state.navigation?.sources||[]).filter(source=>Number(source.item_count||0)>0);select.innerHTML=`<option value="">All sources</option>${sources.map(source=>`<option value="${esc(source.id)}">${esc(source.name)} · ${esc(String(source.id).slice(-6))} (${source.item_count})</option>`).join("")}`;select.value=current;}
setInterval(syncSourceFilter,500);
const originalShowInspector=showInspector;
showInspector=function(x){originalShowInspector(x);const content=$("inspector-content");if(!content||content.querySelector(".original-button"))return;const button=document.createElement("button");button.className="primary original-button";button.textContent=x.volume_status==="CONNECTED"?"Open original":"Original offline";button.disabled=x.volume_status!=="CONNECTED";button.title=x.volume_status==="CONNECTED"?"Open the original from the connected volume":"Connect the source volume to open the original";if(!button.disabled)button.onclick=()=>window.open(`/api/original/${encodeURIComponent(x.asset_id)}`,"_blank","noopener");content.insertBefore(button,content.querySelector("h2"));};

function ensureSourcePicker(){
  const tools=$("folder-tools");
  if(!tools||$("source-picker"))return;
  const wrap=document.createElement("div");
  wrap.id="source-picker";
  wrap.className="source-picker";
  wrap.innerHTML=`<span class="source-picker-label">Sources</span><label class="source-check all"><input type="checkbox" data-source-all>All sources</label><span data-source-options></span>`;
  tools.prepend(wrap);
}
function syncSourcePicker(){
  ensureSourcePicker();
  const wrap=$("source-picker"), options=wrap?.querySelector("[data-source-options]");
  if(!options)return;
  const sources=(state.navigation?.sources||[]).filter(source=>Number(source.item_count||0)>0);
  const selected=new Set(String(state.filters.source||"").split(",").filter(Boolean));
  options.innerHTML=sources.map(source=>{
    const id=String(source.id), checked=!selected.size||selected.has(id);
    return `<label class="source-check"><input type="checkbox" value="${esc(id)}" ${checked?"checked":""}>${esc(source.name||"Unknown source")} · ${esc(id.slice(-6))}<small>${Number(source.item_count||0).toLocaleString()}</small></label>`;
  }).join("");
  options.querySelectorAll("input").forEach(input=>input.onchange=()=>{
    const checks=[...options.querySelectorAll("input:checked")].map(item=>item.value);
    state.filters.source=checks.length===sources.length?"":checks.join(",");
    state.cursor="";
    load();
  });
  const allBox=wrap.querySelector("[data-source-all]");
  allBox.checked=!selected.size;
  allBox.onchange=()=>{state.filters.source="";state.cursor="";load()};
}
setInterval(syncSourcePicker,500);
const originalShowTopicsPage=showTopicsPage;
showTopicsPage=function(){originalShowTopicsPage();document.querySelectorAll(".topic-directory-card[data-topic-id]").forEach(card=>{if(card.querySelector("[data-delete-topic]"))return;const button=document.createElement("button");button.className="text-button danger-button";button.dataset.deleteTopic=card.dataset.topicId;button.textContent="Delete Topic";card.querySelector("div:last-child")?.appendChild(button)})};
const collageNav=document.createElement("button");collageNav.className="nav";collageNav.textContent="✦ Experimental Collage";collageNav.onclick=()=>{window.location.href="/experimental/collage"};document.querySelector(".sidebar")?.append(collageNav);
document.addEventListener("click",event=>{const card=event.target.closest?.(".topic-card[data-id],.topic-directory-card[data-topic-id]");if(card&&!event.target.closest("button")){event.preventDefault();event.stopImmediatePropagation();window.location.href=`/topic-workspace?topic=${encodeURIComponent(card.dataset.id||card.dataset.topicId)}`}},true);

let sourceRefreshPollTimer=null;
let sourceRefreshLastJobId="";
function sourceRefreshActive(job){return Boolean(job&&["queued","running"].includes(job.status))}
function sourceRefreshSummary(job){
  if(!job)return "Choose a registered folder to scan for new photos. The scan is incremental and does not change originals.";
  if(job.status==="queued")return "Refresh queued…";
  if(job.status==="running")return job.stage==="scanning"?"Scanning for new or changed media…":"Building missing thumbnails…";
  if(job.status==="failed")return `Refresh failed: ${job.error||"unknown error"}`;
  return `Last refresh: ${Number(job.files_catalogued||0).toLocaleString()} files checked, ${Number(job.errors||0)} errors.`;
}
function renderSourcesPage(volumes,job,thumbs){
  const active=sourceRefreshActive(job);
  const thumbJob=thumbs?.job;
  const thumbText=thumbJob&&thumbJob.status==="running"?`Building previews: ${Number(thumbJob.processed||0).toLocaleString()} checked · ${Number(thumbJob.generated||0).toLocaleString()} generated`:`Preview cache: ${Number(thumbs?.ready||0).toLocaleString()} ready · ${Number(thumbs?.pending||0).toLocaleString()} pending`;
  const cards=volumes.map(volume=>{
    const ready=volume.status==="CONNECTED"&&volume.path_exists;
    const current=active&&job.volume_id===volume.id;
    const progress=current?`<p class="source-progress">${esc(sourceRefreshSummary(job))}${job.stage==="scanning"&&job.files_seen?` · ${Number(job.files_seen).toLocaleString()} files seen`:""}</p>`:"";
    return `<article class="source-volume-card"><div class="source-volume-copy"><div class="source-volume-title"><h3>${esc(volume.display_name)}</h3><span class="source-state ${ready?"connected":"offline"}">${ready?"Connected":"Unavailable"}</span></div><p>${Number(volume.item_count||0).toLocaleString()} catalogued items</p><code title="${esc(volume.mount_path||"")}">${esc(volume.mount_path||"No folder path registered")}</code>${progress}</div><button class="outline source-refresh-button" data-refresh-volume="${esc(volume.id)}" ${ready&&!active?"":"disabled"}>${current?"Refreshing…":"Refresh source"}</button></article>`;
  }).join("");
  $("page-title").textContent="Sources";
  $("summary").textContent=`${volumes.length} registered folder${volumes.length===1?"":"s"} · ${thumbText}`;
  $("timeline").innerHTML=`<section class="sources-panel"><div class="source-refresh-header"><div><h2>Refresh source data</h2><p>Scan a connected folder for new photos, then generate missing thumbnails automatically.</p><p class="source-refresh-note">Existing catalog records, source IDs and original files remain unchanged.</p></div><span class="source-refresh-status ${active?"is-active":""}">${esc(sourceRefreshSummary(job))}</span></div><div class="source-volume-list">${cards||"<div class=\"empty-inspector\">No registered source folders.</div>"}</div></section>`;
  document.querySelectorAll("[data-refresh-volume]").forEach(button=>button.onclick=async()=>{
    button.disabled=true;button.textContent="Starting…";
    try{await api(`/api/volumes/${encodeURIComponent(button.dataset.refreshVolume)}/refresh`,{method:"POST",body:"{}"});sourceRefreshLastJobId="pending";showToast("Source refresh started; new thumbnails will be generated automatically.");pollSourceRefresh()}catch(error){button.disabled=false;button.textContent="Refresh source";showToast(error.message,true)}
  });
}
async function pollSourceRefresh(){
  if(sourceRefreshPollTimer){clearTimeout(sourceRefreshPollTimer);sourceRefreshPollTimer=null}
  if(state.page!=="directory"||state.pageTitle!=="Sources")return;
  try{
    const [sourceData,thumbs]=await Promise.all([api("/api/volumes"),api("/api/thumbnails/status")]);
    const job=sourceData.refresh_job;
    renderSourcesPage(sourceData.volumes||[],job,thumbs);
    const thumbnailActive=thumbs?.job?.status==="running";
    if(sourceRefreshActive(job)||thumbnailActive){if(job?.job_id)sourceRefreshLastJobId=job.job_id;sourceRefreshPollTimer=setTimeout(pollSourceRefresh,1000);return}
    if(sourceRefreshLastJobId&&job&&job.job_id===sourceRefreshLastJobId){
      sourceRefreshLastJobId="";
      state.navigation=await api("/api/navigation");
      if(job.status==="complete")showToast(`Source refreshed: ${Number(job.files_catalogued||0).toLocaleString()} files checked.`);
      else if(job.status==="failed")showToast(`Source refresh failed: ${job.error||"unknown error"}`,true);
      renderSourcesPage(sourceData.volumes||[],job,thumbs);
    }
  }catch(error){$("timeline").innerHTML=`<div class="empty-inspector">${esc(error.message)}</div>`}
}
async function showSourcesPage(){
  state.page="directory";state.pageTitle="Sources";setActiveNav(10);$("page-title").textContent="Sources";$("summary").textContent="Loading registered source folders…";$("timeline").innerHTML=`<div class="empty-inspector">Loading source folders…</div>`;
  try{const [sourceData,thumbs]=await Promise.all([api("/api/volumes"),api("/api/thumbnails/status")]);renderSourcesPage(sourceData.volumes||[],sourceData.refresh_job,thumbs);if(sourceRefreshActive(sourceData.refresh_job)||thumbs?.job?.status==="running")pollSourceRefresh()}catch(error){$("timeline").innerHTML=`<div class="empty-inspector">${esc(error.message)}</div>`}
}
const legacyShowDirectory=showDirectory;
showDirectory=function(title,entries,key){if(title==="Sources"){showSourcesPage();return}legacyShowDirectory(title,entries,key)};

// Library date filters and sorting are deliberately kept outside the catalog
// identity state. They only change the current view and never mutate assets.
state.dateFilter={day:"",from:"",to:""};
state.sort="captured_desc_id";
state.offset=0;

function activeDateFilter(){return state.dateFilter||{day:"",from:"",to:""}}
function dateFilterText(){const filter=activeDateFilter();if(filter.day)return ` · ${filter.day}`;if(filter.from||filter.to)return ` · ${filter.from||"Any date"} – ${filter.to||"Any date"}`;return ""}
function syncDateFilterControls(){const filter=activeDateFilter();if($("filter-day"))$("filter-day").value=filter.day||"";if($("filter-from"))$("filter-from").value=filter.from||"";if($("filter-to"))$("filter-to").value=filter.to||"";if($("sort-select"))$("sort-select").value=state.sort||"captured_desc_id"}

libraryQuery=function({day="",includeCursor=true}={}){
  const q=new URLSearchParams(),filter=activeDateFilter(),explicitDay=Boolean(day),hasDate=Boolean(filter.day||filter.from||filter.to);
  if(explicitDay)q.set("day",day);
  else if(filter.day)q.set("day",filter.day);
  else if(filter.from||filter.to){if(filter.from)q.set("from",`${filter.from} 00:00:00`);if(filter.to)q.set("to",`${filter.to} 23:59:59`)}
  else if(state.month)q.set("month",state.month);
  if(!explicitDay&&!hasDate&&state.year){q.set("from",`${state.year}-01-01`);q.set("to",`${state.year}-12-31`)}
  if(state.topicId)q.set("event",state.topicId);
  Object.entries(state.filters).forEach(([key,value])=>{if(value)q.set(key,value)});
  if(includeCursor&&state.offset)q.set("offset",String(state.offset));
  if($("search").value)q.set("search",$("search").value);
  q.set("type",$("media").value);q.set("sort",state.sort||"captured_desc_id");
  return q;
};

load=async function(reset=true){
  if(state.loading)return null;
  if(reset){state.cursor="";state.offset=0;if(state.month||state.year||state.topicId)state.dateFilter={day:"",from:"",to:""}}
  state.loading=true;
  const requestOffset=state.offset||0,q=libraryQuery({includeCursor:!reset});
  q.set("limit","150");
  try{
    const page=await api(`/api/library?${q}`);
    if(reset||!state.data)state.data=page;
    else{state.data.items.push(...(page.items||[]));state.data.days=state.data.days||{};Object.entries(page.days||{}).forEach(([day,items])=>{state.data.days[day]=[...(state.data.days[day]||[]),...items]});state.data.day_counts={...(state.data.day_counts||{}),...(page.day_counts||{})}}
    state.cursor=page.next_cursor||"";state.offset=Number(page.next_offset??(requestOffset+(page.items||[]).length));state.hasMore=Boolean(page.has_more);render();return page;
  }catch(error){$("timeline").innerHTML=`<div class="empty-inspector">${esc(error.message)}</div>`;return null}
  finally{state.loading=false}
};

loadMore=async function(){if(state.hasMore&&!state.loading)await load(false)};
async function loadToEnd(){
  if(state.loading)return;
  let guard=0;
  while(state.hasMore&&guard<10000){const before=state.offset;const page=await load(false);guard++;if(!page||state.offset<=before)break}
}

const libraryRender=render;
render=function(){
  libraryRender();
  const summary=$("summary"),filterText=dateFilterText();
  if(summary&&filterText)summary.textContent+=filterText;
  const host=$("load-more");
  if(!host||!state.hasMore)return;
  host.classList.remove("hidden");
  if(!host.querySelector("[data-load-all]")){
    const button=document.createElement("button");button.type="button";button.className="outline";button.dataset.loadAll="1";button.textContent="Load all to end";button.onclick=loadToEnd;host.appendChild(button);
  }
};

function applyLibraryView(){
  const day=$("filter-day").value,from=$("filter-from").value,to=$("filter-to").value;
  if(day&&(from||to)){showToast("Use Single day or From / To, not both.",true);return}
  if(from&&to&&from>to){showToast("The From date must not be after the To date.",true);return}
  state.dateFilter={day,from,to};state.sort=$("sort-select").value||"captured_desc_id";state.month="";state.year="";state.topicId="";state.pageTitle="";state.selected.clear();state.anchorId="";state.cursor="";state.offset=0;load(true)
}
function clearLibraryView(){
  $("search").value="";$("media").value="ALL";state.dateFilter={day:"",from:"",to:""};state.sort="captured_desc_id";state.month="";state.year="";state.topicId="";state.pageTitle="";state.selected.clear();state.anchorId="";state.cursor="";state.offset=0;syncDateFilterControls();load(true)
}
$("filter-button").onclick=()=>{$("filter-panel").classList.toggle("hidden");syncDateFilterControls()};
$("sort-button").onclick=()=>{$("filter-panel").classList.remove("hidden");syncDateFilterControls();$("sort-select")?.focus()};
$("apply-filter").onclick=applyLibraryView;
$("clear-filter").onclick=clearLibraryView;
syncDateFilterControls();

function bindDateOnlyHeader(section){
  section.querySelector(".day-toggle")?.addEventListener("click",()=>{const day=section.dataset.day;state.collapsedDays.has(day)?state.collapsedDays.delete(day):state.collapsedDays.add(day);render()});
  section.querySelector(".day-select")?.addEventListener("click",async()=>{const day=section.dataset.day,button=section.querySelector(".day-select");button.disabled=true;button.textContent="Selecting…";try{const result=await api(`/api/library/ids?${libraryQuery({day,includeCursor:false})}`);result.asset_ids.forEach(id=>state.selected.add(id));updateSelectionUI();showToast(`${result.count.toLocaleString()} photos selected for ${formatDay(day)}`)}catch(error){showToast(error.message,true)}finally{button.disabled=false;button.textContent="Select day"}});
}
function addMissingDateHeaders(){
  const filter=activeDateFilter(),data=state.data,timeline=$("timeline"),loadMore=$("load-more");
  if(!filter.day&&!filter.from&&!filter.to||!data?.day_counts||!timeline||!loadMore)return;
  Object.keys(data.day_counts).forEach(day=>{
    if(timeline.querySelector(`[data-day="${CSS.escape(day)}"]`))return;
    const section=document.createElement("section");section.className="day-group";section.dataset.day=day;const total=Number(data.day_counts[day]||0);section.innerHTML=`<div class="day-header"><div>${formatDay(day)}</div><div class="day-tools"><button class="day-select" type="button">Select day</button><small>${total.toLocaleString()} items · not loaded</small><button class="day-toggle" type="button" aria-expanded="true">−</button></div></div><div class="photo-grid"></div>`;timeline.insertBefore(section,loadMore);bindDateOnlyHeader(section);
  });
}
const dateHeaderRender=render;
render=function(){dateHeaderRender();addMissingDateHeaders()};
