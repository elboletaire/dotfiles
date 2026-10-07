#!/usr/bin/env python3
"""PR Autopilot reconciler.

Reads GitHub + herdr, diffs against a small state file, prints a compact table of
actionable rows. Deterministic; no model involved. See SKILL.md for how the
rows are acted on.
"""
import copy
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

HOME_REPOS = os.environ.get("HOME_REPOS", "").split()
ISSUE_ORGS = os.environ.get("ISSUE_ORGS", "").split()
CLONE_ROOTS = os.environ.get("CLONE_ROOTS", "").split()
CLONE_PREFER = [os.path.expanduser(p).rstrip("/")
                for p in os.environ.get("CLONE_PREFER", "").split()]
MAX_ACTIVE = int(os.environ.get("MAX_ACTIVE", "6"))
# Local HH:MM from which ticks remind the user to close work, not start it.
WIND_DOWN_AT = os.environ.get("WIND_DOWN_AT", "").strip()
MAX_REVIEW_ROUNDS = int(os.environ.get("MAX_REVIEW_ROUNDS", "3"))
AGENT_STALL_MIN = int(os.environ.get("AGENT_STALL_MIN", "35"))
# A review-only PR whose author pushed after our review but never re-requested
# it is flagged PUSHED once its head has been unchanged this long.
RE_REVIEW_QUIET_HOURS = float(os.environ.get("RE_REVIEW_QUIET_HOURS", "4"))

# Model per spawn, keyed by the template that creates the session. Pinned onto
# the claude command line rather than inherited, so the orchestrator's own
# model never decides what the workers run on.
MODEL_FOR = {
    "work": os.environ.get("MODEL_WORK", "opus"),
    "investigate": os.environ.get("MODEL_INVESTIGATE", "opus"),
    "review-fix": os.environ.get("MODEL_REVIEW_FIX", "sonnet"),
    "review-comment": os.environ.get("MODEL_REVIEW_COMMENT", "opus"),
}
MODEL_COLD_REVIEW = os.environ.get("MODEL_COLD_REVIEW", "opus")
STALE_HOURS = int(os.environ.get("STALE_HOURS", "48"))
ISSUE_MAX_AGE_DAYS = int(os.environ.get("ISSUE_MAX_AGE_DAYS", "120"))
STATE_FILE = os.environ.get(
    "STATE_FILE", os.path.expanduser("~/.local/state/pr-autopilot/state.json"))
# Both live next to the state file and exist for the dashboard: the event log
# is appended by every mutating command, the snapshot is the last read-only
# scan rendered as JSON.
EVENTS_FILE = os.path.join(os.path.dirname(STATE_FILE), "events.jsonl")
SNAPSHOT_FILE = os.path.join(os.path.dirname(STATE_FILE), "snapshot.json")
EVENTS_MAX_BYTES = 512 * 1024
EVENTS_KEEP = 1000
# Address of the orchestrator ("herdr:<agent>"). Empty means "whichever agent
# last ran a scan", recorded by the scan itself.
AUTOPILOT_ORCH = os.environ.get("AUTOPILOT_ORCH", "")
# herdr agent name the orchestrator runs under.
ORCH_AGENT = "autopilot"

AGENT_MARKER = "controlled by elboletaire"
FEEDBACK_IGNORE = set(
    (os.environ.get("FEEDBACK_IGNORE_AUTHORS") or "github-actions").split())

EMPTY = {"paused": False, "registry": {}, "declined": [], "handled_merges": [],
         "items": {}, "me": None}


# ---------------------------------------------------------------- utilities

def sh(args, cwd=None, timeout=60):
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        return 1, "", str(e)


def gh_json(args, cwd=None, default=None):
    code, out, _ = sh(["gh"] + args, cwd=cwd)
    if code != 0 or not out:
        return default
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return default


def load():
    try:
        with open(STATE_FILE) as fh:
            s = json.load(fh)
    except (OSError, json.JSONDecodeError):
        s = {}
    out = dict(EMPTY)
    out.update(s)
    for k, v in EMPTY.items():
        out.setdefault(k, v)
    return out


