// Parts on the breadboard: inputs drive guest GPIO pins (or the emulated MCP3008 ADC), outputs show guest pin levels.
const DEFAULTS = {
  button: { label: "Button", pins: [17], idle: 1 }, switch: { label: "Switch", pins: [22], on: false },
  knob: { label: "Knob", pins: [5, 6, 13, 19], value: 0 }, led: { label: "LED", pins: [27], color: "#ff3b30", activeLow: false },
  seg7: { label: "7-segment", pins: [21, 20, 16, 12, 24, 23, 25], activeLow: false }, probe: { label: "Probe", pins: [27] },
  slider: { label: "Slider", pins: [], mode: "adc", channel: 1, value: 0 },
};
const ADC_MAX = 1023; // MCP3008: 10 bits
const SEGS = ["4,2 24,2 20,6 8,6", "26,4 26,24 22,21 22,8", "26,28 26,48 22,44 22,31", "4,50 24,50 20,46 8,46",
  "2,28 2,48 6,44 6,31", "2,4 2,24 6,21 6,8", "4,26 8,23 20,23 24,26 20,29 8,29"];
// Free pins to hand out, best first: avoids 0/1 (ID EEPROM), 2/3 (I2C), 14/15 (UART) and 7-11 (SPI0, the ADC) until nothing else is left.
const PIN_ORDER = [5, 6, 13, 19, 26, 16, 20, 21, 12, 25, 24, 23, 22, 27, 17, 18, 4, 2, 3, 14, 15, 9, 10, 11, 7, 8, 0, 1];
const SAVE_KEYS = ["id", "type", "x", "y", "label", "pins", "idle", "on", "value", "color", "activeLow", "mode", "channel"];

