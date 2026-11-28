"use strict";
/* Nexo para Windows — núcleo de la interfaz: estado, tema, bloqueo, pestañas, terminales,
   eventos de Python, paleta y arranque. Habla con Python por window.pywebview.api y con
   cada terminal por un WebSocket local (bytes en binario, control en JSON). */

let api = null;
let INFO = null;
let THEME = null;
let SETTINGS = { autolock_min: 15, lock_on_screen: true };
let HOSTS = [];
let GROUPS = [];
let ORGS = [];
let HOST_ICONS = {};
const tabs = new Map();          // tabId -> objeto de pestaña (terminal, sftp o db)
let activeTab = "home";
let tabSeq = 0;
const EVENTS = {};               // tipo de evento de Python -> función

/* Llama a la API; si la bóveda se bloqueó por detrás, vuelve a la pantalla de bloqueo. */
async function call(name, ...args) {
  let r;
  try {
    r = await api[name](...args);
  } catch (e) {
    r = { ok: false, error: String(e && e.message || e) };
  }
  if (r && r.locked && !$("#main").hidden) { await lockNow(); }
  return r || { ok: false, error: "Sin respuesta" };
}
window.nexoEvent = ev => { const f = EVENTS[ev.type]; if (f) f(ev); };

// ---------- tema ----------
function applyTheme(t) {
  THEME = t;
  const u = t.ui, r = document.documentElement.style;
  const map = { win: "win", side: "side", head: "head", rail: "rail", surf: "surf", surf2: "surf2", surf3: "surf3",
                line: "line", border2: "border2", fg: "fg", dim: "dim", acc: "acc", "acc-fg": "acc_fg", term: "term",
                sel: "sel" };
  for (const [css, key] of Object.entries(map)) r.setProperty(`--c-${css}`, u[key]);
  r.setProperty("--c-tbg", t.bg);  // fondo de las terminales (el único lugar donde manda el tema)
  for (const t of tabs.values()) if (t.term) t.term.options.theme = xtermTheme();
}
function xtermTheme() {
  const p = THEME.palette, names = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"];
  const th = { background: THEME.bg, foreground: THEME.fg, cursor: THEME.accent, cursorAccent: THEME.bg,
               selectionBackground: THEME.term_sel || THEME.ui.sel,
               selectionInactiveBackground: THEME.term_sel || THEME.ui.sel };
  names.forEach((n, i) => {
    th[n] = p[i];
    th["bright" + n[0].toUpperCase() + n.slice(1)] = p[i + 8];
  });
  return th;
}

// ---------- bloqueo ----------
function showLock() {
  const creating = !INFO.vault_exists;
  $("#main").hidden = true;
  $("#lock").hidden = false;
  $("#pw2").hidden = !creating;
  $("#lock-msg").textContent = creating
    ? "Crea tu contraseña maestra. Cifra todos tus hosts y llaves; no se puede recuperar."
    : "Bóveda bloqueada";
  $("#lock-btn").textContent = creating ? "Crear bóveda" : "Desbloquear";
  $("#lock-import").textContent = creating
    ? "¿Ya usas Nexo? Importa tu bóveda (copia exportada o la de Nexo para Linux)"
    : "Importar otra bóveda (reemplaza la de este equipo)";
  $("#lock-err").textContent = "";
  $("#pw1").value = $("#pw2").value = "";
  setTimeout(() => $("#pw1").focus(), 50);
}
async function submitLock(ev) {
  ev.preventDefault();
  const b = $("#lock-btn");
  b.disabled = true;
  $("#lock-err").textContent = "";
  try {
    let r;
    if (!INFO.vault_exists) {
      r = await api.create_vault($("#pw1").value, $("#pw2").value);
      if (r.ok) r = await api.unlock($("#pw1").value);
    } else {
      r = await api.unlock($("#pw1").value);
    }
    if (!r.ok) { $("#lock-err").textContent = r.error; $("#pw1").select(); return; }
    INFO = await api.info();
    $("#pw1").value = $("#pw2").value = "";
    await showMain();
  } finally {
    b.disabled = false;
  }
}
async function importVault() {
  if (INFO.vault_exists && !await confirmDlg("¿Reemplazar la bóveda de este equipo?",
      "La actual se guarda como copia de respaldo junto al archivo. La importada se abre con SU contraseña maestra.",
      "Elegir archivo…", false)) return;
  const r = await api.import_vault();
  if (r.cancelled) return;
  if (!r.ok) { $("#lock-err").textContent = r.error; return; }
  INFO = await api.info();
  showLock();
  toast("Bóveda importada: desbloquéala con su contraseña maestra");
}
async function lockNow() {
  for (const id of [...tabs.keys()]) closeTab(id, false);
  hideMenu();
  $$("dialog[open]").forEach(d => d.close());
  closePalette();
  await api.lock();
  INFO = await api.info();
  activate("home");
  showLock();
}

