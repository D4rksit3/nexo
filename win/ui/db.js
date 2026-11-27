"use strict";
/* Pestaña de base de datos: objetos a la izquierda, consulta arriba y resultados abajo.
   Ctrl+Enter ejecuta (solo lo seleccionado, si hay selección). F5 recarga los objetos. */

const KIND_ICON = { tabla: "table", vista: "eye", "colección": "collection", clave: "key", base: "database" };

async function openDb(h) {
  const t = addTab("db", h.name, "database");
  t.host = h;
  t.pane.append(el("div", "loading", `Conectando a ${hostSub(h)}…`));
  activate(t.id);
  const r = await call("open_db", h.id, null);
  if (!r.ok) {
    setState(t, "closed");
    t.pane.replaceChildren(errorBox(r.error, () => { closeTab(t.id); openDb(h); }));
    return;
  }
  setState(t, "connected");
  t.sid = r.sid;
  h.last_used = Date.now() / 1000;
  renderHome();
  buildDb(t, r);
}

function buildDb(t, st) {
  t.pane.replaceChildren();
  const wrap = el("div", "dbwrap");
  // objetos
  const side = el("div", "dbside");
  const dbSel = select(st.databases.map(d => [d, d]), st.database);
  dbSel.title = "Base de datos";
  dbSel.hidden = st.databases.length < 2;
  const filter = input("", { type: "search", placeholder: "Filtrar objetos…", className: "filter" });
  const tree = el("div", "dbtree");
  side.append(dbSel, filter, tree);
  // consulta
  const main = el("div", "dbmain");
  const bar = el("div", "dbbar");
  const bRun = btn("Ejecutar", { cls: "primary small", icon: "play-fill", title: "Ctrl+Enter (solo lo seleccionado, si hay selección)" });
  const limit = select([["100", "100 filas"], ["500", "500 filas"], ["1000", "1.000 filas"], ["5000", "5.000 filas"]], "500");
  const bTree = btn("", { cls: "icon-btn", icon: "arrow-clockwise", title: "Recargar objetos (F5)" });
  const bCsv = btn("CSV", { cls: "small", icon: "download", title: "Exportar los resultados a CSV" });
  bar.append(bRun, limit, bTree, bCsv, el("span", "grow"),
             el("span", "badge", st.engine_name));
  if (st.readonly) bar.append(el("span", "badge warn", "SOLO LECTURA"));
  const editor = el("textarea", "dbeditor");
  editor.spellcheck = false;
  editor.placeholder = st.engine === "redis" ? "GET clave\nKEYS usuario:*" : st.engine === "mongodb"
    ? "db.coleccion.find({})" : "SELECT * FROM tabla LIMIT 100;";
  const results = el("div", "dbresults");
  const status = el("div", "files-status");
  const msg = el("span", "grow muted", `Conectado a ${st.engine_name} · base «${st.database || "—"}»` + (st.readonly ? " · solo lectura" : ""));
  status.append(msg);
  main.append(bar, editor, results, status);
  wrap.append(side, main);
  t.pane.append(wrap);

  let lastTree = st.tree;
  let result = null;
  let sortCol = -1, sortDir = 1;
  const collapsedGroups = new Set();

  function renderTree() {
    tree.replaceChildren();
    const q = filter.value.trim().toLowerCase();
    let total = 0;
    for (const g of lastTree) {
      const items = g.items.filter(i => !q || i.name.toLowerCase().includes(q));
      if (q && !items.length) continue;
      const open = q || !collapsedGroups.has(g.group);
      const head = el("div", "group-head");
      head.append(icon(open ? "chevron-down" : "chevron-right"), el("span", null, g.group), el("span", "count", String(g.items.length)));
      head.addEventListener("click", () => { collapsedGroups.has(g.group) ? collapsedGroups.delete(g.group) : collapsedGroups.add(g.group); renderTree(); });
      tree.append(head);
      if (!open) continue;
      for (const it of items) {
        const row = el("div", "dbobj");
        row.append(icon(KIND_ICON[it.kind] || "table"), el("span", null, it.name));
        row.title = `${it.kind} · doble clic para ver su contenido`;
        row.addEventListener("dblclick", () => openObject(g.group, it.name));
        row.addEventListener("contextmenu", e => contextMenu(e, [
          { label: "Ver contenido", icon: "play-fill", action: () => openObject(g.group, it.name) },
          { label: "Copiar nombre", icon: "copy", action: () => copyText(it.name) },
        ]));
        tree.append(row);
        total++;
      }
    }
    if (!lastTree.length) tree.append(el("div", "empty", "Sin objetos"));
  }
  async function openObject(group, name) {
    const r = await call("db_default_query", t.sid, group, name);
    if (!r.ok) return toast(r.error, true);
    editor.value = r.query;
    run();
  }
  async function run() {
    const s = editor.selectionStart, e = editor.selectionEnd;
    const text = s !== e ? editor.value.slice(s, e) : editor.value;
    if (!text.trim()) return toast("Escribe una consulta");
    bRun.disabled = true;
    msg.textContent = "Ejecutando…";
    msg.classList.remove("err");
    const r = await call("db_run", t.sid, text, Number(limit.value));
    bRun.disabled = false;
    if (!r.ok) {
      msg.textContent = "✖ " + r.error;
      msg.classList.add("err");
      if (/conectad|closed|lost|perdi/i.test(r.error)) setState(t, "closed");
      return;
    }
    result = r;
    sortCol = -1;
    renderResults();
    msg.textContent = r.info;
    if (r.database && r.database !== dbSel.value) {
      if (![...dbSel.options].some(o => o.value === r.database)) { const o = el("option", null, r.database); o.value = r.database; dbSel.append(o); }
      dbSel.value = r.database;
    }
  }
  function renderResults() {
    results.replaceChildren();
    if (!result || !result.columns.length) {
      if (result) results.append(el("div", "empty", result.info));
      return;
    }
    const table = el("table", "grid");
    const thead = el("thead"), tr = el("tr");
    result.columns.forEach((c, i) => {
      const th = el("th", sortCol === i ? "sorted" : "", c + (sortCol === i ? (sortDir > 0 ? " ▲" : " ▼") : ""));
      th.addEventListener("click", () => { sortDir = sortCol === i ? -sortDir : 1; sortCol = i; renderResults(); });
      tr.append(th);
    });
    thead.append(tr);
    const tbody = el("tbody");
    let rows = result.rows;
    if (sortCol >= 0) {
      const num = rows.every(r => r[sortCol] === "NULL" || !isNaN(Number(r[sortCol])));
      rows = [...rows].sort((a, b) => {
        const x = a[sortCol], y = b[sortCol];
        return sortDir * (num ? (Number(x) || 0) - (Number(y) || 0) : x.localeCompare(y));
      });
    }
    for (const r of rows) {
      const row = el("tr");
      r.forEach((v, i) => {
        const td = el("td", v === "NULL" ? "null" : "", v.length > 300 ? v.slice(0, 300) + "…" : v);
        td.title = v.length > 80 ? v.slice(0, 2000) : "";
        td.addEventListener("contextmenu", e => contextMenu(e, [
          { label: "Copiar valor", icon: "copy", action: () => copyText(v) },
          { label: "Copiar fila (separada por tabulaciones)", action: () => copyText(r.join("\t")) },
          { label: "Copiar nombre de la columna", action: () => copyText(result.columns[i]) },
        ]));
        td.addEventListener("dblclick", () => copyText(v));
        row.append(td);
      });
      tbody.append(row);
    }
    table.append(thead, tbody);
    results.append(table);
  }
  async function reloadTree() {
    const r = await call("db_tree", t.sid);
    if (!r.ok) return toast(r.error, true);
    lastTree = r.tree;
    renderTree();
  }
  dbSel.addEventListener("change", async () => {
    msg.textContent = `Cambiando a «${dbSel.value}»…`;
    const r = await call("db_use", t.sid, dbSel.value);
    if (!r.ok) { msg.textContent = "✖ " + r.error; return; }
    lastTree = r.tree;
    renderTree();
    msg.textContent = `Base «${r.database}»`;
  });
  filter.addEventListener("input", renderTree);
  bRun.addEventListener("click", run);
  bTree.addEventListener("click", reloadTree);
  bCsv.addEventListener("click", async () => {
    const r = await call("db_export", t.sid);
    if (r.ok) toast(`Exportadas ${r.rows} fila(s) a ${r.path}`);
    else if (!r.cancelled) toast(r.error, true);
  });
  editor.addEventListener("keydown", e => {
    if (e.ctrlKey && e.key === "Enter") { e.preventDefault(); run(); }
    else if (e.key === "F5") { e.preventDefault(); reloadTree(); }
    else if (e.key === "Tab" && !e.shiftKey) {
      e.preventDefault();
      const s = editor.selectionStart;
      editor.setRangeText("  ", s, editor.selectionEnd, "end");
    }
  });
  t.pane.addEventListener("keydown", e => { if (e.key === "F5" && e.target !== editor) { e.preventDefault(); reloadTree(); } });
  t.focus = () => editor.focus();
  t.onClose = () => api.close_session(t.sid);
  t.reconnect = () => { closeTab(t.id); openDb(t.host); };
  renderTree();
}
