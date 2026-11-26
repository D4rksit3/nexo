"use strict";
/* Nexo para Windows — interfaz. Habla con Python por window.pywebview.api y con
   cada terminal por un WebSocket local (bytes en binario, control en JSON). */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
let api = null;
let INFO = null;
let THEME = null;
let HOSTS = [];
let GROUPS = [];
let HOST_ICONS = {};
const collapsed = new Set();
const tabs = new Map();          // tabId -> {kind, title, sid, ws, term, fit, pane, btn, host, state}
let activeTab = "home";
let tabSeq = 0;

// ---------- utilidades ----------
function icon(name) {
  const i = document.createElement("i");
  i.className = "ic";
  i.style.setProperty("--src", `url("icons/bi-${name}.svg")`);
  return i;
}
function paintIcons(root = document) {
  $$(".ic[data-i]", root).forEach(i => i.style.setProperty("--src", `url("icons/bi-${i.dataset.i}.svg")`));
}
let toastTimer = null;
function toast(text, error = false) {
  const t = $("#toast");
  t.textContent = text;
  t.classList.toggle("error", error);
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 3200);
}
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

// ---------- tema ----------
function applyTheme(t) {
  THEME = t;
  const u = t.ui, r = document.documentElement.style;
  const map = { win: "win", side: "side", head: "head", rail: "rail", surf: "surf", surf2: "surf2",
                line: "line", border2: "border2", fg: "fg", dim: "dim", acc: "acc", "acc-fg": "acc_fg", term: "term" };
  for (const [css, key] of Object.entries(map)) r.setProperty(`--c-${css}`, u[key]);
}
function xtermTheme() {
  const p = THEME.palette, names = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"];
  const th = { background: THEME.bg, foreground: THEME.fg, cursor: THEME.accent, cursorAccent: THEME.bg,
               selectionBackground: THEME.ui.sel, selectionInactiveBackground: THEME.ui.sel };
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
  $("#lock-err").textContent = "";
  $("#pw1").value = $("#pw2").value = "";
  setTimeout(() => $("#pw1").focus(), 50);
}
async function submitLock(ev) {
  ev.preventDefault();
  const btn = $("#lock-btn");
  btn.disabled = true;
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
    btn.disabled = false;
  }
}
async function lockNow() {
  for (const id of [...tabs.keys()]) closeTab(id, false);
  await api.lock();
  INFO = await api.info();
  showLock();
}

// ---------- hosts ----------
async function loadHosts() {
  const r = await api.hosts();
  if (!r.ok) return;
  HOSTS = r.hosts;
  GROUPS = r.groups;
  GROUPS.forEach(g => g.collapsed && collapsed.add(g.name));
  renderHosts();
  renderHome();
}
function hostIcon(h) {
  const def = HOST_ICONS[h.icon] || HOST_ICONS.server || ["hdd-rack", "", null];
  const i = icon(def[0]);
  if (def[2]) i.style.color = def[2];
  return i;
}
function hostSub(h) {
  const port = h.port && h.port !== 22 ? `:${h.port}` : "";
  return `${h.user ? h.user + "@" : ""}${h.host}${port}${h.jump ? "  ↳ " + h.jump : ""}`;
}
function hostRow(h) {
  const row = el("div", "host");
  row.dataset.id = h.id;
  row.tabIndex = 0;
  if (h.protocol !== "ssh") {
    row.classList.add("disabled");
    row.title = `${h.protocol.toUpperCase()}: llega en la fase 3`;
  }
  row.append(hostIcon(h));
  const txt = el("div", "txt");
  txt.append(el("div", "name", h.name), el("div", "sub", h.protocol === "ssh" ? hostSub(h) : h.protocol.toUpperCase() + " · " + h.host));
  row.append(txt);
  if (h.protocol === "ssh") {
    const go = el("button", "go");
    go.title = "Conectar";
    go.append(icon("play-fill"));
    go.addEventListener("click", e => { e.stopPropagation(); connect(h); });
    row.append(go);
    row.addEventListener("dblclick", () => connect(h));
    row.addEventListener("keydown", e => { if (e.key === "Enter") connect(h); });
  }
  row.addEventListener("click", () => {
    $$(".host.selected").forEach(x => x.classList.remove("selected"));
    row.classList.add("selected");
  });
  return row;
}
function renderHosts() {
  const list = $("#host-list");
  list.replaceChildren();
  const q = $("#filter").value.trim().toLowerCase();
  const match = h => !q || [h.name, h.host, h.user, h.group].some(x => (x || "").toLowerCase().includes(q));
  const shown = HOSTS.filter(match);
  if (!HOSTS.length) {
    list.append(el("div", "empty", "Sin hosts todavía. Por ahora se crean en Nexo para Linux; la bóveda es la misma."));
    return;
  }
  if (!shown.length) { list.append(el("div", "empty", "Nada coincide con el filtro")); return; }
  const names = [...GROUPS.map(g => g.name), ""];
  for (const g of names) {
    const items = shown.filter(h => (h.group || "") === g).sort((a, b) => a.name.localeCompare(b.name));
    if (!items.length) continue;
    const open = q || !collapsed.has(g);
    const head = el("div", "group-head");
    head.append(icon(open ? "chevron-down" : "chevron-right"), el("span", null, g || "Sin grupo"),
                el("span", "count", String(items.length)));
    head.addEventListener("click", () => {
      collapsed.has(g) ? collapsed.delete(g) : collapsed.add(g);
      renderHosts();
    });
    list.append(head);
    if (open) items.forEach(h => list.append(hostRow(h)));
  }
}
function renderHome() {
  const n = HOSTS.length;
  $("#home-stats").textContent = `${n} host${n === 1 ? "" : "s"} · bóveda cifrada AES-256`;
  const rec = $("#recent");
  rec.replaceChildren();
  const recent = HOSTS.filter(h => h.last_used && h.protocol === "ssh").sort((a, b) => b.last_used - a.last_used).slice(0, 6);
  if (!recent.length) rec.append(el("p", "muted", "Aún no te has conectado a ningún host."));
  recent.forEach(h => rec.append(hostRow(h)));
}

