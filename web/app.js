"use strict";
// mitsu-kkl live data page. Talks to its server only through web/API.md, so the PC server
// (mut_web.py) and a future Pico W firmware can both host it. No external libraries.

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------- texts (PL / EN) --
const TEXT = {
  en: {
    cable: "Cable", connect: "Connect", disconnect: "Disconnect", pids: "PIDs",
    pidsPh: "e.g. 07,14,20-2F", show: "Show", named: "Named PIDs", all: "All 00–BF",
    fault: "Fault codes", back: "Back to live data", format: "Format", hlChange: "Highlight change ≥",
    hlFor: "units, for", removeUnchanged: "Remove unchanged", resetMinMax: "Reset min/max",
    record: "● Record", stopRec: "■ Stop and save", recording: "Recording: {n} rows",
    colName: "Name", colValue: "Value", colConv: "Converted", colHl: "Highlights", colLast: "Last change",
    name: "Name", conversion: "Conversion", unit: "Unit", save: "Save", cancel: "Cancel",
    editTitle: "PID {p}: name and conversion", preview: "Now: {raw} → {conv}", noValue: "no value yet",
    convHelp: "Expression in x (raw byte 0–255), e.g. x*0.0733 · x*31.25 · x-40 · (x>>4)&15 · round(x*0.49, 1). " +
              "Keywords: dtc, dtc2 (fault code bits), bin (binary). Empty = no conversion.",
    convError: "error", noCodes: "no codes", codes: "codes: {c}",
    hint: "Double-click (or long-press) a row to give it a name and a conversion.",
    faultNote: "Fault codes: 40/41 active, 45/46 stored.",
    rejected: "Skipped (blocked or invalid): {l}", recStopped: "The PID list changed, the recording was saved.",
    reads: "{r} reads/s",
    st_idle: "Disconnected", st_opening: "Opening the cable…", st_connecting: "Connecting to the engine ECU…",
    st_no_response: "ECU not responding ({d}), retrying in 3 s. Pin 1 grounded? Ignition on?",
    st_connected: "Connected, ECU ID {id}{via}", via: " via {i}", st_lost: "Connection lost, reconnecting…",
    st_error: "Error: {d}", st_server: "No connection to the server, retrying…",
  },
  pl: {
    cable: "Kabel", connect: "Połącz", disconnect: "Rozłącz", pids: "PID-y",
    pidsPh: "np. 07,14,20-2F", show: "Pokaż", named: "PID-y z nazwą", all: "Wszystkie 00–BF",
    fault: "Kody usterek", back: "Powrót do odczytów", format: "Format", hlChange: "Podświetl zmianę ≥",
    hlFor: "jedn., przez", removeUnchanged: "Usuń niezmienne", resetMinMax: "Zeruj min/max",
    record: "● Nagrywaj", stopRec: "■ Zatrzymaj i zapisz", recording: "Nagrywanie: {n} wierszy",
    colName: "Nazwa", colValue: "Wartość", colConv: "Przeliczona", colHl: "Podświetlenia", colLast: "Ostatnia zmiana",
    name: "Nazwa", conversion: "Przelicznik", unit: "Jednostka", save: "Zapisz", cancel: "Anuluj",
    editTitle: "PID {p}: nazwa i przelicznik", preview: "Teraz: {raw} → {conv}", noValue: "brak odczytu",
    convHelp: "Wyrażenie z x (surowy bajt 0–255), np. x*0.0733 · x*31.25 · x-40 · (x>>4)&15 · round(x*0.49, 1). " +
              "Słowa: dtc, dtc2 (bity kodów usterek), bin (dwójkowo). Puste = bez przeliczenia.",
    convError: "błąd", noCodes: "brak kodów", codes: "kody: {c}",
    hint: "Kliknij dwukrotnie (albo przytrzymaj) wiersz, aby nadać mu nazwę i przelicznik.",
    faultNote: "Kody usterek: 40/41 aktywne, 45/46 zapamiętane.",
    rejected: "Pominięte (zablokowane lub błędne): {l}", recStopped: "Lista PID-ów się zmieniła, nagranie zapisano.",
    reads: "{r} odczytów/s",
    st_idle: "Rozłączono", st_opening: "Otwieranie kabla…", st_connecting: "Łączenie ze sterownikiem silnika…",
    st_no_response: "Sterownik nie odpowiada ({d}), ponowna próba za 3 s. Pin 1 na masie? Zapłon włączony?",
    st_connected: "Połączono, ID sterownika {id}{via}", via: ", przez {i}", st_lost: "Utracono połączenie, łączę ponownie…",
    st_error: "Błąd: {d}", st_server: "Brak połączenia z serwerem, ponawiam…",
  },
};
let lang = localStorage.getItem("lang") || ((navigator.language || "").toLowerCase().startsWith("pl") ? "pl" : "en");
const t = (key, args = {}) => (TEXT[lang][key] ?? key).replace(/\{(\w+)\}/g, (_, k) => args[k] ?? "");

