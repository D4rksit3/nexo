"use strict";
/* Utilidades de interfaz compartidas: elementos, iconos, avisos, diálogos y menú contextual. */

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}
function icon(name, color) {
  const i = document.createElement("i");
  i.className = "ic";
  i.style.setProperty("--src", `url("icons/bi-${name}.svg")`);
  if (color) i.style.color = color;
  return i;
}
function paintIcons(root = document) {
  $$(".ic[data-i]", root).forEach(i => i.style.setProperty("--src", `url("icons/bi-${i.dataset.i}.svg")`));
}
function btn(label, opts = {}) {
  const b = el("button", opts.cls || "", null);
  b.type = "button";
  if (opts.icon) b.append(icon(opts.icon));
  if (label) b.append(el("span", null, label));
  if (opts.title) b.title = opts.title;
  if (opts.onClick) b.addEventListener("click", opts.onClick);
  return b;
}
function field(label, input, hint) {
  // <label> solo para un control simple: con varios botones dentro, un clic en el hueco
  // activaría el primero.
  const simple = ["INPUT", "SELECT", "TEXTAREA"].includes(input.tagName);
  const w = el(simple ? "label" : "div", "field");
  w.append(el("span", "field-label", label), input);
  if (hint) w.append(el("small", "field-hint", hint));
  return w;
}
function input(value = "", attrs = {}) {
  const i = el("input");
  i.value = value ?? "";
  i.spellcheck = false;
  i.autocomplete = "off";
  Object.assign(i, attrs);
  return i;
}
function select(options, value) {
  const s = el("select");
  for (const [v, t] of options) {
    const o = el("option", null, t);
    o.value = v;
    s.append(o);
  }
  if (value != null) s.value = value;
  return s;
}
function check(label, value) {
  const w = el("label", "check");
  const c = el("input");
  c.type = "checkbox";
  c.checked = !!value;
  w.append(c, el("span", null, label));
  w.input = c;
  return w;
}

function humanSize(n) {
  if (n == null) return "";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (i ? n.toFixed(n < 10 ? 1 : 0) : n) + " " + u[i];
}
function humanDate(sec) {
  if (!sec) return "";
  const d = new Date(sec * 1000), now = new Date();
  const two = x => String(x).padStart(2, "0");
  const hm = `${two(d.getHours())}:${two(d.getMinutes())}`;
  if (d.toDateString() === now.toDateString()) return `hoy ${hm}`;
  return `${two(d.getDate())}/${two(d.getMonth() + 1)}/${d.getFullYear()} ${hm}`;
}

// ---------- avisos ----------
let toastTimer = null;
function toast(text, error = false) {
  const t = $("#toast");
  t.textContent = text;
  t.classList.toggle("error", error);
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), error ? 5500 : 3200);
}

// ---------- diálogos ----------
/* modal({title, sub, body, ok, cancel, danger, wide, onOk, extra})
   onOk() puede devolver un valor (cierra y lo entrega) o lanzar Error(msg) (queda abierto con el mensaje).
   Devuelve una promesa: el valor de onOk, true si no hay onOk, o null si se cancela. */
