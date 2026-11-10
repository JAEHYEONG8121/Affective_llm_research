const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const root = path.resolve(__dirname, '..');
  const readme = fs.readFileSync(path.join(root, 'README.md'), 'utf8');
  const catalog = JSON.parse(fs.readFileSync(path.join(root, 'research/catalog.json')));
  const topics = JSON.parse(fs.readFileSync(path.join(root, 'research/taxonomy.json')));
  const diagrams = [...readme.matchAll(/```mermaid\n([\s\S]*?)\n```/g)].map(m => m[1]);
  assert.equal(diagrams.length, 1 + topics.length + (catalog.edges.length ? 1 : 0));
  for (const p of catalog.papers) {
    assert.ok(readme.includes(`](${p.url})`), `Missing Markdown paper link: ${p.id}`);
  }
  const system = process.env.CHROMIUM_PATH || '/usr/bin/chromium';
  const browser = await chromium.launch({
    headless: true,
    ...(fs.existsSync(system) ? {executablePath: system} : {}),
    args: ['--no-sandbox'],
  });
  try {
    const page = await browser.newPage({viewport: {width: 1100, height: 900}});
    await page.setContent('<html lang="ko"><meta charset="utf-8"><style>body{font-family:system-ui;margin:32px;color:#20353d;background:white}.diagram{margin-bottom:48px;max-width:1000px}svg{max-width:100%;height:auto}</style><h1>LLM 감정·정렬 연구 지도</h1><main id="diagrams"></main></html>');
    await page.addScriptTag({path: path.join(root, 'node_modules/mermaid/dist/mermaid.min.js')});
    const counts = await page.evaluate(async diagrams => {
      mermaid.initialize({startOnLoad: false, securityLevel: 'strict', theme: 'neutral'});
      const counts = [];
      for (const [i, source] of diagrams.entries()) {
        const {svg} = await mermaid.render('readme' + i, source);
        const div = document.createElement('div');
        div.id = 'diagram-' + i;
        div.className = 'diagram';
        div.innerHTML = svg;
        document.getElementById('diagrams').append(div);
        counts.push(div.querySelectorAll('.node').length);
      }
      return counts;
    }, diagrams);
    assert.ok(counts.every(n => n > 0));
    assert.equal(counts[0], 1 + topics.length);
    await page.locator('#diagram-1').screenshot({path: '/tmp/affective-atlas-readme-topic.png'});
    console.log(`PASS README: ${diagrams.length} Mermaid diagrams rendered; ${catalog.papers.length} papers have Markdown links; ${counts.reduce((a,b) => a+b,0)} rendered nodes.`);
  } finally {
    await browser.close();
  }
})().catch(e => {console.error(e);process.exitCode=1;});
