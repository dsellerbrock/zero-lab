import RFB from "./novnc/core/rfb.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const T = window.ZL_TOKEN;
let state = null, status = "stopped", wsPort = null, rfb = null;
let pins = { fn: Array(28).fill(0), lev: Array(28).fill(0) };
let widgets = [];

// ---------- API ----------
async function api(path, body) {
  const opts = body === undefined ? { headers: { "X-Zero-Lab-Token": T } }
    : { method: "POST", headers: { "X-Zero-Lab-Token": T, "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
function toast(msg) {
  const t = $("toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove("show"), 3500);
}
const act = (fn) => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message); } };

// ---------- state + settings ----------
function fill(sel, values, current, labels = values) {
  sel.innerHTML = values.map((v, i) => `<option value="${esc(v)}">${esc(labels[i])}</option>`).join("");
  if (values.includes(current)) sel.value = current;
}
function render() {
  const h = state.host, c = state.cfg;
  $("hostinfo").textContent = `${h.system} ${h.arch}` + (h.accels[0] !== "tcg" ? " · accelerated" : " · emulated CPU (no acceleration on this machine)");
  fill($("accel"), h.accels, c.accel, h.accels.map((a) => ({ hvf: "Apple HVF (fast)", tcg: "TCG (emulated)" }[a] || a)));
  fill($("gpu"), h.gpus, c.gpu, h.gpus.map((g) => ({ venus: "Venus (Vulkan, host GPU)", virgl: "virgl (OpenGL, host GPU)", soft: "Software" }[g])));
  for (const k of ["ram", "cpus", "display"]) $(k).value = String(c[k]);
  $("network").checked = c.network; $("snapshot").checked = c.snapshot;
  const imgs = state.images;
  fill($("image"), imgs.map((i) => i.name), c.image || imgs.find((i) => i.provisioned)?.name,
       imgs.map((i) => i.name + (i.provisioned ? "" : " (not set up)")));
  if (!imgs.length) $("addimg").open = true;
  fill($("src-kind"), [...state.catalog.map((e) => e.id), "local"], $("src-kind").value || "desktop",
       [...state.catalog.map((e) => `${e.name} — ${(e.size / 1e9).toFixed(1)} GB`), "A file on this computer…"]);
  fill($("layout-list"), state.layouts, $("layout-list").value);
  showStaged(state.staged);
  if (state.busy) $("progress").textContent = state.busy + "…";
  setStatus(state.status);
}
async function refresh() { state = await api("/api/state"); render(); }
async function saveCfg() {
  state = await api("/api/config", { ram: +$("ram").value, cpus: +$("cpus").value, accel: $("accel").value,
    gpu: $("gpu").value, display: $("display").value, network: $("network").checked,
    snapshot: $("snapshot").checked, image: $("image").value });
}
for (const id of ["ram", "cpus", "accel", "gpu", "display", "network", "snapshot", "image"]) $(id).onchange = act(saveCfg);
$("src-kind").onchange = () => { $("src-path-row").hidden = $("src-kind").value !== "local"; };
$("img-add").onclick = act(async () => {
  const kind = $("src-kind").value;
  await api("/api/image/add", { name: $("img-name").value.trim(), user: $("img-user").value.trim(),
    password: $("img-pass").value, source: kind === "local" ? $("src-path").value.trim() : kind });
  $("img-pass").value = ""; $("progress").textContent = "Starting…";
});

// ---------- boot / stop / status ----------
function setStatus(s, extra = {}) {
  status = s;
  const el = $("status"); el.textContent = s + (extra.boot_seconds ? ` · booted in ${extra.boot_seconds}s` : "");
  el.className = "pill " + s;
  $("boot").disabled = s !== "stopped"; $("stop").disabled = s === "stopped";
  if (s === "stopped") { disconnectScreen(); $("screen-msg").textContent = extra.exit_code ? "QEMU exited with an error; see the serial console." : "Boot the Pi to see its screen."; }
}
$("boot").onclick = act(async () => { await saveCfg(); await api("/api/boot", {}); });
$("stop").onclick = act(() => api("/api/stop", {}));

function connectScreen() {
  if (rfb || !wsPort || state.cfg.display !== "app") return;
  $("screen-msg").textContent = "Waiting for the display…";
  rfb = new RFB($("screen"), `ws://${location.host}/vnc?t=${encodeURIComponent(T)}`);
  rfb.scaleViewport = true; rfb.focusOnClick = true;
  rfb.addEventListener("connect", () => { $("screen-msg").textContent = ""; });
  rfb.addEventListener("disconnect", () => { rfb = null; if (status !== "stopped") setTimeout(connectScreen, 1500); });
}
function disconnectScreen() { if (rfb) { const r = rfb; rfb = null; r.disconnect(); } }

// ---------- events ----------
const serialEl = $("serial"), procEl = $("proc");
function append(el, text) {
  const stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 4;
  el.textContent = (el.textContent + text).slice(-100000);
  if (stick) el.scrollTop = el.scrollHeight;
}
function onEvent(m) {
  if (m.type === "status") {
    if (m.ws_port) wsPort = m.ws_port;
    setStatus(m.status, m);
    if (m.status === "booting" || m.status === "running") { connectScreen(); if (m.status === "booting") applyIdle(); }
  } else if (m.type === "serial") append(serialEl, m.data.replace(/\r/g, ""));
  else if (m.type === "gpio") { const first = !pins.seen; pins = { ...m, seen: true }; updatePins(); if (first) applyIdle(); }
  else if (m.type === "proc") {
    if (m.line !== undefined) append(procEl, m.line + "\n");
    else if (m.state === "running") { procEl.textContent = ""; showTab("proc"); }
    else if (m.state === "exited") append(procEl, `\n[exit status ${m.code}]\n`);
  } else if (m.type === "provision") {
    const p = $("progress");
    if (m.stage === "error") { p.textContent = "Setup failed: " + m.error; }
    else if (m.stage === "done") { p.textContent = "Image ready. Press Boot!"; refresh(); }
    else if (m.stage === "first-boot") p.textContent = "First boot: setting up your user (watch the serial console)…";
    else p.textContent = `${m.stage}: ${m.total ? Math.round(100 * m.done / m.total) : 0}%`;
  } else if (m.type === "images") { state.images = m.images; refresh(); }
}
new EventSource(`/api/events?t=${encodeURIComponent(T)}`).onmessage = (e) => onEvent(JSON.parse(e.data));

function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  serialEl.hidden = name !== "serial"; procEl.hidden = name !== "proc";
}
document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
$("serial-in").onkeydown = act(async (e) => {
  if (e.key !== "Enter") return;
  await api("/api/serial", { text: e.target.value + "\r" }); e.target.value = "";
});