// ------------------------------------------------------------------------ state --
const S = {
  info: null, defs: {}, dtc: new Map(), convs: new Map(), pids: [], rows: new Map(),
  status: { code: "idle" }, fmt: "HEX", sort: { key: null, desc: false },
  faultView: false, liveList: null, rec: null, note: "",
};
const FAULT_PIDS = ["40", "41", "45", "46"];

async function api(method, path, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

// ------------------------------------------------------------ conversions --
// Same language as kkl/piddefs.py, evaluated here so the server stays small (Pico).
function tokenize(src) {
  const re = /\s*(\d+\.?\d*|\.\d+|[A-Za-z_]\w*|\/\/|>>|[-+*/%&|^(),])/y;
  const out = [];
  let m;
  re.lastIndex = 0;
  while (re.lastIndex < src.length) {
    const start = re.lastIndex;
    if (!(m = re.exec(src))) {
      if (/^\s*$/.test(src.slice(start))) break;
      throw new Error(`unexpected '${src.slice(start).trim()[0]}'`);
    }
    out.push(m[1]);
  }
  return out;
}

function parseExpr(src) {
  const tok = tokenize(src);
  let i = 0;
  const peek = () => tok[i];
  const take = (x) => { if (tok[i] !== x) throw new Error(`expected '${x}'`); i++; };
  const int = (v) => { if (!Number.isInteger(v)) throw new Error("bit operator on a fraction"); return v; };
  const bin = (next, ops) => () => {
    let left = next();
    while (ops[peek()]) {
      const f = ops[tok[i++]], l = left, r = next();
      left = (x) => f(l(x), r(x));
    }
    return left;
  };
  const div = (a, b) => { if (b === 0) throw new Error("division by zero"); return a / b; };
  const FUNCS = {
    abs: (a) => Math.abs(a), min: (...a) => Math.min(...a), max: (...a) => Math.max(...a),
    round: (a, n = 0) => { const p = 10 ** n; return Math.round(a * p) / p; },
  };
  let orE;
  const primary = () => {
    const tk = tok[i++];
    if (tk === undefined) throw new Error("unexpected end");
    if (tk === "(") { const e = orE(); take(")"); return e; }
    if (/^[\d.]/.test(tk)) { const v = Number(tk); return () => v; }
    if (tk === "x") return (x) => x;
    if (FUNCS[tk]) {
      take("(");
      const args = [orE()];
      while (peek() === ",") { i++; args.push(orE()); }
      take(")");
      return (x) => FUNCS[tk](...args.map((a) => a(x)));
    }
    throw new Error(`unknown '${tk}'`);
  };
  const unary = () => {
    if (peek() === "-") { i++; const e = unary(); return (x) => -e(x); }
    if (peek() === "+") { i++; return unary(); }
    return primary();
  };
  const term = bin(unary, {
    "*": (a, b) => a * b, "/": div, "//": (a, b) => Math.floor(div(a, b)),
    "%": (a, b) => { if (b === 0) throw new Error("division by zero"); return a - b * Math.floor(a / b); },
  });
  const sum = bin(term, { "+": (a, b) => a + b, "-": (a, b) => a - b });
  const shift = bin(sum, { ">>": (a, b) => int(a) >> int(b) });
  const andE = bin(shift, { "&": (a, b) => int(a) & int(b) });
  const xorE = bin(andE, { "^": (a, b) => int(a) ^ int(b) });
  orE = bin(xorE, { "|": (a, b) => int(a) | int(b) });
  const e = orE();
  if (i < tok.length) throw new Error(`unexpected '${tok[i]}'`);
  e(1);  // catches most mistakes early, like the server does
  return e;
}

function fmtNum(v) {
  if (!Number.isFinite(v)) throw new Error("not a number");
  return Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/\.?0+$/, "");
}

