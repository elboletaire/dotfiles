#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["rich>=13.7"]
# ///
"""Octopilot live dashboard.

A read-only view over three sources, each refreshed at its own pace:

- agent state from herdr (`herdr agent list`), every few seconds;
- octopilot's own state.json and events.jsonl, the moment they change;
- GitHub, through `scan.py snapshot` (a scan that saves nothing), every
  DASHBOARD_REFRESH_SECS and right after any event that changes the table.

It never acts on the table: the orchestrator does. The only things it sends
are the ones you ask for (go/no to the orchestrator, pause/resume).
Run it through dashboard.sh so config.sh is loaded.
"""
import collections
import fcntl
import json
import os
import select
import shutil
import subprocess
import sys
import termios
import threading
import time
import tty

from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

DIR = os.path.dirname(os.path.abspath(__file__))
# scan.py's herdr layer is the one source of truth for where an agent runs and
# how to reach it.
sys.path.insert(0, DIR)
import scan  # noqa: E402
STATE_FILE = os.environ.get(
    "STATE_FILE", os.path.expanduser("~/.local/state/octopilot/state.json"))
STATE_DIR = os.path.dirname(STATE_FILE)
EVENTS_FILE = os.path.join(STATE_DIR, "events.jsonl")
SNAPSHOT_FILE = os.path.join(STATE_DIR, "snapshot.json")
SNAPSHOT_LOCK = SNAPSHOT_FILE + ".lock"
# What each item last sent a desktop notification for, shared by every open
# dashboard so only one of them notifies.
NOTIFIED_FILE = os.path.join(STATE_DIR, "notified.json")
NOTIFIED_LOCK = NOTIFIED_FILE + ".lock"
NOTIFY_WHY = {"READY": "ready to merge", "CAPPED": "out of review rounds",
              "PUSHED": "stale: pushed, never re-requested",
              "STALLED": "agent not reporting", "stalled": "agent not reporting",
              "CLOSED": "closed without merging", "blocked": "agent is blocked",
              "failed": "agent's CI is failing", "capped": "out of review rounds",
              "asking": "agent is asking something"}
REFRESH_SECS = int(os.environ.get("DASHBOARD_REFRESH_SECS", "120"))
MAX_REVIEW_ROUNDS = int(os.environ.get("MAX_REVIEW_ROUNDS", "3"))
AGENT_STALL_MIN = int(os.environ.get("AGENT_STALL_MIN", "35"))
PLUGIN_ID = "elboletaire.octopilot"
IN_HERDR = os.environ.get("HERDR_ENV") == "1"

LIVE_SECS = 3          # herdr agent list
SESSIONS_SECS = 30     # herdr workspaces (titles, worktree paths)
META_SOURCE = "octopilot"
META_TTL_MS = 10 * 60 * 1000   # sidebar tokens vanish if the dashboard dies
META_EVERY = 180               # re-push unchanged tokens before they expire
KICK_DEBOUNCE = 15     # min seconds between event-triggered GitHub refreshes
CONFIRM_SECS = 4       # window for the second press of g / n / P
KITCHEN_SECS = 15      # the kitchen-closed alert cancels itself after this
KITCHEN_GRACE = 0.5    # a g this soon after the alert opened is a typed-ahead
                       # ggg, not a confirmation of something seen
PROMPTER_AGENT = "octopilot-prompter"   # herdr/open.sh's prompter pane
# Appended to a request the user already confirmed past WIND_DOWN_AT.
CONFIRMED = "(confirmed past wind-down)"

# Rows by who has the next move. Agent reports and blocked agents are moved
# into NEEDS on top of these; see build().
NEEDS_ROWS = {"CAPPED", "READY", "PUSHED", "STALLED", "CLOSED"}
ORCH_ROWS = {"MERGED": "cleanup + rebase fan-out", "REVIEW": "reboot for review",
             "FEEDBACK": "send address-feedback", "BOOTING": "send review prompt"}
RUN_ROWS = {"WORKING"}
DONE_ROWS = {"DONE", "GONE"}
# Rows that keep a parked card out of Done, whatever the snapshot's age: each
# needs the orchestrator or the user now.
PARK_EXEMPT = {"MERGED", "CLOSED", "GONE", "FEEDBACK"}
PICK_ROWS = {"PROPOSE"}
NOTE_ROWS = {"UNCLONED", "STALE", "UNKNOWN"}
REPORT_NEEDS = {"blocked", "failed", "stalled", "capped"}
# Events after which the GitHub view is worth refreshing early.
KICK_EVENTS = {"report", "spawn", "sent", "cleanup", "tick", "track", "detach",
               "park", "unpark", "untrack", "decline", "merged"}

AGENT_GLYPH = {"running": ("◐", "yellow"), "waiting": ("⏸", "bold red"),
               "idle": ("○", "dim"), "stopped": ("■", "dim"),
               "error": ("✗", "red")}
