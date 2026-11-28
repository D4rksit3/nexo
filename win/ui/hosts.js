"use strict";
/* Hosts: lista con grupos y organizaciones, inicio, abrir según protocolo y editor. */

const PROTOCOLS = [
  ["ssh", "SSH (terminal + SFTP)"], ["rdp", "RDP (escritorio remoto)"], ["postgres", "PostgreSQL (base de datos)"],
  ["mysql", "MySQL / MariaDB (base de datos)"], ["mssql", "SQL Server (base de datos)"],
  ["mongodb", "MongoDB (base de datos)"], ["redis", "Redis (base de datos)"],
];
const DEFAULT_PORTS = { ssh: 22, rdp: 3389, postgres: 5432, mysql: 3306, mssql: 1433, mongodb: 27017, redis: 6379 };
const DB_PROTOCOLS = ["postgres", "mysql", "mssql", "mongodb", "redis"];
const PROTO_SHORT = { rdp: "RDP", postgres: "PG", mysql: "MySQL", mssql: "MSSQL", mongodb: "Mongo", redis: "Redis" };
const RESOLUTIONS = [["auto", "Ajustar a la ventana"], ["1280x720", "1280 × 720"], ["1366x768", "1366 × 768"],
                     ["1600x900", "1600 × 900"], ["1920x1080", "1920 × 1080"], ["2560x1440", "2560 × 1440"]];
const collapsed = new Set();

async function loadHosts() {
  const r = await call("hosts");
  if (!r.ok) return;
  HOSTS = r.hosts;
  GROUPS = r.groups;
  ORGS = r.orgs;
  collapsed.clear();
  GROUPS.forEach(g => g.collapsed && collapsed.add(g.name));
  renderHosts();
  renderHome();
  renderOrgs();
  renderTunnels();
}
function hostIcon(h) {
  const key = h.icon || (h.protocol === "rdp" ? "windows" : DB_PROTOCOLS.includes(h.protocol) ? "db" : "server");
  const def = HOST_ICONS[key] || HOST_ICONS.server || ["hdd-rack", "", null];
  return icon(def[0], def[2]);
}
function hostSub(h) {
  const port = h.port && h.port !== DEFAULT_PORTS[h.protocol] ? `:${h.port}` : "";
  const proto = h.protocol !== "ssh" ? `${PROTO_SHORT[h.protocol] || h.protocol} · ` : "";
  return `${proto}${h.user ? h.user + "@" : ""}${h.host}${port}${h.jump ? "  ↳ " + h.jump : ""}`;
}

// ---------- abrir ----------
async function openHost(h, mode) {
  if (h.protocol === "ssh") return mode === "sftp" ? openSftp(h) : connect(h);
  if (h.protocol === "rdp") return openRdp(h);
  if (DB_PROTOCOLS.includes(h.protocol)) return openDb(h);
}
EVENTS.rdp_closed = ev => { if (ev.error) toast(`${ev.name}: ${ev.error}`, true); };

