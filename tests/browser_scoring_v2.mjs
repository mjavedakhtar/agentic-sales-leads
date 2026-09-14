#!/usr/bin/env node
/**
 * Real Chrome smoke test, using the Chrome DevTools Protocol and Node >= 22.
 * Seed with tests/seed_scoring_browser.py, start LeadGenPlatform on 8055 using the emitted
 * LEADGEN_DB_PATH, then run: node tests/browser_scoring_v2.mjs
 * Uses pre-seeded disposable scoring fixtures. It does not create research or call a model.
 * Optional: LEADGEN_URL, CHROME_BIN, LEADGEN_ARTIFACTS, LEADGEN_V2_FIXTURE.
 * No browser automation package or downloaded browser is required.
 */
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, writeFile, mkdir, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';

const fixture=JSON.parse(await readFile(process.env.LEADGEN_V2_FIXTURE || '/tmp/leadgen-v2-browser-context.json','utf8'));
const base = process.env.LEADGEN_URL || 'http://127.0.0.1:8055';
const chromeBin = process.env.CHROME_BIN || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const artifacts = process.env.LEADGEN_ARTIFACTS || fixture.artifacts;
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
  await navigate('/research/qa-v2');
  await waitFor('document.querySelectorAll(".shortlist tbody tr").length === 3', 'three v2 fixture leads');
  check(await evaluate('document.querySelector(".policy-tag").textContent.includes("Demo rubric v2")'), 'Shortlist identifies the current rubric');
  check(await evaluate('[...document.querySelectorAll(".score-cell strong")].map(el=>el.textContent).join("|") === "100/100|56-76/100|Not assessed"'), 'Shortlist shows complete, provisional and unknown assessments without treating unknown as zero');
  check(await evaluate('document.querySelector(".source-capture-summary").textContent.includes("1 of 1 public sources captured")'), 'Captured-page count explains the available source evidence');
  await overflow('V2 shortlist desktop');
  await screenshot('v2-shortlist-desktop');
  await select('[aria-label="Sort leads"]','coverage');
  check(await evaluate('document.querySelector(".company-cell strong").textContent === "QA Complete Batteries"'), 'Evidence sorting uses coverage');
  await select('[aria-label="Sort leads"]','name');
  check(await evaluate('[...document.querySelectorAll(".company-cell strong")].map(el=>el.textContent).join("|") === "QA Complete Batteries|QA Partial Batteries|QA Unknown Batteries"'), 'Company-name sorting still works');
  await navigate(fixture.provisionalPath);
  await waitFor('document.querySelector(".rubric-v2")','provisional assessment');
  check(await evaluate('document.querySelector(".big-fit strong").textContent === "56-76/100"'), 'Provisional assessment shows the unresolved score range');
  check(await evaluate('document.querySelectorAll(".criterion-unknown").length === 1 && document.querySelector(".criterion-unknown").textContent.includes("20 possible points remain open")'), 'Unknown criterion keeps its possible points open');
  check(await evaluate('document.querySelector(".evidence-separation b").textContent === "75%" && document.querySelector(".assessment-completeness").textContent.includes("3/4 criteria")'), 'Evidence coverage and assessment completeness remain separate');
  check(await evaluate('[...document.querySelectorAll(".criterion-calculation")].some(el=>el.textContent.includes("4/5 × 40 = 32 points"))'), 'Criterion explains the rating-to-points calculation');
  check(await evaluate('[...document.querySelectorAll(".criterion-sources a")].every(el=>document.getElementById(el.hash.slice(1)))'), 'Every displayed criterion fact link resolves to evidence on the page');
  const factTarget=await evaluate('document.querySelector(".criterion-sources a").hash.slice(1)');
  await click(bySelector('.criterion-sources a'));
  await waitFor(`document.activeElement?.id === ${JSON.stringify(factTarget)}`,'focused evidence card');
  check(await evaluate(`document.getElementById(${JSON.stringify(factTarget)}).classList.contains('highlighted')`), 'Clicking a criterion fact focuses and highlights its evidence card');
  check(await evaluate('document.querySelector(".evidence-panel").textContent.includes("23.000 Mitarbeitende") && document.querySelector(".evidence-panel").textContent.includes("23,000 employees") && document.querySelector(".evidence-panel").textContent.includes("German") && document.querySelector(".evidence-panel").textContent.includes("Untertürkheim site")'), 'German source wording, normalized quantity, source language and site scope are visible together');
  await click(bySelector('.rubric-detail summary'));
  check(await evaluate('document.querySelector(".rubric-detail").open && document.querySelector(".rubric-detail").textContent.length > 40'), 'Rubric details expand to explain the selected rating');
  await overflow('Provisional assessment desktop');
  await screenshot('v2-provisional-desktop',true);
  await navigate(fixture.completePath);
  await waitFor('document.querySelector(".rubric-v2")','complete assessment');
  check(await evaluate('document.querySelector(".big-fit strong").textContent === "100/100" && document.querySelector(".evidence-separation b").textContent === "100%"'), 'Full score and full evidence coverage are reachable in the UI');
  check(await evaluate('document.querySelectorAll(".criterion-unknown").length === 0 && document.querySelector(".assessment-completeness").textContent.includes("4/4 criteria")'), 'A complete assessment reports all four rated criteria');
  await screenshot('v2-complete-desktop');
  await navigate(fixture.unknownPath);
  await waitFor('document.querySelector(".rubric-v2")','unknown assessment');
  check(await evaluate('document.querySelector(".big-fit strong").textContent === "Not assessed" && document.querySelector(".score-explanation").textContent.includes("Open range: 0-100/100")'), 'All-unknown assessment has an explicit open range');
  check(await evaluate('document.querySelectorAll(".criterion-unknown").length === 4 && document.querySelector(".assessment-completeness").textContent.includes("0/4 criteria")'), 'All-unknown criteria remain unknown throughout the assessment');
  await overflow('Unknown assessment desktop');
  await screenshot('v2-unknown-desktop');
  await navigate('/research/qa-summary');
  await waitFor('document.querySelector(".source-capture-summary")','summary-only source notice');
  check(await evaluate('document.querySelector(".source-capture-summary").textContent.includes("Original pages could not be captured") && document.querySelector(".source-capture-summary").textContent.includes("search summaries")'), 'Summary-only research explains why fetched-page evidence is absent');
  check(await evaluate('document.querySelector(".coverage-cell strong").textContent === "0%" && document.querySelector(".score-cell strong").textContent === "56-76/100"'), 'Summary-supported judgments can coexist with zero fetched-page coverage without conflating the metrics');
  await screenshot('v2-summary-only-desktop');
  await navigate(`/leads/${fixture.legacyRun}/${fixture.legacyLead}`);
  await waitFor('document.querySelector(".fit-panel")','captured policy assessment');
  check(await evaluate(`document.querySelector('.big-fit strong').textContent === ${JSON.stringify(fixture.legacyScore+'/100')}`), 'Captured policy retains its saved numeric score');
  check(await evaluate('document.querySelector(".big-fit").textContent.includes("Captured policy v1") && document.querySelector(".policy-notice").textContent.includes("Start a new live assessment")'), 'Captured policy is explicitly distinguished from the current rubric');
  await overflow('Legacy assessment desktop');
  await navigate(`/leads/qa-legacy-live/${fixture.legacyLead}`);
  await waitFor('document.querySelector(".fit-panel")','historical live assessment');
  check(await evaluate('document.querySelector(".big-fit").textContent.includes("Legacy policy v1")'), 'Historical live assessments are visibly legacy policy v1');
  await navigate('/engineering');
  await waitFor('document.querySelectorAll(".workflow-node").length === 8','current live workflow');
  await click(bySelector('.workflow-node',4));
  check(await evaluate('document.querySelector(".node-detail pre").textContent.includes("Model call 4") && document.querySelector(".node-detail").textContent.includes("assess_fit")'), 'Engineering exposes the separate rubric assessment call');
  await click(bySelector('.workflow-node',7));
  await select('[aria-label="Research run trace"]',fixture.legacyRun);
  await waitFor('document.querySelectorAll(".workflow-node").length === 6','captured workflow');
  check(await evaluate('document.querySelectorAll(".workflow-node.selected").length === 1 && document.querySelector(".node-detail pre").textContent.length > 20'), 'Switching to a historical trace preserves a valid selected workflow step');
  await viewport(390,844);
  for(const [label,path] of [['shortlist','/research/qa-v2'],['partial',fixture.provisionalPath],['unknown',fixture.unknownPath],['legacy',`/leads/${fixture.legacyRun}/${fixture.legacyLead}`],['engineering','/engineering']]){
    await navigate(path);
    await waitFor('document.querySelector(".page-heading,.assessment-heading") && !document.querySelector(".loading-state")','mobile '+label);
    await overflow('V2 '+label+' mobile');
    await screenshot('v2-'+label+'-mobile',label==='partial');
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
