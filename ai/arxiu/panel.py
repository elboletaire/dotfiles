"""The right column of Arxiu: what the selection is about, and the queue.

board.py imports it (it runs under uv with rich); the data comes from
arbre_data.py (the Tree) and people.py (People).

    render(tree, people, selection, queue_entries, width, height)

returns a rich renderable of exactly `height` lines, none wider than
`width`: the panel of the selection on top (a pedigree chart, completeness
bars, a lookup card) and the queue of actions at the bottom.

Lookup cards come from the tree's own `scripts/lookup.py`, run in the
background (it takes about half a second): `render` never waits for it. It
shows "consultant…" (or the last card of the same query, marked as being
refreshed) and starts the lookup; when it finishes, the callback given to
`set_on_ready()` is called from the worker thread, and the board redraws.
`prefetch()` starts one ahead of time (when the cursor lands on a person,
say). Cards are cached in memory and under ~/.cache/arxiu/lookup/, per query,
git HEAD and the tree's fingerprint (lookup.py reads the notes as they are,
uncommitted edits included).

In board.py:

    panel.set_on_ready(wake)       # once; wake() must only flag a redraw
    tree = arbre_data.load(path); ppl = people.load(path, tree)
    panel.prefetch(slug, tree["path"], tree["head"], tree["fingerprint"])
    view = panel.render(tree, ppl, selection, queue_entries, w, h)

`pending_lookups()` says whether a card is still on its way.
"""
import hashlib
import os
import re
import textwrap
import threading
import time
from datetime import datetime

from rich.console import Group
from rich.text import Text

import arbre_data
import people as people_mod

LOOKUP_DIR = os.path.join(arbre_data.CACHE_DIR, "lookup")
LOOKUP_KEEP = 300          # cached cards kept on disk
LOOKUP_WORKERS = 2         # lookups running at once
LOOKUP_MAX_QUERIES = 4     # people/sources of an item looked up together

STATUS_GLYPH = {"prefilled": ("✎", "cyan"), "sent": ("✉", "cyan"),
                "working": ("◐", "yellow"), "waiting": ("⏸", "bold red"),
                "done": ("✓", "green"), "error": ("✗", "bold red"),
                "stopped": ("■", "#8a8a8a"),
                "discarded": ("⨯", "#6a6a6a")}
EMPTY_BAR = "#4a4a4a"
MUTED = "#8a8a8a"
MISSING = "#6a6a6a"
KIND_LABEL = {"docs": "document a aconseguir",
              "people": "persona per identificar",
              "cut": "branca que es talla", "photos": "foto per identificar",
              "leads": "pista de cerca", "other": "pendent",
              "searched": "cerca ja feta", "contradictions": "incoherència",
              "discarded": "descartat", "review": "font per revisar"}


# ------------------------------------------------------------------ helpers

def readable(hex_colour, floor=0.22):
    """A branch colour that reads on a dark terminal: dark ones are blended
    towards white until their relative luminance reaches `floor`."""
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(hex_colour or ""))
    if not m:
        return "white"
    rgb = [int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4)]

    def lum(c):
        lin = [(v / 255) / 12.92 if v <= 10 else ((v / 255 + 0.055) / 1.055)
               ** 2.4 for v in c]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    t = 0.0
    out = rgb
    while lum(out) < floor and t < 1:
        t += 0.05
        out = [round(v + (255 - v) * t) for v in rgb]
    return "#" + "".join(f"{v:02x}" for v in out)


def dimmed(hex_colour):
    """The same colour, half way to the background: probable links, bars."""
    m = re.fullmatch(r"#([0-9a-fA-F]{6})", hex_colour or "")
    if not m:
        return MUTED
    rgb = [int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(v * 0.55 + 0x20 * 0.45):02x}" for v in rgb)


