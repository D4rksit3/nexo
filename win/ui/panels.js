"use strict";
/* Paneles laterales (llaves, túneles, organizaciones) y Ajustes. */

let currentPanel = "hosts";
function showPanel(name, toggle = false) {
  const side = $("#side");
  if (toggle && name === currentPanel && !side.hidden) return setSidebar(false);
  if (side.hidden) setSidebar(true);
  currentPanel = name;
  $$(".rail-btn[data-panel]").forEach(b => b.classList.toggle("active", b.dataset.panel === name));
  $$(".side-panel").forEach(p => (p.hidden = p.dataset.panel !== name));
  if (name === "keys") loadKeys();
  if (name === "tunnels") loadTunnels();
  if (name === "orgs") renderOrgs();
}

// ---------- llaves ----------
async function loadKeys() {
  const r = await call("keys");
  if (!r.ok) return;
  const list = $("#key-list");
  list.replaceChildren();
  if (!r.keys.length) {
    const e = el("div", "empty");
    e.append(el("p", null, "Sin llaves. Genera una nueva o importa la que ya usas (id_ed25519, id_rsa…)."),
             btn("Generar llave", { cls: "primary small", icon: "plus-lg", onClick: generateKey }),
             btn("Importar archivo", { cls: "small", onClick: importKeyFile }));
    list.append(e);
    return;
  }
  for (const k of r.keys) {
    const row = el("div", "host key-row");
    row.tabIndex = 0;
    row.append(icon("key", "#f2c66d"));
    const txt = el("div", "txt");
    txt.append(el("div", "name", k.name), el("div", "sub", `${k.kind} · ${k.fingerprint.slice(0, 22)}…`));
    if (k.used_by.length) txt.append(el("div", "sub used", `en ${k.used_by.length} host(s): ${k.used_by.slice(0, 3).join(", ")}${k.used_by.length > 3 ? "…" : ""}`));
    row.append(txt);
    const cp = el("button", "go");
    cp.title = "Copiar llave pública";
    cp.append(icon("copy"));
    cp.addEventListener("click", e => { e.stopPropagation(); copyText(k.public, "Llave pública copiada"); });
    row.append(cp);
    const menu = [
      { label: "Copiar llave pública", icon: "copy", action: () => copyText(k.public, "Llave pública copiada") },
      { label: "Ver llave pública", icon: "eye", action: () => showPublic(k) },
      { label: "Guardar .pub…", icon: "download", action: async () => { const x = await call("save_public_key", k.id); if (x.ok) toast("Guardada en " + x.path); } },
      { label: "Renombrar…", icon: "pencil", action: async () => {
        const n = await ask("Renombrar llave", "Nombre", k.name);
        if (n != null) { await call("rename_key", k.id, n); loadKeys(); }
      } },
      "-",
      { label: "Eliminar", icon: "trash3", danger: true, action: async () => {
        const extra = k.used_by.length ? ` La usan: ${k.used_by.join(", ")}; esos hosts quedarán sin llave.` : "";
        if (!await confirmDlg(`¿Eliminar la llave «${k.name}»?`, "Se borra de la bóveda." + extra)) return;
        await call("delete_key", k.id); loadKeys(); loadHosts();
      } },
    ];
    row.addEventListener("contextmenu", e => contextMenu(e, menu));
    row.addEventListener("dblclick", () => showPublic(k));
    list.append(row);
  }
}
function showPublic(k) {
  const ta = el("textarea", "pub");
  ta.value = k.public;
  ta.readOnly = true;
  modal({ title: k.name, sub: `${k.kind} · ${k.fingerprint}`, wide: true,
          body: [ta, el("p", "muted small", "Pega esta línea en ~/.ssh/authorized_keys del servidor.")],
          ok: "Copiar y cerrar", onOk: () => copyText(k.public, "Llave pública copiada") });
}
async function generateKey() {
  const name = input("", { placeholder: "ej. laptop-trabajo" });
  const kind = select([["ed25519", "Ed25519 (recomendada)"], ["rsa", "RSA 4096 (servidores antiguos)"], ["ecdsa", "ECDSA P-256"]], "ed25519");
  const res = await modal({ title: "Generar llave", body: [field("Nombre", name), field("Tipo", kind)], ok: "Generar",
    onOk: async () => { const r = await call("generate_key", name.value, kind.value); if (!r.ok) throw new Error(r.error); return r; } });
  if (!res) return;
  await loadKeys();
  copyText(res.public, "Llave creada · la pública quedó copiada para el servidor");
}
async function importKeyFile() {
  let r = await call("pick_key_file");
  while (r.need_passphrase) {
    const pw = await ask(`Frase de paso de «${r.name}»`, "Frase de paso", "", { secret: true,
                         sub: r.error === "Frase de paso incorrecta" ? "Frase incorrecta. Inténtalo de nuevo." : "La llave está protegida." });
    if (pw == null) return;
    r = await call("import_pending_key", pw);
  }
  if (r.cancelled) return;
  if (!r.ok) return toast(r.error, true);
  toast(`Llave «${r.name}» importada`);
  loadKeys();
}
async function pasteKey() {
  const ta = el("textarea", "pub");
  ta.placeholder = "-----BEGIN OPENSSH PRIVATE KEY-----\n…\n-----END OPENSSH PRIVATE KEY-----";
  const name = input("", { placeholder: "ej. servidor-legado" });
  const pass = input("", { type: "password", placeholder: "solo si la llave tiene frase de paso" });
  const res = await modal({ title: "Pegar llave privada", wide: true,
    body: [field("Nombre", name), field("Llave privada", ta), field("Frase de paso", pass)], ok: "Importar",
    onOk: async () => {
      const r = await call("import_key_text", ta.value, name.value, pass.value || null);
      if (!r.ok) throw new Error(r.error);
      return r;
    } });
  if (res) { toast(`Llave «${res.name}» importada`); loadKeys(); }
}

