#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["rich>=13.7"]
# ///
"""Taller: every project the user works on, as one list, and what to do next.

- The list (taller.collect()): projects in four sections -- 🔴 Et necessita
  (an agent waiting on you, broken, or done and not looked at yet),
  🟡 Treballant, 🗂 Aparcats (newest first) and 💤 Adormits (one line until
  `d`). Each row: its agents' glyphs (aoe ones dimmed), name, branch,
  uncommitted (✎), unpushed (↑), no remote (⚠), worktrees, last touch.
- The detail of the selection: path and remote, agents, the last exchange,
  the last commits, worktrees and changed files. Commits and changes are
  read for the selected project only, in the background, cached until its
  HEAD, index or dirty count change.

Keys act through herdr (taller.py): ⏎ goes to the project's herdr agent or,
without one, reopens its last conversation in a new workspace as a named
agent; `n` a fresh agent; `w` a new worktree with its own agent; `t` a shell;
`o` the remote in the browser. Herdr agents refresh every `[ui].agents_secs`,
git every `[ui].git_secs` and right after an action. TALLER_DRY_RUN=1 turns
every action into a message saying what it would run. Run it through
taller.sh; `--once` prints one frame (COLUMNS/LINES), `--keys` replays keys
first.
"""
import os
import select
import shlex
import subprocess
import sys
import termios
import textwrap
import threading
import time
import tty

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)
import taller  # noqa: E402

PLUGIN_ID = "elboletaire.taller"
IN_HERDR = os.environ.get("HERDR_ENV") == "1"
DRY_RUN = taller.dry_run()
CONFIRM_SECS = 8       # window for the second press
FLASH_SECS = 8
SIDE_MIN = 120         # from this width the detail sits beside the list
SIDE_SHARE = 0.42      # of the width, for the detail when beside
ENTER = ("\r", "\n")

AGENT_GLYPH = {"working": ("◐", "yellow"), "waiting": ("⏸", "bold red"),
               "error": ("✗", "bold red"), "done": ("✓", "bold green"),
               "idle": ("○", "white"), "stopped": ("■", "grey50"),
               "unknown": ("?", "grey50")}
STATE_LABEL = {"working": "treballant", "waiting": "t'espera",
               "error": "error", "done": "ha acabat", "idle": "inactiu",
               "stopped": "aturat", "unknown": "?"}
SECTION = {"need": ("🔴", "Et necessita", "bold red"),
           "working": ("🟡", "Treballant", "bold yellow"),
           "parked": ("🗂 ", "Aparcats", "bold cyan"),
           "dormant": ("💤", "Adormits", "bold grey50")}


# ----------------------------------------------------------------- helpers

def ago(secs):
    """Compact age: ara, 43m, 5h, 3d, 2w, 4mo, 2y."""
    if secs is None:
        return "–"
    secs = max(0, int(secs))
    if secs < 60:
        return "ara"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    days = secs // 86400
    if days < 14:
        return f"{days}d"
    if days < 63:
        return f"{days // 7}w"
    if days < 365:
        return f"{days // 30}mo"
    return f"{days // 365}y"


def clip(text, n):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:max(0, n - 1)].rstrip() + "…"


def plural(n, one, many):
    return f"{n} {one if n == 1 else many}"


def home(path):
    h = os.path.expanduser("~")
    return "~" + path[len(h):] if path and taller.within(path, h) else path


def line(*parts):
    """A Text from (text, style) pairs, one line, ellipsised."""
    t = Text(no_wrap=True, overflow="ellipsis")
    for p in parts:
        if isinstance(p, Text):
            t.append_text(p)
        elif isinstance(p, tuple):
            t.append(*p)
        else:
            t.append(p)
    return t


def wrapped(prefix, text, width, max_lines, style=""):
    """`prefix` then `text` wrapped under it, at most `max_lines` lines."""
    width = max(10, width - len(prefix))
    chunks = textwrap.wrap(" ".join((text or "").split()), width) or [""]
    if len(chunks) > max_lines:
        chunks = chunks[:max_lines]
        chunks[-1] = clip(chunks[-1] + " …", width)
    out = []
    for i, c in enumerate(chunks):
        t = Text(no_wrap=True, overflow="ellipsis")
        t.append(prefix if i == 0 else " " * len(prefix), style="dim")
        t.append(c, style=style)
        out.append(t)
    return out