def ago(at, now=None):
    """Compact Catalan age: ara, 5m, 3h, 2d, 4set, 3mes."""
    if at is None:
        return "–"
    if isinstance(at, str):
        try:
            at = datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return "–"
    secs = max(0, int((now or time.time()) - float(at)))
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
        return f"{days // 7}set"
    return f"{days // 30}mes"


def line(*parts, width):
    """One panel line from (text, style) parts, cut to `width`."""
    t = Text(no_wrap=True, overflow="ellipsis")
    for p in parts:
        if isinstance(p, Text):
            t.append_text(p)
        else:
            t.append(*p) if isinstance(p, tuple) else t.append(p)
    t.truncate(width, overflow="ellipsis")
    return t


def wrapped(text, width, style="", indent=""):
    """Plain text wrapped to `width` -> lines."""
    out = []
    for ln in textwrap.wrap(text or "", max(8, width), subsequent_indent=indent,
                            break_long_words=True,
                            break_on_hyphens=False) or [""]:
        out.append(line((ln, style), width=width))
    return out


def years(rec):
    """1880–1950, *c.1844, *1987, †1950 or '' (* born, † died)."""
    if not rec:
        return ""

    def one(key):
        y = rec.get(key + "_year")
        if not y:
            return ""
        return ("c." if people_mod.approximate(rec.get(key)) else "") + str(y)

    b, d = one("born"), one("died")
    if b and d:
        return f"{b}–{d}"
    if b:
        return f"*{b}"
    if d:
        return f"†{d}"
    return ""


def name_forms(name):
    """A name from longest to shortest without cutting a word: whole, then
    the surnames from the last one as initials ("Josep Ferrer S.", "Josep
    F. S.")."""
    words = name.split()
    out = [name]
    for keep in range(len(words) - 1, 0, -1):
        out.append(" ".join(words[:keep] + [w[0] + "." for w in words[keep:]
                                            if w[0].isalpha()]))
    return out


def short_name(rec_or_name, room):
    """A name in `room` cells: the longest of name_forms that fits, else
    cut with an ellipsis."""
    name = rec_or_name["name"] if isinstance(rec_or_name, dict) else \
        str(rec_or_name)
    for cand in name_forms(name):
        if len(cand) <= room:
            return cand
    if room <= 1:
        return "…"[:max(0, room)]
    return name[:room - 1].rstrip() + "…"


def fits_whole(name, room):
    """Some form of the name fits in `room` without a hard cut."""
    return any(len(c) <= room for c in name_forms(name))


class Colours:
    """Branch key -> readable colour, from the Tree's branches."""

    def __init__(self, tree, people):
        branches = (tree or {}).get("branches") or \
            list((people or {}).get("branches", {}).values())
        self.raw = {b["key"]: b.get("colour") or "#9a958c" for b in branches}
        self.map = {k: readable(v) for k, v in self.raw.items()}
        self.names = {b["key"]: b.get("name") or b["key"] for b in branches}

    def of(self, key):
        return self.map.get(key, "white")

    def person(self, rec):
        """A person's colour: their branch's when they have one only."""
        keys = (rec or {}).get("branches") or []
        return self.of(keys[0]) if len(keys) == 1 else "white"


# ----------------------------------------------------------------- pedigree