// ---------- túneles ----------
let TUNNELS = [];
async function loadTunnels() {
  const r = await call("tunnels");
  if (!r.ok) return;
  TUNNELS = r.tunnels;
  renderTunnels();
}
function renderTunnels() {
  const list = $("#tunnel-list");
  const active = HOSTS.filter(h => h.tunnel === "activo").length;
  $("#tunnel-badge").hidden = !active;
  $("#tunnel-badge").textContent = active || "";
  if (!list || currentPanel !== "tunnels") return;
  list.replaceChildren();
  if (!TUNNELS.length) {
    list.append(el("div", "empty", "Ningún host tiene reenvíos. Agrégalos en Editar host → Túneles."));
    return;
  }
  for (const t of TUNNELS) {
    const card = el("div", "tunnel " + t.state);
    const head = el("div", "tunnel-head");
    head.append(el("span", "dot " + ({ activo: "connected", conectando: "connecting", error: "closed" }[t.state] || "")),
                el("span", "name grow", t.name));
    const on = t.state === "activo" || t.state === "conectando";
    const b = btn(on ? "Detener" : "Iniciar", { cls: "small" + (on ? "" : " primary") });
    b.addEventListener("click", () => (on ? stopTunnel(t.id) : startTunnel(t)));
    head.append(b);
    card.append(head, el("div", "sub", t.target));
    for (const f of t.forwards) card.append(el("div", "fw", f));
    if (t.state === "error" && t.error) card.append(el("div", "err small", t.error));
    card.addEventListener("contextmenu", e => contextMenu(e, [
      { label: "Editar reenvíos…", icon: "pencil", action: () => editHost(t.id) },
    ]));
    list.append(card);
  }
}
async function startTunnel(h) {
  let pw = null;
  if (h.needs_password) {
    pw = await ask(`Contraseña de ${h.name}`, "Contraseña", "", { secret: true, ok: "Iniciar" });
    if (pw == null) return;
  }
  const r = await call("tunnel_start", h.id, pw);
  if (!r.ok) {
    if (r.error === "need_password") return startTunnel({ ...h, needs_password: true });
    return toast(r.error, true);
  }
  setTunnelState(h.id, "conectando", "");
}
async function stopTunnel(id) {
  await call("tunnel_stop", id);
}
function setTunnelState(id, state, error) {
  const h = HOSTS.find(x => x.id === id);
  if (h) h.tunnel = state;
  const t = TUNNELS.find(x => x.id === id);
  if (t) { t.state = state; t.error = error; }
  renderTunnels();
  renderHosts();
}
EVENTS.tunnel = ev => {
  setTunnelState(ev.id, ev.state, ev.error);
  const h = HOSTS.find(x => x.id === ev.id);
  if (ev.state === "activo") toast(`Túnel de ${h ? h.name : "host"} activo`);
  if (ev.state === "error") toast(`Túnel de ${h ? h.name : "host"}: ${ev.error}`, true);
};