function modal(o) {
  return new Promise(resolve => {
    const d = el("dialog", "dlg" + (o.wide ? " wide" : "") + (o.cls ? " " + o.cls : ""));
    const form = el("form");
    form.method = "dialog";
    form.autocomplete = "off";
    if (o.title) form.append(el("h3", null, o.title));
    if (o.sub) form.append(el("p", "muted sub", o.sub));
    const body = el("div", "dlg-body");
    if (o.body) body.append(...[].concat(o.body));
    form.append(body);
    const err = el("p", "err");
    form.append(err);
    const menu = el("menu");
    for (const x of o.extra || []) {
      const b = btn(x.label, { cls: "left" + (x.danger ? " danger" : "") });
      b.addEventListener("click", async () => {
        const r = await x.onClick();
        if (r !== undefined) { done = true; d.close(); resolve(r); }
      });
      menu.append(b);
    }
    if (o.cancel !== false) {
      const c = btn(o.cancel || "Cancelar");
      c.addEventListener("click", () => d.close());
      menu.append(c);
    }
    if (o.ok !== false) {
      const k = el("button", o.danger ? "primary danger" : "primary", o.ok || "Aceptar");
      k.type = "submit";
      menu.append(k);
    }
    form.append(menu);
    d.append(form);
    let done = false;
    form.addEventListener("submit", async ev => {
      ev.preventDefault();
      err.textContent = "";
      const k = $("button[type=submit]", form);
      if (k) k.disabled = true;
      try {
        const v = o.onOk ? await o.onOk() : true;
        done = true;
        d.close();
        resolve(v === undefined ? true : v);
      } catch (e) {
        err.textContent = e.message || String(e);
      } finally {
        if (k) k.disabled = false;
      }
    });
    d.addEventListener("close", () => { d.remove(); if (!done) resolve(null); });
    d.addEventListener("keydown", e => { if (e.key === "Escape") { e.stopPropagation(); } });
    document.body.append(d);
    paintIcons(d);
    d.showModal();
    const first = $("input:not([type=checkbox]):not([disabled]), textarea, select", body);
    if (o.focus !== false && first) setTimeout(() => { first.focus(); if (first.select) first.select(); }, 30);
  });
}
async function ask(title, label, value = "", opts = {}) {
  const i = input(value, { type: opts.secret ? "password" : "text", placeholder: opts.placeholder || "" });
  return modal({ title, sub: opts.sub, body: [field(label, i)], ok: opts.ok || "Aceptar",
                 onOk: () => {
                   if (!opts.allowEmpty && !i.value.trim()) throw new Error("Escribe algo");
                   return i.value;
                 } });
}
function confirmDlg(title, text, ok = "Eliminar", danger = true) {
  return modal({ title, sub: text, ok, danger });
}
/* Elige entre varias opciones. buttons: [{label, value, primary, danger}] → value o null */
function choose(title, text, buttons) {
  return new Promise(resolve => {
    const d = el("dialog", "dlg");
    d.append(el("h3", null, title));
    if (text) d.append(el("p", "muted sub", text));
    const menu = el("menu");
    let done = false;
    const c = btn("Cancelar");
    c.addEventListener("click", () => d.close());
    menu.append(c);
    for (const b of buttons) {
      const x = btn(b.label, { cls: (b.primary ? "primary" : "") + (b.danger ? " danger" : "") });
      x.addEventListener("click", () => { done = true; d.close(); resolve(b.value); });
      menu.append(x);
    }
    d.append(menu);
    d.addEventListener("close", () => { d.remove(); if (!done) resolve(null); });
    document.body.append(d);
    d.showModal();
    const prim = $(".primary", menu);
    if (prim) prim.focus();
  });
}

// ---------- menú contextual ----------
/* items: [{label, icon, action, danger, disabled, hint}] o "-" para separador */
function contextMenu(ev, items) {
  ev.preventDefault();
  ev.stopPropagation();
  const m = $("#ctx");
  m.replaceChildren();
  for (const it of items) {
    if (!it) continue;
    if (it === "-") { m.append(el("hr")); continue; }
    const b = el("button", "ctx-item" + (it.danger ? " danger" : ""));
    b.type = "button";
    b.disabled = !!it.disabled;
    b.append(it.icon ? icon(it.icon) : el("span", "ic-space"), el("span", "grow", it.label));
    if (it.hint) b.append(el("span", "ctx-hint", it.hint));
    b.addEventListener("click", () => { hideMenu(); it.action && it.action(); });
    m.append(b);
  }
  m.hidden = false;
  const r = m.getBoundingClientRect();
  const x = Math.min(ev.clientX, innerWidth - r.width - 6), y = Math.min(ev.clientY, innerHeight - r.height - 6);
  m.style.left = Math.max(4, x) + "px";
  m.style.top = Math.max(4, y) + "px";
  const first = $(".ctx-item:not(:disabled)", m);
  if (first) first.focus();
}
function hideMenu() { $("#ctx").hidden = true; }
document.addEventListener("mousedown", e => { if (!e.target.closest("#ctx")) hideMenu(); });
document.addEventListener("keydown", e => {
  const m = $("#ctx");
  if (m.hidden) return;
  if (e.key === "Escape") { hideMenu(); e.preventDefault(); return; }
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    const items = $$(".ctx-item:not(:disabled)", m);
    const i = items.indexOf(document.activeElement);
    const n = items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length];
    if (n) n.focus();
    e.preventDefault();
  }
}, true);
window.addEventListener("blur", hideMenu);

