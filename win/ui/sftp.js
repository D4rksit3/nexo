"use strict";
/* Pestaña SFTP: «Este equipo» a la izquierda, el servidor a la derecha.
   Transferir: botones Subir/Bajar, arrastrar de un panel al otro, o soltar archivos del Explorador
   sobre el panel del servidor. Doble clic en un archivo del servidor: se edita en tu equipo y se
   sube al guardar. */

let dropPane = null;   // panel bajo el cursor mientras se arrastran archivos desde el Explorador

function joinLocal(dir, name) {
  if (!dir) return name;  // lista de unidades: el «nombre» ya es la ruta (C:\)
  return dir.endsWith(INFO.sep) ? dir + name : dir + INFO.sep + name;
}
function joinRemote(dir, name) { return dir.endsWith("/") ? dir + name : dir + "/" + name; }
function parentRemote(p) { if (p === "/") return "/"; const i = p.replace(/\/+$/, "").lastIndexOf("/"); return i <= 0 ? "/" : p.slice(0, i); }

async function openSftp(h, password = null) {
  if (h.needs_password && password == null) {
    password = await askPassword(h);
    if (password == null) return;
  }
  const t = addTab("sftp", h.name, "folder2-open");
  t.host = h;
  t.pane.append(el("div", "loading", `Conectando a ${hostSub(h)}…`));
  activate(t.id);
  const r = await call("open_sftp", h.id, password);
  if (!r.ok) {
    setState(t, "closed");
    t.pane.replaceChildren(errorBox(r.error, () => { closeTab(t.id); openSftp(h, password); }));
    return;
  }
  setState(t, "connected");
  t.sid = r.sid;
  t.password = password;
  buildSftp(t, r.home);
}
function errorBox(text, retry) {
  const b = el("div", "error-box");
  b.append(icon("exclamation-triangle"), el("p", null, text));
  if (retry) b.append(btn("Reintentar", { cls: "primary small", icon: "arrow-clockwise", onClick: retry }));
  return b;
}

function buildSftp(t, home) {
  t.pane.replaceChildren();
  const wrap = el("div", "files");
  const local = makeFilePane(t, "local", "Este equipo", "pc-display");
  const remote = makeFilePane(t, "remote", t.host.name, "hdd-rack");
  wrap.append(local.root, remote.root);
  const status = el("div", "files-status");
  const msg = el("span", "grow muted");
  const bar = el("div", "progress");
  const fill = el("div");
  bar.append(fill);
  bar.hidden = true;
  const cancel = btn("Cancelar", { cls: "small", onClick: () => call("sftp_cancel", t.sid) });
  cancel.hidden = true;
  status.append(msg, bar, cancel);
  t.pane.append(wrap, status);
  Object.assign(t, { local, remote, status: { msg, bar, fill, cancel } });
  t.onClose = () => { clearInterval(t.poll); api.close_session(t.sid); };
  t.focus = () => (t.lastPane || remote).list.focus();
  t.reconnect = () => { closeTab(t.id); openSftp(t.host, t.password); };
  local.load(INFO.home);
  remote.load(home);
}

function setStatus(t, text, error = false) {
  t.status.msg.textContent = text;
  t.status.msg.classList.toggle("err", error);
}

