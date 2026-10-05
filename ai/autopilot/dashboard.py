#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["rich>=13.7"]
# ///
"""PR Autopilot live dashboard.

A read-only view over three sources, each refreshed at its own pace:

- agent state from aoe (`aoe ps`), every few seconds;
- autopilot's own state.json and events.jsonl, the moment they change;
- GitHub, through `scan.py snapshot` (a scan that saves nothing), every
  DASHBOARD_REFRESH_SECS and right after any event that changes the table.

It never acts on the table: the orchestrator does. The only things it sends
are the ones you ask for (go/no to the orchestrator, pause/resume).
Run it through dashboard.sh so config.sh is loaded.
"""
import fcntl
import json
import os
import select
import subprocess
import sys
import termios
import threading
import time
import tty

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.environ.get(
    "STATE_FILE", os.path.expanduser("~/.local/state/pr-autopilot/state.json"))
STATE_DIR = os.path.dirname(STATE_FILE)
EVENTS_FILE = os.path.join(STATE_DIR, "events.jsonl")
SNAPSHOT_FILE = os.path.join(STATE_DIR, "snapshot.json")
SNAPSHOT_LOCK = SNAPSHOT_FILE + ".lock"
REFRESH_SECS = int(os.environ.get("DASHBOARD_REFRESH_SECS", "120"))
MAX_REVIEW_ROUNDS = int(os.environ.get("MAX_REVIEW_ROUNDS", "3"))
AGENT_STALL_MIN = int(os.environ.get("AGENT_STALL_MIN", "35"))
PLUGIN_ID = "elboletaire.autopilot"
IN_HERDR = os.environ.get("HERDR_ENV") == "1"

LIVE_SECS = 3          # aoe ps
SESSIONS_SECS = 30     # aoe list (titles and worktree paths)
KICK_DEBOUNCE = 15     # min seconds between event-triggered GitHub refreshes
CONFIRM_SECS = 4       # window for the second press of g / n / P

# Rows by who has the next move. Agent reports and blocked agents are moved
# into NEEDS on top of these; see build().
NEEDS_ROWS = {"CAPPED", "READY", "PUSHED", "STALLED", "CLOSED"}
ORCH_ROWS = {"MERGED": "cleanup + rebase fan-out", "REVIEW": "reboot for review",
             "FEEDBACK": "send address-feedback", "BOOTING": "send review prompt"}
RUN_ROWS = {"WORKING"}
DONE_ROWS = {"DONE", "GONE"}
PICK_ROWS = {"PROPOSE"}
NOTE_ROWS = {"UNCLONED", "STALE", "UNKNOWN"}
REPORT_NEEDS = {"blocked", "failed", "stalled", "capped"}
# Events after which the GitHub view is worth refreshing early.
KICK_EVENTS = {"report", "spawn", "cleanup", "tick", "track", "detach",
               "untrack", "decline", "merged"}

AGENT_GLYPH = {"running": ("◐", "yellow"), "waiting": ("⏸", "bold red"),
               "idle": ("○", "dim"), "stopped": ("■", "dim"),
               "error": ("✗", "red")}
CI_GLYPH = {"pass": ("✓", "green"), "fail": ("✗", "bold red"),
            "pending": ("⏳", "yellow"), "none": ("–", "dim")}


# ----------------------------------------------------------------- helpers

def sh(args, timeout=30, cwd=None):
    try:
        p = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout, cwd=cwd)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        return 1, "", str(e)


def read_json(path, default=None):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return default