function dtcCodes(v, base, withText) {
  const out = [];
  for (let b = 0; b < 8; b++) {
    if (!(v >> b & 1)) continue;
    const d = S.dtc.get(base + b);
    out.push(d ? (withText && d.desc ? `${d.code} ${d.desc}` : String(d.code)) : `bit ${base + b}`);
  }
  return out;
}

function compileConv(text) {
  text = (text || "").trim();
  if (!text) return null;
  const key = text.toLowerCase();
  if (key === "dtc" || key === "dtc2") {
    const base = key === "dtc" ? 0 : 8;
    return (v) => {
      const c = dtcCodes(v, base, S.faultView);
      return c.length ? (S.faultView ? c.join(", ") : t("codes", { c: c.join(", ") })) : t("noCodes");
    };
  }
  if (key === "bin") return (v) => v.toString(2).padStart(8, "0");
  let e;
  try {
    e = parseExpr(text);
  } catch (err) {
    const alt = text.replace(/(?<=\d),(?=\d)/g, ".");  // decimal comma: x*0,0733
    if (alt === text) throw err;
    e = parseExpr(alt);
  }
  return (v) => { try { return fmtNum(e(v)); } catch { return t("convError"); } };
}

function convFor(pid) {
  const d = S.defs[pid];
  if (!S.convs.has(pid)) {
    let f = null;
    try { f = compileConv(d?.conv); } catch { f = () => t("convError"); }
    S.convs.set(pid, f);
  }
  const f = S.convs.get(pid);
  return f ? (v) => { const s = f(v); return d?.unit && /\d$/.test(s) ? `${s} ${d.unit}` : s; } : null;
}

// ----------------------------------------------------------------------- table --
const fmtRaw = (v) => (v == null ? "–" : S.fmt === "HEX" ? v.toString(16).toUpperCase().padStart(2, "0") : String(v));
const clock = (ms) => (ms ? new Date(ms).toLocaleTimeString() : "");

function buildTable() {
  const body = document.querySelector("#tbl tbody");
  const old = S.rows;
  S.rows = new Map();
  body.textContent = "";
  for (const pid of S.pids) {
    const r = old.get(pid) || { pid, v: null, min: null, max: null, base: null, hl: 0, until: 0, last: 0 };
    if (!r.tr) {
      r.tr = document.createElement("tr");
      r.td = {};
      for (const k of ["pid", "name", "value", "conv", "min", "max", "hl", "last"]) {
        r.td[k] = r.tr.appendChild(document.createElement("td"));
        r.td[k].className = k;
      }
      r.tr.addEventListener("dblclick", () => openEdit(pid));
      let press;
      r.tr.addEventListener("touchstart", () => { press = setTimeout(() => openEdit(pid), 600); }, { passive: true });
      for (const ev of ["touchend", "touchmove", "touchcancel"]) r.tr.addEventListener(ev, () => clearTimeout(press));
    }
    S.rows.set(pid, r);
    body.appendChild(r.tr);
    renderRow(r);
  }
  applySort();
}

function renderRow(r) {
  const d = S.defs[r.pid];
  const conv = convFor(r.pid);
  r.td.pid.textContent = r.pid;
  r.td.name.textContent = d?.name || "";
  r.td.value.textContent = fmtRaw(r.v);
  r.td.conv.textContent = r.v != null && conv ? conv(r.v) : "";
  r.td.min.textContent = fmtRaw(r.min);
  r.td.max.textContent = fmtRaw(r.max);
  r.td.hl.textContent = r.hl || "";
  r.td.last.textContent = clock(r.last);
  r.tr.classList.toggle("hl", r.until > Date.now());
  r.tr.classList.toggle("noreply", r.v == null && r.seen);
}

