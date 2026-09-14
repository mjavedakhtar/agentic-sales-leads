#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, writeFile, mkdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const base = process.env.LEADGEN_URL || 'http://127.0.0.1:8040';
const chromeBin = process.env.CHROME_BIN || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const imagesDir = join(dirname(fileURLToPath(import.meta.url)), '../docs/images');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const profile = await mkdtemp(join(tmpdir(), 'leadgen-screenshots-'));
await mkdir(imagesDir, { recursive: true });

const chrome = spawn(chromeBin, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--disable-background-networking', '--disable-component-update', '--disable-sync',
  '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank',
], { stdio: ['ignore', 'ignore', 'pipe'] });

let chromeLog = '';
chrome.stderr.on('data', chunk => { chromeLog += chunk.toString(); });
chrome.on('error', error => { chromeLog += String(error); });

let socket;
const pending = new Map();
let nextId = 0;

async function cdp(method, params = {}) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}

async function evaluate(expression) {
  const result = await cdp('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}

async function waitFor(expression, description, timeout = 10000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    try {
      const val = await evaluate(`Boolean(${expression})`);
      if (val === true) return;
    } catch {}
    await delay(100);
  }
  throw new Error('Timed out waiting for ' + description);
}

async function navigate(path) {
  await cdp('Page.navigate', { url: base + path });
  await waitFor(`location.pathname.startsWith(${JSON.stringify(path.split('?')[0])}) && document.readyState === "complete" && document.querySelector("main, .app-shell, .discover-intro, .knowledge-layout, .pipeline-page, .buyer-page")`, 'page ' + path);
  await delay(800);
}

async function screenshot(filename) {
  await evaluate('document.fonts.ready.then(() => true)');
  await delay(300);
  const params = { format: 'png', captureBeyondViewport: false };
  const shot = await cdp('Page.captureScreenshot', params);
  const targetPath = join(imagesDir, filename);
  await writeFile(targetPath, Buffer.from(shot.data, 'base64'));
  console.log('Saved screenshot:', targetPath);
}

try {
  let port;
  for (let i = 0; i < 100; i++) {
    try {
      port = Number((await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]);
      break;
    } catch {}
    if (chrome.exitCode !== null) throw new Error('Chrome exited: ' + chromeLog);
    await delay(100);
  }
  if (!port) throw new Error('Chrome debugger did not start');

  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(pages.find(page => page.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });

  socket.onmessage = event => {
    const data = JSON.parse(event.data);
    if (data.id) {
      const req = pending.get(data.id);
      if (data.error) req?.reject(new Error(JSON.stringify(data.error)));
      else req?.resolve(data.result);
      pending.delete(data.id);
    }
  };

  await Promise.all([cdp('Page.enable'), cdp('Runtime.enable')]);
  await cdp('Emulation.setDeviceMetricsOverride', { width: 1440, height: 960, deviceScaleFactor: 2, mobile: false });

  // 1. Discover / Home
  console.log('Capturing 01-discover-page.png...');
  await navigate('/');
  await screenshot('01-discover-page.png');

  // Find the latest completed run with leads
  const bootstrap = await (await fetch(`${base}/api/bootstrap`)).json();
  const runWithLeads = bootstrap.runs.find(r => r.lead_count > 0) || bootstrap.runs[0];
  const runId = runWithLeads?.id;

  if (runId) {
    // 2. Research Shortlist
    console.log(`Capturing 02-research-shortlist.png (run ${runId})...`);
    await navigate(`/research/${runId}`);
    await screenshot('02-research-shortlist.png');

    // 3. Lead Detail Drawer
    console.log('Capturing 03-lead-scoring-drawer.png...');
    const runData = await (await fetch(`${base}/api/runs/${runId}`)).json();
    const leadId = runData.leads?.[0]?.id;
    if (leadId) {
      await navigate(`/leads/${runId}/${leadId}`);
      await screenshot('03-lead-scoring-drawer.png');
    }
  }

  // 4. Product Knowledge
  console.log('Capturing 04-product-knowledge.png...');
  await navigate('/knowledge');
  await screenshot('04-product-knowledge.png');

  // 5. Engineering & Architecture
  console.log('Capturing 05-engineering-architecture.png...');
  await navigate('/engineering');
  await screenshot('05-engineering-architecture.png');

  // 6. Buyer Qualification
  console.log('Capturing 06-buyer-qualification.png...');
  await navigate('/buyers/example');
  await screenshot('06-buyer-qualification.png');

  // 7. Sales Pipeline
  console.log('Capturing 07-sales-pipeline.png...');
  await navigate('/pipeline');
  await screenshot('07-sales-pipeline.png');

  console.log('All screenshots captured successfully!');
} catch (err) {
  console.error('Screenshot capture failed:', err);
  process.exit(1);
} finally {
  chrome.kill('SIGTERM');
  await rm(profile, { recursive: true, force: true }).catch(() => {});
}