export function breadboard({ canvas, drive, adc, lev, esc }) {
  let widgets = [];
  const pinText = (w) => (w.mode === "adc" ? `MCP3008 CH${w.channel}` : w.pins.length === 1 ? `GPIO${w.pins[0]}` : `GPIO ${w.pins.join(", ")}`);

  function make(spec) {
    const w = { ...DEFAULTS[spec.type], ...spec, id: spec.id || crypto.randomUUID() };
    w.pins = (Array.isArray(w.pins) ? w.pins : []).map(Number).filter((n) => n >= 0 && n < 28).slice(0, 8);
    w.x = +w.x || 0; w.y = +w.y || 0; w.label = String(w.label ?? ""); w.value = +w.value || 0;
    if (w.mode === "adc") { w.pins = []; w.channel = Math.max(0, Math.min(7, +w.channel || 0)); } // analog parts hold no GPIO pins
    else if (!w.pins.length) w.pins = [...DEFAULTS[spec.type].pins];
    const el = document.createElement("div");
    el.className = "w"; el.style.left = w.x + "px"; el.style.top = w.y + "px";
    el.innerHTML = `<div class="t"><span></span><button type="button" aria-label="Part settings" aria-expanded="false">⚙</button><button type="button" aria-label="Remove part">✕</button></div><div class="b"></div>`;
    const body = el.querySelector(".b"), title = el.querySelector(".t span");
    const relabel = () => {
      title.textContent = `${w.label} on ${pinText(w)}`;
      body.querySelector("[aria-label]")?.setAttribute("aria-label", `${w.label} on ${pinText(w)}`);
    };
    const outActive = (p) => (lev(p) === (w.activeLow ? 0 : 1));

    if (w.type === "button") {
      body.innerHTML = `<button type="button" class="pushbtn" aria-label=""></button>`;
      const b = body.firstChild;
      const press = (down) => { b.classList.toggle("down", down); drive(w.pins[0], down ? 1 - w.idle : w.idle); };
      b.onpointerdown = (e) => { b.setPointerCapture(e.pointerId); press(true); };
      b.onpointerup = b.onpointercancel = () => press(false);
      b.onkeydown = (e) => { if ((e.key === " " || e.key === "Enter") && !e.repeat) { e.preventDefault(); press(true); } };
      b.onkeyup = (e) => { if (e.key === " " || e.key === "Enter") press(false); };
      w.applyIdle = () => drive(w.pins[0], w.idle);
    } else if (w.type === "switch") {
      body.innerHTML = `<button type="button" class="toggle" role="switch" aria-label=""></button>`;
      const b = body.firstChild;
      const show = () => { b.classList.toggle("on", w.on); b.setAttribute("aria-checked", String(w.on)); };
      b.onclick = () => { w.on = !w.on; show(); drive(w.pins[0], w.on ? 1 : 0); };
      w.applyIdle = () => drive(w.pins[0], w.on ? 1 : 0); show();
    } else if (w.type === "knob") {
      body.innerHTML = `<div class="knob" tabindex="0" role="slider" aria-label="" aria-valuemin="0"><div></div></div>`;
      const k = body.firstChild, max = () => (w.mode === "adc" ? ADC_MAX : (1 << w.pins.length) - 1);
      const send = () => (w.mode === "adc" ? adc(w.channel, w.value) : w.pins.forEach((p, i) => drive(p, (w.value >> i) & 1)));
      const show = () => { k.style.setProperty("--a", `${(360 * w.value) / max()}deg`); k.firstChild.textContent = w.value;
        k.setAttribute("aria-valuenow", w.value); k.setAttribute("aria-valuemax", max()); };
      const set = (v) => { v = Math.max(0, Math.min(max(), v)); if (v === w.value) return; w.value = v; show(); send(); };
      // Drag up/down: 6 px per step for pins; the full analog range takes 256 px.
      const perPx = () => (w.mode === "adc" ? ADC_MAX / 256 : 1 / 6), key = () => (w.mode === "adc" ? 16 : 1);
      k.onpointerdown = (e) => { k.setPointerCapture(e.pointerId); const y0 = e.clientY, v0 = w.value;
        k.onpointermove = (m) => set(v0 + Math.round((y0 - m.clientY) * perPx())); };
      k.onpointerup = () => (k.onpointermove = null);
      k.onkeydown = (e) => { if (e.key === "ArrowUp" || e.key === "ArrowRight") set(w.value + key()); if (e.key === "ArrowDown" || e.key === "ArrowLeft") set(w.value - key()); };
      w.applyIdle = send; show();
      w.redraw = () => { w.value = Math.min(w.value, max()); show(); };
    } else if (w.type === "slider") {
      body.innerHTML = `<input type="range" class="slider" min="0" max="${ADC_MAX}" aria-label=""><output></output>`;
      const [r, out] = body.children;
      r.value = w.value = Math.min(w.value, ADC_MAX); out.textContent = w.value;
      r.oninput = () => { w.value = +r.value; out.textContent = w.value; adc(w.channel, w.value); };
      w.applyIdle = () => adc(w.channel, w.value);
      w.redraw = () => {}; // a settings change re-sends the value (to a new channel)
    } else if (w.type === "led") {
      body.innerHTML = `<div class="led" role="img" aria-label="" style="color:${esc(w.color)}"></div>`;
      w.update = () => { const on = outActive(w.pins[0]); body.firstChild.classList.toggle("on", on); };
    } else if (w.type === "seg7") {
      body.innerHTML = `<svg class="seg7" viewBox="0 0 28 52" width="40" height="74" role="img" aria-label="">${SEGS.map((p) => `<polygon points="${p}"/>`).join("")}</svg>`;
      w.update = () => body.querySelectorAll("polygon").forEach((s, i) => s.classList.toggle("on", w.pins[i] !== undefined && outActive(w.pins[i])));
    } else if (w.type === "probe") {
      body.innerHTML = `<canvas class="probe" width="140" height="34" role="img" aria-label=""></canvas>`;
      const c = body.firstChild.getContext("2d"), hist = [];
      w.update = () => hist.push([performance.now(), lev(w.pins[0])]);
      const draw = () => {
        if (!el.isConnected) return;
        const now = performance.now(); while (hist.length > 1 && hist[1][0] < now - 10000) hist.shift();
        c.clearRect(0, 0, 140, 34); c.strokeStyle = "#7CFC9A"; c.beginPath();
        let lv = hist.length ? hist[0][1] : lev(w.pins[0]); c.moveTo(0, lv ? 7 : 27);
        for (const [t, v] of hist) { const x = 140 * (1 - (now - t) / 10000); c.lineTo(x, lv ? 7 : 27); c.lineTo(x, v ? 7 : 27); lv = v; }
        c.lineTo(140, lv ? 7 : 27); c.stroke(); requestAnimationFrame(draw);
      };
      requestAnimationFrame(draw);
    }
    relabel();

    const [gear, close] = el.querySelectorAll(".t button");
    close.onclick = () => { el.remove(); widgets = widgets.filter((x) => x !== w); };
    gear.onclick = () => {
      // Settings open in a dialog, so the board's edges can never clip them.
      const dlg = document.getElementById("part-dlg");
      const cfg = dlg.querySelector(".cfg");
      dlg.querySelector("h2").textContent = `${w.label} settings`;
      const chOpts = (v) => [0, 1, 2, 3, 4, 5, 6, 7].map((n) => `<option value="${v(n)}" ${w.mode === "adc" && w.channel === n ? "selected" : ""}>Analog (MCP3008 channel ${n})</option>`).join("");
      cfg.innerHTML = `<label class="field">Name <input data-k="label" value="${esc(w.label)}"></label>` +
        (w.type === "knob" ? `<label class="field">Sends <select data-k="mode"><option value="pins" ${w.mode !== "adc" ? "selected" : ""}>Binary number on GPIO pins</option>${chOpts((n) => `adc${n}`)}</select></label>` : "") +
        (w.type === "slider" ? `<label class="field">Sends <select data-k="channel">${chOpts((n) => n)}</select></label>` : "") +
        (w.type === "slider" ? "" : `<div class="pins-cfg" ${w.mode === "adc" ? "hidden" : ""}><label class="field">GPIO pins${w.type === "seg7" ? " for a,b,c,d,e,f,g" : w.type === "knob" ? ", lowest bit first" : ""} <input data-k="pins" value="${w.pins.join(",")}" inputmode="numeric"></label>`) +
        (w.type === "button" ? `<label class="check"><input type="checkbox" data-k="idle" ${w.idle ? "checked" : ""}> Reads 1 until pressed (pull-up)</label>` : "") +
        (w.type === "led" || w.type === "seg7" ? `<label class="check"><input type="checkbox" data-k="activeLow" ${w.activeLow ? "checked" : ""}> Lights when the pin is 0</label>` : "") +
        (w.type === "led" ? `<label class="field">Colour <input type="color" data-k="color" value="${esc(w.color)}"></label>` : "") +
        (w.type === "knob" ? `<label class="field">Steps (more steps use more pins)
          <select data-k="steps">${[2, 4, 8, 16, 32, 64, 128, 256].map((n) => `<option value="${n}" ${n === 1 << w.pins.length ? "selected" : ""}>${n} steps, ${Math.log2(n)} pin${n > 2 ? "s" : ""}</option>`).join("")}</select></label>
          <p class="note">A Pi pin is only on or off, so the knob sends its position as a binary number across these pins.</p>` : "") +
        (w.type === "slider" ? "" : "</div>") +
        (w.type === "knob" || w.type === "slider" ? `<p class="note">Analog parts feed the emulated MCP3008 ADC on SPI0 (CE0), 0-1023. Read it in Python with <code>gpiozero.MCP3008(channel=N).value</code>.</p>` : "");
      const pinsInput = cfg.querySelector('[data-k="pins"]'), steps = (bits) => {
        const used = new Set(widgets.filter((x) => x !== w).flatMap((x) => x.pins));
        w.pins = w.pins.slice(0, bits);
        for (const p of PIN_ORDER) { if (w.pins.length >= bits) break; if (!used.has(p) && !w.pins.includes(p)) w.pins.push(p); }
        pinsInput.value = w.pins.join(",");
      };
      cfg.oninput = (e) => {
        const i = e.target, k = i.dataset.k;
        if (k === "pins") { const ps = i.value.split(",").map((s) => parseInt(s, 10)).filter((n) => n >= 0 && n < 28); if (ps.length) w.pins = ps.slice(0, 8); }
        else if (k === "steps") steps(Math.log2(+i.value));
        else if (k === "mode") { // knob: binary pins <-> analog channel, keeping its position
          const was = w.mode === "adc" ? ADC_MAX : (1 << w.pins.length) - 1, frac = w.value / was;
          if (i.value === "pins") { w.mode = "pins"; if (!w.pins.length) steps(4); } else { w.mode = "adc"; w.channel = +i.value.slice(3); w.pins = []; }
          w.value = Math.round(frac * (w.mode === "adc" ? ADC_MAX : (1 << w.pins.length) - 1));
          cfg.querySelector(".pins-cfg").hidden = w.mode === "adc";
        }
        else if (k === "channel") w.channel = +i.value;
        else if (k === "idle") w.idle = i.checked ? 1 : 0;
        else if (k === "activeLow") w.activeLow = i.checked;
        else if (k) w[k] = i.value;
        if (w.type === "led") body.firstChild.style.color = w.color;
        if (w.redraw) { w.redraw(); w.applyIdle?.(); }
        relabel(); w.update && w.update();
      };
      dlg.onclose = () => { cfg.innerHTML = ""; cfg.oninput = null; gear.focus(); };
      dlg.showModal();
      cfg.querySelector("input").focus();
    };

    const bar = el.querySelector(".t");
    bar.onpointerdown = (e) => {
      if (e.target.tagName === "BUTTON") return;
      bar.setPointerCapture(e.pointerId); const dx = e.clientX - w.x, dy = e.clientY - w.y;
      bar.onpointermove = (m) => { w.x = Math.max(0, m.clientX - dx); w.y = Math.max(0, m.clientY - dy); el.style.left = w.x + "px"; el.style.top = w.y + "px"; };
    };
    bar.onpointerup = () => (bar.onpointermove = null);

    canvas.append(el); widgets.push(w); w.update && w.update();
    return w;
  }

  return {
    make,
    update: () => widgets.forEach((w) => w.update && w.update()),
    applyIdle: () => widgets.forEach((w) => w.applyIdle && w.applyIdle()),
    layout: () => ({ version: 1, widgets: widgets.map((w) => Object.fromEntries(SAVE_KEYS.filter((k) => k in w).map((k) => [k, w[k]]))) }),
    load(l) {
      if (!l || l.version !== 1 || !Array.isArray(l.widgets)) throw new Error("That file is not a Zero Lab layout");
      canvas.innerHTML = ""; widgets = [];
      for (const s of l.widgets) if (DEFAULTS[s.type]) make(s);
    },
  };
}