CI_GLYPH = {"pass": ("✓", "green"), "fail": ("✗", "bold red"),
            "pending": ("⏳", "yellow"), "none": ("–", "dim")}
# The pick tree's room the board never takes: its title, eight rows, "+N more".
PICK_MIN_LINES = 10
# Pick repo headers are selectable under this prefix, which no row key has.
REPO_PREFIX = "repo:"


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


def desktop(title, body):
    """Fire-and-forget KDE/freedesktop notification."""
    try:
        subprocess.Popen(["notify-send", "-a", "Octopilot", title, body],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def split_key(key):
    for sep, kind in (("#", "pr"), ("!", "issue"), ("?", "investigate")):
        if sep in key:
            slug, num = key.split(sep, 1)
            return slug, num, kind
    return key, "", "?"


def pick_ref(key):
    """vocdoni/vocdoni-app#452 -> #452 (the repo is the header above it)"""
    return key[len(split_key(key)[0]):] or key


def repo_key(slug):
    """The key of a pick repo's header line, so the header can be selected."""
    return REPO_PREFIX + slug


# ----------------------------------------------------------------- backend

class Hosts:
    """Where the agents live: herdr workspaces, through scan.py so the
    dashboard and the orchestrator agree on them."""

    def live(self):
        return scan.all_live()

    def sessions(self):
        return {r["id"]: r for r in scan.all_sessions()[0]}

    def send(self, address, text):
        return scan.send_to(address, text)

    def focus(self, session, live):
        """Bring the item's herdr agent forward, or its workspace."""
        target = (live.get(session) or {}).get("pane")
        args = ["agent", "focus", target] if target else \
            ["workspace", "focus", session]
        return scan.herdr(args)[0] == 0

    def publish(self, entries):
        """Octopilot's view of each herdr agent, as pane metadata tokens the
        herdr sidebar renders ($ap_kind, $ap_pr, ...; see herdr/README.md)."""
        for pane, tokens in entries:
            args = ["pane", "report-metadata", pane, "--source", META_SOURCE,
                    "--ttl-ms", str(META_TTL_MS)]
            for k, v in tokens.items():
                args += ["--token", f"{k}={v}"] if v else ["--clear-token", k]
            scan.herdr(args, timeout=10)


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

    def publish_loop(self):
        """Mirror each herdr agent's row into the herdr sidebar: on change,
        and again before the tokens' TTL runs out."""
        last, last_at = {}, 0
        while True:
            time.sleep(5)
            data, _ = self.build()
            self.notify(data)
            cur = {}
            for section in ("needs", "orch", "running", "done"):
                for e in data[section]:
                    if e["pane"]:
                        cur[e["pane"]] = sidebar_tokens(e, section)
            stale = time.time() - last_at > META_EVERY
            push = [(p, t) for p, t in cur.items() if stale or last.get(p) != t]
            if push:
                self.backend.publish(push)
            if stale:
                last_at = time.time()
            last = cur

    def notify(self, data):
        """A desktop notification when an item enters Needs you, once per
        item and reason; herdr's own toasts stay inside herdr. The first run
        only records what is already there, so a fresh dashboard does not
        replay old news."""
        if self.snap is None or not shutil.which("notify-send"):
            return
        now_needs = {e["key"]: e for e in data["needs"]}
        with open(NOTIFIED_LOCK, "w") as lk:
            fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
            first = not os.path.exists(NOTIFIED_FILE)
            sent = read_json(NOTIFIED_FILE) or {}
            out = {}
            for k, e in now_needs.items():
                why = e["why"] or "needs you"
                out[k] = why
                if not first and sent.get(k) != why:
                    desktop(f"🔴 {short(k)}: {NOTIFY_WHY.get(why, why)}",
                            f"{e['title']}\n{(e['note'] or '')[:200]}")
            if out != sent or first:
                tmp = f"{NOTIFIED_FILE}.tmp.{os.getpid()}"
                with open(tmp, "w") as fh:
                    json.dump(out, fh)
                os.replace(tmp, NOTIFIED_FILE)

    def start(self):
        for fn in (self.github_loop, self.agents_loop, self.publish_loop):
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
        snap_at = snap.get("generated_at") or 0

        for row in snap.get("rows", []):
            kind, key = row.get("kind"), row.get("key")
            cur_key, it = self.item_for(items, key)
            tracked_kind = kind not in PICK_ROWS | NOTE_ROWS
            # Cleaned up, detached or untracked since the snapshot.
            if tracked_kind and it is None and kind != "GONE":
                continue
            # Picked or declined since the snapshot. `it`, not `key in items`:
            # an issue re-keyed to its PR is only in its item's prev_keys.
            if kind in PICK_ROWS and (it is not None or key in declined):
                continue
            parked = self.parked_done(row, it, snap_at)
            e = self.entry(row, cur_key, it, live, sessions, now, me, parked)
            seen.add(cur_key)
            if kind in NOTE_ROWS:
                out["notes"].append(e)
            elif kind in PICK_ROWS:
                out["pick"].append(e)
            # herdr's live state is seconds old; the snapshot can be minutes
            # old. A tracked item's agent mid-turn -- prompted by the
            # orchestrator or by hand -- is running, whatever its last report
            # or row says, DONE included.
            elif it is not None and e["agent"] == "running" \
                    and kind not in ORCH_ROWS and kind != "GONE":
                e["needs"] = False
                if kind not in RUN_ROWS:
                    e["note"] = f"working again · was {kind.lower()}"
                out["running"].append(e)
            elif parked:
                out["done"].append(e)
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
            parked = self.parked_done(row, it, snap_at)
            e = self.entry(row, k, it, live, sessions, now, me, parked)
            if parked and e["agent"] != "running":
                out["done"].append(e)
            else:
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

    def parked_done(self, row, it, snap_at):
        """Whether a parked card (`d`) sits in Done. An older row predates the
        park; a newer one counts only while its snapshot item is still parked
        (a revival clears it). PARK_EXEMPT kinds never do.
        """
        at = ((it or {}).get("parked") or {}).get("at")
        if not at or row.get("kind") in PARK_EXEMPT:
            return False
        if snap_at < at:
            return True
        return bool((row.get("item") or {}).get("parked"))

    def entry(self, row, key, it, live, sessions, now, me, parked=False):
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
        # scan.py's STALLED rule, applied live: the snapshot can be two
        # minutes behind, and the red Quiet column used to say "stalled"
        # while the row still sat under Running.
        # An agent that reported and stopped is not stalled, it is done.
        stalled = (it.get("driver") == "agent" and kind in RUN_ROWS | {"NEW"}
                   and quiet is not None and quiet >= AGENT_STALL_MIN * 60
                   and agent_state != "running" and not rep_live)
        # A read-only investigation never gets a PR, so no READY row: its
        # `ready` report is the moment the user has something to read.
        rep_needs = REPORT_NEEDS | ({"ready"} if it.get("read_only")
                                    else set())
        needs = (kind in NEEDS_ROWS or stalled
                 or (rep_live and rep.get("state") in rep_needs)
                 or (agent_state == "waiting" and kind not in DONE_ROWS))
        if parked:
            needs = False
        # Why it needs the user, for the desktop notification: one per reason.
        why = (kind if kind in NEEDS_ROWS else "stalled" if stalled
               else rep.get("state") if rep_live
               and rep.get("state") in rep_needs
               else "asking" if agent_state == "waiting" else None)
        if rep_live:
            note = f"{rep.get('state')}: {rep.get('msg') or ''}"
        elif stalled:
            note = "agent not reporting"
        elif parked:
            note = "parked"
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
        pr = it.get("pr") or (split_key(key)[1] if split_key(key)[2] == "pr"
                              else None)
        return {"kind": kind, "key": key, "title": row.get("title") or
                it.get("branch") or "", "url": row.get("url"),
                "checks": row.get("checks"), "draft": row.get("draft"),
                "session": sess, "agent": agent_state, "stalled": stalled,
                "rounds": it.get("review_rounds"), "driver": it.get("driver"),
                "quiet": quiet, "note": note, "needs": needs,
                "pick_kind": pick_kind, "path": sinfo.get("path"),
                "branch": it.get("branch"), "pr": pr,
                "pane": ag.get("pane"), "open": bool(sess and sess in sessions),
                "why": why}

    def orch_target(self, state, sessions):
        """-> (address, label). Addresses are "herdr:<agent>"."""
        addr = scan.orchestrator_target(state)
        target = addr.split(":", 1)[1] if addr.startswith("herdr:") else addr
        title = (sessions.get(target) or {}).get("title")
        return f"herdr:{target}", title or target


def sidebar_tokens(e, section):
    """Row -> the $ap_* tokens herdr/README.md's sidebar layout shows."""
    kind = e["kind"].lower()
    rnd = f"{e['rounds'] or 0}/{MAX_REVIEW_ROUNDS}" \
        if e["rounds"] is not None or e["driver"] == "agent" else ""
    return {"ap_kind": ("🔴 " if section == "needs" else "") + kind,
            "ap_pr": f"#{e['pr']}" if e["pr"] else "",
            "ap_rounds": rnd,
            "ap_ci": CI_GLYPH.get(e["checks"] or "", ("", ""))[0],
            "ap_note": (e["note"] or "")[:48]}


# -------------------------------------------------------------------- view

class Dashboard:
    def __init__(self, model, console):
        self.m = model
        self.console = console
        self.sel_key = None
        self.show_done = False
        self.hidden_done = 0
        self.flash = ("", 0)
        self.confirm = None   # (action, key, deadline)
        self.alert = None     # (key, title, deadline): the kitchen is closed
        self.selectable = []
        self.groups = []      # keys per board column, then the pick list
        self.expanded = set() # pick repos showing their rows; the rest collapse
        self.repos = []       # pick repo slugs, in order, as last rendered
        self.repo_of = {}     # item key -> its repo header's key

    def say(self, msg):
        self.flash = (msg, time.time())

    # -- rendering

    def render(self):
        now = time.time()
        if self.alert and now >= self.alert[2]:
            self.alert = None
            self.say("start cancelled")
        if self.alert:
            return self.kitchen()
        data, hdr = self.m.build()
        head = [self.header(data, hdr, now)]
        if hdr["paused"]:
            head.append(Text(" ⏸  PAUSED — the orchestrator acts on nothing "
                             "until resumed (P)", style="bold black on yellow"))
        # Done rows that still hold a workspace or session stay on the board,
        # so they can be opened or detached (z) without toggling D first.
        still_open = [e for e in data["done"] if e["open"]]
        self.hidden_done = 0 if self.show_done else \
            len(data["done"]) - len(still_open)
        columns = [("🟡 Running", data["running"], "yellow"),
                   ("⏭ Next tick", data["orch"], "blue"),
                   ("🔴 Needs you", data["needs"], "red"),
                   ("💤 Done", data["done"] if self.show_done else still_open,
                    "green")]
        # The selection state first: the footer reads it, and it needs no
        # heights, so it is settled before anything is measured.
        groups = self.pick_groups(data["pick"])
        self.repos = [slug for slug, _ in groups]
        self.repo_of = {e["key"]: repo_key(slug)
                        for slug, grp in groups for _, e in grp}
        # The order j/k walk and h/l jump across: board columns, then picks.
        # A collapsed repo's rows are not in it; its header is.
        pick_keys = []
        for slug, grp in groups:
            pick_keys.append(repo_key(slug))
            if slug in self.expanded:
                pick_keys += [e["key"] for _, e in grp]
        self.groups = [[e["key"] for e in rows] for _, rows, _ in columns]
        self.groups.append(pick_keys)
        # move() navigates by key, so a key listed twice would send ↓ back
        # to its first copy and trap the cursor. Keep the first of each.
        self.selectable = list(dict.fromkeys(k for g in self.groups for k in g))
        if self.sel_key not in self.selectable:
            # A row hidden by its repo's collapse falls back to that header.
            fallback = self.repo_of.get(self.sel_key)
            if fallback not in self.selectable:
                fallback = self.selectable[0] if self.selectable else None
            self.sel_key = fallback
        tail = [self.notes(data["notes"])] if data["notes"] else []
        tail += [self.activity(now), self.footer(data, now)]
        # Everything measured: the board gets what is left after the pick
        # tree's minimum, and the pick tree whatever the board did not take.
        fixed = sum(self.height(p) for p in head + tail)
        board = self.board(columns, self.console.height - fixed - PICK_MIN_LINES)
        head.append(board)
        pick_room = self.console.height - fixed - self.height(board) - 2
        pick = self.pick_tree(groups, max(PICK_MIN_LINES - 2, pick_room))
        return Group(*head, pick, *tail)

    def kitchen(self):
        """The kitchen-closed alert, alone and centered on the screen."""
        key, title, _ = self.alert
        body = Text(justify="center")
        body.append(f"🍳 The kitchen is closed (past {scan.WIND_DOWN_AT})\n\n",
                    style="bold red")
        body.append(f"{key}\n", style="bold")
        body.append(f"{title or ''}\n\n")
        body.append("Press g to start it anyway", style="bold yellow")
        body.append(" · any other key cancels", style="dim")
        panel = Panel(body, title="🍳 Kitchen closed", border_style="bold red",
                      box=box.DOUBLE, padding=(1, 4), expand=False)
        return Align.center(panel, vertical="middle",
                            height=self.console.height)

    def height(self, renderable):
        """Lines the renderable takes on this console."""
        return len(self.console.render_lines(renderable, self.console.options))

    def header(self, data, hdr, now):
        t = Text()
        t.append(" Octopilot ", style="bold reverse")
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

    def board(self, columns, budget):
        """Four equal columns, always all shown: cards move, columns don't.
        A column too tall for budget lines shows the cards around the selected
        one and a "+N more" line for the rest."""
        width = self.card_width()
        cells = []
        for title, rows, color in columns:
            bodies = [self.card_body(e, width) for e in rows]
            sel = next((i for i, e in enumerate(rows)
                        if e["key"] == self.sel_key), None)
            a, b = self.card_window([len(x) + 2 for x in bodies], budget - 1,
                                    sel)
            cards = [self.card(e, color, x)
                     for e, x in zip(rows[a:b], bodies[a:b])]
            if b - a < len(rows):
                cards.append(Text(f"+{len(rows) - (b - a)} more", style="dim"))
            cells.append(Group(Text(f"{title} ({len(rows)})", no_wrap=True,
                                    overflow="ellipsis", style=f"bold {color}"),
                               *(cards or [Text("—", style="dim")])))
        # A one-cell gap between columns: the narrowest is card_width() + 4.
        grid = Table.grid(expand=True)
        row = []
        for i, cell in enumerate(cells):
            if i:
                grid.add_column(width=1)
                row.append("")
            grid.add_column(ratio=1)
            row.append(cell)
        grid.add_row(*row)
        return grid

    def card_window(self, heights, limit, sel):
        """[a, b) of the cards shown: all when they fit in limit lines, else
        the ones around the selected card that fit beside a "+N more" line."""
        if sum(heights) <= limit:
            return 0, len(heights)
        budget = limit - 1
        a, b = (sel, sel + 1) if sel is not None else (0, 0)
        used = heights[a] if sel is not None else 0
        grew = True
        while grew:
            grew = False
            if b < len(heights) and used + heights[b] <= budget:
                used += heights[b]
                b += 1
                grew = True
            if a > 0 and used + heights[a - 1] <= budget:
                a -= 1
                used += heights[a]
                grew = True
        return a, b

    def card_width(self):
        """Text width inside a card: the narrowest board column less the
        card's borders and padding."""
        return max(4, (self.console.width - 3) // 4 - 4)

    def two_lines(self, text, width, style=""):
        """At most two lines of text, measured in cells, the second ellipsised."""
        lines = list(Text(text).wrap(self.console, width)) or [Text("")]
        if len(lines) > 2:
            rest = Text(" ".join(line.plain for line in lines[1:]))
            rest.truncate(width, overflow="ellipsis")
            lines = [lines[0], rest]
        if style:
            for line in lines:
                line.stylize(style)
        return lines

    def card_body(self, e, width):
        """A card's lines inside its border: title, status, note."""
        title = ("[draft] " if e["draft"] else "") + (e["title"] or "")
        status = Text(no_wrap=True, overflow="ellipsis")
        if e["agent"]:
            g, st = AGENT_GLYPH.get(e["agent"], ("?", "dim"))
            status.append(g + " ", style=st)
        status.append(e["kind"].lower())
        if e["checks"] in CI_GLYPH:
            g, st = CI_GLYPH[e["checks"]]
            status.append(f" {g}", style=st)
        if e["rounds"] is not None or e["driver"] == "agent":
            status.append(f" {e['rounds'] or 0}/{MAX_REVIEW_ROUNDS}")
        stalled = e["stalled"] or e["kind"] == "STALLED"
        status.append(f" {ago(e['quiet'])}", style="red" if stalled else "")
        return (self.two_lines(title, width) + [status]
                + self.two_lines(e["note"] or "", width, "dim"))

    def card(self, e, color, body):
        sel = e["key"] == self.sel_key
        return Panel(Group(*body), title=Text(short(e["key"]), style="bold"),
                     title_align="left", box=box.HEAVY if sel else box.ROUNDED,
                     border_style=f"bold {color}" if sel else color,
                     style="bold" if sel else "none", padding=(0, 1),
                     expand=True)

    def pick_groups(self, rows):
        """[(repo slug, [(#, entry)])], repos in order of first appearance. The #
        is the row's place in rows, which `go N` and the orchestrator both count
        by, so rows are not re-sorted, even when a repo's rows are not together."""
        groups = {}
        for i, e in enumerate(rows):
            groups.setdefault(split_key(e["key"])[0], []).append((i, e))
        return list(groups.items())

    def pick_tree(self, groups, limit):
        """Pick next as a tree by repo. A collapsed repo is its header alone,
        with a summary of what it holds."""
        rows = [e for _, grp in groups for _, e in grp]
        nw = len(str(len(rows)))
        rw = max((len(pick_ref(e["key"])) for e in rows), default=0)
        kw = max((len(e["pick_kind"]) for e in rows), default=0)
        width = self.console.width
        lines = []   # (Text, key, is a repo header, is an open repo's header)
        for slug, grp in groups:
            is_open = slug in self.expanded
            hdr = repo_key(slug)
            lines.append((self.repo_line(slug, grp, is_open, hdr == self.sel_key,
                                         width), hdr, True, is_open))
            if is_open:
                for pos, (i, e) in enumerate(grp):
                    lines.append((self.pick_line(i + 1, e, pos == len(grp) - 1,
                                                 nw, rw, kw, width),
                                  e["key"], False, False))
        # Scroll only once the selection falls below the window. An open
        # header is aimed past itself, so its first row is on screen with it.
        sel = next((p for p, line in enumerate(lines)
                    if line[1] == self.sel_key), None)
        aim = sel + 1 if sel is not None and lines[sel][3] else sel
        start = aim - limit + 1 if aim is not None and aim >= limit else 0
        end = min(start + limit, len(lines))
        if start and not lines[start][2]:
            # Never open mid-repo: the repo's header takes the top row.
            head = max(p for p in range(start) if lines[p][2])
            shown = [head] + list(range(start + 1, end))
        else:
            shown = list(range(start, end))
        if len(shown) > 1 and lines[shown[-1]][3] and shown[-1] != sel:
            shown.pop()   # an open header with none of its rows under it
        out = [lines[p][0] for p in shown]
        # Hidden rows: each item, and each collapsed repo's header (it stands
        # for the rows under it). An open header is not counted: its rows are.
        hidden = sum(1 for p, line in enumerate(lines)
                     if p not in shown and not (line[2] and line[3]))
        if hidden:
            out.append(Text(f"+{hidden} more (↑/↓ to scroll)", style="dim"))
        return Group(Text(f"⚪ Pick next ({len(rows)})", style="bold"), *out)

    def repo_line(self, slug, grp, is_open, sel, width):
        line = Text()
        line.append("▶ " if sel else "  ")
        line.append("▾ " if is_open else "▸ ")
        line.append(slug.rsplit("/", 1)[-1], style="bold")
        line.append(f"  {len(grp)}", style="dim")
        if not is_open:
            kinds = collections.Counter(e["pick_kind"] for _, e in grp)
            line.append("  " + " · ".join(f"{n} {k}" for k, n in kinds.items()),
                        style="dim")
        line.truncate(width - 1, overflow="ellipsis")
        if sel:
            line.stylize("reverse")
        return line

    def pick_line(self, n, e, last, nw, rw, kw, width):
        sel = e["key"] == self.sel_key
        # Marker, connector, number, ref and kind keep fixed columns; the
        # title takes the middle, cut by cell width so wide glyphs fit.
        fixed = 2 + 3 + nw + 2 + rw + 2
        room = max(1, width - 1 - fixed - 2 - kw)
        title = Text(e["title"] or "")
        title.truncate(room, overflow="ellipsis", pad=True)
        line = Text()
        line.append("▶ " if sel else "  ")
        line.append("└─ " if last else "├─ ", style="dim")
        line.append(f"{n:>{nw}}  ", style="dim")
        line.append(f"{pick_ref(e['key']):<{rw}}  ", style="bold")
        line.append(title)
        line.append("  ")
        line.append(e["pick_kind"].ljust(kw), style="dim")
        if sel:
            line.stylize("reverse")
        return line

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
        # The row's own decisions first, then what works everywhere.
        sel = next((e for rows in data.values() for e in rows
                    if e["key"] == self.sel_key), None)
        kind = sel["kind"] if sel else None
        items = (self.m.state or {}).get("items") or {}
        tracked = sel and sel["key"] in items
        parked = tracked and items[sel["key"]].get("parked")
        repo = self.sel_repo()
        keys = []
        if repo:
            keys.append(("spc", "fold" if repo in self.expanded else "open"))
        elif self.sel_key in self.repo_of:
            keys.append(("spc", "fold"))
        keys += [("g/n", "go/no")] if kind == "PROPOSE" else []
        if kind == "CAPPED":
            keys.append(("R", "another round"))
        if kind == "PUSHED":
            keys += [("e", "re-review"), ("x", "ack")]
        if tracked:
            keys.append(("z", "detach"))
            keys.append(("d", "undone" if parked else "done"))
        if not repo:
            keys += [("v", "agent"), ("t", "shell"), ("o", "browser")]
        keys += [("i", "investigate"), ("a", "prompter"),
                 ("r", "refresh"),
                 ("D", "hide done" if self.show_done else
                  f"show done (+{self.hidden_done} hidden)" if self.hidden_done
                  else "show done"),
                 ("C", "open all" if self.any_collapsed() else "fold all"),
                 ("P", "pause"), ("q", "quit")]
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

    def sel_repo(self):
        """The slug of the selected pick repo's header, else None."""
        if self.sel_key and self.sel_key.startswith(REPO_PREFIX):
            return self.sel_key[len(REPO_PREFIX):]
        return None

    def any_collapsed(self):
        return any(slug not in self.expanded for slug in self.repos)

    def toggle_all(self):
        """C: expand every repo if any is collapsed, else collapse them all."""
        if self.any_collapsed():
            self.expanded.update(self.repos)
        else:
            self.expanded.clear()

    def move(self, d):
        if not self.selectable:
            return
        try:
            i = self.selectable.index(self.sel_key)
        except ValueError:
            i = 0
        self.sel_key = self.selectable[max(0, min(len(self.selectable) - 1,
                                                  i + d))]

    def jump(self, d):
        """h/l: the first card of the previous or next non-empty column, or of
        the pick list past the last column."""
        cur = next((i for i, g in enumerate(self.groups) if self.sel_key in g),
                   None)
        if cur is None:
            return
        i = cur + d
        while 0 <= i < len(self.groups) and not self.groups[i]:
            i += d
        if 0 <= i < len(self.groups):
            self.sel_key = self.groups[i][0]

    def tree_step(self, d):
        """h/l on the pick tree act like a file tree: l opens a repo, then steps
        into it; h closes it, or from a row closes its repo and goes to the
        header. A collapsed header passes h on to the board."""
        repo = self.sel_repo()
        if d > 0:
            if repo is None:
                return
            if repo not in self.expanded:
                self.expanded.add(repo)
            else:
                # repo_of, not the last frame's pick list: a fast `ll` lands
                # here before the render that shows the repo's rows.
                self.sel_key = next((k for k, h in self.repo_of.items()
                                     if h == self.sel_key), self.sel_key)
        elif repo is not None and repo not in self.expanded:
            self.jump(-1)
        elif repo is None:
            self.expanded.discard(split_key(self.sel_key)[0])
            self.sel_key = self.repo_of[self.sel_key]
        else:
            self.expanded.discard(repo)

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
        """Queue a command in the orchestrator's inbox. Typing it into its
        pane would also send whatever the user is half-way through there."""
        code, out, err = sh([sys.executable, os.path.join(DIR, "scan.py"),
                             "request", text])
        self.say(f"queued '{text}' for the orchestrator" if code == 0
                 else f"queue failed: {(err or out)[:100]}")

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
        if self.alert:
            opened = self.alert[2] - KITCHEN_SECS
            if key == "g" and time.time() - opened < KITCHEN_GRACE:
                return True
            # Only g gets through the alert; anything else (q too) cancels.
            k, self.alert = self.alert[0], None
            if key == "g":
                self.to_orch(f"go {k} {CONFIRMED}")
            else:
                self.say("start cancelled")
            return True
        e = self.selected()
        repo = self.sel_repo()
        if key in ("q", "\x03"):
            return False
        if key in ("j", "\x1b[B"):
            self.move(1)
        elif key in ("k", "\x1b[A"):
            self.move(-1)
        elif key in ("h", "\x1b[D", "l", "\x1b[C") and (
                repo or self.sel_key in self.repo_of):
            self.tree_step(1 if key in ("l", "\x1b[C") else -1)
        elif key in ("h", "\x1b[D"):
            self.jump(-1)
        elif key in ("l", "\x1b[C"):
            self.jump(1)
        elif key in ("\x1b[5~",):
            self.move(-10)
        elif key in ("\x1b[6~",):
            self.move(10)
        elif key == "r":
            self.m.kick.set()
            self.say("refreshing from GitHub…")
        elif key == "D":
            self.show_done = not self.show_done
        elif key == "C":
            self.toggle_all()
        elif key == "P":
            paused = bool((self.m.state or {}).get("paused"))
            verb = "resume" if paused else "pause"
            if self.ask("P", "", f"press P again to {verb} octopilot"):
                code, out, err = sh([sys.executable,
                                     os.path.join(DIR, "scan.py"), verb])
                self.say(out or err)
        elif key == "a":
            self.open_orch(live, term)
        elif key == "i":
            self.investigate(live, term)
        elif key in (" ", "\r", "\n") and repo:
            if repo in self.expanded:
                self.expanded.discard(repo)
            else:
                self.expanded.add(repo)
        elif key == " " and self.sel_key in self.repo_of:
            # Collapse the item's repo and put the cursor on its header.
            self.expanded.discard(split_key(self.sel_key)[0])
            self.sel_key = self.repo_of[self.sel_key]
        elif not e:
            # A repo header has no row, so the row keys have nothing to act on.
            if repo and key in ("v", "t", "o", "g", "n", "R", "e", "x", "z",
                                "d"):
                self.say("select a row, not a repo header")
            return True
        elif key in ("\r", "\n"):
            if e["session"]:
                self.attach(e["session"], live, term)
            else:
                self.say("no session for this row")
        elif key == "v":
            self.agent_popup(e)
        elif key == "t":
            if e["path"] and os.path.isdir(e["path"]):
                self.shell(e["path"], live, term)
            else:
                self.say("no worktree for this row")
        elif key == "o":
            self.browse(e)
        elif key == "g" and e["kind"] == "PROPOSE" and scan.wind_down() == "yes":
            # Past WIND_DOWN_AT a fast gg only opens the alert; the third g,
            # pressed with it on screen, confirms. The orchestrator then never
            # has to ask in its own pane.
            if self.ask("g", e["key"], f"🍳 kitchen closed -- press g again to "
                        f"start {e['key']} anyway"):
                self.alert = (e["key"], e["title"],
                              time.time() + KITCHEN_SECS)
        elif key in ("g", "n") and e["kind"] == "PROPOSE":
            verb = "go" if key == "g" else "no"
            if self.ask(key, e["key"], f"press {key} again to send "
                        f"'{verb} {e['key']}' to the orchestrator"):
                self.to_orch(f"{verb} {e['key']}")
        elif key in ("g", "n"):
            self.say("go/no only applies to Pick next rows")
        elif key == "R":
            if e["kind"] != "CAPPED":
                self.say("R only applies to CAPPED rows")
            elif self.ask("R", e["key"], f"press R again to grant {e['key']} "
                          f"another {MAX_REVIEW_ROUNDS} review rounds"):
                self.run_scan("reset-rounds", e["key"])
        elif key in ("e", "x"):
            if e["kind"] != "PUSHED":
                self.say("e/x only apply to PUSHED (stale) rows")
            elif key == "e" and self.ask("e", e["key"], "press e again to ask "
                                         f"for a re-review of {e['key']}"):
                self.to_orch(f"re-review {e['key']}")
            elif key == "x" and self.ask("x", e["key"], "press x again to ack "
                                         f"the new commits on {e['key']}"):
                self.run_scan("ack-push", e["key"])
        elif key == "z":
            if e["key"] not in ((self.m.state or {}).get("items") or {}):
                self.say("detach only applies to tracked items")
            elif self.ask("z", e["key"], f"press z again to detach {e['key']} "
                          "(worktree kept, untracked)"):
                self.run_scan("detach", e["key"])
        elif key == "d":
            it = ((self.m.state or {}).get("items") or {}).get(e["key"])
            if it is None:
                self.say("d only applies to tracked items")
            elif e["kind"] in ("MERGED", "CLOSED", "GONE", "BOOTING"):
                self.say(f"{e['kind']} rows can't be parked now")
            elif e["kind"] == "FEEDBACK":
                # Its pending feedback would revive the card on the next tick.
                self.say("FEEDBACK rows can't be parked: the feedback is pending")
            elif it.get("parked"):
                if self.ask("d", e["key"], f"press d again to move {e['key']} "
                            "out of Done"):
                    self.run_scan("unpark", e["key"])
            elif self.ask("d", e["key"], f"press d again to move {e['key']} to "
                          "Done (session kept, slot freed)"):
                self.run_scan("park", e["key"])
        return True

    def run_scan(self, *args):
        """A scan.py command that needs no judgement, run right here."""
        code, out, err = sh([sys.executable, os.path.join(DIR, "scan.py"),
                             *args])
        self.say((out or err).splitlines()[-1] if (out or err) else
                 f"{args[0]} exit {code}")

    def investigate(self, live, term):
        """/investigate [--read-only] <repo> <question>, typed here and
        queued."""
        repo = term.read_line(live, "Investigate -- repo (owner/repo or name): ")
        question = repo and term.read_line(live, "Question: ")
        if not (repo and question):
            self.say("investigation cancelled")
            return
        ro = term.read_line(live, "Read-only (a report, no commits or PR)? "
                            "[y/N] ")
        flag = "--read-only " if ro.lower() in ("y", "yes") else ""
        cmd = f"/investigate {flag}{repo} {question}"
        if scan.wind_down() == "yes":
            ok = term.read_line(live, f"🌇 Past {scan.WIND_DOWN_AT} -- start it "
                                "anyway? [y/N] ")
            if ok.lower() not in ("y", "yes"):
                self.say("investigation not started (wind-down)")
                return
            cmd += f" {CONFIRMED}"
        self.to_orch(cmd)

    def attach(self, session, live, term):
        """Switch to the item's herdr agent, in its own workspace."""
        with self.m.lock:
            agents = dict(self.m.live)
        if not self.m.backend.focus(session, agents):
            self.say(f"could not focus workspace {session}")

    def agent_popup(self, e):
        """The row's agent in a popup over the dashboard, without leaving it.
        `ctrl+b q` detaches herdr's attach client, which closes the popup."""
        target = e["pane"] or (((self.m.state or {}).get("items") or {})
                               .get(e["key"], {}).get("agent"))
        if not target:
            self.say("no live agent for this row")
        elif self.popup("agent", {"AP_AGENT": target}):
            self.say("ctrl+b q closes the popup")

    def open_orch(self, live, term):
        """The prompter when there is one (that is where the user types),
        else the orchestrator itself."""
        if scan.herdr(["agent", "focus", PROMPTER_AGENT])[0] == 0:
            return
        _, hdr = self.m.build()
        target = hdr["orch"][0].split(":", 1)[1]
        if scan.herdr(["agent", "focus", target])[0] != 0:
            self.say(f"no herdr agent named {target}")

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

    def read_line(self, live, prompt):
        """One line typed by the user, with the dashboard paused around it.
        Empty on Ctrl-C or Ctrl-D, which callers treat as cancel."""
        live.stop()
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)
        try:
            return input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return ""
        finally:
            tty.setcbreak(self.fd)
            live.start(refresh=True)

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
    backend = Hosts()
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
