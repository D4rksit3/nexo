/* Escritorio remoto dentro de Nexo (Windows) + pantalla completa (F11) y panel oculto (F9).
 *
 * El escritorio remoto es una ventana nativa (el control RDP de Windows) que Python pone
 * encima del área .rdp-screen de la pestaña. La página le avisa dónde está y cuándo debe
 * esconderse: al cambiar de pestaña o cuando hay un diálogo, la paleta o un menú, que si no
 * quedarían tapados por la ventana nativa. */

// ---------- abrir ----------
async function openRdp(h, password = null, acceptCert = null, reuse = null) {
  const r = await call("open_rdp", h.id, password, acceptCert);
  if (!r.ok) {
    if (r.error === "need_password") {
      const pw = await askPassword(h);
      return pw ? openRdp(h, pw, acceptCert, reuse) : null;
    }
    if (r.cert_changed) {
      const ok = await confirmDlg("El certificado del servidor cambió",
        `${h.name} presenta un certificado distinto al de la última vez.\n\n` +
        `Antes: ${r.previous}\nAhora: ${r.fingerprint}\n\n` +
        "Es normal si el servidor se reinstaló o renovó su certificado. Si no esperabas el cambio, " +
        "alguien podría estar interceptando la conexión.", "Confiar y conectar", true);
      return ok ? openRdp(h, password, r.fingerprint, reuse) : null;
    }
    if (reuse) rdpShowClosed(reuse, r.error);
    else toast(`${h.name}: ${r.error}`, true);
    return null;
  }
  h.last_used = Date.now() / 1000;
  renderHome();
  if (!r.embedded) { toast(`Abriendo escritorio remoto de ${h.name}…`); return null; }
  if (r.new_cert) toast(`${h.name}: certificado recordado; desde ahora Nexo confía en él`);
  const t = reuse || newRdpTab(h);
  t.sid = r.sid;
  t.placed = "";
  setState(t, "connecting");
  rdpMessage(t, "pc-display", `Conectando a ${h.name}…`);
  t.status.textContent = `${hostSub(h)} · conectando`;
  activate(t.id);
  rdpSync(true);
  return t;
}

function newRdpTab(h) {
  const t = addTab("rdp", h.name, null);
  t.host = h;
  const bar = el("div", "rdp-bar");
  t.status = el("span", "grow", hostSub(h));
  const bFull = el("button", "icon-btn");
  bFull.title = "Escritorio remoto a pantalla completa (sale con la barra de conexión de arriba)";
  bFull.append(icon("arrows-fullscreen"));
  bFull.addEventListener("click", () => t.sid && call("rdp_fullscreen", t.sid, true));
  const bOff = el("button", "icon-btn");
  bOff.title = "Desconectar";
  bOff.append(icon("power"));
  bOff.addEventListener("click", () => rdpDisconnect(t));
  bar.append(icon("windows"), t.status, bFull, bOff);
  t.screen = el("div", "rdp-screen");
  t.pane.append(bar, t.screen);
  t.onShow = () => rdpSync(true);
  t.focus = () => t.sid && api.rdp_focus(t.sid);
  t.onClose = () => { if (t.sid) api.rdp_close(t.sid); t.sid = null; rdpSync(true); };
  t.reconnect = () => openRdp(t.host, null, null, t);
  return t;
}

function rdpMessage(t, iconName, text, error = false, withRetry = false) {
  const box = el("div", "rdp-msg");
  box.append(icon(iconName));
  const p = el("p", error ? "err" : null, text);
  box.append(p);
  if (withRetry) box.append(btn("Reconectar", { cls: "primary", icon: "arrow-clockwise", onClick: () => t.reconnect() }));
  t.screen.replaceChildren(box);
}

function rdpShowClosed(t, error) {
  setState(t, "closed");
  t.sid = null;
  t.placed = "";
  t.status.textContent = `${hostSub(t.host)} · desconectado`;
  rdpMessage(t, error ? "exclamation-triangle" : "pc-display",
             error || "La sesión de escritorio remoto terminó.", !!error, true);
  rdpSync(true);
}

async function rdpDisconnect(t) {
  if (!t.sid) return;
  const sid = t.sid;
  t.sid = null;
  await api.rdp_close(sid);
  rdpShowClosed(t, "");
}

EVENTS.rdp_state = ev => {
  const t = [...tabs.values()].find(x => x.kind === "rdp" && x.sid === ev.sid);
  if (!t) return;
  if (ev.state === "connected") {
    setState(t, "connected");
    t.status.textContent = `${hostSub(t.host)} · conectado`;
    rdpMessage(t, "pc-display", "");
  } else if (ev.state === "closed") {
    rdpShowClosed(t, ev.error);
    if (ev.error && activeTab !== t.id) toast(`${ev.name}: ${ev.error}`, true);
  }
};

// ---------- ubicar la ventana nativa ----------
function overlayOpen() {
  return !!document.querySelector("dialog[open]") || !$("#palette").hidden || !$("#ctx").hidden || $("#main").hidden;
}
function rdpSync(force = false) {
  let any = false;
  const covered = overlayOpen();
  for (const t of tabs.values()) {
    if (t.kind !== "rdp" || !t.sid) continue;
    const visible = t.id === activeTab && !covered;
    if (visible) any = true;
    const r = t.screen.getBoundingClientRect();
    const key = visible ? `${r.left},${r.top},${r.width},${r.height}` : "hidden";
    if (!force && key === t.placed) continue;
    if (visible && (r.width < 4 || r.height < 4)) continue;  // aún sin dimensiones
    t.placed = key;
    call("rdp_place", t.sid, r.left, r.top, r.width, r.height, visible).then(res => {
      if (!res.ok && t.sid) rdpShowClosed(t, res.error);
    });
  }
  document.body.classList.toggle("rdp-on", any);
}
setInterval(() => { if (tabs.size) rdpSync(); }, 250);
window.addEventListener("resize", () => rdpSync());

// ---------- panel de hosts (F9) y pantalla completa (F11) ----------
function setSidebar(visible, save = true) {
  $("#side").hidden = !visible;
  $("#tool-side").classList.toggle("on", !visible);
  if (save) api.set_ui_pref("sidebar", visible);
  requestAnimationFrame(() => { const t = tabs.get(activeTab); if (t && t.onShow) t.onShow(); rdpSync(true); });
}
function toggleSidebar() { setSidebar($("#side").hidden); }

function toggleFocus() {
  const on = !document.body.classList.contains("focus");
  document.body.classList.toggle("focus", on);
  const b = $("#tool-focus");
  b.classList.toggle("on", on);
  b.title = on ? "Salir de pantalla completa (F11)" : "Pantalla completa: oculta los menús (F11)";
  b.firstElementChild.dataset.i = on ? "fullscreen-exit" : "arrows-fullscreen";
  paintIcons(b);
  api.window_fullscreen();
  setTimeout(() => { const t = tabs.get(activeTab); if (t && t.onShow) t.onShow(); rdpSync(true); }, 250);
}

document.addEventListener("keydown", e => {
  if ($("#main").hidden || document.querySelector("dialog[open]")) return;
  if (e.key === "F9") { e.preventDefault(); toggleSidebar(); }
  else if (e.key === "F11") { e.preventDefault(); toggleFocus(); }
});

function initRdpUi() {
  $("#tool-side").addEventListener("click", toggleSidebar);
  $("#tool-focus").addEventListener("click", toggleFocus);
  if (INFO.ui && INFO.ui.sidebar === false) setSidebar(false, false);
}