def save(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = f"{STATE_FILE}.tmp.{os.getpid()}"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
    os.replace(tmp, STATE_FILE)


@contextmanager
def locked():
    """Exclusive lock for the whole read-modify-write of the state file.

    save() is atomic on its own, but every mutating command does
    load() -> mutate -> save(); without this, two concurrent writers both read
    the same counter and the second silently discards the first's increment.
    The counter that gets lost is review_rounds -- the cap itself. Readers
    (scan/status) do not take the lock.
    """
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    fh = open(STATE_FILE + ".lock", "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def log_event(kind, key_=None, **fields):
    """Append one line to the event log the dashboard tails.

    Called from mutating commands, which all hold the state lock, so the
    trim below cannot race another writer. A failed write never fails the
    command: the log is a convenience, the state file is the truth.
    """
    ev = {"at": int(time.time()), "kind": kind}
    if key_:
        ev["key"] = key_
    ev.update({k: v for k, v in fields.items() if v is not None})
    try:
        os.makedirs(os.path.dirname(EVENTS_FILE), exist_ok=True)
        with open(EVENTS_FILE, "a") as fh:
            fh.write(json.dumps(ev, sort_keys=True) + "\n")
        if os.path.getsize(EVENTS_FILE) > EVENTS_MAX_BYTES:
            with open(EVENTS_FILE) as fh:
                keep = fh.readlines()[-EVENTS_KEEP:]
            tmp = f"{EVENTS_FILE}.tmp.{os.getpid()}"
            with open(tmp, "w") as fh:
                fh.writelines(keep)
            os.replace(tmp, EVENTS_FILE)
    except OSError:
        pass


def whoami(state):
    if not state.get("me"):
        state["me"] = gh_json(["api", "user", "--jq", ".login"], default=None) \
            or sh(["gh", "api", "user", "--jq", ".login"])[1]
    return state["me"]


# --------------------------------------------------------------- agent hosts
#
# Every item runs in herdr. Its `session` is the herdr workspace id (`w12`),
# which survives a herdr restart where pane ids and agent names may not.

HERDR_WS = re.compile(r"^w[0-9A-Za-z]{1,8}$")
# herdr agent states in the vocabulary the scan logic speaks.
HERDR_STATE = {"working": "running", "blocked": "waiting", "idle": "idle",
               "done": "idle", "unknown": "unknown"}


def herdr(args, timeout=60):
    """-> (code, parsed JSON or None, raw text). herdr prints results on
    stdout and errors as JSON on stderr."""
    code, out, err = sh(["herdr"] + args, timeout=timeout)
    data = None
    for text in (out, err):
        try:
            data = json.loads(text)
            break
        except (json.JSONDecodeError, TypeError):
            continue
    return code, data, (err or out)


def herdr_error(data):
    return ((data or {}).get("error") or {}).get("code") or ""


def herdr_sessions():
    """herdr worktree workspaces as [{id,title,path,worktree:{branch,
    main_repo_path}}]; None when herdr could not be asked."""
    if not shutil.which("herdr"):
        return []
    code, data, _ = herdr(["workspace", "list"])
    if code != 0 or not data:
        return None
    by_repo = {}
    for w in (data.get("result") or {}).get("workspaces", []):
        wt = w.get("worktree") or {}
        if wt.get("is_linked_worktree") and wt.get("repo_root"):
            by_repo.setdefault(wt["repo_root"], []).append((w, wt))
    out = []
    for repo, rows in by_repo.items():
        code, d, _ = herdr(["worktree", "list", "--cwd", repo])
        listed = ((d or {}).get("result") or {}).get("worktrees", []) \
            if code == 0 else []
        branch = {x.get("open_workspace_id"): x.get("branch") for x in listed}
        for w, wt in rows:
            out.append({"id": w["workspace_id"], "title": w.get("label"),
                        "path": wt.get("checkout_path"), "backend": "herdr",
                        "worktree": {"branch": branch.get(w["workspace_id"]),
                                     "main_repo_path": repo}})
    return out


def herdr_agents():
    if not shutil.which("herdr"):
        return []
    code, data, _ = herdr(["agent", "list"])
    if code != 0 or not data:
        return []
    return (data.get("result") or {}).get("agents", [])


def herdr_live():
    """workspace id -> {state, agent, pane}. Autopilot runs one agent per
    workspace; when the user opened more, the one autopilot named wins."""
    out = {}
    for a in herdr_agents():
        ws = a.get("workspace_id")
        if not ws:
            continue
        mine = (a.get("name") or "").startswith("ap-")
        if ws in out and not mine:
            continue
        out[ws] = {"session": ws, "agent": a.get("name"),
                   "pane": a.get("pane_id"), "backend": "herdr",
                   "state": HERDR_STATE.get(a.get("agent_status"), "unknown")}
    return out


def all_sessions():
    """-> (sessions, herdr answered). When herdr did not answer, no item may
    be taken for removed: that would untrack live work every time the herdr
    server hiccups."""
    rows = herdr_sessions()
    return (rows or []), rows is not None


def all_live():
    return herdr_live()


def session_age(s, live):
    """Seconds since the session did anything: the last commit on the
    worktree's branch stands in."""
    code, out, _ = sh(["git", "log", "-1", "--format=%ct"], cwd=s.get("path"))
    if code == 0 and out.isdigit():
        return int(time.time()) - int(out)
    return 0


def herdr_target(it):
    """The live agent for a herdr item: its name when that still resolves,
    else whichever agent now occupies its workspace (by pane id)."""
    name = it.get("agent")
    if name and herdr(["agent", "get", name])[0] == 0:
        return name
    for a in herdr_agents():
        if a.get("workspace_id") == it.get("session"):
            return a.get("name") or a.get("pane_id")
    return None


def address_of(it):
    t = herdr_target(it)
    return f"herdr:{t}" if t else None


def send_to(address, text):
    """-> (ok, error code or message). Addresses are "herdr:<agent or pane>";
    a bare one is taken as the agent itself."""
    target = address.split(":", 1)[1] if address.startswith("herdr:") else address
    code, data, raw = herdr(["agent", "prompt", target, text], timeout=120)
    return (True, "") if code == 0 else (False, herdr_error(data) or raw)


def current_orch():
    """Address of the agent running this command, if it is one.

    In herdr the orchestrator needs a name others can address; an unnamed
    agent is named ORCH_AGENT on the spot."""
    pane = os.environ.get("HERDR_PANE_ID")
    if pane and shutil.which("herdr"):
        code, data, _ = herdr(["agent", "get", pane])
        a = ((data or {}).get("result") or {}).get("agent") or {}
        if code == 0 and a:
            name = a.get("name")
            if not name and herdr(["agent", "rename", pane, ORCH_AGENT])[0] == 0:
                name = ORCH_AGENT
            return f"herdr:{name or pane}"
    return None


def sid(session_id):
    return (session_id or "")[:8]


# ------------------------------------------------------------------ registry

def resolve_repo(path):
    info = gh_json(["repo", "view", "--json", "nameWithOwner,defaultBranchRef"],
                   cwd=path)
    if not info:
        return None
    slug = info.get("nameWithOwner")
    default = (info.get("defaultBranchRef") or {}).get("name") or "main"
    code, _, _ = sh(["git", "rev-parse", "--verify", "--quiet",
                     "refs/remotes/origin/develop"], cwd=path)
    base = "develop" if code == 0 else default
    return slug, base


NEW_IGNORED = []


def clone_dirs():
    """Git clones directly under each CLONE_ROOTS folder. Only a real `.git`
    directory counts: a worktree's `.git` is a file, so worktrees are skipped."""
    out = []
    for root in CLONE_ROOTS:
        root = os.path.expanduser(root)
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for n in names:
            p = os.path.join(root, n)
            if os.path.isdir(os.path.join(p, ".git")):
                out.append(p)
    return out


def build_registry(old, refresh=False, old_ignored=None):
    """slug -> {path, base}, derived from the clones on disk.

    Folders that do not resolve on GitHub (no remote, no access) are ignored
    and memoised so they are not re-probed every tick; `refresh` clears the
    memo. When two clones resolve to the same slug, a CLONE_PREFER path wins,
    else the first in alphabetical order.
    """
    reg = {} if refresh else dict(old)
    known = {v["path"] for v in reg.values()}
    memo = set() if refresh else set(old_ignored or [])
    todo = [p for p in clone_dirs() if p not in known and p not in memo]
    if todo:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for p, res in zip(todo, ex.map(resolve_repo, todo)):
                if not res:
                    NEW_IGNORED.append(p)
                    continue
                slug, base = res
                cur = reg.get(slug)
                if cur and cur["path"].rstrip("/") in CLONE_PREFER:
                    continue
                if cur and p.rstrip("/") not in CLONE_PREFER \
                        and cur["path"] < p:
                    continue
                reg[slug] = {"path": p, "base": base}
    return reg


# ----------------------------------------------------------------- discovery

PR_FIELDS = ("number,headRefName,headRefOid,state,isDraft,baseRefName,"
             "author,assignees,url,title,mergedAt")


def home_prs(slug):
    rows = gh_json(["pr", "list", "-R", slug, "--state", "open", "--limit", "50",
                    "--json", PR_FIELDS], default=[]) or []
    for r in rows:
        r["repo"] = slug
    return rows


def search_prs(query_flag, me):
    rows = gh_json(["search", "prs", query_flag, "--state", "open",
                    "--archived=false", "--limit",
                    "60", "--json",
                    "number,repository,title,author,assignees,url"],
                   default=[]) or []
    for r in rows:
        r["repo"] = (r.get("repository") or {}).get("nameWithOwner")
    return [r for r in rows if r.get("repo")]


def cutoff():
    import datetime
    d = datetime.date.today() - datetime.timedelta(days=ISSUE_MAX_AGE_DAYS)
    return d.isoformat()


def home_issues(slug, me):
    out = {}
    fresh = f"updated:>={cutoff()}"
    for args in (["--assignee", me, "--search", fresh],
                 ["--author", me, "--search", f"no:assignee {fresh}"]):
        rows = gh_json(["issue", "list", "-R", slug, "--state", "open",
                        "--limit", "50", "--json", "number,title,url"] + args,
                       default=[]) or []
        for r in rows:
            r["repo"] = slug
            out[r["number"]] = r
    return list(out.values())


def org_issues(me):
    rows = []
    for org in ISSUE_ORGS:
        got = gh_json(["search", "issues", "--assignee", me, "--state", "open",
                       "--owner", org, "--archived=false",
                       "--updated", f">={cutoff()}",
                       "--limit", "60", "--json",
                       "number,repository,title,url"], default=[]) or []
        for r in got:
            r["repo"] = (r.get("repository") or {}).get("nameWithOwner")
        rows += [r for r in got if r.get("repo")]
    return rows


def open_heads(slug):
    rows = gh_json(["pr", "list", "-R", slug, "--state", "open", "--limit",
                    "100", "--json", "headRefName"], default=[]) or []
    return [r["headRefName"] for r in rows]


def pr_detail(slug, number):
    d = gh_json(["pr", "view", str(number), "-R", slug, "--json",
                 "number,state,mergedAt,headRefOid,headRefName,baseRefName,"
                 "statusCheckRollup,isDraft,url,title,reviews,comments,"
                 "reviewRequests"],
                default=None)
    return d


def pr_review_comments(detail):
    """REST review comments for the PR in `detail` (gh pr view has none)."""
    url = (detail or {}).get("url") or ""
    m = re.search(r"github\.com/([^/]+/[^/]+)/pull/(\d+)", url)
    if not m:
        return []
    return gh_json(["api", f"repos/{m.group(1)}/pulls/{m.group(2)}/comments"
                    "?per_page=100"], default=[]) or []


def new_feedback(detail, since):
    """Reviews/comments newer than `since` that autopilot did not itself write.

    Author alone cannot identify the agent: it posts with the user's token, so
    its comments are authored by the user. The signature line the prompt
    library mandates is the discriminator."""
    out = []
    since = since or ""
    review_comments = None
    for r in (detail or {}).get("reviews") or []:
        when = r.get("submittedAt") or ""
        body = r.get("body") or ""
        author = (r.get("author") or {}).get("login", "?")
        # FEEDBACK_IGNORE has to cover reviews as well as comments: a CI bot
        # that reviews on every push would otherwise reset the review-round
        # counter forever and defeat MAX_REVIEW_ROUNDS.
        if when <= since or AGENT_MARKER in body or author in FEEDBACK_IGNORE:
            continue
        state_ = r.get("state") or ""
        if state_ not in ("CHANGES_REQUESTED", "COMMENTED", "APPROVED"):
            continue
        # A reply on a review thread arrives as an empty-body COMMENTED
        # review; the agent's signature is then only in the inline comment.
        # Without this check the agent's own reply re-triggers FEEDBACK every
        # tick, forever. Review comments are fetched once per PR, lazily.
        if not body.strip() and state_ == "COMMENTED":
            if review_comments is None:
                review_comments = pr_review_comments(detail)
            mine = [c for c in review_comments
                    if (c.get("created_at") or "") == when]
            if mine and all(AGENT_MARKER in (c.get("body") or "")
                            for c in mine):
                continue
        # A bare approval is "ship it", not feedback. Only an approval that
        # carries an actual note is worth waking the agent for.
        if state_ == "APPROVED" and not body.strip():
            continue
        out.append((author, when, r.get("state", "REVIEW"), body[:60]))
    for c in (detail or {}).get("comments") or []:
        when = c.get("createdAt") or ""
        body = c.get("body") or ""
        author = (c.get("author") or {}).get("login", "?")
        if when <= since or AGENT_MARKER in body or author in FEEDBACK_IGNORE:
            continue
        out.append((author, when, "comment", body[:60]))
    return sorted(out, key=lambda x: x[1])


def checks_of(detail):
    roll = (detail or {}).get("statusCheckRollup") or []
    if not roll:
        return "none"
    states = set()
    for c in roll:
        states.add(c.get("conclusion") or c.get("state") or "")
    if {"FAILURE", "TIMED_OUT", "CANCELLED", "ERROR", "ACTION_REQUIRED"} & states:
        return "fail"
    if {"PENDING", "IN_PROGRESS", "QUEUED", ""} & states:
        return "pending"
    return "pass"


# ---------------------------------------------------------------------- mode

def mode_for(pr_row, me):
    """'fix' for PRs you own, 'comment' for everyone else's.

    You own a PR when you opened it, or when it is assigned to you (as
    assignee, not reviewer) -- the explicit signal to adopt someone else's
    PR. On any other PR the useful output is a review they can act on, not
    commits pushed over their work. The repo does not change this.
    """
    author = (pr_row.get("author") or {}).get("login")
    assignees = [a.get("login") for a in (pr_row.get("assignees") or [])]
    return "fix" if author == me or me in assignees else "comment"


# ---------------------------------------------------------------------- main

SEP = {"pr": "#", "issue": "!", "investigate": "?"}


def key(slug, num, kind="pr"):
    return f"{slug}{SEP[kind]}{num}"


def scan(state, refresh=False, info=None):
    """Reconcile and return the table rows.

    `info`, when given, is filled with what the rows only summarise -- full
    titles, URLs and the tracked PRs' details -- for the dashboard snapshot.
    """
    me = whoami(state)
    sessions, answered = all_sessions()
    live = all_live()
    reg = build_registry(state.get("registry", {}), refresh,
                         state.get("ignored_paths", []))
    state["registry"] = reg
    state["ignored_paths"] = sorted(
        (set() if refresh else set(state.get("ignored_paths", [])))
        | set(NEW_IGNORED))

    path_to_slug = {v["path"].rstrip("/"): k for k, v in reg.items()}
    session_paths = {s["id"]: s.get("path") for s in sessions}

    # branch -> session, per repo path
    by_branch = {}
    for s in sessions:
        wt = s.get("worktree")
        if not wt:
            continue
        mp = (wt.get("main_repo_path") or "").rstrip("/")
        br = wt.get("branch")
        if mp and br:
            by_branch.setdefault((mp, br), s)

    declined = set(state.get("declined", []))
    handled = set(state.get("handled_merges", []))
    items = state.get("items", {})

    # ---- gather (parallel)
    jobs = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        for slug in HOME_REPOS:
            jobs[("prs", slug)] = ex.submit(home_prs, slug)
            if slug in reg:
                jobs[("iss", slug)] = ex.submit(home_issues, slug, me)
        jobs[("rr", "*")] = ex.submit(search_prs, f"--review-requested={me}", me)
        jobs[("as", "*")] = ex.submit(search_prs, f"--assignee={me}", me)
        jobs[("oi", "*")] = ex.submit(org_issues, me)
        tracked = {k: ex.submit(pr_detail, k.split("#")[0], v["pr"])
                   for k, v in items.items() if v.get("pr")}
        results = {k: f.result() for k, f in jobs.items()}
        details = {k: f.result() for k, f in tracked.items()}

    meta = {}
    if info is not None:
        info["details"] = details
        info["meta"] = meta

    rows = []
    active = 0

    # ---- tracked items
    for k, it in list(items.items()):
        slug = k.split("#")[0].split("!")[0].split("?")[0]
        d = details.get(k)
        sess = it.get("session")
        smeta = f"session={sid(sess)}"

        # The user closed the session's workspace by hand. Stop tracking it
        # so it frees its slot; a merged PR still goes through MERGED below
        # so its cleanup and fan-out happen. Only when herdr answered:
        # silence is not removal.
        if sess and sess not in session_paths \
                and answered and not (
                it.get("pr") and d and d.get("state") == "MERGED"):
            items.pop(k)
            rows.append(("GONE", k, f"{smeta} removed outside autopilot "
                                    "-> untracked, slot freed"))
            continue

        if it.get("pr") and d and d.get("state") == "MERGED":
            if k not in handled:
                rows.append(("MERGED", k, f"branch={it.get('branch')} {smeta}"))
            continue

        if it.get("pr") and d and d.get("state") == "CLOSED":
            rows.append(("CLOSED", k, f"branch={it.get('branch')} {smeta} "
                                      "-> not merged; session left alone"))
            continue

        if it.get("phase") == "booting":
            active += 1
            # A comment item that was already reviewed gets a follow-up review
            # scoped to the author's new commits, not a second full review.
            if it["mode"] == "comment" and it.get("reviewed_sha"):
                tmpl = f"template=re-review PREV={it['reviewed_sha']}"
            elif it["mode"] == "comment":
                tmpl = "template=review-comment"
            else:
                tmpl = "template=review-fix"
            rows.append(("BOOTING", k, f"mode={it['mode']} {smeta} {tmpl}"))
            continue

        if not it.get("pr"):
            # issue-driven work, PR not opened yet
            repo_path = reg.get(slug, {}).get("path", "").rstrip("/")
            # The agent may have switched its worktree to another branch and
            # opened the PR from there; the branch recorded at spawn/track time
            # would then never match. Follow the worktree's live branch.
            wt_path = session_paths.get(sess)
            if wt_path and os.path.isdir(wt_path):
                code, cur, _ = sh(["git", "branch", "--show-current"],
                                  cwd=wt_path)
                if code == 0 and cur and cur != it.get("branch"):
                    it["branch"] = cur
            found = None
            for pr in results.get(("prs", slug), []) or []:
                if pr["headRefName"] == it.get("branch"):
                    found = pr
                    break
            if found is None and repo_path:
                # --state all: a PR opened and merged between two ticks must
                # still be found, or its session lingers as WORKING forever.
                got = gh_json(["pr", "list", "-R", slug, "--state", "all",
                               "--head", it.get("branch", ""), "--json",
                               PR_FIELDS], default=[]) or []
                found = got[0] if got else None
            if found:
                it["pr"] = found["number"]
                nk = key(slug, found["number"])
                # The agent was handed the issue key in its prompt and will
                # keep using it for claim-round/heartbeat; remember it so those
                # calls still resolve after the re-key.
                it.setdefault("prev_keys", []).append(k)
                items[nk] = items.pop(k)
                if found.get("state") == "MERGED":
                    if nk not in handled:
                        rows.append(("MERGED", nk, f"branch={it.get('branch')} {smeta}"))
                    continue
                if found.get("state") == "CLOSED":
                    rows.append(("CLOSED", nk, f"branch={it.get('branch')} {smeta} "
                                               "-> not merged; session left alone"))
                    continue
                active += 1
                # An agent-driven item runs its own review loop; a REVIEW row
                # here would tell the orchestrator to reboot it mid-flight.
                if it.get("driver") == "agent":
                    rows.append(("WORKING", nk,
                                 f"branch={it.get('branch')} {smeta} driver=agent "
                                 f"rounds={int(it.get('review_rounds', 0))}/"
                                 f"{MAX_REVIEW_ROUNDS} quiet=0m"))
                else:
                    rows.append(("REVIEW", nk,
                                 f"mode={it['mode']} {smeta} head={found['headRefOid'][:7]} "
                                 f"reviewed=none"))
                continue
            st = live.get(sess, {}).get("state", "?")
            age = live.get(sess, {}).get("age_secs")
            if age is None:
                age = int(time.time()) - int(it.get("added") or time.time())
            active += 1
            rows.append(("WORKING", k, f"branch={it.get('branch')} {smeta} "
                                       f"state={st} age={age // 60}m"))
            continue

        # tracked open PR
        head = (d or {}).get("headRefOid", "")
        if not d:
            rows.append(("UNKNOWN", k, f"{smeta} -> gh pr view failed"))
            continue
        active += 1
        rv = it.get("reviewed_sha") or ""

        # A human (or review bot) leaving a review outranks everything below:
        # it is explicit instruction, where REVIEW is only autopilot's own
        # second guess. Items tracked before feedback_seen existed get it
        # stamped now, so pre-existing reviews do not stampede on first scan.
        if it["mode"] == "fix":
            if "feedback_seen" not in it:
                it["feedback_seen"] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                    time.gmtime())
            fb = new_feedback(d, it.get("feedback_seen"))
            if fb:
                who, when, kind, snippet = fb[-1]
                # since= is the newest feedback's timestamp: it is what
                # mark-feedback must be given to advance the watermark past
                # it. Printing the old watermark here made the documented
                # flow a no-op.
                rows.append(("FEEDBACK", k,
                             f"mode=fix {smeta} since={when} "
                             f"{who} {kind} \"{snippet}\""))
                continue

        rounds = int(it.get("review_rounds", 0))

        # An agent-driven item runs its own loop: it waits on its own CI,
        # claims its own rounds and reports when it is done. The orchestrator
        # never sends it a review prompt -- it only watches for the agent
        # going quiet, because a dead agent and a working one look identical
        # from here.
        #
        # Its state comes from what the agent says, not from the counter:
        # claim-round counts a round when it starts, so rounds == MAX while
        # the last round is still running. Only a `capped` report or a
        # refused claim means it stopped, and only a `ready` report for this
        # head means it is done (the agent never calls mark-reviewed). A
        # report is current until the agent shows a later sign of life.
        if it.get("driver") == "agent":
            rep = it.get("last_report") or {}
            if rep.get("at", 0) < int(it.get("last_seen") or 0) or \
                    live.get(sess, {}).get("state") == "running":
                rep = {}
            if rep.get("state") == "capped" or it.get("capped_at"):
                rows.append(("CAPPED", k,
                             f"mode={it['mode']} {smeta} head={head[:7]} "
                             f"rounds={rounds}/{MAX_REVIEW_ROUNDS} "
                             "-> agent stopped at the cap; you decide"))
                continue
            if rep.get("state") == "ready" and rep.get("sha") \
                    and head.startswith(rep["sha"]):
                rv = head   # falls through to READY below
            if not rv or not head.startswith(rv):
                quiet = (int(time.time()) - int(it.get("last_seen")
                         or it.get("added") or 0)) // 60
                # Mid-turn (a long review subagent, say) sends no heartbeat
                # but is plainly alive.
                if quiet >= AGENT_STALL_MIN and \
                        live.get(sess, {}).get("state") != "running":
                    rows.append(("STALLED", k,
                                 f"mode={it['mode']} {smeta} head={head[:7]} "
                                 f"rounds={rounds}/{MAX_REVIEW_ROUNDS} "
                                 f"quiet={quiet}m -> agent not reporting"))
                else:
                    rows.append(("WORKING", k,
                                 f"branch={it.get('branch')} {smeta} "
                                 f"driver=agent rounds={rounds}/"
                                 f"{MAX_REVIEW_ROUNDS} quiet={quiet}m"))
                continue

        # Once the user's account has approved someone else's PR, that PR is
        # finished for us: a later push by the author must not trigger another
        # review, which would post "Request changes" over the approval.
        if it["mode"] == "comment":
            mine = [r for r in (d.get("reviews") or [])
                    if (r.get("author") or {}).get("login") == me
                    and r.get("state") in ("APPROVED", "CHANGES_REQUESTED")]
            if mine and mine[-1].get("state") == "APPROVED":
                if live.get(sess, {}).get("state") != "running":
                    active -= 1
                rows.append(("DONE", k, f"mode=comment {smeta} approved by you "
                                        "-> no further reviews"))
                continue

        # Follow-up reviews of someone else's PR run when the author asks for
        # one (re-requests the review), not on every push. A push that is never
        # followed by a re-request is flagged PUSHED once the branch has been
        # quiet for RE_REVIEW_QUIET_HOURS, so the PR cannot sit in limbo.
        if it["mode"] == "comment" and rv:
            running = live.get(sess, {}).get("state") == "running"
            requested = me in [(r.get("login") or r.get("name"))
                               for r in (d.get("reviewRequests") or [])]
            if running:
                rows.append(("WORKING", k, f"mode=comment {smeta} "
                                           "reviewing, not posted yet"))
                continue
            active -= 1
            # `mine` non-empty: our review is posted, so a pending request for
            # us is a re-request, not the original one. Once per head, so a
            # request left pending (e.g. we posted nothing) cannot loop.
            if requested and mine and it.get("rerequest_head") != head:
                if rounds >= MAX_REVIEW_ROUNDS:
                    rows.append(("CAPPED", k,
                                 f"mode=comment {smeta} head={head[:7]} "
                                 f"rounds={rounds}/{MAX_REVIEW_ROUNDS} "
                                 "re-requested -> autopilot stopped; you decide"))
                    continue
                it["rerequest_head"] = head
                active += 1
                rows.append(("REVIEW", k, f"mode=comment {smeta} "
                                          f"head={head[:7]} reviewed={rv[:7]} "
                                          f"round={rounds + 1}/{MAX_REVIEW_ROUNDS} "
                                          "re-requested"))
                continue
            if not head.startswith(rv):
                if it.get("head_seen") != head:
                    it["head_seen"] = head
                    it["head_seen_at"] = int(time.time())
                quiet_h = (int(time.time()) - int(it["head_seen_at"])) / 3600
                if it.get("push_acked") == head:
                    rows.append(("DONE", k, f"mode=comment {smeta} new commits "
                                            "acknowledged -> waiting on re-request"))
                elif quiet_h >= RE_REVIEW_QUIET_HOURS:
                    rows.append(("PUSHED", k, f"mode=comment {smeta} head={head[:7]} "
                                              f"reviewed={rv[:7]} quiet={quiet_h:.0f}h "
                                              "-> pushed since our review, never re-requested"))
                else:
                    rows.append(("DONE", k, f"mode=comment {smeta} new commits "
                                            f"{quiet_h:.1f}h ago -> waiting on re-request"))
                continue
            rows.append(("DONE", k, f"mode=comment {smeta} review posted "
                                    "-> not yours to merge"))
            continue

        # the table prints head[:7] and mark-reviewed stores whatever it was
        # given, so compare by prefix rather than exact match
        if not rv or not head.startswith(rv):
            if rounds >= MAX_REVIEW_ROUNDS:
                rows.append(("CAPPED", k,
                             f"mode={it['mode']} {smeta} head={head[:7]} "
                             f"rounds={rounds}/{MAX_REVIEW_ROUNDS} "
                             "-> autopilot stopped; you decide"))
                continue
            rows.append(("REVIEW", k, f"mode={it['mode']} {smeta} "
                                      f"head={head[:7]} "
                                      f"reviewed={(it.get('reviewed_sha') or 'none')[:7]} "
                                      f"round={rounds + 1}/{MAX_REVIEW_ROUNDS}"))
        elif it["mode"] == "comment":
            # mark-reviewed runs right after the prompt is sent, so the sha
            # match alone does not mean the review is posted: while the session
            # is still running it is in flight and holds its slot. Once idle,
            # the review waits on the author, not on an agent -- no slot. It is
            # still tracked, so a new push brings back REVIEW.
            if live.get(sess, {}).get("state") == "running":
                rows.append(("WORKING", k, f"mode=comment {smeta} "
                                           "reviewing, not posted yet"))
            else:
                active -= 1
                rows.append(("DONE", k, f"mode=comment {smeta} review posted "
                                        "-> not yours to merge"))
        else:
            rows.append(("READY", k, f"mode=fix {smeta} checks={checks_of(d)} "
                                     "-> you merge"))

    # ---- candidates
    # prev_keys too: an issue re-keyed to its PR is still being worked on, and
    # proposing it again would let "go N" spawn a second agent on it.
    seen = set(items) | declined | {pk for it in items.values()
                                    for pk in it.get("prev_keys") or []}
    cand = {}

    for slug in HOME_REPOS:
        for pr in results.get(("prs", slug), []) or []:
            cand[key(slug, pr["number"])] = (slug, pr, mode_for(pr, me))
    for pr in results.get(("as", "*"), []) or []:
        k = key(pr["repo"], pr["number"])
        if k not in cand:
            cand[k] = (pr["repo"], pr, mode_for(pr, me))
    for pr in results.get(("rr", "*"), []) or []:
        k = key(pr["repo"], pr["number"])
        if k not in cand:
            cand[k] = (pr["repo"], pr, mode_for(pr, me))

    for k, (slug, pr, mode) in sorted(cand.items()):
        if k in seen:
            continue
        # a session may already exist on this branch without being tracked
        branch = pr.get("headRefName")
        author = (pr.get("author") or {}).get("login", "?")
        title = (pr.get("title") or "")[:52]
        meta[k] = {"title": pr.get("title"), "url": pr.get("url"),
                   "author": author, "mode": mode, "item_kind": "pr"}
        if slug not in reg:
            rows.append(("UNCLONED", k, f"mode={mode} {author} \"{title}\""))
            continue
        rows.append(("PROPOSE", k, f"mode={mode} {author} \"{title}\""))

    for iss in ((sum((results.get(("iss", s), []) or [] for s in HOME_REPOS), []))
                + (results.get(("oi", "*"), []) or [])):
        k = key(iss["repo"], iss["number"], "issue")
        if k in seen:
            continue
        seen.add(k)
        meta[k] = {"title": iss.get("title"), "url": iss.get("url"),
                   "mode": "fix", "item_kind": "issue"}
        if iss["repo"] not in reg:
            rows.append(("UNCLONED", k, f"mode=fix issue \"{iss['title'][:52]}\""))
        else:
            rows.append(("PROPOSE", k, f"mode=fix issue \"{iss['title'][:52]}\""))

    # ---- stale worktree sessions with no tracked item and no open PR
    # The open-branch set must cover EVERY registered repo, not just the home
    # ones: a session on a non-home repo with a live PR is not stale.
    open_branches = set()
    for slug in HOME_REPOS:
        for pr in results.get(("prs", slug), []) or []:
            open_branches.add((reg.get(slug, {}).get("path", "").rstrip("/"),
                               pr["headRefName"]))
    others = [s2 for s2 in reg if s2 not in HOME_REPOS]
    if others:
        with ThreadPoolExecutor(max_workers=8) as ex:
            heads = dict(zip(others, ex.map(open_heads, others)))
        for slug, brs in heads.items():
            path = reg[slug]["path"].rstrip("/")
            for br in brs:
                open_branches.add((path, br))
    tracked_sessions = {v.get("session") for v in items.values()}
    for (mp, br), s in sorted(by_branch.items()):
        if s["id"] in tracked_sessions or (mp, br) in open_branches:
            continue
        if mp not in path_to_slug:
            continue
        age = session_age(s, live)
        if age < STALE_HOURS * 3600:
            continue
        rows.append(("STALE", path_to_slug[mp],
                     f"branch={br} session={sid(s['id'])} "
                     "nopr "
                     f"idle={age // 3600}h"))

    # Sessions running on this machine that autopilot did not start. They are
    # real load even though they are not tracked, so the header shows them --
    # otherwise ACTIVE reads 0/6 while 15 agents are already running.
    untracked = sum(
        1 for (mp, br), s2 in by_branch.items()
        if s2["id"] not in tracked_sessions and mp in path_to_slug)

    state["items"] = items
    return rows, active, len(reg), untracked


# ------------------------------------------------------- render & spawn

def resolve_key(state, k):
    """Exact key, else an item that used to be known by it.

    An issue-driven item is re-keyed from owner/repo!ISSUE to owner/repo#PR the
    moment its PR appears, but the agent's prompt still carries the old key.
    Without this, its first claim-round after opening the PR fails and the
    round is never counted."""
    items = state.get("items", {})
    if k in items:
        return k
    for cand, it in items.items():
        if k in (it.get("prev_keys") or []):
            return cand
    return k


def split_key(k):
    """'owner/repo#123' -> (slug, 123, 'pr'); '...!123' -> (slug, 123, 'issue')"""
    if "#" in k:
        slug, num = k.split("#", 1)
        return slug, int(num), "pr"
    if "!" in k:
        slug, num = k.split("!", 1)
        return slug, int(num), "issue"
    if "?" in k:
        slug, name = k.split("?", 1)
        return slug, name, "investigate"
    raise SystemExit(f"bad key {k!r} (want owner/repo#PR, owner/repo!ISSUE "
                     f"or owner/repo?investigation)")


def orchestrator_session(state=None):
    """Address of the orchestrator, for the agent to report back to.

    The session rendering the prompt is the orchestrator, so its own address
    wins; the recorded one is the fallback. A stale address would silently
    swallow every agent report.
    """
    return current_orch() or orchestrator_target(state or load())


def issue_context(slug, number, body_max=8000, comment_max=1500, keep=8):
    """The issue, verbatim, for splicing into the prompt.

    Fetched here rather than summarised by the orchestrator: a paraphrase of a
    requirement is lossy in exactly the way that matters, and the orchestrator
    typically read only the title and body while the discussion often lives in
    the comments.

    Body and comments get separate budgets. A single overlong body must never
    be able to push the comments out -- the comments are the part the
    orchestrator has not seen, so they are the last thing to drop.
    """
    d = gh_json(["issue", "view", str(number), "-R", slug, "--json",
                 "number,title,body,labels,comments"], default=None)
    if not d:
        return ""

    def clip(text, limit, hint):
        text = (text or "").strip()
        if len(text) <= limit:
            return text
        return text[:limit] + f"\n\n[...{hint} truncated at {limit} chars]"

    out = [f"### {slug}#{d['number']}: {d.get('title') or ''}"]
    labels = ", ".join(l.get("name", "") for l in (d.get("labels") or []))
    if labels:
        out.append(f"labels: {labels}")
    out += ["", clip(d.get("body"), body_max, "body") or "_(no description)_"]

    comments = d.get("comments") or []
    dropped = max(0, len(comments) - keep)
    if dropped:
        out += ["", f"[{dropped} earlier comment(s) omitted -- read them with "
                    f"`gh issue view {number} -R {slug} --comments`]"]
    for c in comments[-keep:]:
        who = (c.get("author") or {}).get("login", "?")
        when = (c.get("createdAt") or "")[:10]
        out += ["", f"--- comment by {who} ({when}) ---",
                clip(c.get("body"), comment_max, "comment")]
    return "\n".join(out)


def render_prompt(name, subs):
    pdir = os.environ.get("PROMPT_DIR") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "prompts")
    path = os.path.join(pdir, name if name.endswith(".md") else name + ".md")
    with open(path) as fh:
        body = fh.read()
    with open(os.path.join(pdir, "shared", "pr-hygiene.md")) as fh:
        subs.setdefault("HYGIENE", fh.read().strip())
    # {{LOOP}} is only substituted for templates that actually carry it, so
    # review-comment.md (someone else's branch) never gets a push loop.
    if "{{LOOP}}" in body:
        with open(os.path.join(pdir, "shared", "agent-loop.md")) as fh:
            subs.setdefault("LOOP", fh.read().strip())
    if "{{ORCH}}" in body or "{{LOOP}}" in body:
        subs.setdefault("ORCH", orchestrator_session())
    # Set unconditionally: this placeholder lives inside the LOOP fragment,
    # not in the template body, so an `in body` test would never fire.
    subs.setdefault("COLD_REVIEW_MODEL", MODEL_COLD_REVIEW)
    if "{{CONTEXT}}" in body and "CONTEXT" not in subs and subs.get("ISSUE") \
            and subs.get("REPO"):
        subs["CONTEXT"] = issue_context(subs["REPO"], subs["ISSUE"])
    if "KEY" not in subs and subs.get("REPO"):
        if subs.get("PR"):
            subs["KEY"] = f"{subs['REPO']}#{subs['PR']}"
        elif subs.get("ISSUE"):
            subs["KEY"] = f"{subs['REPO']}!{subs['ISSUE']}"
    subs.setdefault("REVIEW_CMD", os.environ.get("REVIEW_CMD", "/review"))
    if name in ("review-comment", "re-review", "review-stack"):
        subs.setdefault("REVIEW_LEVEL",
                        os.environ.get("REVIEW_LEVEL_COMMENT", "medium"))
    subs.setdefault("REVIEW_LEVEL", os.environ.get("REVIEW_LEVEL", "xhigh"))
    subs.setdefault("REVIEW_LEVEL_FOLLOWUP",
                    os.environ.get("REVIEW_LEVEL_FOLLOWUP", "high"))
    # Shared fragments are spliced in FIRST: they carry their own {{REPO}},
    # {{PR}} and {{BRANCH}} placeholders, and if they were substituted in the
    # same pass as everything else those would survive the pass and then be
    # stripped to empty by the sweep below -- yielding `gh pr checks  -R  `.
    for frag in ("CONTEXT", "LOOP", "HYGIENE"):
        if frag in subs:
            body = body.replace("{{" + frag + "}}", str(subs[frag]))
    for k, v in subs.items():
        if k in ("CONTEXT", "LOOP", "HYGIENE"):
            continue
        body = body.replace("{{" + k + "}}", str(v))
    return re.sub(r"\{\{[A-Z_]+\}\}", "", body).strip()