// ---------- lista ----------
function hostRow(h, opts = {}) {
  const row = el("div", "host");
  row.dataset.id = h.id;
  row.tabIndex = 0;
  row.append(hostIcon(h));
  const txt = el("div", "txt");
  txt.append(el("div", "name", h.name), el("div", "sub", hostSub(h)));
  row.append(txt);
  if (h.tunnel === "activo") {
    const b = el("span", "badge on", "túnel");
    b.title = "Túnel activo";
    row.append(b);
  }
  if (h.protocol === "ssh") {
    const s = el("button", "go");
    s.title = "SFTP";
    s.append(icon("folder2-open"));
    s.addEventListener("click", e => { e.stopPropagation(); openHost(h, "sftp"); });
    row.append(s);
  }
  const go = el("button", "go");
  go.title = h.protocol === "rdp" ? "Abrir escritorio remoto" : "Conectar";
  go.append(icon("play-fill"));
  go.addEventListener("click", e => { e.stopPropagation(); openHost(h); });
  row.append(go);
  row.addEventListener("dblclick", () => openHost(h));
  row.addEventListener("keydown", e => {
    if (e.key === "Enter") openHost(h);
    else if (e.key === "Delete" && !h.org) deleteHost(h);
    else if (e.key === "F2" && !h.org) editHost(h.id);
  });
  row.addEventListener("click", () => {
    $$(".host.selected").forEach(x => x.classList.remove("selected"));
    row.classList.add("selected");
  });
  row.addEventListener("contextmenu", e => contextMenu(e, hostMenu(h)));
  if (!h.org && !opts.noDrag) {
    row.draggable = true;
    row.addEventListener("dragstart", e => {
      e.dataTransfer.setData("application/x-nexo-host", h.id);
      e.dataTransfer.effectAllowed = "move";
    });
  }
  return row;
}
function hostMenu(h) {
  const items = [];
  if (h.protocol === "ssh") {
    items.push({ label: "Abrir terminal", icon: "terminal", action: () => openHost(h), hint: "Enter" },
               { label: "Abrir SFTP", icon: "folder2-open", action: () => openHost(h, "sftp") });
    if (h.forwards) items.push(h.tunnel === "activo" || h.tunnel === "conectando"
      ? { label: "Detener túneles", icon: "arrow-left-right", action: () => stopTunnel(h.id) }
      : { label: `Iniciar túneles (${h.forwards})`, icon: "arrow-left-right", action: () => startTunnel(h) });
  } else if (h.protocol === "rdp") {
    items.push({ label: "Abrir escritorio remoto", icon: "windows", action: () => openHost(h) });
  } else {
    items.push({ label: "Abrir base de datos", icon: "database", action: () => openHost(h) });
  }
  if (h.org) {
    items.push("-", { label: `Host de ${h.org_name}`, icon: "building", disabled: true });
    return items;
  }
  items.push("-",
    { label: "Editar…", icon: "pencil", action: () => editHost(h.id), hint: "F2" },
    { label: "Duplicar", icon: "copy", action: async () => { const r = await call("duplicate_host", h.id); r.ok ? (await loadHosts(), editHost(r.id)) : toast(r.error, true); } },
    { label: "Mover a grupo…", icon: "folder", action: () => moveToGroup(h) },
    h.notes ? { label: "Ver notas", icon: "inbox", action: () => showNotes(h) } : null,
    h.protocol === "ssh" ? { label: "Copiar comando ssh", icon: "code-slash", action: () => copyText(sshCommand(h)) } : null,
    "-",
    { label: "Eliminar", icon: "trash3", danger: true, action: () => deleteHost(h), hint: "Supr" });
  return items;
}
function sshCommand(h) {
  const parts = ["ssh"];
  if (h.port && h.port !== 22) parts.push("-p", String(h.port));
  parts.push(h.user ? `${h.user}@${h.host}` : h.host);
  return parts.join(" ");
}
async function showNotes(h) {
  const r = await call("host_notes", h.id);
  const pre = el("pre", "notes-view", r.notes || "");
  modal({ title: `Notas de ${h.name}`, body: [pre], cancel: false, ok: "Cerrar", wide: true });
}
async function deleteHost(h) {
  if (!await confirmDlg(`¿Eliminar «${h.name}»?`, "Se borra de la bóveda. No se puede deshacer.")) return;
  const r = await call("delete_host", h.id);
  if (!r.ok) return toast(r.error, true);
  await loadHosts();
  toast(`«${h.name}» eliminado`);
}
async function moveToGroup(h) {
  const names = GROUPS.map(g => g.name);
  const s = select([["", "Sin grupo"], ...names.map(n => [n, n]), ["__nuevo__", "Nuevo grupo…"]], h.group || "");
  const nuevo = input("", { placeholder: "Nombre del grupo nuevo" });
  const nf = field("Nombre", nuevo);
  nf.hidden = true;
  s.addEventListener("change", () => { nf.hidden = s.value !== "__nuevo__"; if (!nf.hidden) nuevo.focus(); });
  const g = await modal({ title: `Mover «${h.name}»`, body: [field("Grupo", s), nf], ok: "Mover",
    onOk: () => {
      if (s.value !== "__nuevo__") return s.value;
      if (!nuevo.value.trim()) throw new Error("Escribe el nombre del grupo");
      return nuevo.value.trim();
    } });
  if (g == null) return;
  const r = await call("move_host", h.id, g);
  r.ok ? loadHosts() : toast(r.error, true);
}