// ---------- pestañas ----------
function activate(id) {
  activeTab = id;
  $$(".tab").forEach(b => b.classList.toggle("active", b.dataset.tab === id));
  $$(".pane").forEach(p => p.classList.toggle("active", p.dataset.tab === id));
  const t = tabs.get(id);
  if (t) requestAnimationFrame(() => { fitTab(t); t.term.focus(); });
}
function newTab(title, kind) {
  const id = "t" + (++tabSeq);
  const btn = el("button", "tab");
  btn.dataset.tab = id;
  const dot = el("span", "dot connecting");
  const label = el("span", null, title);
  const x = el("span", "x");
  x.title = "Cerrar (Ctrl+Shift+W)";
  x.append(icon("x-lg"));
  btn.append(dot, label, x);
  btn.addEventListener("click", () => activate(id));
  btn.addEventListener("auxclick", e => { if (e.button === 1) closeTab(id); });
  x.addEventListener("click", e => { e.stopPropagation(); closeTab(id); });
  $("#tabs").append(btn);

  const pane = el("div", "pane term");
  pane.dataset.tab = id;
  $("#panes").append(pane);
  const term = new Terminal({
    fontFamily: getComputedStyle(document.body).getPropertyValue("--font-mono"),
    fontSize: 13, lineHeight: 1.1, cursorBlink: true, scrollback: 20000, theme: xtermTheme(),
    allowProposedApi: false, macOptionIsMeta: true,
    windowsPty: INFO.platform === "windows" && kind === "local" ? { backend: "conpty" } : undefined,
  });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.loadAddon(new WebLinksAddon.WebLinksAddon());
  term.open(pane);
  const tab = { id, kind, title, term, fit, pane, btn, dot, label, ws: null, sid: null, state: "connecting" };
  tabs.set(id, tab);
  wireTerminal(tab);
  activate(id);
  return tab;
}
function fitTab(t) {
  try { t.fit.fit(); } catch (_) { /* pestaña oculta */ }
}
function setState(t, state) {
  t.state = state;
  t.dot.className = "dot " + state;
}
function closeTab(id, focusOther = true) {
  const t = tabs.get(id);
  if (!t) return;
  if (t.ws) { t.ws.onclose = null; t.ws.close(); }
  if (t.sid) api.close_session(t.sid);
  t.term.dispose();
  t.pane.remove();
  t.btn.remove();
  tabs.delete(id);
  if (focusOther && activeTab === id) {
    const ids = [...tabs.keys()];
    activate(ids.length ? ids[ids.length - 1] : "home");
  }
}

// ---------- terminal <-> sesión ----------
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
    if (e.ctrlKey && e.key === "Tab") return false;
    return true;
  });
  // Clic derecho como en Windows Terminal / PuTTY: copia si hay selección, si no pega.
  t.pane.addEventListener("contextmenu", e => {
    e.preventDefault();
    if (t.term.hasSelection()) { copySelection(t); t.term.clearSelection(); } else paste(t);
  });
  new ResizeObserver(() => { if (t.pane.classList.contains("active")) fitTab(t); }).observe(t.pane);
}
async function copySelection(t) {
  const text = t.term.getSelection();
  if (!text) return;
  try { await navigator.clipboard.writeText(text); }
  catch (_) { await api.clipboard_set(text); }
  toast("Copiado");
}
async function paste(t) {
  let text = null;
  try { text = await navigator.clipboard.readText(); }
  catch (_) { const r = await api.clipboard_get(); text = r.ok ? r.text : null; }
  if (text) t.term.paste(text);
}