def resolve_mode(slug, num, kind, me):
    """Re-derived here, never taken on trust from the caller."""
    if kind in ("issue", "investigate"):
        return "fix"
    d = gh_json(["pr", "view", str(num), "-R", slug, "--json",
                 "author,assignees"],
                default={}) or {}
    return mode_for(d, me)


def find_session(repo_path, branch):
    for s in all_sessions()[0]:
        wt = s.get("worktree") or {}
        if (wt.get("main_repo_path") or "").rstrip("/") == repo_path.rstrip("/") \
                and wt.get("branch") == branch:
            return s
    return None


def spawn(state, key_, branch, title, new_branch, question=None):
    me = whoami(state)
    slug, num, kind = split_key(key_)
    reg = state.get("registry", {})
    if slug not in reg:
        raise SystemExit(f"{slug} is not in the registry -- no local clone under "
                         f"CLONE_ROOTS ({' '.join(CLONE_ROOTS)}). Clone it first.")
    r = reg[slug]
    path, base = r["path"], r["base"]
    mode = resolve_mode(slug, num, kind, me)

    code, _, err = sh(["git", "fetch", "origin"], cwd=path, timeout=180)
    if code != 0:
        raise SystemExit(f"git fetch failed in {path}: {err}")
    if new_branch:
        sh(["git", "pull", "--ff-only"], cwd=path, timeout=180)

    if find_session(path, branch):
        raise SystemExit(f"a session already exists on {branch} in {slug}")

    tmpl = {"issue": "work", "investigate": "investigate"}.get(
        kind, "review-fix" if mode == "fix" else "review-comment")
    model = MODEL_FOR.get(tmpl, "")

    host = spawn_herdr(key_, path, base, branch, title, new_branch, model)

    item = {"mode": mode, "branch": branch, "pr": num if kind == "pr" else None,
            "reviewed_sha": None, "phase": "working", "added": int(time.time()),
            "driver": "agent" if mode == "fix" else "orchestrator"}
    item.update({k: v for k, v in host.items() if k != "warning"})
    if question:
        item["question"] = question
    state["items"][key_] = item
    save(state)
    log_event("spawn", key_, mode=mode, branch=branch, session=item["session"],
              title=title)

    where = " ".join(f"{k}={v}" for k, v in host.items()
                     if k not in ("session", "warning", "backend"))
    print(f"spawned {key_} mode={mode} branch={branch} "
          f"session={item['session']} {where} model={model or 'default'}")
    if host.get("warning"):
        print(f"WARNING: {host['warning']}")
    print(f"next: `$A send {key_} ...` with the '{tmpl}' prompt")
    print(f"PROMPT_TEMPLATE={tmpl} BASE={base} REPO={slug}")
    return 0