function renderHosts() {
  const list = $("#host-list");
  list.replaceChildren();
  const q = $("#filter").value.trim().toLowerCase();
  const match = h => !q || [h.name, h.host, h.user, h.group, h.org_name, h.protocol].some(x => (x || "").toLowerCase().includes(q));
  const shown = HOSTS.filter(match);
  if (!HOSTS.length) {
    const e = el("div", "empty");
    e.append(el("p", null, "Todavía no hay hosts."),
      btn("Nuevo host", { cls: "primary small", icon: "plus-lg", onClick: () => editHost(null) }),
      btn("Importar ~/.ssh/config", { cls: "small", onClick: importSshConfig }));
    list.append(e);
    return;
  }
  if (!shown.length) { list.append(el("div", "empty", "Nada coincide con el filtro")); return; }
  const own = shown.filter(h => !h.org);
  for (const g of [...GROUPS.map(g => g.name), ""]) {
    const items = own.filter(h => (h.group || "") === g).sort((a, b) => a.name.localeCompare(b.name));
    if (!items.length && (g === "" || q)) continue;
    list.append(groupHead(g, items.length, !!q));
    if (q || !collapsed.has(g)) items.forEach(h => list.append(hostRow(h)));
  }
  for (const o of ORGS) {
    const items = shown.filter(h => h.org === o.id).sort((a, b) => a.name.localeCompare(b.name));
    if (q && !items.length) continue;
    const key = "org:" + o.id;
    const head = el("div", "group-head org");
    const open = q || !collapsed.has(key);
    head.append(icon(open ? "chevron-down" : "chevron-right"), icon("building"), el("span", null, o.name),
                el("span", "count", o.expired ? "sesión expirada" : String(items.length)));
    head.addEventListener("click", () => { collapsed.has(key) ? collapsed.delete(key) : collapsed.add(key); renderHosts(); });
    head.addEventListener("contextmenu", e => contextMenu(e, orgMenu(o)));
    list.append(head);
    if (open) {
      if (o.expired) {
        const b = btn("Volver a ingresar", { cls: "small org-relogin", icon: "box-arrow-in-right", onClick: () => orgLogin(o) });
        list.append(b);
      }
      items.forEach(h => list.append(hostRow(h)));
    }
  }
}
function groupHead(g, count, filtering) {
  const head = el("div", "group-head");
  const open = filtering || !collapsed.has(g);
  const meta = GROUPS.find(x => x.name === g);
  head.append(icon(open ? "chevron-down" : "chevron-right"));
  if (meta && meta.icon && meta.icon !== "folder" && HOST_ICONS[meta.icon]) head.append(icon(HOST_ICONS[meta.icon][0]));
  head.append(el("span", null, g || "Sin grupo"), el("span", "count", String(count)));
  head.addEventListener("click", () => {
    if (collapsed.has(g)) collapsed.delete(g); else collapsed.add(g);
    if (g) call("set_collapsed", g, collapsed.has(g));
    renderHosts();
  });
  head.addEventListener("dragover", e => {
    if (e.dataTransfer.types.includes("application/x-nexo-host")) { e.preventDefault(); head.classList.add("drop"); }
  });
  head.addEventListener("dragleave", () => head.classList.remove("drop"));
  head.addEventListener("drop", async e => {
    head.classList.remove("drop");
    const id = e.dataTransfer.getData("application/x-nexo-host");
    if (!id) return;
    e.preventDefault();
    const r = await call("move_host", id, g);
    r.ok ? loadHosts() : toast(r.error, true);
  });
  if (g) head.addEventListener("contextmenu", e => contextMenu(e, [
    { label: "Nuevo host aquí", icon: "plus-lg", action: () => editHost(null, g) },
    { label: "Renombrar grupo…", icon: "pencil", action: () => renameGroup(g) },
    { label: "Subir", icon: "arrow-up", action: async () => { await call("move_group", g, -1); loadHosts(); } },
    { label: "Bajar", icon: "chevron-down", action: async () => { await call("move_group", g, 1); loadHosts(); } },
    "-",
    { label: "Eliminar grupo", icon: "trash3", danger: true, action: async () => {
      if (!await confirmDlg(`¿Eliminar el grupo «${g}»?`, "Los hosts no se borran: pasan a «Sin grupo».")) return;
      await call("delete_group", g); loadHosts();
    } },
  ]));
  return head;
}
async function newGroup() {
  const name = await ask("Nuevo grupo", "Nombre", "", { placeholder: "ej. Producción" });
  if (name == null) return;
  const r = await call("add_group", name.trim());
  r.ok ? loadHosts() : toast(r.error, true);
}
async function renameGroup(g) {
  const meta = GROUPS.find(x => x.name === g) || {};
  const name = await ask("Renombrar grupo", "Nombre", g);
  if (name == null) return;
  const r = await call("update_group", g, name.trim(), meta.icon || "folder");
  r.ok ? loadHosts() : toast(r.error, true);
}
async function importSshConfig() {
  const r = await call("import_ssh_config");
  if (r.cancelled) return;
  if (!r.ok) return toast(r.error, true);
  await loadHosts();
  let msg = `Importados ${r.added} host(s)` + (r.skipped ? `, ${r.skipped} ya existían` : "");
  if (r.locked_keys && r.locked_keys.length) msg += `. Llaves con frase (impórtalas en Llaves): ${r.locked_keys.join(", ")}`;
  toast(msg);
}

