/* Pure state helpers shared by the browser and Node's test runner. */
(function(root){
  function nextIndex(index, delta, length){return Math.max(0,Math.min(length-1,index+delta))}
  function decisionFor(current, action){return current===action?'clear':action}
  function groups(photos){
    const result=[];let group=[];
    for(const photo of photos){
      const first=group[0],last=group.at(-1),time=Date.parse(photo.captured||'');
      const same=first&&photo.source_id&&photo.source_id===first.source_id&&Number.isFinite(time)&&
        Math.abs(time-Date.parse(last.captured))<=15000&&Math.abs(time-Date.parse(first.captured))<=60000&&group.length<15;
      if(!same){if(group.length>1)result.push(group);group=[]}group.push(photo);
    }
    if(group.length>1)result.push(group);return result;
  }
  const api={nextIndex,decisionFor,groups};if(typeof module!=='undefined')module.exports=api;else root.CullingState=api;
})(typeof window==='undefined'?{}:window);