def pedigree_lines(people, slug, depth, width, colours, highlight=None):
    """A sideways pedigree: the father's side above each person, the
    mother's below, one generation every three columns. `?` marks a parent
    the tree does not record; a probable link is drawn dashed and dim."""
    tree = people_mod.pedigree(people, slug, depth)
    if not tree:
        return [], False
    rows = []

    def walk(node, bits, confs, gen):
        expand = node is not None and node["person"] is not None and \
            gen < depth
        if expand:
            walk(node["father"], bits + (0,), confs + (node["confidence"],),
                 gen + 1)
        rows.append((node, bits, confs))
        if expand:
            walk(node["mother"], bits + (1,), confs + (node["confidence"],),
                 gen + 1)

    walk(tree, (), (), 1)
    out, probable = [], False
    for node, bits, confs in rows:
        t = Text(no_wrap=True, overflow="ellipsis")
        d = len(bits)
        for k in range(1, d):
            dashed = confs[k - 1] == "probable"
            if bits[k - 1] != bits[k]:
                t.append("┆" if dashed else "│",
                         MUTED if dashed else "#9a9a9a")
                t.append("  ")
            else:
                t.append("   ")
        if d:
            dashed = confs[d - 1] == "probable" and node is not None
            probable |= dashed
            t.append(("┌" if bits[-1] == 0 else "└") + ("╌" if dashed else "─")
                     + " ", MUTED if dashed or node is None else "#9a9a9a")
        room = width - t.cell_len
        if node is None:
            t.append("?", MISSING)
        else:
            rec = node["person"]
            ys = years(rec)
            style = colours.person(rec)
            if d == 0 or node["slug"] == highlight:
                style += " bold"
            # The years go before the name is cut.
            name_room = room - (len(ys) + 1 if ys else 0)
            if ys and not fits_whole(node["name"], name_room):
                ys, name_room = "", room
            t.append(short_name(node["name"], max(1, name_room)), style)
            if ys:
                t.append(" " + ys, MUTED)
            if node["more"] and t.cell_len + 2 <= width:
                t.append(" ›", MUTED)
        t.truncate(width, overflow="ellipsis")
        out.append(t)
    return out, probable


def legend(width, chart):
    """The key of a chart's marks, only those it uses ([] when none)."""
    plain = "\n".join(t.plain for t in chart)
    parts = []
    if "╌" in plain:
        parts += [("╌ ", MUTED), ("probable  ", MUTED)]
    if re.search(r"─ \?$", plain, re.M):
        parts += [("? ", MISSING), ("sense dades  ", MUTED)]
    if "›" in plain:
        parts += [("› ", MUTED), ("en sabem més", MUTED)]
    if not parts:
        return []
    t = line(*parts, width=width)
    t.rstrip()
    return [t]


# ------------------------------------------------------------------- bars

def bar(value, total, room, colour):
    room = max(1, room)
    full = round(room * value / total) if total else 0
    if value and not full:
        full = 1
    return [("█" * full, colour), ("░" * (room - full), EMPTY_BAR)]


