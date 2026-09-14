#!/usr/bin/env node
/**
 * Real Chrome smoke test, using the Chrome DevTools Protocol and Node >= 22.
 * Start LeadGenPlatform first, then run: node tests/browser_smoke.mjs
 * The test creates local research and pipeline records. Use a disposable DB.
 * Optional: LEADGEN_URL, CHROME_BIN, LEADGEN_ARTIFACTS, LEADGEN_CAPTURE_ONLY=1.
 * No browser automation package or downloaded browser is required.
 */
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, writeFile, mkdir, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';

const base = process.env.LEADGEN_URL || 'http://127.0.0.1:8040';
const chromeBin = process.env.CHROME_BIN || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const artifacts = process.env.LEADGEN_ARTIFACTS || join(dirname(fileURLToPath(import.meta.url)), '../artifacts/browser');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const profile = await mkdtemp(join(tmpdir(), 'leadgen-chrome-'));
await mkdir(artifacts, {recursive: true});
const chrome = spawn(chromeBin, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--disable-background-networking', '--disable-component-update', '--disable-sync',
  '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank',
], {stdio: ['ignore', 'ignore', 'pipe']});
let chromeLog = '';
chrome.stderr.on('data', chunk => {chromeLog += chunk.toString();});
chrome.on('error', error => {chromeLog += String(error);});
let socket;
const report = {base, startedAt: new Date().toISOString(), checks: [], browserErrors: [], failedRequests: [], overflows: [], evaluationRequests: 0};
const pending = new Map();
let nextId = 0;
let requestedViewportWidth = 1440;

