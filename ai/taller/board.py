#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["rich>=13.7"]
# ///
"""Taller: every project the user works on, as one list, and what to do next.

- The list (taller.collect()): projects in four sections -- 🔴 Et necessita
  (an agent waiting on you, broken, or done and not looked at yet),
  🟡 Treballant, 🗂 Aparcats (newest first) and 💤 Adormits (one line until
  `d`). Each row: its agents' glyphs, name, branch,
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
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
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
# The Taller workspace runs the board as a column beside the orchestrator
# (herdr/open.sh): the detail always goes below the list there.
COLUMN = os.environ.get("TALLER_LAYOUT") == "column"
LIST_SHARE = 0.65      # of the column's height, for the list
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
    """The projects, kept fresh by background threads: herdr agents
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
    """✎ uncommitted, ↑ unpushed, ⚠ no remote, ✗ git error -- of the folder
    alone: each worktree has its own row."""
    t = Text(no_wrap=True)
    if p["dirty"]:
        t.append(f"✎{p['dirty']} ", style="yellow")
    if p["ahead"]:
        t.append(f"↑{p['ahead']} ", style="cyan")
    if p["git"] and "no_remote" in p["flags"]:
        t.append("⚠ ", style="bold red")
    if "error" in p["flags"]:
        t.append("✗ ", style="red")
    t.rstrip()
    return t


def first_pane_id(d):
    """The first pane_id anywhere in a herdr result (a plugin popup's sits at
    .plugin_pane.pane.pane_id)."""
    if isinstance(d, dict):
        if isinstance(d.get("pane_id"), str):
            return d["pane_id"]
        for v in d.values():
            found = first_pane_id(v)
            if found:
                return found
    return None


def chrome():
    """(columns, rows) a section's frame takes: a box's borders and padding,
    or in the column (herdr frames the pane already) a title line and a
    one-column indent."""
    return (2, 1) if COLUMN else (4, 2)


def section(body, title, height, style):
    """A titled section of the screen: a box, or in the column a title line
    over the body, indented by one."""
    if COLUMN:
        return Group(Rule(title, align="left", style=style),
                     Padding(body, (0, 0, 0, 1)))
    return Panel(body, title=title, title_align="left", height=height,
                 border_style=style, padding=(0, 1))


def row_path(r):
    """The folder a list row stands for; None for heads and the dormant
    line."""
    if r[0] == "project":
        return r[1]["path"]
    if r[0] in ("worktree", "sleeper"):
        return r[2]["path"]
    return None


def agent_glyphs(agents):
    """One glyph per agent, in its state's colour."""
    t = Text(no_wrap=True)
    for a in agents:
        g, style = AGENT_GLYPH.get(a["state"], AGENT_GLYPH["unknown"])
        t.append(g, style=style)
    return t