// autobloqueo por inactividad (dentro de Nexo) y al bloquear la sesión de Windows
let lastActivity = Date.now();
for (const evn of ["keydown", "mousedown", "mousemove", "wheel", "touchstart"])
  document.addEventListener(evn, () => (lastActivity = Date.now()), { passive: true, capture: true });
setInterval(() => {
  if ($("#main").hidden || !SETTINGS.autolock_min) return;
  if (Date.now() - lastActivity > SETTINGS.autolock_min * 60000) {
    lockNow().then(() => toast(`Bloqueado tras ${SETTINGS.autolock_min} min sin uso`));
  }
}, 10000);
EVENTS.screen_locked = () => { if (!$("#main").hidden && SETTINGS.lock_on_screen) lockNow(); };

// ---------- pestañas ----------
/* Una pestaña: {id, kind, title, pane, btn, dot, label, onShow(), onClose(), focus()} */
function addTab(kind, title, iconName) {
  const id = "t" + (++tabSeq);
  const b = el("button", "tab k-" + kind);
  b.dataset.tab = id;
  const dot = el("span", "dot connecting");
  const ic = iconName ? icon(iconName) : null;
  const label = el("span", "tab-label", title);
  const x = el("span", "x");
  x.title = "Cerrar (Ctrl+Shift+W)";
  x.append(icon("x-lg"));
  b.append(dot);
  if (ic) b.append(ic);
  b.append(label, x);
  b.addEventListener("click", () => activate(id));
  b.addEventListener("auxclick", e => { if (e.button === 1) closeTab(id); });
  b.addEventListener("contextmenu", e => contextMenu(e, [
    { label: "Cerrar", icon: "x-lg", action: () => closeTab(id) },
    { label: "Cerrar las demás", action: () => [...tabs.keys()].filter(k => k !== id).forEach(k => closeTab(k, false)) },
    tab.reconnect ? { label: "Reconectar", icon: "arrow-clockwise", action: () => tab.reconnect() } : null,
  ]));
  x.addEventListener("click", e => { e.stopPropagation(); closeTab(id); });
  $("#tabs").append(b);
  const pane = el("div", "pane " + kind);
  pane.dataset.tab = id;
  $("#panes").append(pane);
  const tab = { id, kind, title, pane, btn: b, dot, label, state: "connecting" };
  tabs.set(id, tab);
  return tab;
}
function setState(t, state) {
  t.state = state;
  t.dot.className = "dot " + state;
}
function activate(id) {
  activeTab = id;
  $$(".tab").forEach(b => b.classList.toggle("active", b.dataset.tab === id));
  $$(".pane").forEach(p => p.classList.toggle("active", p.dataset.tab === id));
  const t = tabs.get(id);
  if (t) {
    t.btn.scrollIntoView({ block: "nearest", inline: "nearest" });
    requestAnimationFrame(() => { t.onShow && t.onShow(); t.focus && t.focus(); });
  }
}
function closeTab(id, focusOther = true) {
  const t = tabs.get(id);
  if (!t) return;
  try { t.onClose && t.onClose(); } catch (_) { /* nada */ }
  t.pane.remove();
  t.btn.remove();
  tabs.delete(id);
  if (focusOther && activeTab === id) {
    const ids = [...tabs.keys()];
    activate(ids.length ? ids[ids.length - 1] : "home");
  } else if (activeTab === id) activate("home");
}

