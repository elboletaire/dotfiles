#!/usr/bin/env python3
"""Taller collector: every project the user works on, with git state, the
agents running in it and the last conversation held there.

Stdlib only, read-only. board.py imports collect(), the sections and the
actions; run it directly (`taller.py [--json]`) to see what the board would
get (shapes: ai/arxiu/CONTRACT.md). The herdr launches (resuming a project's
conversation, a fresh agent, a new worktree) are the only things that change
anything, and only when the board asks; TALLER_DRY_RUN=1 makes them say what
they would run instead.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULTS = {
    "arbre": {"path": "~/src/arbre", "orchestrator_agent": "arbre",
              "research_agent": "investigacio",
              "research_skill": "genealogy-research", "agent_args": []},
    "taller": {"roots": ["~/src"], "extra": [], "hide": [],
               "dormant_days": 14, "agent_args": []},
    "ui": {"agents_secs": 3, "git_secs": 20},
}

# git on a Windows drive under WSL (/mnt/...) takes seconds per command; a
# hung or slow one must cost its project an "error" flag, never the collect.
GIT_TIMEOUT = float(os.environ.get("ARXIU_GIT_TIMEOUT", "8"))
AGENT_TIMEOUT = 5
WORKERS = 16
# Transcripts are read backwards in chunks, never whole: a Claude Code
# session easily weighs tens of MB.
TAIL_CHUNK = 64 * 1024
TAIL_MAX = 4 * 1024 * 1024
TEXT_MAX = 200

# herdr's agent states in the contract's words.
HERDR_STATE = {"working": "working", "blocked": "waiting", "done": "done",
               "idle": "idle"}

# User lines in a Claude Code transcript that are the harness talking, not
# the user: slash-command echoes, `!` shell output, task notifications.
NOISE_PREFIXES = ("<command-", "<local-command", "<bash-", "<task-notification",
                  "<user-prompt-submit-hook", "[Request interrupted")
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


# ---------------------------------------------------------------- config

def _expand(p):
    return os.path.normpath(os.path.expanduser(p)) if p else p


def load_config(path=None):
    """config.toml next to this module (or $TALLER_CONFIG, or $ARXIU_CONFIG
    from when it lived in Arxiu), with defaults for every missing key and `~`
    expanded in every path."""
    path = (path or os.environ.get("TALLER_CONFIG")
            or os.environ.get("ARXIU_CONFIG") or os.path.join(HERE, "config.toml"))
    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        raw = {}
    cfg = {}
    for section, defaults in DEFAULTS.items():
        cfg[section] = dict(defaults)
        cfg[section].update(raw.get(section) or {})
    for section, values in raw.items():
        cfg.setdefault(section, values)
    cfg["arbre"]["path"] = _expand(cfg["arbre"]["path"])
    t = cfg["taller"]
    t["roots"] = [_expand(p) for p in t["roots"]]
    t["extra"] = [_expand(p) for p in t["extra"]]
    # A hide entry with a slash (or ~) is a path; a bare word is a folder name.
    t["hide"] = [_expand(h) if "/" in h or h.startswith("~") else h
                 for h in t["hide"]]
    return cfg


# ---------------------------------------------------------------- utilities

def sh(args, cwd=None, timeout=GIT_TIMEOUT, env=None):
    """-> (code, stdout, stderr); a timeout or missing binary is code 124/127,
    never an exception. Only the end of stdout is trimmed: a line may start
    with meaningful spaces (`git status --porcelain`)."""
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, env=env, stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout.lstrip("\n").rstrip(), p.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s: {shlex.join(args)}"
    except OSError as e:
        return 127, "", str(e)


def git(path, *args, timeout=GIT_TIMEOUT):
    # GIT_OPTIONAL_LOCKS=0 keeps `git status` from refreshing the index: this
    # module only ever looks at the user's repos, never writes to them.
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", LC_ALL="C")
    return sh(["git", "-C", path] + list(args), timeout=timeout, env=env)


def norm(p):
    return os.path.normpath(os.path.expanduser(p)) if p else p


def within(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def short(text, n=TEXT_MAX):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def iso_epoch(ts):
    if isinstance(ts, (int, float)):
        return int(ts / 1000 if ts > 1e11 else ts)
    try:
        return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
    except (AttributeError, ValueError):
        return None


def dry_run():
    """TALLER_DRY_RUN=1 (or Arxiu's ARXIU_DRY_RUN=1): actions say what they
    would run instead of running it."""
    return "1" in (os.environ.get("TALLER_DRY_RUN"), os.environ.get("ARXIU_DRY_RUN"))


# ---------------------------------------------------------------- git

def parse_remote(url):
    """github/gitlab remotes as "github:owner/repo"; any other host as-is.

    Covers scp-like (git@host:owner/repo.git), ssh:// (with or without a
    port) and https:// forms."""
    if not url:
        return None
    m = (re.match(r"^[a-z+]+://(?:[^@/]+@)?([^/:]+)(?::\d+)?/(.+)$", url)
         or re.match(r"^(?:[^@/]+@)?([^/:]+):(.+)$", url))
    if not m:
        return url
    host, path = m.group(1).lower(), m.group(2).strip("/")
    path = re.sub(r"\.git$", "", path)
    for name in ("github", "gitlab"):
        if host == f"{name}.com":
            return f"{name}:{path}"
    return url


def git_root(path):
    """Main checkout of the repo `path` belongs to (worktrees resolve to their
    main repo), or None when it is not in a work tree."""
    code, out, _ = git(path, "rev-parse", "--path-format=absolute",
                       "--git-common-dir")
    if code != 0 or not out:
        return None
    out = norm(out)
    return os.path.dirname(out) if os.path.basename(out) == ".git" else None


def status(path):
    """`git status --porcelain=v2 --branch` -> {branch, upstream, ahead,
    behind, dirty} or None when git failed or timed out. One call gives all
    of it, which matters on /mnt drives."""
    code, out, _ = git(path, "status", "--porcelain=v2", "--branch")
    if code != 0:
        return None
    st = {"branch": None, "upstream": None, "ahead": None, "behind": None,
          "dirty": 0}
    for line in out.splitlines():
        if line.startswith("# branch.head "):
            head = line.split(" ", 2)[2]
            st["branch"] = None if head == "(detached)" else head
        elif line.startswith("# branch.upstream "):
            st["upstream"] = line.split(" ", 2)[2]
        elif line.startswith("# branch.ab "):
            a, b = line.split()[2:4]
            st["ahead"], st["behind"] = int(a), abs(int(b))
        elif line and not line.startswith("#"):
            st["dirty"] += 1
    return st


def worktree_paths(root):
    """Linked worktrees of `root` (not the main checkout itself), skipping the
    ones gone from disk. None when git failed."""
    code, out, _ = git(root, "worktree", "list", "--porcelain")
    if code != 0:
        return None
    paths = []
    for block in out.split("\n\n"):
        fields = dict(line.partition(" ")[::2] for line in block.splitlines())
        p = norm(fields.get("worktree", ""))
        if (not p or p == root or "bare" in fields or "prunable" in fields
                or not os.path.isdir(p)):
            continue
        paths.append(p)
    return paths


def last_commit(root):
    """Newest commit on any local branch, so work in a worktree counts."""
    code, out, _ = git(root, "for-each-ref", "--sort=-committerdate",
                       "--count=1", "--format=%(committerdate:unix)", "refs/heads")
    return int(out) if code == 0 and out.isdigit() else None


def remote_url(root):
    code, out, _ = git(root, "config", "--get-regexp", r"^remote\..*\.url$")
    if code != 0 or not out:
        return None
    urls = dict(line.split(" ", 1) for line in out.splitlines() if " " in line)
    return urls.get("remote.origin.url") or next(iter(urls.values()), None)