function check(condition, description, detail) {
  report.checks.push({description, passed: !!condition, ...(detail === undefined ? {} : {detail})});
  if (!condition) throw new Error(description + (detail === undefined ? '' : ': ' + JSON.stringify(detail)));
  console.log('PASS ' + description);
}
async function cdp(method, params = {}) {
  const id = ++nextId;
  const promise = new Promise((resolve, reject) => pending.set(id, {resolve, reject}));
  socket.send(JSON.stringify({id, method, params}));
  const timeout = setTimeout(() => {
    pending.get(id)?.reject(new Error('CDP timeout: ' + method));
    pending.delete(id);
  }, 20000);
  try {return await promise;} finally {clearTimeout(timeout);}
}
async function evaluate(expression) {
  const result = await cdp('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result.value;
}
async function waitFor(expression, description, timeout = 20000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {if (await evaluate(`Boolean(${expression})`)) return;} catch (error) {
      if (!String(error).includes('Execution context was destroyed')) throw error;
    }
    await delay(100);
  }
  throw new Error('Timed out: ' + description);
}
async function navigate(path) {
  await evaluate('window.__leadgenSmokeNavigating = true');
  await cdp('Page.navigate', {url: base + path});
  await waitFor(`!window.__leadgenSmokeNavigating && location.pathname === ${JSON.stringify(path)} && document.readyState === "complete" && document.querySelector("main")`, 'page ' + path);
}
const byText = (tag, text) => `[...document.querySelectorAll(${JSON.stringify(tag)})].find(el => el.textContent.trim() === ${JSON.stringify(text)})`;
const bySelector = (selector, index = 0) => `document.querySelectorAll(${JSON.stringify(selector)})[${index}]`;
async function click(expression) {
  const bounds = await evaluate(`(() => {const el = ${expression}; if (!el) throw Error('Click target missing'); if (el.disabled) throw Error('Click target disabled'); el.scrollIntoView({block:'center', inline:'center'}); const r = el.getBoundingClientRect(); return {x:r.x + r.width/2, y:r.y + r.height/2};})()`);
  await cdp('Input.dispatchMouseEvent', {type: 'mousePressed', button: 'left', clickCount: 1, ...bounds});
  await cdp('Input.dispatchMouseEvent', {type: 'mouseReleased', button: 'left', clickCount: 1, ...bounds});
}
async function fill(selector, value) {
  await click(bySelector(selector));
  await evaluate(`document.querySelector(${JSON.stringify(selector)}).select()`);
  if (value) await cdp('Input.insertText', {text: value});
  else {
    await cdp('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Backspace', code: 'Backspace', windowsVirtualKeyCode: 8});
    await cdp('Input.dispatchKeyEvent', {type: 'keyUp', key: 'Backspace', code: 'Backspace', windowsVirtualKeyCode: 8});
  }
}
async function select(selector, value) {
  await evaluate(`(() => {const el = document.querySelector(${JSON.stringify(selector)}); el.value = ${JSON.stringify(value)}; el.dispatchEvent(new Event('change', {bubbles:true}));})()`);
}
async function screenshot(name, fullPage = false) {
  await evaluate('document.fonts.ready.then(() => true)');
  await delay(150);
  const params = {format: 'png', captureBeyondViewport: fullPage};
  if (fullPage) {
    const metrics = await cdp('Page.getLayoutMetrics');
    params.clip = {x: 0, y: 0, width: metrics.cssContentSize.width, height: metrics.cssContentSize.height, scale: 1};
  }
  const shot = await cdp('Page.captureScreenshot', params);
  await writeFile(join(artifacts, name + '.png'), Buffer.from(shot.data, 'base64'));
}
async function overflow(label) {
  const result = await evaluate(`(() => ({viewport:innerWidth, document:document.documentElement.scrollWidth, requested:${requestedViewportWidth}, offenders:[...document.querySelectorAll('main *')].filter(el => {const r=el.getBoundingClientRect();return r.width>0 && r.right>${requestedViewportWidth + 1} && getComputedStyle(el).position!=='fixed' && !el.closest('.table-scroll')}).slice(0,12).map(el => ({tag:el.tagName, className:el.className, right:Math.round(el.getBoundingClientRect().right)}))}))()`);
  report.overflows.push({label, ...result});
  if (result.document > requestedViewportWidth + 1) result.boxes = await evaluate(`[...document.querySelectorAll('html,body,.app-shell,.main-shell,main,.shortlist,.table-scroll,table')].map(el => ({tag:el.tagName,className:el.className,left:el.getBoundingClientRect().left,right:el.getBoundingClientRect().right,width:el.getBoundingClientRect().width,client:el.clientWidth,scroll:el.scrollWidth,overflow:getComputedStyle(el).overflowX,position:getComputedStyle(el).position}))`);
  const passed = result.document <= requestedViewportWidth + 1 && result.viewport <= requestedViewportWidth + 1;
  report.checks.push({description: label + ' has no document overflow', passed, detail: result});
  console.log((passed ? 'PASS ' : 'FAIL ') + label + ' has no document overflow' + (passed ? '' : ': ' + JSON.stringify(result)));
}
async function viewport(width, height) {
  requestedViewportWidth = width;
  await cdp('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 1, mobile: width < 600});
}

try {
  let port;
  for (let i = 0; i < 100; i++) {
    try {port = Number((await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]); break;} catch {}
    if (chrome.exitCode !== null) throw new Error('Chrome exited: ' + chromeLog.slice(-1500));
    await delay(100);
  }
  if (!port) throw new Error('Chrome debugger did not start: ' + chromeLog.slice(-1500));
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(pages.find(page => page.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {socket.onopen = resolve; socket.onerror = reject;});
  socket.onmessage = event => {
    const data = JSON.parse(event.data);
    if (data.id) {
      const request = pending.get(data.id);
      if (data.error) request?.reject(new Error(JSON.stringify(data.error)));
      else request?.resolve(data.result);
      pending.delete(data.id);
    }
    if (data.method === 'Runtime.exceptionThrown') report.browserErrors.push(data.params.exceptionDetails);
    if (data.method === 'Runtime.consoleAPICalled' && data.params.type === 'error') report.browserErrors.push({type: 'console', args: data.params.args.map(arg => arg.value || arg.description)});
    if (data.method === 'Network.loadingFailed' && !data.params.canceled) report.failedRequests.push(data.params);
    if (data.method === 'Network.requestWillBeSent' && data.params.request.method === 'POST' && data.params.request.url.endsWith('/api/evals')) report.evaluationRequests++;
  };
  await Promise.all([cdp('Page.enable'), cdp('Runtime.enable'), cdp('Network.enable')]);
  await viewport(1440, 1050);
  await navigate('/');
  await waitFor('document.querySelectorAll(".play-card").length === 3', 'three research plays');
  check(true, 'Discover loads all three research plays');
  await click(byText('button', 'Captured replay'));
  check(await evaluate(`${byText('button', 'Captured replay')}.getAttribute('aria-pressed') === 'true'`), 'Regression workflow explicitly selects captured replay without live API calls');
  await overflow('Discover desktop');
  await screenshot('01-discover-desktop');

  if (process.env.LEADGEN_INSPECT_PATHS) {
    await viewport(390, 844);
    for (const path of process.env.LEADGEN_INSPECT_PATHS.split(',')) {
      await navigate(path);
      await waitFor('!document.querySelector(".loading-state")', 'inspection ' + path);
      await delay(350);
      await overflow(path + ' mobile inspection');
      await screenshot('inspect-' + path.replaceAll('/', '_'), true);
    }
  } else {

  if (process.env.LEADGEN_CAPTURE_ONLY !== '1') {
    const runs = [];
    let approvedCompany;
    for (let i = 0; i < 3; i++) {
      if (i > 0) {await navigate('/'); await waitFor('document.querySelectorAll(".play-card").length === 3', 'research plays');}
      await click(bySelector('.play-card', i));
      await waitFor('document.querySelector(".scope-panel")', 'scope confirmation');
      check(await evaluate('document.querySelectorAll(".scope-field").length >= 4'), `Play ${i + 1} presents a bounded research scope`);
      await overflow(`Scope ${i + 1} desktop`);
      if (i === 0) await screenshot('02-scope-desktop');
      await click(byText('button', 'Confirm & research'));
      await waitFor('document.querySelectorAll(".shortlist tbody tr").length > 0', 'ranked shortlist', 60000);
      const ranking = await evaluate('[...document.querySelectorAll(".shortlist tbody tr")].map(row => ({score:Number(row.querySelector(".score-cell strong").firstChild.textContent),blocked:row.textContent.includes("Technical mismatch")}))');
      check(ranking.every((lead, j) => j === 0 || (!ranking[j - 1].blocked && lead.blocked) || (ranking[j - 1].blocked === lead.blocked && ranking[j - 1].score >= lead.score)), `Play ${i + 1} ranks by descending fit with blocked leads last`, ranking);
      runs.push(await evaluate('location.pathname'));
      await overflow(`Shortlist ${i + 1} desktop`);
      if (i === 0) {
        await screenshot('03-shortlist-desktop');
        await fill('[aria-label="Search shortlist"]', 'zzzz-no-such-company');
        await waitFor('document.querySelector(".shortlist .empty")', 'shortlist search empty state');
        check(await evaluate('document.querySelectorAll(".shortlist tbody tr").length === 0'), 'Shortlist search filters the actual company rows');
        await fill('[aria-label="Search shortlist"]', '');
        await waitFor('document.querySelectorAll(".shortlist tbody tr").length > 0', 'shortlist search reset');
        await select('[aria-label="Sort leads"]', 'name');
        const names = await evaluate('[...document.querySelectorAll(".company-cell strong")].map(el => el.textContent)');
        check(names.every((name, j) => j === 0 || names[j - 1].localeCompare(name) <= 0), 'Shortlist company-name sorting works');
        await select('[aria-label="Sort leads"]', 'score');
        await click(bySelector('.assess-link'));
        await waitFor('document.querySelector(".decision-panel")', 'lead assessment');
        report.assessmentPath = await evaluate('location.pathname');
        approvedCompany = await evaluate('document.querySelector(".assessment-heading h1").textContent');
        check(await evaluate('document.querySelectorAll(".evidence-row").length > 0 && document.querySelectorAll(".criterion").length > 0'), 'Assessment shows evidence and transparent score components');
        await overflow('Assessment desktop');
        await screenshot('04-assessment-desktop', true);
        await click(byText('button', 'Approve for pipeline'));
        await waitFor('document.querySelector("#review-note")', 'approval rationale dialog');
        check(await evaluate(`${byText('button', 'Approve & add to pipeline')}.disabled`), 'Approval is disabled without a rationale');
        await fill('#review-note', 'x');
        check(await evaluate(`${byText('button', 'Approve & add to pipeline')}.disabled`), 'Approval rejects a rationale that is too short');
        await fill('#review-note', 'Relevant battery module use case. Confirm adhesive requirements and buyer responsibility in discovery.');
        await click(byText('button', 'Approve & add to pipeline'));
        await waitFor('document.querySelector(".decision-record") && !document.querySelector("#review-note")', 'approval saved');
        check(true, 'Human approval records the decision and rationale');
        await click(byText('button', 'Open pipeline'));
        await waitFor('document.querySelectorAll(".pipeline-card").length > 0', 'approved pipeline card');
        await evaluate('window.__leadgenSmokeNavigating = true');
        await cdp('Page.reload');
        await waitFor(`!window.__leadgenSmokeNavigating && document.querySelector('.pipeline-card') && document.body.innerText.includes(${JSON.stringify(approvedCompany)})`, 'pipeline persists after reload');
        check(true, 'Approved pipeline entry survives a page reload');
        await click(`[...document.querySelectorAll('.pipeline-card')].find(el => el.textContent.includes(${JSON.stringify(approvedCompany)}))`);
        await waitFor('document.querySelector("#pipeline-note")', 'pipeline update dialog');
        await select('#pipeline-stage', 'contacted');
        const updateNote = 'Demo review: request a technical discovery call and clarify qualification requirements.';
        await fill('#pipeline-note', updateNote);
        await click(byText('button', 'Save update'));
        await waitFor(`document.querySelector('.activity-list')?.textContent.includes(${JSON.stringify(updateNote)})`, 'pipeline activity saved');
        check(true, 'Pipeline update adds the supplied note to its activity history');
        await click(byText('button', 'Check saved evidence'));
        await waitFor('document.querySelector(".freshness-check")?.textContent.includes("Age checked:")', 'saved source age checked');
        check(true, 'Saved evidence freshness check executes');
        await click(bySelector('[aria-label="Close dialog"]'));
        await waitFor('!document.querySelector("dialog")', 'pipeline dialog closed');
        check(await evaluate(`document.querySelector('.stage-contacted')?.textContent.includes(${JSON.stringify(approvedCompany)})`), 'Updated opportunity moves to the Contacted column');
        await screenshot('05-pipeline-desktop');
      }
      if (i === 2) {
        await select('[aria-label="Filter leads"]', 'blocked');
        await waitFor('document.querySelectorAll(".shortlist tbody tr").length > 0', 'technical mismatch example');
        check(await evaluate('[...document.querySelectorAll(".shortlist tbody tr")].every(row => row.textContent.includes("Technical mismatch"))'), 'Technical mismatch filter exposes only blocked leads');
        await click(bySelector('.assess-link'));
        await waitFor('document.querySelector(".technical-card.blocked")', 'blocked technical assessment');
        check(await evaluate(`${byText('button', 'Approve for pipeline')}.disabled`), 'Hard technical mismatch cannot be approved through the UI');
        check(await evaluate('document.querySelector(".assessment-heading").textContent.includes("Synthetic")'), 'Illustrative technical mismatch is visibly identified as synthetic');
        await screenshot('11-blocked-assessment-desktop', true);
      }
    }
    report.runs = runs;
    await navigate('/');
    await waitFor('document.querySelector(".research-composer textarea")', 'brief composer');
    await fill('textarea[aria-label="Research brief"]', 'Find hospital procurement teams in Canada for surgical robots.');
    await click(byText('button', 'Create research brief'));
    await waitFor('document.querySelector("[role=alert]")', 'unsupported scope rejected');
    check(await evaluate('location.pathname === "/"'), 'Unsupported brief is rejected without inventing a research result');
    report.unsupportedBriefMessage = await evaluate('document.querySelector("[role=alert]").textContent');

    await navigate('/knowledge');
    await waitFor('document.querySelectorAll(".product-selector button").length === 2', 'both supplied products');
    for (let i = 0; i < 2; i++) {
      await click(bySelector('.product-selector button', i));
      await fill('input[aria-label="Search product knowledge"]', 'temperature');
      await click(byText('button', 'Retrieve'));
      await waitFor('document.querySelector(".chunk-list")?.textContent.includes("Retrieval score")', 'retrieved source passages');
      check(await evaluate('document.querySelectorAll(".chunk-card").length > 0 && [...document.querySelectorAll(".chunk-card .badge")].every(el => el.textContent.startsWith("Page "))'), `Product ${i + 1} retrieves source passages with page provenance`);
      check(await evaluate('(async () => {const response = await fetch(document.querySelector(".product-detail a").href); const bytes = new Uint8Array(await response.arrayBuffer()); return response.ok && String.fromCharCode(...bytes.slice(0,5)) === "%PDF-";})()'), `Product ${i + 1} original spec link serves a real PDF`);
    }
    await overflow('Knowledge desktop');
    await screenshot('08-knowledge-desktop', true);

    await navigate('/engineering');
    await waitFor('document.querySelectorAll(".workflow-node").length === 6', 'engineering workflow');
    for (let i = 0; i < 6; i++) {
      await click(bySelector('.workflow-node', i));
      check(await evaluate(`document.querySelectorAll('.workflow-node')[${i}].classList.contains('selected') && document.querySelector('.node-detail pre').textContent.length > 20`), `Engineering step ${i + 1} exposes its execution contract`);
    }
    await waitFor('document.querySelectorAll(".trace-list > div").length > 0', 'persisted execution trace');
    check(true, 'Engineering shows real recorded research events');
    await click(byText('button', 'Run evaluation checks'));
    await waitFor('document.querySelectorAll(".eval-checks > div").length > 0 && !document.querySelector(".eval-panel button").disabled', 'executed regression checks');
    check(report.evaluationRequests === 1, 'Evaluation button sends an actual execution request');
    const evalScore = await evaluate('document.querySelector(".eval-score > strong").textContent');
    const [passed, total] = evalScore.split('/').map(Number);
    check(total > 0 && passed === total, 'Executed engineering regression checks all pass', evalScore);
    await overflow('Engineering desktop');
    await screenshot('09-engineering-desktop', true);

  }

  await viewport(390, 844);
  await navigate('/');
  await waitFor('document.querySelectorAll(".play-card").length === 3', 'mobile Discover');
  await overflow('Discover mobile');
  await screenshot('06-discover-mobile', true);
  await click(bySelector('[aria-label="Toggle navigation"]'));
  check(await evaluate('document.querySelector(".sidebar").classList.contains("open")'), 'Mobile navigation opens');
  await waitFor('document.querySelector(".sidebar").getBoundingClientRect().left >= -0.5', 'mobile navigation transition');
  await click(bySelector('nav a[href="/pipeline"]'));
  await waitFor('document.querySelector(".pipeline-toolbar")', 'mobile pipeline');
  await overflow('Pipeline mobile');
  await screenshot('07-pipeline-mobile', true);
  if (report.runs?.length) {
    await navigate(report.runs[0]);
    await waitFor('document.querySelector(".shortlist")', 'mobile shortlist');
    await overflow('Shortlist mobile');
    await screenshot('mobile-shortlist', true);
    await navigate(report.assessmentPath);
    await waitFor('document.querySelector(".decision-panel")', 'mobile assessment');
    await overflow('Assessment mobile');
    await screenshot('mobile-assessment', true);
  }
  for (const path of ['/knowledge', '/engineering']) {
    await navigate(path);
    await waitFor(`document.querySelector('.page-heading') && !document.querySelector('.loading-state')`, 'mobile ' + path);
    await overflow(path.slice(1) + ' mobile');
    await screenshot('mobile-' + path.slice(1), true);
  }
  }
  check(report.overflows.every(result => result.document <= result.requested + 1 && result.viewport <= result.requested + 1), 'All layouts stay within the requested viewport width');
  check(report.browserErrors.length === 0, 'No uncaught JavaScript or console errors', report.browserErrors);
  check(report.failedRequests.length === 0, 'No failed network requests', report.failedRequests);
  report.passed = true;
  await rm(join(artifacts, 'failure.png'), {force: true});
} catch (error) {
  report.passed = false;
  report.failure = error.stack || String(error);
  console.error(report.failure);
  try {await screenshot('failure'); report.pageText = await evaluate('document.body.innerText');} catch {}
  process.exitCode = 1;
} finally {
  report.finishedAt = new Date().toISOString();
  await writeFile(join(artifacts, 'report.json'), JSON.stringify(report, null, 2));
  socket?.close();
  chrome.kill('SIGTERM');
  await delay(250);
  await rm(profile, {recursive: true, force: true}).catch(() => {});
  console.log('Browser report: ' + join(artifacts, 'report.json'));
}