// ---------- terminales ----------
function newTerminalTab(title, kind) {
  const t = addTab(kind === "local" ? "term" : "term", title, kind === "local" ? "terminal" : null);
  t.termKind = kind;
  const term = new Terminal({
    fontFamily: getComputedStyle(document.body).getPropertyValue("--font-mono"),
    fontSize: termFontSize(), lineHeight: 1.1, cursorBlink: true, scrollback: 20000, theme: xtermTheme(),
    allowProposedApi: false,
    windowsPty: INFO.platform === "windows" && kind === "local" ? { backend: "conpty" } : undefined,
  });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.loadAddon(new WebLinksAddon.WebLinksAddon((e, uri) => api.open_url(uri)));
  term.open(t.pane);
  Object.assign(t, { term, fit, ws: null, sid: null });
  t.onShow = () => fitTab(t);
  t.focus = () => term.focus();
  t.onClose = () => {
    if (t.ws) { t.ws.onclose = null; t.ws.close(); }
    if (t.sid) api.close_session(t.sid);
    term.dispose();
  };
  t.reconnect = () => reconnect(t);
  wireTerminal(t);
  activate(t.id);
  return t;
}
// ---------- tamaño de letra de las terminales (Ctrl + / Ctrl - / Ctrl 0 / Ctrl+rueda) ----------
const TERM_FONT_BASE = 13;
const ZOOM_KEYS = { "+": 1, "=": 1, "-": -1, "_": -1, "0": 0 };
let TERM_ZOOM = 0;
function termFontSize() { return Math.max(7, Math.min(40, TERM_FONT_BASE + TERM_ZOOM)); }
function termZoom(delta) {
  const z = delta === 0 ? 0 : Math.max(7 - TERM_FONT_BASE, Math.min(40 - TERM_FONT_BASE, TERM_ZOOM + delta));
  if (z === TERM_ZOOM && delta !== 0) return;
  TERM_ZOOM = z;
  for (const t of tabs.values()) if (t.term) { t.term.options.fontSize = termFontSize(); if (t.id === activeTab) fitTab(t); }
  api.set_ui_pref("term_zoom", z);
  toast(`Letra de las terminales: ${termFontSize()} px${z ? "" : " (normal)"}`);
}
// el navegador interno no debe hacer zoom a toda la página: solo cambian las terminales
document.addEventListener("keydown", e => {
  if (e.ctrlKey && !e.altKey && ZOOM_KEYS[e.key] !== undefined && !isTyping(e)) {
    e.preventDefault();
    const t = tabs.get(activeTab);
    if (t && t.term) termZoom(ZOOM_KEYS[e.key]);
  }
}, true);
document.addEventListener("wheel", e => {
  if (!e.ctrlKey) return;
  e.preventDefault();
  const t = tabs.get(activeTab);
  if (t && t.term && t.pane.contains(e.target) && e.deltaY) termZoom(e.deltaY < 0 ? 1 : -1);
}, { passive: false });

