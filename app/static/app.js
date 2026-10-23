import RFB from "./novnc/core/rfb.js";
import { breadboard } from "./widgets.js";
import { filesPanel } from "./files.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const T = window.ZL_TOKEN;
let state = null, ready = null, status = "stopped", wsPort = null, rfb = null, setupOpen = false, screenUp = false;
let pins = { fn: Array(28).fill(0), lev: Array(28).fill(0), seen: false };

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
  clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove("show"), 4000);
}
const act = (fn) => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message); } };
function fill(sel, values, current, labels = values) {
  sel.innerHTML = values.map((v, i) => `<option value="${esc(v)}">${esc(labels[i])}</option>`).join("");
  if (values.includes(current)) sel.value = current;
}
const ACCEL = { hvf: "Fast (Apple HVF)", tcg: "Emulated (TCG), works everywhere" };
const ACCEL_SHORT = { hvf: "Fast CPU", tcg: "Emulated CPU" };
const GPU = { venus: "Fast 3D on your GPU (Venus)", virgl: "Compatible 3D on your GPU (virgl)", soft: "Software, no GPU" };
const GPU_SHORT = { venus: "GPU 3D", virgl: "GPU 3D", soft: "Software 3D" };
// "/Users/ann/Library/..." -> "~/Library/..." so save locations fit on one line
const tilde = (p) => (state && p.startsWith(state.paths.home + "/") ? "~" + p.slice(state.paths.home.length) : p);
const provisioned = () => state.images.filter((i) => i.provisioned);
const shortLabel = (l) => l.replace(/ \(64-bit.*$/, "");
const activeImage = () => provisioned().find((i) => i.name === state.cfg.image) || provisioned()[0];

// ---------- top bar ----------
function renderSummary() {
  const c = state.cfg, img = activeImage();
  const parts = [img ? img.label.replace(/ \(64-bit.*$/, "") : "No disk image", `${c.ram} MB`,
    `${c.cpus} CPU${c.cpus > 1 ? "s" : ""}`, ACCEL_SHORT[c.accel], GPU_SHORT[c.gpu], "⚙"];
  $("summary").innerHTML = parts.map((p, i) => `<span class="${i === 0 ? "disk" : i === parts.length - 1 ? "gear" : ""}">${esc(p)}</span>`).join("");
  $("summary").setAttribute("aria-label", `Settings: ${parts.slice(0, -1).join(", ")}`);
}
function updateControls() {
  const running = status !== "stopped", busy = state.busy;
  const missing = ready ? ready.rows.filter((r) => r.required && r.state !== "ok") : [];
  const reason = busy ? "Setting up the disk image" : !ready ? "Checking" : missing.length ? "Finish setup to boot" : "";
  $("boot-reason").textContent = running ? "" : reason;
  $("boot").disabled = running || !!busy || !ready?.ready;
  $("boot").setAttribute("aria-describedby", "boot-reason");
  $("stop").disabled = !running;
  $("settings-fields").disabled = running || !!busy;
  $("lock-note").hidden = !running;
  $("run").disabled = $("pstop").disabled = $("autostart").disabled = status !== "running";
  $("code-hint").textContent = status === "running" ? "" : status === "stopped" ? "Boot the Pi to build and run code." : "Code can run once the desktop is up.";
  const st = $("status");
  st.dataset.state = busy ? "setup" : status;  // an attribute, so it can't pick up other classes' styles
  $("status-text").textContent = busy ? "Setting up" : { stopped: "Stopped", booting: "Booting", running: "Running", stopping: "Stopping" }[status];
}

// ---------- screen: setup flow or the Pi's display ----------
function renderScreen() {
  const needSetup = status === "stopped" && (setupOpen || !activeImage() || state.busy);
  $("setup").hidden = !needSetup;
  document.querySelector(".monitor").classList.toggle("first-run", needSetup);
  $("screen-msg").hidden = needSetup || screenUp;
  if (needSetup) return;
  const img = activeImage();
  $("screen-msg").textContent =
    status === "stopped" ? `Press Boot to start ${shortLabel(img.label)}.`
    : state.cfg.display === "window" ? "The Pi's screen is in its own window."
    : status === "booting" ? "Starting the Pi. The screen appears when the display comes up." : "";
}
function renderSetup() {
  const fs = $("os-choices"), cur = fs.querySelector("input:checked")?.value || "desktop";
  fs.innerHTML = '<legend class="sr">Operating system</legend>' + state.catalog.map((e) => `
    <label class="choice"><input type="radio" name="os" value="${esc(e.id)}"><span>${esc(e.name.replace(/ \(64-bit.*$/, ""))}</span>
      <span class="size">${(e.size / 1e9).toFixed(1)} GB</span>
      <small>${e.id === "desktop" ? "Recommended. The normal Pi desktop." : e.id === "full" ? "Desktop plus extra apps for learning and office work." : "No desktop: terminal only, smallest download."}</small></label>`).join("") + `
    <label class="choice"><input type="radio" name="os" value="local"><span>A disk image already on this computer</span><span></span>
      <small>An official .img or .img.xz you downloaded before. Zero Lab works on a copy.</small></label>`;
  (fs.querySelector(`input[value="${cur}"]`) || fs.querySelector("input")).checked = true;
  fs.onchange = () => { $("local-row").hidden = fs.querySelector("input:checked").value !== "local"; };
  fs.onchange();
  $("go-note").textContent = state.host.accels[0] === "hvf"
    ? "Takes about 5 to 10 minutes on this Mac, mostly the download. The first boot then creates your user."
    : "This computer emulates the Pi's CPU, so the first boot takes 20 to 40 minutes after the download.";
  $("setup-cancel").hidden = !activeImage();
  $("setup-title").textContent = activeImage() ? "Set up another disk image" : "Set up your Pi";
}
const STAGES = ["download", "decompress", "prepare", "first-boot"];
const FIRST_BOOT = { ZL_PROVISION_BEGIN: "starting", ZL_USER_READY: "user created", ZL_SSH_ENABLED: "network and SSH set up",
  ZL_AUTOLOGIN: "desktop login set up", ZL_INITRAMFS_BEGIN: "preparing fast disk access (the longest part)",
  ZL_VIRTIO_INITRAMFS_OK: "fast disk access ready", ZL_PROVISIONED: "finishing" };
const gb = (b) => `${(b / 1e9).toFixed(2)} GB`;
function showProgress(m) {
  const list = $("progress"); list.hidden = false;
  const idx = m.stage === "done" ? STAGES.length : STAGES.indexOf(m.stage);
  list.querySelectorAll("li").forEach((li, i) => {
    li.className = i < idx ? "done" : i === idx ? "active" : "";
    const pct = li.querySelector(".pct"), bar = li.querySelector(".bar");
    const frac = i === idx && m.total > 1 ? Math.min(1, m.done / m.total) : null;
    if (frac !== null) {  // update in place: one line per stage, one bar
      const p = `${Math.round(frac * 100)}%`;
      pct.textContent = li.dataset.stage === "download" ? `${gb(m.done)} of ${gb(m.total)}, ${p}` : p;
      bar.hidden = false; bar.firstChild.style.width = `${frac * 100}%`;
    } else if (i !== idx) { pct.textContent = i < idx ? "done" : ""; bar.hidden = true; }
    if (li.dataset.stage === "first-boot" && i === idx && m.step && FIRST_BOOT[m.step])
      li.querySelector(".lbl").textContent = `First boot: ${FIRST_BOOT[m.step]}`;
  });
  ["step-os", "step-user"].forEach((id) => $(id).classList.add("done"));
  $("img-add").disabled = true;
}
$("setup").onsubmit = act(async (e) => {
  e.preventDefault();
  const kind = $("os-choices").querySelector("input:checked").value;
  if (!$("img-pass").value) { $("img-pass").focus(); throw new Error("Choose a password for the Pi's user"); }
  let name = kind, n = 2;
  while (state.images.some((i) => i.name === name)) name = `${kind}-${n++}`;
  $("setup-error").hidden = true;
  await api("/api/image/add", { name, user: $("img-user").value.trim(), password: $("img-pass").value,
    source: kind === "local" ? $("src-path").value.trim() : kind });
  $("img-pass").value = "";
  state.busy = `setting up ${name}`; updateControls();
  showProgress({ stage: kind === "local" ? "decompress" : "download", done: 0, total: 1 });
});
$("setup-cancel").onclick = () => { setupOpen = false; renderScreen(); };

// ---------- settings drawer ----------
const dlg = $("settings");
$("summary").onclick = () => dlg.showModal();
function renderSettings() {
  const h = state.host, c = state.cfg;
  fill($("image"), provisioned().map((i) => i.name), activeImage()?.name, provisioned().map((i, _, all) => shortLabel(i.label) + (all.filter((j) => j.label === i.label).length > 1 ? ` (${i.name})` : "")));
  if (!provisioned().length) $("image").innerHTML = "<option>None yet</option>";
  fill($("accel"), h.accels, c.accel, h.accels.map((a) => ACCEL[a]));
  fill($("gpu"), h.gpus, c.gpu, h.gpus.map((g) => GPU[g]));
  fill($("display"), h.displays, c.display, h.displays.map((d) => ({ app: "In Zero Lab", window: "In a separate window" }[d])));
  $("ram").value = String(c.ram); $("cpus").value = String(c.cpus);
  $("network").checked = c.network; $("snapshot").checked = c.snapshot;
  $("config-path").textContent = tilde(state.paths.config);
  $("layouts-path").textContent = tilde(state.paths.layouts);
  $("cache-path").textContent = tilde(state.paths.cache);
}
async function saveCfg() {
  state = await api("/api/config", { ram: +$("ram").value, cpus: +$("cpus").value, accel: $("accel").value,
    gpu: $("gpu").value, display: $("display").value, network: $("network").checked,
    snapshot: $("snapshot").checked, ...(activeImage() ? { image: $("image").value } : {}) });
  render();
  const s = $("saved-state"); s.textContent = "Saved"; s.className = "saved";
  clearTimeout(saveCfg.t); saveCfg.t = setTimeout(() => { s.textContent = "Changes save automatically"; s.className = ""; }, 2500);
}
$("settings-fields").onchange = act(saveCfg);
$("new-image").onclick = () => { dlg.close(); setupOpen = true; render(); $("os-choices").querySelector("input:checked")?.focus(); };
document.querySelectorAll("[data-reveal]").forEach((b) => (b.onclick = act(() => api("/api/reveal", { what: b.dataset.reveal }))));

// ---------- boot / stop ----------
$("boot").onclick = act(async () => { setupOpen = false; await api("/api/boot", {}); });
$("stop").onclick = act(() => api("/api/stop", {}));
function connectScreen() {
  if (rfb || !wsPort || state.cfg.display !== "app") return;
  rfb = new RFB($("screen"), `ws://${location.host}/vnc?t=${encodeURIComponent(T)}`);
  rfb.scaleViewport = true; rfb.focusOnClick = true;
  rfb.addEventListener("connect", () => { screenUp = true; $("screen-msg").hidden = true; });
  rfb.addEventListener("disconnect", () => { rfb = null; screenUp = false; renderScreen(); if (status !== "stopped") setTimeout(connectScreen, 1500); });
}
function disconnectScreen() { if (rfb) { const r = rfb; rfb = null; r.disconnect(); } }

// ---------- events ----------
// Console output arrives in hundreds of small chunks per second while the Pi boots. Rewriting a large
// <pre> per chunk freezes the page, so chunks are queued and appended at most every 100 ms.
const pending = new Map();
function append(el, text) {
  pending.set(el, (pending.get(el) || "") + text);
  if (!append.timer) append.timer = setTimeout(flushConsoles, 100);
}
function flushConsoles() {
  append.timer = null;
  for (const [el, text] of pending) {
    const stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 4;
    if (!el.firstChild) el.append(document.createTextNode(""));
    const node = el.firstChild;
    node.appendData(text);
    if (node.length > 120000) node.deleteData(0, node.length - 80000);  // keep the last ~80 KB
    if (stick && !el.hidden) el.scrollTop = el.scrollHeight;
  }
  pending.clear();
}
function onEvent(m) {
  if (m.type === "status") {
    if (m.ws_port) wsPort = m.ws_port;
    status = m.status;
    if (status === "stopped") disconnectScreen();
    if (status === "booting" || status === "running") { connectScreen(); if (status === "booting") applyIdle(); }
    if (m.boot_seconds) toast(`Booted in ${m.boot_seconds} s`);
    if (state) render();
  } else if (m.type === "serial") append($("serial"), m.data.replace(/\x1b\[[0-9;:?]*[A-Za-z]|\r/g, ""));  // drop colour codes
  else if (m.type === "gpio") { const first = !pins.seen; pins = { ...m, seen: true }; updateHeader(); bb.update(); if (first) applyIdle(); }
  else if (m.type === "proc") {
    if (m.line !== undefined) append($("proc"), m.line + "\n");
    else if (m.state === "running") { $("proc").textContent = ""; selectTab("code"); }
    else if (m.state === "exited") append($("proc"), `\n[the program exited with status ${m.code}]\n`);
  } else if (m.type === "provision") {
    if (m.stage !== refreshReady.stage) { refreshReady.stage = m.stage; refreshReady(); }
    if (m.stage === "error") {
      $("setup-error").textContent = `Setup stopped: ${m.error}`; $("setup-error").hidden = false;
      $("img-add").disabled = false; $("progress").hidden = true;
      ["step-os", "step-user"].forEach((id) => $(id).classList.remove("done"));
    } else if (m.stage === "done") {
      showProgress(m); setupOpen = false; toast("Disk image ready. Press Boot."); refresh();
    } else showProgress(m);
  } else if (m.type === "images") refresh();
  if (m.type === "provision" && ["first-boot", "error"].includes(m.stage)) api("/api/readiness").then((r) => { ready = r; renderReadiness(); updateControls(); });
}
new EventSource(`/api/events?t=${encodeURIComponent(T)}`).onmessage = (e) => onEvent(JSON.parse(e.data));

// ---------- tabs ----------
const TABS = ["code", "serial"];
function selectTab(name) {
  TABS.forEach((t) => {
    const on = t === name;
    $(`tab-${t}`).setAttribute("aria-selected", String(on)); $(`tab-${t}`).tabIndex = on ? 0 : -1;
    $(`panel-${t}`).hidden = !on;
  });
}
TABS.forEach((t, i) => {
  $(`tab-${t}`).onclick = () => selectTab(t);
  $(`tab-${t}`).onkeydown = (e) => {
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (d) { const n = TABS[(i + d + TABS.length) % TABS.length]; selectTab(n); $(`tab-${n}`).focus(); }
  };
});
$("serial-in").onkeydown = act(async (e) => {
  if (e.key !== "Enter") return;
  await api("/api/serial", { text: e.target.value + "\r" }); e.target.value = "";
});

// ---------- drop-in code ----------
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());
function showStaged(list) {
  $("staged").innerHTML = list.slice(0, 40).map((f) => `<li>${esc(f)}</li>`).join("") + (list.length > 40 ? `<li>and ${list.length - 40} more</li>` : "");
}
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
  showStaged(staged); toast(`${items.length} file${items.length > 1 ? "s" : ""} ready to build`);
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
drop.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); picker.click(); } };
drop.onclick = (e) => { if (e.target === drop || e.target.tagName === "STRONG") picker.click(); };
const picker = Object.assign(document.createElement("input"), { type: "file", multiple: true, hidden: true });
picker.onchange = act(async () => { await api("/api/project/clear", {}); await upload([...picker.files].map((f) => [f.name, f])); picker.value = ""; });
document.body.append(picker);
$("run").onclick = act(() => api("/api/project/run", {}));
$("pstop").onclick = act(() => api("/api/project/stop", {}));
$("pclear").onclick = act(async () => { await api("/api/project/clear", {}); showStaged([]); });
$("autostart").onchange = act((e) => api("/api/project/autostart", { on: e.target.checked }));

