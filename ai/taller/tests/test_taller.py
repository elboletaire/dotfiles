"""Tests for taller.py against real throwaway git repos, fake transcripts
under a temp HOME and fake aoe/herdr executables on PATH."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import taller  # noqa: E402

GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True,
                   env=dict(os.environ, **GIT_ENV))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def jsonl(path, rows):
    write(path, "".join(json.dumps(r) + "\n" for r in rows))


def make_repo(path, remote=None):
    """A repo with one commit; with `remote`, pushed and tracking it."""
    os.makedirs(path)
    run("git", "init", "-q", "-b", "main", cwd=path)
    write(os.path.join(path, "a.txt"), "a\n")
    run("git", "add", ".", cwd=path)
    run("git", "commit", "-q", "-m", "init", cwd=path)
    if remote:
        run("git", "init", "-q", "--bare", "-b", "main", remote)
        run("git", "remote", "add", "origin", remote, cwd=path)
        run("git", "push", "-q", "-u", "origin", "main", cwd=path)


def fake_bin(d, name, script):
    path = os.path.join(d, name)
    write(path, "#!/bin/sh\n" + script)
    os.chmod(path, 0o755)


class TallerCase(unittest.TestCase):
    """Builds a small world: src/ with repos, an extra repo, a hidden one, a
    non-repo folder with an aoe agent, transcripts, fake aoe and herdr."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.t = os.path.realpath(self.tmp.name)
        self.home = os.path.join(t, "home")
        self.src = os.path.join(t, "src")
        self.bin = os.path.join(t, "bin")
        os.makedirs(self.home)
        # The user's global gitignore lists .worktrees/; the temp HOME needs
        # it too, or a worktree inside a repo counts as an untracked file.
        os.makedirs(os.path.join(self.home, ".config", "git"))
        with open(os.path.join(self.home, ".config", "git", "ignore"), "w") as fh:
            fh.write(".worktrees/\n")
        os.makedirs(self.bin)
        os.makedirs(self.src)

        # alpha: tracked upstream, one commit ahead, a dirty file, a worktree
        # with its own dirty file.
        self.alpha = os.path.join(self.src, "alpha")
        make_repo(self.alpha, remote=os.path.join(t, "remotes", "alpha.git"))
        write(os.path.join(self.alpha, "b.txt"), "b\n")
        run("git", "add", ".", cwd=self.alpha)
        run("git", "commit", "-q", "-m", "ahead", cwd=self.alpha)
        write(os.path.join(self.alpha, "dirty.txt"), "x\n")
        self.wt = os.path.join(self.alpha, ".worktrees", "feat-x")
        run("git", "worktree", "add", "-q", "-b", "feat/x", self.wt, cwd=self.alpha)
        write(os.path.join(self.wt, "w1.txt"), "1\n")
        write(os.path.join(self.wt, "w2.txt"), "2\n")
        # beta: no remote; hidden: hidden by name; plain: not a repo.
        self.beta = os.path.join(self.src, "beta")
        make_repo(self.beta)
        make_repo(os.path.join(self.src, "hidden"))
        os.makedirs(os.path.join(self.src, "plain"))
        # extra: outside the roots.
        self.extra = os.path.join(t, "elsewhere", "extra")
        make_repo(self.extra)
        # docker: not a repo, an aoe agent runs there.
        self.docker = os.path.join(t, "docker")
        os.makedirs(self.docker)

        self.cfg = {
            "arbre": {"path": os.path.join(self.src, "arbre")},
            "taller": {"roots": [self.src], "extra": [self.extra],
                       "hide": ["hidden"], "dormant_days": 14},
        }
        self.aoe_list = [
            {"id": "a1", "title": "Alpha WT", "path": self.wt, "tool": "claude",
             "state": "live"},
            {"id": "a2", "title": "*arr", "path": self.docker, "tool": "claude",
             "state": "live"},
            {"id": "a3", "title": "Beta", "path": self.beta + "/", "tool": "pi",
             "state": "live"},
            {"id": "a4", "title": "Gone", "path": self.alpha + "/.worktrees/.aoe-trash/a4",
             "tool": "claude", "state": "trashed",
             "worktree": json.dumps({"branch": "x"})},
            {"id": "a5", "title": "Extra", "path": self.extra, "tool": "claude",
             "state": "live"},
        ]
        self.aoe_ps = [{"session": "a1", "state": "running"},
                       {"session": "a2", "state": "waiting"}]
        self.herdr_out = {"result": {"agents": [
            {"name": "ha", "agent": "pi", "agent_status": "blocked",
             "workspace_id": "w1", "pane_id": "p1", "cwd": self.alpha}]}}
        self.herdr_running = True
        self.env = mock.patch.dict(os.environ, {
            "HOME": self.home, "PATH": self.bin + os.pathsep + os.environ["PATH"],
            "XDG_CONFIG_HOME": os.path.join(self.home, ".config"), **GIT_ENV})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.tmp.cleanup)

    def fakes(self):
        d = os.path.join(self.t, "canned")
        write(os.path.join(d, "list.json"), json.dumps(self.aoe_list))
        write(os.path.join(d, "ps.json"), json.dumps(self.aoe_ps))
        write(os.path.join(d, "show.json"), json.dumps({"status": "error"}))
        write(os.path.join(d, "herdr.json"), json.dumps(self.herdr_out))
        log = os.path.join(self.t, "calls.log")
        fake_bin(self.bin, "aoe", f"""echo "aoe $*" >> {log}
case "$1" in
  list) cat {d}/list.json ;;
  ps) cat {d}/ps.json ;;
  session) [ "$2" = show ] && [ "$3" = a5 ] && cat {d}/show.json || echo '{{"status":"stopped"}}' ;;
  *) exit 3 ;;
esac
""")
        if self.herdr_running:
            fake_bin(self.bin, "herdr", f"""echo "herdr $*" >> {log}
[ "$1 $2" = "agent list" ] && cat {d}/herdr.json || exit 3
""")
        else:
            fake_bin(self.bin, "herdr", f"""echo "herdr $*" >> {log}
echo '{{"id":"cli:agent:list","error":{{"code":"server_not_running","message":"no herdr server"}}}}' >&2
exit 1
""")
        return log

    def collect(self):
        self.fakes()
        return {p["name"]: p for p in taller.collect(self.cfg)}