# ---------------------------------------------------------------- agents

def _json(text):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def herdr_agents():
    """herdr agents as contract Agents. The server is often not running
    (server_not_running, exit 1): that is simply no agents."""
    if not shutil.which("herdr"):
        return []
    code, out, err = sh(["herdr", "agent", "list"], timeout=AGENT_TIMEOUT)
    data = _json(out) or _json(err) or {}
    if code != 0 or not isinstance(data, dict):
        return []
    agents = []
    for a in (data.get("result") or {}).get("agents") or []:
        if not a.get("cwd"):
            continue
        agents.append({
            "host": "herdr", "id": a.get("workspace_id") or "",
            "name": a.get("name") or a.get("pane_id") or "",
            "tool": a.get("agent") or "", "path": norm(a["cwd"]),
            "state": HERDR_STATE.get(a.get("agent_status"), "unknown"),
            "pane": a.get("pane_id")})
    return agents


def list_agents():
    """Every herdr agent. Cheap enough (~0.2s) for the board's fast agent
    refresh; pair with match_agents() to update projects in place."""
    return herdr_agents()


def match_agents(projects, agents):
    """Set each project's `agents` from `agents`; returns the ones no project
    claims."""
    for p in projects:
        p["agents"] = []
    orphans = []
    for a in agents:
        p = find_project(projects, a["path"])
        (p["agents"] if p else orphans).append(a)
    return orphans


# ---------------------------------------------------------------- transcripts

def claude_dir(path):
    # Claude Code names the folder after the cwd with every non-alphanumeric
    # character (/, ., spaces) turned into "-".
    return os.path.join(os.path.expanduser("~/.claude/projects"),
                        re.sub(r"[^A-Za-z0-9-]", "-", path))


def pi_dir(path):
    # pi keeps dots and spaces: /home/u/.dotfiles -> --home-u-.dotfiles--
    return os.path.join(os.path.expanduser("~/.pi/agent/sessions"),
                        "--" + path.strip("/").replace("/", "-") + "--")


def transcripts(paths):
    """[(mtime, file, tool)] for every transcript of `paths`, newest first."""
    found = []
    for path in paths:
        for tool, d in (("claude", claude_dir(path)), ("pi", pi_dir(path))):
            try:
                entries = list(os.scandir(d))
            except OSError:
                continue
            for e in entries:
                if e.name.endswith(".jsonl") and e.is_file():
                    try:
                        found.append((e.stat().st_mtime, e.path, tool, path))
                    except OSError:
                        pass
    return sorted(found, reverse=True)


def tail_lines(path, max_bytes=None):
    """The file's lines newest first, reading backwards at most max_bytes."""
    max_bytes = max_bytes or TAIL_MAX
    with open(path, "rb") as fh:
        pos = fh.seek(0, os.SEEK_END)
        buf, read = b"", 0
        while pos > 0 and read < max_bytes:
            step = min(TAIL_CHUNK, pos)
            pos -= step
            fh.seek(pos)
            buf = fh.read(step) + buf
            read += step
            lines = buf.split(b"\n")
            buf = lines[0]  # may be the tail end of a longer line
            for line in reversed(lines[1:]):
                if line.strip():
                    yield line
        if pos == 0 and buf.strip():
            yield buf


def text_of(content):
    """Text blocks of a message's content (str or list of blocks); tool
    calls, tool results, thinking and images are not conversation."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(b.get("text") or "" for b in content
                     if isinstance(b, dict) and b.get("type") == "text")


def user_text(text):
    """The user's own words, or "" for harness noise."""
    text = REMINDER.sub("", text or "").strip()
    if not text or text.startswith(NOISE_PREFIXES):
        return ""
    return text


def message_of(d, tool):
    """-> (role, text, epoch) of a transcript line, or None when it is not a
    user/agent message worth showing."""
    if tool == "pi":
        if d.get("type") != "message":
            return None
        m = d.get("message") or {}
        role = m.get("role")
    else:
        if d.get("type") not in ("user", "assistant"):
            return None
        if d.get("isMeta") or d.get("isSidechain") or d.get("isCompactSummary"):
            return None
        m = d.get("message") or {}
        role = d["type"]
    if role not in ("user", "assistant"):
        return None
    text = text_of(m.get("content"))
    text = user_text(text) if role == "user" else text.strip()
    if not text:
        return None
    return role, text, iso_epoch(d.get("timestamp") or m.get("timestamp"))


def title_of(d):
    # Renamed sessions carry customTitle, auto-named ones aiTitle; old
    # transcripts had a "summary" line.
    for key in ("customTitle", "aiTitle"):
        if isinstance(d.get(key), str) and d[key].strip():
            return key, d[key]
    if d.get("type") == "summary" and isinstance(d.get("summary"), str):
        return "summary", d["summary"]
    return None


def read_exchange(path, tool):
    """Last user prompt, the agent's reply to it (empty while it is still
    working on it), and the session title, from the transcript's tail."""
    user = agent = None
    at = None
    titles = {}
    try:
        for raw in tail_lines(path):
            d = _json(raw.decode("utf-8", "replace"))
            if not isinstance(d, dict):
                continue
            t = title_of(d)
            if t:
                titles.setdefault(t[0], t[1])
            if user is None:
                msg = message_of(d, tool)
                if msg:
                    role, text, ts = msg
                    at = at or ts
                    if role == "assistant" and agent is None:
                        agent = text
                    elif role == "user":
                        user = text
            # pi has no titles; Claude Code repeats ai-title often enough
            # that the tail nearly always holds one.
            if user is not None and (tool == "pi" or titles):
                break
    except OSError:
        return None
    if user is None and agent is None:
        return None
    title = titles.get("customTitle") or titles.get("aiTitle") or titles.get("summary")
    if at is None:
        try:
            at = int(os.path.getmtime(path))
        except OSError:
            at = None
    return {"user": short(user or ""), "agent": short(agent or ""),
            "title": short(title, 80) if title else None, "at": at,
            "tool": tool}


def last_exchange(paths):
    """Newest conversation held in any of `paths` (a repo and its worktrees).
    Adds `tool` and `path` (where it ran) to the contract shape so
    resume_cmd() knows what to reopen and where."""
    for _, f, tool, where in transcripts(paths)[:3]:
        ex = read_exchange(f, tool)
        if ex:
            ex["path"] = where
            return ex
    return None


# ---------------------------------------------------------------- discovery

def hidden(path, hide):
    return any(path == h if "/" in h else os.path.basename(path) == h
               for h in hide)


def discover(cfg):
    """-> {root: seed} for the configured projects: repos under the roots,
    extra folders and the arbre. root is the main checkout; seeds carry what
    is known before git runs (git, and a name for non-repos)."""
    t = cfg["taller"]
    candidates = []
    for root in t["roots"]:
        try:
            entries = sorted(os.scandir(root), key=lambda e: e.name)
        except OSError:
            continue
        candidates += [e.path for e in entries
                       if e.is_dir() and os.path.exists(os.path.join(e.path, ".git"))]
    candidates += [p for p in t["extra"] + [cfg["arbre"]["path"]]
                   if p and os.path.isdir(p)]
    candidates = [norm(p) for p in candidates]

    def resolve(path):
        # A .git folder is a main checkout: no need to ask git, which is the
        # slow part on /mnt drives. A .git file is a worktree or submodule.
        if os.path.isdir(os.path.join(path, ".git")):
            return path
        return git_root(path)

    with ThreadPoolExecutor(WORKERS) as ex:
        roots = list(ex.map(resolve, candidates))
    seeds = {}
    for path, root in zip(candidates, roots):
        seeds.setdefault(root or path, {"git": bool(root)})
    return seeds


