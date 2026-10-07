#!/usr/bin/env python3
"""The tree's agents in herdr: config, lookups, starting them, prompting
them, and typing a prompt into one without sending it.

Stdlib only. The tree's agents run in herdr only: the orchestrator
(`[arbre].orchestrator_agent`, below the board in the Arxiu workspace) and a
research agent (`[arbre].research_agent`) the board starts on demand in a new
tab of that workspace. Each gets ARXIU_ROLE in its pane's environment (the
librarian mod reads it). ARXIU_DRY_RUN=1 turns every action into a message
saying what it would run; read-only calls (listing and getting agents) still
run. See CONTRACT.md.

`agents.py --accept-trust <name> <cwd> <root>` answers claude's folder-trust
prompt for herdr/open.sh.
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULTS = {
    "arbre": {"path": "~/src/arbre", "orchestrator_agent": "arbre",
              "research_agent": "investigacio",
              "research_skill": "genealogy-research",
              "interview_skill": "family-interview", "agent_args": []},
    "ui": {"agents_secs": 3},
}

AGENT_TIMEOUT = 5
ARXIU_LABEL = "Arxiu"          # the workspace herdr/open.sh builds
START_TIMEOUT_MS = 60000
TEXT_MAX = 200

# herdr's lifecycle states -> the contract's.
HERDR_STATE = {"working": "working", "blocked": "waiting", "done": "done",
               "idle": "idle"}


# ---------------------------------------------------------------- config

def load_config(path=None):
    """config.toml next to this module (or $ARXIU_CONFIG), with defaults for
    every missing key and `~` expanded in the tree's path."""
    path = path or os.environ.get("ARXIU_CONFIG") or \
        os.path.join(HERE, "config.toml")
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
    cfg["arbre"]["path"] = os.path.normpath(
        os.path.expanduser(cfg["arbre"]["path"]))
    return cfg


# ---------------------------------------------------------------- utilities

def dry_run():
    return os.environ.get("ARXIU_DRY_RUN") == "1"


def sh(args, timeout=60, cwd=None, env=None):
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