class DiscoveryTest(TallerCase):
    def test_roots_extra_hide_and_agent_folders(self):
        ps = self.collect()
        self.assertEqual(set(ps), {"alpha", "beta", "extra", "*arr"})
        self.assertNotIn("plain", ps)  # not a repo, no agent
        arr = ps["*arr"]
        self.assertFalse(arr["git"])
        self.assertEqual(arr["path"], self.docker)
        self.assertIn("no_git", arr["flags"])

    def test_hide_by_full_path(self):
        self.cfg["taller"]["hide"] = [self.beta]
        self.assertNotIn("beta", self.collect())

    def test_worktree_is_not_a_project(self):
        # Even a worktree dropped right under a root belongs to its repo.
        outside = os.path.join(self.src, "alpha-wt")
        run("git", "worktree", "add", "-q", "-b", "feat/y", outside, cwd=self.alpha)
        ps = self.collect()
        self.assertNotIn("alpha-wt", ps)
        paths = {w["path"]: w for w in ps["alpha"]["worktrees"]}
        self.assertEqual(set(paths), {self.wt, outside})
        self.assertEqual(paths[self.wt]["branch"], "feat/x")
        self.assertEqual(paths[self.wt]["dirty"], 2)

    def test_agent_in_repo_outside_roots_brings_main_repo(self):
        other = os.path.join(self.t, "other")
        make_repo(other)
        owt = os.path.join(other, ".worktrees", "w")
        run("git", "worktree", "add", "-q", "-b", "w", owt, cwd=other)
        self.aoe_list.append({"id": "a6", "title": "Other", "path": owt,
                              "tool": "claude", "state": "live"})
        ps = self.collect()
        self.assertEqual(ps["other"]["path"], other)
        self.assertEqual([a["id"] for a in ps["other"]["agents"]], ["a6"])


