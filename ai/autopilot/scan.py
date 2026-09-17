#!/usr/bin/env python3
"""PR Autopilot reconciler.

Reads GitHub + aoe, diffs against a small state file, prints a compact table of
actionable rows. Deterministic; no model involved. See SKILL.md for how the
rows are acted on.
"""
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HOME_REPOS = os.environ.get("HOME_REPOS", "").split()
ISSUE_ORGS = os.environ.get("ISSUE_ORGS", "").split()
MAX_ACTIVE = int(os.environ.get("MAX_ACTIVE", "6"))
STALE_HOURS = int(os.environ.get("STALE_HOURS", "48"))
ISSUE_MAX_AGE_DAYS = int(os.environ.get("ISSUE_MAX_AGE_DAYS", "120"))
STATE_FILE = os.environ.get(
    "STATE_FILE", os.path.expanduser("~/.local/state/pr-autopilot/state.json"))

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
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
    os.replace(tmp, STATE_FILE)


def whoami(state):
    if not state.get("me"):
        state["me"] = gh_json(["api", "user", "--jq", ".login"], default=None) \
            or sh(["gh", "api", "user", "--jq", ".login"])[1]
    return state["me"]


# ------------------------------------------------------------------ aoe side

def aoe_sessions():
    """[{id,title,path,group,worktree:{branch,main_repo_path,base_branch}|None}]"""
    rows = gh_or_aoe(["aoe", "list", "--json"]) or []
    out = []
    for r in rows:
        if r.get("state") not in (None, "live"):
            continue
        wt = r.get("worktree")
        if isinstance(wt, str):
            try:
                wt = json.loads(wt)
            except json.JSONDecodeError:
                wt = None
        r["worktree"] = wt if isinstance(wt, dict) else None
        out.append(r)
    return out


def gh_or_aoe(args):
    code, out, _ = sh(args)
    if code != 0 or not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def aoe_live():
    rows = gh_or_aoe(["aoe", "ps", "--json"]) or []
    return {r["session"]: r for r in rows if r.get("session")}


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


SKIPPED = []
NEW_SKIPS = []


def build_registry(sessions, old, refresh=False, old_skips=None):
    """slug -> {path, group, orc, base}. Derived from orchestrator sessions."""
    reg = {} if refresh else dict(old)
    known_paths = {v["path"] for v in reg.values()}
    # Paths that already failed to resolve: skip re-probing and re-reporting
    # them every tick. `refresh` clears the memo so a rename still surfaces.
    memo = set() if refresh else set(old_skips or [])
    todo = []
    for s in sessions:
        path = s.get("path")
        if not path or s.get("worktree") or not os.path.isdir(path):
            continue
        if not refresh and (path in known_paths or path in memo):
            continue
        todo.append(s)
    if todo:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for s, res in zip(todo, ex.map(lambda x: resolve_repo(x["path"]), todo)):
                if not res:
                    SKIPPED.append((s.get("title") or "?", s["path"]))
                    NEW_SKIPS.append(s["path"])
                    continue
                slug, base = res
                reg[slug] = {"path": s["path"], "group": s.get("group") or "",
                             "orc": s["id"], "base": base}
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
    rows = gh_json(["search", "prs", query_flag, "--state", "open", "--limit",
                    "60", "--json",
                    "number,repository,title,author,url"], default=[]) or []
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
                       "--owner", org, "--updated", f">={cutoff()}",
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
                 "statusCheckRollup,isDraft,url,title,reviews,comments"],
                default=None)
    return d