def worktree_dir(repo, branch):
    """<repo>/.worktrees/<branch with / as ->."""
    return os.path.join(repo.rstrip("/"), ".worktrees", branch.replace("/", "-"))


def agent_name(key_):
    """A herdr agent name ([a-z][a-z0-9_-]{0,31}) unique among live agents:
    ap-<repo>-<number>, e.g. ap-vocdoni-app-1782."""
    slug, num, _ = split_key(key_)
    base = re.sub(r"[^a-z0-9_-]+", "-",
                  f"ap-{slug.split('/', 1)[-1]}-{num}".lower()).strip("-")
    taken = {a.get("name") for a in herdr_agents()}
    name, n = base[:32], 2
    while name in taken:
        sfx = f"-{n}"
        name, n = base[:32 - len(sfx)] + sfx, n + 1
    return name


def spawn_herdr(key_, path, base, branch, title, new_branch, model):
    """git worktree + herdr workspace + named claude agent.

    The worktree is created with git, not `herdr worktree create`: for a
    branch that only exists on origin, herdr makes a fresh local branch off
    HEAD instead of tracking it, which would put a PR's agent on the wrong
    code. herdr then opens the checkout as a workspace, grouped under the
    repo's.
    """
    wt = worktree_dir(path, branch)
    listed = sh(["git", "worktree", "list", "--porcelain"], cwd=path)[1]
    if f"worktree {wt}" not in listed.splitlines():
        if new_branch:
            args = ["git", "worktree", "add", "--no-track", "-b", branch, wt,
                    f"origin/{base}"]
        elif sh(["git", "rev-parse", "--verify", "--quiet",
                 f"refs/heads/{branch}"], cwd=path)[0] == 0:
            args = ["git", "worktree", "add", wt, branch]
        else:
            args = ["git", "worktree", "add", "--track", "-b", branch, wt,
                    f"origin/{branch}"]
        code, out, err = sh(args, cwd=path, timeout=180)
        if code != 0:
            raise SystemExit(f"git worktree add failed: {err or out}")

    code, data, raw = herdr(["worktree", "open", "--cwd", path, "--path", wt,
                             "--label", title, "--no-focus"])
    if code != 0:
        raise SystemExit(f"herdr worktree open failed: {raw}")
    res = data["result"]
    ws, pane = res["workspace"]["workspace_id"], res["root_pane"]["pane_id"]

    name = agent_name(key_)
    args = ["agent", "start", name, "--kind", "claude", "--pane", pane,
            "--timeout", "60000"]
    if model:
        # argv straight to claude, no shell: opus[1m] needs no quoting here.
        args += ["--", "--model", model]
    # The pane's shell may still be starting; agent start needs its prompt.
    for attempt in range(3):
        code, data, raw = herdr(args, timeout=90)
        if code == 0 or herdr_error(data) == "agent_not_ready":
            break
        time.sleep(2)
    host = {"backend": "herdr", "session": ws, "agent": name, "worktree": wt}
    if code != 0 and herdr_error(data) == "agent_not_ready":
        if not accept_trust(name, wt, path):
            host["warning"] = (f"agent {name} is blocked at startup; check "
                               f"workspace {ws} before sending it a prompt")
    elif code != 0:
        raise SystemExit(f"herdr agent start failed (workspace {ws} kept): "
                         f"{raw}")
    return host


