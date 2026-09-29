"""Welcome window: a short plain-language introduction (welcome/pl.md, welcome/en.md) rendered
in a Tk Text widget. Polish when Windows is set to Polish, else English. The technical
description stays in README.md on GitHub."""

import ctypes
import locale
import re
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk

from .update import REPO

REPO_URL = f"https://github.com/{REPO}"
FILES = {"en": "welcome/en.md", "pl": "welcome/pl.md"}
TEXTS = {
    "en": {"title": "Welcome to mitsu-kkl {v}", "hide": "Don't show again (until the next version)",
           "close": "Close", "missing": "Description file {f} not found."},
    "pl": {"title": "Witaj w mitsu-kkl {v}", "hide": "Nie pokazuj więcej (do następnej wersji)",
           "close": "Zamknij", "missing": "Nie znaleziono pliku opisu {f}."},
}


def system_language():
    """'pl' when the Windows display language is Polish (or, off Windows, the locale), else 'en'."""
    try:
        return "pl" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x15 else "en"
    except (AttributeError, OSError):
        loc = (locale.getlocale()[0] or "").lower()
        return "pl" if loc.startswith(("pl", "polish")) else "en"


# -- minimal Markdown: headings, paragraphs, lists, tables, code, **bold**, *italic*, `code`, links --
_INLINE = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)|\*([^*\s][^*]*?)\*")
_ITEM = re.compile(r"(\s*)(?:[-*]|(\d+)\.)\s+(.*)")


def _block_start(line):
    s = line.strip()
    return s.startswith(("```", "#", "|")) or bool(_ITEM.match(line))