# ------------------------------------------------------------------- model

class Model:
    """The projects, kept fresh by background threads: herdr and aoe agents
    every [ui].agents_secs, a full collect every [ui].git_secs (or when
    kicked), and the selected project's details on demand."""

    def __init__(self, cfg):
        self.cfg = cfg
        ui = cfg.get("ui", {})
        self.agents_secs = max(1, int(ui.get("agents_secs", 3)))
        self.git_secs = max(5, int(ui.get("git_secs", 20)))
        self.dormant_days = cfg["taller"]["dormant_days"]
        self.lock = threading.Lock()
        self.changed = threading.Event()
        self.kick_collect = threading.Event()
        self.kick_agents = threading.Event()
        self.kick_details = threading.Event()
        self.projects = None
        self.err = None
        self.collected_at = 0
        self.agents_at = 0
        self.collecting = False
        self.orphans = set()      # agent folders a collect already looked at
        self.details = {}         # path -> (key, data)
        self.wanted = None        # project whose details are due
        self.sync = False         # --once: details inline, no thread

    # -- projects

    def collect(self):
        self.collecting = True
        self.changed.set()
        try:
            ps, err = taller.collect(self.cfg), None
        except Exception as e:  # noqa: BLE001 -- a bad repo must not kill the board
            ps, err = None, f"{type(e).__name__}: {e}"
        with self.lock:
            if ps is not None:
                self.projects = ps
                self.collected_at = self.agents_at = time.time()
            self.err = err
            self.collecting = False
        self.changed.set()

    def refresh_agents(self):
        """Agents again (~0.2s) onto copies of the projects. An agent in a
        folder no project holds brings a collect, once per folder."""
        try:
            agents = taller.list_agents()
        except Exception:  # noqa: BLE001
            return
        with self.lock:
            projects = self.projects
        if projects is None:
            return
        fresh = [dict(p) for p in projects]
        orphans = taller.match_agents(fresh, agents)
        for p in fresh:
            taller.wake(p, self.dormant_days)
        with self.lock:
            if self.projects is projects:
                self.projects = fresh
                self.agents_at = time.time()
        new = {a["path"] for a in orphans} - self.orphans
        self.orphans |= new
        if new:
            self.kick_collect.set()
        self.changed.set()

    def collect_loop(self):
        while True:
            self.kick_collect.clear()
            self.collect()
            self.kick_collect.wait(self.git_secs)

    def agents_loop(self):
        while True:
            self.kick_agents.wait(self.agents_secs)
            self.kick_agents.clear()
            self.refresh_agents()

    def snapshot(self):
        with self.lock:
            return list(self.projects or [])

    # -- details of the selection

    def details_for(self, p):
        """-> (data or None, loading). Asks for a fresh read when the cached
        one is missing or out of date; the stale one shows meanwhile."""
        if not p or not p["git"]:
            return None, False
        key = taller.details_key(p)
        cached = self.details.get(p["path"])
        if cached and cached[0] == key:
            return cached[1], False
        if self.sync:
            self.load_details(p, key)
            return self.details[p["path"]][1], False
        self.wanted = p
        self.kick_details.set()
        return (cached[1] if cached else None), True

    def load_details(self, p, key=None):
        key = key or taller.details_key(p)
        try:
            data = taller.details(p["path"])
        except Exception as e:  # noqa: BLE001
            data = {"commits": [], "changes": [], "changes_total": 0,
                    "error": f"{type(e).__name__}: {e}"}
        self.details[p["path"]] = (key, data)
        self.changed.set()

    def details_loop(self):
        while True:
            self.kick_details.wait()
            self.kick_details.clear()
            p = self.wanted
            if not p:
                continue
            key = taller.details_key(p)
            cached = self.details.get(p["path"])
            if not cached or cached[0] != key:
                self.load_details(p, key)

    def start(self):
        for fn in (self.collect_loop, self.agents_loop, self.details_loop):
            threading.Thread(target=fn, daemon=True).start()


# -------------------------------------------------------------------- view