function onValue(pid, v, now) {
  const r = S.rows.get(pid);
  if (!r) return;
  r.seen = true;
  if (v == null) { r.v = null; renderRow(r); return; }
  const threshold = Math.max(1, Number($("threshold").value) || 1);
  if (r.base == null) {
    r.base = r.min = r.max = v;
  } else {
    if (v !== r.v && r.v != null) r.last = now;
    if (Math.abs(v - r.base) >= threshold) {
      r.base = v;
      r.hl += 1;
      r.until = now + (Number($("hlSecs").value) || 3) * 1000;
    }
    r.min = Math.min(r.min, v);
    r.max = Math.max(r.max, v);
  }
  r.v = v;
  renderRow(r);
}

const SORT_KEYS = {
  pid: (r) => parseInt(r.pid, 16), name: (r) => (S.defs[r.pid]?.name || "").toLowerCase(),
  value: (r) => r.v ?? -1, conv: (r) => { const n = parseFloat(r.td.conv.textContent); return isNaN(n) ? r.td.conv.textContent : n; },
  min: (r) => r.min ?? -1, max: (r) => r.max ?? -1, hl: (r) => r.hl, last: (r) => r.last,
};

function applySort() {
  document.querySelectorAll("#tbl th").forEach((th) => {
    th.classList.toggle("sorted", th.dataset.k === S.sort.key);
    th.classList.toggle("desc", th.dataset.k === S.sort.key && S.sort.desc);
  });
  if (!S.sort.key) return;
  const key = SORT_KEYS[S.sort.key];
  const rows = [...S.rows.values()].sort((a, b) => {
    const x = key(a), y = key(b);
    const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
    return S.sort.desc ? -c : c;
  });
  const body = document.querySelector("#tbl tbody");
  for (const r of rows) body.appendChild(r.tr);
}

// ---------------------------------------------------------------- status / texts --
function renderStatus() {
  const st = S.status;
  const el = $("status");
  const via = st.iface ? t("via", { i: st.iface }) : "";
  el.textContent = st.code === "server" ? t("st_server") : t("st_" + st.code, { d: st.detail, id: st.ecu_id, via });
  el.className = "status " + ({ connected: "connected", no_response: "warn", lost: "warn", error: "err", server: "err" }[st.code] || "");
  const running = !["idle", "error", "server"].includes(st.code);
  const b = $("btnConn");
  b.textContent = running ? t("disconnect") : t("connect");
  b.disabled = st.code === "server";
  $("iface").disabled = running;
  if (!running) $("rate").textContent = "";
}

function applyTexts() {
  document.documentElement.lang = lang;
  $("lang").value = lang;
  document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  $("pidText").placeholder = t("pidsPh");
  $("btnFault").textContent = S.faultView ? t("back") : t("fault");
  $("btnRec").textContent = S.rec ? t("stopRec") : t("record");
  renderStatus();
  renderNote();
  S.convs.clear();
  S.rows.forEach(renderRow);
}

function renderNote() {
  $("note").textContent = [S.faultView ? t("faultNote") : t("hint"), S.note].filter(Boolean).join("  ·  ");
}

// ---------------------------------------------------------------- server events --
function applyPids(list) {
  S.pids = list;
  if (!S.faultView) $("pidText").value = compactPids(list);
  if (S.rec && S.rec.pids.join() !== list.join()) { stopRecording(); S.note = t("recStopped"); renderNote(); }
  buildTable();
}

function compactPids(list) {
  const n = list.map((p) => parseInt(p, 16));
  const out = [];
  for (let i = 0; i < n.length;) {
    let j = i;
    while (j + 1 < n.length && n[j + 1] === n[j] + 1) j++;
    const hx = (v) => v.toString(16).toUpperCase().padStart(2, "0");
    out.push(j - i >= 2 ? `${hx(n[i])}-${hx(n[j])}` : n.slice(i, j + 1).map(hx).join(","));
    i = j + 1;
  }
  return out.join(",");
}

