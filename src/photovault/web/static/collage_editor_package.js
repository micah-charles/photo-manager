document.querySelector("#export-package")?.addEventListener("click",async()=>{
  const s=window.fabricSpikeState, doc=s?.doc;
  if(!doc){document.querySelector("#status").textContent="Open a candidate first.";return}
  const assets=[...new Set((doc.elements||doc.frames||[])
    .filter(x=>x.type==="photo" || !x.type)
    .map(x=>x.photo_id||x.asset_id)
    .filter(Boolean))];
  document.querySelector("#status").textContent="Building ChatGPT design package…";
  try{
    const r=await fetch("/api/collage/design-packages",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({asset_ids:assets,page_spec:doc.page_spec||{},mode:"improve_existing",style:doc.style||"organic",style_intent:doc.style_intent||doc.metadata?.style_intent||"organic",current_document:doc})});
    const d=await r.json();if(!r.ok)throw Error(d.error||`HTTP ${r.status}`);
    const a=document.createElement("a");a.href=d.download;a.download=`${d.package_id}.zip`;a.click();document.querySelector("#status").textContent=`Exported ${d.asset_count} assets for ChatGPT.`;
  }catch(e){document.querySelector("#status").textContent=e.message}
});