def accept_trust(name, wt, repo):
    """Answer claude's "do you trust this folder?" for a worktree of one of
    our own clones, and nothing else. -> True once the agent is idle."""
    if not os.path.realpath(wt).startswith(os.path.realpath(repo) + os.sep):
        return False
    _, screen, _ = sh(["herdr", "agent", "read", name, "--source", "visible"])
    if "trust this folder" not in screen:
        return False
    # The dialog defaults to "No, exit": move to "Yes" before confirming.
    herdr(["agent", "send-keys", name, "down", "enter"])
    code, _, _ = herdr(["agent", "wait", name, "--until", "idle",
                        "--timeout", "60000"], timeout=90)
    return code == 0


def siblings(state, slug, exclude=None):
    """Tracked mode=fix items in `slug` with an open PR -- the rebase fan-out
    set. mode=comment items are never included: they are other people's
    branches and must not be pushed to."""
    out = []
    for k, it in sorted(state.get("items", {}).items()):
        if k == exclude:
            continue
        if not k.startswith(slug + "#") and not k.startswith(slug + "!"):
            continue
        if it.get("mode") != "fix" or not it.get("pr") or not it.get("session"):
            continue
        out.append((k, it))
    return out


def print_siblings(state, slug, exclude=None):
    base = state.get("registry", {}).get(slug, {}).get("base", "main")
    rows = siblings(state, slug, exclude)
    if not rows:
        print("SIBLINGS: none")
        return
    print("SIBLINGS:")
    for k, it in rows:
        print(f"  {it['session']} {it['branch']} {it['pr']} {base} {k}")