class Board:
    def __init__(self, model, console):
        self.m = model
        self.console = console
        self.cursor = None        # selected folder's path (project or worktree)
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
        ("worktree", p, worktree, section) | ("sleeper", p, worktree) |
        ("dormant", projects, sleepers)], and the cursor kept on a project
        or a worktree. A worktree put to sleep on its own leaves its
        project's rows for the dormant section's."""
        projects = self.visible(self.m.snapshot())
        groups = taller.sections(projects)
        sleepers = taller.sleepers(projects)
        rows = []
        for sec in taller.SECTIONS:
            ps = groups[sec]
            extra = sleepers if sec == "dormant" else []
            if not ps and not extra:
                continue
            rows.append(("head", sec, len(ps) + len(extra)))
            if sec == "dormant" and not (self.show_dormant or self.filter):
                rows.append(("dormant", ps, extra))
                continue
            for p in ps:
                rows.append(("project", p, sec))
                rows += [("worktree", p, w, sec)
                         for w in taller.awake_worktrees(p)]
            rows += [("sleeper", p, w) for p, w in extra]
        self.rows = rows
        paths = self.paths()
        if self.cursor not in paths:
            self.cursor = paths[0] if paths else None
        return rows

    def paths(self):
        """The folders the cursor can be on, in list order."""
        return [row_path(r) for r in self.rows if row_path(r)]

    def row(self):
        return next((r for r in self.rows if row_path(r) == self.cursor),
                    None)

    def project(self):
        """The selected row's project (a worktree's: its repo)."""
        r = self.row()
        return r[1] if r else None

    def selected(self):
        """The selected folder (taller.folder): the main checkout or a
        worktree, what the actions and the detail work on."""
        r = self.row()
        return taller.folder(r[1], self.cursor) if r else None

    def move(self, d):
        paths = self.paths()
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
        p = self.selected()
        if COLUMN:
            # The keys between the list and the detail, a blank line under
            # them; the list no taller than its rows (title line, header and
            # a blank line), the detail gets the rest.
            room = max(8, height - foot_h - 1)
            list_h = max(6, int(room * LIST_SHARE))
            list_h = min(list_h, max(6, len(self.rows) + 3))
            root.split_column(
                Layout(self.list_panel(width, list_h), name="list",
                       size=list_h),
                Layout(Padding(foot, (0, 0, 1, 0)), name="foot",
                       size=foot_h + 1),
                Layout(self.detail_panel(p, width, room - list_h),
                       name="detail"))
            return root
        root.split_column(Layout(name="body", size=body_h),
                          Layout(foot, name="foot", size=foot_h))
        if width >= SIDE_MIN:
            side_w = max(40, int(width * SIDE_SHARE))
            root["body"].split_row(
                Layout(self.list_panel(width - side_w, body_h), name="list"),
                Layout(self.detail_panel(p, side_w, body_h), name="detail",
                       size=side_w))
        else:
            list_h = max(6, int(body_h * 0.5))
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
            if sec == "dormant":
                n += len(taller.sleepers(projects))
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
        cw, ch = chrome()
        inner_h = height - ch
        title = Text("📂 Projectes", style="bold")
        if self.m.projects is None:
            msg = self.m.err or "llegint els projectes…"
            return section(Text(msg, style="red" if self.m.err else "dim"),
                           title, height, "green")
        head = self.header(width - cw)
        self.list_h = max(3, inner_h - 2)
        table = self.table(width - cw, self.list_h)
        parts = [head, Text(""), table]
        if not self.rows:
            parts.append(Text("cap projecte" + (" amb aquest filtre"
                                                if self.filter else ""),
                              style="dim"))
        return section(Group(*parts), title, height, "green")

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
        idx = next((i for i, r in enumerate(rows)
                    if row_path(r) == self.cursor), 0)
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
                names = ", ".join([p["name"] for p in r[1]] + [
                    f"{p['name']}/{os.path.basename(w['path'])}"
                    for p, w in r[2]])
                tb.add_row("", "", Text(f"{names}", style="dim italic",
                                        no_wrap=True, overflow="ellipsis"),
                           Text("d desplega", style="dim"), "", "", "")
            elif r[0] in ("worktree", "sleeper"):
                p, w = r[1], r[2]
                f = taller.folder(p, w["path"])
                sel = w["path"] == self.cursor
                dim = r[0] == "sleeper" or r[3] == "dormant"
                name = Text(no_wrap=True, overflow="ellipsis")
                if r[0] == "sleeper":
                    name.append(p["name"] + "/", style="grey50")
                else:
                    shown = taller.awake_worktrees(p)
                    fork = "└ " if w is shown[-1] else "├ "
                    name.append(fork, style="grey50")
                name.append(os.path.basename(w["path"]),
                            style="bold" if sel else
                            ("grey50" if dim else ""))
                branch = Text(w["branch"] or "(detached)",
                              style="grey50" if dim else "magenta")
                at = (f["last_exchange"] or {}).get("at")
                touch = Text(ago(now - at) if at else "", style="dim")
                tb.add_row("▶" if sel else "", agent_glyphs(f["agents"]),
                           name, branch, row_flags(f), "", touch,
                           style="reverse" if sel else None)
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
                main = taller.folder(p)
                tb.add_row("▶" if sel else "", agent_glyphs(main["agents"]),
                           name, branch, row_flags(main), wt, touch,
                           style="reverse" if sel else None)
        return tb

    # .. the detail

    def detail_panel(self, p, width, height):
        cw, ch = chrome()
        inner_w, inner_h = width - cw, height - ch
        if not p:
            return section(Text("cap projecte seleccionat", style="dim"),
                           Text("Detall", style="bold"), height, "grey35")
        lines = self.detail_lines(p, inner_w)
        if len(lines) > inner_h:
            lines = lines[:inner_h - 1] + [Text("…", style="dim")]
        title = (f"{p['repo_name']} ⑂ {p['name']}" if p.get("worktree")
                 else p["name"])
        return section(Group(*lines), Text(title, style="bold"), height,
                       "grey35")

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
        for a in p["agents"]:
            g, style = AGENT_GLYPH.get(a["state"], AGENT_GLYPH["unknown"])
            t = line("  ", (g + " ", style), (a["name"], "bold"),
                     (f"  {a['tool'] or '?'} · ", "dim"),
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
        p = self.selected()
        keys = [("↑↓", "mou")]
        if p:
            a = taller.pick_agent(p)
            keys.append(("⏎", f"→ {a['name']}" if a else "reprèn a herdr"))
            keys.append(("v", "mostra"))
            keys.append(("n", "agent nou"))
            if p["git"]:
                keys.append(("w", "worktree"))
            keys.append(("t", "terminal"))
            if p["git"] and IN_HERDR:
                keys.append(("g", "git"))
            if taller.web_url(p["remote"]):
                keys.append(("o", "web"))
            keys.append(("z", "desperta" if self.slept(p) else "adorm"))
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
            return not self.ask("quit", "q",
                                "prem q o ctrl-c de nou per sortir")
        self.build_rows()
        page = max(1, self.list_h - 2)
        moves = {"j": 1, "\x1b[B": 1, "k": -1, "\x1b[A": -1,
                 "\x1b[6~": page, "\x1b[5~": -page,
                 "\x1b[H": -10 ** 6, "\x1b[F": 10 ** 6}
        p = self.selected()
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
            self.worktree(self.project())
        elif key == "v":
            self.agent_popup(p)
        elif key == "t":
            self.shell(p, live, term)
        elif key == "g":
            self.git_popup(p)
        elif key == "o":
            self.open_web(p)
        elif key == "z":
            self.sleep(p)
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
        ex = p.get("last_exchange")
        name = taller.agent_name(p["name"], self.herdr_names())
        what = (f"{ex.get('tool') or 'claude'} --continue"
                + (f" («{clip(ex['title'], 40)}»)" if ex.get("title") else "")
                if ex else "un claude nou (cap conversa prèvia)")
        if not self.ask("resume", "\r", f"prem ⏎ de nou per obrir {name} a "
                        f"herdr: {what}", preview=self.where(p)):
            return
        self.run(f"obrint {p['name']} a herdr…",
                 lambda s: taller.resume_project(p, self.agent_args(), s))

    def fresh(self, p):
        if not self.ask("fresh", "n", f"prem n de nou per engegar un claude "
                        f"nou a {p['name']}", preview=self.where(p)):
            return
        self.run(f"engegant un agent a {p['name']}…",
                 lambda s: taller.fresh_agent(p, self.agent_args(), s))

    def slept(self, p):
        """Is the folder() asleep: put to sleep itself, or a worktree of a
        project put to sleep whole?"""
        repo = next((x for x in self.m.snapshot()
                     if x["path"] == p["repo"]), p)
        return taller.asleep(repo, p["path"]) or (
            p.get("worktree") is not None and taller.asleep(repo))

    def sleep(self, p):
        """z: the folder to sleep (the project row: the main checkout with
        every worktree; a worktree row: that one alone), its herdr
        workspaces closed -- or, asleep already, woken up."""
        if self.slept(p):
            path = p["path"] if p["path"] in p.get("slept", {}) else p["repo"]
            ok, msg = taller.wake_up(path)
            self.say(msg)
            self.m.kick_collect.set()
            return
        whole = p.get("worktree") is None
        name = self.list_name(p)
        scope = (f"{name} i els seus {len(p['worktrees'])} worktrees"
                 if whole and p["worktrees"] else name)
        agents = self.project()["agents"] if whole else p["agents"]
        notes = []
        if agents:
            notes.append("tanca " + ", ".join(a["name"] for a in agents)
                         + " i el seu workspace")
        busy = [a["name"] for a in agents if a["state"] == "working"]
        if busy:
            notes.append("⚠ treballant: " + ", ".join(busy))
        dirty = p["dirty"] + (sum(w["dirty"] for w in p["worktrees"])
                              if whole else 0)
        if dirty:
            notes.append(f"⚠ {dirty} fitxers sense commit (es queden)")
        if not self.ask("sleep", "z", f"prem z de nou per adormir {scope}",
                        preview="; ".join(notes)):
            return
        self.run(f"adormint {name}…",
                 lambda s: taller.put_to_sleep(p, whole, s))

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

    def open_popup(self, entrypoint, cwd, env=None, title=None):
        """One of the plugin's popups, its pane labelled `title` when given.
        -> (ok, message); not ok when not inside herdr."""
        if not IN_HERDR and not DRY_RUN:
            return False, "només funciona dins de herdr"
        args = ["herdr", "plugin", "pane", "open", "--plugin", PLUGIN_ID,
                "--entrypoint", entrypoint, "--placement", "popup",
                "--width", "92%", "--height", "88%", "--cwd", cwd]
        for k, v in (env or {}).items():
            args += ["--env", f"{k}={v}"]
        rename = ["herdr", "pane", "rename", "<popup>", title] if title else None
        if DRY_RUN:
            return True, "dry-run: " + " ; ".join(
                shlex.join(a) for a in (args, rename) if a)
        code, out, err = taller.sh(args, timeout=20)
        if code != 0:
            return False, f"popup de herdr fallida: {clip(err or out, 100)}"
        pane = first_pane_id((taller._json(out) or {}).get("result"))
        if rename and pane:
            taller.herdr(["pane", "rename", pane, title], timeout=10)
        return True, ""

    def popup(self, entrypoint, cwd, env=None, title=None):
        """open_popup(), saying how it went. -> ok."""
        ok, msg = self.open_popup(entrypoint, cwd, env, title)
        if msg and (ok or IN_HERDR or DRY_RUN):
            self.say(msg)
        return ok

    @staticmethod
    def list_name(p):
        """A folder() as its row reads in the list: the project's name, or
        a worktree's folder."""
        return os.path.basename(p["path"]) if p.get("worktree") else p["name"]

    def agent_popup(self, p):
        """The folder's agent (one waiting on you first) in a popup over the
        board, without leaving it. With none, its last conversation is
        resumed in the background first (no focus taken), then shown."""
        a = taller.pick_agent(p)
        if a:
            if self.popup("agent", p["path"], {"TALLER_AGENT": a["name"]},
                          self.list_name(p)):
                if not DRY_RUN:
                    self.say("ctrl+b q tanca la finestra")
            else:
                self.say("b només funciona dins de herdr")
            return

        def work(status):
            ok, msg, name = taller.resume_project(p, self.agent_args(),
                                                  status, focus=False)
            if not ok:
                return ok, msg
            ok, shown = self.open_popup("agent", p["path"],
                                        {"TALLER_AGENT": name},
                                        self.list_name(p))
            if DRY_RUN:
                return ok, f"{msg} ; {shown}"
            return ok, ("ctrl+b q tanca la finestra" if ok
                        else f"{name} engegat, però {shown}")
        self.run(f"engegant {p['name']} en segon pla…", work)

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
        self.cbreak()
        return self

    def cbreak(self):
        """cbreak without ISIG, so ctrl-c reaches handle() as \\x03 (and
        asks first) instead of killing the board."""
        tty.setcbreak(self.fd)
        attrs = termios.tcgetattr(self.fd)
        attrs[3] &= ~termios.ISIG
        termios.tcsetattr(self.fd, termios.TCSADRAIN, attrs)

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
            self.cbreak()
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