class GitStateTest(TallerCase):
    def test_alpha(self):
        a = self.collect()["alpha"]
        self.assertEqual(a["branch"], "main")
        self.assertEqual(a["dirty"], 1)
        self.assertEqual((a["ahead"], a["behind"]), (1, 0))
        self.assertTrue(a["remote"].endswith("alpha.git"))
        self.assertEqual(set(a["flags"]), {"dirty", "unpushed"})
        self.assertFalse(a["dormant"])

    def test_no_remote_no_upstream(self):
        b = self.collect()["beta"]
        self.assertIsNone(b["ahead"])
        self.assertIsNone(b["behind"])
        self.assertIn("no_remote", b["flags"])
        self.assertNotIn("no_upstream", b["flags"])

    def test_no_upstream(self):
        run("git", "remote", "add", "origin", "git@github.com:o/beta.git", cwd=self.beta)
        b = self.collect()["beta"]
        self.assertEqual(b["remote"], "github:o/beta")
        self.assertIn("no_upstream", b["flags"])

    def test_git_timeout_degrades_one_project(self):
        real = taller.git

        def slow(path, *args, **kw):
            if path.startswith(self.beta):
                return 124, "", "timeout"
            return real(path, *args, **kw)

        with mock.patch.object(taller, "git", slow):
            ps = self.collect()
        self.assertIn("error", ps["beta"]["flags"])
        self.assertNotIn("error", ps["alpha"]["flags"])

    def test_dormant(self):
        now = time.time()
        p = {"git": True, "dirty": 0, "worktrees": [], "ahead": 0, "remote": "x",
             "branch": "main", "_upstream": "origin/main", "agents": [],
             "last_touch": int(now - 20 * 86400)}
        self.assertEqual(taller.finish(dict(p), 14, now)["flags"], ["dormant"])
        p2 = dict(p, last_touch=int(now - 86400))
        self.assertFalse(taller.finish(p2, 14, now)["dormant"])
        # A live agent keeps an old project awake; a stopped one does not.
        p3 = dict(p, agents=[{"state": "idle"}])
        self.assertFalse(taller.finish(p3, 14, now)["dormant"])
        p4 = dict(p, agents=[{"state": "stopped"}])
        self.assertTrue(taller.finish(p4, 14, now)["dormant"])


class RemoteTest(unittest.TestCase):
    def test_forms(self):
        cases = {
            "git@github.com:elboletaire/dotfiles.git": "github:elboletaire/dotfiles",
            "ssh://git@github.com/elboletaire/manga-downloader": "github:elboletaire/manga-downloader",
            "https://github.com/tdlib/telegram-bot-api.git": "github:tdlib/telegram-bot-api",
            "ssh://git@gitlab.com/elboletaire/planets.git": "gitlab:elboletaire/planets",
            "ssh://git@gitlab.com:2222/group/sub/repo.git": "gitlab:group/sub/repo",
            "git@gitlab.com:qtmule/QtMule.git": "gitlab:qtmule/QtMule",
            "https://user@gitlab.com/a/b": "gitlab:a/b",
            "elboletaire.loc:/home/x/arbre": "elboletaire.loc:/home/x/arbre",
            "/srv/git/x.git": "/srv/git/x.git",
        }
        for url, want in cases.items():
            self.assertEqual(taller.parse_remote(url), want, url)
        self.assertIsNone(taller.parse_remote(None))


class AgentsTest(TallerCase):
    def test_states_and_matching(self):
        ps = self.collect()
        alpha = {a["id"]: a for a in ps["alpha"]["agents"]}
        self.assertEqual(alpha["a1"]["state"], "working")       # running
        self.assertEqual(alpha["a1"]["path"], self.wt)
        self.assertEqual(alpha["w1"]["state"], "waiting")       # herdr blocked
        self.assertEqual(alpha["w1"]["pane"], "p1")
        self.assertEqual(alpha["w1"]["host"], "herdr")
        self.assertEqual(ps["*arr"]["agents"][0]["state"], "waiting")
        self.assertEqual(ps["beta"]["agents"][0]["state"], "stopped")  # not in ps
        self.assertEqual(ps["extra"]["agents"][0]["state"], "error")   # show: error
        ids = [a["id"] for p in ps.values() for a in p["agents"]]
        self.assertNotIn("a4", ids)  # trashed

    def test_herdr_not_running(self):
        self.herdr_running = False
        t0 = time.time()
        ps = self.collect()
        self.assertLess(time.time() - t0, 10)
        self.assertEqual([a["id"] for a in ps["alpha"]["agents"]], ["a1"])

    def test_no_binaries(self):
        with mock.patch.object(taller.shutil, "which", return_value=None):
            self.assertEqual(taller.list_agents(), [])

    def test_find_project_deepest(self):
        ps = list(self.collect().values())
        self.assertEqual(taller.find_project(ps, self.wt + "/sub")["name"], "alpha")
        self.assertEqual(taller.find_project(ps, self.beta)["name"], "beta")
        self.assertIsNone(taller.find_project(ps, "/nowhere"))