def new_feedback(detail, since):
    """Reviews/comments newer than `since` that autopilot did not itself write.

    Author alone cannot identify the agent: it posts with the user's token, so
    its comments are authored by the user. The signature line the prompt
    library mandates is the discriminator."""
    out = []
    since = since or ""
    for r in (detail or {}).get("reviews") or []:
        when = r.get("submittedAt") or ""
        body = r.get("body") or ""
        if when <= since or AGENT_MARKER in body:
            continue
        state_ = r.get("state") or ""
        if state_ not in ("CHANGES_REQUESTED", "COMMENTED", "APPROVED"):
            continue
        # A bare approval is "ship it", not feedback. Only an approval that
        # carries an actual note is worth waking the agent for.
        if state_ == "APPROVED" and not body.strip():
            continue
        out.append((r.get("author", {}).get("login", "?"), when,
                    r.get("state", "REVIEW"), body[:60]))
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

def mode_for(slug, pr_row, me):
    """'fix' | 'comment' | None (out of scope)."""
    if slug in HOME_REPOS:
        return "fix"
    assignees = [a.get("login") for a in (pr_row.get("assignees") or [])]
    if me in assignees:
        return "fix"
    return "comment"      # only reachable via the review-requested search


# ---------------------------------------------------------------------- main

SEP = {"pr": "#", "issue": "!", "investigate": "?"}


def key(slug, num, kind="pr"):
    return f"{slug}{SEP[kind]}{num}"