function fitTab(t) {
  try { t.fit.fit(); } catch (_) { /* pestaña oculta */ }
}
function attach(t, r) {
  t.sid = r.sid;
  const ws = new WebSocket(r.ws);
  ws.binaryType = "arraybuffer";
  t.ws = ws;
  ws.onopen = () => sendResize(t);
  ws.onmessage = ev => {
    if (typeof ev.data === "string") {
      const m = JSON.parse(ev.data);
      if (m.t === "status") setState(t, m.state);
      return;
    }
    t.term.write(new Uint8Array(ev.data));
  };
  ws.onclose = () => { if (t.state !== "closed") setState(t, "closed"); };
}
function sendResize(t) {
  if (t.ws && t.ws.readyState === 1) t.ws.send(JSON.stringify({ t: "resize", cols: t.term.cols, rows: t.term.rows }));
}
const enc = new TextEncoder();
function wireTerminal(t) {
  t.term.onData(d => {
    if (t.state === "closed") {
      if (d === "\r") reconnect(t);
      return;
    }
    if (t.ws && t.ws.readyState === 1) t.ws.send(enc.encode(d));
  });
  t.term.onBinary(d => {
    if (t.ws && t.ws.readyState === 1) t.ws.send(Uint8Array.from(d, c => c.charCodeAt(0)));
  });
  t.term.onResize(() => sendResize(t));
  t.term.attachCustomKeyEventHandler(e => {
    if (e.type !== "keydown") return true;
    const k = e.key.toLowerCase();
    if (e.ctrlKey && e.shiftKey && k === "c") { copySelection(t); return false; }
    if (e.ctrlKey && e.shiftKey && k === "v") { paste(t); return false; }
    if (e.ctrlKey && e.shiftKey && ["t", "w", "l", "f"].includes(k)) return false;   // atajos de la app
    if (e.ctrlKey && !e.shiftKey && k === "k") return false;
    if (e.ctrlKey && e.key === "Tab") return false;
    if (e.key === "F9" || e.key === "F11") return false;                               // panel y pantalla completa
    if (e.ctrlKey && !e.altKey && ZOOM_KEYS[e.key] !== undefined) {                    // letra más grande/chica
      e.preventDefault();
      termZoom(ZOOM_KEYS[e.key]);
      return false;
    }
    return true;
  });
  // Clic derecho como en Windows Terminal / PuTTY: copia si hay selección, si no pega.
  t.pane.addEventListener("contextmenu", e => {
    e.preventDefault();
    if (t.term.hasSelection()) { copySelection(t); t.term.clearSelection(); } else paste(t);
  });
  new ResizeObserver(() => { if (t.pane.classList.contains("active")) fitTab(t); }).observe(t.pane);
}
async function copyText(text, note = "Copiado") {
  try { await navigator.clipboard.writeText(text); }
  catch (_) { await api.clipboard_set(text); }
  if (note) toast(note);
}
async function copySelection(t) {
  const text = t.term.getSelection();
  if (text) copyText(text);
}
async function paste(t) {
  let text = null;
  try { text = await navigator.clipboard.readText(); }
  catch (_) { const r = await api.clipboard_get(); text = r.ok ? r.text : null; }
  if (text) t.term.paste(text);
}
async function connect(h, password = null) {
  if (h.needs_password && password == null) {
    password = await askPassword(h);
    if (password == null) return;
  }
  const t = newTerminalTab(h.name, "ssh");
  t.host = h;
  fitTab(t);
  const r = await call("open_ssh", h.id, password, t.term.cols, t.term.rows);
  if (!r.ok) {
    t.term.write(`\r\n\x1b[31m${r.error}\x1b[0m\r\n`);
    setState(t, "closed");
    return;
  }
  attach(t, r);
  h.last_used = Date.now() / 1000;
  renderHome();
}
async function quickConnect(ev) {
  ev.preventDefault();
  const target = $("#quick").value.trim();
  if (!target) return;
  const pw = await ask(`Contraseña de ${target}`, "Contraseña", "", { secret: true, ok: "Conectar",
                       sub: "Conexión rápida: no se guarda nada en la bóveda." });
  if (pw == null) return;
  const t = newTerminalTab(target, "ssh");
  fitTab(t);
  const r = await call("open_quick", target, pw, t.term.cols, t.term.rows);
  if (!r.ok) { t.term.write(`\r\n\x1b[31m${r.error}\x1b[0m\r\n`); setState(t, "closed"); return; }
  attach(t, r);
  $("#quick").value = "";
}
async function openLocal() {
  const t = newTerminalTab(INFO.local_shell, "local");
  fitTab(t);
  const r = await call("open_local", t.term.cols, t.term.rows);
  if (!r.ok) { t.term.write(`\r\n\x1b[31m${r.error}\x1b[0m\r\n`); setState(t, "closed"); return; }
  attach(t, r);
}
async function reconnect(t) {
  if (!t.sid) return;
  if (t.ws) { t.ws.onclose = null; t.ws.close(); }
  setState(t, "connecting");
  t.term.write("\r\n");
  const r = await call("reopen", t.sid, t.term.cols, t.term.rows);
  if (!r.ok) { setState(t, "closed"); return; }
  attach(t, r);
}
function askPassword(h) {
  return ask(`Contraseña de ${h.name}`, "Contraseña", "", { secret: true, ok: "Conectar", sub: hostSub(h),
             placeholder: "no se guarda" });
}

