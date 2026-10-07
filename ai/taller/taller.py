#!/usr/bin/env python3
"""Taller collector: every project the user works on, with git state, the
agents running in it and the last conversation held there.

Stdlib only, read-only. board.py imports collect() and the actions; run it
directly (`taller.py [--json]`) to see what the board would get. See
CONTRACT.md for the shapes. The herdr-native actions (starting the tree's
agents, opening a project in herdr) are the only ones that change anything,
and only when the board asks.
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
               "dormant_days": 14},
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

# Contract states; aoe and herdr each speak their own dialect.
AOE_STATE = {"running": "working", "waiting": "waiting", "idle": "idle"}
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
    """config.toml next to this module (or $ARXIU_CONFIG), with defaults for
    every missing key and `~` expanded in every path."""
    path = path or os.environ.get("ARXIU_CONFIG") or os.path.join(HERE, "config.toml")
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
    never an exception."""
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, env=env, stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
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


def trashed(path):
    """aoe parks removed worktrees in .worktrees/.aoe-trash/<id>."""
    return "/.aoe-trash/" in path + "/"


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
    return os.environ.get("ARXIU_DRY_RUN") == "1"


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
    ones aoe trashed or that are gone from disk. None when git failed."""
    code, out, _ = git(root, "worktree", "list", "--porcelain")
    if code != 0:
        return None
    paths = []
    for block in out.split("\n\n"):
        fields = dict(line.partition(" ")[::2] for line in block.splitlines())
        p = norm(fields.get("worktree", ""))
        if (not p or p == root or "bare" in fields or "prunable" in fields
                or trashed(p) or not os.path.isdir(p)):
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


def aoe_agents():
    """Live aoe sessions as contract Agents. `aoe ps` only lists sessions with
    a running process: a live session missing there is stopped, or errored
    when `aoe session show` says so."""
    if not shutil.which("aoe"):
        return []
    with ThreadPoolExecutor(2) as ex:
        f_list = ex.submit(sh, ["aoe", "list", "--json"], timeout=AGENT_TIMEOUT)
        f_ps = ex.submit(sh, ["aoe", "ps", "--json"], timeout=AGENT_TIMEOUT)
        rows = _json(f_list.result()[1]) or []
        ps = {r.get("session"): r for r in _json(f_ps.result()[1]) or []
              if isinstance(r, dict)}
    rows = [r for r in rows if isinstance(r, dict) and r.get("state") == "live"
            and r.get("path") and not trashed(r["path"])]

    def state_of(r):
        if r["id"] in ps:
            return AOE_STATE.get(ps[r["id"]].get("state"), "unknown")
        code, out, _ = sh(["aoe", "session", "show", r["id"], "--json"],
                          timeout=AGENT_TIMEOUT)
        shown = _json(out) or {}
        return "error" if shown.get("status") == "error" else "stopped"

    with ThreadPoolExecutor(WORKERS) as ex:
        states = list(ex.map(state_of, rows))
    return [{"host": "aoe", "id": r["id"], "name": r.get("title") or r["id"],
             "tool": r.get("tool") or "", "path": norm(r["path"]), "state": s,
             "pane": None} for r, s in zip(rows, states)]


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
    """Every agent on both hosts. Cheap enough (~0.2s) for the board's fast
    agent refresh; pair with match_agents() to update projects in place."""
    with ThreadPoolExecutor(2) as ex:
        a, h = ex.submit(aoe_agents), ex.submit(herdr_agents)
        return a.result() + h.result()


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
            seeds.setdefault(a["path"], {"git": False, "name": a["name"]})
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
                                       "dirty": (wst or {}).get("dirty", 0)})
        if st is None:
            error = True
        else:
            p.update({k: st[k] for k in ("branch", "dirty", "ahead", "behind")})
            p["_upstream"] = st["upstream"]
    p["last_exchange"] = last_exchange([root] + [w["path"] for w in p["worktrees"]])
    stamps = [s for s in (commit, (p["last_exchange"] or {}).get("at")) if s]
    p["last_touch"] = max(stamps) if stamps else None
    p["_error"] = error
    return p


def finish(p, dormant_days, now=None):
    """Flags and dormancy, once agents are matched: a project with an agent
    that is not stopped is never dormant, however old its last commit."""
    now = now or time.time()
    awake = any(a["state"] not in ("stopped", "error") for a in p["agents"])
    p["dormant"] = not awake and (p["last_touch"] is None
                                  or now - p["last_touch"] > dormant_days * 86400)
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
    seeds = {r: s for r, s in seeds.items() if not hidden(r, hide)}
    with ThreadPoolExecutor(WORKERS) as ex:
        projects = list(ex.map(lambda kv: scan(*kv), seeds.items()))
    match_agents(projects, agents)
    for p in projects:
        finish(p, cfg["taller"]["dormant_days"])
    projects.sort(key=lambda p: (p["dormant"], -(p["last_touch"] or 0), p["name"]))
    return projects


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
    if agent["host"] == "herdr":
        return _run(["herdr", "agent", "prompt", _herdr_target(agent), text])
    return _run(["aoe", "send", agent["id"], text])


def focus(agent):
    """herdr can bring an agent forward; aoe cannot, the board attaches."""
    if agent["host"] != "herdr":
        return False, "aoe: " + shlex.join(attach_cmd(agent))
    return _run(["herdr", "agent", "focus", _herdr_target(agent)], timeout=10)


def attach_cmd(agent):
    if agent["host"] == "herdr":
        return ["herdr", "agent", "attach", _herdr_target(agent)]
    return ["aoe", "session", "attach", agent["id"]]


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


def find_workspace(label):
    code, data, _ = herdr(["workspace", "list"], timeout=AGENT_TIMEOUT)
    if code != 0:
        return None
    for w in ((data or {}).get("result") or {}).get("workspaces") or []:
        if w.get("label") == label:
            return w.get("workspace_id")
    return None


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
    pane = (((data or {}).get("result") or {}).get("root_pane") or {}) \
        .get("pane_id")
    args = [pane if a == "<pane>" else a for a in plan[1][1:]]
    status(f"engegant {name}: esperant claude…")
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
    """A new herdr workspace at the project running its last conversation
    (the same one an aoe session there holds, since it is the same folder).
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


def main(argv):
    if argv[:1] == ["--accept-trust"] and len(argv) == 4:
        # herdr/open.sh, when the orchestrator stops at claude's trust prompt.
        return 0 if accept_trust(*argv[1:]) else 1
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
