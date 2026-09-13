async function exportDesignPackage(){
  if(!window.collageState?.selected?.size){document.querySelector("#status").textContent="Select at least one photo first.";return}
  const page=typeof readPageSpec==="function"?readPageSpec():{};
  document.querySelector("#status").textContent="Building design package…";
  try{
    const query=new URLSearchParams(location.search);
    const response=await fetch("/api/collage/design-packages",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({asset_ids:[...window.collageState.selected],page_spec:page,style:"organic",mode:"from_scratch",topic_id:query.get("topic"),section_id:query.get("section")})});
    const data=await response.json(); if(!response.ok) throw Error(data.error||`HTTP ${response.status}`);
    const link=document.createElement("a");link.href=data.download;link.download=`${data.package_id}.zip`;link.click();
    document.querySelector("#status").textContent=`Exported ${data.asset_count} assets. Upload the ZIP and contact sheet to ChatGPT.`;
  }catch(error){document.querySelector("#status").textContent=error.message}
}
document.querySelector("#export-design")?.addEventListener("click",exportDesignPackage);