// ---------- drop-in code ----------
// A file dropped anywhere else must not navigate the window away from the app.
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());
function showStaged(list) { $("staged").innerHTML = list.slice(0, 50).map((f) => `<li>${esc(f)}</li>`).join("") + (list.length > 50 ? `<li>… ${list.length - 50} more</li>` : ""); }
async function walk(entry, prefix, out) {
  if (entry.isFile) out.push([prefix + entry.name, await new Promise((ok, err) => entry.file(ok, err))]);
  else if (entry.isDirectory) {
    const reader = entry.createReader();
    for (let batch; (batch = await new Promise((ok, err) => reader.readEntries(ok, err))).length;)
      for (const e of batch) if (!e.name.startsWith(".")) await walk(e, prefix + entry.name + "/", out);
  }
}
async function upload(items) {
  let staged = [];
  for (const [path, file] of items) {
    const r = await fetch("/api/project/file", { method: "POST", headers: { "X-Zero-Lab-Token": T, "X-Path": path }, body: file });
    const j = await r.json(); if (!r.ok) throw new Error(j.error); staged = j.staged;
  }
  showStaged(staged); toast(`${items.length} file(s) ready — press Build & run`);
}
const drop = $("drop");
drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
drop.ondragleave = () => drop.classList.remove("over");
drop.ondrop = act(async (e) => {
  e.preventDefault(); drop.classList.remove("over");
  const entries = [...e.dataTransfer.items].map((i) => i.webkitGetAsEntry()).filter(Boolean);
  const items = []; for (const en of entries) await walk(en, "", items);
  await api("/api/project/clear", {}); await upload(items);
});
$("run").onclick = act(() => api("/api/project/run", {}));
$("pstop").onclick = act(() => api("/api/project/stop", {}));
$("pclear").onclick = act(async () => { await api("/api/project/clear", {}); showStaged([]); });
$("autostart").onchange = act((e) => api("/api/project/autostart", { on: e.target.checked }));