function makeFilePane(t, side, title, iconName) {
  const isRemote = side === "remote";
  const root = el("div", "fpane " + side);
  const head = el("div", "fpane-head");
  head.append(icon(iconName), el("span", "fpane-title", title));
  const tools = el("div", "fpane-tools");
  const bUp = btn("", { cls: "icon-btn", icon: "arrow-up", title: "Subir un nivel (Retroceso)" });
  const bHome = btn("", { cls: "icon-btn", icon: "house", title: "Carpeta personal" });
  const bRefresh = btn("", { cls: "icon-btn", icon: "arrow-clockwise", title: "Actualizar (F5)" });
  const bNew = btn("", { cls: "icon-btn", icon: "folder-plus", title: "Nueva carpeta" });
  const path = input("", { className: "fpath", title: "Escribe una ruta y Enter" });
  const bXfer = isRemote
    ? btn("Bajar", { cls: "small xfer", icon: "download", title: "Bajar lo seleccionado a «Este equipo» (Ctrl+←)" })
    : btn("Subir", { cls: "small xfer", icon: "upload", title: "Subir lo seleccionado al servidor (Ctrl+→)" });
  tools.append(bUp, bHome, bRefresh, bNew, path, bXfer);
  if (isRemote) {
    const bPick = btn("", { cls: "icon-btn", icon: "file-earmark-arrow-up", title: "Subir archivos o una carpeta desde un selector" });
    bPick.addEventListener("click", e => contextMenu(e, [
      { label: "Subir archivos…", icon: "file-earmark-arrow-up", action: () => pickUpload(t, false) },
      { label: "Subir una carpeta…", icon: "folder-plus", action: () => pickUpload(t, true) },
    ]));
    tools.insertBefore(bPick, bXfer);
  }
  const header = el("div", "frow fhead");
  const cols = [["name", "Nombre"], ["size", "Tamaño"], ["mtime", "Modificado"]];
  const list = el("div", "flist");
  list.tabIndex = 0;
  root.append(head, tools, header, list);

  const p = { root, list, side, cwd: null, entries: [], sel: new Set(), anchor: null, sort: ["name", 1], parent: null };
  for (const [key, label] of cols) {
    const c = el("div", "fcol " + key, label);
    c.addEventListener("click", () => {
      p.sort = [key, p.sort[0] === key ? -p.sort[1] : 1];
      render();
    });
    header.append(c);
  }

  async function load(dir, keepSel = false) {
    const r = isRemote ? await call("sftp_list", t.sid, dir) : await call("local_list", dir);
    if (!r.ok) {
      setStatus(t, `${isRemote ? t.host.name : "Este equipo"}: ${r.error}`, true);
      if (isRemote && /conectad|cerrad|Socket|EOF/i.test(r.error)) setState(t, "closed");
      return false;
    }
    const prev = p.cwd;
    p.cwd = r.path;
    p.parent = isRemote ? parentRemote(r.path) : r.parent;
    p.entries = r.entries;
    if (!keepSel || prev !== p.cwd) p.sel.clear();
    path.value = p.cwd || "Este equipo";
    render();
    return true;
  }
  p.load = load;
  p.refresh = () => load(p.cwd, true);

  function sorted() {
    const [k, dir] = p.sort;
    return [...p.entries].sort((a, b) => {
      if (a.dir !== b.dir) return a.dir ? -1 : 1;
      if (k === "name") return dir * a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" });
      return dir * ((a[k] || 0) - (b[k] || 0)) || a.name.localeCompare(b.name);
    });
  }
  function render() {
    list.replaceChildren();
    $$(".fcol", header).forEach(c => c.classList.toggle("sorted", c.classList.contains(p.sort[0])));
    const items = sorted();
    p.view = items;
    if (!items.length) list.append(el("div", "empty", "Carpeta vacía"));
    for (const e of items) {
      const row = el("div", "frow" + (p.sel.has(e.name) ? " selected" : ""));
      row.dataset.name = e.name;
      const kind = fileKind(e.name, e.dir, e.link);
      const [ic, color] = FILE_KINDS[kind] || FILE_KINDS.file;
      const n = el("div", "fcol name");
      n.append(icon(e.dir && p.cwd === "" ? "hdd-stack" : ic, color), el("span", null, e.name));
      if (e.link) n.append(el("span", "flink", "→"));
      row.append(n, el("div", "fcol size", e.dir ? "" : humanSize(e.size)), el("div", "fcol mtime", humanDate(e.mtime)));
      row.draggable = p.cwd !== "";
      row.addEventListener("mousedown", ev => { if (ev.button === 0 || !p.sel.has(e.name)) clickRow(ev, e.name); });
      row.addEventListener("dblclick", () => openEntry(e));
      row.addEventListener("contextmenu", ev => { if (!p.sel.has(e.name)) clickRow(ev, e.name); contextMenu(ev, entryMenu(e)); });
      row.addEventListener("dragstart", ev => {
        if (!p.sel.has(e.name)) { p.sel = new Set([e.name]); paintSel(); }
        ev.dataTransfer.setData("application/x-nexo-files", JSON.stringify({ tab: t.id, side, dir: p.cwd, names: [...p.sel] }));
        ev.dataTransfer.effectAllowed = "copy";
      });
      list.append(row);
    }
  }
  function paintSel() {
    $$(".frow", list).forEach(r => r.classList.toggle("selected", p.sel.has(r.dataset.name)));
  }
  function clickRow(ev, name) {
    t.lastPane = p;
    const names = p.view.map(x => x.name);
    if (ev.shiftKey && p.anchor != null) {
      const a = names.indexOf(p.anchor), b = names.indexOf(name);
      p.sel = new Set(names.slice(Math.min(a, b), Math.max(a, b) + 1));
    } else if (ev.ctrlKey) {
      p.sel.has(name) ? p.sel.delete(name) : p.sel.add(name);
      p.anchor = name;
    } else {
      p.sel = new Set([name]);
      p.anchor = name;
    }
    paintSel();
  }
  function full(name) { return isRemote ? joinRemote(p.cwd, name) : joinLocal(p.cwd, name); }
  async function openEntry(e) {
    if (e.dir) return load(full(e.name));
    if (isRemote) {
      const r = await call("sftp_edit", t.sid, full(e.name));
      if (!r.ok) return toast(r.error, true);
      setStatus(t, `✎ ${e.name} abierto en tu equipo: cada vez que guardes se sube a ${t.host.name}`);
    } else {
      const r = await call("local_open", full(e.name));
      if (!r.ok) toast(r.error, true);
    }
  }
  function selectedEntries() { return p.entries.filter(e => p.sel.has(e.name)); }
  function entryMenu(e) {
    const many = p.sel.size > 1;
    const items = [];
    if (!many) items.push({ label: e.dir ? "Abrir" : isRemote ? "Editar en este equipo" : "Abrir", icon: e.dir ? "folder2-open" : "pencil",
                            action: () => openEntry(e), hint: "Enter" });
    items.push(isRemote
      ? { label: `Bajar${many ? ` (${p.sel.size})` : ""}`, icon: "download", action: () => transfer(t, "down"), hint: "Ctrl+←" }
      : { label: `Subir al servidor${many ? ` (${p.sel.size})` : ""}`, icon: "upload", action: () => transfer(t, "up"), hint: "Ctrl+→",
          disabled: p.cwd === "" });
    if (!isRemote && !many && p.cwd !== "") items.push({ label: "Mostrar en el Explorador", icon: "folder", action: () => call("local_open", full(e.name), true) });
    items.push({ label: "Copiar ruta", icon: "copy", action: () => copyText(full(e.name), "Ruta copiada") });
    if (p.cwd !== "") {
      items.push("-");
      if (!many) items.push({ label: "Renombrar…", icon: "pencil", action: () => rename(e), hint: "F2" });
      items.push({ label: isRemote ? "Eliminar" : "Mover a la papelera", icon: "trash3", danger: true, action: removeSel, hint: "Supr" });
    }
    return items;
  }
  async function rename(e) {
    const n = await ask("Renombrar", "Nombre nuevo", e.name);
    if (n == null || n === e.name) return;
    const r = isRemote ? await call("sftp_rename", t.sid, full(e.name), n) : await call("local_rename", full(e.name), n);
    r.ok ? load(p.cwd) : toast(r.error, true);
  }
  async function removeSel() {
    const names = [...p.sel];
    if (!names.length || p.cwd === "") return;
    const what = names.length === 1 ? `«${names[0]}»` : `${names.length} elementos`;
    const ok = await confirmDlg(isRemote ? `¿Eliminar ${what} del servidor?` : `¿Mover ${what} a la papelera?`,
      isRemote ? "Las carpetas se borran con todo su contenido. No se puede deshacer." : "Podrás recuperarlo desde la Papelera de reciclaje.",
      isRemote ? "Eliminar" : "Mover a la papelera");
    if (!ok) return;
    setStatus(t, "Eliminando…");
    const r = isRemote ? await call("sftp_delete", t.sid, names.map(full)) : await call("local_trash", names.map(full));
    if (!r.ok) toast(r.error, true); else setStatus(t, `✖ ${what} eliminado(s)`);
    load(p.cwd);
  }
  async function mkdir() {
    if (p.cwd === "") return;
    const n = await ask("Nueva carpeta", "Nombre", "");
    if (n == null) return;
    const r = isRemote ? await call("sftp_mkdir", t.sid, full(n.trim())) : await call("local_mkdir", full(n.trim()));
    r.ok ? load(p.cwd) : toast(r.error, true);
  }
  p.selectedEntries = selectedEntries;

  bUp.addEventListener("click", () => p.parent != null && load(p.parent));
  bHome.addEventListener("click", () => load(isRemote ? null : INFO.home));
  bRefresh.addEventListener("click", () => p.refresh());
  bNew.addEventListener("click", mkdir);
  bXfer.addEventListener("click", () => transfer(t, isRemote ? "down" : "up"));
  path.addEventListener("keydown", e => { if (e.key === "Enter") { load(path.value.trim() === "Este equipo" ? "" : path.value.trim()); list.focus(); } });
  list.addEventListener("mousedown", e => { t.lastPane = p; if (e.target === list) { p.sel.clear(); paintSel(); } });
  list.addEventListener("contextmenu", e => {
    if (e.target !== list && !e.target.classList.contains("empty")) return;
    contextMenu(e, [
      { label: "Nueva carpeta…", icon: "folder-plus", action: mkdir, disabled: p.cwd === "" },
      { label: "Actualizar", icon: "arrow-clockwise", action: () => p.refresh(), hint: "F5" },
      isRemote ? { label: "Subir archivos…", icon: "file-earmark-arrow-up", action: () => pickUpload(t, false) } : null,
      !isRemote && p.cwd ? { label: "Abrir en el Explorador", icon: "folder", action: () => call("local_open", p.cwd) } : null,
    ]);
  });
  list.addEventListener("keydown", e => {
    const v = p.view || [];
    const i = v.findIndex(x => x.name === p.anchor);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const n = v[Math.max(0, Math.min(v.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)))];
      if (n) { clickRow({ shiftKey: e.shiftKey, ctrlKey: false }, n.name); $(`.frow[data-name="${CSS.escape(n.name)}"]`, list)?.scrollIntoView({ block: "nearest" }); }
      e.preventDefault();
    } else if (e.key === "Enter") { const x = v[i]; if (x) openEntry(x); }
    else if (e.key === "Backspace") { if (p.parent != null) load(p.parent); e.preventDefault(); }
    else if (e.key === "Delete") removeSel();
    else if (e.key === "F2") { const x = v[i]; if (x) rename(x); }
    else if (e.key === "F5") { p.refresh(); e.preventDefault(); }
    else if (e.ctrlKey && e.key.toLowerCase() === "a") { p.sel = new Set(v.map(x => x.name)); paintSel(); e.preventDefault(); }
    else if (e.ctrlKey && e.key === "ArrowRight" && !isRemote) { transfer(t, "up"); e.preventDefault(); }
    else if (e.ctrlKey && e.key === "ArrowLeft" && isRemote) { transfer(t, "down"); e.preventDefault(); }
  });
  // arrastrar: entre paneles (filas) o desde el Explorador (archivos; Python da las rutas)
  root.addEventListener("dragover", e => {
    const types = e.dataTransfer.types;
    if (types.includes("Files")) { dropPane = { tab: t, side }; root.classList.add("drop"); e.preventDefault(); return; }
    if (types.includes("application/x-nexo-files")) { root.classList.add("drop"); e.preventDefault(); }
  });
  root.addEventListener("dragleave", e => { if (!root.contains(e.relatedTarget)) root.classList.remove("drop"); });
  root.addEventListener("drop", e => {
    root.classList.remove("drop");
    const raw = e.dataTransfer.getData("application/x-nexo-files");
    if (!raw) return;   // archivos del Explorador: llegan por el evento files_dropped
    e.preventDefault();
    const d = JSON.parse(raw);
    if (d.tab !== t.id || d.side === side) return;
    const row = e.target.closest(".frow[data-name]");
    const target = row && p.entries.find(x => x.name === row.dataset.name && x.dir);
    transfer(t, d.side === "local" ? "up" : "down", { names: d.names, src: d.dir, dest: target ? full(target.name) : p.cwd });
  });
  return p;
}