class TranscriptTest(TallerCase):
    def claude(self, cwd, name, rows, age=0):
        d = taller.claude_dir(cwd)
        path = os.path.join(d, name)
        jsonl(path, rows)
        t = time.time() - age
        os.utime(path, (t, t))
        return path

    def test_claude_dir_naming(self):
        self.assertTrue(taller.claude_dir("/home/u/.dotfiles").endswith(
            "/.claude/projects/-home-u--dotfiles"))
        self.assertTrue(taller.claude_dir("/mnt/d/fotos antigues - proves").endswith(
            "-mnt-d-fotos-antigues---proves"))
        self.assertTrue(taller.pi_dir("/home/u/.dotfiles").endswith(
            "/.pi/agent/sessions/--home-u-.dotfiles--"))

    def test_claude_parsing(self):
        ts = "2026-10-01T10:00:00.000Z"
        rows = [
            {"type": "ai-title", "aiTitle": "Old title"},
            {"type": "user", "timestamp": ts, "message": {"role": "user",
             "content": "Fix   the\n  bug please"}},
            {"type": "assistant", "timestamp": ts, "message": {"role": "assistant",
             "content": [{"type": "thinking", "thinking": "hm"},
                         {"type": "text", "text": "Looking."}]}},
            {"type": "user", "timestamp": ts, "message": {"role": "user",
             "content": [{"type": "tool_result", "content": "out"}]}},
            {"type": "user", "isMeta": True, "message": {"role": "user",
             "content": "<local-command-caveat>x</local-command-caveat>"}},
            {"type": "user", "message": {"role": "user",
             "content": "<command-name>/clear</command-name>"}},
            {"type": "user", "message": {"role": "user",
             "content": "<system-reminder>noise</system-reminder>"}},
            {"type": "ai-title", "aiTitle": "Bug fixing"},
            {"type": "assistant", "timestamp": "2026-10-01T10:05:00Z",
             "message": {"role": "assistant",
                         "content": [{"type": "text", "text": "Fixed. " + "x" * 400}]}},
            {"type": "last-prompt", "lastPrompt": "Fix the bug please"},
        ]
        self.claude(self.beta, "s.jsonl", rows)
        ex = self.collect()["beta"]["last_exchange"]
        self.assertEqual(ex["user"], "Fix the bug please")
        self.assertTrue(ex["agent"].startswith("Fixed. xxx"))
        self.assertLessEqual(len(ex["agent"]), taller.TEXT_MAX)
        self.assertEqual(ex["title"], "Bug fixing")
        self.assertEqual(ex["tool"], "claude")
        self.assertEqual(ex["at"], taller.iso_epoch("2026-10-01T10:05:00Z"))

    def test_custom_title_wins_and_pending_reply(self):
        rows = [
            {"type": "assistant", "message": {"role": "assistant",
             "content": [{"type": "text", "text": "previous answer"}]}},
            {"type": "user", "message": {"role": "user", "content": "new question"}},
            {"type": "custom-title", "customTitle": "My name"},
            {"type": "ai-title", "aiTitle": "Auto name"},
        ]
        self.claude(self.beta, "s.jsonl", rows)
        ex = self.collect()["beta"]["last_exchange"]
        self.assertEqual(ex["user"], "new question")
        self.assertEqual(ex["agent"], "")  # still working on it
        self.assertEqual(ex["title"], "My name")

    def test_pi_parsing(self):
        d = taller.pi_dir(self.beta)
        jsonl(os.path.join(d, "2026-10-01_x.jsonl"), [
            {"type": "session", "cwd": self.beta},
            {"type": "message", "timestamp": "2026-10-01T11:00:00Z",
             "message": {"role": "user", "content": [{"type": "text", "text": "hola"}]}},
            {"type": "message", "message": {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "..."},
                {"type": "toolCall", "name": "bash"}]}},
            {"type": "message", "message": {"role": "toolResult",
             "content": [{"type": "text", "text": "tool out"}]}},
            {"type": "message", "timestamp": "2026-10-01T11:01:00Z",
             "message": {"role": "assistant", "content": [{"type": "text", "text": "adéu"}]}},
            {"type": "custom_message", "content": "notify"},
        ])
        ex = self.collect()["beta"]["last_exchange"]
        self.assertEqual((ex["user"], ex["agent"], ex["title"], ex["tool"]),
                         ("hola", "adéu", None, "pi"))
        self.assertEqual(taller.resume_cmd(self.collect()["beta"]),
                         ["env", "-C", self.beta, "pi", "--continue"])

    def test_newest_across_worktrees_and_last_touch(self):
        self.claude(self.alpha, "old.jsonl", [
            {"type": "user", "message": {"role": "user", "content": "root"}}], age=3600)
        self.claude(self.wt, "new.jsonl", [
            {"type": "user", "timestamp": "2099-01-01T00:00:00Z",
             "message": {"role": "user", "content": "in worktree"}}])
        a = self.collect()["alpha"]
        self.assertEqual(a["last_exchange"]["user"], "in worktree")
        self.assertEqual(a["last_exchange"]["path"], self.wt)
        self.assertEqual(a["last_touch"], taller.iso_epoch("2099-01-01T00:00:00Z"))
        self.assertEqual(taller.resume_cmd(a), ["env", "-C", self.wt, "claude", "--continue"])

    def test_tail_reads_only_the_end(self):
        path = os.path.join(self.t, "big.jsonl")
        filler = json.dumps({"type": "assistant", "message": {"role": "assistant",
                            "content": [{"type": "text", "text": "y" * 1000}]}})
        with open(path, "w") as fh:
            fh.write(json.dumps({"type": "user", "message": {"role": "user",
                                 "content": "too far"}}) + "\n")
            for _ in range(200):
                fh.write(filler + "\n")
        with mock.patch.object(taller, "TAIL_MAX", 32 * 1024):
            lines = list(taller.tail_lines(path, 32 * 1024))
            ex = taller.read_exchange(path, "claude")
        self.assertLess(len(lines), 60)
        self.assertEqual(ex["user"], "")
        self.assertTrue(ex["agent"].startswith("yyy"))