def row_flags(p):
    """✎ uncommitted (worktrees too), ↑ unpushed, ⚠ no remote, ✗ git error."""
    t = Text(no_wrap=True)
    dirty = (p["dirty"] or 0) + sum(w["dirty"] for w in p["worktrees"])
    if dirty:
        t.append(f"✎{dirty} ", style="yellow")
    if p["ahead"]:
        t.append(f"↑{p['ahead']} ", style="cyan")
    if p["git"] and "no_remote" in p["flags"]:
        t.append("⚠ ", style="bold red")
    if "error" in p["flags"]:
        t.append("✗ ", style="red")
    t.rstrip()
    return t


def agent_glyphs(agents):
    """One glyph per agent: herdr ones in their state's colour, then the aoe
    ones dimmed with a small "aoe" after them."""
    t = Text(no_wrap=True)
    for a in sorted(agents, key=lambda a: a["host"] != "herdr"):
        g, style = AGENT_GLYPH.get(a["state"], AGENT_GLYPH["unknown"])
        if a["host"] == "aoe":
            style = "dim " + style
        t.append(g, style=style)
    if any(a["host"] == "aoe" for a in agents):
        t.append("ᵃᵒᵉ", style="dim")
    return t


class Board:
    def __init__(self, model, console):
        self.m = model
        self.console = console
        self.cursor = None        # selected project's path
        self.show_dormant = False
        self.filter = ""
        self.input = None         # {"kind": filter|branch, "prompt", "buf"}
        self.confirm = None       # {"action", "key", "path", "until", "msg", ...}
        self.flash = ("", 0)
        self.busy = ""
        self.rows = []
        self.list_h = 10

    def say(self, msg):
        self.flash = (msg, time.time())
        self.m.changed.set()

    # -- the list

    def visible(self, projects):
        if not self.filter:
            return projects
        f = self.filter.lower()
        return [p for p in projects if f in p["name"].lower()]

    def build_rows(self):
        """[("head", section, n) | ("project", p, section) |
        ("dormant", projects)], and the cursor kept on a project."""
        projects = self.visible(self.m.snapshot())
        groups = taller.sections(projects)
        rows = []
        for sec in taller.SECTIONS:
            ps = groups[sec]
            if not ps:
                continue
            rows.append(("head", sec, len(ps)))
            if sec == "dormant" and not (self.show_dormant or self.filter):
                rows.append(("dormant", ps))
                continue
            rows += [("project", p, sec) for p in ps]
        self.rows = rows
        paths = [r[1]["path"] for r in rows if r[0] == "project"]
        if self.cursor not in paths:
            self.cursor = paths[0] if paths else None
        return rows

    def project(self):
        return next((r[1] for r in self.rows if r[0] == "project"
                     and r[1]["path"] == self.cursor), None)

    def move(self, d):
        paths = [r[1]["path"] for r in self.rows if r[0] == "project"]
        if not paths:
            return
        i = paths.index(self.cursor) if self.cursor in paths else 0
        self.cursor = paths[max(0, min(len(paths) - 1, i + d))]
        self.confirm = None

    # -- rendering

    def render(self):
        self.build_rows()
        width, height = self.console.size
        foot = self.footer()
        foot_h = max(1, len(foot.wrap(self.console, width)))
        body_h = max(8, height - foot_h)
        root = Layout()
        root.split_column(Layout(name="body", size=body_h),
                          Layout(foot, name="foot", size=foot_h))
        p = self.project()
        if width >= SIDE_MIN:
            side_w = max(40, int(width * SIDE_SHARE))
            root["body"].split_row(
                Layout(self.list_panel(width - side_w, body_h), name="list"),
                Layout(self.detail_panel(p, side_w, body_h), name="detail",
                       size=side_w))
        else:
            list_h = max(6, body_h // 2)
            root["body"].split_column(
                Layout(self.list_panel(width, list_h), name="list",
                       size=list_h),
                Layout(self.detail_panel(p, width, body_h - list_h),
                       name="detail"))
        return root

    def header(self, width):
        projects = self.m.snapshot()
        groups = taller.sections(projects)
        t = Text(no_wrap=True, overflow="ellipsis")
        for i, sec in enumerate(taller.SECTIONS):
            icon, _, style = SECTION[sec]
            n = len(groups[sec])
            if i:
                t.append("  ")
            t.append(f"{icon} {n}", style=style if n else "dim")
        if self.filter:
            t.append(f"   filtre «{self.filter}»", style="bold magenta")
        bare = [p for p in projects if taller.no_backup(p)]
        if bare:
            t.append("   ⚠ " + plural(len(bare), "projecte sense còpia",
                                       "projectes sense còpia"),
                     style="bold red")
        now = time.time()
        if self.m.collecting:
            t.append("   ⟳ git", style="cyan")
        elif self.m.collected_at:
            t.append(f"   git fa {ago(now - self.m.collected_at)}",
                     style="dim")
        return t

    def list_panel(self, width, height):
        inner_h = height - 2
        title = Text("🛠  Taller", style="bold")
        if self.m.projects is None:
            msg = self.m.err or "llegint els projectes…"
            return Panel(Text(msg, style="red" if self.m.err else "dim"),
                         title=title, title_align="left", height=height,
                         border_style="green")
        head = self.header(width - 4)
        self.list_h = max(3, inner_h - 2)
        table = self.table(width - 4, self.list_h)
        parts = [head, Text(""), table]
        if not self.rows:
            parts.append(Text("cap projecte" + (" amb aquest filtre"
                                                if self.filter else ""),
                              style="dim"))
        return Panel(Group(*parts), title=title, title_align="left",
                     height=height, border_style="green", padding=(0, 1))

    def table(self, width, room):
        tb = Table(box=None, expand=True, pad_edge=False, show_edge=False,
                   show_header=False, padding=(0, 1))
        tb.add_column("", width=1, no_wrap=True)
        tb.add_column("agents", no_wrap=True, min_width=2)
        tb.add_column("name", ratio=3, no_wrap=True, overflow="ellipsis")
        tb.add_column("branch", ratio=2, no_wrap=True, overflow="ellipsis")
        tb.add_column("flags", no_wrap=True)
        tb.add_column("wt", no_wrap=True, justify="right")
        tb.add_column("ago", no_wrap=True, justify="right", min_width=3)
        rows = self.rows
        idx = next((i for i, r in enumerate(rows) if r[0] == "project"
                    and r[1]["path"] == self.cursor), 0)
        start = 0
        if len(rows) > room:
            start = max(0, min(idx - room // 3, len(rows) - room))
        now = time.time()
        for r in rows[start:start + room]:
            if r[0] == "head":
                icon, label, style = SECTION[r[1]]
                tb.add_row("", Text(icon), Text(f"{label} ({r[2]})",
                                                style=style), "", "", "", "")
            elif r[0] == "dormant":
                names = ", ".join(p["name"] for p in r[1])
                tb.add_row("", "", Text(f"{names}", style="dim italic",
                                        no_wrap=True, overflow="ellipsis"),
                           Text("d desplega", style="dim"), "", "", "")
            else:
                p = r[1]
                sel = p["path"] == self.cursor
                dim = r[2] == "dormant"
                name = Text(p["name"], style="bold" if sel else
                            ("grey50" if dim else ""))
                branch = Text(p["branch"] or ("sense git" if not p["git"]
                                              else "–"),
                              style="grey50" if dim or not p["branch"]
                              else "magenta")
                wt = Text(f"⑂{len(p['worktrees'])}" if p["worktrees"] else "",
                          style="dim")
                touch = Text(ago(now - p["last_touch"]) if p["last_touch"]
                             else "–", style="dim")
                tb.add_row("▶" if sel else "", agent_glyphs(p["agents"]),
                           name, branch, row_flags(p), wt, touch,
                           style="reverse" if sel else None)
        return tb

    # .. the detail

    def detail_panel(self, p, width, height):
        inner_w, inner_h = width - 4, height - 2
        if not p:
            return Panel(Text("cap projecte seleccionat", style="dim"),
                         title=Text("Detall", style="bold"),
                         title_align="left", height=height,
                         border_style="grey35")
        lines = self.detail_lines(p, inner_w)
        if len(lines) > inner_h:
            lines = lines[:inner_h - 1] + [Text("…", style="dim")]
        return Panel(Group(*lines), title=Text(p["name"], style="bold"),
                     title_align="left", height=height, border_style="grey35",
                     padding=(0, 1))

    def detail_lines(self, p, width):
        now = time.time()
        out = [line((home(p["path"]), "dim"))]
        if not p["git"]:
            out.append(line(("sense git", "yellow"),
                            (" · una carpeta on corre un agent", "dim")))
        elif p["remote"]:
            t = line(("remot ", "dim"), (p["remote"], "cyan"))
            if p["branch"]:
                t.append("  ")
                t.append(p["branch"], style="magenta")
                if p["ahead"]:
                    t.append(f" ↑{p['ahead']} per pujar", style="bold cyan")
                if p["behind"]:
                    t.append(f" ↓{p['behind']}", style="dim")
                if "no_upstream" in p["flags"]:
                    t.append(" sense upstream", style="yellow")
            out.append(t)
        else:
            out.append(line(("⚠ sense remot: no hi ha còpia fora d'aquest "
                             "ordinador", "bold red")))
        if "error" in p["flags"]:
            out.append(line(("✗ git ha fallat o ha trigat massa", "red")))

        out.append(Text(""))
        out.append(line(("Agents", "bold")))
        if not p["agents"]:
            out.append(line(("  cap · ⏎ reprèn l'última conversa a herdr",
                             "dim")))
        for a in sorted(p["agents"], key=lambda a: a["host"] != "herdr"):
            g, style = AGENT_GLYPH.get(a["state"], AGENT_GLYPH["unknown"])
            t = line("  ", (g + " ", style), (a["name"], "bold"),
                     (f"  {a['tool'] or '?'} · {a['host']} · ", "dim"),
                     (STATE_LABEL.get(a["state"], a["state"]),
                      style if a["state"] in taller.NEED_STATES else "dim"))
            if a["path"] != p["path"]:
                t.append(f"  {os.path.relpath(a['path'], p['path'])}",
                         style="dim")
            out.append(t)

        ex = p.get("last_exchange")
        if ex:
            out.append(Text(""))
            t = line(("Última conversa", "bold"),
                     (f"  {ex.get('tool')} · fa {ago(now - ex['at'])}"
                      if ex.get("at") else f"  {ex.get('tool')}", "dim"))
            out.append(t)
            if ex.get("title"):
                out.append(line(("  «" + ex["title"] + "»", "italic")))
            if ex.get("user"):
                out += wrapped("  tu    ", ex["user"], width, 2)
            out += wrapped("  agent ", ex.get("agent") or "(encara hi "
                           "treballa, o no ha contestat)", width, 3,
                           style="" if ex.get("agent") else "dim")

        d, loading = self.m.details_for(p)
        if p["git"]:
            out.append(Text(""))
            out.append(line(("Commits", "bold"),
                            ("  ⟳" if loading else "", "cyan")))
            if d is None:
                out.append(line(("  carregant…", "dim")))
            else:
                if d.get("error"):
                    out.append(line(("  " + d["error"], "red")))
                for c in d["commits"]:
                    out.append(line("  ", (c["sha"], "yellow"), " ",
                                    clip(c["subject"], max(10, width - 16)),
                                    (f"  {ago(now - c['at'])}"
                                     if c["at"] else "", "dim")))
                if not d["commits"] and not d.get("error"):
                    out.append(line(("  cap commit", "dim")))
        if p["worktrees"]:
            out.append(Text(""))
            out.append(line(("Worktrees", "bold")))
            for w in p["worktrees"]:
                t = line("  ", (w["branch"] or "(detached)", "magenta"),
                         (f"  {os.path.relpath(w['path'], p['path'])}",
                          "dim"))
                if w["dirty"]:
                    t.append(f"  ✎{w['dirty']}", style="yellow")
                out.append(t)
        if p["git"] and d is not None and d["changes_total"]:
            out.append(Text(""))
            out.append(line(("Canvis", "bold"),
                            (f"  {d['changes_total']}", "yellow")))
            for c in d["changes"]:
                code, path = c[:2], c[3:]
                out.append(line("  ", (code, "yellow"), " ", path))
            more = d["changes_total"] - len(d["changes"])
            if more > 0:
                out.append(line((f"  … i {more} més", "dim")))
        return out

    # .. footer

    def footer(self):
        now = time.time()
        width = self.console.size[0]
        t = Text()
        if self.input:
            t.append(f" {self.input['prompt']} ", style="bold black on cyan")
            t.append(" " + self.input["buf"] + "▏")
            hint = "⏎ aplica · Esc treu el filtre" \
                if self.input["kind"] == "filter" else "⏎ continua · Esc cancel·la"
            t.append(f"   {hint}", style="dim")
            return t
        c = self.confirm
        if c and now < c["until"]:
            t.append(f" {c['msg']} ", style="bold black on yellow")
            for ln in textwrap.wrap(c.get("preview") or "", width - 2)[:4]:
                t.append("\n " + ln, style="yellow")
            t.append("\n")
        elif self.busy:
            t.append(" ⟳ " + clip(self.busy, width - 4), style="bold cyan")
            t.append("\n")
        elif self.flash[0] and now - self.flash[1] < FLASH_SECS:
            for ln in textwrap.wrap(self.flash[0], width - 2)[:3]:
                t.append(" " + ln + "\n", style="bold cyan")
        for k, what in self.keys():
            t.append(f" {k}", style="bold")
            t.append(f" {what} ", style="dim")
        if DRY_RUN:
            t.append(" [dry-run]", style="bold magenta")
        return t

    def keys(self):
        p = self.project()
        keys = [("↑↓", "mou")]
        if p:
            a = taller.pick_agent(p)
            keys.append(("⏎", f"→ {a['name']}" if a else "reprèn a herdr"))
            keys.append(("n", "agent nou"))
            if p["git"]:
                keys.append(("w", "worktree"))
            keys.append(("t", "terminal"))
            if p["git"] and IN_HERDR:
                keys.append(("g", "git"))
            if taller.web_url(p["remote"]):
                keys.append(("o", "web"))
        if any(r[0] == "head" and r[1] == "dormant" for r in self.rows) \
                and not self.filter:
            keys.append(("d", "amaga adormits" if self.show_dormant
                         else "adormits"))
        keys += [("/", "filtra"), ("u", "refresca"), ("q", "surt")]
        return keys

    # -- keys

    def ask(self, action, key, msg, preview="", **extra):
        """A second press of the same key on the same project within
        CONFIRM_SECS confirms. -> True on that second press."""
        now = time.time()
        c = self.confirm
        if c and c["action"] == action and c["key"] == key \
                and c["path"] == self.cursor and now < c["until"]:
            self.confirm = None
            return True
        self.confirm = dict(action=action, key=key, path=self.cursor,
                            until=now + CONFIRM_SECS, msg=msg,
                            preview=preview, **extra)
        return False

    def handle(self, key, live, term):
        """-> False to quit."""
        if self.input:
            return self.handle_input(key)
        if key in ("q", "\x03"):
            return False
        self.build_rows()
        page = max(1, self.list_h - 2)
        moves = {"j": 1, "\x1b[B": 1, "k": -1, "\x1b[A": -1,
                 "\x1b[6~": page, "\x1b[5~": -page,
                 "\x1b[H": -10 ** 6, "\x1b[F": 10 ** 6}
        p = self.project()
        if key in moves:
            self.move(moves[key])
        elif key == "\x1b":
            self.confirm = None
            self.filter = ""
        elif key == "/":
            self.input = {"kind": "filter", "prompt": "filtra", "buf":
                          self.filter}
        elif key == "d":
            self.show_dormant = not self.show_dormant
        elif key == "u":
            self.m.kick_collect.set()
            self.m.kick_agents.set()
            self.say("refrescant…")
        elif not p:
            return True
        elif key in ENTER:
            self.enter(p)
        elif key == "n":
            self.fresh(p)
        elif key == "w":
            self.worktree(p)
        elif key == "t":
            self.shell(p, live, term)
        elif key == "g":
            self.git_popup(p)
        elif key == "o":
            self.open_web(p)
        return True

    def handle_input(self, key):
        inp = self.input
        if key == "\x1b":
            self.input = None
            if inp["kind"] == "filter":
                self.filter = ""
        elif key in ENTER:
            self.input = None
            if inp["kind"] == "branch":
                self.worktree_asked(inp["buf"].strip())
        elif key in ("\x7f", "\x08"):
            inp["buf"] = inp["buf"][:-1]
        elif key == "\x15":   # ctrl-u
            inp["buf"] = ""
        elif len(key) == 1 and key.isprintable():
            inp["buf"] += key
        if inp["kind"] == "filter" and self.input:
            self.filter = inp["buf"]
        return True

    # -- actions

    def agent_args(self):
        return list(self.m.cfg["taller"].get("agent_args") or [])

    def run(self, what, fn, after=None):
        """`fn` (-> (ok, msg[, name])) in a thread, with `what` as progress;
        then agents and git are refreshed."""
        if self.busy:
            self.say(f"espera: {self.busy}")
            return

        def status(msg):
            self.busy = msg
            self.m.changed.set()

        def work():
            try:
                res = fn(status)
                ok, msg = res[0], res[1]
            except Exception as e:  # noqa: BLE001 -- a thread must not die silently
                ok, msg = False, f"{type(e).__name__}: {e}"
            self.busy = ""
            if ok and after:
                msg += after
            self.say(msg if ok else f"no s'ha pogut: {msg}")
            self.m.kick_agents.set()
            self.m.kick_collect.set()
        status(what)
        threading.Thread(target=work, daemon=True).start()

    def enter(self, p):
        """The project's herdr agent, or its conversation reopened there."""
        a = taller.pick_agent(p)
        if a:
            self.run(f"→ {a['name']}…", lambda s: taller.focus(a))
            return
        aoe = [x for x in p["agents"] if x["host"] == "aoe"]
        busy = [x for x in aoe if x["state"] in ("working", "waiting")]
        if busy and p.get("last_exchange"):
            self.say(f"la sessió aoe «{busy[0]['name']}» està "
                     f"{STATE_LABEL[busy[0]['state']]}: acaba-la o atura-la "
                     "abans de reprendre la conversa a herdr")
            return
        ex = p.get("last_exchange")
        name = taller.agent_name(p["name"], self.herdr_names())
        what = (f"{ex.get('tool') or 'claude'} --continue"
                + (f" («{clip(ex['title'], 40)}»)" if ex.get("title") else "")
                if ex else "un claude nou (cap conversa prèvia)")
        preview = self.where(p)
        if aoe:
            preview += (f" · la sessió aoe «{aoe[0]['name']}» hi segueix "
                        "viva: atura-la després")
        if not self.ask("resume", "\r", f"prem ⏎ de nou per obrir {name} a "
                        f"herdr: {what}", preview=preview):
            return
        after = ""
        if aoe:
            after = (" · la sessió aoe «" + aoe[0]["name"] + "» ja es pot "
                     "aturar (aoe session stop " + aoe[0]["id"] + ")")
        self.run(f"obrint {p['name']} a herdr…",
                 lambda s: taller.resume_project(p, self.agent_args(), s),
                 after)

    def fresh(self, p):
        if not self.ask("fresh", "n", f"prem n de nou per engegar un claude "
                        f"nou a {p['name']}", preview=self.where(p)):
            return
        self.run(f"engegant un agent a {p['name']}…",
                 lambda s: taller.fresh_agent(p, self.agent_args(), s))

    def where(self, p):
        a = next((x for x in p["agents"] if x["host"] == "herdr"), None)
        if a:
            return "en una pestanya nova del seu workspace de herdr"
        return f"en un workspace nou «{p['name']}» a {home(p['path'])}"

    def worktree(self, p):
        if not p["git"]:
            self.say(f"{p['name']} no és un repositori git")
            return
        c = self.confirm
        if c and c["action"] == "worktree" and c["path"] == p["path"] \
                and time.time() < c["until"]:
            self.confirm = None
            branch = c["branch"]
            self.run(f"worktree {branch}…",
                     lambda s: taller.new_worktree(p, branch,
                                                   self.agent_args(), s))
            return
        self.confirm = None
        self.input = {"kind": "branch", "buf": "",
                      "prompt": f"branca nova (de {p['branch'] or 'HEAD'})"}

    def worktree_asked(self, branch):
        p = self.project()
        if not p or not branch:
            return
        err = taller.check_branch(p, branch)
        if err:
            self.say(err)
            return
        wt = taller.worktree_dir(p["path"], branch)
        self.ask("worktree", "w", f"prem w de nou per crear el worktree "
                 f"{branch}", preview=("git fetch; " if p["remote"] else "")
                 + f"git worktree add -b "
                 f"{branch} {home(wt)} {p['branch'] or 'HEAD'}; workspace "
                 f"«{taller.branch_title(branch)}» amb claude "
                 f"«{taller.agent_name(branch, self.herdr_names())}»", branch=branch)

    def herdr_names(self):
        return {a["name"] for p in self.m.snapshot() for a in p["agents"]
                if a["host"] == "herdr"}

    def popup(self, entrypoint, cwd):
        """One of the plugin's popups; False when not inside herdr."""
        if not IN_HERDR and not DRY_RUN:
            return False
        args = ["herdr", "plugin", "pane", "open", "--plugin", PLUGIN_ID,
                "--entrypoint", entrypoint, "--placement", "popup",
                "--width", "92%", "--height", "88%", "--cwd", cwd]
        if DRY_RUN:
            self.say("dry-run: " + shlex.join(args))
            return True
        code, out, err = taller.sh(args, timeout=20)
        if code != 0:
            self.say(f"popup de herdr fallida: {clip(err or out, 100)}")
        return code == 0

    def shell(self, p, live, term):
        if self.popup("shell", p["path"]):
            return
        if term is not None:
            term.suspend(live, [os.environ.get("SHELL", "sh")], cwd=p["path"])

    def git_popup(self, p):
        if not p["git"]:
            return
        if not self.popup("git", p["path"]):
            self.say("g només funciona dins de herdr")

    def open_web(self, p):
        url = taller.web_url(p["remote"])
        if not url:
            self.say("no sé l'adreça web d'aquest remot" if p["remote"]
                     else "sense remot")
            return
        cmd = taller.browser_cmd(url)
        if not cmd:
            self.say(f"no sé obrir el navegador: {url}")
            return
        if DRY_RUN:
            self.say("dry-run: " + shlex.join(cmd))
            return
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        self.say(f"obrint {url}")


# --------------------------------------------------------------- terminal

def split_keys(data):
    out, i = [], 0
    while i < len(data):
        if data[i] == "\x1b" and i + 1 < len(data) and data[i + 1] in "[O":
            j = i + 2
            while j < len(data) and not (data[j].isalpha() or data[j] == "~"):
                j += 1
            out.append(data[i:j + 1])
            i = j + 1
        else:
            out.append(data[i])
            i += 1
    return out


class Terminal:
    """cbreak stdin for single-key input, restorable around child programs."""

    def __init__(self):
        self.fd = sys.stdin.fileno()
        self.saved = termios.tcgetattr(self.fd)

    def __enter__(self):
        tty.setcbreak(self.fd)
        return self

    def __exit__(self, *a):
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)

    def keys(self, timeout):
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return []
        data = os.read(self.fd, 64).decode(errors="ignore")
        return split_keys(data)

    def suspend(self, live, cmd, cwd=None):
        live.stop()
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)
        try:
            subprocess.run(cmd, cwd=cwd)
        except OSError as e:
            print(f"failed: {e}")
            time.sleep(2)
        finally:
            tty.setcbreak(self.fd)
            live.start(refresh=True)


# ------------------------------------------------------------------- main

def main():
    args = sys.argv[1:]
    cfg = taller.load_config()
    model = Model(cfg)

    if "--once" in args:
        # One frame on stdout, for checking the layout without a TTY. Keys
        # given with --keys are replayed first (e.g. --keys 'jj\r').
        model.sync = True
        model.collect()
        width = int(os.environ.get("COLUMNS", "160"))
        height = int(os.environ.get("LINES", "50"))
        console = Console(width=width, height=height, force_terminal=True)
        board = Board(model, console)
        board.render()
        if "--keys" in args:
            seq = args[args.index("--keys") + 1]
            for k in split_keys(seq.encode().decode("unicode_escape")):
                board.handle(k, None, None)
                board.render()
            # Background work a key started: let it land.
            deadline = time.time() + 120
            while board.busy and time.time() < deadline:
                time.sleep(0.1)
        console.print(board.render())
        return 0

    if not sys.stdin.isatty():
        print("board needs a terminal (or pass --once)", file=sys.stderr)
        return 1

    console = Console()
    board = Board(model, console)
    model.start()
    with Terminal() as term, Live(board.render(), console=console,
                                  screen=True, auto_refresh=False) as live:
        last_draw = 0
        while True:
            quit_ = False
            for k in term.keys(0.25):
                if not board.handle(k, live, term):
                    quit_ = True
                    break
                model.changed.set()
            if quit_:
                break
            now = time.time()
            if model.changed.is_set() or now - last_draw >= 1:
                model.changed.clear()
                live.update(board.render(), refresh=True)
                last_draw = now
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