// ---------- 40-pin header, by physical position ----------
const HEADER = ["3v3", "5v", 2, "5v", 3, "gnd", 4, 14, "gnd", 15, 17, 18, 27, "gnd", 22, 23, "3v3", 24, 10, "gnd",
  9, 25, 11, 8, "gnd", 7, 0, 1, 5, "gnd", 6, 12, 13, "gnd", 19, 16, 26, 20, "gnd", 21];
const pads = HEADER.map((f, i) => {
  // Physical layout seen from above: pin 1 bottom-left, odd pins on the bottom row, even pins on top.
  const pin = i + 1, col = Math.ceil(pin / 2), top = pin % 2 === 0;
  const kind = typeof f === "number" ? "gpio" : f === "gnd" ? "gnd" : "pwr";
  const name = kind === "gpio" ? `GPIO${f}` : f.toUpperCase();
  const li = document.createElement("li");
  li.className = `pad ${kind}${pin === 1 ? " one" : ""}`;
  li.style.gridColumn = col; li.style.gridRow = top ? 2 : 3;
  li.dataset.bcm = kind === "gpio" ? f : "";
  li.title = `Pin ${pin}: ${name}`;
  li.setAttribute("aria-label", `Pin ${pin}, ${name}`);
  const lbl = document.createElement("li");
  lbl.className = `plabel ${kind}`; lbl.setAttribute("aria-hidden", "true");
  lbl.textContent = kind === "gpio" ? f : kind === "gnd" ? "GND" : f.toUpperCase();
  lbl.style.gridColumn = col; lbl.style.gridRow = top ? 1 : 4;
  $("header40").append(lbl, li);
  return li;
});
function updateHeader() {
  for (const li of pads) {
    if (li.dataset.bcm === "") continue;
    const g = +li.dataset.bcm, fn = pins.fn[g], hi = !!pins.lev[g];
    const dir = fn === 0 ? "in" : fn === 1 ? "out" : "alt";
    li.classList.remove("in", "out", "alt", "hi"); li.classList.add(dir); if (hi) li.classList.add("hi");
    li.setAttribute("aria-label", `${li.title.split(":")[0]}, GPIO${g}, ${dir === "in" ? "input" : dir === "out" ? "output" : "other function"}, ${hi ? "high" : "low"}`);
  }
}