function handle(msg) {
  const now = Date.now();
  switch (msg.type) {
    case "state":
      S.status = msg.status;
      renderStatus();
      applyPids(msg.pids);
      for (const [p, v] of Object.entries(msg.values)) if (v != null) onValue(p, v, now);
      break;
    case "status":
      S.status = msg;
      renderStatus();
      break;
    case "values":  // the browser's clock: the Pico has none
      for (const [p, v] of Object.entries(msg.v)) onValue(p, v, now);
      if (S.rec) recordRow(now);
      break;
    case "rate":
      $("rate").textContent = t("reads", { r: Math.round(msg.reads) });
      break;
    case "pids":
      applyPids(msg.pids);
      break;
    case "defs":
      loadDefs();
      break;
  }
}

async function loadDefs() {
  const d = await api("GET", "/api/defs");
  S.defs = d.pids;
  S.dtc = new Map(d.dtc.map((x) => [x.bit, x]));
  S.convs.clear();
  S.rows.forEach(renderRow);
}

function listen() {
  const es = new EventSource("/api/events");
  es.onmessage = (e) => handle(JSON.parse(e.data));
  es.onerror = () => { S.status = { code: "server" }; renderStatus(); };
  es.onopen = () => loadDefs().catch(() => {});
}

// ----------------------------------------------------------------------- actions --
async function setPids(body) {
  try {
    const r = await api("POST", "/api/pids", body);
    S.note = r.rejected.length ? t("rejected", { l: r.rejected.join(", ") }) : "";
  } catch (e) {
    S.note = e.message;
  }
  renderNote();
}

function showLive(text) {
  if (S.faultView) { S.faultView = false; S.convs.clear(); applyTexts(); }
  setPids({ text });
}

function toggleFault() {
  S.faultView = !S.faultView;
  S.convs.clear();
  if (S.faultView) {
    S.liveList = S.pids.slice();
    setPids({ pids: FAULT_PIDS, temporary: true });
  } else {
    setPids({ pids: S.liveList || [] });
  }
  applyTexts();
}

// -------------------------------------------------------------------- recording --
function startRecording() {
  const cols = [];
  for (const p of S.pids) {
    const d = S.defs[p] || {};
    const label = [p, d.name].filter(Boolean).join(" ");
    cols.push({ p, head: label, conv: false });
    if (convFor(p)) cols.push({ p, head: `${label} [${d.unit || "conv"}]`, conv: true });
  }
  S.rec = { pids: S.pids.slice(), cols, t0: Date.now(), rows: [] };
  $("btnRec").classList.add("on");
  applyTexts();
}

function recordRow(ms) {
  const R = S.rec;
  const row = [new Date(ms).toISOString(), ((ms - R.t0) / 1000).toFixed(3)];
  for (const c of R.cols) {
    const v = S.rows.get(c.p)?.v;
    convFor(c.p);  // makes sure S.convs holds the compiled conversion
    row.push(v == null ? "" : c.conv ? S.convs.get(c.p)(v) : v);  // no unit: it is in the header, Excel wants numbers
  }
  R.rows.push(row);
  $("recInfo").textContent = t("recording", { n: R.rows.length });
}