def cleanup(state, key_):
    """Remove a merged item's session and worktree, then mark it handled."""
    it = state.get("items", {}).get(key_)
    if not it:
        print(f"{key_} is not tracked; nothing to clean up", file=sys.stderr)
        return 1
    sess = it.get("session")
    if sess:
        code, _, raw = herdr(["worktree", "remove", "--workspace", sess,
                              "--force"], timeout=180)
        wt = it.get("worktree")
        if code != 0 and wt and os.path.isdir(wt):
            # The workspace is already gone; the checkout may not be.
            code, out, err = sh(["git", "worktree", "remove", "--force", wt],
                                cwd=wt, timeout=180)
            raw = err or out
        print(f"herdr worktree remove {sess}: {'ok' if code == 0 else raw}")
    if key_ not in state["handled_merges"]:
        state["handled_merges"].append(key_)
    state["items"].pop(key_, None)
    save(state)
    log_event("cleanup", key_)
    print(f"cleaned up {key_}")
    slug = key_.split("#")[0].split("!")[0]
    print_siblings(state, slug)
    return 0


ORDER = ["MERGED", "REVIEW", "FEEDBACK", "BOOTING", "WORKING", "STALLED",
         "READY", "CAPPED", "PUSHED", "DONE", "CLOSED", "GONE",
         "PROPOSE", "UNCLONED", "STALE", "UNKNOWN"]


def row_order(r):
    return (ORDER.index(r[0]) if r[0] in ORDER else 99, r[1])


def wind_down():
    """'yes'/'no' against WIND_DOWN_AT in local time, None when unset."""
    if not WIND_DOWN_AT:
        return None
    return "yes" if time.strftime("%H:%M") >= WIND_DOWN_AT.zfill(5) else "no"


def render(rows, active, nrepos, state, untracked=0):
    extra = f"   UNTRACKED {untracked}" if untracked else ""
    wd = wind_down()
    if wd:
        extra += f"   WIND_DOWN {wd} (from {WIND_DOWN_AT})"
    if state.get("inbox"):
        extra += f"   INBOX {len(state['inbox'])} (run inbox)"
    print(f"PAUSED {'yes' if state.get('paused') else 'no'}   "
          f"REPOS {nrepos}   ACTIVE {active}/{MAX_ACTIVE}{extra}")
    rows.sort(key=row_order)
    if not rows:
        print("(nothing actionable)")
    for kind, k, extra in rows:
        print(f"{kind:<9}{k:<38}{extra}")