// ---------- breadboard parts ----------
const drive = (pin, level) => (pins.seen ? api("/api/gpio", { pin, level }).catch((e) => toast(e.message)) : null);
const bb = breadboard({ canvas: $("canvas"), drive, lev: (p) => pins.lev[p] ?? 0, esc });
const applyIdle = () => { if (pins.seen) bb.applyIdle(); };
let addPos = 0;
document.querySelectorAll("[data-add]").forEach((b) => (b.onclick = () => {
  addPos = (addPos + 1) % 6; const w = bb.make({ type: b.dataset.add, x: 16 + addPos * 22, y: 16 + addPos * 26 });
  if (pins.seen) w.applyIdle?.();
}));
$("layout-save").onclick = act(async () => {
  const name = $("layout-name").value.trim() || $("layout-list").value || "my-layout";
  const r = await api("/api/layout/save", { name, layout: bb.layout() });
  fill($("layout-list"), r.layouts, name); $("layout-name").value = "";
  toast(`Saved “${name}” to ${tilde(state.paths.layouts)}`);
});
$("layout-load").onclick = act(async () => { bb.load(await api(`/api/layout?name=${encodeURIComponent($("layout-list").value)}`)); applyIdle(); });
$("layout-export").onclick = act(async () => {
  const name = $("layout-list").value; if (!name) throw new Error("Save the layout first, then copy it");
  toast("Copied to " + tilde((await api("/api/layout/export", { name })).path));
});
$("canvas").ondragover = (e) => e.preventDefault();
$("canvas").ondrop = act(async (e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) { bb.load(JSON.parse(await f.text())); applyIdle(); } });
bb.load({ version: 1, widgets: [ // matches samples/button-led-*
  { type: "button", x: 20, y: 24, label: "Button", pins: [17], idle: 1 },
  { type: "led", x: 196, y: 24, label: "LED", pins: [27], color: "#ff3b30" },
] });