function stopRecording() {
  const R = S.rec;
  S.rec = null;
  $("btnRec").classList.remove("on");
  $("recInfo").textContent = "";
  applyTexts();
  if (!R || !R.rows.length) return;
  const q = (s) => (/[",\n]/.test(String(s)) ? `"${String(s).replace(/"/g, '""')}"` : String(s));
  const lines = [["time", "t [s]", ...R.cols.map((c) => c.head)], ...R.rows].map((r) => r.map(q).join(","));
  const blob = new Blob(["﻿" + lines.join("\r\n") + "\r\n"], { type: "text/csv" });
  const stamp = new Date(R.t0).toISOString().replace(/[-:]/g, "").replace("T", "-").slice(0, 15);
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `${stamp}_readings.csv` });
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

// -------------------------------------------------------------------- edit dialog --
let editPid = null;

function openEdit(pid) {
  editPid = pid;
  const d = S.defs[pid] || {};
  $("editTitle").textContent = t("editTitle", { p: pid });
  $("edName").value = d.name || "";
  $("edConv").value = d.conv || "";
  $("edUnit").value = d.unit || "";
  updatePreview();
  $("dlgEdit").showModal();
}

function updatePreview() {
  const v = S.rows.get(editPid)?.v;
  $("edError").textContent = "";
  $("edSave").disabled = false;
  let f;
  try {
    f = compileConv($("edConv").value);
  } catch (e) {
    $("edError").textContent = e.message;
    $("edSave").disabled = true;
    $("edPreview").textContent = "";
    return;
  }
  const unit = $("edUnit").value;
  $("edPreview").textContent = v == null ? t("noValue")
    : t("preview", { raw: `${fmtRaw(v)} (${v})`, conv: f ? `${f(v)}${unit ? " " + unit : ""}` : "–" });
}

async function saveEdit() {
  try {
    await api("PUT", "/api/defs", { pid: editPid, name: $("edName").value, conv: $("edConv").value, unit: $("edUnit").value });
    $("dlgEdit").close();
  } catch (e) {
    $("edError").textContent = e.message;
  }
}

// -------------------------------------------------------------------------- setup --
async function init() {
  $("lang").addEventListener("change", (e) => { lang = e.target.value; localStorage.setItem("lang", lang); applyTexts(); });
  $("btnConn").addEventListener("click", () => {
    const running = !["idle", "error", "server"].includes(S.status.code);
    api("POST", running ? "/api/disconnect" : "/api/connect", running ? {} : { iface: $("iface").value || undefined })
      .catch((e) => { S.note = e.message; renderNote(); });
  });
  $("btnApply").addEventListener("click", () => showLive($("pidText").value));
  $("pidText").addEventListener("keydown", (e) => { if (e.key === "Enter") showLive($("pidText").value); });
  $("btnNamed").addEventListener("click", () =>
    showLive(Object.entries(S.defs).filter(([, d]) => d.name).map(([p]) => p).join(",")));
  $("btnAll").addEventListener("click", () => showLive("00-BF"));
  $("btnFault").addEventListener("click", toggleFault);
  document.querySelectorAll("input[name=fmt]").forEach((el) =>
    el.addEventListener("change", () => { S.fmt = el.value; S.rows.forEach(renderRow); }));
  $("btnUnchanged").addEventListener("click", () =>
    setPids({ pids: S.pids.filter((p) => { const r = S.rows.get(p); return r && r.min != null && r.min !== r.max; }) }));
  $("btnReset").addEventListener("click", () => S.rows.forEach((r) => {
    Object.assign(r, { min: r.v, max: r.v, base: r.v, hl: 0, until: 0, last: 0 });
    renderRow(r);
  }));
  $("btnRec").addEventListener("click", () => (S.rec ? stopRecording() : startRecording()));
  document.querySelectorAll("#tbl th").forEach((th) => th.addEventListener("click", () => {
    S.sort = { key: th.dataset.k, desc: S.sort.key === th.dataset.k ? !S.sort.desc : false };
    applySort();
  }));
  for (const id of ["edConv", "edUnit"]) $(id).addEventListener("input", updatePreview);
  $("formEdit").addEventListener("submit", (e) => {
    if (e.submitter?.value === "save") { e.preventDefault(); saveEdit(); }
  });
  setInterval(() => {  // end highlights on time
    const now = Date.now();
    S.rows.forEach((r) => { if (r.tr.classList.contains("hl") && r.until <= now) r.tr.classList.remove("hl"); });
  }, 200);

  applyTexts();
  try {
    S.info = await api("GET", "/api/info");
    $("ver").textContent = S.info.version;
    const sel = $("iface");
    sel.textContent = "";
    for (const i of S.info.ifaces) sel.appendChild(new Option(i.label, i.key, false, i.key === S.info.iface));
    $("ifaceBox").hidden = S.info.server !== "pc" || S.info.ifaces.length < 2;
    await loadDefs();
  } catch (e) {
    S.note = e.message;
  }
  listen();
}

init();