function renderHome() {
  const n = HOSTS.length;
  $("#home-stats").textContent = `${n} host${n === 1 ? "" : "s"} · bóveda cifrada AES-256`;
  const rec = $("#recent");
  rec.replaceChildren();
  const recent = HOSTS.filter(h => h.last_used).sort((a, b) => b.last_used - a.last_used).slice(0, 6);
  if (!recent.length) rec.append(el("p", "muted", "Aún no te has conectado a ningún host."));
  recent.forEach(h => rec.append(hostRow(h, { noDrag: true })));
}

// ---------- editor de host ----------
async function editHost(id, group = null) {
  const r = await call("host_get", id);
  if (!r.ok) return toast(r.error, true);
  const h = r.host;
  if (!id && group) h.group = group;
  const tabsBar = el("div", "dlg-tabs");
  const pages = {};
  const page = (key, label) => {
    const b = btn(label, { cls: "dlg-tab" });
    b.dataset.page = key;
    b.addEventListener("click", () => showPage(key));
    tabsBar.append(b);
    pages[key] = el("div", "dlg-page");
    pages[key].dataset.page = key;
    return pages[key];
  };
  const showPage = key => {
    $$(".dlg-tab", tabsBar).forEach(b => b.classList.toggle("active", b.dataset.page === key));
    Object.entries(pages).forEach(([k, p]) => (p.hidden = k !== key));
  };

  // General
  const g = page("general", "General");
  const fName = input(h.name, { placeholder: "ej. nodo-aplicaciones" });
  const fGroup = input(h.group || "", { placeholder: "ej. Producción" });
  fGroup.setAttribute("list", "group-options");
  const dl = el("datalist");
  dl.id = "group-options";
  r.groups.forEach(n => { const o = el("option"); o.value = n; dl.append(o); });
  const fProto = select(PROTOCOLS, h.protocol);
  const fHost = input(h.host, { placeholder: "IP o nombre DNS" });
  const fPort = input(h.port, { type: "number", min: 1, max: 65535 });
  const fUser = input(h.user || "", { placeholder: "ej. ubuntu / Administrador" });
  const fAuth = select([["key", "Llave SSH"], ["password", "Contraseña"]], h.auth === "password" ? "password" : "key");
  const fKey = select([["", r.keys.length ? "— elige una llave —" : "— no hay llaves: créalas en «Llaves» —"],
                       ...r.keys.map(k => [k.id, `${k.name}  (${k.kind})`])], h.key || "");
  const fPass = input("", { type: "password", placeholder: h.has_password ? "•••••• guardada — escribe para cambiarla" : "vacío = preguntar al conectar" });
  const fClear = check("Borrar la contraseña guardada", false);
  fClear.hidden = !h.has_password;
  const fJump = select([["", "— directo —"], ...r.jumps.map(j => [j.id, `${j.name}  (${j.host})`])], h.jump || "");
  let iconTouched = !!h.icon;
  let iconValue = h.icon || (h.protocol === "rdp" ? "windows" : DB_PROTOCOLS.includes(h.protocol) ? "db" : "linux");
  const iconGrid = el("div", "icon-grid");
  const paintIconGrid = () => {
    iconGrid.replaceChildren();
    for (const [key, [ic, label, color]] of Object.entries(HOST_ICONS)) {
      const b = el("button", "icon-pick" + (key === iconValue ? " active" : ""));
      b.type = "button";
      b.title = label;
      b.append(icon(ic, color));
      b.addEventListener("click", () => { iconValue = key; iconTouched = true; paintIconGrid(); });
      iconGrid.append(b);
    }
  };
  paintIconGrid();
  const rowAuth = field("Autenticación", fAuth);
  const rowKey = field("Llave", fKey);
  const rowPass = field("Contraseña", fPass);
  const two = (a, b) => { const w = el("div", "row2"); w.append(a, b); return w; };
  g.append(two(field("Nombre", fName), field("Grupo", fGroup)), dl, field("Protocolo", fProto),
           two(field("Host", fHost), field("Puerto", fPort)), field("Usuario", fUser), rowAuth, rowKey, rowPass, fClear,
           field("Saltar por", fJump, "Usa otro host SSH como bastión. En RDP y bases de datos, Nexo abre un túnel automático por ese host."),
           field("Icono", iconGrid));

  // Túneles
  const t = page("tunnels", "Túneles");
  t.append(el("p", "muted small", "Local (L): un puerto de tu PC llega a un destino visto desde el servidor (ej. 5433 → 127.0.0.1:5432). " +
    "Remoto (R): un puerto del servidor llega a tu PC. SOCKS (D): proxy dinámico en tu PC. Se encienden desde el panel «Túneles»."));
  const fwBox = el("div", "fw-list");
  const fwRows = [];
  const addFw = fw => {
    const row = el("div", "fw-row");
    const ty = select([["L", "Local"], ["R", "Remoto"], ["D", "SOCKS"]], fw.type || "L");
    const port = input(fw.port ?? "", { placeholder: "puerto", type: "number", min: 1, max: 65535 });
    const arrow = el("span", "arrow", "→");
    const dh = input(fw.dest_host || "", { placeholder: "destino" });
    const dp = input(fw.dest_port ?? "", { placeholder: "puerto", type: "number", min: 1, max: 65535 });
    const rm = btn("", { cls: "icon-btn", icon: "trash3", title: "Quitar" });
    const rec = { row, ty, port, dh, dp, bind: fw.bind || "127.0.0.1" };
    const sync = () => [arrow, dh, dp].forEach(x => (x.style.visibility = ty.value === "D" ? "hidden" : "visible"));
    ty.addEventListener("change", sync);
    rm.addEventListener("click", () => { fwRows.splice(fwRows.indexOf(rec), 1); row.remove(); });
    row.append(ty, port, arrow, dh, dp, rm);
    fwRows.push(rec);
    fwBox.append(row);
    sync();
  };
  (h.forwards || []).forEach(addFw);
  t.append(fwBox, btn("Agregar reenvío", { cls: "small", icon: "plus-lg",
    onClick: () => addFw({ type: "L", dest_host: "127.0.0.1" }) }));

  // RDP
  const rp = page("rdp", "RDP");
  const o = h.rdp || {};
  const fDomain = input(o.domain || "", { placeholder: "opcional, ej. EMPRESA" });
  const fRes = select(RESOLUTIONS, o.resolution || "auto");
  const fFull = check("Pantalla completa", o.fullscreen);
  const fClip = check("Portapapeles compartido", o.clipboard !== false);
  const fShare = check("Compartir mis unidades con el equipo remoto", o.share_home);
  rp.append(field("Dominio", fDomain), field("Resolución", fRes), fFull, fClip, fShare,
            el("p", "muted small", INFO.platform === "windows"
              ? "Se abre dentro de Nexo, en una pestaña, sin los avisos de Windows: Nexo recuerda el certificado del servidor la primera vez y solo pregunta si cambia. La contraseña va directo a la sesión, sin pasar por el disco."
              : "En Linux se abre con FreeRDP."));

  // Base de datos
  const dp_ = page("db", "Base de datos");
  const d = h.db || {};
  const fDb = input(d.database || "", { placeholder: "postgres, app_prod, 0 (Redis)…" });
  const fAuthDb = input(d.auth_db || "", { placeholder: "admin" });
  const rowAuthDb = field("Base de autenticación", fAuthDb);
  const fRo = check("Solo lectura (recomendado en producción)", d.readonly);
  const fTls = check("Cifrar con TLS/SSL", d.tls);
  dp_.append(field("Base de datos", fDb), rowAuthDb, fRo, fTls,
             el("p", "muted small", "Si la base no está expuesta, usa «Saltar por» en General: Nexo abre un túnel SSH automático hacia ella."));

  // Notas
  const np = page("notes", "Notas");
  const fNotes = el("textarea", "notes");
  fNotes.value = h.notes || "";
  fNotes.placeholder = "Lo que quieras recordar de este host (cifrado en la bóveda)";
  np.append(fNotes);

  const sync = changed => {
    const proto = fProto.value, isDb = DB_PROTOCOLS.includes(proto), isRdp = proto === "rdp";
    if (changed === fProto) {
      if (Object.values(DEFAULT_PORTS).includes(Number(fPort.value)) || !fPort.value) fPort.value = DEFAULT_PORTS[proto];
      if (!iconTouched) { iconValue = isRdp ? "windows" : isDb ? "db" : "linux"; paintIconGrid(); }
    }
    rowAuth.hidden = isRdp || isDb;
    const useKey = proto === "ssh" && fAuth.value === "key";
    rowKey.hidden = !useKey;
    rowPass.hidden = useKey;
    fClear.hidden = useKey || !h.has_password;
    fPass.placeholder = h.has_password ? "•••••• guardada — escribe para cambiarla"
      : isDb ? "contraseña de la base de datos" : isRdp ? "vacío = la pide Windows al conectar" : "vacío = preguntar al conectar";
    $$(".dlg-tab", tabsBar).forEach(b => {
      const k = b.dataset.page;
      b.hidden = (k === "tunnels" && proto !== "ssh") || (k === "rdp" && !isRdp) || (k === "db" && !isDb);
    });
    rowAuthDb.hidden = proto !== "mongodb";
  };
  fProto.addEventListener("change", () => sync(fProto));
  fAuth.addEventListener("change", () => sync(fAuth));
  showPage("general");
  sync(null);

  const saved = await modal({
    title: id ? `Editar «${h.name}»` : "Nuevo host", wide: true, cls: "host-dlg", ok: "Guardar",
    body: [tabsBar, ...Object.values(pages)],
    onOk: async () => {
      const data = {
        id: id || null, name: fName.value, group: fGroup.value, protocol: fProto.value, host: fHost.value,
        port: Number(fPort.value), user: fUser.value, auth: fAuth.value, key: fKey.value || null,
        password: fPass.value, password_clear: fClear.input.checked, jump: fJump.value || null,
        icon: iconTouched ? iconValue : (h.icon || null), notes: fNotes.value,
        forwards: fwRows.map(x => ({ type: x.ty.value, bind: x.bind, port: x.port.value === "" ? null : Number(x.port.value),
                                    dest_host: x.dh.value, dest_port: x.dp.value })),
        rdp: { domain: fDomain.value, resolution: fRes.value, fullscreen: fFull.input.checked,
               clipboard: fClip.input.checked, share_home: fShare.input.checked },
        db: { database: fDb.value, auth_db: fAuthDb.value, readonly: fRo.input.checked, tls: fTls.input.checked },
      };
      const res = await call("save_host", data);
      if (!res.ok) {
        if (/llave/i.test(res.error)) showPage("general");
        else if (/túnel/i.test(res.error)) showPage("tunnels");
        throw new Error(res.error);
      }
      return res.id;
    },
  });
  if (saved) { await loadHosts(); toast(id ? "Host guardado" : "Host creado"); }
}

