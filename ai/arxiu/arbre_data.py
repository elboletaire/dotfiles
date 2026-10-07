#!/usr/bin/env python3
"""Reads a family-tree-kit tree for Arxiu's 🌳 Arbre column.

Stdlib only: board.py imports it, and the tests run it with a bare python3.
Nothing here writes into the tree. The one command that could have --
`make validate` -- is replaced by its read-only half, `scripts/validate.py`
(see run_validation), and its result is cached under ~/.cache/arxiu/.

Everything specific to a tree comes from its `families.yml`: the data folders
(`paths`), the families and their `##` titles, the branches with their colour,
and the groups of branches that are the `###` headings of the research files.
Nothing names a folder or a branch of a particular tree.

`load(tree_path) -> Tree` returns a plain dict (the shape is documented on
load()). It is meant to be called again whenever the tree changes: notes and
research files are re-parsed only when their stat changes, and git is asked
again only when HEAD moves, so a refresh with nothing new costs a few
milliseconds.
"""
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata

DEFAULT_PATHS = {"people": "people", "sources": "sources",
                 "research": "research", "portraits": "portraits"}
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or
                         os.path.expanduser("~/.cache"), "arxiu")
# The research files of the kit. Their names are the engine's, not the tree's
# (only the folder they live in is the tree's).
PENDING_FILE = "pendientes.md"
CONTRADICTIONS_FILE = "incoherencias.md"
DISCARDED_FILE = "descartados.md"
REVIEW_FILE = "revision.md"
SOURCE_ID = re.compile(r"^F(\d+)$")

# What a `####` category of pendientes.md is about, by the words of its
# heading. The kit only speaks Spanish so far (`language: es`); a category no
# pattern knows is "other", never dropped.
CATEGORY_KINDS = (
    # Logs of searches already made: what NOT to repeat, not pending work.
    ("searched", re.compile(r"sin resultado|no repetir|sense resultat|"
                            r"no result|do not repeat", re.I)),
    # Other search logs (dated, or "búsquedas"): leads still to follow.
    ("leads", re.compile(r"b[uú]squeda|pistas|search|"
                         r"\(\d{1,2}-\d{1,2}-\d{4}\)", re.I)),
    ("photos", re.compile(r"foto|photo", re.I)),
    ("docs", re.compile(r"document|conseguir|petici[oó]n|archiv|request",
                        re.I)),
    ("people", re.compile(r"identificar|persona|identify|people", re.I)),
    ("cut", re.compile(r"se cortan|ramas que|dead end|cut", re.I)),
)
KIND_ORDER = ["docs", "people", "cut", "photos", "leads", "other"]

# Commits that touch notes without researching them: sweeping maintenance
# (a date convention applied to every note, regenerated reference sections).
# They would make every branch look researched today.
NOISE_SUBJECT = re.compile(r"^(chore|style|refactor|docs|test|build|ci)"
                           r"(\([^)]*\))?!?:", re.I)
NOISE_FILES = 80

STALE_DAYS = 21          # a branch not researched for longer is flagged
DIARY_LEN = 10
WEEK_SECS = 7 * 86400


# ------------------------------------------------------------------ helpers

def sh(args, cwd=None, timeout=30, env=None):
    # GIT_OPTIONAL_LOCKS=0: never refresh the tree's index, not even that.
    env = dict(env or os.environ, GIT_OPTIONAL_LOCKS="0")
    try:
        p = subprocess.run(args, capture_output=True, text=True, cwd=cwd,
                           timeout=timeout, env=env)
        return p.returncode, p.stdout, p.stderr
    except (subprocess.TimeoutExpired, OSError) as e:
        return 1, "", str(e)


def norm(text):
    """Heading text -> comparable key: no accents, no case, no trailing
    "(N)" count, nothing after a colon ("Familia reciente: padres y ..." is
    the same section as "Familia reciente")."""
    text = re.sub(r"\s*\(\d+\)\s*$", "", text or "")
    text = text.split(":", 1)[0]
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().lower()


