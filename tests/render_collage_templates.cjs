/* Opt-in visual regression harness. Uses an isolated browser and the production
 * renderer; never writes the catalog or saves/replaces a user's document.
 * node tests/render_collage_templates.cjs <catalog-photo-json> <output-directory>
 * PLAYWRIGHT_MODULE may name an installed Playwright package. */
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const library = require('../src/photovault/web/static/collage_template_library.js');
const source = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const photos = (source.items || source).filter(p => p.media_type !== 'VIDEO');
const out = path.resolve(process.argv[3]); fs.mkdirSync(out, {recursive: true});
const cases = [];
for (const preset of ['a4-portrait', 'a4-landscape', 'large-square']) {
  for (const count of (preset === 'large-square' ? [12] : [10, 15, 20])) {
    // Sample across the source, not fifteen nearly identical burst frames.
    const items = Array.from({length: count}, (_, i) => photos[Math.floor(i * photos.length / count)]);
    for (const family of library.families) {
      const built = library.build({familyId: family.id, photos: items, page: {preset_id: preset},
        title: 'A Welsh spring | 春日同行', subtitle: '14 April 2026 · A day with family',
        caption: 'Gardens, quiet paths and moments together. 花園裡，留下同行的回憶。'});
      cases.push({key: `${preset}-${count}-${family.id}`, family: family.name, items, spec: built.spec, diagnostics: built.diagnostics});
    }
  }
}
const docs = JSON.parse(execFileSync(process.env.PYTHON || 'python3', ['-c', `
import sys,json
from photovault.collage.design_formats import validate_and_repair_design_spec,to_collage_document
result=[]
for spec in json.load(sys.stdin):
 ids={a['asset_id']:{} for a in spec['assets']}
 checked,report=validate_and_repair_design_spec(spec,set(ids))
 assert not report['errors'],report
 result.append({'document':to_collage_document(checked,asset_map=ids),'validation':report})
json.dump(result,sys.stdout)
`], {input: JSON.stringify(cases.map(c => c.spec)), cwd: path.resolve(__dirname,'..'), env: {...process.env, PYTHONPATH: 'src'}, maxBuffer: 40*1024*1024}));

(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1600,height:1000}});
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.goto(`${process.env.PHOTO_MANAGER_URL || 'http://127.0.0.1:8777'}/experimental/collage/fabric-v2`);
    await page.waitForFunction(() => typeof renderDocument === 'function' && window.CollageTemplateLibrary && document.querySelector('#sample-template').options.length === 13);
    await page.locator('#sample-template').selectOption('botanical');
    await page.locator('#sample-template-match').selectOption('a4-landscape');
    await page.screenshot({path: path.join(out, 'workflow.png'),fullPage:true});
    const evidence = [];
    for (let i=0;i<cases.length;i++) {
      const c = cases[i];
      const render = await page.evaluate(async ({doc,items}) => {
        const canvas = new fabric.StaticCanvas(document.createElement('canvas'), {enableRetinaScaling:false});
        try {
          const normalized = normalizeDocument(doc);
          const report = await renderDocument(canvas, normalized, {assetMap:new Map(items.map(p=>[p.asset_id,p])), interactive:false, renderMode:'funnel', strictAssets:true});
          return {report, png:canvas.toDataURL({format:'png',multiplier:0.65})};
        } finally { canvas.dispose(); }
      }, {doc:docs[i].document,items:c.items});
      fs.writeFileSync(path.join(out,c.key+'.png'),Buffer.from(render.png.split(',')[1],'base64'));
      evidence.push({key:c.key, family:c.family, diagnostics:c.diagnostics, validation:docs[i].validation, render:render.report});
      if (i%12===11) console.log(`Rendered ${i+1}/${cases.length} pages`);
    }
    // Contact sheets are screenshots of the same rendered output, not alternate
    // thumbnail geometry. Full-size individual PNGs are saved alongside them.
    for (const group of [...new Set(cases.map(c=>c.key.replace(/-[^-]+$/, '')))]) {
      const members=cases.filter(c=>c.key.startsWith(group+'-'));
      await page.setContent('<style>body{font:15px sans-serif;background:#ddd;margin:12px}.grid{display:grid;grid-template-columns:repeat(4,360px);gap:16px}article{background:white;padding:8px}img{width:100%;height:485px;object-fit:contain}h3{margin:0 0 6px;font-size:15px}</style><div class="grid"></div>');
      for (const c of members) await page.evaluate(({title,png})=>{
        const article=document.createElement('article'); const h=document.createElement('h3');h.textContent=title;
        const image=document.createElement('img');image.src=png;article.append(h,image);document.querySelector('.grid').append(article);
      },{title:c.family,png:'data:image/png;base64,'+fs.readFileSync(path.join(out,c.key+'.png')).toString('base64')});
      await page.evaluate(()=>Promise.all([...document.images].map(i=>i.decode())));
      await page.screenshot({path:path.join(out,`board-${group}.png`),fullPage:true});
    }
    fs.writeFileSync(path.join(out,'render-report.json'),JSON.stringify({errors,evidence},null,2));
    if(errors.length || evidence.some(e=>e.render.failed_element_ids.length || e.render.warnings.length)) throw Error('Render failures or warnings; see report.');
    console.log(`Saved ${evidence.length} production-rendered pages and comparison boards to ${out}`);
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