class ActionsTest(unittest.TestCase):
    aoe = {"host": "aoe", "id": "s1", "name": "Alpha", "tool": "claude",
           "path": "/x", "state": "idle", "pane": None}
    herdr = {"host": "herdr", "id": "w1", "name": "ha", "tool": "pi",
             "path": "/x", "state": "idle", "pane": "p1"}

    def test_dry_run_runs_nothing(self):
        with mock.patch.dict(os.environ, {"ARXIU_DRY_RUN": "1"}), \
                mock.patch.object(taller.subprocess, "run") as sp:
            ok, msg = taller.send(self.aoe, "hola món")
            self.assertTrue(ok)
            self.assertEqual(msg, "dry-run: aoe send s1 'hola món'")
            ok, msg = taller.send(self.herdr, "hi")
            self.assertEqual(msg, "dry-run: herdr agent prompt ha hi")
            ok, msg = taller.focus(self.herdr)
            self.assertEqual((ok, msg), (True, "dry-run: herdr agent focus ha"))
            ok, _ = taller.focus(self.aoe)
            self.assertFalse(ok)
            sp.assert_not_called()

    def test_attach_and_resume(self):
        self.assertEqual(taller.attach_cmd(self.aoe), ["aoe", "session", "attach", "s1"])
        self.assertEqual(taller.resume_cmd({"path": "/p", "last_exchange": None}),
                         ["env", "-C", "/p", "claude", "--continue"])