def add_strays(seeds, agents):
    """Agents running outside every known project bring their folder in: the
    repo it belongs to, or the bare folder named after the agent."""
    stray = [a for a in agents
             if not any(within(a["path"], r) for r in seeds)]
    with ThreadPoolExecutor(WORKERS) as ex:
        roots = list(ex.map(lambda a: git_root(a["path"]), stray))
    for a, root in zip(stray, roots):
        if root:
            seeds.setdefault(root, {"git": True})
        else:
            seeds.setdefault(a["path"], {"git": False})
    return seeds


def scan(root, seed):
    """Git state and last conversation of one project."""
    p = {"name": seed.get("name") or os.path.basename(root), "path": root,
         "git": seed["git"], "remote": None, "branch": None, "dirty": 0,
         "ahead": None, "behind": None, "worktrees": [], "last_touch": None,
         "agents": [], "last_exchange": None, "flags": [], "dormant": False}
    error = False
    commit = None
    if p["git"]:
        wts = worktree_paths(root)
        error = wts is None
        with ThreadPoolExecutor(4 + len(wts or [])) as ex:
            f_st = ex.submit(status, root)
            f_commit = ex.submit(last_commit, root)
            f_remote = ex.submit(remote_url, root)
            f_wts = [(w, ex.submit(status, w)) for w in wts or []]
            st = f_st.result()
            commit = f_commit.result()
            p["remote"] = parse_remote(f_remote.result())
            for w, f in f_wts:
                wst = f.result()
                error |= wst is None
                p["worktrees"].append({"path": w,
                                       "branch": (wst or {}).get("branch"),
                                       "dirty": (wst or {}).get("dirty", 0),
                                       "ahead": (wst or {}).get("ahead")})
        if st is None:
            error = True
        else:
            p.update({k: st[k] for k in ("branch", "dirty", "ahead", "behind")})
            p["_upstream"] = st["upstream"]
    # Each folder's own last conversation (folder() hands it to the actions)
    # and the newest of them, the project's.
    folders = [root] + [w["path"] for w in p["worktrees"]]
    with ThreadPoolExecutor(len(folders)) as ex:
        p["exchanges"] = dict(zip(folders, ex.map(
            lambda f: last_exchange([f]), folders)))
    held = [e for e in p["exchanges"].values() if e]
    p["last_exchange"] = max(held, key=lambda e: e.get("at") or 0,
                             default=None)
    stamps = [s for s in (commit, (p["last_exchange"] or {}).get("at")) if s]
    p["last_touch"] = max(stamps) if stamps else None
    p["_error"] = error
    return p


def folder(p, path=None):
    """The project's main checkout (no `path`, or its own) or one of its
    worktrees, shaped like a project so every action takes either: its own
    agents (the main checkout's are those in no worktree), last
    conversation, branch and changes. `repo` / `repo_name` are the
    project's path and name, `worktree` the worktree's entry (None for the
    main checkout)."""
    path = path or p["path"]
    w = next((x for x in p["worktrees"] if x["path"] == path), None)
    if w:
        agents = [a for a in p["agents"] if within(a["path"], path)]
    else:
        agents = [a for a in p["agents"] if not any(
            within(a["path"], x["path"]) for x in p["worktrees"])]
    exchanges = p.get("exchanges")
    f = dict(p, path=path, agents=agents, repo=p["path"],
             repo_name=p["name"], worktree=w,
             last_exchange=(exchanges.get(path) if exchanges is not None
                            else p.get("last_exchange")))
    if w:
        f.update(name=w["branch"] or os.path.basename(path),
                 branch=w["branch"], dirty=w["dirty"], ahead=w.get("ahead"),
                 behind=None, worktrees=[])
    return f


def live(agents):
    return any(a["state"] not in ("stopped", "error") for a in agents)


def is_dormant(p, dormant_days, now=None):
    """No live agent, and put to sleep (sleep_folders()) or untouched for
    `dormant_days`."""
    now = now or time.time()
    if live(p["agents"]):
        return False
    return (p.get("path") in p.get("slept", {}) or p["last_touch"] is None
            or now - p["last_touch"] > dormant_days * 86400)


def wake(p, dormant_days, now=None):
    """Dormancy again after match_agents() changed a project's agents
    (finish() can only run once: it consumes the scan's private keys)."""
    p["dormant"] = is_dormant(p, dormant_days, now)
    flags = [f for f in p["flags"] if f != "dormant"]
    if p["dormant"]:
        at = flags.index("error") if "error" in flags else len(flags)
        flags.insert(at, "dormant")
    p["flags"] = flags
    return p


def finish(p, dormant_days, now=None):
    """Flags and dormancy, once agents are matched: a project with an agent
    that is not stopped is never dormant, however old its last commit."""
    p["dormant"] = is_dormant(p, dormant_days, now)
    flags = []
    if not p["git"]:
        flags.append("no_git")
    else:
        if p["dirty"] or any(w["dirty"] for w in p["worktrees"]):
            flags.append("dirty")
        if p["ahead"]:
            flags.append("unpushed")
        if not p["remote"]:
            flags.append("no_remote")
        elif p["branch"] and not p.pop("_upstream", None):
            flags.append("no_upstream")
    if p["dormant"]:
        flags.append("dormant")
    if p.pop("_error", False):
        flags.append("error")
    p.pop("_upstream", None)
    p["flags"] = flags
    return p


def collect(cfg):
    """Every Taller project (the arbre one included), with agents matched."""
    with ThreadPoolExecutor(2) as ex:
        f_agents = ex.submit(list_agents)
        seeds = discover(cfg)
        agents = f_agents.result()
    seeds = add_strays(seeds, agents)
    hide = cfg["taller"]["hide"]
    # A root itself (the orchestrator runs in the first one) holds projects
    # rather than being one, unless it's a repo of its own.
    roots = {norm(r) for r in cfg["taller"]["roots"]}
    seeds = {r: s for r, s in seeds.items() if not hidden(r, hide)
             and (s["git"] or r not in roots)}
    with ThreadPoolExecutor(WORKERS) as ex:
        projects = list(ex.map(lambda kv: scan(*kv), seeds.items()))
    match_agents(projects, agents)
    apply_sleep(projects)
    for p in projects:
        finish(p, cfg["taller"]["dormant_days"])
    projects.sort(key=lambda p: (p["dormant"], -(p["last_touch"] or 0), p["name"]))
    return projects


# ---------------------------------------------------------------- sleep
#
# A project or one worktree put to sleep from the board (`z`): its herdr
# workspace closed and the folder listed with the time in the state file, so
# it shows as dormant whatever its age. Anything done there afterwards (a new
# commit or conversation, a live agent) wakes it and drops it from the file.

SLEEP_GRACE = 60   # secs a fresh entry is kept even if a collect sees agents


def sleep_file():
    state = os.environ.get("XDG_STATE_HOME") or os.path.expanduser(
        "~/.local/state")
    return os.environ.get("TALLER_SLEEP") or os.path.join(
        state, "taller", "sleep.json")


def load_sleep():
    """-> {folder: epoch it was put to sleep}."""
    try:
        with open(sleep_file()) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, (int, float))} \
        if isinstance(data, dict) else {}


def save_sleep(data):
    path = sleep_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
    os.replace(tmp, path)


def folder_touch(p, path):
    """When the project (its main checkout: every folder counts) or one of
    its worktrees was last touched."""
    if path == p["path"]:
        return p["last_touch"]
    return ((p.get("exchanges") or {}).get(path) or {}).get("at")