// ---------- paleta (Ctrl+K) ----------
let paletteItems = [];
let paletteIndex = 0;
function openPalette() {
  if ($("#main").hidden) return;
  $("#palette").hidden = false;
  if (typeof rdpSync === "function") rdpSync(true);
  $("#palette-input").value = "";
  renderPalette();
  $("#palette-input").focus();
}
function closePalette() { $("#palette").hidden = true; if (typeof rdpSync === "function") rdpSync(true); }
function paletteSource() {
  const acts = [
    { label: "Terminal local", sub: INFO.local_shell, icon: "terminal", run: openLocal },
    { label: "Nuevo host", icon: "plus-lg", run: () => editHost(null) },
    { label: "Llaves SSH", icon: "key", run: () => showPanel("keys") },
    { label: "Túneles", icon: "arrow-left-right", run: () => showPanel("tunnels") },
    { label: "Organizaciones", icon: "building", run: () => showPanel("orgs") },
    { label: "Ajustes y temas", icon: "gear", run: openSettings },
    { label: "Importar ~/.ssh/config", icon: "box-arrow-in-right", run: importSshConfig },
    { label: "Agrandar letra de las terminales", sub: "Ctrl +", icon: "zoom-in", run: () => termZoom(1) },
    { label: "Achicar letra de las terminales", sub: "Ctrl -", icon: "zoom-out", run: () => termZoom(-1) },
    { label: "Letra de las terminales: tamaño normal", sub: "Ctrl 0", icon: "type", run: () => termZoom(0) },
    { label: "Ocultar / mostrar panel de hosts", sub: "F9", icon: "layout-sidebar", run: toggleSidebar },
    { label: "Pantalla completa (sin menús)", sub: "F11", icon: "arrows-fullscreen", run: toggleFocus },
    { label: "Bloquear", icon: "lock", run: lockNow },
  ];
  const hostItems = [];
  for (const h of HOSTS) {
    hostItems.push({ label: h.name, sub: hostSub(h), host: h, run: () => openHost(h) });
    if (h.protocol === "ssh") hostItems.push({ label: `SFTP · ${h.name}`, sub: hostSub(h), icon: "folder2-open", run: () => openHost(h, "sftp") });
  }
  hostItems.sort((a, b) => (b.host?.last_used || 0) - (a.host?.last_used || 0));
  return [...hostItems, ...acts];
}
function renderPalette() {
  const q = $("#palette-input").value.trim().toLowerCase();
  const words = q.split(/\s+/).filter(Boolean);
  paletteItems = paletteSource().filter(it => words.every(w => (it.label + " " + (it.sub || "")).toLowerCase().includes(w))).slice(0, 40);
  paletteIndex = 0;
  const list = $("#palette-list");
  list.replaceChildren();
  paletteItems.forEach((it, i) => {
    const row = el("div", "palette-item" + (i === 0 ? " active" : ""));
    row.append(it.host ? hostIcon(it.host) : icon(it.icon || "play-fill"), el("span", "grow", it.label));
    if (it.sub) row.append(el("span", "palette-sub", it.sub));
    row.addEventListener("mousedown", e => { e.preventDefault(); closePalette(); it.run(); });
    list.append(row);
  });
  if (!paletteItems.length) list.append(el("div", "empty", "Nada coincide"));
}
function movePalette(d) {
  const rows = $$(".palette-item");
  if (!rows.length) return;
  rows[paletteIndex]?.classList.remove("active");
  paletteIndex = (paletteIndex + d + rows.length) % rows.length;
  rows[paletteIndex].classList.add("active");
  rows[paletteIndex].scrollIntoView({ block: "nearest" });
}

