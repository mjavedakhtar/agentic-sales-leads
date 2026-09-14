#!/usr/bin/env node
/**
 * Chrome regression checks for buying-responsibility comparison.
 * Run against a local LeadGenPlatform server: LEADGEN_URL=http://127.0.0.1:8059 node tests/browser_buyers.mjs
 * The saved illustrative fixture and bootstrap are read from the real local API.
 * Live POST, poll and retry responses are intercepted through CDP before interaction.
 * No paid model calls or application-record mutations are made by this test.
 * Prefer an isolated server with LEADGEN_GEMINI_API_KEY, GEMINI_API_KEY and GOOGLE_API_KEY empty.
 * Requires Node >= 22 and installed Chrome. Optional CHROME_BIN and LEADGEN_ARTIFACTS.
 */
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, writeFile, mkdir, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';

const base = process.env.LEADGEN_URL || 'http://127.0.0.1:8059';
const chromeBin = process.env.CHROME_BIN || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const artifacts = process.env.LEADGEN_ARTIFACTS || join(dirname(fileURLToPath(import.meta.url)), '../artifacts/buyer-browser');
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
  await navigate('/buyers/example');
  await waitFor('document.querySelectorAll(".buyer-card").length===5','five illustrative companies');
  check(await evaluate('document.querySelector(".buyer-illustrative").textContent.includes("Fictional companies")'),'Illustrative fixture has an explicit disclosure');
  check(await evaluate('[...document.querySelectorAll(".buyer-summary strong")].map(e=>e.textContent).join("|")==="5|1|2"'),'Summary isolates initial rule effect from follow-up effect');
  check(await evaluate('document.querySelector(".buyer-stage-switch button").getAttribute("aria-pressed")==="true"'),'Comparison defaults to the same stored evidence');
  check(await evaluate('document.querySelectorAll(".buyer-card.supported").length===1'),'Only one original company qualifies on initial evidence');
  const originalScores=await evaluate('[...document.querySelectorAll(".buyer-original-score strong")].map(e=>e.textContent)');
  await overflow('Buyer comparison desktop');
  await screenshot('buyers-initial-desktop',true);
  check(await evaluate('document.querySelectorAll(".buyer-filters button")[4].querySelector("span").textContent==="1"'),'Initial unclear count includes the known material user with unknown procurement');
  await click(bySelector('.buyer-filters button',4));
  await waitFor('document.querySelectorAll(".buyer-card").length===1','unknown procurement filter');
  check(await evaluate('document.querySelector(".buyer-company h3").textContent==="Elm Plastics"&&!document.querySelector(".buyer-results").textContent.includes("Delta Components")'),'Unclear filter shows Elm and excludes the supported purchaser');
  await click(bySelector('.buyer-filters button',2));
  await waitFor('document.querySelectorAll(".buyer-card").length===3','material users and specifiers filter');
  check(await evaluate('document.querySelector(".buyer-results").textContent.includes("Elm Plastics")'),'A company can be a known material user while its purchasing responsibility remains unclear');

  await click(bySelector('.buyer-filters button',1));
  check(await evaluate('document.querySelectorAll(".buyer-card").length===1&&document.querySelector(".buyer-company h3").textContent==="Delta Components"'),'Supported-buyer filter selects only the evidenced purchaser');
  await click(byText('button','After follow-up'));
  check(await evaluate('document.querySelectorAll(".buyer-card").length===5&&document.querySelectorAll(".buyer-card.supported").length===2'),'Follow-up reveals the new purchasing finding and resets filter');
  check(JSON.stringify(await evaluate('[...document.querySelectorAll(".buyer-original-score strong")].map(e=>e.textContent)'))===JSON.stringify(originalScores),'Commercial scores stay unchanged across evidence views');
  await click(bySelector('.buyer-detail summary',4));
  check(await evaluate('document.querySelectorAll(".buyer-detail")[4].open&&document.querySelectorAll(".buyer-detail")[4].textContent.includes("Evidence added during follow-up")'),'Added evidence is separate from original evidence');
  check(await evaluate('document.querySelectorAll(".buyer-detail")[4].textContent.includes("Einkauf beschafft PA66-Compounds")'),'Original German evidence is visible');
  check(await evaluate('document.querySelectorAll(".buyer-detail")[4].querySelectorAll(".buyer-role").length===5'),'Material use, specification, procurement, components and customer-supplied roles are separate');
  check(await evaluate('[...document.querySelectorAll(".buyer-role-evidence a")].every(a=>document.getElementById(a.hash.slice(1)))'),'All responsibility evidence anchors resolve');
  check(await evaluate('document.querySelectorAll(".buyer-evidence-meta a").length===0'),'Fictional quotations do not masquerade as real source links');
  await screenshot('buyers-followup-desktop',true);
  check(await evaluate('document.querySelectorAll(".buyer-filters button")[4].querySelector("span").textContent==="0"'),'Follow-up resolves the last unknown purchasing responsibility');
  await click(bySelector('.buyer-filters button',4));
  check(await evaluate('document.querySelector(".empty")?.textContent.includes("No companies match")'),'Empty filter result is explained');
  await viewport(390,844);
  await navigate('/buyers/example');
  await waitFor('document.querySelectorAll(".buyer-card").length===5','mobile buyer comparison');
  await click(byText('button','After follow-up'));
  await waitFor('document.querySelectorAll(".buyer-card.supported").length===2','mobile follow-up');
  await overflow('Buyer comparison mobile');
  await screenshot('buyers-followup-mobile',true);
  await click(bySelector('.buyer-detail summary',1));
  check(await evaluate('document.querySelectorAll(".buyer-detail")[1].textContent.includes("Customers supply and own the resin")'),'Customer-supplied material caveat remains visible');
  await overflow('Expanded buyer evidence mobile');
  await screenshot('buyers-expanded-mobile',true);
  const fixture=await (await fetch(base+'/api/buyer-checks/example')).json();
  const bootstrap=await (await fetch(base+'/api/bootstrap')).json();
  const scenario=bootstrap.scenarios[0];
  const run={id:'buyer-browser-qa',status:'completed',mode:'live',query:'Offline browser QA',title:'Buyer comparison QA',scope:{...fixture.baseline.scope,criteria:[],limitations:[]},created_at:fixture.created_at,leads:fixture.initial_candidates.map(c=>({...c,gate:{status:'eligible'},gaps:[],coverage:75,evidence:[],criteria:[],sector:'Automotive'})),trace:[],sources:[],usage:{}};
  let current=null, posts=0, retries=0, polls=0, capability=true;
  const live={...fixture,mode:'live',run_id:run.id,baseline:{...fixture.baseline,run_id:run.id},trace:[{node:'assess_existing',detail:'Saved evidence assessed.',at:fixture.created_at}],followup:{...fixture.followup,performed:false}};
  const originalHandler=socket.onmessage;
  socket.onmessage=event=>{
    const data=JSON.parse(event.data);
    if(data.method==='Fetch.requestPaused'){
      const {requestId,request}=data.params;const url=new URL(request.url);let response;
      if(url.pathname==='/api/bootstrap')response={...bootstrap,capabilities:{...bootstrap.capabilities,live:{configured:capability}},runs:[run]};
      else if(url.pathname===`/api/runs/${run.id}`)response=run;
      else if(url.pathname===`/api/runs/${run.id}/buyer-check/retry`){retries++;current={...live,status:'completed'};response=current;}
      else if(url.pathname===`/api/runs/${run.id}/buyer-check`){if(request.method==='POST'){posts++;current=current||{...live,status:'running',current_node:'assess_existing',initial_candidates:[],candidates:[]};}else if(current?.status==='running'){polls++;if(polls>1)current={...live,status:'completed'};}response=current;}
      else{cdp('Fetch.continueRequest',{requestId});return;}
      cdp('Fetch.fulfillRequest',{requestId,responseCode:200,responseHeaders:[{name:'Content-Type',value:'application/json'}],body:Buffer.from(JSON.stringify(response)).toString('base64')});return;
    }
    originalHandler(event);
  };
  await cdp('Fetch.enable',{patterns:[{urlPattern:'*/api/*'}]});
  await viewport(1440,1050);
  await navigate('/research/'+run.id+'/buyers');
  await waitFor('document.querySelector(".buyer-setup")','new check setup');
  check(posts===0,'Opening a comparison URL does not automatically call the model');
  await click(byText('button','Check buying responsibility'));
  await waitFor('document.querySelector(".buyer-progress")','running check progress');
  check(posts===1,'Explicit button initiates one buyer check');
  await screenshot('buyers-running-desktop');
  await waitFor('document.querySelectorAll(".buyer-card").length===5','saved comparison after polling');
  check(polls>=2,'Live check polls to its saved completion');
  await click(bySelector('.buyer-filters button',4));
  await waitFor('document.querySelectorAll(".buyer-card").length===1','live unclear filter');
  check(posts===1&&await evaluate('document.querySelector(".buyer-company h3").textContent==="Elm Plastics"'),'Filtering unknown procurement performs no new assessment call');
  await click(bySelector('.buyer-filters button',1));
  await click(byText('button','After follow-up'));
  check(posts===1,'Filtering and evidence-view switching make no new assessment requests');
  current={...live,status:'failed',error:'Simulated provider interruption for QA'};
  await navigate('/research/'+run.id+'/buyers');
  await waitFor('document.querySelector(".notice.danger")?.textContent.includes("Simulated")','failed check state');
  await click(byText('button','Retry buyer check'));
  await waitFor('document.querySelector(".page-heading .badge")?.textContent.includes("Comparison saved")','retry completion');
  check(retries===1,'Failed check uses the explicit retry endpoint');
  current={...live,status:'failed',error:'Search call budget consumed',can_retry:false};
  await navigate('/research/'+run.id+'/buyers');
  await waitFor('document.querySelector(".notice.danger")?.textContent.includes("budget consumed")','consumed retry budget');
  check(await evaluate('[...document.querySelectorAll("button")].find(e=>e.textContent.trim()==="Retry buyer check").disabled'),'Consumed search budget disables retry');
  current={...live,status:'completed',candidates:[...live.candidates,{...live.candidates[3],id:'qa-new-buyer',name:'QA Newly Discovered Buyer',origin:'followup',score:null,score_upper:null}]};
  await navigate('/research/'+run.id+'/buyers');
  await waitFor('document.querySelectorAll(".buyer-card").length===5','original leads before followup');
  await click(byText('button','After follow-up'));
  await waitFor('document.querySelectorAll(".buyer-card").length===6','new company in followup');
  check(await evaluate('(()=>{const card=[...document.querySelectorAll(".buyer-card")].find(c=>c.textContent.includes("QA Newly Discovered Buyer"));return card.textContent.includes("No commercial assessment yet")&&!card.querySelector(".buyer-original-score strong")&&!card.querySelector(".buyer-original button")})()'),'New follow-up company has no invented commercial score or original assessment link');
  await navigate('/research/'+run.id);
  await waitFor('document.querySelector(".buyer-entry")','shortlist entry');
  await screenshot('buyers-shortlist-button');
  await click(byText('button','Check buying responsibility'));
  await waitFor('location.pathname.endsWith("/buyers")&&document.querySelectorAll(".buyer-card").length===5','shortlist launches comparison');
  check(posts===2,'Shortlist action opens the idempotent saved buyer check');
  capability=false;current=null;
  await navigate('/research/'+run.id+'/buyers');
  await waitFor('document.querySelector(".buyer-setup")','unconfigured setup');
  check(await evaluate('[...document.querySelectorAll("button")].find(e=>e.textContent.trim()==="Check buying responsibility").disabled'),'Live check is disabled when provider is not configured');
  check(await evaluate('document.querySelector(".buyer-setup-foot").textContent.includes("Live research is unavailable")'),'Missing provider has a clear explanation and illustrative alternative');
  await overflow('Buyer setup desktop');
  await viewport(390,844);
  await overflow('Buyer setup mobile');
  await screenshot('buyers-setup-mobile',true);
  check(report.overflows.every(result=>result.document<=result.requested+1&&result.viewport<=result.requested+1),'All buyer layouts stay within viewport');
  check(report.browserErrors.length===0,'No uncaught JavaScript or console errors',report.browserErrors);
  check(report.failedRequests.length===0,'No failed browser requests',report.failedRequests);
  report.passed=true;
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