def apply_sleep(projects, now=None):
    """Each project's `slept` ({folder: epoch}) from the state file, for the
    folders still asleep; entries woken since (touched after, a live agent)
    or of folders gone are dropped from it."""
    now = now or time.time()
    data = load_sleep()
    keep = {}
    for p in projects:
        p["slept"] = {}
        for path in [p["path"]] + [w["path"] for w in p["worktrees"]]:
            at = data.get(path)
            if at is None:
                continue
            touch = folder_touch(p, path)
            agents = folder(p, path)["agents"] if path != p["path"] \
                else p["agents"]
            if now - at < SLEEP_GRACE or not (
                    live(agents) or (touch and touch > at)):
                p["slept"][path] = at
                keep[path] = at
    if keep != data:
        try:
            save_sleep(keep)
        except OSError:
            pass
    return projects


def asleep(p, path=None):
    """Is the project (no `path`, or its own) or that worktree of it put to
    sleep, with no live agent there now?"""
    path = path or p["path"]
    if path not in p.get("slept", {}):
        return False
    agents = p["agents"] if path == p["path"] else folder(p, path)["agents"]
    return not live(agents)


def sleepers(projects):
    """[(project, worktree)] of the worktrees asleep in projects that are
    not: they show among the dormant ones, on their own."""
    return [(p, w) for p in projects if not p["dormant"]
            for w in p["worktrees"] if asleep(p, w["path"])]


def awake_worktrees(p):
    """The worktrees listed under the project: all of them when it sleeps
    whole, else those not asleep on their own."""
    if p["dormant"]:
        return list(p["worktrees"])
    return [w for w in p["worktrees"] if not asleep(p, w["path"])]


def sleep_plan(f, whole, agents, spaces, own=None):
    """herdr steps that put a folder() to sleep: `whole` -- the main checkout
    with every worktree -- or that folder alone. Closes each workspace its
    agents run in, and the one labelled after it (the project's name, a
    worktree's branch title); a workspace that also holds agents from
    elsewhere, or that herdr keeps for another checkout (the repo's, where
    a worktree's agent may have landed), keeps living: only these agents'
    panes close. Never `own`,
    the board's workspace. `agents`: every herdr agent (herdr_agents()),
    `spaces`: herdr's workspace list."""
    if whole:
        roots = [f["repo"]]
        folders = [f["repo"]] + [w["path"] for w in f["worktrees"]]
        labels = [f["repo_name"]] + [branch_title(w["branch"])
                                     for w in f["worktrees"] if w["branch"]]
    else:
        roots = folders = [f["path"]]
        labels = ([branch_title(f["branch"])] if f["branch"] else []) \
            if f.get("worktree") else [f["name"]]

    def mine(a):
        if not any(within(a["path"], r) for r in roots):
            return False
        if whole or f.get("worktree"):
            return True
        # The main checkout alone: not its worktrees' agents.
        return not any(within(a["path"], w["path"]) for w in f["worktrees"])

    ours = [a for a in agents if a["host"] == "herdr" and mine(a)]
    ids = [a["id"] for a in ours if a["id"]]
    ids += [w["workspace_id"] for w in spaces if w.get("workspace_id")
            and (checkout_of(w) in folders if checkout_of(w)
                 else w.get("label") in labels)]
    checkout = {w.get("workspace_id"): checkout_of(w) for w in spaces}
    steps, seen = [], set()
    for wid in ids:
        if wid in seen or wid == own:
            continue
        seen.add(wid)
        others = [a for a in agents if a["id"] == wid and not mine(a)]
        if others or checkout.get(wid) not in (None, *folders):
            steps += [["herdr", "pane", "close", a["pane"]] for a in ours
                      if a["id"] == wid and a.get("pane")]
        else:
            steps.append(["herdr", "workspace", "close", wid])
    return steps


def put_to_sleep(f, whole, status=None):
    """Close the herdr side of a folder() (see sleep_plan) and list it in the
    state file. -> (ok, message)."""
    status = status or (lambda msg: None)
    plan = sleep_plan(f, whole, herdr_agents(), workspaces(),
                      os.environ.get("HERDR_WORKSPACE_ID"))
    path = f["repo"] if whole else f["path"]
    if dry_run():
        return True, "dry-run: " + (" ; ".join(shlex.join(a) for a in plan)
                                    or "res a tancar") + f" ; adorm {path}"
    for step in plan:
        status(f"herdr {step[1]} close {step[3]}…")
        code, data, raw = herdr(step[1:], timeout=20)
        if code != 0 and herdr_error(data) not in ("workspace_not_found",
                                                    "pane_not_found"):
            return False, f"herdr {step[1]} close ha fallat: {short(raw, 160)}"
    data = load_sleep()
    data[path] = int(time.time())
    save_sleep(data)
    closed = plural_of(len(plan), "sessió tancada", "sessions tancades")
    return True, f"{os.path.basename(path)} adormit ({closed})"


def wake_folder(p):
    """An agent started in the folder() `p`: it, and its repo when that was
    asleep whole, are awake again (without waiting for a collect to see the
    agent, which a short-lived one may never give it)."""
    data = load_sleep()
    woken = [x for x in {p["path"], p.get("repo")} if x and x in data]
    for x in woken:
        del data[x]
    if woken:
        save_sleep(data)


def wake_up(path):
    """Drop a folder from the state file. -> (ok, message)."""
    data = load_sleep()
    if data.pop(path, None) is None:
        return False, "no dormia"
    if dry_run():
        return True, f"dry-run: desperta {path}"
    save_sleep(data)
    return True, f"{os.path.basename(path)} despert"


# ---------------------------------------------------------------- remove
#
# A worktree removed from the board (`x`) or `taller.py remove`: its herdr
# side closed as sleep closes it, `git worktree remove` and its local branch
# deleted. Never a whole project. Uncommitted files or commits on no remote
# would be lost, so then it takes forcing.

def removal_risks(f):
    """What removing the worktree folder() `f` would lose, read live: ["N
    fitxers sense commit", "N commits que no són a cap remot"]."""
    risks = []
    st = status(f["path"])
    if st is None:
        return ["no s'ha pogut llegir el git status"]
    if st["dirty"]:
        risks.append(plural_of(st["dirty"], "fitxer sense commit",
                               "fitxers sense commit"))
    code, out, _ = git(f["path"], "rev-list", "--count", "HEAD", "--not",
                       "--remotes")
    if code != 0:
        risks.append("no s'ha pogut comprovar els commits sense pujar")
    elif int(out or 0):
        risks.append(plural_of(int(out), "commit que no és a cap remot",
                               "commits que no són a cap remot"))
    return risks


def remove_plan(f, force=False):
    """The git steps that remove the worktree folder() `f`: the worktree,
    then its local branch (none when detached)."""
    repo = f["repo"]
    steps = [["git", "-C", repo, "worktree", "remove"]
             + (["--force"] if force else []) + [f["path"]]]
    if f["branch"]:
        steps.append(["git", "-C", repo, "branch", "-D", f["branch"]])
    return steps


def remove_worktree(f, force=False, status=None):
    """Close the worktree's herdr side (see sleep_plan), remove it and delete
    its local branch. Refuses the main checkout, and a worktree with
    removal_risks() unless `force`. -> (ok, message)."""
    status = status or (lambda msg: None)
    if not f.get("worktree"):
        return False, "només es poden eliminar worktrees, no projectes"
    risks = removal_risks(f)
    if risks and not force:
        return False, ("té " + ", ".join(risks)
                       + "; cal forçar-ho per eliminar-lo")
    plan = sleep_plan(f, False, herdr_agents(), workspaces(),
                      os.environ.get("HERDR_WORKSPACE_ID")) \
        + remove_plan(f, force)
    if dry_run():
        return True, "dry-run: " + " ; ".join(shlex.join(a) for a in plan)
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    for step in plan:
        if step[0] == "herdr":
            status(f"herdr {step[1]} close {step[3]}…")
            code, data, raw = herdr(step[1:], timeout=20)
            if code != 0 and herdr_error(data) not in ("workspace_not_found",
                                                        "pane_not_found"):
                return False, (f"herdr {step[1]} close ha fallat: "
                               f"{short(raw, 160)}")
            continue
        what = " ".join(step[3:5])
        status(f"git {what}…")
        code, out, err = sh(step, timeout=60, env=env)
        if code != 0:
            return False, f"git {what} ha fallat: {short(err or out, 160)}"
    data = load_sleep()
    if data.pop(f["path"], None) is not None:
        save_sleep(data)
    gone = f"{os.path.basename(f['path'])} eliminat"
    return True, gone + (f" (i la branca {f['branch']})" if f["branch"]
                         else "")