// ---------- resizable GPIO panel (drag the divider; arrow keys too); remembered per browser ----------
{
  const sp = $("splitter"), bench = document.querySelector(".bench"), KEY = "zerolab.bbWidth";
  const setW = (px) => {
    const w = Math.round(Math.max(320, Math.min(px, innerWidth * 0.7)));
    bench.style.setProperty("--bb-w", w + "px"); sp.setAttribute("aria-valuenow", w);
    try { localStorage.setItem(KEY, w); } catch { /* not remembered */ }
  };
  try { const saved = +localStorage.getItem(KEY); if (saved) setW(saved); } catch { /* ignore */ }
  sp.onpointerdown = (e) => {
    sp.setPointerCapture(e.pointerId); sp.classList.add("dragging");
    sp.onpointermove = (m) => setW(bench.getBoundingClientRect().right - 16 - m.clientX);
  };
  sp.onpointerup = () => { sp.onpointermove = null; sp.classList.remove("dragging"); };
  sp.onkeydown = (e) => {
    const cur = document.querySelector(".breadboard").getBoundingClientRect().width;
    if (e.key === "ArrowLeft") setW(cur + 24); if (e.key === "ArrowRight") setW(cur - 24);
  };
}

// ---------- Files sidebar ----------
const files = filesPanel({ $, api, toast, esc, tilde: (p) => tilde(p), token: T });

