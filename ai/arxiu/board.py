#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["rich>=13.7"]
# ///
"""Arxiu: the genealogy research dashboard, in two columns.

- Left (~60%): the tree in `[arbre].path`, read by arbre_data.py: totals and
  the week's progress, then a list you expand -- families, their branches
  (the `groups` of families.yml), and in a branch its people and its pending
  items -- the tree's agents and its latest commits.
- Right (~40%): panel.py's view of the selection (a pedigree, completeness,
  a lookup card) and the queue of what was asked of the agents.

It acts on the tree's agents (actions.py): a lowercase key types a prompt
for the selection into the orchestrator's input, below the board in the
Arxiu workspace, without sending it; the uppercase one sends it to the
background research agent after a second press. Everything asked goes into
the queue (research_queue.py), whose statuses follow herdr's agent states.

The tree refreshes when its files or git change (stat polling, a few ms),
agents and the queue every `[ui].agents_secs`. Validation of the tree runs in
the background, and only when the tree changed since the last run.
ARXIU_DRY_RUN=1 turns every action into a message saying what it would do.
Run it through arxiu.sh; `--once` prints one frame (COLUMNS/LINES) for
checking the layout without a TTY.
"""
import os
import re
import select
import shlex
import shutil
import subprocess
import sys
import termios
import threading
import time
import tty
from datetime import date

from rich import box
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)
import actions  # noqa: E402
import agents  # noqa: E402
import arbre_data  # noqa: E402
import research_queue  # noqa: E402

# The right column and the people come from panel.py and people.py. Without
# them (broken, or not there yet) the list still works: the people of a
# branch are read from the notes here, and the column shows a placeholder.
try:
    import people as people_mod  # noqa: E402
    PEOPLE_ERR = None
except Exception as e:  # noqa: BLE001 -- any failure means "no people.py"
    people_mod = None
    PEOPLE_ERR = f"{type(e).__name__}: {e}"
try:
    import panel  # noqa: E402
    PANEL_ERR = None
except Exception as e:  # noqa: BLE001
    panel = None
    PANEL_ERR = f"{type(e).__name__}: {e}"

PLUGIN_ID = "elboletaire.arxiu"
IN_HERDR = os.environ.get("HERDR_ENV") == "1"
DRY_RUN = os.environ.get("ARXIU_DRY_RUN") == "1"
TREE_POLL = 1.0        # seconds between stat polls of the tree
CONFIRM_SECS = 8       # window for the second press of a send
FLASH_SECS = 6
PANEL_SHARE = 0.4      # of the width, for the right column

AGENT_GLYPH = {"working": ("◐", "yellow"), "waiting": ("⏸", "bold red"),
               "error": ("✗", "bold red"), "done": ("✓", "green"),
               "idle": ("○", "dim"), "stopped": ("■", "dim"),
               "unknown": ("?", "dim")}
ATTENTION = {"waiting", "error"}
KIND_LABEL = actions.KIND_LABEL
# Node kinds that open and close, and whether they start open.
OPEN_BY_DEFAULT = {"family": True, "row": False, "people": False,
                   "head": True}


# ----------------------------------------------------------------- helpers

def sh(args, timeout=30, cwd=None, env=None):
    try:
        p = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout, cwd=cwd, env=env,
                           stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout, p.stderr
    except (subprocess.TimeoutExpired, OSError) as e:
        return 1, "", str(e)


def ago(secs):
    """Compact age: 43m, 5h, 3d, 2w, 4mo."""
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


def when(epoch, now=None):
    """Catalan relative day for "última recerca": avui, ahir, fa 3 dies…"""
    if not epoch:
        return "–"
    now = now or time.time()
    days = (date.fromtimestamp(now) - date.fromtimestamp(epoch)).days
    if days <= 0:
        return "avui"
    if days == 1:
        return "ahir"
    if days < 14:
        return f"fa {days} dies"
    if days < 60:
        return f"fa {days // 7} setmanes"
    if days < 365:
        return f"fa {days // 30} mesos"
    return f"fa {days // 365} anys"


def clip(text, n):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:max(0, n - 1)].rstrip() + "…"


def plural(n, one, many):
    return f"{n} {one if n == 1 else many}"


# ------------------------------------------------------------------ people

def fallback_people(tree):
    """Without people.py: just enough of the person notes for the list
    (slug, name, dates, branches), in people.py's shape."""
    path = tree["path"]
    cache = arbre_data._cache(path)
    other = next((b["key"] for b in tree["branches"]
                  if b.get("family") is None), "otras")
    persons, branches = {}, {}
    pdir = os.path.join(path, tree["paths"]["people"])
    for f in arbre_data._md_files(pdir):
        meta = arbre_data._note_meta(cache, f)
        slug = os.path.basename(f)[:-3]
        keys = [str(t)[len("rama/"):] for t in arbre_data._as_list(
            meta.get("tags")) if str(t).startswith("rama/")] or [other]
        name = " ".join(str(x) for x in (meta.get("given_name"),
                                         meta.get("surnames")) if x) or slug
        persons[slug] = {"slug": slug, "name": name, "born": meta.get("born"),
                         "died": meta.get("died"), "branches": keys,
                         "pending": []}
        for k in keys:
            branches.setdefault(k, {"key": k, "members": []})["members"] \
                .append(slug)
    return {"path": path, "persons": persons, "branches": branches,
            "families": {}, "items": {}, "fallback": True}


def branch_people(people, key):
    """The people of a branch (CONTRACT.md: people.branch_people)."""
    if people_mod and not people.get("fallback"):
        return people_mod.branch_people(people, key)
    b = people.get("branches", {}).get(key) or {}
    return [people["persons"][s] for s in sorted(b.get("members", []))]


def years(rec):
    """"1880–1950", "c.1842–1896", "n. 1987", "†1950" or ""."""
    def y(v):
        m = re.search(r"\d{4}", str(v or ""))
        if not m:
            return ""
        exact = re.fullmatch(r"\d{4}(-\d{2}){0,2}", str(v).strip())
        return m.group(0) if exact else "c." + m.group(0)
    b, d = y(rec.get("born")), y(rec.get("died"))
    if b and d:
        return f"{b}–{d}"
    if b:
        return f"n. {b}"
    if d:
        return f"†{d}"
    return ""