// ---------- transferencias ----------
async function transfer(t, direction, opt = {}) {
  const from = direction === "up" ? t.local : t.remote;
  const to = direction === "up" ? t.remote : t.local;
  const names = opt.names || [...from.sel];
  const src = opt.src !== undefined ? opt.src : from.cwd;
  const dest = opt.dest || to.cwd;
  if (!names.length) return toast(direction === "up" ? "Selecciona en «Este equipo» lo que quieres subir" : "Selecciona en el servidor lo que quieres bajar");
  if (direction === "down" && !dest) return toast("Abre una carpeta en «Este equipo» para bajar ahí", true);
  if (direction === "up" && src === "") return toast("Entra a una unidad o carpeta primero", true);
  const job = await call("sftp_progress", t.sid);
  if (job.ok && job.job.running) return toast("Espera a que termine la transferencia en curso", true);
  const c = await call("sftp_clash", t.sid, direction, names, dest);
  if (!c.ok) return toast(c.error, true);
  let skip = [];
  if (c.clash.length) {
    const shown = c.clash.slice(0, 5).join(", ") + (c.clash.length > 5 ? "…" : "");
    const choice = await choose(`${c.clash.length} elemento(s) ya existen en el destino`,
      `${shown}\n\nLas carpetas se combinan; los archivos con el mismo nombre se reemplazan.`,
      [{ label: "Omitir existentes", value: "skip" }, { label: "Reemplazar", value: "replace", primary: true }]);
    if (!choice) return;
    if (choice === "skip") skip = c.clash;
    if (skip.length === names.length) return toast("Nada que transferir");
  }
  const r = await call("sftp_transfer", t.sid, direction, names, src, dest, skip);
  if (!r.ok) return toast(r.error, true);
  t.xferDest = { pane: to, dir: dest };
  watchTransfer(t);
}
function watchTransfer(t) {
  const s = t.status;
  s.bar.hidden = false;
  s.cancel.hidden = false;
  clearInterval(t.poll);
  t.poll = setInterval(async () => {
    const r = await call("sftp_progress", t.sid);
    if (!r.ok) { clearInterval(t.poll); return; }
    const j = r.job;
    const pct = j.total ? Math.round((j.done / j.total) * 100) : 0;
    s.fill.style.width = pct + "%";
    if (j.running) {
      setStatus(t, `${j.direction === "up" ? "↑" : "↓"} ${j.file || "…"}  ${pct}%` + (j.n > 1 ? `  (${j.i}/${j.n})` : "") +
                   (j.total ? `  · ${humanSize(j.done)} de ${humanSize(j.total)}` : ""));
    } else finishTransfer(t, j);
  }, 250);
}
function finishTransfer(t, j) {
  clearInterval(t.poll);
  t.poll = null;
  t.status.bar.hidden = true;
  t.status.cancel.hidden = true;
  if (j.cancelled) { setStatus(t, "✖ Transferencia cancelada"); toast("Transferencia cancelada"); }
  else if (j.error) { setStatus(t, `✖ ${j.error}`, true); toast(j.error, true); }
  else {
    const msg = j.direction === "up" ? `↑ ${j.files} archivo(s) subidos a ${t.host.name}:${j.dest}` : `↓ ${j.files} archivo(s) bajados a ${j.dest}`;
    setStatus(t, msg);
    toast(msg);
  }
  t.remote.refresh();
  t.local.refresh();
}
EVENTS.sftp_done = ev => {
  for (const t of tabs.values()) if (t.sid === ev.sid && t.poll) finishTransfer(t, ev.job);
};
async function pickUpload(t, folder) {
  const r = await call("sftp_pick_upload", t.sid, folder);
  if (!r.ok || !r.paths.length) return;
  transfer(t, "up", { names: r.paths, src: null, dest: t.remote.cwd });
}
EVENTS.files_dropped = ev => {
  const d = dropPane;
  dropPane = null;
  $$(".fpane.drop").forEach(x => x.classList.remove("drop"));
  const t = d ? d.tab : tabs.get(activeTab);
  if (!t || t.kind !== "sftp" || !t.sid) return toast("Suelta los archivos sobre el panel del servidor de una pestaña SFTP");
  if (d && d.side === "local") return toast("Suelta los archivos en el panel del servidor para subirlos");
  transfer(t, "up", { names: ev.paths, src: null, dest: t.remote.cwd });
};

// ---------- edición remota ----------
EVENTS.edit_saved = ev => {
  for (const t of tabs.values()) if (t.sid === ev.sid) { setStatus(t, `↑ ${ev.name} guardado en ${t.host.name}`); t.remote.refresh(); }
  toast(`↑ ${ev.name} guardado en el servidor`);
};
EVENTS.edit_error = ev => toast(`No se pudo subir ${ev.name}: ${ev.error}`, true);
EVENTS.edit_conflict = async ev => {
  const c = await choose(`«${ev.name}» cambió en el servidor`,
    "Alguien lo modificó mientras lo editabas. Si lo sobrescribes, se pierden esos cambios.",
    [{ label: "Sobrescribir con mi versión", value: "force", danger: true }]);
  if (c === "force") call("sftp_force_upload", ev.sid, ev.local);
};