// ---------- render ----------
function render() {
  files.status(status);
  renderSummary(); renderSettings(); updateControls(); renderScreen();
  if (!$("setup").hidden && !state.busy) renderSetup();
  const ll = $("layout-list"), names = state.layouts;
  fill(ll, names.length ? names : [""], ll.value, names.length ? names : ["No saved layouts yet"]);
  $("layout-load").disabled = $("layout-export").disabled = !names.length;
}
async function refresh() {
  [state, ready] = await Promise.all([api("/api/state"), api("/api/readiness")]);
  status = state.status; render(); renderReadiness();
}

// ---------- readiness stop light ----------
function refreshReady() {
  api("/api/state").then((st) => { state = st; return api("/api/readiness"); })
    .then((r) => { ready = r; renderReadiness(); updateControls(); renderSummary(); }).catch(() => {});
}
const readyDlg = $("ready-dlg");
$("ready-btn").onclick = () => readyDlg.showModal();
document.querySelectorAll("[data-open-ready]").forEach((b) => (b.onclick = () => readyDlg.showModal()));
const STATE_WORD = { ok: "Done", warn: "Optional, works slower", missing: "Needed before Boot", waiting: "Happens later" };
function renderReadiness() {
  if (!ready) return;
  const todo = ready.rows.filter((r) => r.required && r.state !== "ok");
  const settingUp = !!state?.busy;
  $("ready-btn").querySelector(".light").className = "light " + (settingUp ? "warn" : ready.level);
  $("ready-text").textContent = settingUp ? "Setting up" : ready.ready ? (ready.level === "ok" ? "Ready to boot" : "Ready, slower") : `${todo.length} to set up`;
  $("ready-btn").setAttribute("aria-label", `Readiness checklist: ${$("ready-text").textContent}`);
  $("ready-summary").textContent = ready.ready
    ? (ready.level === "ok" ? "Everything is ready. Press Boot." : "Ready to boot. Amber items only make it slower.")
    : `Before the first boot: ${todo.map((r) => r.title).join(", ")}.`;
  for (const [id, compact] of [["ready-inline", true], ["ready-full", false]]) {
    $(id).innerHTML = ready.rows.map((r) => {
      const fixes = [r.fix, r.fix?.alt].filter(Boolean).map((f) => `<button type="button" class="btn" data-fix="${esc(f.action)}">${esc(f.label)}</button>`).join("");
      return `<li><span class="light ${esc(r.state)}" role="img" aria-label="${esc(STATE_WORD[r.state])}"></span>
        <span class="what"><strong>${esc(r.title)}</strong><span class="state">${esc(r.short)}</span></span>
        <p class="detail">${esc(r.detail)}</p>${fixes ? `<span class="fixes">${fixes}</span>` : ""}</li>`;
    }).join("");
  }
}
document.addEventListener("click", act(async (e) => {
  const b = e.target.closest("[data-fix]"); if (!b) return;
  const kind = b.dataset.fix;
  if (kind === "reveal") return api("/api/reveal", { what: "data" });
  readyDlg.close(); setupOpen = true; render();
  const radio = $("os-choices").querySelector(`input[value="${kind === "choose" ? "local" : "desktop"}"]`);
  if (radio) { radio.checked = true; $("os-choices").onchange(); }
  (kind === "choose" ? $("src-path") : $("img-pass").value ? $("img-add") : $("img-pass")).focus();
}));