// ---------- organizaciones ----------
function renderOrgs() {
  const list = $("#org-list");
  if (!list) return;
  list.replaceChildren();
  const intro = el("p", "muted small pad", "Entra a los hosts que te asigna tu organización con Nexo Server: " +
    "sin contraseñas ni llaves en tu equipo, con doble factor y sesiones registradas.");
  if (!ORGS.length) {
    const e = el("div", "empty");
    e.append(intro, btn("Conectar a una organización", { cls: "primary small", icon: "building", onClick: () => orgLogin(null) }));
    list.append(e);
    return;
  }
  for (const o of ORGS) {
    const card = el("div", "tunnel");
    const head = el("div", "tunnel-head");
    head.append(icon("building"), el("span", "name grow", o.name));
    const more = btn("", { cls: "icon-btn", icon: "three-dots-vertical", title: "Opciones" });
    more.addEventListener("click", e => contextMenu(e, orgMenu(o)));
    head.append(more);
    card.append(head, el("div", "sub", `${o.username} · ${o.url.replace(/^https?:\/\//, "")}`));
    card.append(el("div", o.expired ? "err small" : "fw", o.expired ? "Sesión expirada o cerrada" : `${o.hosts} host(s) disponibles`));
    if (o.expired) card.append(btn("Volver a ingresar", { cls: "small primary", onClick: () => orgLogin(o) }));
    card.addEventListener("contextmenu", e => contextMenu(e, orgMenu(o)));
    list.append(card);
  }
  list.append(intro);
}
function orgMenu(o) {
  return [
    { label: "Actualizar hosts", icon: "arrow-clockwise", action: async () => {
      const r = await call("org_refresh");
      (r.messages || []).forEach(m => toast(m, true));
      await loadHosts();
      if (!(r.messages || []).length) toast(`${o.name} actualizada`);
    } },
    { label: "Volver a ingresar…", icon: "box-arrow-in-right", action: () => orgLogin(o) },
    { label: "Cerrar sesión", icon: "lock", action: async () => { await call("org_logout", o.id, false); loadHosts(); } },
    "-",
    { label: "Quitar de este equipo", icon: "trash3", danger: true, action: async () => {
      if (!await confirmDlg(`¿Quitar «${o.name}»?`, "Se borra de este equipo; tu cuenta en el servidor sigue igual.", "Quitar")) return;
      await call("org_logout", o.id, true); loadHosts();
    } },
  ];
}
async function orgLogin(o) {
  const url = input(o ? o.url : "", { placeholder: "https://nexo.miempresa.com" });
  const user = input(o ? o.username : "", { placeholder: "tu usuario" });
  const pass = input("", { type: "password" });
  const totp = input("", { placeholder: "6 dígitos", inputMode: "numeric", maxLength: 8 });
  const res = await modal({
    title: o ? `Volver a ingresar a ${o.name}` : "Conectar a una organización",
    sub: "Necesitas el servidor de Nexo Server de tu organización, tu usuario y el código de tu app de doble factor.",
    body: [field("Servidor", url), field("Usuario", user), field("Contraseña", pass), field("Código 2FA", totp)],
    ok: "Ingresar",
    onOk: async () => {
      const r = await call("org_login", url.value.trim(), user.value.trim(), pass.value, totp.value.trim());
      if (!r.ok) throw new Error(r.error);
      return r;
    },
  });
  if (!res) return;
  await loadHosts();
  toast(`${res.name}: ${res.hosts} host(s) disponibles`);
}