def plural_of(n, one, many):
    return f"{n} {one if n == 1 else many}"


def find_project(projects, path):
    """The project whose root or one of its worktrees holds `path` (deepest
    match wins, so a worktree nested in its repo still maps right)."""
    path = norm(path)
    best, depth = None, -1
    for p in projects:
        for root in [p["path"]] + [w["path"] for w in p["worktrees"]]:
            if within(path, root) and len(root) > depth:
                best, depth = p, len(root)
    return best


# ---------------------------------------------------------------- actions

def _herdr_target(agent):
    return agent.get("name") or agent.get("pane") or agent["id"]


def _run(argv, timeout=60):
    if dry_run():
        return True, "dry-run: " + shlex.join(argv)
    code, out, err = sh(argv, timeout=timeout)
    return code == 0, (out if code == 0 else err or out)


def send(agent, text):
    return _run(["herdr", "agent", "prompt", _herdr_target(agent), text])


def focus(agent):
    return _run(["herdr", "agent", "focus", _herdr_target(agent)], timeout=10)


def attach_cmd(agent):
    return ["herdr", "agent", "attach", _herdr_target(agent)]


def resume_cmd(project):
    """Reopen the newest conversation where it ran (a worktree, maybe): both
    tools pick "the last one" per working directory, so `env -C` carries it."""
    ex = project.get("last_exchange") or {}
    tool = ex.get("tool") or "claude"
    where = ex.get("path") or project["path"]
    return ["env", "-C", where, tool, "--continue"]


# ---------------------------------------------------------------- herdr-native
#
# The tree's agents run in herdr only: a named orchestrator next to the board
# (herdr/open.sh) and a named research agent the board starts on demand, each
# with ARXIU_ROLE in its pane's environment (the librarian mod reads it).

ARXIU_LABEL = "Arxiu"          # the workspace herdr/open.sh builds
START_TIMEOUT_MS = 60000


def herdr(args, timeout=60):
    """-> (code, parsed JSON or None, raw text). herdr prints results on
    stdout and errors as JSON on stderr."""
    code, out, err = sh(["herdr"] + args, timeout=timeout)
    return code, _json(out) or _json(err), (err or out)


def herdr_error(data):
    return (((data or {}).get("error") or {}).get("code")) or ""


def herdr_agent(name):
    """herdr's own record of the agent called `name` (agent_status, pane_id,
    cwd...), or None when no agent has that name."""
    if not name or not shutil.which("herdr"):
        return None
    code, data, _ = herdr(["agent", "get", name], timeout=AGENT_TIMEOUT)
    if code != 0:
        return None
    return ((data or {}).get("result") or {}).get("agent")


def workspaces():
    """herdr's workspace list; [] when it can't be had."""
    if not shutil.which("herdr"):
        return []
    code, data, _ = herdr(["workspace", "list"], timeout=AGENT_TIMEOUT)
    if code != 0:
        return []
    return ((data or {}).get("result") or {}).get("workspaces") or []


def find_workspace(label):
    for w in workspaces():
        if w.get("label") == label:
            return w.get("workspace_id")
    return None


def checkout_of(w):
    """The folder a herdr workspace is a git checkout workspace of (the ones
    `herdr worktree open` makes: the worktree's, and the repo's parent one it
    adds when missing), or None."""
    return norm((w.get("worktree") or {}).get("checkout_path"))