# ------------------------------------------------------------------- model

class Model:
    """What the screen shows, kept fresh by background threads."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.tree_path = cfg["arbre"]["path"]
        self.lock = threading.Lock()
        self.changed = threading.Event()
        self.tree = None
        self.tree_err = None
        self.tree_sig = None
        self.people = None
        self.people_err = PEOPLE_ERR
        self.agents = []          # the tree's
        self.all_agents = []      # every herdr agent
        self.agents_at = 0
        self.queue = []
        self.kick_tree = threading.Event()
        self.kick_agents = threading.Event()

    # -- tree

    def load_tree(self):
        try:
            tree = arbre_data.load(self.tree_path)
            err = None
        except Exception as e:  # noqa: BLE001 -- a broken note must not kill the board
            tree, err = None, f"{type(e).__name__}: {e}"
        with self.lock:
            if tree is not None:
                self.tree = tree
            self.tree_err = err
        if tree is not None:
            self.load_people(tree)
        self.changed.set()

    def load_people(self, tree):
        try:
            ppl = people_mod.load(self.tree_path, tree) if people_mod \
                else fallback_people(tree)
            err = PEOPLE_ERR
        except Exception as e:  # noqa: BLE001
            ppl, err = None, f"{type(e).__name__}: {e}"
        with self.lock:
            if ppl is not None:
                self.people = ppl
            self.people_err = err

    def refresh_validation(self):
        """Re-read the cached validation result (cheap) into the tree."""
        with self.lock:
            tree = self.tree
        if tree:
            tree["validation"] = arbre_data.validation(self.tree_path)
            self.changed.set()

    def validate(self, force=False):
        started = arbre_data.validate_async(
            self.tree_path, force=force, on_done=self.refresh_validation)
        if started:
            self.refresh_validation()
        return started

    def tree_loop(self):
        while True:
            sig = arbre_data.changed_signature(self.tree_path)
            if sig != self.tree_sig or self.kick_tree.is_set():
                self.kick_tree.clear()
                self.tree_sig = sig
                self.load_tree()
                if os.path.isfile(os.path.join(self.tree_path, "families.yml")):
                    self.validate()
            self.kick_tree.wait(TREE_POLL)

    # -- agents and the queue

    def refresh_agents(self):
        """herdr's agents (~0.1s), and the queue's statuses from them."""
        try:
            found = agents.list_agents(strict=True)
        except Exception:  # noqa: BLE001
            found = None
        # Without an answer from herdr the statuses stay as they are.
        try:
            entries = research_queue.update(found) if found is not None \
                else research_queue.load()
        except OSError:
            entries = research_queue.load()
        with self.lock:
            if found is not None:
                self.agents = agents.tree_agents(self.cfg, found)
                self.all_agents = found
                self.agents_at = time.time()
            self.queue = entries
        self.changed.set()

    def agents_loop(self):
        secs = max(1, int(self.cfg.get("ui", {}).get("agents_secs", 3)))
        while True:
            self.refresh_agents()
            self.kick_agents.wait(secs)
            self.kick_agents.clear()

    def start(self):
        for fn in (self.tree_loop, self.agents_loop):
            threading.Thread(target=fn, daemon=True).start()

    # -- view data

    def snapshot(self):
        with self.lock:
            return self.tree, self.people, list(self.agents), \
                list(self.queue)

    def agent(self, name):
        return next((a for a in self.all_agents if a.get("name") == name),
                    None)


# -------------------------------------------------------------------- view

def detail_entries(row):
    """A row -> its pending work: ("head", label, count) and ("item", item)
    entries, in reading order. Searches already made (the "no repetir" logs)
    and discarded documents are a count, not items."""
    out = []
    by_kind = {}
    for items in row["pending"].values():
        for it in items:
            by_kind.setdefault(it["kind"], []).append(it)
    for kind in ("docs", "people", "cut", "photos", "leads", "other"):
        items = by_kind.pop(kind, [])
        if items:
            out.append(("head", KIND_LABEL[kind], len(items)))
            out += [("item", it) for it in items]
    for kind, items in by_kind.items():   # a kind arbre_data added later
        out.append(("head", KIND_LABEL.get(kind, kind), len(items)))
        out += [("item", it) for it in items]
    contra = [it for items in row["contradictions"].values() for it in items]
    if contra:
        out.append(("head", KIND_LABEL["contradictions"], len(contra)))
        out += [("item", it) for it in contra]
    if row["review"]:
        out.append(("head", KIND_LABEL["review"], len(row["review"])))
        out += [("item", it) for it in row["review"]]
    return out


def row_people(people, row):
    """The people of a row's branches, each once, in branch_people's order,
    each with the first of its branches the row covers."""
    if not people:
        return []
    out, seen = [], set()
    for key in row["branches"]:
        for p in branch_people(people, key):
            p = p if isinstance(p, dict) else \
                people["persons"].get(p) or {"slug": p, "name": p}
            if p["slug"] not in seen:
                seen.add(p["slug"])
                out.append((p, key))
    return out


def build_nodes(tree, people, is_open):
    """The list as it is now: family -> row (a group of branches) -> its
    people (a folder of them) and its pending items under their category.
    -> [node]; a node is {id, kind, depth, label, ...}. `is_open(node_id,
    kind)` says whether a node is expanded."""
    nodes = []
    fams = []
    for r in tree["rows"]:
        if r["family"] not in fams:
            fams.append(r["family"])
    for fk in fams:
        fam = actions.family_of(tree, fk)
        rows = [r for r in tree["rows"] if r["family"] == fk]
        fid = f"f:{fk}"
        nodes.append({"id": fid, "kind": "family", "depth": 0, "family": fk,
                      "label": fam["label"], "rows": rows,
                      "open": is_open(fid, "family")})
        if not nodes[-1]["open"]:
            continue
        for r in rows:
            rid = f"r:{r['id']}"
            nodes.append({"id": rid, "kind": "row", "depth": 1, "row": r,
                          "family": fk, "label": r["title"],
                          "open": is_open(rid, "row")})
            if not nodes[-1]["open"]:
                continue
            members = row_people(people, r) if r["branches"] else []
            if members or people is None:
                pid = f"p:{r['id']}"
                nodes.append({"id": pid, "kind": "people", "depth": 2,
                              "row": r, "family": fk, "count": len(members),
                              "label": "persones" if people is not None
                              else "persones (carregant…)",
                              "open": is_open(pid, "people")})
                if nodes[-1]["open"]:
                    for p, key in members:
                        nodes.append({"id": f"s:{r['id']}:{p['slug']}",
                                      "kind": "person", "depth": 3, "row": r,
                                      "family": fk, "branch": key,
                                      "person": p, "label": p.get("name")
                                      or p["slug"]})
            head = None
            for n, e in enumerate(detail_entries(r)):
                if e[0] == "head":
                    hid = f"k:{r['id']}:{e[1]}"
                    head = {"id": hid, "kind": "head", "depth": 2, "row": r,
                            "family": fk, "label": e[1], "count": e[2],
                            "open": is_open(hid, "head")}
                    nodes.append(head)
                elif head is None or head["open"]:
                    it = e[1]
                    nodes.append({"id": f"i:{r['id']}:{n}", "kind": "item",
                                  "depth": 3, "row": r, "family": fk,
                                  "item": it, "label":
                                  f"{it['id']} — {it['title']}"
                                  if it.get("id") else it["title"]})
            info = []
            if r["counts"].get("searched"):
                info.append(f"{plural(r['counts']['searched'], 'cerca', 'cerques')}"
                            " sense resultat (no repetir)")
            if r["counts"].get("discarded"):
                info.append(f"{r['counts']['discarded']} descartats")
            if not r["branches"] and not detail_entries(r):
                info.append("res pendent")
            for i, t in enumerate(info):
                nodes.append({"id": f"n:{r['id']}:{i}", "kind": "info",
                              "depth": 2, "row": r, "family": fk,
                              "label": t})
    return nodes


def selection_of(node):
    """A list node -> CONTRACT.md's selection. Beyond the contract's keys it
    carries `row` (the branch-table row id) and `branches` (the row's
    branch keys): a row can group several branches."""
    sel = {"kind": None, "family": None, "branch": None, "person": None,
           "item": None, "row": None, "branches": []}
    if not node:
        return sel
    sel["family"] = node.get("family")
    if node["kind"] == "family":
        sel["kind"] = "family"
        return sel
    row = node["row"]
    sel.update(row=row["id"], branches=list(row["branches"]),
               branch=row["branches"][0] if row["branches"] else None)
    if node["kind"] == "person":
        sel.update(kind="person", person=node["person"]["slug"],
                   branch=node.get("branch") or sel["branch"])
    elif node["kind"] == "item":
        sel.update(kind="item", item=node["item"])
    else:
        sel["kind"] = "branch"
    return sel


class Board:
    def __init__(self, model, console):
        self.m = model
        self.console = console
        self.focus = "list"       # or "panel" (Tab)
        self.cursor = None        # node id
        self.opened = {}          # node id -> open, where not the default
        self.nodes = []
        self.panel_scroll = 0
        self.flash = ("", 0)
        self.busy = ""            # a long action's progress, until it ends
        self.confirm = None       # (action, key, deadline, message, preview)
        self.input = None         # {"prompt", "buf", "default"}
        self.overlay = None       # {"title", "lines", "scroll"}
        self.menu = None          # {"title", "entries", "at"}: the actions menu
        self.list_h = 10
        self.last = None          # the cursor's node, when it was last seen

    def say(self, msg):
        self.flash = (msg, time.time())

    def is_open(self, node_id, kind):
        return self.opened.get(node_id, OPEN_BY_DEFAULT.get(kind, False))

    # -- the list

    def refresh_nodes(self):
        tree, people, _, _ = self.m.snapshot()
        if tree is None:
            self.nodes = []
            return
        self.nodes = build_nodes(tree, people, self.is_open)
        ids = [n["id"] for n in self.nodes]
        if self.cursor in ids:
            self.last = self.node()
            return
        # The node went away (the tree changed, or its parent closed): its
        # row if that is still there, else its family, else the first row.
        last = self.last or {}
        for want in ((f"r:{last['row']['id']}" if last.get("row") else None),
                     (f"f:{last['family']}" if "family" in last else None)):
            if want in ids:
                self.cursor = want
                break
        else:
            self.cursor = next((i for i in ids if i.startswith("r:")),
                               ids[0] if ids else None)
        self.last = self.node()

    def node(self):
        return next((n for n in self.nodes if n["id"] == self.cursor), None)

    def selection(self):
        return selection_of(self.node())

    def parent(self, node):
        """The node a node hangs from (by depth, above it), or None."""
        idx = self.nodes.index(node)
        for n in reversed(self.nodes[:idx]):
            if n["depth"] < node["depth"]:
                return n
        return None

    # -- rendering

    def render(self):
        self.refresh_nodes()
        tree, people, tree_agents, queue = self.m.snapshot()
        width, height = self.console.size
        foot = self.footer()
        foot_h = max(1, len(foot.wrap(self.console, width)))
        body_h = max(8, height - foot_h)
        right_w = max(30, int(width * PANEL_SHARE))
        root = Layout()
        root.split_column(Layout(name="body", size=body_h),
                          Layout(foot, name="foot", size=foot_h))
        if self.overlay:
            root["body"].update(self.overlay_panel(body_h))
            return root
        left = Layout(self.tree_panel(tree, tree_agents, width - right_w,
                                      body_h), name="left")
        side = self.menu_panel(body_h) if self.menu else \
            self.side_panel(tree, people, queue, right_w, body_h)
        right = Layout(side, name="right", size=right_w)
        root["body"].split_row(left, right)
        return root

    def border(self, side):
        return "green" if self.focus == side else "grey35"

    def tree_panel(self, tree, tree_agents, width, height):
        inner_w, inner_h = width - 4, height - 2
        title = Text("🌳 Arxiu", style="bold")
        if not os.path.isfile(os.path.join(self.m.tree_path, "families.yml")):
            tree = None
            self.m.tree_err = self.m.tree_err or \
                f"no hi ha cap arbre a {self.m.tree_path} (sense families.yml)" \
                " · [arbre].path a config.toml"
        if tree is None:
            msg = self.m.tree_err or f"llegint {self.m.tree_path}…"
            return Panel(Text(msg, style="red" if self.m.tree_err else "dim"),
                         title=title, title_align="left", height=height,
                         border_style=self.border("list"))
        head = self.tree_header(tree, inner_w)
        strip = self.agents_strip(tree_agents)
        diary = self.diary(tree, inner_w, max_lines=1)
        fixed = len(head) + len(strip) + len(diary)
        if self.m.tree_err:
            head.insert(0, Text(f"⚠ {clip(self.m.tree_err, inner_w)}",
                                style="red"))
            fixed += 1
        self.list_h = max(3, inner_h - fixed - 1)
        table = self.node_table(tree, inner_w, self.list_h)
        pad = max(0, self.list_h + 1 - self.table_h)
        parts = head + [table] + [Text("")] * pad + strip + diary
        return Panel(Group(*parts), title=title, title_align="left",
                     height=height, border_style=self.border("list"),
                     padding=(0, 1))

    def tree_header(self, tree, width=200):
        t = tree["totals"]
        v = tree.get("validation") or {}
        line = self.totals_line(t, short=False)
        if len(line.plain) > width:
            line = self.totals_line(t, short=True)
        line.no_wrap, line.overflow = True, "ellipsis"
        w = tree["week"]
        line2 = Text()
        line2.append("Aquesta setmana: ", style="dim")
        bits = []
        if w["sources"]:
            rng = f" ({w['first_source']}–{w['last_source']})" \
                if w["first_source"] != w["last_source"] else \
                f" ({w['first_source']})"
            bits.append(Text(f"+{w['sources']} fonts{rng}", style="green"))
        if w["people"]:
            bits.append(Text(f"+{plural(w['people'], 'persona', 'persones')}",
                             style="green"))
        if not bits:
            bits.append(Text("res de nou", style="dim"))
        for i, b in enumerate(bits):
            if i:
                line2.append(" · ")
            line2.append_text(b)
        line2.append("   validació ", style="dim")
        line2.append_text(self.validation_badge(v))
        line2.no_wrap, line2.overflow = True, "ellipsis"
        out = [line, line2]
        if v.get("state") == "error" and v.get("lines"):
            out.append(Text(f"✗ {clip(v['lines'][0], 200)}", style="red",
                            no_wrap=True, overflow="ellipsis"))
        return out

    def totals_line(self, t, short):
        line = Text()
        line.append(plural(t["people"], "persona", "persones"), style="bold")
        line.append(" · ")
        line.append(plural(t["sources"], "font", "fonts"), style="bold")
        if t.get("last_source") and not short:
            line.append(f" ({t['last_source']})", style="dim")
        line.append(" · ")
        line.append(plural(t["pending"], "pendent", "pendents"),
                    style="yellow" if t["pending"] else "dim")
        line.append(" · ")
        line.append(f"{t['contradictions']} incoh." if short else
                    plural(t["contradictions"], "incoherència",
                           "incoherències"),
                    style="magenta" if t["contradictions"] else "dim")
        line.append(" · ")
        line.append(f"{t['review']} per revisar",
                    style="cyan" if t["review"] else "dim")
        return line

    def validation_badge(self, v):
        if v.get("running"):
            return Text("⟳ validant", style="cyan")
        state = v.get("state")
        if state == "ok":
            txt = "✓"
            if v.get("warnings"):
                txt += f" {plural(v['warnings'], 'avís', 'avisos')}"
            return Text(txt + (" (antiga)" if v.get("stale") else ""),
                        style="yellow" if v.get("stale") else "green")
        if state == "error":
            return Text(f"✗ {plural(v.get('errors') or 0, 'error', 'errors')}"
                        + (" (antiga)" if v.get("stale") else ""),
                        style="bold red")
        return Text("? sense validar", style="dim")

    def node_table(self, tree, width, room):
        """The list, as a table: the name (indented by depth) and, for
        families and rows, their counts and last research."""
        wide = width >= 72
        tb = Table(box=None, expand=True, pad_edge=False, show_edge=False,
                   header_style="bold dim", padding=(0, 1))
        tb.add_column("", width=1, no_wrap=True)
        tb.add_column("Família · branca", ratio=1, no_wrap=True,
                      overflow="ellipsis")
        cols = ("Pend", "Docs", "Ids", "Incoh", "Rev") if wide \
            else ("Pend", "Incoh")
        for name in cols:
            tb.add_column(name, justify="right", no_wrap=True)
        tb.add_column("Última", no_wrap=True)
        nodes = self.nodes
        idx = next((i for i, n in enumerate(nodes)
                    if n["id"] == self.cursor), 0)
        start = 0
        if len(nodes) > room:
            start = max(0, min(idx - room // 3, len(nodes) - room))
        shown = nodes[start:start + room]
        colour = {b["key"]: b.get("colour") for b in tree["branches"]}
        now = time.time()
        for n in shown:
            sel = n["id"] == self.cursor
            here = sel and self.focus == "list"
            name = Text("  " * n["depth"])
            nums = [""] * len(cols)
            last = Text("")
            if n["kind"] in ("family", "row", "people", "head"):
                name.append("▾ " if n["open"] else "▸ ", style="dim")
            if n["kind"] == "family":
                name.append(n["label"], style="bold")
                c = self.sum_counts(n["rows"])
                nums = self.count_cells(c, cols)
                newest = max((r["last_research"] or 0 for r in n["rows"]),
                             default=0)
                last = Text(when(newest, now), style="dim")
            elif n["kind"] == "row":
                r = n["row"]
                for col in r["colours"][:3] or ["grey50"]:
                    name.append("●", style=col)
                name.append(" ")
                name.append(r["title"], style=f"bold {r['colour']}" if sel
                            else r["colour"] if r["matched"] else "")
                nums = self.count_cells(r["counts"], cols)
                last = Text(when(r["last_research"], now),
                            style="yellow" if r["stale"] else "dim")
                if r["stale"]:
                    last.append(" ⚠")
            elif n["kind"] in ("people", "head"):
                name.append(f"{n['label']} ({n.get('count', 0)})",
                            style="bold dim")
            elif n["kind"] == "person":
                p = n["person"]
                name.append("● ", style=colour.get(n.get("branch")) or "dim")
                name.append(n["label"])
                ys = years(p)
                if ys:
                    name.append(f"  {ys}", style="dim")
                if p.get("pending"):
                    name.append(f"  ·{len(p['pending'])}", style="yellow")
            elif n["kind"] == "item":
                name.append("• " + n["label"])
            else:
                name.append(n["label"], style="dim italic")
            marker = "▶" if here else ("›" if sel else "")
            tb.add_row(marker, name, *nums, last,
                       style="reverse" if here else None)
        self.table_h = len(shown) + 1
        return tb

    @staticmethod
    def sum_counts(rows):
        out = {}
        for r in rows:
            for k, v in (r.get("counts") or {}).items():
                out[k] = out.get(k, 0) + (v or 0)
        return out

    @staticmethod
    def count_cells(c, cols):
        key = {"Pend": ("pending", "yellow"), "Docs": ("docs", ""),
               "Ids": ("people", ""), "Incoh": ("contradictions", "magenta"),
               "Rev": ("review", "cyan")}
        out = []
        for col in cols:
            k, style = key[col]
            n = c.get(k) or 0
            out.append(Text(str(n) if n else "·", style=style if n else "dim"))
        return out

    def agents_strip(self, tree_agents):
        line = Text()
        line.append("Agents  ", style="bold dim")
        cfg = self.m.cfg["arbre"]
        role = {cfg.get("orchestrator_agent"): "orquestrador",
                cfg.get("research_agent"): "recerca"}
        if not tree_agents:
            line.append("cap" if self.m.agents_at else "…", style="dim")
        for i, a in enumerate(tree_agents):
            if i:
                line.append("  ")
            g, st = AGENT_GLYPH.get(a.get("state"), ("?", "dim"))
            line.append(g + " ", style=st)
            name = a.get("name") or "?"
            line.append(name, style="bold" if a.get("state") in ATTENTION
                        else "")
            if role.get(name):
                line.append(f" {role[name]}", style="dim")
        line.no_wrap, line.overflow = True, "ellipsis"
        return [line]

    def diary(self, tree, width, max_lines=2):
        """The latest commits, flowed over up to `max_lines` lines; a commit
        is never split across two."""
        now = time.time()
        lines = [Text()]
        lines[0].append("Diari   ", style="bold dim")
        for c in tree.get("diary") or []:
            piece = Text()
            piece.append(c["sha"], style="yellow")
            piece.append(f" {clip(c['text'], 40)}")
            piece.append(f" {ago(now - c['at'])}", style="dim")
            cur = lines[-1]
            sep = 3 if len(cur.plain) > 8 else 0
            if len(cur.plain) + sep + len(piece.plain) > width:
                if len(lines) == max_lines:
                    break
                cur = Text(" " * 8)
                lines.append(cur)
                sep = 0
            if sep:
                cur.append(" · ", style="dim")
            cur.append_text(piece)
        for t in lines:
            t.no_wrap, t.overflow = True, "ellipsis"
        return lines

    # .. the right column

    def side_panel(self, tree, people, queue, width, height):
        inner_w, inner_h = width - 4, height - 2
        sel = self.selection()
        title = Text(self.side_title(sel), style="bold")
        if panel is None or tree is None:
            body = self.placeholder(sel, queue, inner_w, inner_h)
        else:
            try:
                body = self.panel_body(tree, people, sel, queue, inner_w,
                                       inner_h)
            except Exception as e:  # noqa: BLE001 -- a panel bug must not kill the board
                body = Group(Text(f"panel.py: {type(e).__name__}: {e}",
                                  style="red"),
                             *self.placeholder(sel, queue, inner_w,
                                               inner_h - 1).renderables)
        return Panel(body, title=title, title_align="left", height=height,
                     border_style=self.border("panel"), padding=(0, 1))

    def panel_body(self, tree, people, sel, queue, width, height):
        """panel.render(), scrollable when the column has the focus: then it
        renders taller and shows a window of it."""
        if self.focus != "panel":
            self.panel_scroll = 0
            return panel.render(tree, people, sel, queue, width, height)
        tall = panel.render(tree, people, sel, queue, width, height * 4)
        lines = list(getattr(tall, "renderables", [tall]))
        # The panel pads between its body and the queue: keep one blank.
        out, blank = [], 0
        for t in lines:
            blank = blank + 1 if isinstance(t, Text) and not t.plain else 0
            if blank <= 1:
                out.append(t)
        top = max(0, len(out) - height)
        self.panel_scroll = max(0, min(self.panel_scroll, top))
        return Group(*out[self.panel_scroll:self.panel_scroll + height])

    def side_title(self, sel):
        kind = sel.get("kind")
        label = {"family": "família", "branch": "branca", "person": "persona",
                 "item": "punt"}.get(kind, "")
        return "Detall" + (f" · {label}" if label else "")

    def placeholder(self, sel, queue, width, height):
        """Without panel.py: what is selected and the queue, as text."""
        out = [Text(f"panel.py no disponible: {clip(PANEL_ERR or '', width)}",
                    style="dim")]
        if sel.get("kind"):
            what = sel.get("person") or (sel.get("item") or {}).get("title") \
                or sel.get("row") or sel.get("family")
            out.append(Text(f"{sel['kind']}: {clip(str(what), width - 10)}"))
        out.append(Text(""))
        out.append(Text(f"Cua ({len(queue)})", style="bold"))
        for e in reversed(queue[-max(1, height - 4):]):
            out.append(Text(clip(f"{e.get('status')} · {e.get('label')} · "
                                 f"{e.get('agent')}", width), style="dim"))
        return Group(*out)

    # .. overlay and footer

    def overlay_panel(self, height):
        o = self.overlay
        inner = max(1, height - 2)
        lines = o["lines"]
        o["scroll"] = max(0, min(o["scroll"], max(0, len(lines) - inner)))
        shown = lines[o["scroll"]:o["scroll"] + inner]
        body = Text("\n".join(shown))
        more = len(lines) - o["scroll"] - inner
        sub = Text(f" ↓ {more} línies més · j/k ↑↓ PgUp/PgDn · Esc tanca "
                   if more > 0 else " Esc tanca ", style="dim")
        return Panel(body, title=Text(o["title"], style="bold"),
                     title_align="left", subtitle=sub, subtitle_align="right",
                     height=height, border_style="cyan")

    def menu_entries(self, sel):
        """[(key, label, mode)] of the actions menu: the selection's
        actions (the lowercase ones; an uppercase key sends) and the
        lookup, or [] when it has no actions."""
        out = [(a["key"], a["label"], a["mode"])
               for a in actions.catalogue(sel["kind"])
               if a["mode"] == "prefill"]
        if out:
            out.append(("l", "consulta la fitxa", "lookup"))
        return out

    def menu_panel(self, height):
        """The actions menu, in the right column: the list stays in sight."""
        m = self.menu
        orch = self.m.cfg["arbre"].get("orchestrator_agent") or "orquestrador"
        research = self.m.cfg["arbre"].get("research_agent") or "recerca"
        t = Text()
        for i, (key, label, mode) in enumerate(m["entries"]):
            on = i == m["at"]
            t.append(" ▶ " if on else "   ", style="bold cyan")
            t.append(f" {key} ", style="bold black on cyan" if on else "bold")
            t.append(f" {label}\n", style="bold" if on else "")
            if mode == "prefill":
                t.append(f"       → {orch}", style="dim")
                if actions.find(m["kind"], key.upper()):
                    t.append(f" · {key.upper()} → {research}", style="dim")
                t.append("\n")
        sub = Text(" ⏎ o la tecla · Esc tanca ", style="dim")
        return Panel(t, title=Text(m["title"], style="bold"),
                     title_align="left", subtitle=sub, subtitle_align="right",
                     height=height, border_style="cyan")

    def open_menu(self):
        sel = self.selection()
        entries = self.menu_entries(sel)
        if not entries:
            self.say("res a fer amb aquesta selecció")
            return
        title = "Accions"
        if sel["kind"] == "person":
            node = self.node()
            title += " · " + actions.person_name(
                (node or {}).get("person"), sel["person"])
        self.menu = {"title": title, "kind": sel["kind"], "entries": entries,
                     "at": 0}

    def handle_menu(self, key):
        m = self.menu
        entries = m["entries"]
        if key in ("\x1b", "q", "m"):
            self.menu = None
        elif key in ("j", "\x1b[B"):
            m["at"] = min(len(entries) - 1, m["at"] + 1)
        elif key in ("k", "\x1b[A"):
            m["at"] = max(0, m["at"] - 1)
        else:
            if key in ("\r", "\n"):
                key = entries[m["at"]][0]
            if key == "l" or actions.find(m["kind"], key):
                self.menu = None
                self.run_key(key)
        return True

    def run_key(self, key):
        """A key as if pressed on the list: an action, or the lookup."""
        if key == "l":
            self.start_lookup_input()
        else:
            self.act(key)

    def action_keys(self, kind):
        """The footer's part for the selection's actions: each lowercase
        key, then the uppercase ones together."""
        cat = actions.catalogue(kind)
        if not cat:
            return []
        orch = self.m.cfg["arbre"].get("orchestrator_agent") or "orquestrador"
        research = self.m.cfg["arbre"].get("research_agent") or "recerca"
        keys = [(a["key"], a["label"]) for a in cat if a["mode"] == "prefill"]
        keys[-1] = (keys[-1][0], f"{keys[-1][1]} → {orch}")
        upper = "/".join(a["key"] for a in cat if a["mode"] == "send")
        keys.append((upper, f"→ {research}"))
        return keys

    def footer(self):
        now = time.time()
        t = Text()
        if self.input:
            t.append(f" {self.input['prompt']} ", style="bold black on cyan")
            t.append(" " + self.input["buf"] + "▏")
            t.append("   ⏎ consulta · Esc cancel·la", style="dim")
            return t
        if self.confirm and now < self.confirm[2]:
            t.append(f" {self.confirm[3]} ", style="bold black on yellow")
            if self.confirm[4]:
                import textwrap
                width = self.console.size[0] - 2
                for ln in textwrap.wrap(self.confirm[4], width)[:4]:
                    t.append("\n " + ln, style="yellow")
            t.append("\n")
        elif self.busy:
            t.append(" ⟳ " + clip(self.busy, self.console.size[0] - 4),
                     style="bold cyan")
            t.append("\n")
        elif self.flash[0] and now - self.flash[1] < FLASH_SECS:
            t.append(" " + clip(self.flash[0], self.console.size[0] - 2),
                     style="bold cyan")
            t.append("\n")
        if self.menu:
            keys = [("↑↓", "mou"), ("⏎", "tria"), ("Esc/m", "tanca")]
        elif self.overlay:
            keys = [("j/k", "desplaça"), ("Esc/q", "tanca")]
        else:
            n = self.node()
            kind = self.selection().get("kind")
            keys = [("↑↓", "mou")]
            if self.focus == "panel":
                keys = [("j/k", "desplaça el detall")]
            elif n and n["kind"] in OPEN_BY_DEFAULT:
                keys.append(("⏎", "tanca" if n["open"] else "obre"))
            keys += self.action_keys(kind)
            if actions.catalogue(kind):
                keys.append(("m", "menú"))
            keys += [("l", "consulta"), ("v", "valida"), ("w", "web"),
                     ("a", "recerca"), ("t", "terminal"), ("u", "refresca"),
                     ("Tab", "llista" if self.focus == "panel"
                      else "detall"), ("q", "surt")]
        for k, what in keys:
            t.append(f" {k}", style="bold")
            t.append(f" {what} ", style="dim")
        if DRY_RUN:
            t.append(" [dry-run]", style="bold magenta")
        return t

    # -- keys

    def move(self, d):
        self.refresh_nodes()
        ids = [n["id"] for n in self.nodes if n["kind"] != "info"]
        if not ids:
            return
        if self.cursor in ids:
            i = ids.index(self.cursor)
        else:
            # On an info line (or nowhere): from where it sits in the list.
            all_ids = [n["id"] for n in self.nodes]
            pos = all_ids.index(self.cursor) if self.cursor in all_ids else 0
            i = sum(1 for n in self.nodes[:pos] if n["kind"] != "info") - \
                (1 if d > 0 else 0)
        self.cursor = ids[max(0, min(len(ids) - 1, i + d))]
        self.confirm = None

    def toggle(self, node, want=None):
        if node["kind"] not in OPEN_BY_DEFAULT:
            return False
        new = (not node["open"]) if want is None else want
        self.opened[node["id"]] = new
        return True

    def ask(self, action, key, prompt, preview=""):
        """Second press of the same key within CONFIRM_SECS confirms."""
        now = time.time()
        c = self.confirm
        if c and c[0] == action and c[1] == key and now < c[2]:
            self.confirm = None
            return True
        self.confirm = (action, key, now + CONFIRM_SECS, prompt, preview)
        return False

    def handle(self, key, live, term):
        if self.input:
            return self.handle_input(key)
        if self.menu:
            return self.handle_menu(key)
        if self.overlay:
            o = self.overlay
            if key in ("\x1b", "q", "\r", "\n"):
                self.overlay = None
            elif key in ("j", "\x1b[B"):
                o["scroll"] += 1
            elif key in ("k", "\x1b[A"):
                o["scroll"] = max(0, o["scroll"] - 1)
            elif key in ("\x1b[6~", " "):
                o["scroll"] += self.console.size[1] - 6
            elif key == "\x1b[5~":
                o["scroll"] = max(0, o["scroll"] - (self.console.size[1] - 6))
            elif key in ("g", "\x1b[H"):
                o["scroll"] = 0
            return True
        if key in ("q", "\x03"):
            return False
        self.refresh_nodes()
        if key == "\t":
            self.focus = "panel" if self.focus == "list" else "list"
            self.confirm = None
        elif self.focus == "panel" and key in ("j", "k", "\x1b[A", "\x1b[B",
                                                "\x1b[5~", "\x1b[6~"):
            step = {"j": 1, "\x1b[B": 1, "k": -1, "\x1b[A": -1,
                    "\x1b[6~": 10, "\x1b[5~": -10}[key]
            self.panel_scroll = max(0, self.panel_scroll + step)
        elif key in ("j", "\x1b[B"):
            self.move(1)
        elif key in ("k", "\x1b[A"):
            self.move(-1)
        elif key == "\x1b[6~":
            self.move(10)
        elif key == "\x1b[5~":
            self.move(-10)
        elif key in ("\r", "\n", " "):
            n = self.node()
            if n and not self.toggle(n):
                self.say(self.leaf_hint(n))
        elif key == "\x1b[C":
            n = self.node()
            if n:
                self.toggle(n, True)
        elif key == "\x1b[D":
            n = self.node()
            if n and n["kind"] in OPEN_BY_DEFAULT and n["open"]:
                self.toggle(n, False)
            elif n and self.parent(n):
                self.cursor = self.parent(n)["id"]
        elif key == "\x1b":
            # Back out of a branch: to its row, closed.
            self.confirm = None
            n = self.node()
            while n and n["depth"] > 1:
                n = self.parent(n)
            if n and n["kind"] == "row":
                self.cursor = n["id"]
                self.toggle(n, False)
        elif key == "u":
            self.m.kick_tree.set()
            self.m.kick_agents.set()
            self.say("refrescant…")
        elif key == "l":
            self.start_lookup_input()
        elif key == "m":
            self.open_menu()
        elif key == "v":
            if self.m.validate(force=True):
                self.say("validant l'arbre en segon pla…")
            else:
                self.say("ja s'està validant")
        elif key == "w":
            self.open_web()
        elif key == "t":
            self.shell(self.m.tree_path, live, term)
        elif key == "a":
            self.go_agent(self.m.cfg["arbre"].get("research_agent"))
        elif len(key) == 1 and key.isalpha():
            self.act(key)
        return True

    def leaf_hint(self, n):
        kind = selection_of(n).get("kind")
        keys = [a["key"] for a in actions.catalogue(kind)
                if a["mode"] == "prefill"]
        return ("tecles: " + " · ".join(
            f"{a['key']} {a['label']}" for a in actions.catalogue(kind)
            if a["mode"] == "prefill")) if keys else ""

    def start_lookup_input(self):
        hint = self.lookup_default()
        self.input = {"prompt": "consulta" + (f" (buit = {hint})"
                                              if hint else ""),
                      "buf": "", "default": hint}

    def lookup_default(self):
        sel = self.selection()
        if sel["kind"] == "person":
            return sel["person"]
        if sel["kind"] == "item" and (sel["item"] or {}).get("id"):
            return sel["item"]["id"]
        if sel["kind"] == "family":
            tree = self.m.tree or {}
            keys = [k for r in tree.get("rows", [])
                    if r["family"] == sel["family"] for k in r["branches"]]
            return " ".join(f"rama/{k}" for k in keys)
        return " ".join(f"rama/{k}" for k in sel["branches"])

    def handle_input(self, key):
        inp = self.input
        if key == "\x1b":
            self.input = None
        elif key in ("\r", "\n"):
            query = inp["buf"].strip() or inp.get("default")
            self.input = None
            if query:
                self.lookup(query)
        elif key in ("\x7f", "\x08"):
            inp["buf"] = inp["buf"][:-1]
        elif key == "\x15":   # ctrl-u
            inp["buf"] = ""
        elif len(key) == 1 and key.isprintable():
            inp["buf"] += key
        return True

    # -- actions

    def act(self, key):
        """An action key on the selection (actions.py): prefill the
        orchestrator now, or send to the research agent on a second press."""
        sel = self.selection()
        a = actions.find(sel["kind"], key)
        if not a:
            return
        if self.busy:
            self.say(f"espera: {self.busy}")
            return
        tree, _, _, _ = self.m.snapshot()
        node = self.node()
        person = node.get("person") if node else None
        plan = actions.build(self.m.cfg, tree, sel, key, person=person,
                             refs=self.item_refs(sel))
        cfg = self.m.cfg["arbre"]
        if plan["mode"] == "send":
            name = cfg.get("research_agent")
            agent = self.m.agent(name)
            if agent and agent.get("state") == "waiting":
                self.say(f"{name} espera una resposta teva (aprovació o "
                         "pregunta): a hi va; no li envio res")
                return
            what = f"enviar a {name}" if agent else \
                f"engegar {name} (pestanya nova a Arxiu) i enviar-li"
            if not self.ask(key, f"{plan['target']}#{plan['what']}",
                            f"prem {key} de nou per {what}:", plan["prompt"]):
                return

        def status(msg):
            self.busy = msg
            self.m.changed.set()

        def work():
            try:
                ok, msg = actions.run(self.m.cfg, plan, status)
            except Exception as e:  # noqa: BLE001 -- a thread must not die silently
                ok, msg = False, f"{type(e).__name__}: {e}"
            self.busy = ""
            if not ok and plan["mode"] == "prefill":
                msg += f" · {key.upper()} ho envia a {cfg.get('research_agent')}"
            self.say(msg if ok else f"no s'ha pogut: {msg}")
            self.m.kick_agents.set()
            self.m.changed.set()
        status(f"{'escrivint a' if plan['mode'] == 'prefill' else 'enviant a'} "
               f"{plan['agent']}…")
        threading.Thread(target=work, daemon=True).start()

    def item_refs(self, sel):
        """The people and sources the selected item mentions (people.py),
        for its prompt's starting point."""
        _, ppl, _, _ = self.m.snapshot()
        if sel["kind"] != "item" or not people_mod or not ppl \
                or ppl.get("fallback"):
            return None
        try:
            refs = people_mod.item_refs(ppl, sel["item"])
        except Exception:  # noqa: BLE001
            return None
        return list(refs.get("people") or []) + list(refs.get("sources") or [])

    def lookup(self, query):
        """`uv run scripts/lookup.py <query>` in the tree, into an overlay.
        Each word is one query, like on the command line."""
        args = shlex.split(query) if query.count('"') % 2 == 0 \
            else query.split()
        self.overlay = {"title": f"🔎 lookup {query}", "scroll": 0,
                        "lines": ["consultant…"]}

        def work():
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            code, out, err = sh(["uv", "run", "--quiet", "--script",
                                 "scripts/lookup.py", *args],
                                timeout=120, cwd=self.m.tree_path, env=env)
            text = out if code == 0 else (out + "\n" + err).strip()
            if self.overlay and self.overlay["title"].endswith(query):
                self.overlay["lines"] = (text or "(cap resultat)").splitlines()
            self.m.changed.set()
        threading.Thread(target=work, daemon=True).start()

    def open_web(self):
        index = os.path.join(self.m.tree_path, "build", "web", "index.html")
        if not os.path.exists(index):
            self.say("no hi ha web construïda: `make html` a l'arbre la "
                     "genera (build/web/index.html)")
            return
        if DRY_RUN:
            self.say(f"dry-run: obriria {index}")
            return
        target = index
        if shutil.which("wslview"):
            cmd = ["wslview", index]
        elif shutil.which("explorer.exe") and shutil.which("wslpath"):
            code, out, _ = sh(["wslpath", "-w", index])
            target = out.strip() if code == 0 else index
            cmd = ["explorer.exe", target]
        elif shutil.which("xdg-open"):
            cmd = ["xdg-open", index]
        elif shutil.which("open"):
            cmd = ["open", index]
        else:
            self.say(f"no sé obrir el navegador: {index}")
            return
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        self.say("obrint la web de l'arbre")

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
        if DRY_RUN:
            self.say("dry-run: " + shlex.join(args))
            return True
        code, out, err = sh(args, timeout=20)
        if code != 0:
            self.say(f"popup de herdr fallida: {clip(err or out, 100)}")
        return code == 0

    def go_agent(self, name):
        if not name:
            return
        if not self.m.agent(name):
            self.say(f"«{name}» no corre a herdr · una acció en majúscula "
                     "l'engega")
            return
        ok, msg = agents.focus(name)
        self.say(msg if DRY_RUN or not ok else f"→ {name}")

    def shell(self, path, live, term):
        if self.popup("shell", {}, cwd=path):
            return
        if DRY_RUN:
            self.say(f"dry-run: shell a {path}")
            return
        if term is not None:
            term.suspend(live, [os.environ.get("SHELL", "sh")], cwd=path)


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
        """Keys typed since the last call, split into single characters and
        whole escape sequences (one read can carry several)."""
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
    cfg = agents.load_config()
    model = Model(cfg)
    if panel is not None and hasattr(panel, "set_on_ready"):
        panel.set_on_ready(model.changed.set)

    if "--once" in args:
        # One frame on stdout, for checking the layout without a TTY. Keys
        # given with --keys are replayed first (e.g. --keys $'\r\x1b[B').
        model.tree_sig = arbre_data.changed_signature(model.tree_path)
        model.load_tree()
        model.refresh_agents()
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
            # Background work a key started (a lookup, an action): let it land.
            deadline = time.time() + 60
            while threading.active_count() > 1 and time.time() < deadline:
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