// ---------- tipos de archivo (iconos del SFTP, iguales a los de Nexo para Linux) ----------
const FILE_KINDS = {
  folder: ["folder-fill", "#e8b75a"], link: ["link-45deg", "#5fd4d4"], archive: ["file-earmark-zip", "#c8955c"],
  pdf: ["file-earmark-pdf", "#ff6b6b"], image: ["file-earmark-image", "#5fd49a"], video: ["file-earmark-play", "#ff7fc8"],
  audio: ["file-earmark-music", "#b18cff"], code: ["file-earmark-code", "#6cb6ff"], script: ["terminal-fill", "#8fd18a"],
  text: ["file-earmark-text", "#c8ced9"], sheet: ["file-earmark-spreadsheet", "#3ddc84"], doc: ["file-earmark-word", "#5b9bff"],
  slides: ["file-earmark-slides", "#ff8a2a"], key: ["file-earmark-lock", "#f2c66d"], db: ["database-fill", "#4fd8e0"],
  disk: ["disc", "#9aa7bd"], binary: ["file-earmark-binary", "#a3e635"], font: ["file-earmark-font", "#d7b4f8"],
  config: ["gear-fill", "#9fb3c8"], file: ["file-earmark", "#8a93a3"],
};
const FILE_EXT = {};
for (const [k, exts] of Object.entries({
  archive: "zip tar gz tgz bz2 tbz xz txz zst 7z rar lz lzma deb rpm apk jar war ear snap flatpak cab",
  pdf: "pdf", image: "png jpg jpeg gif svg webp bmp ico tif tiff heic avif psd xcf",
  video: "mp4 mkv avi mov webm wmv flv m4v mpg mpeg", audio: "mp3 wav flac ogg oga m4a aac opus wma",
  code: "py pyc js mjs cjs ts tsx jsx go rs c h cc cpp hpp cs java kt php rb pl lua swift dart scala r html htm css scss sass less vue svelte json jsonc xml yaml yml toml sql graphql proto tf hcl",
  script: "sh bash zsh fish ps1 psm1 bat cmd", text: "txt md rst log nfo readme", sheet: "xls xlsx xlsm ods csv tsv",
  doc: "doc docx odt rtf", slides: "ppt pptx odp", key: "pem key crt cer csr der pub p12 pfx jks kdbx gpg asc sig ppk",
  db: "db sqlite sqlite3 mdb accdb dump bak frm ibd", disk: "iso img qcow2 vmdk vdi vhd vhdx dmg",
  binary: "exe dll so bin elf o a msi appimage msix", font: "ttf otf woff woff2",
  config: "conf cfg ini env properties service socket timer rules",
})) exts.split(" ").forEach(e => (FILE_EXT[e] = k));
const FILE_NAMES = { dockerfile: "code", makefile: "code", authorized_keys: "key", known_hosts: "key", id_rsa: "key",
  id_ed25519: "key", id_ecdsa: "key", ".env": "config", ".bashrc": "script", ".zshrc": "script", ".profile": "script",
  crontab: "config", readme: "text", license: "text", changelog: "text" };
function fileKind(name, isDir, isLink) {
  if (isDir) return "folder";
  const low = name.toLowerCase();
  if (FILE_NAMES[low]) return FILE_NAMES[low];
  if (/\.tar\.(gz|xz|bz2|zst)$/.test(low)) return "archive";
  const dot = low.replace(/^\.+/, "").lastIndexOf(".");
  const ext = dot >= 0 ? low.replace(/^\.+/, "").slice(dot + 1) : "";
  return FILE_EXT[ext] || (isLink ? "link" : "file");
}