def plain(md):
    """Markdown of an item -> the text a terminal can show: links become
    their label, emphasis and code marks go."""
    md = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md)
    md = re.sub(r"(\*\*|__|`)", "", md)
    md = re.sub(r"(?<![\w*])\*(?!\s)([^*]+)\*", r"\1", md)
    return re.sub(r"[ \t]+", " ", md).strip()


def stat_key(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


# --------------------------------------------------------- tiny YAML subset

def _scalar(s):
    s = s.strip()
    if not s:
        return None
    if s[0] in "\"'" and s[-1] == s[0] and len(s) >= 2:
        body = s[1:-1]
        return body.replace('\\"', '"') if s[0] == '"' else \
            body.replace("''", "'")
    if s in ("true", "True", "yes"):
        return True
    if s in ("false", "False", "no"):
        return False
    if s in ("null", "~"):
        return None
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    return s


def _strip_comment(line):
    """Drop a `# comment`, but not a `#` inside quotes (colours)."""
    out, q = [], None
    for i, c in enumerate(line):
        if q:
            if c == q:
                q = None
        elif c in "\"'":
            q = c
        elif c == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(c)
    return "".join(out).rstrip()


def _flow(s, i=0):
    """Parse a flow value ({...}, [...] or a scalar) at s[i:]; -> (value, end)."""
    while i < len(s) and s[i] == " ":
        i += 1
    if i < len(s) and s[i] in "[{":
        close = "]" if s[i] == "[" else "}"
        is_map = s[i] == "{"
        out = {} if is_map else []
        i += 1
        while True:
            while i < len(s) and s[i] in " ,":
                i += 1
            if i >= len(s) or s[i] == close:
                return out, i + 1
            if is_map:
                j = i
                while j < len(s) and s[j] != ":":
                    j += 1
                key = _scalar(s[i:j])
                val, i = _flow(s, j + 1)
                out[key] = val
            else:
                val, i = _flow(s, i)
                out.append(val)
    # A scalar ends at the next , ] or } outside quotes.
    j, q = i, None
    while j < len(s):
        c = s[j]
        if q:
            if c == q:
                q = None
        elif c in "\"'" and j == i:
            q = c
        elif c in ",]}":
            break
        j += 1
    return _scalar(s[i:j]), j


def parse_yaml(text):
    """The subset of YAML families.yml (and the notes' frontmatter) use:
    nested mappings by indentation, block lists (of scalars or of mappings),
    flow lists and flow mappings, quoted or bare scalars, comments.
    families.yml needs no more, and the board must run without PyYAML."""
    lines = []
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if line.strip():
            lines.append((len(line) - len(line.lstrip(" ")), line.strip()))

    def block(i, indent):
        """Parse the block starting at lines[i] (indent `indent`)."""
        if i < len(lines) and lines[i][1].startswith("- "):
            out = []
            while i < len(lines) and lines[i][0] == indent and \
                    (lines[i][1].startswith("- ") or lines[i][1] == "-"):
                rest = lines[i][1][2:].strip()
                m = re.match(r"^([^\s\[{\"'][^:]*):(\s|$)(.*)", rest)
                if m and not rest.startswith(("{", "[")):
                    # "- key: value" opens a mapping whose other keys sit
                    # two columns further in.
                    sub_indent = indent + 2
                    lines[i] = (sub_indent, rest)
                    val, i = mapping(i, sub_indent)
                    out.append(val)
                else:
                    out.append(_flow(rest)[0] if rest else None)
                    i += 1
            return out, i
        return mapping(i, indent)

    def mapping(i, indent):
        out = {}
        while i < len(lines) and lines[i][0] == indent and \
                not lines[i][1].startswith("- "):
            text_ = lines[i][1]
            key, _, rest = text_.partition(":")
            key, rest = _scalar(key), rest.strip()
            i += 1
            if rest:
                out[key] = _flow(rest)[0]
            elif i < len(lines) and (lines[i][0] > indent or
                                     (lines[i][0] == indent and
                                      lines[i][1].startswith("- "))):
                out[key], i = block(i, lines[i][0])
            else:
                out[key] = None
        return out, i

    if not lines:
        return {}
    return block(0, lines[0][0])[0]


def frontmatter(text):
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    try:
        return parse_yaml(text[3:end]) or {}
    except (ValueError, IndexError):
        return {}


def wikilink(v):
    m = re.match(r"^\[\[([^\]|#]+)", str(v or "").strip())
    return m.group(1) if m else str(v or "").strip()


# ----------------------------------------------------------------- config

def load_config(tree):
    """families.yml -> {paths, families, branches, other, groups}. Missing
    keys get the kit's defaults, so a half-started tree still loads."""
    cfg = parse_yaml(read(os.path.join(tree, "families.yml"))) or {}
    paths = dict(DEFAULT_PATHS)
    paths.update({k: v for k, v in (cfg.get("paths") or {}).items() if v})
    families = [{"key": f.get("key"), "label": f.get("label") or f.get("key"),
                 "title": f.get("title") or f.get("label") or f.get("key"),
                 "default": bool(f.get("default"))}
                for f in cfg.get("families") or [] if isinstance(f, dict)]
    groups = [{"family": g.get("family"), "title": g.get("title"),
               "branches": list(g.get("branches") or [])}
              for g in cfg.get("groups") or [] if isinstance(g, dict)]
    group_of = {b: g["title"] for g in groups for b in g["branches"]}
    branches = [{"key": b.get("key"), "name": b.get("label") or b.get("key"),
                 "colour": b.get("color") or "#9a958c",
                 "family": b.get("family"), "founder": b.get("founder"),
                 "group": group_of.get(b.get("key"))}
                for b in cfg.get("branches") or [] if isinstance(b, dict)]
    other = cfg.get("other_branch") or {}
    other = {"key": other.get("key") or "otras",
             "name": other.get("label") or "Otras familias",
             "colour": other.get("color") or "#9a958c",
             "family": None, "founder": None, "group": None}
    return {"paths": paths, "families": families, "branches": branches,
            "other": other, "groups": groups, "main": cfg.get("main")}


# ------------------------------------------------------- research markdown

def parse_research(text):
    """pendientes.md / incoherencias.md / descartados.md -> list of
    {family, section, category, title, text, line}. `family` and `section`
    are the raw `##` / `###` headings (None when an item sits right under a
    higher one); an item is a top-level `- ` bullet with everything indented
    under it, sub-lists and wrapped lines included."""
    items = []
    family = section = category = None
    cur = None
    blank = False

    def close():
        nonlocal cur
        if cur:
            body = "\n".join(cur["lines"]).strip()
            first = cur["lines"][0]
            m = re.match(r"^\s*\*\*(.+?)\*\*", first)
            title = plain(m.group(1)) if m else plain(first)
            items.append({"family": cur["family"], "section": cur["section"],
                          "category": cur["category"], "title": title,
                          "text": plain(body), "line": cur["line"]})
            cur = None

    for n, line in enumerate(text.splitlines(), 1):
        h = re.match(r"^(#{1,6})\s+(.*)$", line)
        if h:
            close()
            level, title = len(h.group(1)), h.group(2).strip()
            if level == 2:
                family, section, category = title, None, None
            elif level == 3:
                section, category = title, None
            elif level >= 4:
                category = title
            blank = False
            continue
        if line.startswith("- ") or line == "-":
            close()
            cur = {"family": family, "section": section, "category": category,
                   "lines": [line[2:]], "line": n}
            blank = False
            continue
        if not line.strip():
            blank = True
            continue
        if cur and (line.startswith((" ", "\t")) or not blank):
            cur["lines"].append(line.strip())
            blank = False
            continue
        # A paragraph at column 0 after a blank line: prose, not an item.
        close()
        blank = False
    close()
    return items


def parse_review(text):
    """revision.md -> list of {family, section, id, title}. A pending source
    is a heading whose text is a link starting with its id: `#### [F119 —
    title](...)` under a family's `###` group, or `### [F164 — ...]` right
    under a `##` (the General part)."""
    out = []
    family = section = None
    for line in text.splitlines():
        h = re.match(r"^(#{2,6})\s+(.*)$", line)
        if not h:
            continue
        level, title = len(h.group(1)), h.group(2).strip()
        m = re.match(r"^\[(F\d+)\s*[—–-]\s*(.*?)\]\(", title) or \
            re.match(r"^\[(F\d+)\s*[—–-]\s*(.*)$", title)
        if m:
            out.append({"family": family, "section": section,
                        "id": m.group(1), "title": plain(m.group(2))})
        elif level == 2:
            family, section = title, None
        elif level == 3:
            section = title
    return out


def category_kind(category):
    for kind, rx in CATEGORY_KINDS:
        if rx.search(category or ""):
            return kind
    return "other"


# ------------------------------------------------------------------ rows

def _title(heading):
    """A heading as a row title: no "(N)" count, nothing after a colon."""
    return re.sub(r"\s*\(\d+\)\s*$", "", heading.split(":", 1)[0]).strip()


class Rows:
    """The rows of the branch table: one per `groups` entry of families.yml
    (the `###` headings the research files use), in families.yml order, then
    one per heading no group matches ("Familia reciente", "Varias ramas",
    "Otras familias", "General"), so nothing is dropped."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.rows, self.by_id = [], {}
        self.fam_by_title = {norm(f["title"]): f for f in cfg["families"]}
        self.fam_by_title.update({norm(f["label"]): f
                                  for f in cfg["families"]})
        self.branch = {b["key"]: b for b in cfg["branches"]}
        self.branch[cfg["other"]["key"]] = cfg["other"]
        for g in cfg["groups"]:
            self.add(g["family"], g["title"], g["branches"], True)

    def add(self, family, title, branches, matched):
        rid = f"{family or ''}/{norm(title)}"
        if rid in self.by_id:
            return self.by_id[rid]
        cols = [self.branch[b]["colour"] for b in branches if b in self.branch]
        row = {"id": rid, "title": title, "family": family,
               "branches": list(branches), "colours": cols,
               "colour": cols[0] if cols else self.cfg["other"]["colour"],
               "matched": matched,
               "pending": {}, "searched": {}, "contradictions": {},
               "review": [], "discarded": [],
               "counts": {}, "last_research": None, "last_commit": None}
        self.rows.append(row)
        self.by_id[rid] = row
        return row

    def family(self, heading):
        """A `##` heading -> family key; "General" and unknown ones keep a
        key of their own so their items still show."""
        if heading is None:
            return None
        f = self.fam_by_title.get(norm(heading))
        return f["key"] if f else "~" + norm(heading)

    def find(self, family_heading, section):
        fam = self.family(family_heading)
        groups = [r for r in self.rows if r["matched"] and r["family"] == fam]
        if section is None:
            # Items right under a family: its only group if it has one,
            # else a row for the family as a whole.
            if len(groups) == 1:
                return groups[0]
            label = next((f["label"] for f in self.cfg["families"]
                          if f["key"] == fam), family_heading or "General")
            return self.add(fam, label, [], False)
        key = norm(section)
        for r in groups:
            t = norm(r["title"])
            if key == t or key.startswith(t) or t.startswith(key):
                return r
        # A heading named after one branch (or the "other" branch).
        for b in self.branch.values():
            if norm(b["name"]) == key:
                if b.get("group"):
                    hit = [r for r in groups if r["title"] == b["group"]]
                    if hit:
                        return hit[0]
                return self.add(fam, _title(section), [b["key"]], False)
        for r in self.rows:
            if r["family"] == fam and norm(r["title"]) == key:
                return r
        return self.add(fam, _title(section), [], False)


# ------------------------------------------------------------------ cache

class _Cache:
    """Per-tree memo: parsed notes by stat, git results by HEAD."""

    def __init__(self):
        self.notes = {}       # path -> (stat, meta)
        self.files = {}       # path -> (stat, parsed)
        self.git = {}         # name -> (key, value)


_CACHES = {}
_LOCK = threading.Lock()


def _cache(tree):
    with _LOCK:
        return _CACHES.setdefault(tree, _Cache())


def _note_meta(cache, path):
    st = stat_key(path)
    hit = cache.notes.get(path)
    if hit and hit[0] == st:
        return hit[1]
    text = read(path)
    meta = frontmatter(text[:20000])
    cache.notes[path] = (st, meta)
    return meta


def _parsed(cache, path, parser):
    st = stat_key(path)
    hit = cache.files.get(path)
    if hit and hit[0] == st:
        return hit[1]
    val = parser(read(path)) if st else []
    cache.files[path] = (st, val)
    return val


def _md_files(folder):
    try:
        return sorted(e.path for e in os.scandir(folder)
                      if e.is_file() and e.name.endswith(".md"))
    except OSError:
        return []


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


# -------------------------------------------------------------------- git

def git_head(tree):
    code, out, _ = sh(["git", "-C", tree, "rev-parse", "HEAD"], timeout=10)
    return out.strip() if code == 0 else None


def _git_memo(cache, name, key, fn):
    hit = cache.git.get(name)
    if hit and hit[0] == key:
        return hit[1]
    val = fn()
    cache.git[name] = (key, val)
    return val


def research_times(tree, folders):
    """Every data file -> (epoch, sha, subject) of the newest commit that
    researched it: the whole history in one `git log` (tens of ms on a few
    hundred commits), skipping maintenance sweeps (NOISE_SUBJECT, or more
    than NOISE_FILES files at once)."""
    code, out, _ = sh(["git", "-C", tree, "log", "--no-renames",
                       "--format=%x01%H%x00%ct%x00%s", "--name-only", "--",
                       *folders], timeout=60)
    times = {}
    if code != 0:
        return times
    for chunk in out.split("\x01")[1:]:
        head, _, names = chunk.partition("\n")
        sha, ct, subject = (head.split("\x00") + ["", "", ""])[:3]
        files = [f for f in names.splitlines() if f.strip()]
        if NOISE_SUBJECT.match(subject) or len(files) > NOISE_FILES:
            continue
        for f in files:
            if f not in times:
                times[f] = (int(ct or 0), sha[:7], subject)
    return times


def week_progress(tree, paths, now):
    """People and sources added in the last 7 days (still there), with the
    range of the new source ids."""
    since = str(int(now - WEEK_SECS))
    people, sources = paths["people"], paths["sources"]
    code, out, _ = sh(["git", "-C", tree, "log", f"--since={since}",
                       "--diff-filter=A", "--no-renames", "--name-only",
                       "--format=", "--", people, sources], timeout=30)
    new_people, new_sources = set(), set()
    if code == 0:
        for f in out.splitlines():
            d, name = os.path.split(f.strip())
            if not name.endswith(".md") or \
                    not os.path.exists(os.path.join(tree, f.strip())):
                continue
            if d == people:
                new_people.add(name[:-3])
            elif d == sources and SOURCE_ID.match(name[:-3]):
                new_sources.add(name[:-3])
    ids = sorted(new_sources, key=lambda s: int(s[1:]))
    return {"people": len(new_people), "sources": len(new_sources),
            "first_source": ids[0] if ids else None,
            "last_source": ids[-1] if ids else None}


def diary(tree, n=DIARY_LEN):
    code, out, _ = sh(["git", "-C", tree, "log", f"-n{n}",
                       "--format=%h%x00%ct%x00%s"], timeout=10)
    rows = []
    for line in out.splitlines() if code == 0 else []:
        sha, ct, subject = (line.split("\x00") + ["", "", ""])[:3]
        m = re.match(r"^(\w+)(\([^)]*\))?!?:\s*(.*)$", subject)
        rows.append({"sha": sha, "at": int(ct or 0), "subject": subject,
                     "kind": m.group(1) if m else None,
                     "text": m.group(3) if m else subject})
    return rows


# ------------------------------------------------------------- validation

def fingerprint(tree, paths=None):
    """A cheap signature of everything validation reads: the notes, the
    research files, families.yml and places.yml (count, newest mtime, total
    size). One scandir per folder: a few ms for ~800 notes."""
    paths = paths or load_config(tree)["paths"]
    n = newest = total = 0
    for role in ("people", "sources", "research"):
        try:
            entries = list(os.scandir(os.path.join(tree, paths[role])))
        except OSError:
            continue
        for e in entries:
            if not e.name.endswith(".md"):
                continue
            try:
                st = e.stat()
            except OSError:
                continue
            n += 1
            newest = max(newest, st.st_mtime_ns)
            total += st.st_size
    for name in ("families.yml", "places.yml"):
        st = stat_key(os.path.join(tree, name))
        if st:
            n += 1
            newest = max(newest, st[0])
            total += st[1]
    return f"{n}:{newest}:{total}"


def _validation_file(tree):
    h = hashlib.sha1(os.path.realpath(tree).encode()).hexdigest()[:12]
    return os.path.join(CACHE_DIR, f"validate-{h}.json")


def validation(tree, fp=None):
    """The cached validation result, with `stale` when the tree changed
    since it ran and `running` while a run is in flight. Never runs it."""
    res = None
    try:
        with open(_validation_file(tree)) as fh:
            res = json.load(fh)
    except (OSError, json.JSONDecodeError):
        pass
    fp = fp or fingerprint(tree)
    running = _RUNNING.get(os.path.realpath(tree), False)
    if not res:
        return {"state": "unknown", "stale": True, "running": running,
                "errors": None, "warnings": None, "lines": [], "at": None}
    res["stale"] = res.get("fingerprint") != fp
    res["running"] = running
    return res


def validate_cmd():
    """The read-only half of `make validate`. The make target runs
    `references` first, which rewrites revision.md and the generated sections
    of the notes (and `folders` creates folders): Arxiu must never write into
    the tree, so it runs only the check. ARXIU_VALIDATE_CMD overrides it
    (the tests use a stub)."""
    env = os.environ.get("ARXIU_VALIDATE_CMD")
    if env:
        return ["sh", "-c", env]
    return ["uv", "run", "--quiet", "--script", "scripts/validate.py"]


def parse_validation(code, out):
    errors = [ln[len("ERROR: "):] for ln in out.splitlines()
              if ln.startswith("ERROR: ")]
    warnings = [ln[len("warning: "):] for ln in out.splitlines()
                if ln.startswith("warning: ")]
    summary = next((ln for ln in reversed(out.splitlines()) if ln.strip()), "")
    state = "ok" if code == 0 and not errors else "error"
    if code != 0 and not errors:
        errors = [summary or f"exit {code}"]
    return {"state": state, "code": code, "errors": len(errors),
            "warnings": len(warnings), "summary": summary,
            "lines": [f"ERROR: {e}" for e in errors[:6]] +
                     [f"warning: {w}" for w in warnings[:max(0, 6 - len(errors))]]}


_RUNNING = {}


def run_validation(tree, fp=None):
    """Validate now (blocking) and cache the result. A lock file keeps two
    boards (the pane and a peek overlay) from validating at once."""
    real = os.path.realpath(tree)
    fp = fp or fingerprint(tree)
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _validation_file(tree)
    with open(path + ".lock", "w") as lk:
        try:
            fcntl.flock(lk.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return validation(tree, fp)
        _RUNNING[real] = True
        try:
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            started = time.time()
            code, out, err = sh(validate_cmd(), cwd=tree, timeout=600, env=env)
            res = parse_validation(code, out + ("\n" + err if code else ""))
            res.update({"fingerprint": fp, "at": int(time.time()),
                        "secs": round(time.time() - started, 1)})
            tmp = path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(res, fh)
            os.replace(tmp, path)
        finally:
            _RUNNING[real] = False
    return validation(tree, fp)


def validate_async(tree, force=False, on_done=None):
    """Kick a background validation if the tree changed since the last one
    (or `force`). -> True when one was started."""
    real = os.path.realpath(tree)
    if _RUNNING.get(real):
        return False
    fp = fingerprint(tree)
    if not force and not validation(tree, fp)["stale"]:
        return False
    _RUNNING[real] = True   # set before the thread starts: no double kick

    def work():
        try:
            _RUNNING[real] = False   # run_validation sets it under its lock
            run_validation(tree, fp)
        finally:
            _RUNNING[real] = False
            if on_done:
                on_done()
    threading.Thread(target=work, daemon=True).start()
    return True


# ------------------------------------------------------------------- load

def load(tree_path, now=None):
    """Read the tree. -> Tree:

    {
      "path", "loaded_at", "head", "paths": {people, sources, research, ...},
      "totals": {"people", "sources", "last_source", "pending",
                 "contradictions", "review", "discarded"},
      "families": [{key, label, title, default}],
      "branches": [{key, name, colour, family, group, founder}],
      "rows": [{id, title, family, branches, colours, colour, matched,
                "pending": {category: [item]},   # real pending work
                "searched": {category: [item]},  # "no repetir" logs
                "contradictions": {category: [item]},
                "review": [{id, title}], "discarded": [item],
                "counts": {docs, people, cut, photos, other, pending,
                           searched, contradictions, review},
                "last_research": epoch | None, "last_commit": {...} | None,
                "stale": bool}],
      "week": {people, sources, first_source, last_source},
      "diary": [{sha, at, subject, kind, text}],
      "validation": see validation(),
      "fingerprint": str,
    }

    An item is {title, text, category, kind, line, file}."""
    tree = os.path.abspath(os.path.expanduser(tree_path))
    now = now or time.time()
    cache = _cache(tree)
    cfg = load_config(tree)
    paths = cfg["paths"]
    pdir = os.path.join(tree, paths["people"])
    sdir = os.path.join(tree, paths["sources"])
    rdir = os.path.join(tree, paths["research"])

    # -- notes: who belongs to which branch, which sources they cite
    people = _md_files(pdir)
    sources = [p for p in _md_files(sdir)
               if SOURCE_ID.match(os.path.basename(p)[:-3])]
    other = cfg["other"]["key"]
    branch_files = {}
    for p in people:
        meta = _note_meta(cache, p)
        keys = [str(t)[len("rama/"):] for t in _as_list(meta.get("tags"))
                if str(t).startswith("rama/")] or [other]
        rel = os.path.relpath(p, tree)
        cited = [os.path.join(paths["sources"], wikilink(s) + ".md")
                 for s in _as_list(meta.get("sources"))]
        for k in keys:
            bucket = branch_files.setdefault(k, set())
            bucket.add(rel)
            bucket.update(cited)
    ids = [int(os.path.basename(p)[1:-3]) for p in sources]
    width = max((len(os.path.basename(p)) - 4 for p in sources), default=3)
    last_source = f"F{max(ids):0{width}d}" if ids else None

    # -- research files
    rows = Rows(cfg)
    files = {
        "pending": os.path.join(rdir, PENDING_FILE),
        "contradictions": os.path.join(rdir, CONTRADICTIONS_FILE),
        "discarded": os.path.join(rdir, DISCARDED_FILE),
    }
    totals = {"pending": 0, "contradictions": 0, "discarded": 0,
              "review": 0, "searched": 0}
    for what, path in files.items():
        for it in _parsed(cache, path, parse_research):
            row = rows.find(it["family"], it["section"])
            item = dict(it, file=os.path.basename(path),
                        kind=category_kind(it["category"])
                        if what == "pending" else what)
            cat = it["category"] or ""
            if what == "pending":
                bucket = "searched" if item["kind"] == "searched" else "pending"
                row[bucket].setdefault(cat, []).append(item)
                totals[bucket] += 1
            elif what == "contradictions":
                row["contradictions"].setdefault(cat, []).append(item)
                totals["contradictions"] += 1
            else:
                row["discarded"].append(item)
                totals["discarded"] += 1
    for it in _parsed(cache, os.path.join(rdir, REVIEW_FILE), parse_review):
        row = rows.find(it["family"], it["section"])
        row["review"].append(dict(it, file=REVIEW_FILE, kind="review",
                                  category=None, text=it["title"], line=None))
        totals["review"] += 1

    # -- git: last research per row, the week, the diary
    head = git_head(tree)
    times = _git_memo(cache, "times", head, lambda: research_times(
        tree, [paths["people"], paths["sources"]])) if head else {}
    day = int(now // 3600)   # the week window slides: refresh hourly
    week = _git_memo(cache, "week", (head, day),
                     lambda: week_progress(tree, paths, now)) if head else \
        {"people": 0, "sources": 0, "first_source": None, "last_source": None}
    log = _git_memo(cache, "diary", head, lambda: diary(tree)) if head else []

    for row in rows.rows:
        best = None
        for b in row["branches"]:
            for f in branch_files.get(b, ()):
                t = times.get(f)
                if t and (best is None or t[0] > best[0]):
                    best = t
        if best:
            row["last_research"] = best[0]
            row["last_commit"] = {"at": best[0], "sha": best[1],
                                  "subject": best[2]}
        row["stale"] = bool(best and now - best[0] > STALE_DAYS * 86400)
        c = {k: 0 for k in KIND_ORDER}
        for items in row["pending"].values():
            for it in items:
                c[it["kind"]] = c.get(it["kind"], 0) + 1
        c["pending"] = sum(len(v) for v in row["pending"].values())
        c["searched"] = sum(len(v) for v in row["searched"].values())
        c["contradictions"] = sum(len(v) for v in
                                  row["contradictions"].values())
        c["review"] = len(row["review"])
        c["discarded"] = len(row["discarded"])
        row["counts"] = c

    # Unmatched rows with nothing in them would only be noise.
    kept = [r for r in rows.rows if r["matched"] or
            any(r["counts"][k] for k in ("pending", "contradictions",
                                         "review", "searched"))]
    fam_order = {f["key"]: i for i, f in enumerate(cfg["families"])}
    kept.sort(key=lambda r: (fam_order.get(r["family"], len(fam_order)),
                             not r["matched"]))

    fp = fingerprint(tree, paths)
    branches = cfg["branches"] + [cfg["other"]]
    return {
        "path": tree, "loaded_at": now, "head": head, "paths": paths,
        "totals": {"people": len(people), "sources": len(sources),
                   "last_source": last_source, **totals},
        "families": cfg["families"], "branches": branches,
        "rows": kept, "week": week, "diary": log,
        "validation": validation(tree, fp), "fingerprint": fp,
    }


def changed_signature(tree, paths=None):
    """What the board polls to know the tree changed: the notes' fingerprint
    plus git's HEAD and index (a commit with no file change still moves
    the diary)."""
    sig = [fingerprint(tree, paths)]
    for name in ("HEAD", "index", "logs/HEAD"):
        st = stat_key(os.path.join(tree, ".git", name))
        sig.append(str(st))
    return "|".join(sig)


if __name__ == "__main__":
    # `arbre_data.py <tree> [--validate]`: the Tree as JSON, for debugging.
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target = args[0] if args else "~/src/arbre"
    t0 = time.time()
    data = load(target)
    t1 = time.time()
    load(target)
    t2 = time.time()
    if "--validate" in sys.argv:
        data["validation"] = run_validation(os.path.expanduser(target))
    if "--summary" in sys.argv:
        print(f"load {t1 - t0:.3f}s, reload {t2 - t1:.3f}s")
        print(json.dumps(data["totals"], ensure_ascii=False))
        print(json.dumps(data["week"], ensure_ascii=False))
        for r in data["rows"]:
            print(f"{r['family']!s:12} {r['title'][:40]:40} "
                  f"{json.dumps(r['counts'])} {r['last_research']}")
    else:
        json.dump(data, sys.stdout, ensure_ascii=False, indent=1, default=str)