def ago(secs):
    if secs is None:
        return "–"
    secs = max(0, int(secs))
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h{(secs % 3600) // 60:02d}"
    return f"{secs // 86400}d"


def short(key):
    """vocdoni/vocdoni-app#452 -> vocdoni-app#452"""
    return key.split("/", 1)[1] if "/" in key else key


def split_key(key):
    for sep, kind in (("#", "pr"), ("!", "issue"), ("?", "investigate")):
        if sep in key:
            slug, num = key.split(sep, 1)
            return slug, num, kind
    return key, "", "?"


# ----------------------------------------------------------------- backend

class AoeBackend:
    """Where the agents live. Swapped for herdr when the workers move."""

    def live(self):
        code, out, _ = sh(["aoe", "ps", "--json"], timeout=20)
        try:
            rows = json.loads(out) if code == 0 and out else []
        except json.JSONDecodeError:
            rows = []
        return {r["session"]: r for r in rows if r.get("session")}

    def sessions(self):
        code, out, _ = sh(["aoe", "list", "--json"], timeout=20)
        try:
            rows = json.loads(out) if code == 0 and out else []
        except json.JSONDecodeError:
            rows = []
        return {r["id"]: r for r in rows if r.get("id")}

    def send(self, target, text):
        code, out, err = sh(["aoe", "send", target, text], timeout=60)
        return code == 0, err or out

    def attach_cmd(self, session):
        return ["aoe", "session", "attach", session]


# ------------------------------------------------------------------- model

class Model:
    """Everything the screen shows, refreshed by background threads."""

    def __init__(self, backend):
        self.backend = backend
        self.lock = threading.Lock()
        self.snap = read_json(SNAPSHOT_FILE)
        self.snap_mtime = 0
        self.snap_err = None
        self.snap_running = False
        self.snap_started = 0
        self.state = read_json(STATE_FILE, {}) or {}
        self.state_mtime = 0
        self.events = []
        self.events_size = 0
        self.live = {}
        self.sessions = {}
        self.kick = threading.Event()
        self.changed = threading.Event()

    # -- sources

    def poll_files(self):
        """state.json, events.jsonl and snapshot.json: cheap stat()s, run
        every loop. The snapshot is re-read here rather than only after our
        own refresh, so every open dashboard shows whichever refresh ran."""
        try:
            m = os.stat(SNAPSHOT_FILE).st_mtime
        except OSError:
            m = 0
        if m != self.snap_mtime:
            snap = read_json(SNAPSHOT_FILE)
            if snap is not None:
                with self.lock:
                    self.snap, self.snap_mtime = snap, m
                self.changed.set()
        try:
            m = os.stat(STATE_FILE).st_mtime
        except OSError:
            m = 0
        if m != self.state_mtime:
            st = read_json(STATE_FILE)
            if st is not None:
                with self.lock:
                    self.state, self.state_mtime = st, m
                self.changed.set()
        try:
            size = os.stat(EVENTS_FILE).st_size
        except OSError:
            size = 0
        if size != self.events_size:
            fresh = []
            try:
                with open(EVENTS_FILE) as fh:
                    if 0 < self.events_size < size:
                        fh.seek(self.events_size)
                    lines = fh.readlines()
            except OSError:
                lines = []
            for line in lines:
                try:
                    fresh.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            first = self.events_size == 0
            with self.lock:
                # A shrink means the log was trimmed: start over from it.
                self.events = (fresh if first or size < self.events_size
                               else self.events + fresh)[-200:]
                self.events_size = size
            if not first and any(e.get("kind") in KICK_EVENTS for e in fresh):
                self.kick.set()
            self.changed.set()

    def refresh_snapshot(self, force=False):
        """Run a read-only scan, unless another dashboard (the pane and a
        peek overlay, say) is already running one or ran one recently: they
        all read the same snapshot.json, so one refresh serves them all."""
        if not force:
            gen = (read_json(SNAPSHOT_FILE) or {}).get("generated_at") or 0
            if time.time() - gen < REFRESH_SECS - 5:
                return
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(SNAPSHOT_LOCK, "w") as lk:
            try:
                fcntl.flock(lk.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return
            self.snap_running, self.snap_started = True, time.time()
            self.changed.set()
            code, _, err = sh([sys.executable, os.path.join(DIR, "scan.py"),
                               "snapshot", "--quiet"], timeout=600)
            with self.lock:
                self.snap_err = None if code == 0 else \
                    (err or "snapshot failed").splitlines()[-1][:120]
                self.snap_running = False
        self.changed.set()

    def github_loop(self):
        force = False
        while True:
            self.refresh_snapshot(force)
            force = False
            deadline = time.time() + REFRESH_SECS
            while time.time() < deadline:
                if self.kick.wait(timeout=max(0.1, deadline - time.time())):
                    self.kick.clear()
                    wait = KICK_DEBOUNCE - (time.time() - self.snap_started)
                    if wait > 0:
                        time.sleep(wait)
                    force = True
                    break

    def agents_loop(self):
        last_sessions = 0
        while True:
            live = self.backend.live()
            sessions = None
            if time.time() - last_sessions > SESSIONS_SECS:
                sessions = self.backend.sessions()
                last_sessions = time.time()
            with self.lock:
                self.live = live
                if sessions is not None:
                    self.sessions = sessions
            self.changed.set()
            time.sleep(LIVE_SECS)

    def start(self):
        for fn in (self.github_loop, self.agents_loop):
            threading.Thread(target=fn, daemon=True).start()

    # -- view

    def item_for(self, items, key):
        if key in items:
            return key, items[key]
        for k, it in items.items():
            if key in (it.get("prev_keys") or []):
                return k, it
        return key, None

    def build(self):
        """Snapshot rows + live state -> {needs, orch, running, pick, done,
        notes} lists of entry dicts, plus the header numbers."""
        with self.lock:
            snap = self.snap or {}
            state = self.state or {}
            live = dict(self.live)
            sessions = dict(self.sessions)
        now = time.time()
        items = state.get("items", {}) or {}
        declined = set(state.get("declined", []) or [])
        me = state.get("me")
        out = {s: [] for s in ("needs", "orch", "running", "pick", "done",
                               "notes")}
        seen = set()

        for row in snap.get("rows", []):
            kind, key = row.get("kind"), row.get("key")
            cur_key, it = self.item_for(items, key)
            tracked_kind = kind not in PICK_ROWS | NOTE_ROWS
            # Cleaned up, detached or untracked since the snapshot.
            if tracked_kind and it is None and kind != "GONE":
                continue
            # Picked or declined since the snapshot.
            if kind in PICK_ROWS and (key in items or key in declined):
                continue
            e = self.entry(row, cur_key, it, live, sessions, now, me)
            seen.add(cur_key)
            if kind in NOTE_ROWS:
                out["notes"].append(e)
            elif kind in PICK_ROWS:
                out["pick"].append(e)
            elif kind in DONE_ROWS:
                out["done"].append(e)
            elif e["needs"]:
                out["needs"].append(e)
            elif kind in ORCH_ROWS:
                out["orch"].append(e)
            elif kind in NEEDS_ROWS:
                out["needs"].append(e)
            else:
                out["running"].append(e)

        # Spawned or tracked since the last snapshot: show them right away.
        for k, it in items.items():
            if k in seen:
                continue
            row = {"kind": "NEW", "key": k, "title": it.get("question")}
            e = self.entry(row, k, it, live, sessions, now, me)
            (out["needs"] if e["needs"] else out["running"]).append(e)

        # Oldest wait first: the longer something has waited on you, the
        # more it is costing.
        out["needs"].sort(key=lambda e: -(e["quiet"] or 0))
        hdr = {"paused": bool(state.get("paused")),
               "active": snap.get("active"), "max_active": snap.get("max_active"),
               "untracked": snap.get("untracked") or 0,
               "generated_at": snap.get("generated_at"),
               "last_tick": state.get("last_tick"),
               "orch": self.orch_target(state, sessions)}
        return out, hdr

    def entry(self, row, key, it, live, sessions, now, me):
        it = it or {}
        kind = row.get("kind")
        sess = it.get("session")
        ag = live.get(sess, {}) if sess else {}
        agent_state = ag.get("state")
        last = it.get("last_seen") or it.get("added")
        quiet = (now - last) if last else None
        rep = it.get("last_report") or {}
        # A report is current until the agent shows a later sign of life.
        rep_live = bool(rep) and rep.get("at", 0) >= (it.get("last_seen") or 0)
        needs = (kind in NEEDS_ROWS
                 or (rep_live and rep.get("state") in REPORT_NEEDS)
                 or (agent_state == "waiting" and kind not in DONE_ROWS))
        if rep_live:
            note = f"{rep.get('state')}: {rep.get('msg') or ''}"
        elif kind in ORCH_ROWS:
            note = f"next tick: {ORCH_ROWS[kind]}"
        elif kind == "NEW":
            note = "spawned, waiting for the next GitHub refresh"
        else:
            note = row.get("note") or it.get("last_note") or ""
        if agent_state == "waiting" and not rep_live:
            note = "agent is asking something" + (f" · {note}" if note else "")
        mode = it.get("mode") or row.get("mode") or \
            (row.get("fields") or {}).get("mode")
        if row.get("item_kind") == "issue" or split_key(key)[2] == "issue":
            pick_kind = "issue"
        elif mode == "comment":
            pick_kind = "review only"
        elif row.get("author") and me and row.get("author") != me:
            pick_kind = "adopt PR"
        else:
            pick_kind = "your PR"
        sinfo = sessions.get(sess, {}) if sess else {}
        return {"kind": kind, "key": key, "title": row.get("title") or
                it.get("branch") or "", "url": row.get("url"),
                "checks": row.get("checks"), "draft": row.get("draft"),
                "session": sess, "agent": agent_state,
                "rounds": it.get("review_rounds"), "driver": it.get("driver"),
                "quiet": quiet, "note": note, "needs": needs,
                "pick_kind": pick_kind, "path": sinfo.get("path"),
                "branch": it.get("branch")}

    def orch_target(self, state, sessions):
        t = os.environ.get("AUTOPILOT_ORCH") or state.get("orch") or "Autopilot"
        title = (sessions.get(t) or {}).get("title")
        return t, title or t


# -------------------------------------------------------------------- view

class Dashboard:
    def __init__(self, model, console):
        self.m = model
        self.console = console
        self.sel_key = None
        self.show_done = False
        self.flash = ("", 0)
        self.confirm = None   # (action, key, deadline)
        self.selectable = []

    def say(self, msg):
        self.flash = (msg, time.time())

    # -- rendering

    def render(self):
        data, hdr = self.m.build()
        now = time.time()
        parts = [self.header(data, hdr, now)]
        self.selectable = []
        if hdr["paused"]:
            parts.append(Text(" ⏸  PAUSED — the orchestrator acts on nothing "
                              "until resumed (P)", style="bold black on yellow"))
        parts.append(self.items_table("🔴 Needs you", data["needs"], "red"))
        parts.append(self.items_table("⏭  Next tick (orchestrator)",
                                      data["orch"], "blue"))
        parts.append(self.items_table("🟡 Running", data["running"], "yellow"))
        if self.show_done:
            parts.append(self.items_table("✔  Done / waiting on others",
                                          data["done"], "green"))
        used = sum(self.height(p) for p in parts)
        room = self.console.height - used - 16
        parts.append(self.pick_table(data["pick"], max(3, room)))
        if data["notes"]:
            parts.append(self.notes(data["notes"]))
        parts.append(self.activity(now))
        parts.append(self.footer(data, now))
        if self.sel_key not in self.selectable:
            self.sel_key = self.selectable[0] if self.selectable else None
        return Group(*[p for p in parts if p is not None])

    def height(self, renderable):
        if renderable is None:
            return 0
        if isinstance(renderable, Text):
            return 1
        return getattr(renderable, "row_count", 0) + 2

    def header(self, data, hdr, now):
        t = Text()
        t.append(" PR Autopilot ", style="bold reverse")
        t.append("  ")
        t.append(f"🔴 {len(data['needs'])} needs you", style="bold red"
                 if data["needs"] else "dim")
        t.append(" · ")
        t.append(f"🟡 {len(data['running']) + len(data['orch'])} running",
                 style="yellow")
        t.append(" · ")
        t.append(f"⚪ {len(data['pick'])} to pick")
        if hdr["active"] is not None:
            t.append(f" · {hdr['active']}/{hdr['max_active']} slots")
            if hdr["untracked"]:
                t.append(f" (+{hdr['untracked']} untracked)", style="dim")
        t.append("\n ")
        gen = hdr["generated_at"]
        if self.m.snap_running:
            t.append("GitHub ⟳ refreshing", style="cyan")
        elif gen:
            age = now - gen
            style = "green" if age < REFRESH_SECS * 1.5 else \
                "yellow" if age < REFRESH_SECS * 4 else "red"
            t.append(f"GitHub {ago(age)} ago", style=style)
        else:
            t.append("GitHub: no snapshot yet", style="yellow")
        if self.m.snap_err:
            t.append(f" ({self.m.snap_err})", style="red")
        t.append("  ·  last tick ")
        t.append(ago(now - hdr["last_tick"]) + " ago" if hdr["last_tick"]
                 else "never", style="dim")
        t.append(f"  ·  orchestrator {hdr['orch'][1]}", style="dim")
        t.append(f"  ·  {time.strftime('%H:%M:%S')}", style="dim")
        return t

    def items_table(self, title, rows, color):
        if not rows:
            return None
        tb = Table(title=title, title_justify="left", title_style=f"bold {color}",
                   box=box.SIMPLE_HEAD, expand=True, pad_edge=False,
                   show_edge=False)
        tb.add_column("", width=1, no_wrap=True)
        tb.add_column("Item", no_wrap=True, style="bold")
        tb.add_column("Title", ratio=3, no_wrap=True, overflow="ellipsis")
        tb.add_column("State", no_wrap=True)
        tb.add_column("CI", width=2, no_wrap=True, justify="center")
        tb.add_column("Rnd", no_wrap=True, justify="right")
        tb.add_column("Quiet", no_wrap=True, justify="right")
        tb.add_column("Note", ratio=2, no_wrap=True, overflow="ellipsis")
        for e in rows:
            self.selectable.append(e["key"])
            sel = e["key"] == self.sel_key
            state = Text(e["kind"].lower())
            if e["agent"]:
                g, st = AGENT_GLYPH.get(e["agent"], ("?", "dim"))
                state = Text.assemble((g + " ", st), e["kind"].lower())
            ci = Text(*CI_GLYPH.get(e["checks"] or "", ("", "")))
            rnd = f"{e['rounds'] or 0}/{MAX_REVIEW_ROUNDS}" \
                if e["rounds"] is not None or e["driver"] == "agent" else ""
            stalled = e["driver"] == "agent" and e["quiet"] and \
                e["quiet"] >= AGENT_STALL_MIN * 60
            quiet = Text(ago(e["quiet"]), style="red" if stalled else "")
            tb.add_row("▶" if sel else "", short(e["key"]),
                       ("[draft] " if e["draft"] else "") + (e["title"] or ""),
                       state, ci, rnd, quiet, e["note"],
                       style="reverse" if sel else None)
        return tb

    def pick_table(self, rows, limit):
        tb = Table(title=f"⚪ Pick next ({len(rows)})", title_justify="left",
                   title_style="bold", box=box.SIMPLE_HEAD, expand=True,
                   pad_edge=False, show_edge=False)
        tb.add_column("", width=1, no_wrap=True)
        tb.add_column("#", justify="right", no_wrap=True, style="dim")
        tb.add_column("Item", no_wrap=True, style="bold")
        tb.add_column("Title", ratio=1, no_wrap=True, overflow="ellipsis")
        tb.add_column("Kind", no_wrap=True)
        shown = rows
        if self.sel_key in [e["key"] for e in rows[limit:]]:
            idx = [e["key"] for e in rows].index(self.sel_key)
            shown = rows[max(0, idx - limit + 1): idx + 1]
        else:
            shown = rows[:limit]
        for e in rows:
            self.selectable.append(e["key"])
        for e in shown:
            n = rows.index(e) + 1
            sel = e["key"] == self.sel_key
            tb.add_row("▶" if sel else "", str(n), short(e["key"]),
                       e["title"] or "", e["pick_kind"],
                       style="reverse" if sel else None)
        if len(rows) > len(shown):
            tb.add_row("", "", Text(f"+{len(rows) - len(shown)} more (↑/↓ to "
                                    "scroll)", style="dim"), "", "")
        return tb

    def notes(self, rows):
        t = Text(" notes: ", style="dim")
        for e in rows:
            t.append(f"{e['kind'].lower()} {short(e['key'])}  ", style="dim")
        return t

    def activity(self, now):
        with self.m.lock:
            evs = [e for e in self.m.events if e.get("kind") != "tick"][-6:]
        tb = Table(title="Activity", title_justify="left", title_style="bold dim",
                   box=None, expand=True, show_header=False, pad_edge=False)
        tb.add_column(no_wrap=True, style="dim")
        tb.add_column(no_wrap=True)
        tb.add_column(no_wrap=True, style="bold")
        tb.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
        if not evs:
            tb.add_row("", Text("no events yet", style="dim"), "", "")
        for e in reversed(evs):
            kind = e.get("kind", "")
            style = {"report": "magenta", "spawn": "cyan", "cleanup": "green",
                     "capped": "red"}.get(kind, "")
            detail = " ".join(str(e[f]) for f in ("state", "round", "phase",
                                                  "branch", "msg", "note")
                              if e.get(f) not in (None, ""))
            tb.add_row(time.strftime("%H:%M", time.localtime(e.get("at", 0))),
                       Text(kind, style=style), short(e.get("key", "")), detail)
        return tb

    def footer(self, data, now):
        msg, at = self.flash
        t = Text()
        if self.confirm and now < self.confirm[2]:
            t.append(f" {self.confirm[3]} ", style="bold black on yellow")
            t.append("\n")
        elif msg and now - at < 6:
            t.append(f" {msg}", style="bold cyan")
            t.append("\n")
        keys = [("↑↓/jk", "move"), ("⏎", "open agent"), ("t", "shell"),
                ("o", "browser"), ("g/n", "go/no"), ("a", "orchestrator"),
                ("r", "refresh"), ("d", "done"), ("P", "pause"), ("q", "quit")]
        for k, what in keys:
            t.append(f" {k}", style="bold")
            t.append(f" {what} ", style="dim")
        return t

    # -- actions

    def selected(self):
        data, _ = self.m.build()
        for section in data.values():
            for e in section:
                if e["key"] == self.sel_key:
                    return e
        return None

    def move(self, d):
        if not self.selectable:
            return
        try:
            i = self.selectable.index(self.sel_key)
        except ValueError:
            i = 0
        self.sel_key = self.selectable[max(0, min(len(self.selectable) - 1,
                                                  i + d))]

    def ask(self, action, key, prompt):
        """Second press of the same key within CONFIRM_SECS confirms."""
        now = time.time()
        c = self.confirm
        if c and c[0] == action and c[1] == key and now < c[2]:
            self.confirm = None
            return True
        self.confirm = (action, key, now + CONFIRM_SECS, prompt)
        return False

    def to_orch(self, text):
        _, hdr = self.m.build()
        target, title = hdr["orch"]
        ok, err = self.m.backend.send(target, text)
        self.say(f"sent '{text}' to {title}" if ok else f"send failed: {err}")

    def popup(self, entrypoint, env, cwd=None):
        """Open one of the plugin's popups; False when not inside herdr."""
        if not IN_HERDR:
            return False
        args = ["herdr", "plugin", "pane", "open", "--plugin", PLUGIN_ID,
                "--entrypoint", entrypoint, "--placement", "popup",
                "--width", "92%", "--height", "88%"]
        for k, v in env.items():
            args += ["--env", f"{k}={v}"]
        if cwd:
            args += ["--cwd", cwd]
        code, out, err = sh(args, timeout=20)
        if code != 0:
            self.say(f"herdr popup failed: {(err or out)[:100]}")
        return code == 0

    def handle(self, key, live, term):
        e = self.selected()
        if key in ("q", "\x03"):
            return False
        if key in ("j", "\x1b[B"):
            self.move(1)
        elif key in ("k", "\x1b[A"):
            self.move(-1)
        elif key in ("\x1b[5~",):
            self.move(-10)
        elif key in ("\x1b[6~",):
            self.move(10)
        elif key == "r":
            self.m.kick.set()
            self.say("refreshing from GitHub…")
        elif key == "d":
            self.show_done = not self.show_done
        elif key == "P":
            paused = bool((self.m.state or {}).get("paused"))
            verb = "resume" if paused else "pause"
            if self.ask("P", "", f"press P again to {verb} autopilot"):
                code, out, err = sh([sys.executable,
                                     os.path.join(DIR, "scan.py"), verb])
                self.say(out or err)
        elif key == "a":
            _, hdr = self.m.build()
            self.attach(hdr["orch"][0], live, term)
        elif not e:
            return True
        elif key in ("\r", "\n"):
            if e["session"]:
                self.attach(e["session"], live, term)
            else:
                self.say("no session for this row")
        elif key == "t":
            if e["path"] and os.path.isdir(e["path"]):
                self.shell(e["path"], live, term)
            else:
                self.say("no worktree for this row")
        elif key == "o":
            self.browse(e)
        elif key in ("g", "n") and e["kind"] == "PROPOSE":
            verb = "go" if key == "g" else "no"
            if self.ask(key, e["key"], f"press {key} again to send "
                        f"'{verb} {e['key']}' to the orchestrator"):
                self.to_orch(f"{verb} {e['key']}")
        elif key in ("g", "n"):
            self.say("go/no only applies to Pick next rows")
        return True

    def attach(self, session, live, term):
        if self.popup("attach", {"AP_SESSION": session}):
            return
        term.suspend(live, self.m.backend.attach_cmd(session))

    def shell(self, path, live, term):
        if self.popup("shell", {}, cwd=path):
            return
        term.suspend(live, [os.environ.get("SHELL", "sh")], cwd=path)

    def browse(self, e):
        slug, num, kind = split_key(e["key"])
        if kind not in ("pr", "issue"):
            self.say("nothing to open for an investigation")
            return
        args = ["gh", "pr" if kind == "pr" else "issue", "view", num, "-R",
                slug, "--web"]
        subprocess.Popen(args, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        self.say(f"opening {short(e['key'])} in the browser")


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
        """Keys typed since the last call. One read can carry several
        (fast typing, key repeat), so it is split into single characters
        and whole escape sequences."""
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
    backend = AoeBackend()
    model = Model(backend)

    if "--once" in args:
        # One frame on stdout, for checking the layout without a TTY.
        if "--refresh" in args:
            model.refresh_snapshot(force=True)
        model.poll_files()
        model.live = backend.live()
        model.sessions = backend.sessions()
        width = int(os.environ.get("COLUMNS", "160"))
        height = int(os.environ.get("LINES", "50"))
        console = Console(width=width, height=height, force_terminal=True)
        console.print(Dashboard(model, console).render())
        return 0

    if not sys.stdin.isatty():
        print("dashboard needs a terminal (or pass --once)", file=sys.stderr)
        return 1

    console = Console()
    dash = Dashboard(model, console)
    model.poll_files()
    model.start()
    with Terminal() as term, Live(dash.render(), console=console, screen=True,
                                  auto_refresh=False) as live:
        last_draw = 0
        while True:
            quit_ = False
            for k in term.keys(0.25):
                if not dash.handle(k, live, term):
                    quit_ = True
                    break
                model.changed.set()
            if quit_:
                break
            model.poll_files()
            now = time.time()
            if model.changed.is_set() or now - last_draw >= 1:
                model.changed.clear()
                live.update(dash.render(), refresh=True)
                last_draw = now
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