// ---------- GPIO pin strip ----------
const pinEls = [];
for (let i = 0; i < 28; i++) { const d = document.createElement("div"); d.className = "pin"; d.innerHTML = `<b></b>${i}`; $("pins").append(d); pinEls.push(d); }
function updatePins() {
  pinEls.forEach((d, i) => {
    const fn = pins.fn[i]; d.className = "pin " + (fn === 0 ? "in" : fn === 1 ? "out" : "alt") + (pins.lev[i] ? " hi" : "");
    d.title = `GPIO${i}: ${fn === 0 ? "input" : fn === 1 ? "output" : "alt function " + fn}, level ${pins.lev[i]}`;
  });
  widgets.forEach((w) => w.update && w.update());
}
const drive = (pin, level) => api("/api/gpio", { pin, level }).catch((e) => toast(e.message));

// ---------- widgets ----------
const DEFAULTS = {
  button: { label: "Button", pins: [17], idle: 1 }, switch: { label: "Switch", pins: [22], on: false },
  knob: { label: "Knob", pins: [5, 6, 13, 19], value: 0 }, led: { label: "LED", pins: [27], color: "#ff3b30", activeLow: false },
  seg7: { label: "7-segment", pins: [2, 3, 4, 14, 15, 18, 23], activeLow: false }, probe: { label: "Probe", pins: [27] },
};
const SEGS = ["4,2 24,2 20,6 8,6", "26,4 26,24 22,21 22,8", "26,28 26,48 22,44 22,31", "4,50 24,50 20,46 8,46",
  "2,28 2,48 6,44 6,31", "2,4 2,24 6,21 6,8", "4,26 8,23 20,23 24,26 20,29 8,29"];
const lev = (p) => pins.lev[p] ?? 0;