def bars(rows, total, width, colour):
    """rows: (label, value, style) -> completeness lines."""
    label_w = min(17, max(8, width // 3))
    num_w = len(str(total)) + 1
    room = min(32, width - label_w - num_w - 1)
    out = []
    for label, value, style in rows:
        c = colour if style != "dim" else dimmed(colour)
        out.append(line((f"{label[:label_w]:<{label_w}} ", MUTED),
                        *bar(value, total, room, c),
                        (f"{value:>{num_w}}", "bold" if value else MUTED),
                        width=width))
    return out


def stacked(parts, total, room):
    """[(value, colour)] -> one bar split in proportion."""
    out, used = [], 0
    for value, colour in parts:
        n = round(room * value / total) if total else 0
        if value and not n:
            n = 1
        n = min(n, room - used)
        out.append(("█" * n, colour))
        used += n
    out.append(("░" * (room - used), EMPTY_BAR))
    return out


# ------------------------------------------------------------------ lookup

_LOOK = {}            # key -> {"state": pending|done|error, "text", "at"}
_LAST = {}            # queries -> text of the newest card (any HEAD)
_LOOK_LOCK = threading.Lock()
_SLOTS = threading.Semaphore(LOOKUP_WORKERS)
_ON_READY = None


def set_on_ready(callback):
    """`callback()` is called (from a worker thread) when a lookup finishes:
    the board should only wake its loop and redraw."""
    global _ON_READY
    _ON_READY = callback


def _queries(q):
    return tuple(q) if isinstance(q, (list, tuple)) else (q,)


def _key(queries, head, fingerprint):
    raw = "\x00".join(queries) + f"\x01{head}\x01{fingerprint}"
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def lookup_cmd(queries):
    """The tree's read-only lookup script; ARXIU_LOOKUP_CMD overrides it
    (`{q}` is replaced by the queries)."""
    env = os.environ.get("ARXIU_LOOKUP_CMD")
    if env:
        return ["sh", "-c", env.replace("{q}", " ".join(queries))]
    return ["uv", "run", "--quiet", "--script", "scripts/lookup.py",
            *queries]


def _run_lookup(tree_path, queries):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    code, out, err = arbre_data.sh(lookup_cmd(queries), cwd=tree_path,
                                   timeout=60, env=env)
    return code == 0, out if code == 0 else (err or out).strip()[-400:]


def _disk(key):
    return os.path.join(LOOKUP_DIR, key + ".txt")


def _store(key, text):
    try:
        os.makedirs(LOOKUP_DIR, exist_ok=True)
        tmp = _disk(key) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, _disk(key))
        files = sorted((e for e in os.scandir(LOOKUP_DIR)
                        if e.name.endswith(".txt")),
                       key=lambda e: e.stat().st_mtime)
        for e in files[:max(0, len(files) - LOOKUP_KEEP)]:
            os.unlink(e.path)
    except OSError:
        pass


ASK = object()     # "no head given": ask git (None is a tree with no git)


def _head(tree_path, head):
    return arbre_data.git_head(tree_path) if head is ASK else head


def card(queries, tree_path, head=ASK, fingerprint=None, start=True):
    """The lookup card of `queries` (a slug, an F0xx, or a list) without
    waiting: {"state": done|pending|error, "text": str | None,
    "stale": text of an older card of the same query, or None}. A miss
    starts the lookup in the background (unless `start` is False). Pass the
    Tree's `head` (else git is asked, a few ms) and `fingerprint`."""
    queries = _queries(queries)
    tree_path = os.path.abspath(os.path.expanduser(tree_path))
    head = _head(tree_path, head)
    key = _key(queries, head, fingerprint)
    with _LOOK_LOCK:
        hit = _LOOK.get(key)
        if hit:
            return dict(hit, stale=_LAST.get(queries))
    try:
        with open(_disk(key), encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        text = None
    if text is not None:
        hit = {"state": "done", "text": text, "at": time.time()}
        with _LOOK_LOCK:
            _LOOK[key] = hit
            _LAST[queries] = text
        return dict(hit, stale=None)
    if start:
        prefetch(queries, tree_path, head, fingerprint)
    return {"state": "pending", "text": None, "stale": _LAST.get(queries)}


def prefetch(queries, tree_path, head=ASK, fingerprint=None):
    """Start the lookup of `queries` (a slug, an F0xx, or a list) in the
    background unless it is cached or running. -> its state (done | pending
    | error). Same keys as card(): pass the Tree's `head` and
    `fingerprint`."""
    queries = _queries(queries)
    tree_path = os.path.abspath(os.path.expanduser(tree_path))
    head = _head(tree_path, head)
    key = _key(queries, head, fingerprint)
    with _LOOK_LOCK:
        if key in _LOOK:
            return _LOOK[key]["state"]
    if os.path.exists(_disk(key)):
        return card(queries, tree_path, head, fingerprint, start=False)["state"]
    with _LOOK_LOCK:
        if key in _LOOK:
            return _LOOK[key]["state"]
        _LOOK[key] = {"state": "pending", "text": None, "at": time.time()}

    def work():
        with _SLOTS:
            try:
                ok, text = _run_lookup(tree_path, list(queries))
            except Exception as e:      # a failed lookup is shown, not raised
                ok, text = False, str(e)
        with _LOOK_LOCK:
            _LOOK[key] = {"state": "done" if ok else "error", "text": text,
                          "at": time.time()}
            if ok:
                _LAST[queries] = text
        if ok:
            _store(key, text)
        cb = _ON_READY
        if cb:
            try:
                cb()
            except Exception:
                pass

    threading.Thread(target=work, daemon=True).start()
    return "pending"


def pending_lookups():
    """How many lookups are running: the board may keep redrawing while
    any is."""
    with _LOOK_LOCK:
        return sum(1 for v in _LOOK.values() if v["state"] == "pending")


def card_lines(res, width, budget, people=None, colours=None,
               compact=False):
    """A lookup card -> at most `budget` lines. Several cards (an item's
    people and sources) share the room; `compact` keeps each line of the
    card on one line instead of wrapping it."""
    if budget <= 0:
        return []
    text = res.get("text")
    note = None
    if res["state"] == "pending":
        if not res.get("stale"):
            return [line(("consultant la fitxa…", MUTED + " italic"),
                         width=width)]
        text, note = res["stale"], "actualitzant…"
    elif res["state"] == "error":
        return wrapped("no s'ha pogut consultar: " + (text or ""), width,
                       MUTED)[:budget]
    blocks = [[]]
    for raw in (text or "").splitlines():
        if raw.startswith("## ") and blocks[-1]:
            blocks.append([])
        if raw.strip():
            blocks[-1].append(raw)
    blocks = [b for b in blocks if b]
    out = [line((note, MUTED + " italic"), width=width)] if note else []
    room = budget - len(out)
    shares = [room // len(blocks) + (1 if i < room % len(blocks) else 0)
              for i in range(len(blocks))] if blocks else []
    for block, share in zip(blocks, shares):
        lines_ = []
        for raw in block:
            lines_ += _card_line(raw, width, people, colours, compact)
        if len(lines_) > share:
            cut = len(lines_) - share + 1
            lines_ = lines_[:max(0, share - 1)] + \
                [line((f"… {cut} línies més", MUTED), width=width)]
        out += lines_[:share]
    return out[:budget]


def _card_line(raw, width, people, colours, compact):
    persons = (people or {}).get("persons", {})
    if raw.startswith("## "):
        title = re.sub(r"\s+—\s+\S+\.md$", "", raw[3:])
        m = re.search(r"\[([^\]]+)\]$", title)
        style = "bold"
        if m and m.group(1) in persons and colours:
            style = colours.person(persons[m.group(1)]) + " bold"
        return [line((title, style), width=width)]
    if raw.startswith("- "):
        return [line(("· ", MUTED), (raw[2:], MUTED), width=width)]
    if raw.endswith(":") or re.match(r"^[a-z ]+ \(\d+[^)]*\):", raw):
        return [line((raw, "bold " + MUTED), width=width)]
    if compact:
        return [line(raw, width=width)]
    return wrapped(raw, width, "", indent="  ")


# ------------------------------------------------------------------ queue

def queue_lines(entries, width, budget, now=None):
    """The queue, newest first: glyph, age, label, agent."""
    entries = sorted(entries or [], key=lambda e: _epoch(e.get("at")),
                     reverse=True)
    title = f" Cua ({len(entries)}) " if entries else " Cua · buida "
    head = line(("──", MUTED), (title, "bold"),
                ("─" * max(0, width - len(title) - 2), MUTED), width=width)
    out = [head]
    rows = max(0, budget - 1)
    for i, e in enumerate(entries[:rows]):
        if i == rows - 1 and len(entries) > rows:
            out.append(line((f"… {len(entries) - rows + 1} més", MUTED),
                            width=width))
            break
        glyph, style = STATUS_GLYPH.get(e.get("status"), ("·", MUTED))
        label = e.get("label") or e.get("target") or e.get("kind") or "?"
        parts = [(glyph, style), (f" {ago(e.get('at'), now):>4} ", MUTED),
                 (label, "" if e.get("status") != "done" else MUTED)]
        if e.get("agent"):
            parts.append((f" · {e['agent']}", MUTED))
        out.append(line(*parts, width=width))
    return out[:max(1, budget)]


def _epoch(at):
    if isinstance(at, (int, float)):
        return at
    try:
        return datetime.fromisoformat(str(at).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0


# ------------------------------------------------------------------ kinds

def _branch_of(tree, people, key):
    for b in (tree or {}).get("branches") or []:
        if b["key"] == key:
            return b
    return (people or {}).get("branches", {}).get(key)


def branch_body(tree, people, key, width, budget, colours):
    b = _branch_of(tree, people, key) or {"key": key, "name": key}
    pb = people["branches"].get(key) or {"members": [], "root": None}
    colour = colours.of(key)
    fam = people["families"].get(b.get("family") or "", {})
    c = people_mod.completeness(people, key)
    out = [line(("■ ", colour), (b.get("name") or key, colour + " bold"),
                (f" · {c['people']} persones", MUTED),
                (f" · {fam.get('label')}" if fam.get("label") else "", MUTED),
                width=width)]
    root = pb["root"]
    chart, extra = [], []
    if root:
        configured = b.get("founder") == root
        chart.append(line(("fundador" if configured else "arrel (deduïda)",
                           MUTED), width=width))
        ped, _ = pedigree_lines(people, root, 3, width, colours)
        chart += ped
        chain = people_mod.line_of_descent(people, root)
        if len(chain) > 2:
            names = " › ".join(people["persons"][s]["given_name"] or s
                               for s in chain[1:])
            extra += wrapped("↓ " + names, width, MUTED, indent="  ")[:2]
        extra += legend(width, ped)
    else:
        chart.append(line(("sense fundador ni membres", MUTED), width=width))
    rows = [("amb fonts", c["with_sources"], ""),
            ("pares provats", c["parents_proven"], ""),
            ("pares probables", c["parents_probable"], "dim"),
            ("sense pares", c["parents_missing"], "dim"),
            ("amb naixement", c["with_birth"], ""),
            ("notes de recerca", c["with_research_notes"], ""),
            ("amb pendents", c["with_pending"], "dim")]
    comp = [line(("Completesa", "bold"), width=width)] + \
        bars(rows, c["people"], width, colour)
    foot = []
    if c["pending_items"] or c["contradictions"]:
        foot.append(line((f"{c['pending_items']} punts pendents · "
                          f"{c['contradictions']} amb incoherències",
                          MUTED), width=width))
    # What goes when room is short: the descent and the key first, then
    # the gap and the footnote; the chart and the bars stay.
    if len(out + chart + extra + comp + foot) + 1 > budget:
        extra = []
    gap = [Text()] if len(out + chart + comp + foot) + 1 <= budget else []
    if len(out + chart + gap + comp + foot) > budget:
        foot = []
    out += chart + extra + gap + comp + foot
    left = budget - len(out) - 2
    if left > 0:
        out += [Text(), line(("Per generacions", "bold"), width=width)]
        out += generation_lines(people, key, width, left, colours)
    return out[:budget]


def generation_lines(people, key, width, budget, colours):
    """One line per generation from the root: given names, in birth order."""
    gens = people_mod.generations(people, key)
    by = {}
    for rec in people_mod.branch_people(people, key):
        by.setdefault(gens.get(rec["slug"]), []).append(rec)
    out = []
    for g in sorted(by, key=lambda g: (g is None, g or 0)):
        recs = by[g]
        label = f"{g:>2} " if g is not None else " · "
        names = ", ".join(r["given_name"] or r["slug"] for r in recs)
        out.append(line((label, MUTED), (names, ""),
                        (f" ({len(recs)})" if len(recs) > 3 else "", MUTED),
                        width=width))
    if len(out) > budget:
        out = out[:max(0, budget - 1)] + [
            line((f"… {len(out) - budget + 1} generacions més", MUTED),
                 width=width)]
    return out[:budget]


def family_body(tree, people, key, width, budget, colours):
    fam = people["families"].get(key) or {"label": key, "branches": []}
    members = people_mod.family_people(people, key)
    out = [line((fam.get("label") or key, "bold"),
                (f" · {len(fam['branches'])} branques · "
                 f"{len(members)} persones", MUTED), width=width)]
    root = fam.get("root")
    if root:
        chart, _ = pedigree_lines(people, root, 3, width, colours)
        out += chart
        out += legend(width, chart)
    out.append(Text())
    label_w = min(16, max(8, width // 3))
    total_w = 4
    room = min(30, width - label_w - total_w - 2)
    out.append(line((f"{'branca':<{label_w}} ", MUTED),
                    ("█", "white"), (" provats ", MUTED),
                    ("█", dimmed("#d0d0d0")), (" probables ", MUTED),
                    ("░", EMPTY_BAR), (" sense", MUTED), width=width))
    biggest = max([len(people["branches"].get(k, {}).get("members", []))
                   for k in fam["branches"]] or [1]) or 1
    for k in fam["branches"]:
        c = people_mod.completeness(people, k)
        colour = colours.of(k)
        n = c["people"]
        # The bar's length is the branch's size against the biggest one,
        # split by how its parents are documented.
        length = max(1, round(room * n / biggest)) if n else 1
        parts = stacked([(c["parents_proven"], colour),
                         (c["parents_probable"], dimmed(colour))],
                        n, length)
        name = colours.names.get(k, k)
        if len(name) > label_w - 1:
            name = name[:label_w - 2].rstrip() + "…"
        out.append(line((f"{name:<{label_w}} ", colour), *parts,
                        (" " * (room - length)), (f" {n:>{total_w - 1}}",
                                                  "bold"), width=width))
    c = people_mod.completeness(people, family=key)
    if len(out) + 9 <= budget and c["people"]:
        out += [Text(), line(("Completesa de la família", "bold"),
                             width=width)]
        out += bars([("amb fonts", c["with_sources"], ""),
                     ("pares provats", c["parents_proven"], ""),
                     ("pares probables", c["parents_probable"], "dim"),
                     ("amb naixement", c["with_birth"], ""),
                     ("notes de recerca", c["with_research_notes"], ""),
                     ("amb pendents", c["with_pending"], "dim")],
                    c["people"], width, "#c8c8c8")
    return out[:budget]


def person_body(tree, people, slug, width, budget, colours):
    rec = people["persons"].get(slug)
    if not rec:
        return [line((f"{slug}: sense fitxa", MUTED), width=width)]
    ys = years(rec)
    out = [line((rec["name"], colours.person(rec) + " bold"),
                (f"  {ys}" if ys else "", MUTED), width=width)]
    chips = [("■", colours.of(k)) for k in rec["branches"]]
    info = f" {rec['sources']} fonts"
    if rec["pending"]:
        info += f" · {len(rec['pending'])} pendents"
    out.append(line(*chips, (info, MUTED), width=width))
    depth = 3 if budget >= 7 + 2 + 6 else 2
    chart, _ = pedigree_lines(people, slug, depth, width, colours)
    out += chart
    out += legend(width, chart)
    left = budget - len(out)
    if left > 1:
        res = card(slug, (tree or {}).get("path") or people["path"],
                   (tree or {}).get("head", ASK),
                   (tree or {}).get("fingerprint"))
        out += card_lines(_drop_title(res), width, left, people, colours)
    return out[:budget]


def _drop_title(res):
    """The person's card without its `## Name [slug]` line (the panel's
    header already says it)."""
    for k in ("text", "stale"):
        if res.get(k):
            lines = res[k].splitlines()
            if lines and lines[0].startswith("## ") and \
                    res[k].count("\n## ") == 0:
                res = dict(res, **{k: "\n".join(lines[1:])})
    return res


def item_body(tree, people, item, width, budget, colours):
    item = item or {}
    out = []
    title = item.get("title") or item.get("id") or "?"
    if item.get("id") and item.get("id") not in title:
        title = f"{item['id']} — {title}"
    out += [line((t.plain, "bold"), width=width)
            for t in wrapped(title, width)][:2]
    where = f"{item.get('file') or ''}"
    if item.get("line"):
        where += f":{item['line']}"
    kind = KIND_LABEL.get(item.get("kind"), item.get("kind") or "")
    out.append(line((" · ".join(x for x in (kind, where) if x), MUTED),
                    width=width))
    refs = people_mod.item_refs(people, item)
    srcs = list(refs["sources"])
    if item.get("id") and item["id"] not in srcs:
        srcs.insert(0, item["id"])
    persons = people["persons"]
    if refs["people"] or srcs:
        t = Text("esmenta: ", MUTED)
        for i, s in enumerate(refs["people"]):
            t.append(("" if i == 0 else ", "))
            t.append(short_name(persons[s], 28), colours.person(persons[s]))
        for i, s in enumerate(srcs):
            t.append(", " if (i or refs["people"]) else "")
            t.append(s, "bold")
        lines_ = t.wrap(_console(width), width, overflow="ellipsis")
        out += list(lines_)[:3]
    else:
        out.append(line(("no esmenta cap persona ni font", MUTED),
                        width=width))
    queries = (refs["people"][:3] + srcs)[:LOOKUP_MAX_QUERIES]
    left = budget - len(out) - 1
    if queries and left > 1:
        out.append(Text())
        res = card(queries, (tree or {}).get("path") or people["path"],
                   (tree or {}).get("head", ASK),
                   (tree or {}).get("fingerprint"))
        out += card_lines(res, width, left, people, colours,
                          compact=len(queries) > 1)
    return out[:budget]


_CONSOLES = {}


def _console(width):
    from rich.console import Console
    if width not in _CONSOLES:
        _CONSOLES[width] = Console(width=width, file=open(os.devnull, "w"),
                                   color_system=None)
    return _CONSOLES[width]


# ----------------------------------------------------------------- render

def body(tree, people, selection, width, budget):
    sel = selection or {}
    colours = Colours(tree, people)
    kind = sel.get("kind")
    if not people:
        return [line(("carregant les persones…", MUTED), width=width)]
    if kind == "person" and sel.get("person"):
        return person_body(tree, people, sel["person"], width, budget,
                           colours)
    if kind == "item" and sel.get("item"):
        return item_body(tree, people, sel["item"], width, budget, colours)
    if kind == "branch" and sel.get("branch"):
        return branch_body(tree, people, sel["branch"], width, budget,
                           colours)
    fam = sel.get("family")
    if not fam and sel.get("branch"):
        fam = (_branch_of(tree, people, sel["branch"]) or {}).get("family")
    if fam and fam in people["families"]:
        return family_body(tree, people, fam, width, budget, colours)
    if sel.get("branch"):
        return branch_body(tree, people, sel["branch"], width, budget,
                           colours)
    return [line(("selecciona una família, branca, persona o punt",
                  MUTED), width=width)]


def render(tree, people, selection, queue_entries, width, height, now=None):
    """The right column: the selection's panel on top, the queue at the
    bottom. Exactly `height` lines, none wider than `width`; never waits
    (lookups run in the background, see prefetch / set_on_ready)."""
    width = max(10, int(width))
    height = max(1, int(height))
    n = len(queue_entries or [])
    q_budget = 1 if not n else min(n, max(2, min(10, height // 4))) + 1
    if height < 6:
        q_budget = min(q_budget, 1)
    top_budget = max(0, height - q_budget - (1 if height >= 8 else 0))
    top = body(tree, people, selection, width, top_budget)[:top_budget]
    bottom = queue_lines(queue_entries, width, q_budget, now)
    pad = [Text() for _ in range(max(0, height - len(top) - len(bottom)))]
    lines_ = top + pad + bottom
    lines_ = lines_[:height]
    for t in lines_:
        t.no_wrap = True
        t.overflow = "ellipsis"
        if t.cell_len > width:
            t.truncate(width, overflow="ellipsis")
    return Group(*lines_)