// ---------- info tips: hover, focus or click (touch); Escape closes ----------
const TIPS = {
  ram: "<p>How much memory the Pi gets. A real Zero 2 W has 512 MB. More makes the desktop smoother but takes it from your computer.</p>",
  cpus: "<p>The Zero 2 W has 4 cores. Fewer leaves more of your computer free for other things.</p>",
  accel: "<p><b>Fast (Apple HVF)</b>: Apple's built-in hypervisor runs the Pi's CPU directly on your Mac's cores. Fastest. Apple Silicon only.</p><p><b>Emulated (TCG)</b>: QEMU translates every Pi instruction in software. Works on any computer, several times slower.</p><p><b>KVM</b> is Linux's hypervisor; it can't run this Pi model yet, so Linux and Windows use TCG.</p>",
  gpu: "<p><b>Venus</b>: passes the Pi's Vulkan graphics to your computer's GPU (through Metal on a Mac). Fastest 3D.</p><p><b>virgl</b>: the older OpenGL route to your GPU. Try it if Venus misbehaves.</p><p><b>Software</b>: the Pi draws everything on the CPU. Always works; 3D is slow.</p>",
  display: "<p><b>In Zero Lab</b> shows the Pi's screen in this window. <b>Separate window</b> uses QEMU's own window instead, which can feel snappier.</p>",
  network: "<p>Lets the Pi reach the internet through your computer, for things like apt and pip. Sending your code to the Pi works either way.</p>",
  snapshot: "<p><b>On</b>: each boot starts from the last saved state and today's changes are thrown away when the Pi stops. Good for experiments.</p><p><b>Off</b>: the Pi keeps its files, like a real SD card.</p>",
};
const tipbox = Object.assign(document.createElement("div"), { id: "tipbox", role: "tooltip", hidden: true });
let tipOwner = null, tipPinned = false;
function showTip(btn) {
  if (tipOwner && tipOwner !== btn) tipOwner.setAttribute("aria-expanded", "false");
  tipOwner = btn; tipbox.innerHTML = TIPS[btn.dataset.tip] || "";
  (btn.closest("dialog") || document.body).append(tipbox);
  tipbox.hidden = false; btn.setAttribute("aria-expanded", "true"); btn.setAttribute("aria-describedby", "tipbox");
  const r = btn.getBoundingClientRect(), w = tipbox.offsetWidth, h = tipbox.offsetHeight;
  tipbox.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2)) + "px";
  tipbox.style.top = (r.bottom + 8 + h < innerHeight ? r.bottom + 8 : r.top - h - 8) + "px";
}
function hideTip() {
  tipbox.hidden = true; tipPinned = false;
  if (tipOwner) { tipOwner.setAttribute("aria-expanded", "false"); tipOwner.removeAttribute("aria-describedby"); tipOwner = null; }
}
document.querySelectorAll(".tip").forEach((b) => {
  b.setAttribute("aria-expanded", "false");
  b.onmouseenter = b.onfocus = () => showTip(b);
  b.onmouseleave = b.onblur = () => { if (!tipPinned) hideTip(); };
  b.onclick = (e) => { e.preventDefault(); if (tipPinned && tipOwner === b) hideTip(); else { showTip(b); tipPinned = true; } };
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !tipbox.hidden) { e.preventDefault(); e.stopPropagation(); hideTip(); } }, true);
document.addEventListener("pointerdown", (e) => { if (tipPinned && !e.target.closest(".tip")) hideTip(); });

// Deep links for help pages and docs: #checklist, #settings, #tip-<name> (e.g. #tip-accel).
function openFromHash() {
  const h = location.hash.slice(1);
  if (h === "checklist") readyDlg.showModal();
  else if (h === "settings") dlg.showModal();
  else if (h.startsWith("tip-") && TIPS[h.slice(4)]) {
    dlg.showModal();
    const b = document.querySelector(`.tip[data-tip="${h.slice(4)}"]`);
    if (b) { showTip(b); tipPinned = true; }
  }
}
window.addEventListener("hashchange", openFromHash);
refresh().then(openFromHash).catch((e) => toast(e.message));