class HerdrNativeTest(unittest.TestCase):
    """The tree's agents in herdr: a fake `herdr` on PATH answers from canned
    JSON in a state folder and logs every call."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.t = os.path.realpath(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.tree = os.path.join(t, "arbre")
        os.makedirs(self.tree)
        self.state = os.path.join(t, "state")
        self.bin = os.path.join(t, "bin")
        os.makedirs(self.state)
        os.makedirs(self.bin)
        self.log = os.path.join(t, "calls.log")
        self.cfg = {"arbre": {"path": self.tree, "research_agent": "inv",
                              "agent_args": ["--model", "haiku"]}}
        s = self.state
        # agent.json present = the agent exists; start.json is what
        # `agent start` answers (and its exit code in start.code); start
        # creates agent.json, like herdr would.
        fake_bin(self.bin, "herdr", f"""printf '%s\\n' "herdr $*" >> {self.log}
case "$1 $2" in
  "workspace list") cat {s}/workspaces.json ;;
  "workspace create") echo '{{"result":{{"root_pane":{{"pane_id":"w9:p1"}}}}}}' ;;
  "tab create") echo '{{"result":{{"root_pane":{{"pane_id":"w2:p7"}}}}}}' ;;
  "agent get") [ -f {s}/agent.json ] && cat {s}/agent.json && exit 0
               echo '{{"error":{{"code":"agent_not_found"}}}}' >&2; exit 1 ;;
  "agent start") cat {s}/start.json; code=$(cat {s}/start.code)
                 [ "$code" = 0 ] && echo '{{"result":{{"agent":{{"agent_status":"idle"}}}}}}' > {s}/agent.json
                 exit $code ;;
  "agent read") cat {s}/screen.txt ;;
  "agent prompt"|"agent send-keys"|"agent wait"|"pane run") echo '{{"result":{{}}}}' ;;
  *) exit 3 ;;
