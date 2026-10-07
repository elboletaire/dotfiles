"""What the board asked the tree's agents to do: every prompt it prefilled
or sent, newest last, in `~/.cache/arxiu/queue.json` (bounded), with a status
followed from herdr's agent states.

Stdlib only. An entry (CONTRACT.md):

    {id, at, kind, target, label, agent, mode: "prefill" | "send", status}

Status: a prefill starts `prefilled` (typed, not sent: it waits for the
user's Enter), a send starts `sent`; then `working` -> `waiting` (blocked on
the user) -> `done`. `stopped`: the agent is gone. `discarded`: a newer
prefill to the same agent replaced one that was never sent.
"""
import json
import os
import time

MAX_ENTRIES = 50
# A send whose agent is idle again this long after it went in, without ever
# being seen working, is done (a short turn between two refreshes). Before
# that, idle only means claude has not picked it up yet.
SEND_GRACE = 20
ACTIVE = ("prefilled", "sent", "working", "waiting")
FINAL = ("done", "stopped", "discarded")
LABEL = {"prefilled": "escrit", "sent": "enviat", "working": "treballant",
         "waiting": "t'espera", "done": "fet", "stopped": "aturat",
         "discarded": "descartat"}


def default_path():
    if os.environ.get("ARXIU_QUEUE"):
        return os.environ["ARXIU_QUEUE"]
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(cache, "arxiu", "queue.json")


def load(path=None):
    """The entries, oldest first ([] when there is no file or it is broken)."""
    try:
        with open(path or default_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict)] \
        if isinstance(data, list) else []


def save(entries, path=None):
    """Write atomically, keeping the newest MAX_ENTRIES."""
    path = path or default_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(entries[-MAX_ENTRIES:], fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def append(kind, target, label, agent, mode, path=None, now=None):
    """Record a prefill or a send. -> the new entry. An older prefill to the
    same agent that is still unsent is discarded: the new text went into the
    same input."""
    now = now or time.time()
    entries = load(path)
    if mode == "prefill":
        for e in entries:
            if e.get("agent") == agent and e.get("status") == "prefilled":
                e["status"] = "discarded"
    n = sum(1 for e in entries if int(e.get("at") or 0) == int(now))
    entry = {"id": f"{int(now)}-{n}", "at": now, "kind": kind,
             "target": target, "label": label, "agent": agent, "mode": mode,
             "status": "prefilled" if mode == "prefill" else "sent"}
    entries.append(entry)
    save(entries, path)
    return entry


def next_status(entry, state, now=None):
    """An entry's status given its agent's contract state now (None: the
    agent is not running)."""
    now = now or time.time()
    st = entry.get("status")
    if st not in ACTIVE:
        return st
    if state is None:
        return "stopped"
    if state == "working":
        return "working"
    if state == "waiting":
        # A prefill is only typed: the agent blocked on something else.
        return st if st == "prefilled" else "waiting"
    if state in ("idle", "done"):
        if st in ("working", "waiting"):
            return "done"
        if st == "sent" and now - (entry.get("at") or 0) > SEND_GRACE:
            return "done"
    return st


def refresh(entries, agents, now=None):
    """Follow each agent's state into its entries, in place. Only the newest
    active entry of an agent follows it while it works; older active ones of
    the same agent are done once it is idle again. -> True when anything
    changed."""
    state = {a.get("name"): a.get("state") for a in agents}
    changed = False
    newest = {}
    for e in entries:
        if e.get("status") in ACTIVE:
            newest[e.get("agent")] = e
    for e in entries:
        if e.get("status") not in ACTIVE:
            continue
        s = state.get(e.get("agent"))
        if e is newest.get(e.get("agent")):
            new = next_status(e, s, now)
        elif s is None:
            new = "stopped"
        elif s in ("idle", "done"):
            new = "done"
        else:
            new = e["status"]
        if new != e["status"]:
            e["status"] = new
            changed = True
    return changed


def update(agents, path=None, now=None):
    """Load, refresh from `agents`, save when anything changed. -> entries."""
    entries = load(path)
    if refresh(entries, agents, now):
        save(entries, path)
    return entries