function makeWidget(spec) {
  const w = { ...DEFAULTS[spec.type], ...spec, id: spec.id || crypto.randomUUID() };
  w.pins = (Array.isArray(w.pins) ? w.pins : []).map(Number).filter((n) => n >= 0 && n < 28).slice(0, 8);
  w.x = +w.x || 0; w.y = +w.y || 0; w.label = String(w.label ?? ""); w.value = +w.value || 0;
  if (!w.pins.length) w.pins = [...DEFAULTS[spec.type].pins];
  const el = document.createElement("div"); el.className = "w"; el.style.left = w.x + "px"; el.style.top = w.y + "px";
  el.innerHTML = `<div class="t"><span></span><button title="Settings">⚙</button><button title="Remove">✕</button></div><div class="b"></div>`;
  const body = el.querySelector(".b"), title = el.querySelector(".t span");
  const relabel = () => (title.textContent = `${w.label} · GPIO ${w.pins.join(",")}`);
  relabel();
  const outActive = (p) => (lev(p) === (w.activeLow ? 0 : 1));

  if (w.type === "button") {
    body.innerHTML = `<button class="pushbtn" aria-label="${esc(w.label)}"></button>`;
    const b = body.firstChild;
    b.onpointerdown = (e) => { b.setPointerCapture(e.pointerId); b.classList.add("down"); drive(w.pins[0], 1 - w.idle); };
    b.onpointerup = b.onpointercancel = () => { b.classList.remove("down"); drive(w.pins[0], w.idle); };
    w.applyIdle = () => drive(w.pins[0], w.idle);
  } else if (w.type === "switch") {
    body.innerHTML = `<button class="toggle" role="switch" aria-label="${esc(w.label)}"></button>`;
    const b = body.firstChild; const show = () => b.classList.toggle("on", w.on);
    b.onclick = () => { w.on = !w.on; show(); drive(w.pins[0], w.on ? 1 : 0); };
    w.applyIdle = () => drive(w.pins[0], w.on ? 1 : 0); show();
  } else if (w.type === "knob") {
    body.innerHTML = `<div class="knob" tabindex="0" role="slider"><div></div></div>`;
    const k = body.firstChild, max = () => (1 << w.pins.length) - 1;
    const show = () => { k.style.setProperty("--a", `${(360 * w.value) / max()}deg`); k.firstChild.textContent = w.value; k.setAttribute("aria-valuenow", w.value); };
    const set = (v) => { v = Math.max(0, Math.min(max(), v)); if (v === w.value) return; w.value = v; show(); w.pins.forEach((p, i) => drive(p, (v >> i) & 1)); };
    k.onpointerdown = (e) => { k.setPointerCapture(e.pointerId); const y0 = e.clientY, v0 = w.value;
      k.onpointermove = (m) => set(v0 + Math.round((y0 - m.clientY) / 6)); };
    k.onpointerup = () => (k.onpointermove = null);
    k.onkeydown = (e) => { if (e.key === "ArrowUp") set(w.value + 1); if (e.key === "ArrowDown") set(w.value - 1); };
    w.applyIdle = () => w.pins.forEach((p, i) => drive(p, (w.value >> i) & 1)); show();
  } else if (w.type === "led") {
    body.innerHTML = `<div class="led" style="color:${esc(w.color)}"></div>`;
    w.update = () => body.firstChild.classList.toggle("on", outActive(w.pins[0]));
  } else if (w.type === "seg7") {
    body.innerHTML = `<svg class="seg7" viewBox="0 0 28 52" width="56" height="104">${SEGS.map((p) => `<polygon points="${p}"/>`).join("")}</svg>`;
    w.update = () => body.querySelectorAll("polygon").forEach((s, i) => s.classList.toggle("on", w.pins[i] !== undefined && outActive(w.pins[i])));
  } else if (w.type === "probe") {
    body.innerHTML = `<canvas class="probe" width="180" height="40"></canvas>`;
    const c = body.firstChild.getContext("2d"), hist = [];
    w.update = () => hist.push([performance.now(), lev(w.pins[0])]);
    const draw = () => {
      if (!el.isConnected) return;
      const now = performance.now(); while (hist.length > 1 && hist[1][0] < now - 10000) hist.shift();
      c.clearRect(0, 0, 180, 40); c.strokeStyle = "#7CFC9A"; c.beginPath();
      let lv = hist.length ? hist[0][1] : lev(w.pins[0]); c.moveTo(0, lv ? 8 : 32);
      for (const [t, v] of hist) { const x = 180 * (1 - (now - t) / 10000); c.lineTo(x, lv ? 8 : 32); c.lineTo(x, v ? 8 : 32); lv = v; }
      c.lineTo(180, lv ? 8 : 32); c.stroke(); requestAnimationFrame(draw);
    };
    requestAnimationFrame(draw);
  }

  // settings
  const [gear, close] = el.querySelectorAll(".t button");
  close.onclick = () => { el.remove(); widgets = widgets.filter((x) => x !== w); };
  gear.onclick = () => {
    const open = el.querySelector(".cfg"); if (open) return open.remove();
    const cfg = document.createElement("div"); cfg.className = "cfg";
    cfg.innerHTML = `<label>Label <input data-k="label" value="${esc(w.label)}"></label>
      <label>GPIO (BCM, comma list${w.type === "seg7" ? ": a,b,c,d,e,f,g" : w.type === "knob" ? ", LSB first" : ""}) <input data-k="pins" value="${w.pins.join(",")}"></label>` +
      (w.type === "button" ? `<label class="check"><input type="checkbox" data-k="idle" ${w.idle ? "checked" : ""}> Idle high (active-low, like a pull-up)</label>` : "") +
      (w.type === "led" || w.type === "seg7" ? `<label class="check"><input type="checkbox" data-k="activeLow" ${w.activeLow ? "checked" : ""}> Lit when low</label>` : "") +
      (w.type === "led" ? `<label>Colour <input type="color" data-k="color" value="${esc(w.color)}"></label>` : "");
    cfg.oninput = () => {
      for (const i of cfg.querySelectorAll("input")) {
        const k = i.dataset.k;
        if (k === "pins") { const ps = i.value.split(",").map((s) => parseInt(s, 10)).filter((n) => n >= 0 && n < 28); if (ps.length) w.pins = ps.slice(0, 8); }
        else if (k === "idle") w.idle = i.checked ? 1 : 0;
        else if (k === "activeLow") w.activeLow = i.checked;
        else w[k] = i.value;
      }
      if (w.type === "led") body.firstChild.style.color = w.color;
      relabel(); w.update && w.update();
    };
    el.append(cfg);
  };

  // drag by the title bar
  const bar = el.querySelector(".t");
  bar.onpointerdown = (e) => {
    if (e.target.tagName === "BUTTON") return;
    bar.setPointerCapture(e.pointerId); const dx = e.clientX - w.x, dy = e.clientY - w.y;
    bar.onpointermove = (m) => { w.x = Math.max(0, m.clientX - dx); w.y = Math.max(0, m.clientY - dy); el.style.left = w.x + "px"; el.style.top = w.y + "px"; };
  };
  bar.onpointerup = () => (bar.onpointermove = null);

  $("canvas").append(el); widgets.push(w); w.update && w.update();
  return w;
}
function applyIdle() { if (pins.seen) widgets.forEach((w) => w.applyIdle && w.applyIdle()); }
let addPos = 0;
document.querySelectorAll("[data-add]").forEach((b) => (b.onclick = () => {
  addPos = (addPos + 1) % 6; makeWidget({ type: b.dataset.add, x: 16 + addPos * 22, y: 16 + addPos * 26 }).applyIdle?.();
}));

