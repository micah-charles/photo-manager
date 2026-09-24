/* Read-only, opt-in art-direction review. Manifest: [{key, sectionId, title,
 * subtitle, caption, semantics, heroIds?, presets?}]. No catalog writes; private
 * manifests and renders live outside the repository. Reuse a saved source.json
 * for an exact before/after comparison. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const library = require('../src/photovault/web/static/collage_template_library.js');
const base = process.env.PHOTO_MANAGER_URL || 'http://127.0.0.1:8777';
const out = path.resolve(process.argv[3]);
const manifest = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
async function get(url) {
  const r = await fetch(base + url); if (!r.ok) throw Error(`${url}: ${r.status}`); return r.json();
}
(async () => {
  fs.mkdirSync(out, {recursive:true});
  const cases = [];
  for (const source of manifest) {
    if (!source.photos) {
      const ids = (await get(`/api/sections/${encodeURIComponent(source.sectionId)}/assets`)).asset_ids;
      const data = await get('/api/collage/photos?' + ids.map(id=>'asset_id='+encodeURIComponent(id)).join('&'));
      source.photos = ids.map(id=>data.items.find(p=>p.asset_id===id));
      assert(source.photos.every(Boolean), 'Never skip an unavailable source');
    }
    for (const preset of source.presets || ['a4-portrait']) for (const family of library.families) {
      const built = library.build({...source, familyId:family.id, page:{preset_id:preset}});
      const photos = built.spec.alternatives[0].elements.filter(e=>e.type==='photo');
      assert.equal(photos.length, source.photos.length);
      assert.deepEqual(new Set(photos.map(p=>p.asset_id)), new Set(source.photos.map(p=>p.asset_id)));
      cases.push({key:`${source.key}-${preset}-${family.id}`, group:`${source.key}-${preset}`, source, ...built, familyName:family.name});
    }
  }
  fs.writeFileSync(path.join(out,'source.json'), JSON.stringify(manifest,null,2));
  const docs = JSON.parse(execFileSync(process.env.PYTHON || 'python3',['-c',`
import json,sys
from photovault.collage.design_formats import validate_and_repair_design_spec,to_collage_document,validate_collage_document
out=[]
for spec in json.load(sys.stdin):
 ids={a['asset_id']:{} for a in spec['assets']}
 checked,report=validate_and_repair_design_spec(spec,set(ids))
 assert not report['errors'],report
 doc=to_collage_document(checked,asset_map=ids)
 validate_collage_document(doc,set(ids))
 out.append({'document':doc,'validation':report})
json.dump(out,sys.stdout)
`],{input:JSON.stringify(cases.map(c=>c.spec)),cwd:path.resolve(__dirname,'..'),env:{...process.env,PYTHONPATH:'src'},maxBuffer:50*1024*1024}));
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1600,height:1050}});
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    // Guard against accidental saves if editor bootstrap behavior changes.
    await page.route('**/api/**', route => route.request().method()==='GET' ? route.continue() : route.abort());
    await page.goto(base+'/experimental/collage/fabric-v2');
    await page.waitForFunction(()=>typeof renderDocument==='function');
    const evidence=[];
    for (let i=0;i<cases.length;i++) {
      const c=cases[i];
      const result=await page.evaluate(async ({doc,items})=>{
        const canvas=new fabric.StaticCanvas(document.createElement('canvas'),{enableRetinaScaling:false});
        try {
          const normalized=normalizeDocument(doc);
          const report=await renderDocument(canvas,normalized,{assetMap:new Map(items.map(p=>[p.asset_id,p])),interactive:false,renderMode:'funnel',strictAssets:true});
          return {report,png:canvas.toDataURL({format:'png',multiplier:1})};
        } finally {canvas.dispose();}
      },{doc:docs[i].document,items:c.source.photos});
      fs.writeFileSync(path.join(out,c.key+'.png'),Buffer.from(result.png.split(',')[1],'base64'));
      evidence.push({key:c.key,diagnostics:c.diagnostics,validation:docs[i].validation,render:result.report});
      if(i%12===11) console.log(`Rendered ${i+1}/${cases.length}`);
    }
    for(const group of new Set(cases.map(c=>c.group))) {
      await page.setContent('<style>body{margin:12px;background:#ddd;font:15px sans-serif}.grid{display:grid;grid-template-columns:repeat(4,365px);gap:12px}article{padding:8px;background:white}img{width:100%;display:block}h3{margin:0 0 8px;font-size:15px}</style><div class="grid"></div>');
      for(const c of cases.filter(c=>c.group===group)) await page.evaluate(({name,png})=>{
        const article=document.createElement('article'),h=document.createElement('h3'),im=document.createElement('img');h.textContent=name;im.src=png;article.append(h,im);document.querySelector('.grid').append(article);
      },{name:c.familyName,png:'data:image/png;base64,'+fs.readFileSync(path.join(out,c.key+'.png')).toString('base64')});
      await page.evaluate(()=>Promise.all([...document.images].map(im=>im.decode())));
      await page.screenshot({path:path.join(out,'board-'+group+'.png'),fullPage:true});
    }
    fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({version:library.VERSION,errors,evidence},null,2));
    assert.equal(errors.length,0,JSON.stringify(errors));
    assert.equal(evidence.filter(e=>e.render.failed_element_ids.length || e.render.warnings.length).length,0,'Inspect report.json');
    console.log(`Verified ${cases.length} pages; sources and comparisons: ${out}`);
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