def short(text, n=TEXT_MAX):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _json(text):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def inside(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


def herdr(args, timeout=60):
    """-> (code, parsed JSON or None, raw text). herdr prints results on
    stdout and errors as JSON on stderr."""
    code, out, err = sh(["herdr"] + args, timeout=timeout)
    return code, _json(out) or _json(err), (err or out)


def herdr_error(data):
    return (((data or {}).get("error") or {}).get("code")) or ""


def _run(argv, timeout=60):
    if dry_run():
        return True, "dry-run: " + shlex.join(argv)
    code, out, err = sh(argv, timeout=timeout)
    return code == 0, (out if code == 0 else err or out)


# ---------------------------------------------------------------- lookups

def _agent(a):
    """herdr's agent record -> contract Agent."""
    return {"host": "herdr", "id": a.get("workspace_id") or "",
            "name": a.get("name") or a.get("pane_id") or "",
            "tool": a.get("agent") or "",
            "path": os.path.normpath(a.get("cwd") or ""),
            "state": HERDR_STATE.get(a.get("agent_status"), "unknown"),
            "pane": a.get("pane_id")}


def list_agents(strict=False):
    """Every herdr agent, as contract Agents. No server (exit 1), or no
    herdr at all: no agents -- or None with `strict`, to tell "none" from
    "could not ask"."""
    fail = None if strict else []
    if not shutil.which("herdr"):
        return fail
    code, data, _ = herdr(["agent", "list"], timeout=AGENT_TIMEOUT)
    if code != 0 or not isinstance(data, dict):
        return fail
    return [_agent(a) for a in (data.get("result") or {}).get("agents") or []
            if a.get("cwd")]


def tree_agents(cfg, agents=None):
    """The agents working in the tree (or a worktree inside it)."""
    tree = cfg["arbre"]["path"]
    agents = list_agents() if agents is None else agents
    return [a for a in agents if a.get("path") and inside(a["path"], tree)]


def herdr_agent(name):
    """herdr's own record of the agent called `name` (agent_status, pane_id,
    cwd...), or None when no agent has that name."""
    if not name or not shutil.which("herdr"):
        return None
    code, data, _ = herdr(["agent", "get", name], timeout=AGENT_TIMEOUT)
    if code != 0:
        return None
    return ((data or {}).get("result") or {}).get("agent")


def get_agent(name):
    """The contract Agent called `name`, or None."""
    a = herdr_agent(name)
    return _agent(a) if a else None


def find_workspace(label):
    code, data, _ = herdr(["workspace", "list"], timeout=AGENT_TIMEOUT)
    if code != 0:
        return None
    for w in ((data or {}).get("result") or {}).get("workspaces") or []:
        if w.get("label") == label:
            return w.get("workspace_id")
    return None


def _target(agent):
    """An agent argument -> the name herdr knows it by. Takes a name or a
    contract Agent."""
    if isinstance(agent, str):
        return agent
    return agent.get("name") or agent.get("pane") or agent.get("id")


# ---------------------------------------------------------------- actions

def focus(agent):
    """Bring the agent's pane forward."""
    return _run(["herdr", "agent", "focus", _target(agent)], timeout=10)


def _ready(name, rec, what):
    """None when `rec` (herdr's record of `name`) can take input now, else
    the Catalan reason it cannot."""
    if not rec:
        return f"«{name}» no corre a herdr"
    status = rec.get("agent_status")
    if status == "blocked":
        return (f"{name} espera una resposta teva (aprovació o pregunta): "
                f"no li {what} res")
    if status == "working":
        return f"{name} està treballant: no li {what} res fins que acabi"
    return None


def prompt(agent, text):
    """Submit `text` to the agent (`herdr agent prompt`: the text and Enter).
    Refuses when it is blocked on a question or an approval. -> (ok, msg)"""
    name = _target(agent)
    rec = herdr_agent(name)
    if rec and rec.get("agent_status") == "blocked":
        return False, _ready(name, rec, "envio")
    argv = ["herdr", "agent", "prompt", name, text]
    if dry_run():
        return True, "dry-run: " + shlex.join(argv)
    code, data, raw = herdr(argv[1:])
    if code != 0:
        return False, f"no s'ha pogut enviar a {name}: {short(raw, 160)}"
    return True, f"enviat a {name}"


def one_line(text):
    """Claude's input takes a pasted newline as a newline, but a typed one
    may submit: a prompt that is only typed goes in as one line."""
    return " ".join((text or "").split())


def prefill(agent, text):
    """Type `text` into the agent's input WITHOUT pressing Enter, then focus
    its pane: nothing runs until the user reads it and presses Enter there.
    Only when the agent is idle or done; a working or blocked agent gets
    nothing (its input is in use). -> (ok, message)"""
    name = _target(agent)
    rec = herdr_agent(name)
    why = _ready(name, rec, "escric")
    if why:
        return False, why
    pane = rec.get("pane_id")
    steps = [["herdr", "pane", "send-text", pane, one_line(text)],
             ["herdr", "agent", "focus", name]]
    if dry_run():
        return True, "dry-run: " + " ; ".join(shlex.join(s) for s in steps)
    code, _, raw = herdr(steps[0][1:], timeout=20)
    if code != 0:
        return False, f"no s'ha pogut escriure a {name}: {short(raw, 160)}"
    herdr(steps[1][1:], timeout=10)
    return True, f"escrit a {name}: revisa'l i prem ⏎ per enviar-lo"


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
    question or an approval: that one is for the user. A working one gets
    it anyway: claude queues it after the current turn. -> (ok, message)."""
    status = status or (lambda msg: None)
    a = cfg["arbre"]
    name, tree = a.get("research_agent"), a["path"]
    if not name:
        return False, "[arbre].research_agent buit a config.toml"
    state, _ = research_status(cfg)
    if state == "blocked":
        return False, (f"{name} espera una resposta teva (aprovació o "
                       "pregunta): no li envio res")
    argv = ["herdr", "agent", "prompt", name, text]
    if state == "missing":
        ok, msg = start_agent(name, "research", tree, tree,
                              a.get("agent_args") or [], status)
        if dry_run():
            return ok, msg + " ; " + shlex.join(argv)
        if not ok:
            return False, msg
    if dry_run():
        return True, "dry-run: " + shlex.join(argv)
    status(f"enviant a {name}…")
    code, data, raw = herdr(argv[1:])
    if code != 0 and herdr_error(data) == "agent_not_ready" \
            and accept_trust(name, tree, tree):
        code, data, raw = herdr(argv[1:])
    if code != 0:
        if herdr_error(data) == "agent_not_ready":
            return False, f"{name} no està llest: {short(screen_tail(name), 160)}"
        return False, f"no s'ha pogut enviar a {name}: {short(raw, 160)}"
    return True, f"enviat a {name}"


# ---------------------------------------------------------------- CLI

def main(argv):
    if argv[:1] == ["--accept-trust"] and len(argv) == 4:
        # herdr/open.sh, when the orchestrator stops at claude's trust prompt.
        return 0 if accept_trust(*argv[1:]) else 1
    cfg = load_config()
    for a in tree_agents(cfg):
        print(f"{a['name']:<16} {a['state']:<8} {a['pane'] or '-':<8} "
              f"{a['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