// ---------- atajos globales ----------
document.addEventListener("keydown", e => {
  if ($("#main").hidden) return;
  if (!$("#palette").hidden) {
    if (e.key === "Escape") { closePalette(); e.preventDefault(); }
    else if (e.key === "ArrowDown") { movePalette(1); e.preventDefault(); }
    else if (e.key === "ArrowUp") { movePalette(-1); e.preventDefault(); }
    else if (e.key === "Enter") { const it = paletteItems[paletteIndex]; closePalette(); if (it) it.run(); e.preventDefault(); }
    return;
  }
  if (document.querySelector("dialog[open]")) return;
  const k = e.key.toLowerCase();
  if (e.ctrlKey && !e.shiftKey && k === "k") { e.preventDefault(); openPalette(); }
  else if (e.ctrlKey && e.shiftKey && k === "t") { e.preventDefault(); openLocal(); }
  else if (e.ctrlKey && e.shiftKey && k === "w") { e.preventDefault(); if (activeTab !== "home") closeTab(activeTab); }
  else if (e.ctrlKey && e.shiftKey && k === "l") { e.preventDefault(); lockNow(); }
  else if (e.ctrlKey && !e.shiftKey && k === "n" && !isTyping(e)) { e.preventDefault(); editHost(null); }
  else if (e.ctrlKey && k === "f" && (e.shiftKey || activeTab === "home")) { e.preventDefault(); showPanel("hosts"); $("#filter").focus(); }
  else if (e.ctrlKey && e.key === "Tab") {
    e.preventDefault();
    const ids = ["home", ...tabs.keys()];
    const i = ids.indexOf(activeTab);
    activate(ids[(i + (e.shiftKey ? -1 : 1) + ids.length) % ids.length]);
  }
});
function isTyping(e) {
  const t = e.target;
  return t && (t.tagName === "TEXTAREA" || (t.tagName === "INPUT" && t.type !== "checkbox"));
}

// ---------- arranque ----------
async function showMain() {
  $("#lock").hidden = true;
  $("#main").hidden = false;
  SETTINGS = INFO.settings || SETTINGS;
  TERM_ZOOM = (INFO.ui && INFO.ui.term_zoom) || 0;
  lastActivity = Date.now();
  $("#home-local-name").textContent = `Terminal local · ${INFO.local_shell}`;
  $("#home-version").textContent = `Nexo ${INFO.version} para ${INFO.platform === "windows" ? "Windows" : "Linux"}`;
  await loadHosts();
  if (ORGS.length) call("org_refresh").then(r => { (r.messages || []).forEach(m => toast(m, true)); loadHosts(); });
  $("#filter").focus();
}
async function boot() {
  api = window.pywebview.api;
  paintIcons();
  try { HOST_ICONS = await (await fetch("host-icons.json")).json(); } catch (_) { HOST_ICONS = {}; }
  INFO = await api.info();
  applyTheme(INFO.theme);
  $("#lock-form").addEventListener("submit", submitLock);
  $("#lock-import").addEventListener("click", importVault);
  $("#rail-local").addEventListener("click", openLocal);
  $("#rail-palette").addEventListener("click", openPalette);
  $("#rail-settings").addEventListener("click", openSettings);
  $("#home-local").addEventListener("click", openLocal);
  $("#home-new").addEventListener("click", () => editHost(null));
  $("#home-import").addEventListener("click", importSshConfig);
  $("#quick-form").addEventListener("submit", quickConnect);
  $("#rail-lock").addEventListener("click", lockNow);
  $$(".rail-btn[data-panel]").forEach(b => b.addEventListener("click", () => showPanel(b.dataset.panel, true)));
  $(".tab[data-tab=home]").addEventListener("click", () => activate("home"));
  $("#palette").addEventListener("mousedown", e => { if (e.target.id === "palette") closePalette(); });
  $("#palette-input").addEventListener("input", renderPalette);
  initHosts();
  initPanels();
  initRdpUi();
  // soltar archivos: el navegador no debe abrirlos; Python recibe las rutas (evento files_dropped)
  document.addEventListener("dragover", e => e.preventDefault());
  document.addEventListener("drop", e => e.preventDefault());
  if (INFO.unlocked) await showMain(); else showLock();
}
window.addEventListener("pywebviewready", boot);