function initHosts() {
  $("#filter").addEventListener("input", renderHosts);
  $("#filter").addEventListener("keydown", e => {
    if (e.key === "Enter") {
      const first = $("#host-list .host");
      if (first) openHost(HOSTS.find(h => h.id === first.dataset.id));
    } else if (e.key === "ArrowDown") {
      const first = $("#host-list .host");
      if (first) { first.focus(); e.preventDefault(); }
    }
  });
  $("#host-list").addEventListener("keydown", e => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const rows = $$("#host-list .host");
    const i = rows.indexOf(document.activeElement);
    const n = rows[i + (e.key === "ArrowDown" ? 1 : -1)];
    if (n) { n.focus(); n.click(); e.preventDefault(); }
  });
  $("#hosts-add").addEventListener("click", () => editHost(null));
  $("#hosts-more").addEventListener("click", e => contextMenu(e, [
    { label: "Nuevo host", icon: "plus-lg", action: () => editHost(null), hint: "Ctrl+N" },
    { label: "Nuevo grupo", icon: "folder-plus", action: newGroup },
    { label: "Importar ~/.ssh/config", icon: "box-arrow-in-right", action: importSshConfig },
    "-",
    { label: "Plegar todos los grupos", icon: "chevron-right", action: () => { GROUPS.forEach(g => collapsed.add(g.name)); collapsed.add(""); renderHosts(); } },
    { label: "Desplegar todos", icon: "chevron-down", action: () => { collapsed.clear(); renderHosts(); } },
  ]));
}