// ---------- layouts ----------
const SAVE_KEYS = ["id", "type", "x", "y", "label", "pins", "idle", "on", "value", "color", "activeLow"];
const layout = () => ({ version: 1, widgets: widgets.map((w) => Object.fromEntries(SAVE_KEYS.filter((k) => k in w).map((k) => [k, w[k]]))) });
function loadLayout(l) {
  if (!l || l.version !== 1 || !Array.isArray(l.widgets)) throw new Error("not a Zero Lab layout");
  $("canvas").innerHTML = ""; widgets = [];
  for (const s of l.widgets) if (DEFAULTS[s.type]) makeWidget(s);
  applyIdle();
}
$("layout-save").onclick = act(async () => {
  const name = $("layout-name").value.trim() || "my-layout";
  const r = await api("/api/layout/save", { name, layout: layout() });
  fill($("layout-list"), r.layouts, name); toast(`Saved “${name}”`);
});
$("layout-load").onclick = act(async () => loadLayout(await api(`/api/layout?name=${encodeURIComponent($("layout-list").value)}`)));
$("layout-export").onclick = act(async () => {
  const name = $("layout-list").value; if (!name) throw new Error("save the layout first");
  toast("Exported to " + (await api("/api/layout/export", { name })).path);
});
const cv = $("canvas");
cv.ondragover = (e) => e.preventDefault();
cv.ondrop = act(async (e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) loadLayout(JSON.parse(await f.text())); });

// starter layout: matches samples/button-led-*
loadLayout({ version: 1, widgets: [
  { type: "button", x: 20, y: 20, label: "Button", pins: [17], idle: 1 },
  { type: "led", x: 160, y: 20, label: "LED", pins: [27], color: "#ff3b30" },
] });
refresh().catch((e) => toast(e.message));
