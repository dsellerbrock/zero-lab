// The Files sidebar: browse the Pi's file system over the app's loopback SSH, move files in and out.
const ICON = {
  folder: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M1.5 3.5h5l1.5 1.5h6.5v8h-13z" fill="currentColor" opacity=".85"/></svg>',
  file: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 1.5h6l3 3v10h-9z" fill="none" stroke="currentColor"/></svg>',
  link: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 1.5h6l3 3v10h-9z" fill="none" stroke="currentColor" stroke-dasharray="2 1.5"/></svg>',
};
const size = (n) => (n < 1024 ? `${n} B` : n < 1 << 20 ? `${(n / 1024).toFixed(0)} KB` : n < 1 << 30 ? `${(n / (1 << 20)).toFixed(1)} MB` : `${(n / (1 << 30)).toFixed(1)} GB`);
const when = (t) => new Date(t * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });

export function filesPanel({ $, api, toast, esc, tilde, token }) {
  const root = $("files"), list = $("fs-list"), crumbs = $("fs-crumbs"), prog = $("fs-progress");
  let cwd = null, entries = [], running = false, home = "/home/pi";

  // ----- open / closed, remembered per browser -----
  const KEY = "zerolab.files.open";
  const setOpen = (open) => {
    root.classList.toggle("open", open);
    $("fs-toggle").setAttribute("aria-expanded", String(open));
    $("fs-toggle").setAttribute("aria-label", open ? "Close the Files sidebar" : "Open the Files sidebar");
    try { localStorage.setItem(KEY, open ? "1" : "0"); } catch { /* private mode: not remembered */ }
    if (open && running && cwd === null) go(home);
  };
  $("fs-toggle").onclick = () => setOpen(!root.classList.contains("open"));
  let remembered = false;
  try { remembered = localStorage.getItem(KEY) === "1"; } catch { /* ignore */ }
  setOpen(remembered);

  // ----- confirm dialog that also works inside the macOS app window -----
  const dlg = $("confirm-dlg");
  const confirmBox = (text, ok) => new Promise((resolve) => {
    $("confirm-text").textContent = text; $("confirm-ok").textContent = ok;
    dlg.onclose = () => resolve(dlg.returnValue === "ok");
    dlg.showModal(); $("confirm-cancel").focus();
  });

  // ----- listing -----
  async function go(path) {
    if (!running) return;
    try {
      const r = await api(`/api/fs/list?path=${encodeURIComponent(path)}&hidden=${$("fs-hidden").checked ? 1 : 0}`);
      cwd = r.path; entries = r.entries; render();
    } catch (e) { toast(e.message); }
  }
  const join = (dir, name) => (dir === "/" ? "/" + name : `${dir}/${name}`);
  function render() {
    const parts = cwd.split("/").filter(Boolean);
    crumbs.innerHTML = `<button type="button" data-path="/">/</button>` + parts.map((p, i) =>
      `<span aria-hidden="true">›</span><button type="button" data-path="/${esc(parts.slice(0, i + 1).join("/"))}">${esc(p)}</button>`).join("");
    crumbs.querySelectorAll("button").forEach((b) => (b.onclick = () => go(b.dataset.path)));
    crumbs.lastElementChild?.setAttribute("aria-current", "location");
    list.innerHTML = entries.length ? entries.map((e, i) => `
      <li role="option" tabindex="${i ? -1 : 0}" aria-selected="false" data-i="${i}" class="${e.dir ? "dir" : ""}"
          aria-label="${esc(e.name)}, ${e.dir ? "folder" : size(e.size)}">
        <span class="ic">${ICON[e.dir ? "folder" : e.link ? "link" : "file"]}</span>
        <span class="nm">${esc(e.name)}</span>
        <span class="mt">${e.dir ? "" : size(e.size)}</span>
        <span class="mt">${when(e.mtime)}</span>
        <span class="acts">
          <button type="button" data-act="get" aria-label="Download ${esc(e.name)} to Downloads" title="Download">⤓</button>
          <button type="button" data-act="ren" aria-label="Rename ${esc(e.name)}" title="Rename">✎</button>
          <button type="button" data-act="del" aria-label="Delete ${esc(e.name)}" title="Delete">✕</button>
        </span></li>`).join("") : `<li class="empty">This folder is empty. Drop files here to copy them in.</li>`;
  }
  const rowOf = (el) => el.closest("li[data-i]");
  const entryOf = (li) => entries[+li.dataset.i];

  async function act(kind, e) {
    const path = join(cwd, e.name);
    if (kind === "open") return e.dir ? go(path) : act("get", e);
    if (kind === "get") {
      toast(`Copying ${e.name} to Downloads`);
      const r = await api("/api/fs/download", { path });
      return toast("Saved to " + tilde(r.path));
    }
    if (kind === "del") {
      if (!(await confirmBox(`Delete “${e.name}”${e.dir ? " and everything in it" : ""} from the Pi? This can't be undone.`, "Delete"))) return;
      await api("/api/fs/delete", { path }); toast(`Deleted ${e.name}`); return go(cwd);
    }
    if (kind === "ren") {
      const li = list.querySelector(`li[data-i="${entries.indexOf(e)}"]`), nm = li.querySelector(".nm");
      const input = Object.assign(document.createElement("input"), { value: e.name, className: "rename", ariaLabel: `New name for ${e.name}` });
      nm.replaceWith(input); input.focus(); input.select();
      const done = async (save) => {
        input.onblur = null;
        if (save && input.value && input.value !== e.name) {
          try { await api("/api/fs/rename", { path, name: input.value }); } catch (err) { toast(err.message); }
        }
        go(cwd);
      };
      input.onkeydown = (k) => { if (k.key === "Enter") done(true); if (k.key === "Escape") done(false); k.stopPropagation(); };
      input.onblur = () => done(true);
    }
  }
  list.onclick = (ev) => {
    const li = rowOf(ev.target); if (!li) return;
    const b = ev.target.closest("button[data-act]");
    if (b) return guard(act(b.dataset.act, entryOf(li)));
    focusRow(li);
  };
  list.ondblclick = (ev) => { const li = rowOf(ev.target); if (li && !ev.target.closest("button")) guard(act("open", entryOf(li))); };
  const guard = (p) => p?.catch?.((e) => toast(e.message));

  // ----- keyboard: roving focus through the rows -----
  function focusRow(li) {
    list.querySelectorAll("li[data-i]").forEach((x) => { x.tabIndex = -1; x.setAttribute("aria-selected", "false"); });
    li.tabIndex = 0; li.setAttribute("aria-selected", "true"); li.focus();
  }
  list.onkeydown = (ev) => {
    const li = rowOf(document.activeElement); if (!li || ev.target.tagName === "INPUT") return;
    const rows = [...list.querySelectorAll("li[data-i]")], i = rows.indexOf(li);
    const k = ev.key;
    if (k === "ArrowDown" || k === "ArrowUp") { ev.preventDefault(); const n = rows[i + (k === "ArrowDown" ? 1 : -1)]; if (n) focusRow(n); }
    else if (k === "Home" || k === "End") { ev.preventDefault(); focusRow(rows[k === "Home" ? 0 : rows.length - 1]); }
    else if (k === "Enter") guard(act("open", entryOf(li)));
    else if (k === "Backspace") { ev.preventDefault(); up(); }
    else if (k === "F2") guard(act("ren", entryOf(li)));
    else if (k === "Delete") guard(act("del", entryOf(li)));
  };
  const up = () => { if (cwd !== "/") go(cwd.replace(/\/[^/]+$/, "") || "/"); };

  // ----- toolbar -----
  $("fs-up").onclick = up;
  $("fs-refresh").onclick = () => go(cwd ?? home);
  $("fs-hidden").onchange = () => go(cwd ?? home);
  $("fs-home").onclick = () => go(home);
  $("fs-mkdir").onclick = async () => {
    let name = "New folder", n = 2;
    while (entries.some((e) => e.name === name)) name = `New folder ${n++}`;
    try { await api("/api/fs/mkdir", { path: join(cwd, name) }); await go(cwd); act("ren", entries.find((e) => e.name === name)); } catch (e) { toast(e.message); }
  };
  $("fs-term").onclick = () => guard(api("/api/fs/terminal", { path: cwd }).then(() => toast("Opened a terminal on the Pi's desktop")));
  const picker = $("fs-pick");
  $("fs-upload").onclick = () => picker.click();
  picker.onchange = () => { upload([...picker.files].map((f) => [f.name, f]), cwd); picker.value = ""; };

  // ----- copying in: drop on the list (current folder) or on a folder row -----
  async function walk(entry, prefix, out) {
    if (entry.isFile) out.push([prefix + entry.name, await new Promise((ok, err) => entry.file(ok, err))]);
    else if (entry.isDirectory) {
      const r = entry.createReader();
      for (let batch; (batch = await new Promise((ok, err) => r.readEntries(ok, err))).length;)
        for (const e of batch) await walk(e, prefix + entry.name + "/", out);
    }
  }
  root.ondragover = (ev) => { if (!running) return; ev.preventDefault(); root.classList.add("over");
    list.querySelectorAll("li.drop").forEach((x) => x.classList.remove("drop"));
    const li = rowOf(ev.target); if (li) li.classList.toggle("drop", !!entryOf(li).dir); };
  root.ondragleave = (ev) => { if (!root.contains(ev.relatedTarget)) root.classList.remove("over"); };
  root.ondrop = async (ev) => {
    ev.preventDefault(); root.classList.remove("over"); if (!running) return;
    const li = rowOf(ev.target), target = li && entryOf(li).dir ? join(cwd, entryOf(li).name) : cwd;
    const items = []; for (const en of [...ev.dataTransfer.items].map((i) => i.webkitGetAsEntry()).filter(Boolean)) await walk(en, "", items);
    upload(items, target);
  };
  function send(path, file, overwrite) {
    return new Promise((resolve, reject) => {
      const x = new XMLHttpRequest();
      x.open("POST", `/api/fs/upload?path=${encodeURIComponent(path)}&overwrite=${overwrite ? 1 : 0}`);
      x.setRequestHeader("X-Zero-Lab-Token", token);
      x.upload.onprogress = (p) => p.lengthComputable && showProgress(file.name, p.loaded / p.total);
      x.onload = () => (x.status === 200 ? resolve() : reject(Object.assign(new Error(JSON.parse(x.responseText || "{}").error || x.statusText), { status: x.status })));
      x.onerror = () => reject(new Error("upload failed"));
      x.send(file);
    });
  }
  function showProgress(name, frac, label) {
    prog.hidden = false;
    prog.innerHTML = `<span>${esc(label || `Copying ${name}`)}</span><span class="pct">${Math.round(frac * 100)}%</span><span class="bar"><i style="width:${frac * 100}%"></i></span>`;
  }
  async function upload(items, dir) {
    if (!items.length) return;
    const tops = [...new Set(items.map(([p]) => p.split("/")[0]))];
    const clash = dir === cwd ? tops.filter((t) => entries.some((e) => e.name === t)) : [];
    let overwrite = false;
    if (clash.length) {
      overwrite = await confirmBox(`${clash.length === 1 ? `“${clash[0]}” is` : `${clash.length} items are`} already in ${dir}. Replace ${clash.length === 1 ? "it" : "them"}?`, "Replace");
      if (!overwrite) return;
    }
    let done = 0;
    try {
      for (const [rel, file] of items) {
        showProgress(rel, 0, `Copying ${rel} (${done + 1} of ${items.length})`);
        await send(join(dir, rel), file, overwrite);
        done++;
      }
      toast(`Copied ${done} item${done === 1 ? "" : "s"} to ${dir}`);
    } catch (e) {
      toast(e.status === 409 ? `${e.message === "exists" ? "Already on the Pi" : e.message}; nothing replaced` : e.message);
    } finally {
      prog.hidden = true; go(cwd);
    }
  }

  return {
    status(s) {
      if ((s === "running") === running && (running || cwd === null)) return;
      running = s === "running";
      root.classList.toggle("live", running);
      $("fs-off").hidden = running; $("fs-on").hidden = !running;
      if (!running) { cwd = null; entries = []; list.innerHTML = ""; return; }
      api("/api/fs/home").then((r) => { home = r.path; if (root.classList.contains("open") && cwd === null) go(home); }).catch(() => {});
    },
  };
}
