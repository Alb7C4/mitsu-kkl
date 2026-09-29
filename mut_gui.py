#!/usr/bin/env python3
"""MUT-II live viewer for the engine ECU (5-baud 0x00 @ 15625) with change highlighting.

  pythonw mut_gui.py --connect                             # interface picked in the window
  pythonw mut_gui.py --port COM5                           # override: any chip via its COM port
  python mut_gui.py --backend sim --sim mutlive --connect  # offline demo

The watched PIDs with their names and optional conversions live in a definitions file
(default pid_definitions.csv, or an existing pid_definicje.csv; format in kkl/piddefs.py). It is saved on every change and
re-read when it is edited outside the program.

Read-only: requests are limited to proto.MUT_ALLOWED (0x00-0xBF, 0xFD-0xFF).
Highlight rule: a row lights up when its value has moved by >= threshold units since the
value at its previous highlight (or the first reading), so slow drifts are caught too.
"""

import argparse
import csv
import datetime
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from kkl import __version__, dtcdefs, proto
from kkl.update import check_latest
from kkl.welcome import WelcomeWindow, system_language
from kkl.interfaces import AUTO, Iface, cli_key, list_interfaces, open_interface
from kkl.link import KLine, hires_timer, now
from kkl.profiles import load_profiles, save_profiles
from kkl.piddefs import CONV_ERROR, DEFAULTS, PidDef, compile_conversion, format_pids, load_defs, parse_pids, save_defs

# Next to the .exe when frozen by PyInstaller (not its temp dir), so files survive restarts.
HERE = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
SETTINGS = HERE / "mut_gui.json"
DEFS_DEFAULT = HERE / "pid_definitions.csv"
DEFS_LEGACY = HERE / "pid_definicje.csv"  # default name before the English UI; still used if it exists
DTC_DEFS = HERE / "dtc_definitions.csv"   # fault code bit -> code number -> description
PROFILES = HERE / "pid_profiles.csv"      # named PID lists
FIRST_LIST = "07,14,15,17,21,3A,40,45"
DTC_LIST = (0x40, 0x41, 0x45, 0x46)
BTN_LIVE, BTN_BACK = "Show selected live Data PIDs", "Back to Live Data PID"
FILETYPES = [("PID definitions", "*.csv"), ("PID list", "*.txt"), ("All files", "*.*")]
CONV_HELP = ("Expression in x (raw byte 0–255), e.g. x*0.0733 · x*31.25 · x-40 · (x>>4)&15 · "
             "round(x*0.49, 1). Keywords: dtc, dtc2 (fault code bits), bin (binary). "
             "Empty = no conversion.")


def _default_defs():
    return DEFS_LEGACY if not DEFS_DEFAULT.exists() and DEFS_LEGACY.exists() else DEFS_DEFAULT


class NullLog:
    """KLine needs a logger; a byte-level log at ~150 requests/s would be huge."""

    def ev(self, *args, **kwargs):
        pass


class Poller(threading.Thread):
    """Owns the interface: connects, polls the PID list in a loop, reconnects."""

    def __init__(self, open_dev, pids, out):
        super().__init__(daemon=True)
        self.open_dev, self.out = open_dev, out
        self.stop_ev = threading.Event()
        self.lock = threading.Lock()
        self._pids = list(pids)

    def set_pids(self, pids):
        with self.lock:
            self._pids = list(pids)

    def _status(self, text):
        self.out.put(("status", text))

    def run(self):
        try:
            dev = self.open_dev()
        except Exception as e:
            self.out.put(("fatal", f"Cannot open interface: {e}"))
            self.out.put(("stopped", None))
            return
        self.out.put(("iface", getattr(dev, "label", "")))
        kl = KLine(dev, NullLog())
        hires_timer(True)
        try:
            kl.setup(15625, 1)
            while not self.stop_ev.is_set():
                self._status("Connecting (5-baud 0x00 @ 15625)...")
                res = proto.mut(kl, NullLog(), addr=0x00, baud=15625, queries=proto.MUT_ID_QUERIES)
                if res["outcome"] != "DATA":
                    self._status(f"ECU not responding ({res['outcome']}), retrying in 3 s. Pin 1 grounded? Ignition on?")
                    self.stop_ev.wait(3.0)
                    continue
                self.out.put(("connected", "".join(q["resp"] for q in res["queries"])))
                self._poll(kl)
                if not self.stop_ev.is_set():
                    self._status("Session lost, reconnecting in 2 s...")
                    self.stop_ev.wait(2.0)
        except Exception as e:
            self.out.put(("fatal", f"Interface error: {type(e).__name__}: {e}"))
        finally:
            try:
                dev.close()
            except Exception:
                pass
            hires_timer(False)
            self.out.put(("stopped", None))

    def _poll(self, kl):
        misses, count, t_rate = 0, 0, now()
        while not self.stop_ev.is_set():
            with self.lock:
                pids = list(self._pids)
            keepalive = not pids
            if keepalive:
                pids = [0xFE]  # keep the session alive with an empty list
            t_cycle, wall = now(), time.time()
            cycle = {}
            for pid in pids:
                if self.stop_ev.is_set():
                    return
                v = self._query(kl, pid)
                self.out.put(("val", pid, v))
                cycle[pid] = v
                misses = 0 if v is not None else misses + 1
                if misses >= 8:
                    return
                count += 1
            if not keepalive:
                self.out.put(("cycle", wall, cycle))  # one complete pass, for the readings log
            kl.trim()
            t = now()
            if t - t_rate >= 1.0:
                self.out.put(("rate", count / (t - t_rate), t - t_cycle))
                count, t_rate = 0, t

    @staticmethod
    def _query(kl, pid):
        """One MUT request: the K-line echoes our byte, then the ECU sends one value byte."""
        proto.check_mut(pid)
        kl.discard()
        kl.write([pid])
        got = kl.read_n(2, 0.15)
        if len(got) == 2 and got[0][1] == pid:
            return got[1][1]
        return None