def scan(state, refresh=False):
    me = whoami(state)
    sessions = aoe_sessions()
    live = aoe_live()
    reg = build_registry(sessions, state.get("registry", {}), refresh,
                         state.get("skipped_paths", []))
    state["registry"] = reg
    state["skipped_paths"] = sorted(
        set(state.get("skipped_paths", [])) | set(NEW_SKIPS))

    path_to_slug = {v["path"].rstrip("/"): k for k, v in reg.items()}

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

    rows = []
    active = 0

    # ---- tracked items
    for k, it in list(items.items()):
        slug = k.split("#")[0].split("!")[0].split("?")[0]
        d = details.get(k)
        sess = it.get("session")
        smeta = f"session={sid(sess)}"

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
            rows.append(("BOOTING", k, f"mode={it['mode']} {smeta}"))
            continue

        if not it.get("pr"):
            # issue-driven work, PR not opened yet
            repo_path = reg.get(slug, {}).get("path", "").rstrip("/")
            found = None
            for pr in results.get(("prs", slug), []) or []:
                if pr["headRefName"] == it.get("branch"):
                    found = pr
                    break
            if found is None and repo_path:
                got = gh_json(["pr", "list", "-R", slug, "--state", "open",
                               "--head", it.get("branch", ""), "--json",
                               PR_FIELDS], default=[]) or []
                found = got[0] if got else None
            if found:
                it["pr"] = found["number"]
                nk = key(slug, found["number"])
                items[nk] = items.pop(k)
                rows.append(("REVIEW", nk,
                             f"mode={it['mode']} {smeta} head={found['headRefOid'][:7]} "
                             f"reviewed=none"))
                active += 1
                continue
            st = live.get(sess, {}).get("state", "?")
            age = live.get(sess, {}).get("age_secs", 0)
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
        # the table prints head[:7] and mark-reviewed stores whatever it was
        # given, so compare by prefix rather than exact match
        if not rv or not head.startswith(rv):
            rows.append(("REVIEW", k, f"mode={it['mode']} {smeta} "
                                      f"head={head[:7]} "
                                      f"reviewed={(it.get('reviewed_sha') or 'none')[:7]}"))
        elif it["mode"] == "comment":
            rows.append(("DONE", k, f"mode=comment {smeta} review posted "
                                    "-> not yours to merge"))
        else:
            rows.append(("READY", k, f"mode=fix {smeta} checks={checks_of(d)} "
                                     "-> you merge"))

    # ---- candidates
    seen = set(items) | declined
    cand = {}

    for slug in HOME_REPOS:
        for pr in results.get(("prs", slug), []) or []:
            cand[key(slug, pr["number"])] = (slug, pr, "fix")
    for pr in results.get(("as", "*"), []) or []:
        k = key(pr["repo"], pr["number"])
        if k not in cand:
            cand[k] = (pr["repo"], pr, "fix")
    for pr in results.get(("rr", "*"), []) or []:
        k = key(pr["repo"], pr["number"])
        if k not in cand:
            cand[k] = (pr["repo"], pr, "comment")

    for k, (slug, pr, mode) in sorted(cand.items()):
        if k in seen:
            continue
        # a session may already exist on this branch without being tracked
        branch = pr.get("headRefName")
        author = (pr.get("author") or {}).get("login", "?")
        title = (pr.get("title") or "")[:52]
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
        age = live.get(s["id"], {}).get("age_secs", 0)
        if age < STALE_HOURS * 3600:
            continue
        rows.append(("STALE", path_to_slug[mp],
                     f"branch={br} session={sid(s['id'])} nopr "
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


def render_prompt(name, subs):
    pdir = os.environ.get("PROMPT_DIR") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "prompts")
    path = os.path.join(pdir, name if name.endswith(".md") else name + ".md")
    with open(path) as fh:
        body = fh.read()
    with open(os.path.join(pdir, "shared", "pr-hygiene.md")) as fh:
        subs.setdefault("HYGIENE", fh.read().strip())
    subs.setdefault("REVIEW_CMD", os.environ.get("REVIEW_CMD", "/review"))
    subs.setdefault("REVIEW_LEVEL", os.environ.get("REVIEW_LEVEL", "high"))
    for k, v in subs.items():
        body = body.replace("{{" + k + "}}", str(v))
    return re.sub(r"\{\{[A-Z_]+\}\}", "", body).strip()


def resolve_mode(slug, num, kind, me):
    """Re-derived here, never taken on trust from the caller."""
    if slug in HOME_REPOS:
        return "fix"
    if kind in ("issue", "investigate"):
        return "fix"
    d = gh_json(["pr", "view", str(num), "-R", slug, "--json", "assignees"],
                default={}) or {}
    logins = [a.get("login") for a in (d.get("assignees") or [])]
    return "fix" if me in logins else "comment"


def find_session(repo_path, branch):
    for s in aoe_sessions():
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
        raise SystemExit(f"{slug} is not in the registry -- no local clone with an "
                         f"orchestrator session. Clone it and create one first.")
    r = reg[slug]
    path, base, orc, group = r["path"], r["base"], r["orc"], r["group"]
    mode = resolve_mode(slug, num, kind, me)

    code, _, err = sh(["git", "fetch", "origin"], cwd=path, timeout=180)
    if code != 0:
        raise SystemExit(f"git fetch failed in {path}: {err}")
    if new_branch:
        sh(["git", "pull", "--ff-only"], cwd=path, timeout=180)

    if find_session(path, branch):
        raise SystemExit(f"a session already exists on {branch} in {slug}")

    args = ["aoe", "add", path, "-w", branch]
    if new_branch:
        args += ["-b", "--base-branch", base]
    args += ["-P", orc, "-t", title, "-l"]
    code, out, err = sh(args, timeout=300)
    if code != 0:
        raise SystemExit(f"aoe add failed: {err or out}")

    if group:
        sh(["aoe", "group", "move", title, f"{group}/worktrees"], timeout=60)

    sess = find_session(path, branch)
    if not sess:
        raise SystemExit("session created but could not be located by branch; "
                         "check `aoe list --json`")

    item = {"mode": mode, "branch": branch, "session": sess["id"],
            "pr": num if kind == "pr" else None, "reviewed_sha": None,
            "phase": "working", "added": int(time.time())}
    if question:
        item["question"] = question
    state["items"][key_] = item
    save(state)

    tmpl = {"issue": "work", "investigate": "investigate"}.get(
        kind, "review-fix" if mode == "fix" else "review-comment")
    print(f"spawned {key_} mode={mode} branch={branch} session={sess['id']} "
          f"group={group}/worktrees")
    print(f"next: send the '{tmpl}' prompt to session {sess['id']}")
    print(f"PROMPT_TEMPLATE={tmpl} BASE={base} REPO={slug}")
    return 0


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
        code, out, err = sh(["aoe", "remove", sess, "--delete-worktree",
                             "--force"], timeout=180)
        print(f"aoe remove {sid(sess)}: {'ok' if code == 0 else (err or out)}")
    if key_ not in state["handled_merges"]:
        state["handled_merges"].append(key_)
    state["items"].pop(key_, None)
    save(state)
    print(f"cleaned up {key_}")
    slug = key_.split("#")[0].split("!")[0]
    print_siblings(state, slug)
    return 0


ORDER = ["MERGED", "REVIEW", "FEEDBACK", "BOOTING", "WORKING", "READY", "DONE", "CLOSED",
         "PROPOSE", "UNCLONED", "STALE", "UNKNOWN"]


def render(rows, active, nrepos, state, untracked=0):
    extra = f"   UNTRACKED {untracked}" if untracked else ""
    print(f"PAUSED {'yes' if state.get('paused') else 'no'}   "
          f"REPOS {nrepos}   ACTIVE {active}/{MAX_ACTIVE}{extra}")
    rows.sort(key=lambda r: (ORDER.index(r[0]) if r[0] in ORDER else 99, r[1]))
    if not rows:
        print("(nothing actionable)")
    for kind, k, extra in rows:
        print(f"{kind:<9}{k:<38}{extra}")
    for title, path in SKIPPED:
        print(f"{'SKIPPED':<9}{title:<38}{path} -> gh repo view failed "
              "(not a repo, renamed, or no access)")


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "scan"
    state = load()

    if cmd in ("scan", "refresh"):
        rows, active, n, untracked = scan(state, refresh=(cmd == "refresh"))
        save(state)
        render(rows, active, n, state, untracked)
        return 0
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
    if cmd == "status":
        print(json.dumps(state, indent=2, sort_keys=True))
        return 0
    if cmd in ("pause", "resume"):
        state["paused"] = cmd == "pause"
        save(state)
        print(f"paused={state['paused']}")
        return 0
    if cmd == "decline":
        for k in args[1:]:
            if k not in state["declined"]:
                state["declined"].append(k)
        save(state)
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
        state["items"][k] = {"mode": mode, "branch": branch, "session": session,
                             "pr": pr, "reviewed_sha": None, "phase": "working",
                             "added": int(time.time())}
        save(state)
        print(f"tracked {k} mode={mode} branch={branch} session={sid(session)}")
        return 0
    if cmd == "untrack":
        for k in args[1:]:
            state["items"].pop(k, None)
        save(state)
        print("untracked:", " ".join(args[1:]))
        return 0
    if cmd == "set-phase":
        k, phase = args[1], args[2]
        if k in state["items"]:
            state["items"][k]["phase"] = phase
            save(state)
            print(f"{k} phase={phase}")
        else:
            print(f"unknown item {k}", file=sys.stderr)
            return 1
        return 0
    if cmd == "mark-feedback":
        k, when = args[1], args[2]
        if k in state["items"]:
            state["items"][k]["feedback_seen"] = when
            save(state)
            print(f"{k} feedback_seen={when}")
        return 0
    if cmd == "mark-reviewed":
        k, sha = args[1], args[2]
        if k in state["items"]:
            state["items"][k]["reviewed_sha"] = sha
            state["items"][k]["phase"] = "fixing"
            save(state)
            print(f"{k} reviewed={sha[:7]}")
        return 0
    if cmd == "mark-merged":
        for k in args[1:]:
            if k not in state["handled_merges"]:
                state["handled_merges"].append(k)
            state["items"].pop(k, None)
        save(state)
        print("merged:", " ".join(args[1:]))
        return 0

    print(f"unknown command: {cmd}", file=sys.stderr)
    print("usage: scan.sh [scan|refresh|status|pause|resume|decline|undecline|"
          "track|untrack|set-phase|mark-reviewed|mark-merged|render|spawn|"
          "investigate]", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