esac
""")
        self.workspaces([{"label": "Arxiu", "workspace_id": "w2"}])
        self.start(0)
        write(os.path.join(s, "screen.txt"), "")
        self.env = mock.patch.dict(os.environ, {
            "PATH": self.bin + os.pathsep + os.environ["PATH"]})
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("ARXIU_DRY_RUN", None)

    def workspaces(self, rows):
        write(os.path.join(self.state, "workspaces.json"),
              json.dumps({"result": {"workspaces": rows}}))

    def agent(self, status):
        write(os.path.join(self.state, "agent.json"), json.dumps(
            {"result": {"agent": {"name": "inv", "agent_status": status}}}))

    def start(self, code, error=None):
        write(os.path.join(self.state, "start.json"),
              json.dumps({"error": {"code": error}}) if error else "{}")
        write(os.path.join(self.state, "start.code"), str(code))

    def calls(self):
        try:
            with open(self.log) as fh:
                return fh.read().splitlines()
        except OSError:
            return []

    def mutating(self):
        return [c for c in self.calls()
                if not c.startswith(("herdr workspace list", "herdr agent get",
                                     "herdr agent read"))]

    def test_running_agent_is_prompted(self):
        self.agent("idle")
        ok, msg = taller.prompt_research(self.cfg, "hola món")
        self.assertTrue(ok, msg)
        self.assertEqual(self.mutating(), ["herdr agent prompt inv hola món"])

    def test_blocked_agent_gets_nothing(self):
        self.agent("blocked")
        ok, msg = taller.prompt_research(self.cfg, "hola")
        self.assertFalse(ok)
        self.assertIn("espera una resposta", msg)
        self.assertEqual(self.mutating(), [])

    def test_missing_agent_starts_in_a_tab_of_arxiu(self):
        seen = []
        ok, msg = taller.prompt_research(self.cfg, "hola", seen.append)
        self.assertTrue(ok, msg)
        self.assertEqual(self.mutating(), [
            f"herdr tab create --workspace w2 --cwd {self.tree} --label inv "
            "--env ARXIU_ROLE=research --no-focus",
            "herdr agent start inv --kind claude --pane w2:p7 --timeout 60000 "
            "-- --model haiku",
            "herdr agent prompt inv hola"])
        self.assertTrue(any("engegant inv" in s for s in seen), seen)

    def test_without_arxiu_workspace_it_gets_its_own(self):
        self.workspaces([{"label": "other", "workspace_id": "w1"}])
        ok, _ = taller.prompt_research(self.cfg, "hola")
        self.assertTrue(ok)
        self.assertEqual(self.mutating()[0],
                         f"herdr workspace create --label inv --cwd {self.tree} "
                         "--env ARXIU_ROLE=research --no-focus")

    def test_trust_prompt_in_the_tree_is_accepted(self):
        self.start(1, "agent_not_ready")
        write(os.path.join(self.state, "screen.txt"),
              "Do you trust this folder?\n> No, exit\n  Yes\n")
        ok, msg = taller.prompt_research(self.cfg, "hola")
        self.assertTrue(ok, msg)
        calls = self.mutating()
        self.assertIn("herdr agent send-keys inv down enter", calls)
        self.assertEqual(calls[-1], "herdr agent prompt inv hola")

    def test_other_dialogs_are_left_for_the_user(self):
        self.start(1, "agent_not_ready")
        write(os.path.join(self.state, "screen.txt"),
              "Allow this MCP server?\n> Yes\n  No\n")
        ok, msg = taller.prompt_research(self.cfg, "hola")
        self.assertFalse(ok)
        self.assertIn("Allow this MCP server", msg)
        self.assertFalse([c for c in self.calls()
                          if "send-keys" in c or "prompt" in c])

    def test_trust_outside_the_tree_is_refused(self):
        write(os.path.join(self.state, "screen.txt"), "trust this folder")
        self.assertFalse(taller.accept_trust("inv", self.t, self.tree))
        self.assertTrue(taller.accept_trust("inv", self.tree + "/x", self.tree))

    def test_dry_run_says_and_runs_nothing(self):
        with mock.patch.dict(os.environ, {"ARXIU_DRY_RUN": "1"}):
            ok, msg = taller.prompt_research(self.cfg, "hola")
            self.assertTrue(ok)
            self.assertIn("herdr tab create --workspace w2", msg)
            self.assertIn("herdr agent start inv --kind claude --pane '<pane>'",
                          msg)
            self.assertIn("herdr agent prompt inv hola", msg)
            self.agent("idle")
            ok, msg = taller.prompt_research(self.cfg, "hola")
            self.assertEqual(msg, "dry-run: herdr agent prompt inv hola")
            ok, msg = taller.open_in_herdr({"name": "alpha", "path": "/p",
                                            "last_exchange": None})
            self.assertEqual(msg, "dry-run: herdr workspace create --label "
                             "alpha --cwd /p --focus ; herdr pane run '<pane>' "
                             "claude")
        self.assertEqual(self.mutating(), [])

    def test_open_in_herdr_resumes_where_it_ran(self):
        p = {"name": "alpha", "path": "/p",
             "last_exchange": {"tool": "pi", "path": "/p/.worktrees/x"}}
        ok, msg = taller.open_in_herdr(p)
        self.assertTrue(ok, msg)
        self.assertEqual(self.mutating(), [
            "herdr workspace create --label alpha --cwd /p/.worktrees/x --focus",
            "herdr pane run w9:p1 env -C /p/.worktrees/x pi --continue"])


class ConfigTest(unittest.TestCase):
    def test_defaults_and_expansion(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.toml")
            write(path, '[taller]\nroots = ["~/code"]\nhide = ["~/code/x", "foo"]\n')
            with mock.patch.dict(os.environ, {"HOME": "/h"}):
                cfg = taller.load_config(path)
        self.assertEqual(cfg["taller"]["roots"], ["/h/code"])
        self.assertEqual(cfg["taller"]["hide"], ["/h/code/x", "foo"])
        self.assertEqual(cfg["taller"]["dormant_days"], 14)
        self.assertEqual(cfg["arbre"]["path"], "/h/src/arbre")
        self.assertEqual(cfg["ui"]["git_secs"], 20)

    def test_env_and_shipped_config(self):
        with mock.patch.dict(os.environ, {"ARXIU_CONFIG": "/nonexistent.toml"}):
            self.assertEqual(taller.load_config()["taller"]["roots"],
                             [os.path.expanduser("~/src")])
        cfg = taller.load_config(os.path.join(taller.HERE, "config.toml"))
        self.assertIn(os.path.expanduser("~/.dotfiles"), cfg["taller"]["extra"])


if __name__ == "__main__":
    unittest.main()