class App:
    COLS = (("pid", "PID", 50), ("name", "Name", 200), ("value", "Value", 70),
            ("phys", "Converted", 130), ("min", "Min", 55), ("max", "Max", 55),
            ("changes", "Highlights", 85), ("last", "Last change", 110))

    def __init__(self, root, cli_iface=None):
        self.root = root
        self.q = queue.Queue()
        self.poller = None
        self.rows = {}
        self.defs, self.keep, self.convs = {}, [], {}
        self.defs_path, self.defs_mtime = DEFS_DEFAULT, None
        self._last_file_check = 0.0
        self.picker, self._picker_refill = None, None
        self._menu_row = None
        self.csv_file = self.csv = None
        self.rec_on, self.rec_file, self.rec_csv, self.rec_path = False, None, None, None
        self.rec_header, self.rec_stamp, self.rec_t0, self.rec_rows, self.rec_part = None, "", None, 0, 0
        self.rec_no, self.dtc_mtime = 0, None
        s = self._load_settings()
        self.fmt = tk.StringVar(value=s.get("fmt", "HEX"))
        self.threshold = tk.StringVar(value=str(s.get("threshold", 1)))
        self.hl_secs = tk.StringVar(value=str(s.get("hl_secs", 3)))
        self.pid_text = tk.StringVar()
        self.status = tk.StringVar(value="Disconnected")
        self.info = tk.StringVar(value="")
        self.note = tk.StringVar(value="")
        self.file_label = tk.StringVar(value="")
        self.rec_label = tk.StringVar(value="Readings log: off")
        self.live_sort = tk.BooleanVar(value=s.get("live_sort", False))
        self.sort_col, self.sort_desc = s.get("sort_col"), s.get("sort_desc", False)
        self.iface_var = tk.StringVar()
        self.iface_keys = {}  # combobox label -> interface key
        self.saved_iface = s.get("iface", AUTO)
        self.iface_used = ""
        self.ecu_id = None
        self.view_dtc = False  # fault-codes view: shows DTC_LIST, leaves the live-data list alone
        self.prof_var = tk.StringVar()
        self.profiles, self.prof_keep, self.prof_mtime = {}, [], None
        self._last_sort = 0.0
        self.check_updates = s.get("check_updates", True)
        self.welcome, self.welcome_hidden = None, s.get("welcome_hidden_version", "")
        root.title(f"MUT-II live data: Eclipse 4G63 – mitsu-kkl {__version__}")
        root.geometry(s.get("geometry", "940x600"))
        self._build()
        self.refresh_ifaces(cli_iface or self.saved_iface)
        # "pids" is the pre-definitions-file setting; it seeds a newly created file
        dtc_problems = self._load_dtc_defs()
        prof_problems = self._load_profiles(select=s.get("profile", ""))
        self._open_defs(Path(s.get("defs_path") or _default_defs()), first_list=s.get("pids", FIRST_LIST))
        if dtc_problems:
            self.note.set(self.note.get() + f"  {DTC_DEFS.name}: " + "; ".join(dtc_problems[:3]))
        if prof_problems:
            self.note.set(self.note.get() + f"  {PROFILES.name}: " + "; ".join(prof_problems[:3]))
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(50, self._tick)
        if self.check_updates:
            threading.Thread(target=lambda: self.q.put(("update", check_latest())), daemon=True).start()
        if self.welcome_hidden != __version__:  # "don't show again" only holds for the version it was ticked in
            root.after(300, self.show_welcome)

    # -- layout ----------------------------------------------------------------------
    def _build(self):
        pad = {"padx": 4, "pady": 3}
        iff = self.first_bar = ttk.Frame(self.root)
        iff.pack(fill="x", **pad)
        ttk.Label(iff, text="Interface:").pack(side="left")
        self.cb_iface = ttk.Combobox(iff, textvariable=self.iface_var, state="readonly", width=52)
        self.cb_iface.pack(side="left", padx=4)
        self.btn_refresh = ttk.Button(iff, text="Refresh", command=lambda: self.refresh_ifaces(announce=True))
        self.btn_refresh.pack(side="left")
        ttk.Label(iff, text="Cable with a non-FTDI chip (CH340, PL2303…): pick its COM port.",
                  foreground="#555555").pack(side="left", padx=8)

        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)
        self.btn_conn = ttk.Button(top, text="Connect", command=self.connect)
        self.btn_conn.pack(side="left")
        self.btn_disc = ttk.Button(top, text="Disconnect", command=self.disconnect, state="disabled")
        self.btn_disc.pack(side="left", padx=4)
        self.btn_rec = ttk.Button(top, text="● Record log", command=self.toggle_record, width=17)
        self.btn_rec.pack(side="left", padx=(8, 0))
        ttk.Label(top, textvariable=self.status, width=52).pack(side="left", padx=6)
        ttk.Label(top, textvariable=self.info).pack(side="right")

        pidf = ttk.Frame(self.root)
        pidf.pack(fill="x", **pad)
        ttk.Label(pidf, text="PIDs (hex, e.g. 07,14,20-2F):").pack(side="left")
        entry = ttk.Entry(pidf, textvariable=self.pid_text, width=40)
        entry.pack(side="left", padx=4)
        entry.bind("<Return>", lambda e: self.apply_pids())
        self.btn_live = ttk.Button(pidf, text=BTN_LIVE, width=len(BTN_LIVE), command=self.apply_pids)
        self.btn_live.pack(side="left")
        self.btn_dtc = ttk.Button(pidf, text="Fault Codes", command=self.show_fault_codes)
        self.btn_dtc.pack(side="left", padx=2)
        ttk.Button(pidf, text="Named PIDs", command=self.preset_known).pack(side="left", padx=(12, 2))
        ttk.Button(pidf, text="All 00-BF",
                   command=lambda: self._preset(range(0x00, 0xC0), "all 00-BF")).pack(side="left", padx=2)

        prf = ttk.Frame(self.root)
        prf.pack(fill="x", **pad)
        ttk.Label(prf, text="Profile:").pack(side="left")
        self.cb_prof = ttk.Combobox(prf, textvariable=self.prof_var, state="readonly", width=32)
        self.cb_prof.pack(side="left", padx=4)
        self.cb_prof.bind("<<ComboboxSelected>>", lambda e: self._profile_selected())
        ttk.Button(prf, text="Load", command=self.profile_load).pack(side="left", padx=2)
        ttk.Button(prf, text="Save", command=self.profile_save).pack(side="left", padx=2)
        ttk.Button(prf, text="Save as new…", command=self.profile_save_new).pack(side="left", padx=2)
        ttk.Button(prf, text="Edit…", command=self.profile_edit).pack(side="left", padx=2)
        ttk.Button(prf, text="Delete", command=self.profile_delete).pack(side="left", padx=2)
        ttk.Label(prf, text="Profiles store PID lists; Save / Save as new take the current list.",
                  foreground="#555555").pack(side="left", padx=8)

        opt = ttk.Frame(self.root)
        opt.pack(fill="x", **pad)
        ttk.Label(opt, text="Format:").pack(side="left")
        for f in ("HEX", "DEC"):
            ttk.Radiobutton(opt, text=f, value=f, variable=self.fmt, command=self._render_all).pack(side="left")
        ttk.Label(opt, text="   Highlight when the value changes by ≥").pack(side="left")
        ttk.Spinbox(opt, from_=1, to=255, width=5, textvariable=self.threshold).pack(side="left", padx=3)
        ttk.Label(opt, text="units, for").pack(side="left")
        ttk.Spinbox(opt, from_=0.5, to=60, increment=0.5, width=5, textvariable=self.hl_secs).pack(side="left", padx=3)
        ttk.Label(opt, text="s").pack(side="left")

        lst = ttk.Frame(self.root)
        lst.pack(fill="x", **pad)
        ttk.Label(lst, text="List:").pack(side="left")
        ttk.Button(lst, text="Add PID…", command=self.open_picker).pack(side="left", padx=2)
        ttk.Button(lst, text="Remove unchanged", command=self.remove_unchanged).pack(side="left", padx=2)
        ttk.Button(lst, text="Remove highlighted", command=self.remove_highlighted).pack(side="left", padx=2)
        ttk.Button(lst, text="Reset min/max", command=self.reset_stats).pack(side="left", padx=2)
        ttk.Checkbutton(lst, text="Live sort (click a column header to sort)",
                        variable=self.live_sort).pack(side="right")

        fil = ttk.Frame(self.root)
        fil.pack(fill="x", **pad)
        ttk.Label(fil, text="Definitions file:").pack(side="left")
        ttk.Label(fil, textvariable=self.file_label, foreground="#1f4e8c").pack(side="left", padx=4)
        ttk.Button(fil, text="Load…", command=self.load_file).pack(side="left", padx=2)
        ttk.Button(fil, text="Save as…", command=self.save_as).pack(side="left", padx=2)
        ttk.Button(fil, text="Edit in Notepad", command=self.edit_file).pack(side="left", padx=2)
        ttk.Button(fil, text="Edit fault code definitions",
                   command=lambda: self.edit_file(DTC_DEFS)).pack(side="left", padx=(12, 2))
        ttk.Button(fil, text="About…", command=self.show_welcome).pack(side="right", padx=2)
        ttk.Button(fil, text="Logs folder", command=self.open_logs).pack(side="right", padx=2)
        ttk.Label(fil, textvariable=self.rec_label, foreground="#8c1f1f").pack(side="right", padx=6)

        tf = ttk.Frame(self.root)
        tf.pack(fill="both", expand=True, **pad)
        self.tree = ttk.Treeview(tf, columns=[c[0] for c in self.COLS], show="headings", selectmode="extended")
        for key, title, width in self.COLS:
            self.tree.heading(key, text=title, command=lambda k=key: self.sort_by(k))
            anchor = "w" if key in ("name", "phys") else "center"
            self.tree.column(key, width=width, anchor=anchor, stretch=key in ("name", "phys"))
        self.tree.tag_configure("hl", background="#ffd84d")
        self.tree.tag_configure("noreply", foreground="#999999")
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Remove from list", command=self.remove_selected)
        self.menu.add_command(label="Edit name and conversion…", command=lambda: self.edit_def(self._menu_row))
        self.menu.add_separator()
        self.menu.add_command(label="Add PID…", command=self.open_picker)
        self.tree.bind("<Button-3>", self._context_menu)
        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<Delete>", lambda e: self.remove_selected())
        self.tree.bind("<Insert>", lambda e: self.open_picker())

        ttk.Label(self.root, textvariable=self.note, foreground="#555555").pack(fill="x", **pad)

    # -- settings ----------------------------------------------------------------------
    def _load_settings(self):
        try:
            return json.loads(SETTINGS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_settings(self):
        iface = self._iface_key()
        s = {"fmt": self.fmt.get(), "threshold": self.threshold.get(), "hl_secs": self.hl_secs.get(),
             "defs_path": str(self.defs_path), "geometry": self.root.geometry(),
             "live_sort": self.live_sort.get(), "sort_col": self.sort_col, "sort_desc": self.sort_desc,
             # a simulator chosen on the command line must not become the default interface
             "iface": self.saved_iface if iface.startswith("sim:") else iface,
             "profile": self.prof_var.get(), "check_updates": self.check_updates,
             "welcome_hidden_version": self.welcome_hidden}
        try:
            SETTINGS.write_text(json.dumps(s, indent=1), encoding="utf-8")
        except OSError:
            pass

    # -- interface ---------------------------------------------------------------------
    def _iface_key(self):
        return self.iface_keys.get(self.iface_var.get(), AUTO)

    def refresh_ifaces(self, want=None, announce=False):
        """Re-scan FTDI devices and COM ports, keeping (or restoring) the chosen interface."""
        want = want or self._iface_key()
        found = list_interfaces()
        if want not in {i.key for i in found}:
            kind, _, arg = want.partition(":")
            found.append(Iface(want, f"Simulator ({arg})" if kind == "sim" else f"{arg or want} – not detected"))
        self.iface_keys = {i.label: i.key for i in found}
        self.cb_iface.configure(values=[i.label for i in found])
        self.iface_var.set(next(i.label for i in found if i.key == want))
        if announce:
            real = [i.label for i in found if i.key != AUTO and not i.label.endswith("not detected")]
            self.note.set("Detected interfaces: " + ("; ".join(real) if real else "none. Plug in the cable and click Refresh."))

    def _num(self, var, default, cast, minimum):
        try:
            return max(cast(var.get().replace(",", ".")), minimum)
        except ValueError:
            return default

    # -- definitions file -----------------------------------------------------------------
    def _open_defs(self, path, first_list=FIRST_LIST):
        """Make `path` the current definitions file (created with defaults if missing)."""
        path = Path(path)
        if not path.exists():
            path = _default_defs()
        problems, created, legacy = [], not path.exists(), False
        if created:
            defs = {d.pid: PidDef(d.pid, d.name, d.conv, d.unit) for d in DEFAULTS}
            for p in parse_pids(first_list)[0]:
                defs.setdefault(p, PidDef(p)).active = True
            keep = []
        else:
            try:
                defs, problems, keep, legacy = load_defs(path)
            except (OSError, UnicodeDecodeError) as e:
                self.note.set(f"Cannot load {path.name}: {e}")
                return False
        self.defs_path, self.defs, self.keep = path, defs, keep
        self.convs = {}
        for p in defs:
            self._compile(p)
        if created or legacy:  # legacy: a file from the Polish version, rewrite it in English
            self._save_defs()
        else:
            self._remember_mtime()
        self.file_label.set(str(path.name))
        self._rebuild()
        msg = f"{'Created' if created else 'Loaded'} {path.name}: {len(self._active())} PIDs on the list."
        if problems:
            msg += f"  Notes ({len(problems)}): " + "; ".join(problems[:3]) + ("…" if len(problems) > 3 else "")
        self.note.set(msg)
        return True

    def _compile(self, pid):
        d = self.defs.get(pid)
        try:
            self.convs[pid] = compile_conversion(d.conv) if d else None
        except ValueError:
            self.convs[pid] = "conversion error"

    def _remember_mtime(self):
        try:
            self.defs_mtime = self.defs_path.stat().st_mtime_ns
        except OSError:
            self.defs_mtime = None

    def _save_defs(self):
        try:
            save_defs(self.defs_path, self.defs, self.keep)
        except OSError as e:
            self.note.set(f"Cannot save {self.defs_path.name}: {e}")
            return False
        self._remember_mtime()
        return True

    def _check_file(self):
        """Re-read the definitions file when it was changed outside the program."""
        try:
            mtime = self.defs_path.stat().st_mtime_ns
        except OSError:
            mtime = None
        if mtime is not None and self.defs_mtime is not None and mtime != self.defs_mtime:
            if self._open_defs(self.defs_path):
                self.note.set(f"{self.defs_path.name} changed on disk, reloaded. " + self.note.get())
        try:
            prof_mtime = PROFILES.stat().st_mtime_ns
        except OSError:
            prof_mtime = None
        if prof_mtime is not None and self.prof_mtime is not None and prof_mtime != self.prof_mtime:
            problems = self._load_profiles()
            self.note.set(f"{PROFILES.name} changed on disk, reloaded."
                          + (" Problems: " + "; ".join(problems[:3]) if problems else ""))
        try:
            dtc_mtime = DTC_DEFS.stat().st_mtime_ns
        except OSError:
            return
        if self.dtc_mtime is not None and dtc_mtime != self.dtc_mtime:
            problems = self._load_dtc_defs()
            self._render_all()
            self.note.set(f"{DTC_DEFS.name} changed on disk, reloaded."
                          + (" Problems: " + "; ".join(problems[:3]) if problems else ""))

    def _load_dtc_defs(self):
        """Fault code descriptions for the dtc/dtc2 conversions (file created with defaults if missing)."""
        try:
            problems = dtcdefs.load(DTC_DEFS)
            self.dtc_mtime = DTC_DEFS.stat().st_mtime_ns
        except (OSError, UnicodeDecodeError) as e:
            return [f"cannot read it: {e}"]
        return problems

    def load_file(self):
        path = filedialog.askopenfilename(title="Load PID definitions", initialdir=self.defs_path.parent,
                                          filetypes=FILETYPES)
        if path:
            self._open_defs(Path(path))

    def save_as(self):
        path = filedialog.asksaveasfilename(title="Save PID definitions as", initialdir=self.defs_path.parent,
                                            initialfile=self.defs_path.name, defaultextension=".csv",
                                            filetypes=FILETYPES)
        if not path:
            return
        self.defs_path = Path(path)
        if self._save_defs():
            self.file_label.set(self.defs_path.name)
            self.note.set(f"Saved to {path}. This is now the current definitions file.")

    def edit_file(self, path=None):
        path = path or self.defs_path
        try:
            subprocess.Popen(["notepad.exe", str(path)])
        except OSError as e:
            self.note.set(f"Cannot start Notepad: {e}")
            return
        self.note.set(f"Changes to {path.name} saved in Notepad are loaded automatically.")

    # -- list -----------------------------------------------------------------------
    def _active(self):
        return [p for p in sorted(self.defs) if self.defs[p].active]

    def _new_row(self):
        return {"v": None, "min": None, "max": None, "ref": None, "hl_until": 0.0,
                "hl_on": False, "changes": 0, "last": "", "seen": False}

    def _rebuild(self):
        shown = list(DTC_LIST) if self.view_dtc else self._active()
        old = self.rows
        self.rows = {p: old.get(p) or self._new_row() for p in shown}
        self.tree.delete(*self.tree.get_children())
        for p in shown:
            self.tree.insert("", "end", iid=str(p))
            self._render(p)
        if self.poller:
            self.poller.set_pids(shown)
        if not self.view_dtc:  # while fault codes are shown the field keeps the live-data list
            self.pid_text.set(format_pids(shown))
        self._apply_sort()
        if self._picker_refill:
            self._picker_refill()

    def _after_change(self):
        for p in self.defs:
            if p not in self.convs:
                self._compile(p)
        self._set_view(False)  # list edits always concern the live-data list
        self._save_defs()
        self._rebuild()

    def _set_view(self, dtc):
        self.view_dtc = dtc
        self.btn_live.configure(text=BTN_BACK if dtc else BTN_LIVE)
        self.btn_dtc.configure(state="disabled" if dtc else "normal")

    def show_fault_codes(self):
        for p in DTC_LIST:  # rows need a definition; the defaults bring the dtc/dtc2 decoding
            if p not in self.defs:
                d = next((d for d in DEFAULTS if d.pid == p), PidDef(p))
                self.defs[p] = PidDef(p, d.name, d.conv, d.unit)
                self._compile(p)
        self._set_view(True)
        self._rebuild()
        self.note.set(f"Fault codes: 40/41 = active, 45/46 = stored; descriptions come from {DTC_DEFS.name}. "
                      f"“{BTN_BACK}” returns to your PID list.")

    def _dtc_view_blocks(self):
        if self.view_dtc:
            self.note.set(f"The fault codes view has a fixed list. Click “{BTN_BACK}” to edit your PID list.")
        return self.view_dtc

    def _set_active(self, pids):
        pids = set(pids)
        for p in pids:
            self.defs.setdefault(p, PidDef(p))
        for p, d in self.defs.items():
            d.active = p in pids
        self._after_change()

    def _add(self, pids):
        for p in pids:
            proto.check_mut(p)
            self.defs.setdefault(p, PidDef(p)).active = True
        self._after_change()

    def _remove(self, pids):
        for p in pids:
            if p in self.defs:
                self.defs[p].active = False
        self._after_change()

    def apply_pids(self):
        pids, rejected = parse_pids(self.pid_text.get())
        self._set_active(pids)
        msg = f"{len(self.rows)} PIDs on the list."
        if rejected:
            msg += f" Skipped {len(rejected)} (blocked or invalid): {', '.join(rejected[:8])}"
            msg += "…" if len(rejected) > 8 else ""
        self.note.set(msg)

    def _preset(self, pids, label):
        self._set_active(pids)
        self.note.set(f"List: {label} ({len(self.rows)} PIDs).")

    def preset_known(self):
        self._preset([p for p in self.defs if self.defs[p].name], "PIDs named in the definitions file")

    # -- PID list profiles ------------------------------------------------------------------
    def _load_profiles(self, select=None):
        """(Re)read pid_profiles.csv (created with examples if missing); keeps or sets the selection."""
        try:
            self.profiles, problems, self.prof_keep = load_profiles(PROFILES)
            self.prof_mtime = PROFILES.stat().st_mtime_ns
        except (OSError, UnicodeDecodeError) as e:
            self.profiles, self.prof_keep, problems = {}, [], [f"cannot read it: {e}"]
        self.cb_prof.configure(values=list(self.profiles))
        want = self.prof_var.get() if select is None else select
        self.prof_var.set(want if want in self.profiles else "")
        return problems

    def _save_profiles(self):
        try:
            save_profiles(PROFILES, self.profiles, self.prof_keep)
            self.prof_mtime = PROFILES.stat().st_mtime_ns
        except OSError as e:
            self.note.set(f"Cannot save {PROFILES.name}: {e}")
            return False
        self.cb_prof.configure(values=list(self.profiles))
        return True

    def _selected_profile(self):
        name = self.prof_var.get()
        if name not in self.profiles:
            self.note.set("Pick a profile in the Profile list first.")
            return None
        return name

    def _profile_selected(self):
        name = self.prof_var.get()
        pids = self.profiles.get(name, [])
        self.note.set(f"Profile “{name}”: {len(pids)} PIDs ({format_pids(pids) or 'empty'}). "
                      "Click Load to show them.")

    def profile_load(self):
        name = self._selected_profile()
        if name is None:
            return
        self._set_active(self.profiles[name])
        self.note.set(f"Loaded profile “{name}”: {len(self.rows)} PIDs.")

    def profile_save(self):
        """Overwrite the selected profile with the current live-data list."""
        name = self.prof_var.get()
        if name not in self.profiles:
            self.profile_save_new()
            return
        pids = self._active()
        if not messagebox.askyesno("Save profile", f"Overwrite profile “{name}” with the current list "
                                   f"({len(pids)} PIDs)?", parent=self.root):
            return
        self.profiles[name] = pids
        if self._save_profiles():
            self.note.set(f"Saved the current list ({len(pids)} PIDs) to profile “{name}”.")

    def profile_save_new(self):
        name = simpledialog.askstring("Save as new profile", "Name of the new profile:", parent=self.root)
        name = (name or "").strip().replace(";", ",")
        if not name:
            return
        if name in self.profiles and not messagebox.askyesno(
                "Save profile", f"Profile “{name}” already exists. Overwrite it?", parent=self.root):
            return
        pids = self._active()
        self.profiles[name] = pids
        if self._save_profiles():
            self.prof_var.set(name)
            self.note.set(f"Saved the current list ({len(pids)} PIDs) as profile “{name}”.")

    def profile_delete(self):
        name = self._selected_profile()
        if name is None:
            return
        if not messagebox.askyesno("Delete profile", f"Delete profile “{name}”? The PIDs shown now stay "
                                   "on the list.", parent=self.root):
            return
        del self.profiles[name]
        if self._save_profiles():
            self.prof_var.set("")
            self.note.set(f"Deleted profile “{name}”.")

    def _apply_profile_edit(self, old, new, text):
        """Rename profile `old` and/or replace its PIDs; returns an error message or None."""
        new = new.strip().replace(";", ",")
        if not new:
            return "The name cannot be empty."
        if new != old and new in self.profiles:
            return f"A profile named “{new}” already exists."
        pids = parse_pids(text)[0]
        # rebuilt so a renamed profile keeps its place in the list
        self.profiles = {(new if k == old else k): (pids if k == old else v) for k, v in self.profiles.items()}
        if not self._save_profiles():
            return self.note.get()
        self.prof_var.set(new)
        return None

    def profile_edit(self):
        name = self._selected_profile()
        if name is None:
            return
        top = tk.Toplevel(self.root)
        top.title(f"Edit profile “{name}”")
        top.transient(self.root)
        top.resizable(False, False)
        new_name, text, info = (tk.StringVar(value=name), tk.StringVar(value=format_pids(self.profiles[name])),
                                tk.StringVar())
        frm = ttk.Frame(top, padding=10)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Name:").grid(row=0, column=0, sticky="w", pady=3)
        e = ttk.Entry(frm, textvariable=new_name, width=40)
        e.grid(row=0, column=1, sticky="w", pady=3)
        e.focus_set()
        ttk.Label(frm, text="PIDs (hex, e.g. 07,14,20-2F):").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(frm, textvariable=text, width=64).grid(row=1, column=1, sticky="w", pady=3)
        ttk.Button(frm, text="Use the current list",
                   command=lambda: text.set(format_pids(self._active()))).grid(row=2, column=1, sticky="w", pady=3)
        ttk.Label(frm, textvariable=info, wraplength=520, foreground="#555555").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(4, 6))

        def check(*_):
            pids, bad = parse_pids(text.get())
            info.set(f"{len(pids)} PIDs" + (f"; skipped (blocked or invalid): {', '.join(bad[:8])}" if bad else ""))

        def save(load=False):
            err = self._apply_profile_edit(name, new_name.get(), text.get())
            if err:
                info.set(err)
                return
            top.destroy()
            if load:
                self.profile_load()
            else:
                self.note.set(f"Saved profile “{self.prof_var.get()}”. Click Load to show it.")

        text.trace_add("write", check)
        check()
        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(btns, text="Save", command=save).pack(side="left", padx=4)
        ttk.Button(btns, text="Save and load", command=lambda: save(True)).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=top.destroy).pack(side="left")
        top.bind("<Return>", lambda e: save())
        top.bind("<Escape>", lambda e: top.destroy())
        top.grab_set()

    def remove_unchanged(self):
        """Drop PIDs that answered but never changed (min == max) or never answered."""
        if self._dtc_view_blocks():
            return
        gone = [p for p, st in self.rows.items() if st["seen"] and (st["min"] is None or st["min"] == st["max"])]
        self._remove(gone)
        self.note.set(f"Removed {len(gone)} PIDs that never changed, {len(self.rows)} left.")

    def remove_highlighted(self):
        """Drop PIDs that are highlighted right now (e.g. noisy ones hiding the interesting changes)."""
        if self._dtc_view_blocks():
            return
        t = now()
        gone = [p for p, st in self.rows.items() if st["hl_until"] > t]
        self._remove(gone)
        self.note.set(f"Removed {len(gone)} highlighted PIDs, {len(self.rows)} left.")

    def remove_selected(self):
        if self._dtc_view_blocks():
            return
        gone = [int(i) for i in self.tree.selection()]
        if gone:
            self._remove(gone)
            self.note.set(f"Removed from the list: {format_pids(sorted(gone))}. Names and conversions stay in the file.")

    def reset_stats(self):
        for p, st in self.rows.items():
            st.update(min=st["v"], max=st["v"], ref=st["v"], changes=0, last="", hl_until=0.0)
            self._render(p)

    def _order(self):
        return [int(i) for i in self.tree.get_children()]

    # -- context menu -------------------------------------------------------------------
    def _context_menu(self, event):
        row = self.tree.identify_row(event.y)
        if row and row not in self.tree.selection():
            self.tree.selection_set(row)
        if row:
            self.tree.focus(row)
        n = len(self.tree.selection())
        self._menu_row = int(row) if row else None
        self.menu.entryconfigure(0, label=f"Remove from list ({n})" if n > 1 else "Remove from list",
                                 state="normal" if n else "disabled")
        self.menu.entryconfigure(1, state="normal" if row else "disabled")
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _on_double(self, event):
        row = self.tree.identify_row(event.y)
        if row and self.tree.identify_region(event.x, event.y) == "cell":
            self.edit_def(int(row))

    # -- add-PID window -------------------------------------------------------------------
    def open_picker(self):
        if self.picker is not None:
            self.picker.deiconify()
            self.picker.lift()
            return
        top = tk.Toplevel(self.root)
        self.picker = top
        top.title("Add PIDs to the list")
        top.transient(self.root)
        top.geometry("600x520")
        flt, only_named, info = tk.StringVar(), tk.BooleanVar(), tk.StringVar(
            value="Select one or more (Ctrl / Shift) and click Add selected. Double-click or Enter adds right away.")

        bar = ttk.Frame(top)
        bar.pack(fill="x", padx=6, pady=6)
        ttk.Label(bar, text="Search (hex or name):").pack(side="left")
        search = ttk.Entry(bar, textvariable=flt)
        search.pack(side="left", fill="x", expand=True, padx=4)
        ttk.Checkbutton(bar, text="named only", variable=only_named, command=lambda: refill()).pack(side="left")

        frame = ttk.Frame(top)
        frame.pack(fill="both", expand=True, padx=6)
        cols = (("pid", "PID", 50), ("name", "Name", 230), ("conv", "Conversion", 150), ("on", "On list", 70))
        tree = ttk.Treeview(frame, columns=[c[0] for c in cols], show="headings", selectmode="extended")
        for key, title, width in cols:
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor="w" if key in ("name", "conv") else "center",
                        stretch=key in ("name", "conv"))
        tree.tag_configure("on", foreground="#999999")
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        def refill():
            q = flt.get().strip().lower()
            q = q[2:] if q.startswith("0x") else q
            tree.delete(*tree.get_children())
            for p in sorted(proto.MUT_ALLOWED):
                d = self.defs.get(p) or PidDef(p)
                if only_named.get() and not d.name:
                    continue
                if q and q not in f"{p:02x} {d.name.lower()}":
                    continue
                conv = f"{d.conv} [{d.unit}]" if d.unit else d.conv
                tree.insert("", "end", iid=str(p), values=(f"{p:02X}", d.name, conv, "✓" if d.active else ""),
                            tags=("on",) if d.active else ())

        def add(event=None):
            pids = [int(i) for i in tree.selection()]
            if not pids and len(tree.get_children()) == 1:   # Enter in the search box with one match
                pids = [int(tree.get_children()[0])]
            pids = [p for p in pids if not (p in self.defs and self.defs[p].active)]
            if not pids:
                info.set("Nothing to add: select PIDs that are not on the list yet.")
                return
            self._add(pids)
            self.note.set(f"Added to the list: {format_pids(sorted(pids))}.")
            info.set(f"Added: {format_pids(sorted(pids))}")

        def edit():
            sel = tree.focus() or (tree.selection() or [None])[0]
            if sel:
                self.edit_def(int(sel), parent=top)

        def closed(event):
            if event.widget is top:
                self.picker = self._picker_refill = None

        btns = ttk.Frame(top)
        btns.pack(fill="x", padx=6, pady=6)
        ttk.Button(btns, text="Add selected", command=add).pack(side="left")
        ttk.Button(btns, text="Edit name and conversion…", command=edit).pack(side="left", padx=6)
        ttk.Button(btns, text="Close", command=top.destroy).pack(side="right")
        ttk.Label(top, textvariable=info, foreground="#555555").pack(fill="x", padx=6, pady=(0, 6))

        flt.trace_add("write", lambda *a: refill())
        tree.bind("<Double-1>", lambda e: add() if tree.identify_region(e.x, e.y) == "cell" else None)
        tree.bind("<Return>", add)
        search.bind("<Return>", add)
        top.bind("<Escape>", lambda e: top.destroy())
        top.bind("<Destroy>", closed)
        self._picker_refill = refill
        refill()
        search.focus_set()

    # -- definition editor ------------------------------------------------------------------
    def edit_def(self, pid, parent=None):
        if pid is None:
            return
        d = self.defs.get(pid) or PidDef(pid)
        top = tk.Toplevel(parent or self.root)
        top.title(f"PID {pid:02X}: name and conversion")
        top.transient(parent or self.root)
        top.resizable(False, False)
        name, conv, unit, preview = (tk.StringVar(value=d.name), tk.StringVar(value=d.conv),
                                     tk.StringVar(value=d.unit), tk.StringVar())
        frm = ttk.Frame(top, padding=10)
        frm.pack(fill="both", expand=True)
        for r, (label, var, width) in enumerate((("Name:", name, 44), ("Conversion:", conv, 44),
                                                 ("Unit:", unit, 12))):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=3)
            e = ttk.Entry(frm, textvariable=var, width=width)
            e.grid(row=r, column=1, sticky="w", pady=3)
            if r == 0:
                e.focus_set()
        ttk.Label(frm, text=CONV_HELP, wraplength=420, foreground="#555555").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(4, 6))
        prev_lbl = ttk.Label(frm, textvariable=preview, wraplength=420)
        prev_lbl.grid(row=4, column=0, columnspan=2, sticky="w")

        def update_preview(*_):
            try:
                f = compile_conversion(conv.get())
            except ValueError as e:
                preview.set(f"Conversion error: {e}")
                prev_lbl.configure(foreground="#b00020")
                return False
            prev_lbl.configure(foreground="#1a5e1a")
            if f is None:
                preview.set("No conversion: the “Converted” column stays empty.")
                return True
            u = f" {unit.get().strip()}" if unit.get().strip() else ""
            v = self.rows.get(pid, {}).get("v")
            now_part = f"now: {v} → {f(v)}{u}     " if v is not None else ""
            preview.set(now_part + "examples: " + ",  ".join(f"{s} → {f(s)}{u}" for s in (0, 128, 255)))
            return True

        def save(event=None):
            if not update_preview():
                return
            dd = self.defs.setdefault(pid, PidDef(pid))
            dd.name, dd.conv, dd.unit = (v.get().strip().replace(";", ",") for v in (name, conv, unit))
            self._compile(pid)
            self._save_defs()
            if pid in self.rows:
                self._render(pid)
            if self._picker_refill:
                self._picker_refill()
            self.note.set(f"Saved the definition of PID {pid:02X} to {self.defs_path.name}.")
            top.destroy()

        conv.trace_add("write", update_preview)
        unit.trace_add("write", update_preview)
        update_preview()
        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Save", command=save).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=top.destroy).pack(side="left")
        top.bind("<Return>", save)
        top.bind("<Escape>", lambda e: top.destroy())
        top.grab_set()

    # -- sorting ----------------------------------------------------------------------
    def sort_by(self, key):
        if self.sort_col == key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_col, self.sort_desc = key, False
        self._apply_sort()

    def _sort_value(self, pid):
        st, k = self.rows[pid], self.sort_col
        if k == "name":
            return self.defs[pid].name or None
        if k == "last":
            return st["last"] or None
        return {"pid": pid, "value": st["v"], "phys": st["v"], "min": st["min"], "max": st["max"],
                "changes": st["changes"]}[k]

    def _apply_sort(self):
        for key, title, _ in self.COLS:
            arrow = (" ▼" if self.sort_desc else " ▲") if key == self.sort_col else ""
            self.tree.heading(key, text=title + arrow)
        if self.sort_col not in [c[0] for c in self.COLS]:
            return
        pids = list(self.rows)
        present = [p for p in pids if self._sort_value(p) is not None]
        missing = [p for p in pids if self._sort_value(p) is None]  # rows without data stay at the end
        order = sorted(present, key=self._sort_value, reverse=self.sort_desc) + missing
        for i, p in enumerate(order):
            self.tree.move(str(p), "", i)
        self._last_sort = now()

    # -- rows ----------------------------------------------------------------------
    def _fmt(self, v):
        if v is None:
            return "--"
        return f"{v:02X}" if self.fmt.get() == "HEX" else str(v)

    def _converted(self, pid, v):
        conv = self.convs.get(pid)
        if v is None or conv is None:
            return ""
        if isinstance(conv, str):  # the definition's conversion does not compile
            return conv
        out = conv(v)
        unit = self.defs[pid].unit
        return f"{out} {unit}" if unit and out != CONV_ERROR else out

    def _render(self, pid):
        st = self.rows[pid]
        st["hl_on"] = now() < st["hl_until"]
        tag = "hl" if st["hl_on"] else ("noreply" if st["seen"] and st["v"] is None else "")
        self.tree.item(str(pid), tags=(tag,) if tag else (), values=(
            f"{pid:02X}", self.defs[pid].name, self._fmt(st["v"]), self._converted(pid, st["v"]),
            self._fmt(st["min"]), self._fmt(st["max"]), st["changes"] or "", st["last"]))

    def _render_all(self):
        for p in self.rows:
            self._render(p)

    def _on_value(self, pid, v):
        st = self.rows.get(pid)
        if st is None:
            return
        changed = v != st["v"] or not st["seen"]
        st["seen"] = True
        st["v"] = v
        if v is not None:
            st["min"] = v if st["min"] is None else min(st["min"], v)
            st["max"] = v if st["max"] is None else max(st["max"], v)
            if st["ref"] is None:
                st["ref"] = v
            elif abs(v - st["ref"]) >= self._num(self.threshold, 1, int, 1):
                st["hl_until"] = now() + self._num(self.hl_secs, 3.0, float, 0.1)
                st["changes"] += 1
                st["last"] = time.strftime("%H:%M:%S")
                self._log_change(pid, st["ref"], v)
                st["ref"] = v
                changed = True
        if changed:
            self._render(pid)

    def _log_change(self, pid, old, new):
        if self.csv:
            self.csv.writerow([datetime.datetime.now().isoformat(timespec="milliseconds"),
                               f"{pid:02X}", old, new, new - old])

    # -- readings log ------------------------------------------------------------------
    def toggle_record(self):
        if self.rec_on:
            self._rec_close()
            return
        self.rec_on = True
        self.rec_stamp = f"{datetime.datetime.now():%Y%m%d-%H%M%S}"
        self.rec_no = self._next_rec_no()
        self.rec_header, self.rec_t0, self.rec_rows, self.rec_part = None, None, 0, 0
        self.btn_rec.configure(text="■ Stop log")
        self.rec_label.set("Readings log: waiting for ECU data")

    def _next_rec_no(self):
        """1 + the highest recording number in logs/ (and in this session), so names never repeat."""
        nums = [int(m.group(1)) for f in (HERE / "logs").glob("*_readings_*.csv")
                if (m := re.search(r"_readings_(\d+)", f.name))]
        return max(nums + [self.rec_no]) + 1

    def _rec_open_part(self, header):
        """New file for the first cycle and whenever the columns change (list or definitions)."""
        if self.rec_file:
            self.rec_file.close()
        self.rec_part += 1
        suffix = "" if self.rec_part == 1 else f"_part{self.rec_part}"
        self.rec_path = HERE / "logs" / f"{self.rec_stamp}_readings_{self.rec_no:03d}{suffix}.csv"
        try:
            self.rec_path.parent.mkdir(exist_ok=True)
            self.rec_file = open(self.rec_path, "w", newline="", encoding="utf-8-sig")
        except OSError as e:
            self.rec_file = None
            self._rec_close()
            self.note.set(f"Cannot create the log: {e}")
            return False
        self.rec_csv = csv.writer(self.rec_file)  # comma-separated, decimal point
        self.rec_csv.writerow(header)
        self.rec_header = header
        if self.rec_part > 1:
            self.note.set(f"Log columns changed, continuing in {self.rec_path.name}.")
        return True

    def _log_cycle(self, wall, values):
        """One CSV row per polling pass: time, then raw value (+ converted, if defined) per PID."""
        if not self.rec_on:
            return
        header, convs = ["time", "t [s]"], []
        for p in values:
            d = self.defs.get(p) or PidDef(p)
            base = f"{p:02X} {d.name}".strip()
            conv = self.convs.get(p)
            convs.append(conv if callable(conv) else None)
            header.append(base)
            if callable(conv):
                header.append(f"{base} [{d.unit}]" if d.unit else f"{base} (converted)")
        if header != self.rec_header and not self._rec_open_part(header):
            return
        if self.rec_t0 is None:
            self.rec_t0 = wall
        row = [f"{datetime.datetime.fromtimestamp(wall):%H:%M:%S.%f}"[:-3], f"{wall - self.rec_t0:.3f}"]
        for (p, v), conv in zip(values.items(), convs):
            row.append("" if v is None else v)
            if conv:
                row.append("" if v is None else conv(v))
        self.rec_csv.writerow(row)
        self.rec_rows += 1

    def _rec_close(self):
        self.rec_on = False
        if self.rec_file:
            self.rec_file.close()
            self.note.set(f"Saved log {self.rec_path.name}: {self.rec_rows} rows"
                          + (f" (in {self.rec_part} files)." if self.rec_part > 1 else "."))
        self.rec_file = self.rec_csv = None
        self.btn_rec.configure(text="● Record log")
        self.rec_label.set("Readings log: off")

    def open_logs(self):
        folder = HERE / "logs"
        folder.mkdir(exist_ok=True)
        os.startfile(folder)

    # -- connection ------------------------------------------------------------------
    def connect(self):
        if self.poller:
            return
        logdir = HERE / "logs"
        logdir.mkdir(exist_ok=True)
        path = logdir / f"{datetime.datetime.now():%Y%m%d-%H%M%S}_gui_changes.csv"
        self.csv_file = open(path, "w", newline="", encoding="utf-8")
        self.csv = csv.writer(self.csv_file)
        self.csv.writerow(["time", "pid", "old", "new", "delta"])
        key = self._iface_key()
        self.iface_used = ""
        self.poller = Poller(lambda: open_interface(key), list(self.rows), self.q)
        self.poller.start()
        self.btn_conn.configure(state="disabled")
        self.btn_disc.configure(state="normal")
        self.cb_iface.configure(state="disabled")
        self.btn_refresh.configure(state="disabled")
        self.status.set("Opening interface...")

    def disconnect(self):
        if self.poller:
            self.poller.stop_ev.set()
            self.status.set("Disconnecting...")

    def _stopped(self):
        self.poller = None
        if self.csv_file:
            self.csv_file.close()
            self.csv_file = self.csv = None
        self.btn_conn.configure(state="normal")
        self.btn_disc.configure(state="disabled")
        self.cb_iface.configure(state="readonly")
        self.btn_refresh.configure(state="normal")
        self.info.set("")
        if not self.status.get().startswith(("Interface error", "Cannot open")):
            self.status.set("Disconnected")

    def _tick(self):
        try:
            for _ in range(5000):
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "val":
                    self._on_value(msg[1], msg[2])
                elif kind == "cycle":
                    self._log_cycle(msg[1], msg[2])
                elif kind == "status":
                    self.status.set(msg[1])
                elif kind == "iface":
                    self.iface_used = msg[1]
                elif kind == "connected":
                    self.ecu_id = msg[1]
                    via = f" via {self.iface_used}" if self.iface_used else ""
                    self.status.set(f"Connected to engine ECU, ID {msg[1]}{via}")
                elif kind == "rate":
                    self.info.set(f"{msg[1]:.0f} reads/s, cycle {msg[2]:.2f} s")
                elif kind == "fatal":
                    self.status.set(msg[1])
                    if msg[1].startswith("Cannot open"):
                        self.note.set(msg[1] + ". Check the Interface list (a cable with a non-FTDI chip: pick its "
                                      "COM port); after plugging in the cable click Refresh.")
                elif kind == "stopped":
                    self._stopped()
                elif kind == "update" and msg[1]:
                    self._show_update(*msg[1])
        except queue.Empty:
            pass
        t = now()
        for p, st in self.rows.items():
            if st["hl_on"] and t >= st["hl_until"]:
                self._render(p)
        if self.live_sort.get() and self.sort_col and t - self._last_sort >= 1.0:
            self._apply_sort()
        if t - self._last_file_check >= 1.0:
            self._last_file_check = t
            self._check_file()
        if self.csv_file:
            self.csv_file.flush()
        if self.rec_file:
            self.rec_file.flush()
            self.rec_label.set(f"Log: {self.rec_path.name}, {self.rec_rows} rows")
        self.root.after(50, self._tick)

    def show_welcome(self):
        if self.welcome and self.welcome.exists():
            self.welcome.win.lift()
            return
        # README files are bundled into the .exe (PyInstaller --add-data); from source they sit in HERE
        dirs = [Path(getattr(sys, "_MEIPASS", HERE)), HERE]
        self.welcome = WelcomeWindow(self.root, __version__, dirs, system_language(),
                                     self.welcome_hidden == __version__, self._welcome_closed)

    def _welcome_closed(self, hide):
        self.welcome_hidden = __version__ if hide else ""
        self._save_settings()

    def _show_update(self, tag, url):
        """Bar above everything else; the user downloads and replaces the files."""
        bar = tk.Frame(self.root, background="#fff3c4")
        bar.pack(fill="x", before=self.first_bar)

        def never():
            self.check_updates = False
            self._save_settings()
            bar.destroy()

        tk.Label(bar, text=f"A newer version is available: {tag} (you have {__version__}).",
                 background="#fff3c4").pack(side="left", padx=6, pady=3)
        ttk.Button(bar, text="Open download page", command=lambda: webbrowser.open(url)).pack(side="left", padx=2)
        ttk.Button(bar, text="Later", command=bar.destroy).pack(side="left", padx=2)
        ttk.Button(bar, text="Don't check again", command=never).pack(side="left", padx=2)

    def close(self):
        self._save_settings()
        if self.poller:
            self.poller.stop_ev.set()
            self.poller.join(timeout=3.0)
        if self.csv_file:
            self.csv_file.close()
        if self.rec_on:
            self._rec_close()
        self.root.destroy()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=("auto", "d2xx", "serial", "sim"),
                    help="override the interface picked in the window")
    ap.add_argument("--sim", default="mutlive", help="simulator model for --backend sim")
    ap.add_argument("--port", help="COM port, e.g. COM5 (implies --backend serial)")
    ap.add_argument("--dev", type=int, help="D2XX device index (implies --backend d2xx)")
    ap.add_argument("--serial", help="D2XX: open by FTDI serial number (implies --backend d2xx)")
    ap.add_argument("--connect", action="store_true", help="connect right after start")
    args = ap.parse_args()
    cli_iface = cli_key(args.backend, args.dev, args.serial, args.port, args.sim)  # None: use the window's choice
    root = tk.Tk()
    app = App(root, cli_iface)
    if args.connect:
        root.after(200, app.connect)
    root.mainloop()


if __name__ == "__main__":
    main()