// ---------- ajustes ----------
async function openSettings() {
  const th = await call("themes");
  const body = [];
  // Apariencia
  body.push(el("div", "section-label", "TEMA DE LAS TERMINALES"));
  const grid = el("div", "theme-grid");
  const paintThemes = cur => {
    grid.replaceChildren();
    for (const t of th.themes) {
      const b = el("button", "theme-card" + (t.id === cur ? " active" : ""));
      b.type = "button";
      b.style.background = t.bg;
      b.style.color = t.fg;
      const sw = el("div", "swatches");
      for (const c of t.palette.slice(1, 7)) { const s = el("span"); s.style.background = c; sw.append(s); }
      b.append(el("div", "theme-name", t.name), sw);
      b.addEventListener("click", async () => {
        const r = await call("set_theme", t.id, null);
        if (r.ok) { applyTheme(r.theme); paintThemes(t.id); }
      });
      grid.append(b);
    }
  };
  paintThemes(th.current.id);
  body.push(grid, el("div", "section-label", "COLOR DE ACENTO"));
  const accents = el("div", "accents");
  const paintAccents = cur => {
    accents.replaceChildren();
    for (const a of th.accents) {
      const b = el("button", "accent" + (a.id === cur ? " active" : ""));
      b.type = "button";
      b.title = a.name;
      b.style.background = a.color || "linear-gradient(135deg, var(--c-surf2), var(--c-surf3))";
      if (!a.color) b.textContent = "T";
      b.addEventListener("click", async () => {
        const r = await call("set_theme", null, a.id);
        if (r.ok) { applyTheme(r.theme); paintAccents(a.id); }
      });
      accents.append(b);
    }
  };
  paintAccents(th.current.accent_id);
  body.push(accents);

  // Seguridad
  body.push(el("div", "section-label", "SEGURIDAD"));
  const minutes = select([["0", "Nunca"], ["1", "1 minuto"], ["5", "5 minutos"], ["10", "10 minutos"], ["15", "15 minutos"],
                          ["30", "30 minutos"], ["60", "1 hora"], ["240", "4 horas"]], String(SETTINGS.autolock_min));
  if (![...minutes.options].some(x => x.value === String(SETTINGS.autolock_min))) {
    const op = el("option", null, `${SETTINGS.autolock_min} minutos`); op.value = String(SETTINGS.autolock_min); minutes.append(op); minutes.value = op.value;
  }
  const onScreen = check(INFO.platform === "windows" ? "Bloquear al bloquear Windows (Win+L) o suspender" : "Bloquear al bloquear la sesión",
                         SETTINGS.lock_on_screen);
  const saveSec = async () => {
    const r = await call("set_settings", Number(minutes.value), onScreen.input.checked);
    if (r.ok) SETTINGS = r.settings;
  };
  minutes.addEventListener("change", saveSec);
  onScreen.input.addEventListener("change", saveSec);
  body.push(field("Bloquear tras un tiempo sin uso", minutes), onScreen,
            btn("Cambiar contraseña maestra…", { cls: "small", icon: "shield-lock", onClick: changePassword }));

  // Bóveda
  body.push(el("div", "section-label", "BÓVEDA"));
  body.push(el("p", "muted small", (INFO.store
    ? "Importante: al desinstalar Nexo, Windows borra sus datos, bóveda incluida. Exporta una copia antes. "
    : "") + "La copia exportada va cifrada: se abre con tu misma contraseña maestra, aquí o en Nexo para Linux."),
    btn("Exportar copia cifrada…", { cls: "small", icon: "download", onClick: async () => {
      const r = await call("export_vault");
      if (r.ok) toast("Copia guardada en " + r.path); else if (!r.cancelled) toast(r.error, true);
    } }));

  // Acerca de
  body.push(el("div", "section-label", "ACERCA DE"));
  body.push(el("p", "muted small", `Nexo ${INFO.version} · SSH, SFTP, túneles, RDP y bases de datos en una sola ventana. ` +
    "Bóveda local cifrada (AES-256-GCM + scrypt). Sin cuentas, sin nube y sin telemetría: " +
    "Nexo solo se conecta a los servidores que tú agregas."));
  await modal({ title: "Ajustes", wide: true, cls: "settings-dlg", body, ok: "Listo", cancel: false, focus: false });
}
async function changePassword() {
  const cur = input("", { type: "password" });
  const n1 = input("", { type: "password" });
  const n2 = input("", { type: "password" });
  const ok = await modal({ title: "Cambiar contraseña maestra", sub: "No se puede recuperar: si la olvidas, pierdes la bóveda.",
    body: [field("Contraseña actual", cur), field("Nueva (mínimo 8 caracteres)", n1), field("Repetir la nueva", n2)],
    ok: "Cambiar",
    onOk: async () => { const r = await call("change_password", cur.value, n1.value, n2.value); if (!r.ok) throw new Error(r.error); } });
  if (ok) toast("Contraseña maestra cambiada");
}

function initPanels() {
  $("#keys-add").addEventListener("click", e => contextMenu(e, [
    { label: "Generar llave nueva", icon: "plus-lg", action: generateKey },
    { label: "Importar archivo…", icon: "folder2-open", action: importKeyFile },
    { label: "Pegar llave privada…", icon: "copy", action: pasteKey },
  ]));
  $("#orgs-add").addEventListener("click", () => orgLogin(null));
}