ROW_TITLE = re.compile(r'"(.*)"')
ROW_FIELD = re.compile(r"(\w+)=(\S+)")
# Item fields the dashboard shows; the rest of an item is bookkeeping.
SNAPSHOT_ITEM_FIELDS = ("mode", "branch", "session", "pr", "driver", "phase",
                        "review_rounds", "last_seen", "last_note",
                        "last_report", "added", "question", "reviewed_sha")


def parse_extra(extra):
    """A row's free-text tail -> {fields, title, note}.

    The quoted title goes first: it may itself contain `=` or `->`."""
    out = {}
    m = ROW_TITLE.search(extra)
    if m:
        out["title"] = m.group(1)
        extra = extra[:m.start()] + extra[m.end():]
    head, _, note = extra.partition(" -> ")
    out["fields"] = dict(ROW_FIELD.findall(head))
    if note.strip():
        out["note"] = note.strip()
    return out


def snapshot(state):
    """Run a scan on a throwaway copy of the state and publish it as JSON.

    Nothing is saved: the orchestrator's scan owns every state transition
    (feedback watermarks, re-keys, untracking), and a dashboard refreshing
    every two minutes must never consume one of them before it does.
    """
    work = copy.deepcopy(state)
    info = {}
    rows, active, nrepos, untracked = scan(work, info=info)
    rows.sort(key=row_order)
    items = work.get("items", {})
    out = []
    for kind, k, extra in rows:
        r = {"kind": kind, "key": k, "extra": extra}
        r.update(parse_extra(extra))
        it = items.get(k)
        if it:
            r["item"] = {f: it[f] for f in SNAPSHOT_ITEM_FIELDS
                         if it.get(f) is not None}
        d = info["details"].get(k)
        m = info["meta"].get(k)
        if d:
            r.update(title=d.get("title"), url=d.get("url"),
                     checks=checks_of(d), head=(d.get("headRefOid") or "")[:7],
                     draft=bool(d.get("isDraft")))
        elif m:
            r.update({f: v for f, v in m.items() if v is not None})
        out.append(r)
    snap = {"generated_at": int(time.time()),
            "paused": bool(state.get("paused")),
            "repos": nrepos, "active": active, "max_active": MAX_ACTIVE,
            "untracked": untracked, "max_rounds": MAX_REVIEW_ROUNDS,
            "stall_min": AGENT_STALL_MIN,
            "last_tick": state.get("last_tick"),
            "orch": orchestrator_target(state),
            "rows": out}
    os.makedirs(os.path.dirname(SNAPSHOT_FILE), exist_ok=True)
    tmp = f"{SNAPSHOT_FILE}.tmp.{os.getpid()}"
    with open(tmp, "w") as fh:
        json.dump(snap, fh, indent=2, sort_keys=True)
    os.replace(tmp, SNAPSHOT_FILE)
    return snap


def orchestrator_target(state):
    """Where agent reports and dashboard commands are sent."""
    return AUTOPILOT_ORCH or state.get("orch") or f"herdr:{ORCH_AGENT}"


def item_or_exit(state, k):
    k = resolve_key(state, k)
    it = state["items"].get(k)
    if it is None:
        raise SystemExit(f"unknown item {k}")
    return k, it


def send_item(state, k, text):
    """Exit 4 when the agent is sitting on an approval or question: that is
    the user's call, and typing a prompt into it would answer it blindly."""
    k, it = item_or_exit(state, k)
    addr = address_of(it)
    if not addr:
        print(f"{k}: no live agent to send to", file=sys.stderr)
        return 1
    ok, err = send_to(addr, text)
    if not ok:
        if err == "agent_blocked":
            print(f"{k}: agent is waiting on an approval or a question; "
                  "nothing sent -- report it to the user", file=sys.stderr)
            return 4
        print(f"{k}: send to {addr} failed: {err}", file=sys.stderr)
        return 1
    # A new prompt makes the agent's last report history.
    it["last_seen"] = int(time.time())
    save(state)
    log_event("sent", k, text=text.strip().splitlines()[0][:80] if text.strip()
              else "")
    print(f"sent to {k} ({addr})")
    return 0


def reboot(state, k):
    """Give an item's agent a fresh conversation for its next review prompt,
    then mark it booting. herdr clears the conversation in place, keeping
    the pinned model."""
    k, it = item_or_exit(state, k)
    target = herdr_target(it)
    if not target:
        print(f"{k}: no live agent in workspace {it.get('session')}",
              file=sys.stderr)
        return 1
    ok, err = send_to(f"herdr:{target}", "/clear")
    if not ok:
        print(f"{k}: /clear failed: {err}", file=sys.stderr)
        return 4 if err == "agent_blocked" else 1
    herdr(["agent", "wait", target, "--until", "idle", "--timeout",
           "60000"], timeout=90)
    it["phase"] = "booting"
    save(state)
    log_event("reboot", k)
    print(f"{k} rebooted -> booting")
    return 0


REPORT_STATES = ("ready", "capped", "blocked", "failed", "stalled")


def report(state, args):
    """report <key> <state> <sha> <message...> [--to <session>]

    Records the agent's final report on its item and queues it in the
    orchestrator's inbox as the `AUTOPILOT <key> <state> <sha> <message>`
    line it already parses. The dashboard shows it from the item.

    `--to` is accepted and ignored: agents spawned before the inbox still
    pass it.
    """
    if "--to" in args:
        i = args.index("--to")
        args = args[:i] + args[i + 2:]
    if len(args) < 4:
        print("usage: report <key> <state> <sha> <message...> [--to <session>]",
              file=sys.stderr)
        return 1
    k = resolve_key(state, args[1])
    st, sha, msg = args[2], args[3], " ".join(args[4:])
    if st not in REPORT_STATES:
        print(f"bad report state {st!r} (want {'|'.join(REPORT_STATES)})",
              file=sys.stderr)
        return 1
    now = int(time.time())
    it = state["items"].get(k)
    if it is not None:
        it["last_report"] = {"state": st, "sha": sha, "msg": msg[:300],
                             "at": now}
        it["last_seen"] = now
        save(state)
    # Into the orchestrator's inbox, never typed into its pane: a typed
    # prompt lands on whatever the user is half-way through writing there
    # and sends it. The log line below is what its Monitor wakes on.
    to_inbox(state, f"AUTOPILOT {args[1]} {st} {sha} {msg}".rstrip())
    log_event("report", k, state=st, sha=sha[:7], msg=msg[:300])
    print(f"reported {k} {st} -> inbox")
    return 0


INBOX_MAX = 200


def to_inbox(state, text):
    """Queue one message for the orchestrator. Caller holds the lock."""
    box = state.setdefault("inbox", [])
    box.append({"at": int(time.time()), "text": text})
    del box[:-INBOX_MAX]
    save(state)


def inbox(state):
    """Print and clear the orchestrator's pending messages, oldest first.

    Agent reports print as the `AUTOPILOT <key> <state> <sha> <message>` line
    they always were; dashboard requests as `REQUEST <command>`. Continuation
    lines are indented, so every message starts at column 0."""
    box = state.get("inbox") or []
    if not box:
        print("(inbox empty)")
        return 0
    for m in box:
        first, *rest = m["text"].splitlines() or [""]
        print(f"{time.strftime('%H:%M', time.localtime(m['at']))} {first}")
        for line in rest:
            print(f"    {line}")
    state["inbox"] = []
    save(state)
    return 0


READ_ONLY = {"render", "status", "siblings", "snapshot", "wind-down"}


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "scan"
    if cmd in READ_ONLY:
        return dispatch(cmd, args, load())
    # scan mutates (registry memo, feedback_seen stamps) and every other
    # command is a read-modify-write, so both run under the lock.
    with locked():
        return dispatch(cmd, args, load())