// ---------- abrir sesiones ----------
async function connect(h, password = null) {
  if (h.needs_password && password == null) {
    password = await askPassword(h);
    if (password == null) return;
  }
  const t = newTab(h.name, "ssh");
  t.host = h;
  t.password = password;
  fitTab(t);
  const r = await api.open_ssh(h.id, password, t.term.cols, t.term.rows);
  if (!r.ok) {
    t.term.write(`\r\n\x1b[31m${r.error}\x1b[0m\r\n`);
    setState(t, "closed");
    return;
  }
  attach(t, r);
  h.last_used = Date.now() / 1000;
  renderHome();
}
async function openLocal() {
  const t = newTab(INFO.local_shell, "local");
  fitTab(t);
  const r = await api.open_local(t.term.cols, t.term.rows);
  if (!r.ok) { t.term.write(`\r\n\x1b[31m${r.error}\x1b[0m\r\n`); setState(t, "closed"); return; }
  attach(t, r);
}
async function reconnect(t) {
  if (!t.sid) return;
  if (t.ws) { t.ws.onclose = null; t.ws.close(); }
  setState(t, "connecting");
  t.term.write("\r\n");
  const r = await api.reopen(t.sid, t.term.cols, t.term.rows);
  if (!r.ok) { setState(t, "closed"); return; }
  attach(t, r);
}
function askPassword(h) {
  return new Promise(resolve => {
    const d = $("#pw-dialog");
    $("#pw-title").textContent = `Contraseña de ${h.name}`;
    $("#pw-sub").textContent = hostSub(h);
    $("#pw-host").value = "";
    d.onclose = () => {
      const v = $("#pw-host").value;
      $("#pw-host").value = "";
      resolve(d.returnValue === "ok" && v ? v : null);
    };
    d.showModal();
    $("#pw-host").focus();
  });
}

// ---------- atajos globales ----------
document.addEventListener("keydown", e => {
  if ($("#main").hidden) return;
  const k = e.key.toLowerCase();
  if (e.ctrlKey && e.shiftKey && k === "t") { e.preventDefault(); openLocal(); }
  else if (e.ctrlKey && e.shiftKey && k === "w") { e.preventDefault(); if (activeTab !== "home") closeTab(activeTab); }
  else if (e.ctrlKey && e.shiftKey && k === "l") { e.preventDefault(); lockNow(); }
  else if (e.ctrlKey && !e.shiftKey && k === "f" && !tabs.has(activeTab)) { e.preventDefault(); $("#filter").focus(); }
  else if (e.ctrlKey && e.shiftKey && k === "f") { e.preventDefault(); $("#filter").focus(); }
  else if (e.ctrlKey && e.key === "Tab") {
    e.preventDefault();
    const ids = ["home", ...tabs.keys()];
    const i = ids.indexOf(activeTab);
    activate(ids[(i + (e.shiftKey ? -1 : 1) + ids.length) % ids.length]);
  }
});

// ---------- arranque ----------
async function showMain() {
  $("#lock").hidden = true;
  $("#main").hidden = false;
  $("#home-local-name").textContent = `Terminal local · ${INFO.local_shell}`;
  $("#home-version").textContent = `Nexo ${INFO.version} para ${INFO.platform === "windows" ? "Windows" : "Linux"} · versión de prueba (fase 1)`;
  await loadHosts();
  $("#filter").focus();
}
async function boot() {
  api = window.pywebview.api;
  paintIcons();
  try { HOST_ICONS = await (await fetch("host-icons.json")).json(); } catch (_) { HOST_ICONS = {}; }
  INFO = await api.info();
  applyTheme(INFO.theme);
  $("#lock-form").addEventListener("submit", submitLock);
  $("#rail-local").addEventListener("click", openLocal);
  $("#home-local").addEventListener("click", openLocal);
  $("#rail-lock").addEventListener("click", lockNow);
  $("#rail-hosts").addEventListener("click", () => $("#side").hidden = !$("#side").hidden);
  $("#filter").addEventListener("input", renderHosts);
  $("#filter").addEventListener("keydown", e => {
    if (e.key === "Enter") {
      const first = $("#host-list .host:not(.disabled)");
      if (first) connect(HOSTS.find(h => h.id === first.dataset.id));
    }
  });
  $(".tab[data-tab=home]").addEventListener("click", () => activate("home"));
  if (INFO.unlocked) await showMain(); else showLock();
}
window.addEventListener("pywebviewready", boot);
