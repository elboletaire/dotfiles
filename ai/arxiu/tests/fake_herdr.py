"""A fake `herdr` on PATH for the agents.py and actions.py tests: it answers
from canned JSON in a state folder and logs every call, one line each."""
import json
import os
import tempfile
import unittest
from unittest import mock


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


class HerdrCase(unittest.TestCase):
    """state/agents/<name>.json present = an agent with that name exists;
    `agent list` lists them all; start.json / start.code are what `agent
    start` answers (a successful start creates the agent, idle, like
    herdr would)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = self.t = os.path.realpath(self.tmp.name)
        self.tree = os.path.join(t, "arbre")
        os.makedirs(self.tree)
        s = self.state = os.path.join(t, "state")
        os.makedirs(os.path.join(s, "agents"))
        self.bin = os.path.join(t, "bin")
        self.log = os.path.join(t, "calls.log")
        self.queue = os.path.join(t, "cache", "queue.json")
        # Each argument on its own line, a blank line after each call: the
        # tests compare exact argv, spaces inside arguments included.
        write(os.path.join(self.bin, "herdr"), f"""#!/bin/sh
for a in "$@"; do printf '%s\\n' "$a"; done >> {self.log}
echo >> {self.log}
case "$1 $2" in
  "workspace list") cat {s}/workspaces.json ;;
  "workspace create") echo '{{"result":{{"root_pane":{{"pane_id":"w9:p1"}}}}}}' ;;
  "tab create") echo '{{"result":{{"root_pane":{{"pane_id":"w2:p7"}}}}}}' ;;
  "agent list") printf '{{"result":{{"agents":['
                sep=; for f in {s}/agents/*.json; do [ -f "$f" ] || continue
                printf '%s' "$sep"; cat "$f" | tr -d '\\n'; sep=,; done
                printf ']}}}}\\n' ;;
  "agent get") f={s}/agents/$3.json
               [ -f "$f" ] && printf '{{"result":{{"agent":' && cat "$f" && echo '}}}}' && exit 0
               echo '{{"error":{{"code":"agent_not_found"}}}}' >&2; exit 1 ;;
  "agent start") cat {s}/start.json; code=$(cat {s}/start.code)
                 [ "$code" = 0 ] && printf '{{"name":"%s","agent_status":"idle","pane_id":"w2:p7","cwd":"{self.tree}"}}' "$3" > {s}/agents/$3.json
                 exit $code ;;
  "agent read") cat {s}/screen.txt ;;
  "agent prompt"|"agent send-keys"|"agent wait"|"agent focus"|"pane send-text"|"pane run") echo '{{"result":{{}}}}' ;;
  *) exit 3 ;;
esac
""")
        os.chmod(os.path.join(self.bin, "herdr"), 0o755)
        self.workspaces([{"label": "Arxiu", "workspace_id": "w2"}])
        self.start(0)
        write(os.path.join(s, "screen.txt"), "")
        env = mock.patch.dict(os.environ, {
            "PATH": self.bin + os.pathsep + os.environ["PATH"],
            "ARXIU_QUEUE": self.queue})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("ARXIU_DRY_RUN", None)
        self.cfg = {"arbre": {"path": self.tree, "orchestrator_agent": "orq",
                              "research_agent": "inv",
                              "research_skill": "genealogy-research",
                              "agent_args": ["--model", "haiku"]},
                    "ui": {"agents_secs": 3}}

    def workspaces(self, rows):
        write(os.path.join(self.state, "workspaces.json"),
              json.dumps({"result": {"workspaces": rows}}))

    def agent(self, name, status, pane="w1:p2", cwd=None):
        write(os.path.join(self.state, "agents", f"{name}.json"), json.dumps(
            {"name": name, "agent_status": status, "pane_id": pane,
             "workspace_id": pane.split(":")[0], "agent": "claude",
             "cwd": cwd or self.tree}))

    def start(self, code, error=None):
        write(os.path.join(self.state, "start.json"),
              json.dumps({"error": {"code": error}}) if error else "{}")
        write(os.path.join(self.state, "start.code"), str(code))

    def calls(self):
        """Every call as its argv (without "herdr")."""
        try:
            with open(self.log) as fh:
                blocks = fh.read().split("\n\n")
        except OSError:
            return []
        return [b.split("\n") for b in blocks if b.strip()]

    def mutating(self):
        """The calls that change something, as strings (args joined by a
        space, for readability)."""
        reads = (["workspace", "list"], ["agent", "get"], ["agent", "read"],
                 ["agent", "list"])
        return [" ".join(c) for c in self.calls() if c[:2] not in reads]