def dispatch(cmd, args, state):
    if cmd in ("scan", "refresh"):
        rows, active, n, untracked = scan(state, refresh=(cmd == "refresh"))
        state["last_tick"] = int(time.time())
        # The orchestrator is whoever runs the tick; remembering it here lets
        # `report` and the dashboard reach it without being told.
        orch = current_orch()
        if orch:
            state["orch"] = orch
        save(state)
        render(rows, active, n, state, untracked)
        counts = {}
        for kind, _, _ in rows:
            counts[kind] = counts.get(kind, 0) + 1
        log_event("tick", active=active, counts=counts)
        return 0
    if cmd == "snapshot":
        snap = snapshot(state)
        if "--quiet" not in args:
            print(json.dumps(snap, indent=2, sort_keys=True))
        return 0
    if cmd == "report":
        return report(state, args)
    if cmd == "inbox":
        return inbox(state)
    if cmd == "request":
        # A command from the dashboard (go/no/re-review/investigate...),
        # queued for the orchestrator the same way agent reports are.
        text = " ".join(args[1:]).strip()
        if not text:
            print("usage: request <command...>", file=sys.stderr)
            return 1
        to_inbox(state, f"REQUEST {text}")
        log_event("request", text=text[:200])
        print(f"queued for the orchestrator: {text}")
        return 0
    if cmd == "send":
        # send <key> <text...>: prompt the item's agent, wherever it runs.
        return send_item(state, args[1], " ".join(args[2:]))
    if cmd == "reboot":
        return reboot(state, args[1])
    if cmd == "render":
        # render <template> KEY=VAL ...
        subs = dict(kv.split("=", 1) for kv in args[2:] if "=" in kv)
        it_ = state.get("items", {}).get(subs.get("KEY", ""), {})
        if it_.get("question"):
            subs.setdefault("QUESTION", it_["question"])
            subs.setdefault("BRANCH", it_.get("branch", ""))
        print(render_prompt(args[1], subs))
        return 0
    if cmd == "spawn":
        # spawn <key> <branch> <title> [--new]
        return spawn(state, args[1], args[2], args[3], "--new" in args[4:])
    if cmd == "investigate":
        # investigate <slug> <name> <branch> <title> <question>
        slug_, name, branch, title, question = args[1:6]
        return spawn(state, key(slug_, name, "investigate"), branch, title,
                     True, question=question)
    if cmd == "siblings":
        print_siblings(state, args[1],
                       args[2] if len(args) > 2 else None)
        return 0
    if cmd == "cleanup":
        return cleanup(state, args[1])
    if cmd == "wind-down":
        print(f"WIND_DOWN {wind_down() or 'off'} (from {WIND_DOWN_AT or '-'})")
        return 0
    if cmd == "status":
        print(json.dumps(state, indent=2, sort_keys=True))
        return 0
    if cmd in ("pause", "resume"):
        state["paused"] = cmd == "pause"
        save(state)
        log_event(cmd)
        print(f"paused={state['paused']}")
        return 0
    if cmd == "decline":
        for k in args[1:]:
            if k not in state["declined"]:
                state["declined"].append(k)
        save(state)
        for k in args[1:]:
            log_event("decline", k)
        print("declined:", " ".join(args[1:]))
        return 0
    if cmd == "undecline":
        state["declined"] = [k for k in state["declined"] if k not in args[1:]]
        save(state)
        print("undeclined:", " ".join(args[1:]))
        return 0
    if cmd == "track":
        # track <key> <mode> <branch> <session> [pr]
        k, mode, branch, session = args[1:5]
        pr = int(args[5]) if len(args) > 5 else None
        if not HERDR_WS.match(session):
            print(f"{session} is not a herdr workspace id (like w12)",
                  file=sys.stderr)
            return 1
        state["items"][k] = {"mode": mode, "branch": branch, "session": session,
                             "pr": pr, "reviewed_sha": None, "phase": "working",
                             "added": int(time.time())}
        # Name its agent so it can be addressed.
        it = state["items"][k]
        it["backend"] = "herdr"
        occupant = herdr_live().get(session) or {}
        if occupant.get("agent"):
            it["agent"] = occupant["agent"]
        elif occupant.get("pane"):
            name = agent_name(k)
            if herdr(["agent", "rename", occupant["pane"], name])[0] == 0:
                it["agent"] = name
        save(state)
        log_event("track", k, mode=mode, branch=branch, session=session)
        print(f"tracked {k} mode={mode} branch={branch} session={sid(session)}")
        return 0
    if cmd == "ack-push":
        # ack-push <key>: the user has seen the PUSHED flag; stop flagging this
        # head. A re-request or a further push brings the PR back.
        k = args[1]
        it = state["items"].get(k)
        if it and it.get("pr"):
            d = pr_detail(k.split("#")[0], it["pr"]) or {}
            it["push_acked"] = d.get("headRefOid")
            save(state)
            print(f"{k} push_acked={str(it['push_acked'])[:7]}")
            return 0
        print(f"unknown item {k}", file=sys.stderr)
        return 1
    if cmd == "detach":
        # detach <key>: park an item without losing its work. Closes its herdr
        # workspace (agent stopped, worktree and branch kept) and drops the
        # item from state, so it holds no slot and its PR/issue is proposed
        # again like anything else. Reverse by hand: `herdr worktree open
        # --path <worktree>`, start claude in it, then `track`.
        k = args[1]
        it = state["items"].get(k)
        if not it:
            print(f"unknown item {k}", file=sys.stderr)
            return 1
        sess = it.get("session")
        if sess:
            code, _, raw = herdr(["workspace", "close", sess])
            if code != 0:
                print(f"herdr workspace close failed: {raw}", file=sys.stderr)
                return 1
        state["items"].pop(k)
        save(state)
        log_event("detach", k, branch=it.get("branch"))
        print(f"detached {k} session={sid(sess)} branch={it.get('branch')} "
              "-> workspace closed"
              f", worktree kept{' at ' + it['worktree'] if it.get('worktree') else ''}"
              ", untracked")
        return 0
    if cmd == "untrack":
        for k in args[1:]:
            state["items"].pop(k, None)
            log_event("untrack", k)
        save(state)
        print("untracked:", " ".join(args[1:]))
        return 0
    if cmd == "set-phase":
        k, phase = args[1], args[2]
        if k in state["items"]:
            state["items"][k]["phase"] = phase
            save(state)
            log_event("phase", k, phase=phase)
            print(f"{k} phase={phase}")
        else:
            print(f"unknown item {k}", file=sys.stderr)
            return 1
        return 0
    if cmd == "mark-feedback":
        k, when = args[1], args[2]
        if k in state["items"]:
            state["items"][k]["feedback_seen"] = when
            state["items"][k]["review_rounds"] = 0
            state["items"][k].pop("capped_at", None)
            save(state)
            log_event("feedback", k, since=when)
            print(f"{k} feedback_seen={when} rounds=0")
        return 0
    if cmd == "mark-reviewed":
        k, sha = args[1], args[2]
        if k in state["items"]:
            it = state["items"][k]
            it["reviewed_sha"] = sha
            it["phase"] = "fixing"
            it["review_rounds"] = int(it.get("review_rounds", 0)) + 1
            save(state)
            log_event("reviewed", k, sha=sha[:7], round=it["review_rounds"])
            print(f"{k} reviewed={sha[:7]} "
                  f"round={it['review_rounds']}/{MAX_REVIEW_ROUNDS}")
        return 0
    if cmd == "claim-round":
        k = resolve_key(state, args[1])
        it = state["items"].get(k)
        if it is None:
            print(f"unknown item {k}", file=sys.stderr)
            return 1
        n = int(it.get("review_rounds", 0))
        if n >= MAX_REVIEW_ROUNDS:
            # The scan shows CAPPED from here even if the agent dies before
            # its `capped` report; reset-rounds and mark-feedback clear it.
            it["capped_at"] = int(time.time())
            save(state)
            log_event("capped", k, round=n)
            print(f"CAPPED rounds={n}/{MAX_REVIEW_ROUNDS}")
            return 3
        n += 1
        it["review_rounds"] = n
        it["phase"] = "fixing"
        it["last_seen"] = int(time.time())
        save(state)
        log_event("round", k, round=n)
        print(f"PROCEED round={n}/{MAX_REVIEW_ROUNDS}")
        return 0
    if cmd == "heartbeat":
        k = resolve_key(state, args[1])
        if k in state["items"]:
            state["items"][k]["last_seen"] = int(time.time())
            if len(args) > 2:
                state["items"][k]["last_note"] = " ".join(args[2:])[:200]
            save(state)
            log_event("heartbeat", k, note=state["items"][k].get("last_note"))
            print(f"{k} last_seen=now")
        return 0
    if cmd == "reset-rounds":
        for k in args[1:]:
            if k in state["items"]:
                state["items"][k]["review_rounds"] = 0
                state["items"][k].pop("capped_at", None)
                log_event("reset-rounds", k)
                print(f"{k} rounds=0/{MAX_REVIEW_ROUNDS}")
        save(state)
        return 0
    if cmd == "mark-merged":
        for k in args[1:]:
            if k not in state["handled_merges"]:
                state["handled_merges"].append(k)
            state["items"].pop(k, None)
            log_event("merged", k)
        save(state)
        print("merged:", " ".join(args[1:]))
        return 0

    print(f"unknown command: {cmd}", file=sys.stderr)
    print("usage: scan.sh [scan|refresh|status|pause|resume|decline|undecline|"
          "track|untrack|detach|set-phase|mark-reviewed|claim-round|heartbeat|"
          "reset-rounds|"
          "mark-merged|"
          "render|spawn|"
          "investigate|snapshot|report|inbox|request|send|reboot|wind-down]", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