def inside(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


def accept_trust(name, cwd, root):
    """Answer claude's "do you trust this folder?" for a folder inside `root`
    (the tree), and nothing else; any other dialog stays for the user.
    -> True once the agent is idle."""
    if not inside(cwd, root):
        return False
    _, screen, _ = sh(["herdr", "agent", "read", name, "--source", "visible"],
                      timeout=AGENT_TIMEOUT)
    if "trust this folder" not in screen:
        return False
    # The dialog defaults to "No, exit": move to "Yes" before confirming.
    herdr(["agent", "send-keys", name, "down", "enter"])
    code, _, _ = herdr(["agent", "wait", name, "--until", "idle",
                        "--timeout", str(START_TIMEOUT_MS)], timeout=90)
    return code == 0


def screen_tail(name, n=3):
    """The last non-empty lines on the agent's screen, to say why it is not
    ready."""
    _, screen, _ = sh(["herdr", "agent", "read", name, "--source", "visible"],
                      timeout=AGENT_TIMEOUT)
    lines = [ln.strip() for ln in screen.splitlines() if ln.strip()]
    return " · ".join(lines[-n:])


def start_plan(name, role, cwd, agent_args=(), workspace=None):
    """argv of each step start_agent() runs; "<pane>" stands for the pane the
    first step creates. In a new tab of `workspace` (the Arxiu one), or in a
    workspace of its own named after the agent when there is none."""
    env = f"ARXIU_ROLE={role}"
    if workspace:
        first = ["herdr", "tab", "create", "--workspace", workspace, "--cwd",
                 cwd, "--label", name, "--env", env, "--no-focus"]
    else:
        first = ["herdr", "workspace", "create", "--label", name, "--cwd", cwd,
                 "--env", env, "--no-focus"]
    start = ["herdr", "agent", "start", name, "--kind", "claude", "--pane",
             "<pane>", "--timeout", str(START_TIMEOUT_MS)]
    if agent_args:
        start += ["--"] + list(agent_args)
    return [first, start]


def start_agent(name, role, cwd, root, agent_args=(), status=None):
    """Start a claude agent named `name` in `cwd` (a new tab of the Arxiu
    workspace) with ARXIU_ROLE=`role`, and wait until it takes prompts.
    -> (ok, message). Never answers a dialog for the user except claude's
    folder-trust prompt for a folder inside `root`."""
    status = status or (lambda msg: None)
    plan = start_plan(name, role, cwd, agent_args, find_workspace(ARXIU_LABEL))
    if dry_run():
        return True, "dry-run: " + " ; ".join(shlex.join(a) for a in plan)
    status(f"engegant {name}: pestanya nova…")
    code, data, raw = herdr(plan[0][1:])
    if code != 0:
        return False, f"no s'ha pogut obrir la pestanya: {short(raw, 120)}"
    return start_in_pane(name, plan[1], pane_of(data), cwd, root, status)


def pane_of(data):
    """The pane a create/open call made: `.result.root_pane.pane_id`, wherever
    in the result it sits (workspace, tab and worktree calls differ)."""
    def walk(d):
        if isinstance(d, dict):
            rp = d.get("root_pane")
            if isinstance(rp, dict) and rp.get("pane_id"):
                return rp["pane_id"]
            for v in d.values():
                found = walk(v)
                if found:
                    return found
        return None
    return walk((data or {}).get("result"))


def start_in_pane(name, start, pane, cwd, root, status):
    """Run `start` (a `herdr agent start` argv, "<pane>" for the pane) in
    `pane` and wait until the agent takes prompts. Claude's folder-trust
    prompt is answered only for a folder inside `root`; any other dialog is
    left on screen and its last lines come back. -> (ok, message)."""
    if not pane:
        return False, f"herdr no ha tornat cap pane per a {name}"
    args = [pane if a == "<pane>" else a for a in start[1:]]
    status(f"engegant {name}: esperant l'agent…")
    # The pane's shell may still be starting; agent start needs its prompt.
    for _ in range(3):
        code, data, raw = herdr(args, timeout=START_TIMEOUT_MS / 1000 + 30)
        if code == 0 or herdr_error(data) == "agent_not_ready":
            break
        time.sleep(2)
    if code == 0:
        return True, f"{name} engegat"
    if herdr_error(data) == "agent_not_ready":
        if accept_trust(name, cwd, root):
            return True, f"{name} engegat (carpeta de confiança acceptada)"
        return False, (f"{name} s'ha aturat en engegar (pestanya {pane}): "
                       f"{short(screen_tail(name), 160)}")
    return False, f"no s'ha pogut engegar {name}: {short(raw, 160)}"


def research_status(cfg):
    """-> ("missing" | "blocked" | "ready", herdr's agent record or None)
    for `[arbre].research_agent`."""
    a = herdr_agent(cfg["arbre"].get("research_agent"))
    if not a:
        return "missing", None
    return ("blocked" if a.get("agent_status") == "blocked" else "ready"), a


def prompt_research(cfg, text, status=None):
    """Prompt the herdr agent `[arbre].research_agent` with `text`, starting
    it first (a new tab of the Arxiu workspace, in the tree, ARXIU_ROLE=
    research) when it is not running. Refuses when it is blocked on a
    question or an approval: that one is for the user. -> (ok, message)."""
    status = status or (lambda msg: None)
    a = cfg["arbre"]
    name, tree = a.get("research_agent"), a["path"]
    if not name:
        return False, "[arbre].research_agent buit a config.toml"
    state, _ = research_status(cfg)
    if state == "blocked":
        return False, (f"{name} espera una resposta teva (aprovació o "
                       "pregunta): no li envio res")
    prompt = ["herdr", "agent", "prompt", name, text]
    if state == "missing":
        ok, msg = start_agent(name, "research", tree, tree,
                              a.get("agent_args") or [], status)
        if dry_run():
            return ok, msg + " ; " + shlex.join(prompt)
        if not ok:
            return False, msg
    if dry_run():
        return True, "dry-run: " + shlex.join(prompt)
    status(f"enviant a {name}…")
    code, data, raw = herdr(prompt[1:])
    if code != 0 and herdr_error(data) == "agent_not_ready" \
            and accept_trust(name, tree, tree):
        code, data, raw = herdr(prompt[1:])
    if code != 0:
        if herdr_error(data) == "agent_not_ready":
            return False, f"{name} no està llest: {short(screen_tail(name), 160)}"
        return False, f"no s'ha pogut enviar a {name}: {short(raw, 160)}"
    return True, f"enviat a {name}"


def open_plan(project):
    """argv of each step open_in_herdr() runs ("<pane>": the new workspace's
    pane): a workspace at the project, named after it, running the last
    conversation again (or a new one when there is none)."""
    ex = project.get("last_exchange")
    cmd = resume_cmd(project) if ex else ["claude"]
    where = (ex or {}).get("path") or project["path"]
    label = project.get("name") or os.path.basename(project["path"])
    return [["herdr", "workspace", "create", "--label", label, "--cwd", where,
             "--focus"],
            ["herdr", "pane", "run", "<pane>", shlex.join(cmd)]]


def open_in_herdr(project):
    """A new herdr workspace at the project running its last conversation.
    -> (ok, message)."""
    plan = open_plan(project)
    if dry_run():
        return True, "dry-run: " + " ; ".join(shlex.join(a) for a in plan)
    code, data, raw = herdr(plan[0][1:])
    if code != 0:
        return False, f"no s'ha pogut crear el workspace: {short(raw, 120)}"
    pane = (((data or {}).get("result") or {}).get("root_pane") or {}) \
        .get("pane_id")
    code, _, raw = herdr(["pane", "run", pane, plan[1][-1]])
    if code != 0:
        return False, f"workspace creat, però l'ordre ha fallat: {short(raw, 120)}"
    return True, f"obert a herdr: {plan[0][4]}"


# ---------------------------------------------------------------- the board
#
# What board.py needs beyond collect(): where each project goes on screen,
# the expensive per-project details, and the herdr launches behind its keys
# (resume the project's conversation, a fresh agent, a new worktree). Every
# agent it starts gets a name, so herdr lists it by name and not by pane.

SECTIONS = ("need", "working", "parked", "dormant")
# An agent in one of these states wants you: blocked on a question or an
# approval, broken, or finished with nobody having looked yet (herdr's done).
NEED_STATES = {"waiting", "error", "done"}
AGENT_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
# Branch prefixes the worktree title drops (herdr-orchestrator.md).
TITLE_PREFIXES = ("feat", "fix", "chore", "docs", "refactor", "test", "ci",
                  "build", "perf", "style")
WORKTREES = ".worktrees"


def section(p):
    """need | working | parked | dormant: the first that applies."""
    states = {a["state"] for a in p["agents"]}
    if states & NEED_STATES:
        return "need"
    if "working" in states:
        return "working"
    if p["dormant"]:
        return "dormant"
    return "parked"


def sections(projects):
    """-> {section: [project]}, each newest first."""
    out = {s: [] for s in SECTIONS}
    for p in projects:
        out[section(p)].append(p)
    for rows in out.values():
        rows.sort(key=lambda p: (-(p["last_touch"] or 0), p["name"]))
    return out


def no_backup(p):
    """Work that exists only on this machine: no remote, or commits ahead of
    the upstream."""
    return p["git"] and ("no_remote" in p["flags"] or "unpushed" in p["flags"])


def agent_name(base, taken=()):
    """A herdr agent name ([a-z][a-z0-9_-]{0,31}) from a project or branch
    name, with -2, -3... when `taken` already has it."""
    s = re.sub(r"[^a-z0-9_-]+", "-", (base or "").lower()).strip("-_")
    if s and not s[0].isalpha():
        s = "p-" + s
    s = s[:32].rstrip("-_") or "agent"
    taken = set(taken)
    if s not in taken:
        return s
    for n in range(2, 1000):
        suffix = f"-{n}"
        cand = s[:32 - len(suffix)].rstrip("-_") + suffix
        if cand not in taken:
            return cand
    raise ValueError(f"no free agent name for {base!r}")


def herdr_names():
    """Names (or pane ids, for unnamed ones) of every herdr agent."""
    return {a["name"] for a in herdr_agents()}


def pick_agent(p):
    """The project's agent to go to: one that wants you, else a working
    one, else any."""
    rank = {"waiting": 0, "error": 0, "done": 1, "working": 2}
    return min(p["agents"], key=lambda a: rank.get(a["state"], 3), default=None)


def project_workspace(p):
    """herdr workspace of the project (or of a folder()): the one its herdr
    agents run in, else the one herdr keeps for that very checkout, else one
    labelled after it (a worktree's branch title, the project's name). Never
    the repo's for a worktree: that's the parent `herdr worktree open` puts
    the worktree's own workspace under. None when there is none."""
    for a in p["agents"]:
        if a["host"] == "herdr" and a.get("id"):
            return a["id"]
    spaces = workspaces()
    for w in spaces:
        if checkout_of(w) == p["path"]:
            return w.get("workspace_id")
    label = branch_title(p["branch"] or p["name"]) if p.get("worktree") \
        else p["name"]
    return next((w.get("workspace_id") for w in spaces
                 if w.get("label") == label and not checkout_of(w)), None)


def web_url(remote):
    """Browser URL of a parsed remote ("github:o/r"), or None."""
    if not remote:
        return None
    for host in ("github", "gitlab"):
        if remote.startswith(host + ":"):
            return f"https://{host}.com/{remote[len(host) + 1:]}"
    if remote.startswith(("https://", "http://")):
        return re.sub(r"\.git$", "", remote)
    return None


def browser_cmd(url, which=shutil.which):
    """argv opening `url` in the browser; under WSL the Windows one."""
    if which("wslview"):
        return ["wslview", url]
    if which("explorer.exe"):
        return ["explorer.exe", url]
    for opener in ("xdg-open", "open"):
        if which(opener):
            return [opener, url]
    return None


# .. details: only for the selected project, cached by the board

def git_dir(path):
    """<path>/.git, or where a worktree's .git file points ("gitdir: ...")."""
    dot = os.path.join(path, ".git")
    if os.path.isfile(dot):
        try:
            with open(dot) as fh:
                head, _, where = fh.read().strip().partition(" ")
            if head == "gitdir:":
                return os.path.normpath(os.path.join(path, where))
        except OSError:
            pass
    return dot


def details_key(p):
    """Changes whenever the details could: the repo's HEAD, index and reflog
    stamps (a stat each, no git) plus what collect() saw."""
    gitdir = git_dir(p["path"])
    stamps = []
    for f in ("HEAD", "index", "logs/HEAD"):
        try:
            stamps.append(os.stat(os.path.join(gitdir, f)).st_mtime_ns)
        except OSError:
            stamps.append(None)
    return (p["path"], p["branch"], p["dirty"], p["ahead"], tuple(stamps))


def details(path, n_commits=5, n_changes=8):
    """The last commits and the changed files of a checkout:
    {commits: [{sha, at, subject}], changes: [porcelain line], changes_total,
    error}."""
    with ThreadPoolExecutor(2) as ex:
        f_log = ex.submit(git, path, "log", f"-{n_commits}",
                          "--format=%h%x1f%ct%x1f%s")
        f_st = ex.submit(git, path, "status", "--porcelain")
        (lc, lout, lerr), (sc, sout, serr) = f_log.result(), f_st.result()
    commits = []
    for line in lout.splitlines() if lc == 0 else []:
        sha, at, subject = (line.split("\x1f") + ["", ""])[:3]
        commits.append({"sha": sha, "at": int(at) if at.isdigit() else None,
                        "subject": subject})
    changes = [ln for ln in sout.splitlines() if ln.strip()] if sc == 0 else []
    error = None
    if sc != 0:
        error = short(serr or "git status ha fallat", 120)
    elif lc != 0 and "does not have any commits" not in lerr:
        error = short(lerr or "git log ha fallat", 120)
    return {"commits": commits, "changes": changes[:n_changes],
            "changes_total": len(changes), "error": error}


# .. launches

def launch_kind(tool):
    return tool if tool in ("claude", "pi") else "claude"


def start_argv(name, kind, args=()):
    argv = ["herdr", "agent", "start", name, "--kind", kind, "--pane",
            "<pane>", "--timeout", str(START_TIMEOUT_MS)]
    return argv + (["--"] + list(args) if args else [])


def _focus(focus):
    return "--focus" if focus else "--no-focus"


def _opener(p, name, cwd, workspace, focus=True):
    """First step of a launch: a tab of the project's workspace, or a
    workspace of its own labelled with the project's name -- a worktree's
    (a folder()) opened with `herdr worktree open`, grouped under the
    repo's in herdr's sidebar and titled after its branch."""
    if workspace:
        return ["herdr", "tab", "create", "--workspace", workspace, "--cwd",
                cwd, "--label", name, _focus(focus)]
    if p.get("worktree"):
        return ["herdr", "worktree", "open", "--cwd", p["repo"], "--path",
                p["path"], "--label", branch_title(p["branch"] or p["name"]),
                _focus(focus)]
    return ["herdr", "workspace", "create", "--label", p["name"], "--cwd",
            cwd, _focus(focus)]


def resume_plan(p, name, workspace=None, agent_args=(), focus=True):
    """Steps to run the project's last conversation again in herdr as agent
    `name` (`--continue` where it ran: a worktree, maybe), or a new claude
    when there was none. "<pane>": the pane the first step makes."""
    ex = p.get("last_exchange")
    where = (ex or {}).get("path") or p["path"]
    if not os.path.isdir(where):
        where = p["path"]
    kind = launch_kind((ex or {}).get("tool"))
    args = (list(agent_args) if kind == "claude" else []) + \
        (["--continue"] if ex else [])
    return [_opener(p, name, where, workspace, focus),
            start_argv(name, kind, args)]


def fresh_plan(p, name, workspace=None, agent_args=(), focus=True):
    """Steps for a new claude conversation in the project."""
    return [_opener(p, name, p["path"], workspace, focus),
            start_argv(name, "claude", agent_args)]


def branch_title(branch):
    """feat/convert-images -> "Convert Images"."""
    head, sep, rest = branch.partition("/")
    if sep and head in TITLE_PREFIXES:
        branch = rest
    words = [w for w in re.split(r"[-_/.\s]+", branch) if w]
    return " ".join(w[:1].upper() + w[1:] for w in words) or branch


def worktree_dir(repo, branch):
    return os.path.join(repo, WORKTREES, branch.replace("/", "-"))


def check_branch(p, branch):
    """Why `branch` cannot be a new worktree of `p`, or None when it can."""
    if not p["git"]:
        return f"{p['name']} no és un repositori git"
    if not branch:
        return "cal un nom de branca"
    code, _, _ = sh(["git", "check-ref-format", "--branch", branch])
    if code != 0 or branch.startswith("-"):
        return f"«{branch}» no és un nom de branca vàlid"
    code, _, _ = git(p["path"], "show-ref", "--verify", "--quiet",
                     f"refs/heads/{branch}")
    if code == 0:
        return f"la branca {branch} ja existeix"
    if os.path.exists(worktree_dir(p["path"], branch)):
        return f"{worktree_dir(p['path'], branch)} ja existeix"
    return None


def worktree_plan(p, branch, name, agent_args=(), focus=True):
    """herdr-orchestrator.md's "create", without touching the main checkout:
    fetch, a new branch off the current one in <repo>/.worktrees/<branch>,
    opened in herdr as a workspace (grouped under the repo's) titled after
    the branch, and claude in it named `name`."""
    repo = p["path"]
    wt = worktree_dir(repo, branch)
    steps = []
    if p.get("remote"):
        steps.append(["git", "-C", repo, "fetch", "--quiet"])
    steps.append(["git", "-C", repo, "worktree", "add", "-b", branch, wt,
                  p.get("branch") or "HEAD"])
    steps.append(["herdr", "worktree", "open", "--cwd", repo, "--path", wt,
                  "--label", branch_title(branch), _focus(focus)])
    steps.append(start_argv(name, "claude", agent_args))
    return steps


def launch(plan, name, cwd, root, status=None):
    """Run a plan from the *_plan() functions: git steps, then the herdr step
    that makes the pane, then the agent start in it. A failed fetch is only
    a warning (offline still works); anything else stops. -> (ok, msg)."""
    status = status or (lambda msg: None)
    if dry_run():
        return True, "dry-run: " + " ; ".join(shlex.join(a) for a in plan)
    pane, notes = None, []
    for step in plan[:-1]:
        if step[0] == "git":
            what = " ".join(step[3:5])
            status(f"{name}: git {what}…")
            env = dict(os.environ, GIT_TERMINAL_PROMPT="0", LC_ALL="C")
            code, out, err = sh(step, timeout=120, env=env)
            if code != 0:
                if step[3] == "fetch":
                    notes.append("fetch ha fallat")
                    continue
                return False, f"git {what} ha fallat: {short(err or out, 160)}"
        else:
            status(f"{name}: herdr {step[1]} {step[2]}…")
            code, data, raw = herdr(step[1:])
            if code != 0:
                return False, (f"herdr {step[1]} {step[2]} ha fallat: "
                               f"{short(raw, 160)}")
            pane = pane_of(data) or pane
    ok, msg = start_in_pane(name, plan[-1], pane, cwd, root, status)
    return ok, msg + (f" ({', '.join(notes)})" if notes and ok else "")


def resume_project(p, agent_args=(), status=None, focus=True):
    """The project's last conversation as a named herdr agent, in its
    workspace (a new one labelled after it when there is none).
    -> (ok, message, agent name)."""
    name = agent_name(p["name"], herdr_names())
    plan = resume_plan(p, name, project_workspace(p), agent_args, focus)
    first = plan[0]
    where = first[first.index("--path" if "--path" in first else "--cwd") + 1]
    ok, msg = launch(plan, name, where, p["path"], status)
    if ok and not dry_run():
        wake_folder(p)
    return ok, msg, name


def fresh_agent(p, agent_args=(), status=None, focus=True):
    """A new claude conversation in the project, named after it.
    -> (ok, message, agent name)."""
    name = agent_name(p["name"], herdr_names())
    plan = fresh_plan(p, name, project_workspace(p), agent_args, focus)
    ok, msg = launch(plan, name, p["path"], p["path"], status)
    if ok and not dry_run():
        wake_folder(p)
    return ok, msg, name


def new_worktree(p, branch, agent_args=(), status=None, focus=True):
    """A new worktree on a new branch with its own herdr workspace and
    claude. -> (ok, message, agent name)."""
    err = check_branch(p, branch)
    if err:
        return False, err, None
    name = agent_name(branch, herdr_names())
    plan = worktree_plan(p, branch, name, agent_args, focus)
    ok, msg = launch(plan, name, worktree_dir(p["path"], branch), p["path"],
                     status)
    return ok, msg, name


# ---------------------------------------------------------------- CLI

def age(epoch, now=None):
    if not epoch:
        return "-"
    s = int((now or time.time()) - epoch)
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if s >= n:
            return f"{s // n}{unit}"
    return f"{s}s"


def table(projects):
    rows = []
    for p in projects:
        ab = "" if p["ahead"] is None else f"+{p['ahead']}/-{p['behind']}"
        agents = " ".join(f"{a['tool']}:{a['state']}" for a in p["agents"])
        rows.append([p["name"], p["branch"] or "-", str(p["dirty"]), ab,
                     str(len(p["worktrees"])), age(p["last_touch"]),
                     p["remote"] or "-", agents, ",".join(p["flags"])])
    head = ["name", "branch", "dirty", "ahead", "wt", "touch", "remote",
            "agents", "flags"]
    widths = [min(30, max(len(r[i]) for r in rows + [head])) for i in range(len(head))]
    out = []
    for r in [head] + rows:
        out.append("  ".join(c[:w].ljust(w) for c, w in zip(r, widths)).rstrip())
    return "\n".join(out)


class NotFound(Exception):
    pass


def find_folder(projects, name, worktree=None):
    """The folder() a CLI argument names: a project by name (any case) or
    path, then one of its worktrees by branch, folder name or path."""
    want = name.lower()
    p = (next((x for x in projects if x["name"] == name), None)
         or next((x for x in projects if x["name"].lower() == want), None)
         or next((x for x in projects if x["path"] == norm(name)), None))
    if not p:
        raise NotFound(f"cap projecte «{name}». N'hi ha: "
                       + ", ".join(sorted(x["name"] for x in projects)))
    if not worktree:
        return folder(p)
    for w in p["worktrees"]:
        if worktree in (w["branch"], os.path.basename(w["path"]), w["path"]):
            return folder(p, w["path"])
    raise NotFound(f"{p['name']} no té cap worktree «{worktree}». Té: "
                   + (", ".join(w["branch"] or w["path"] for w in p["worktrees"])
                      or "cap"))


def sessions(projects):
    """One line per herdr session: agent, state, where (<project> or
    <project> ⑂ <branch>), tool."""
    labels = {"working": "treballant", "waiting": "t'espera", "done":
              "acabat sense mirar", "idle": "inactiu", "error": "error"}
    out = []
    for p in projects:
        for f in [folder(p)] + [folder(p, w["path"]) for w in p["worktrees"]]:
            where = (f"{p['name']} ⑂ {f['branch'] or f['name']}"
                     if f["worktree"] else p["name"])
            for a in f["agents"]:
                out.append(f"{a['name']}\t{labels.get(a['state'], a['state'])}"
                           f"\t{where}\t{a['tool']}")
    return "\n".join(out) or "cap sessió oberta a herdr"


def _cli_folder(p):
    """A folder() as JSON for `show`: its details read now."""
    out = {k: v for k, v in p.items() if not k.startswith("_")
           and k not in ("exchanges",)}
    if p["git"]:
        out["details"] = details(p["path"])
    return out


def cli(argv):
    """Subcommands for the Taller orchestrator (the taller:orchestrator
    skill): the board's actions, taking the focus from nobody."""
    import argparse
    ap = argparse.ArgumentParser(prog="taller.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd in ("show", "resume", "new", "remove"):
        sp = sub.add_parser(cmd)
        sp.add_argument("project")
        sp.add_argument("--worktree", required=cmd == "remove")
        if cmd == "new":
            sp.add_argument("--prompt")
        if cmd == "remove":
            sp.add_argument("--force", action="store_true")
    sp = sub.add_parser("worktree")
    sp.add_argument("project")
    sp.add_argument("branch")
    sp.add_argument("--prompt")
    sp = sub.add_parser("prompt")
    sp.add_argument("agent")
    sp.add_argument("text")
    sub.add_parser("sessions")
    a = ap.parse_args(argv)

    if a.cmd == "prompt":
        ok, msg = send({"host": "herdr", "name": a.agent, "id": ""}, a.text)
        print(msg if ok else f"no s'ha pogut: {msg}")
        return 0 if ok else 1
    cfg = load_config()
    projects = collect(cfg)
    if a.cmd == "sessions":
        print(sessions(projects))
        return 0
    try:
        f = find_folder(projects, a.project, getattr(a, "worktree", None))
    except NotFound as e:
        print(e)
        return 1
    if a.cmd == "show":
        json.dump(_cli_folder(f), sys.stdout, indent=2,
                  ensure_ascii=False)
        print()
        return 0
    if a.cmd == "remove":
        ok, msg = remove_worktree(f, a.force)
        print(msg if ok else f"no s'ha pogut: {msg}")
        return 0 if ok else 1
    args = list(cfg["taller"].get("agent_args") or [])
    if a.cmd == "resume":
        ok, msg, name = resume_project(f, args, focus=False)
    elif a.cmd == "new":
        ok, msg, name = fresh_agent(f, args, focus=False)
    else:
        ok, msg, name = new_worktree(f, a.branch, args, focus=False)
    print(msg if ok else f"no s'ha pogut: {msg}")
    if ok and getattr(a, "prompt", None):
        ok, msg = send({"host": "herdr", "name": name, "id": ""}, a.prompt)
        print(msg if ok else f"no s'ha pogut enviar: {msg}")
    return 0 if ok else 1


def main(argv):
    if argv[:1] == ["--accept-trust"] and len(argv) == 4:
        # herdr/open.sh, when the orchestrator stops at claude's trust prompt.
        return 0 if accept_trust(*argv[1:]) else 1
    if argv and not argv[0].startswith("-"):
        return cli(argv)
    cfg = load_config()
    t0 = time.time()
    projects = collect(cfg)
    if "--json" in argv:
        json.dump(projects, sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        print(table(projects))
        print(f"\n{len(projects)} projects in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
