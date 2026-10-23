#!/usr/bin/env node
// Screenshot a running Zero Lab UI with headless Chrome, once the page is ready (not at load).
//   node tools/shoot.mjs URL OUT.png [WIDTHxHEIGHT] [JS to run first, may be async]
// Waits until the app has its state (the readiness light has a state), runs the optional JS,
// lets it settle, then captures. No dependencies: Chrome DevTools protocol over Node's WebSocket.
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [url, out, size = "1440x900", pre = ""] = process.argv.slice(2);
if (!url || !out) { console.error("usage: shoot.mjs URL OUT.png [WxH] [JS]"); process.exit(2); }
const [width, height] = size.split("x").map(Number);
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const prof = mkdtempSync(join(tmpdir(), "zl-shoot-"));
const port = 9300 + Math.floor(Math.random() * 500);
const chrome = spawn(CHROME, ["--headless=new", "--hide-scrollbars", "--force-prefers-reduced-motion",
  `--remote-debugging-port=${port}`, `--user-data-dir=${prof}`, `--window-size=${width},${height}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

try {
  let target;
  for (let i = 0; i < 50 && !target; i++) {
    await sleep(200);
    target = await fetch(`http://127.0.0.1:${port}/json/list`).then((r) => r.json()).then((l) => l.find((t) => t.type === "page")).catch(() => null);
  }
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  let id = 0; const waiting = new Map();
  ws.onmessage = (m) => { const d = JSON.parse(m.data); waiting.get(d.id)?.(d); waiting.delete(d.id); };
  const cdp = (method, params = {}) => new Promise((r) => { waiting.set(++id, r); ws.send(JSON.stringify({ id, method, params })); });
  const evaluate = async (expression) => (await cdp("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true })).result?.result?.value;

  await cdp("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
  await cdp("Page.navigate", { url });
  for (let i = 0; i < 100; i++) {  // ready: the readiness light has left "Checking"
    if (await evaluate(`!!document.querySelector('.topbar [data-state]:not([data-state="checking"])') || document.getElementById('sample-list')?.options.length > 0`)) break;
    await sleep(200);
  }
  if (pre) await evaluate(`(async () => { ${pre} })()`);
  await sleep(1200);
  const shot = await cdp("Page.captureScreenshot", { format: "png" });
  writeFileSync(out, Buffer.from(shot.result.data, "base64"));
  ws.close();
} finally {
  chrome.kill();
  await sleep(300);
  rmSync(prof, { recursive: true, force: true });
}