def parse_markdown(md):
    """-> [("h", level, text) | ("para", text) | ("item", level, number, text) |
           ("table", rows) | ("code", text)]"""
    lines, blocks, i = md.splitlines(), [], 0
    while i < len(lines):
        line, s = lines[i], lines[i].strip()
        if s.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            blocks.append(("code", "\n".join(lines[i + 1:j])))
            i = j + 1
        elif not s:
            i += 1
        elif m := re.match(r"(#{1,6})\s+(.*)", s):
            blocks.append(("h", len(m.group(1)), m.group(2)))
            i += 1
        elif s.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                raw = lines[i].strip().strip("|").replace("\\|", "\0")
                cells = [c.strip().replace("\0", "|") for c in raw.split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            blocks.append(("table", rows))
        elif m := _ITEM.match(line):
            indent, text = len(m.group(1)), m.group(3)
            i += 1
            while (i < len(lines) and lines[i].strip() and not _block_start(lines[i])
                   and len(lines[i]) - len(lines[i].lstrip()) > indent):
                text += " " + lines[i].strip()
                i += 1
            blocks.append(("item", indent // 2, m.group(2), text))
        else:
            text = s
            i += 1
            while i < len(lines) and lines[i].strip() and not _block_start(lines[i]):
                text += " " + lines[i].strip()
                i += 1
            blocks.append(("para", text))
    return blocks


def slug(heading):
    """GitHub-style anchor: 'Bezpieczeństwo' -> 'bezpieczeństwo', 'What's inside' -> 'whats-inside'."""
    return re.sub(r"[^\w\- ]", "", heading.lower()).strip().replace(" ", "-")


class MarkdownView:
    def __init__(self, text, on_link):
        self.t, self.on_link, self.n_links = text, on_link, 0
        base = ("Segoe UI", 10)
        text.configure(font=base, wrap="word", padx=14, pady=10, spacing1=1, spacing3=1)
        text.tag_configure("bold", font=("Segoe UI", 10, "bold"))
        text.tag_configure("italic", font=("Segoe UI", 10, "italic"))
        text.tag_configure("code", font=("Consolas", 10), background="#eef0f2")
        text.tag_configure("codeblock", font=("Consolas", 9), background="#f4f5f7", lmargin1=12, lmargin2=12,
                           spacing1=0, spacing3=0)
        text.tag_configure("h1", font=("Segoe UI", 18, "bold"), spacing1=4, spacing3=6)
        text.tag_configure("h2", font=("Segoe UI", 13, "bold"), spacing1=12, spacing3=4, foreground="#1f3b5c")
        text.tag_configure("h3", font=("Segoe UI", 11, "bold"), spacing1=8, spacing3=2)
        text.tag_configure("para", spacing3=8)
        for lvl in range(4):
            text.tag_configure(f"item{lvl}", lmargin1=6 + 20 * lvl, lmargin2=22 + 20 * lvl, spacing3=3)
        text.tag_configure("link", foreground="#1a5fb4", underline=True)
        text.tag_bind("link", "<Enter>", lambda e: text.configure(cursor="hand2"))
        text.tag_bind("link", "<Leave>", lambda e: text.configure(cursor=""))

    def render(self, md):
        t = self.t
        t.configure(state="normal")
        t.delete("1.0", "end")
        prev = None
        for b in parse_markdown(md):
            kind = b[0]
            if prev == "item" and kind != "item":
                t.insert("end", "\n")
            if kind == "h":
                level = min(b[1], 3)
                t.mark_set("h-" + slug(b[2]), "end-1c")
                t.mark_gravity("h-" + slug(b[2]), "left")
                self._inline(b[2], (f"h{level}",))
                t.insert("end", "\n", (f"h{level}",))
            elif kind == "para":
                self._inline(b[1], ("para",))
                t.insert("end", "\n", ("para",))
            elif kind == "item":
                self._item(b[1], f"{b[2]}. " if b[2] else "•  ", b[3])
            elif kind == "table":
                self._table(b[1])
            elif kind == "code":
                t.insert("end", b[1] + "\n", ("codeblock",))
                t.insert("end", "\n")
            prev = "item" if kind in ("item", "table") else kind
        t.configure(state="disabled")

    def _item(self, level, bullet, text):
        tag = f"item{min(level, 3)}"
        self.t.insert("end", bullet, (tag,))
        self._inline(text, (tag,))
        self.t.insert("end", "\n", (tag,))

    def _table(self, rows):
        """Rows as list items: bold first cell, then the other cells (with their headers)."""
        if not rows:
            return
        head, body = rows[0], rows[1:]
        for row in body:
            first = row[0][2:-2] if row[0].startswith("**") and row[0].endswith("**") else row[0]
            if len(row) == 2:
                rest = row[1]
            else:
                rest = " · ".join(f"{h}: {c}" for h, c in zip(head[1:], row[1:]) if c not in ("", "-", "–"))
            self._item(0, "•  ", f"**{first}**" + (f" — {rest}" if rest else ""))

    def _inline(self, s, tags):
        pos = 0
        for m in _INLINE.finditer(s):
            self.t.insert("end", s[pos:m.start()], tags)
            bold, code, ltext, url, ital = m.groups()
            if bold is not None:
                self._inline(bold, tags + ("bold",))
            elif code is not None:
                self.t.insert("end", code, tags + ("code",))
            elif ltext is not None:
                tag = f"link{self.n_links}"
                self.n_links += 1
                self.t.tag_bind(tag, "<Button-1>", lambda e, u=url: self.on_link(u))
                self._inline(ltext, tags + ("link", tag))
            else:
                self._inline(ital, tags + ("italic",))
            pos = m.end()
        self.t.insert("end", s[pos:], tags)


class WelcomeWindow:
    """on_close(hide) is called with the state of the 'don't show again' checkbox."""

    def __init__(self, master, version, doc_dirs, lang, hidden, on_close):
        self.version, self.doc_dirs, self.on_close = version, [Path(d) for d in doc_dirs], on_close
        self.win = w = tk.Toplevel(master)
        w.transient(master)
        w.minsize(520, 300)
        self.lang = tk.StringVar(value=lang)
        self.hide = tk.BooleanVar(value=hidden)

        top = ttk.Frame(w)
        top.pack(fill="x", padx=8, pady=(8, 2))
        for code, label in (("pl", "Polski"), ("en", "English")):
            ttk.Radiobutton(top, text=label, value=code, variable=self.lang,
                            command=lambda: self.set_lang(self.lang.get())).pack(side="left", padx=(0, 10))

        body = ttk.Frame(w)
        body.pack(fill="both", expand=True, padx=8, pady=4)
        self.text = tk.Text(body, borderwidth=1, relief="solid", background="#ffffff")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.view = MarkdownView(self.text, self._link)

        bottom = ttk.Frame(w)
        bottom.pack(fill="x", padx=8, pady=(2, 8))
        self.cb_hide = ttk.Checkbutton(bottom, variable=self.hide)
        self.cb_hide.pack(side="left")
        self.btn_close = ttk.Button(bottom, command=self.close)
        self.btn_close.pack(side="right")

        w.protocol("WM_DELETE_WINDOW", self.close)
        w.bind("<Escape>", lambda e: self.close())
        self.set_lang(lang)
        self._center(master)
        self.btn_close.focus_set()

    def set_lang(self, lang):
        self.lang.set(lang)
        tx = TEXTS[lang]
        self.win.title(tx["title"].format(v=self.version))
        self.cb_hide.configure(text=tx["hide"])
        self.btn_close.configure(text=tx["close"])
        name = FILES[lang]
        path = next((d / name for d in self.doc_dirs if (d / name).is_file()), None)
        md = path.read_text(encoding="utf-8-sig") if path else "# mitsu-kkl\n\n" + tx["missing"].format(f=name)
        self.view.render(md)
        self.text.yview_moveto(0)

    def _link(self, url):
        if url.startswith("#"):
            mark = "h-" + url[1:].lower()
            if mark in self.text.mark_names():
                self.text.yview(mark)
            return
        if not url.startswith(("http://", "https://")):
            url = f"{REPO_URL}/releases" if url.rstrip("/").endswith("releases") else f"{REPO_URL}/blob/main/{url}"
        webbrowser.open(url)

    def _center(self, master):
        """Up to 860x700, never taller than the screen minus the taskbar, centred on the main
        window but kept fully on screen so the checkbox and Close button stay visible."""
        w = self.win
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        width, height = min(860, sw - 40), min(700, sh - 110)   # 110: title bar + taskbar
        try:
            x = master.winfo_rootx() + (master.winfo_width() - width) // 2
            y = master.winfo_rooty() + (master.winfo_height() - height) // 2
        except tk.TclError:
            x, y = (sw - width) // 2, (sh - height) // 2
        x = max(0, min(x, sw - width - 10))
        y = max(0, min(y, sh - height - 80))
        w.geometry(f"{width}x{height}+{x}+{y}")

    def close(self):
        hide = self.hide.get()
        self.win.destroy()
        self.on_close(hide)

    def exists(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False
