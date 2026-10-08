"""Tests for taller.py against real throwaway git repos, fake transcripts
under a temp HOME and a fake herdr executable on PATH."""
import io
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
    non-repo folder with an agent, transcripts and a fake herdr."""

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
        # docker: not a repo, an agent runs there.
        self.docker = os.path.join(t, "docker")
        os.makedirs(self.docker)

        self.cfg = {
            "arbre": {"path": os.path.join(self.src, "arbre")},
            "taller": {"roots": [self.src], "extra": [self.extra],
                       "hide": ["hidden"], "dormant_days": 14},
        }
        self.herdr_out = {"result": {"agents": [
            {"name": "ha", "agent": "pi", "agent_status": "blocked",
             "workspace_id": "w1", "pane_id": "p1", "cwd": self.alpha},
            {"name": "alpha-wt", "agent": "claude", "agent_status": "working",
             "workspace_id": "w2", "pane_id": "p2", "cwd": self.wt},
            {"name": "arr", "agent": "claude", "agent_status": "blocked",
             "workspace_id": "w3", "pane_id": "p3", "cwd": self.docker},
            {"name": "beta", "agent": "pi", "agent_status": "idle",
             "workspace_id": "w4", "pane_id": "p4", "cwd": self.beta + "/"},
            {"name": "extra", "agent": "claude", "agent_status": "done",
             "workspace_id": "w5", "pane_id": "p5", "cwd": self.extra},
            {"name": "nocwd", "agent": "claude", "agent_status": "idle",
             "workspace_id": "w9", "pane_id": "p9"}]}}
        self.herdr_running = True
        self.env = mock.patch.dict(os.environ, {
            "HOME": self.home, "PATH": self.bin + os.pathsep + os.environ["PATH"],
            "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
            "XDG_STATE_HOME": os.path.join(self.home, ".local", "state"),
            **GIT_ENV})
        os.environ.pop("TALLER_SLEEP", None)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.tmp.cleanup)

    def fakes(self):
        d = os.path.join(self.t, "canned")
        write(os.path.join(d, "herdr.json"), json.dumps(self.herdr_out))
        log = os.path.join(self.t, "calls.log")
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
        self.assertEqual(set(ps), {"alpha", "beta", "extra", "docker"})
        self.assertNotIn("plain", ps)  # not a repo, no agent
        arr = ps["docker"]
        self.assertFalse(arr["git"])
        self.assertEqual(arr["path"], self.docker)
        self.assertIn("no_git", arr["flags"])

    def test_an_agent_in_a_root_itself_brings_no_project(self):
        # The Taller orchestrator runs in the first root: the folder holding
        # the projects is not one of them.
        self.herdr_out["result"]["agents"].append(
            {"name": "taller", "agent": "claude", "agent_status": "idle",
             "workspace_id": "w7", "pane_id": "p7", "cwd": self.src})
        ps = self.collect()
        self.assertNotIn("src", ps)
        self.assertEqual(set(ps), {"alpha", "beta", "extra", "docker"})

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
        self.herdr_out["result"]["agents"].append(
            {"name": "other", "agent": "claude", "agent_status": "idle",
             "workspace_id": "w6", "pane_id": "p6", "cwd": owt})
        ps = self.collect()
        self.assertEqual(ps["other"]["path"], other)
        self.assertEqual([a["id"] for a in ps["other"]["agents"]], ["w6"])


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


def wt_project(self, **kw):
    """alpha with its worktree, as a TallerCase test hands it to the
    actions."""
    p = {"name": "alpha", "path": self.alpha, "git": True,
         "branch": "main", "agents": [], "last_touch": 1000,
         "worktrees": [{"path": self.wt, "branch": "feat/x", "dirty": 0,
                        "ahead": None}],
         "exchanges": {self.alpha: None, self.wt: {"at": 900}},
         "last_exchange": None}
    p.update(kw)
    return p


class SleepTest(TallerCase):
    proj = wt_project

    def test_put_to_sleep_lists_the_folder(self):
        self.fakes()
        f = taller.folder(self.proj(), self.wt)
        with mock.patch.object(taller, "herdr_agents", return_value=[]):
            ok, msg = taller.put_to_sleep(f, whole=False)
        self.assertTrue(ok, msg)
        self.assertIn(self.wt, taller.load_sleep())
        self.assertTrue(taller.sleep_file().startswith(self.home))

    def test_dry_run_writes_nothing(self):
        self.fakes()
        with mock.patch.dict(os.environ, {"TALLER_DRY_RUN": "1"}), \
                mock.patch.object(taller, "herdr_agents", return_value=[]):
            ok, msg = taller.put_to_sleep(taller.folder(self.proj()), True)
        self.assertIn("adorm " + self.alpha, msg)
        self.assertEqual(taller.load_sleep(), {})

    def test_asleep_until_touched(self):
        now = 5000
        taller.save_sleep({self.alpha: 2000, self.wt: 2000})
        p = self.proj()
        taller.apply_sleep([p], now)
        self.assertTrue(taller.asleep(p))
        self.assertTrue(taller.asleep(p, self.wt))
        self.assertTrue(taller.is_dormant(p, 14, now))
        # A conversation in the worktree afterwards wakes it, and the whole
        # project with it (its last touch is the newest of every folder).
        p = self.proj(last_touch=3000,
                      exchanges={self.alpha: None, self.wt: {"at": 3000}})
        taller.apply_sleep([p], now)
        self.assertEqual(p["slept"], {})
        self.assertEqual(taller.load_sleep(), {})

    def test_a_live_agent_wakes_it_after_the_grace(self):
        taller.save_sleep({self.wt: 4990})
        working = [taller_agent("working", self.wt)]
        p = self.proj(agents=working)
        taller.apply_sleep([p], 5000)       # within the grace: kept
        self.assertIn(self.wt, taller.load_sleep())
        self.assertFalse(taller.asleep(p, self.wt))
        p = self.proj(agents=working)
        taller.apply_sleep([p], 5000 + taller.SLEEP_GRACE)
        self.assertEqual(taller.load_sleep(), {})

    def test_gone_folders_are_dropped(self):
        taller.save_sleep({"/nowhere": 1})
        taller.apply_sleep([self.proj()], 5000)
        self.assertEqual(taller.load_sleep(), {})

    def test_sleepers_and_awake_worktrees(self):
        p = dict(self.proj(), slept={self.wt: 1}, dormant=False)
        self.assertEqual(taller.sleepers([p]), [(p, p["worktrees"][0])])
        self.assertEqual(taller.awake_worktrees(p), [])
        p["dormant"] = True
        self.assertEqual(taller.sleepers([p]), [])
        self.assertEqual(taller.awake_worktrees(p), p["worktrees"])

    def test_sleep_plan(self):
        p = self.proj()
        agents = [taller_agent("idle", self.alpha, "w1", "w1:p1"),
                  taller_agent("idle", self.wt, "w2", "w2:p1"),
                  # the board's own workspace, and one shared with another
                  # project
                  taller_agent("idle", self.alpha, "w9", "w9:p2"),
                  taller_agent("idle", self.wt, "w3", "w3:p1"),
                  taller_agent("idle", self.beta, "w3", "w3:p2")]
        spaces = [{"workspace_id": "w1", "label": "alpha"},
                  {"workspace_id": "w4", "label": "X"},
                  {"workspace_id": "w5", "label": "beta"}]
        whole = taller.sleep_plan(taller.folder(p), True, agents, spaces, "w9")
        self.assertEqual(whole, [["herdr", "workspace", "close", "w1"],
                                 ["herdr", "workspace", "close", "w2"],
                                 ["herdr", "pane", "close", "w3:p1"],
                                 ["herdr", "workspace", "close", "w4"]])
        wt = taller.sleep_plan(taller.folder(p, self.wt), False, agents,
                               spaces, "w9")
        self.assertEqual(wt, [["herdr", "workspace", "close", "w2"],
                              ["herdr", "pane", "close", "w3:p1"],
                              ["herdr", "workspace", "close", "w4"]])
        main = taller.sleep_plan(taller.folder(p), False, agents, spaces,
                                 "w9")
        self.assertEqual(main, [["herdr", "workspace", "close", "w1"]])

    def test_sleep_plan_finds_herdrs_checkout_workspaces(self):
        p = self.proj()
        spaces = [{"workspace_id": "w6", "label": "master",
                   "worktree": {"checkout_path": self.alpha}},
                  {"workspace_id": "w7", "label": "renamed",
                   "worktree": {"checkout_path": self.wt}},
                  # labelled like the project, but beta's checkout
                  {"workspace_id": "w8", "label": "alpha",
                   "worktree": {"checkout_path": self.beta}}]
        self.assertEqual(
            taller.sleep_plan(taller.folder(p), True, [], spaces),
            [["herdr", "workspace", "close", "w6"],
             ["herdr", "workspace", "close", "w7"]])
        self.assertEqual(
            taller.sleep_plan(taller.folder(p, self.wt), False, [], spaces),
            [["herdr", "workspace", "close", "w7"]])

    def test_a_worktree_agent_in_the_repos_workspace_closes_alone(self):
        p = self.proj()
        agents = [taller_agent("idle", self.wt, "w6", "w6:p2")]
        spaces = [{"workspace_id": "w6", "label": "alpha",
                   "worktree": {"checkout_path": self.alpha}}]
        self.assertEqual(
            taller.sleep_plan(taller.folder(p, self.wt), False, agents,
                              spaces),
            [["herdr", "pane", "close", "w6:p2"]])
        # Asleep whole, the repo's workspace is the project's own.
        self.assertEqual(
            taller.sleep_plan(taller.folder(p), True, agents, spaces),
            [["herdr", "workspace", "close", "w6"]])

    def test_starting_an_agent_wakes_the_folder(self):
        taller.save_sleep({self.alpha: 1, self.wt: 1, "/other": 1})
        f = taller.folder(self.proj(), self.wt)
        with mock.patch.object(taller, "launch", return_value=(True, "ok")), \
                mock.patch.object(taller, "herdr_names", return_value=set()), \
                mock.patch.object(taller, "workspaces", return_value=[]):
            taller.fresh_agent(f)
        # The worktree, and its repo asleep whole; nothing else.
        self.assertEqual(taller.load_sleep(), {"/other": 1})

    def test_wake_up(self):
        taller.save_sleep({self.wt: 1})
        self.assertTrue(taller.wake_up(self.wt)[0])
        self.assertEqual(taller.load_sleep(), {})
        self.assertFalse(taller.wake_up(self.wt)[0])


def taller_agent(state, path, wid="w1", pane="p1"):
    return {"host": "herdr", "id": wid, "name": pane, "tool": "claude",
            "path": path, "state": state, "pane": pane}


class WorkspaceTest(TallerCase):
    proj = wt_project

    def ws(self, spaces, path=None):
        with mock.patch.object(taller, "workspaces", return_value=spaces):
            return taller.project_workspace(taller.folder(self.proj(), path))

    def test_a_worktree_never_lands_in_the_repos_workspace(self):
        # `herdr worktree open` for another worktree made the repo's parent
        # workspace, labelled after it: a second worktree must get its own,
        # not a tab there.
        parent = {"workspace_id": "w6", "label": "alpha",
                  "worktree": {"checkout_path": self.alpha}}
        self.assertIsNone(self.ws([parent], self.wt))
        self.assertIsNone(self.ws([dict(parent, worktree=None)], self.wt))
        # The main checkout does use it.
        self.assertEqual(self.ws([parent]), "w6")

    def test_a_worktree_finds_its_own_by_checkout_then_label(self):
        own = {"workspace_id": "w7", "label": "whatever",
               "worktree": {"checkout_path": self.wt}}
        self.assertEqual(self.ws([own], self.wt), "w7")
        self.assertEqual(self.ws([{"workspace_id": "w8", "label": "X"}],
                                 self.wt), "w8")


class RemoveTest(TallerCase):
    def setUp(self):
        super().setUp()
        self.log = os.path.join(self.t, "calls.log")
        d = os.path.join(self.t, "canned")
        write(os.path.join(d, "herdr.json"), json.dumps(self.herdr_out))
        fake_bin(self.bin, "herdr", f"""echo "herdr $*" >> {self.log}
[ "$1 $2" = "agent list" ] && cat {d}/herdr.json
exit 0
""")
        # feat/y: off the remote's main, clean and with nothing unpushed.
        self.wy = os.path.join(self.alpha, ".worktrees", "feat-y")
        run("git", "worktree", "add", "-q", "-b", "feat/y", self.wy,
            "origin/main", cwd=self.alpha)

    def find(self, wt=None):
        ps = taller.collect(self.cfg)
        return taller.find_folder(ps, "alpha", wt)

    def branches(self):
        return subprocess.run(["git", "-C", self.alpha, "branch",
                               "--format=%(refname:short)"],
                              capture_output=True, text=True).stdout.split()

    def test_risks(self):
        self.assertEqual(taller.removal_risks(self.find("feat/x")),
                         ["2 fitxers sense commit",
                          "1 commit que no és a cap remot"])
        self.assertEqual(taller.removal_risks(self.find("feat/y")), [])

    def test_a_clean_worktree_goes_with_its_branch(self):
        ok, msg = taller.remove_worktree(self.find("feat/y"))
        self.assertTrue(ok, msg)
        self.assertEqual(msg, "feat-y eliminat (i la branca feat/y)")
        self.assertFalse(os.path.exists(self.wy))
        self.assertNotIn("feat/y", self.branches())

    def test_risky_takes_forcing(self):
        f = self.find("feat/x")
        ok, msg = taller.remove_worktree(f)
        self.assertFalse(ok)
        self.assertIn("2 fitxers sense commit", msg)
        self.assertIn("cal forçar-ho", msg)
        self.assertTrue(os.path.exists(self.wt))
        self.assertIn("feat/x", self.branches())
        taller.save_sleep({self.wt: 1})
        ok, msg = taller.remove_worktree(f, force=True)
        self.assertTrue(ok, msg)
        self.assertFalse(os.path.exists(self.wt))
        self.assertNotIn("feat/x", self.branches())
        # Its agent's workspace closed, and its sleep entry gone.
        with open(self.log) as fh:
            self.assertIn("herdr workspace close w2", fh.read())
        self.assertEqual(taller.load_sleep(), {})

    def test_never_a_project(self):
        ok, msg = taller.remove_worktree(self.find())
        self.assertFalse(ok)
        self.assertIn("només es poden eliminar worktrees", msg)
        self.assertTrue(os.path.isdir(self.alpha))

    def test_cli(self):
        with self.assertRaises(SystemExit), \
                mock.patch("sys.stderr", io.StringIO()):
            taller.cli(["remove", "alpha"])
        out = io.StringIO()
        with mock.patch("sys.stdout", out), \
                mock.patch.dict(os.environ, {"TALLER_DRY_RUN": "1"}):
            self.assertEqual(taller.cli(["remove", "alpha", "--worktree",
                                         "feat/x"]), 1)
            self.assertEqual(taller.cli(["remove", "alpha", "--worktree",
                                         "feat/x", "--force"]), 0)
        self.assertIn("cal forçar-ho", out.getvalue())
        self.assertIn(f"git -C {self.alpha} worktree remove --force "
                      f"{self.wt} ; git -C {self.alpha} branch -D feat/x",
                      out.getvalue())
        self.assertTrue(os.path.exists(self.wt))


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
        self.assertEqual(alpha["w2"]["state"], "working")
        self.assertEqual(alpha["w2"]["path"], self.wt)
        self.assertEqual(alpha["w1"]["state"], "waiting")       # blocked
        self.assertEqual(alpha["w1"]["pane"], "p1")
        self.assertEqual(alpha["w1"]["host"], "herdr")
        self.assertEqual(ps["docker"]["agents"][0]["state"], "waiting")
        self.assertEqual(ps["beta"]["agents"][0]["state"], "idle")
        self.assertEqual(ps["extra"]["agents"][0]["state"], "done")
        ids = [a["id"] for p in ps.values() for a in p["agents"]]
        self.assertNotIn("w9", ids)  # no cwd

    def test_herdr_not_running(self):
        self.herdr_running = False
        t0 = time.time()
        ps = self.collect()
        self.assertLess(time.time() - t0, 10)
        self.assertEqual(ps["alpha"]["agents"], [])
        self.assertNotIn("docker", ps)  # only its agent brought it in

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

    def test_each_folder_keeps_its_own_conversation(self):
        self.claude(self.alpha, "old.jsonl", [
            {"type": "user", "message": {"role": "user", "content": "root"}}], age=3600)
        self.claude(self.wt, "new.jsonl", [
            {"type": "user", "timestamp": "2099-01-01T00:00:00Z",
             "message": {"role": "user", "content": "in worktree"}}])
        a = self.collect()["alpha"]
        self.assertEqual(a["exchanges"][self.alpha]["user"], "root")
        self.assertEqual(a["exchanges"][self.wt]["user"], "in worktree")
        # The main checkout: its own agents and conversation only.
        main = taller.folder(a)
        self.assertEqual((main["path"], main["worktree"]), (self.alpha, None))
        self.assertEqual([x["name"] for x in main["agents"]], ["ha"])
        self.assertEqual(main["last_exchange"]["user"], "root")
        self.assertEqual(taller.resume_cmd(main),
                         ["env", "-C", self.alpha, "claude", "--continue"])
        # The worktree, shaped like a project of its own.
        w = taller.folder(a, self.wt)
        self.assertEqual((w["path"], w["repo"], w["name"]),
                         (self.wt, self.alpha, "feat/x"))
        self.assertEqual((w["branch"], w["dirty"], w["worktrees"]),
                         ("feat/x", 2, []))
        self.assertEqual([x["name"] for x in w["agents"]], ["alpha-wt"])
        self.assertEqual(w["last_exchange"]["user"], "in worktree")
        # Without a workspace, it opens grouped under the repo's in herdr's
        # sidebar, as `w` does.
        plan = taller.resume_plan(w, taller.agent_name(w["name"]))
        self.assertEqual(plan[0], ["herdr", "worktree", "open", "--cwd",
                                   self.alpha, "--path", self.wt, "--label",
                                   "X", "--focus"])
        self.assertEqual(plan[1][3], "feat-x")
        self.assertEqual(taller.fresh_plan(w, "feat-x")[0][:3],
                         ["herdr", "worktree", "open"])
        # With one, a tab in it.
        self.assertEqual(taller.resume_plan(w, "feat-x", "w2")[0][:3],
                         ["herdr", "tab", "create"])
        # The agent runs, and its trust prompt is answered, in the worktree.
        w["agents"] = []
        with mock.patch.object(taller, "launch", return_value=(True, "ok")) as la, \
                mock.patch.object(taller, "herdr_names", return_value=set()), \
                mock.patch.object(taller, "find_workspace", return_value=None):
            taller.resume_project(w)
        self.assertEqual(la.call_args.args[2:4], (self.wt, self.wt))

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
    herdr = {"host": "herdr", "id": "w1", "name": "ha", "tool": "pi",
             "path": "/x", "state": "idle", "pane": "p1"}

    def test_dry_run_runs_nothing(self):
        with mock.patch.dict(os.environ, {"ARXIU_DRY_RUN": "1"}), \
                mock.patch.object(taller.subprocess, "run") as sp:
            ok, msg = taller.send(self.herdr, "hi")
            self.assertTrue(ok)
            self.assertEqual(msg, "dry-run: herdr agent prompt ha hi")
            ok, msg = taller.focus(self.herdr)
            self.assertEqual((ok, msg), (True, "dry-run: herdr agent focus ha"))
            sp.assert_not_called()

    def test_attach_and_resume(self):
        self.assertEqual(taller.attach_cmd(self.herdr), ["herdr", "agent", "attach", "ha"])
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
                              "agent_args": ["--model", "claude-haiku-5-5[1m]"]}}
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
            "-- --model claude-haiku-5-5[1m]",
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


def project(name="p", path="/p", **kw):
    """A collect()-shaped project."""
    p = {"name": name, "path": path, "git": True, "remote": "github:o/p",
         "branch": "main", "dirty": 0, "ahead": 0, "behind": 0,
         "worktrees": [], "last_touch": int(time.time()), "agents": [],
         "last_exchange": None, "flags": [], "dormant": False}
    p.update(kw)
    return p


def agent(state, host="herdr", name="a", **kw):
    a = {"host": host, "id": "w1", "name": name, "tool": "claude",
         "path": "/p", "state": state, "pane": "w1:p1"}
    a.update(kw)
    return a


class BoardLogicTest(unittest.TestCase):
    def test_agent_name(self):
        n = taller.agent_name
        self.assertEqual(n(".dotfiles"), "dotfiles")
        self.assertEqual(n("*arr"), "arr")
        self.assertEqual(n("QtMule"), "qtmule")
        self.assertEqual(n("feat/user-auth"), "feat-user-auth")
        self.assertEqual(n("2048 game"), "p-2048-game")
        self.assertEqual(n("***"), "agent")
        self.assertEqual(n("x" * 50), "x" * 32)
        self.assertEqual(n("planets", {"planets"}), "planets-2")
        self.assertEqual(n("planets", {"planets", "planets-2"}), "planets-3")
        long = n("y" * 40, {"y" * 32})
        self.assertEqual(long, "y" * 30 + "-2")
        for name in ("dotfiles", "p-2048-game", long, n("Ñandú_ß")):
            self.assertRegex(name, taller.AGENT_NAME)

    def test_sections(self):
        need = [project("w", agents=[agent("waiting")]),
                project("e", agents=[agent("error")]),
                project("d", agents=[agent("done"), agent("working")])]
        working = project("k", agents=[agent("working"), agent("idle")])
        parked = [project("old", last_touch=100),
                  project("new", last_touch=200, agents=[agent("idle")])]
        dormant = project("z", dormant=True, agents=[agent("stopped")])
        got = taller.sections(need + [working] + parked + [dormant])
        self.assertEqual(list(got), ["need", "working", "parked", "dormant"])
        self.assertEqual({p["name"] for p in got["need"]}, {"w", "e", "d"})
        self.assertEqual([p["name"] for p in got["working"]], ["k"])
        self.assertEqual([p["name"] for p in got["parked"]], ["new", "old"])
        self.assertEqual([p["name"] for p in got["dormant"]], ["z"])
        # Wanting you beats being dormant.
        self.assertEqual(taller.section(project(dormant=True, agents=[
            agent("waiting")])), "need")

    def test_wake(self):
        now = time.time()
        p = project(last_touch=int(now - 30 * 86400), flags=["dirty", "error"])
        taller.wake(p, 14, now)
        self.assertEqual(p["flags"], ["dirty", "dormant", "error"])
        p["agents"] = [agent("idle")]
        taller.wake(p, 14, now)
        self.assertEqual((p["dormant"], p["flags"]), (False, ["dirty", "error"]))

    def test_no_backup(self):
        self.assertTrue(taller.no_backup(project(flags=["no_remote"])))
        self.assertTrue(taller.no_backup(project(flags=["unpushed", "dirty"])))
        self.assertFalse(taller.no_backup(project(flags=["dirty"])))
        self.assertFalse(taller.no_backup(project(git=False, flags=["no_git"])))

    def test_pick_agent(self):
        p = project(agents=[agent("idle", name="i"), agent("working", name="w"),
                            agent("done", name="d")])
        self.assertEqual(taller.pick_agent(p)["name"], "d")
        p["agents"].append(agent("waiting", name="b"))
        self.assertEqual(taller.pick_agent(p)["name"], "b")
        self.assertIsNone(taller.pick_agent(project(agents=[])))

    def test_web_url_and_browser(self):
        self.assertEqual(taller.web_url("github:o/r"), "https://github.com/o/r")
        self.assertEqual(taller.web_url("gitlab:g/s/r"), "https://gitlab.com/g/s/r")
        self.assertEqual(taller.web_url("https://git.x/a/b.git"), "https://git.x/a/b")
        self.assertIsNone(taller.web_url("elboletaire.loc:/home/x/arbre"))
        self.assertIsNone(taller.web_url(None))
        have = lambda *names: (lambda b: b in names)  # noqa: E731
        self.assertEqual(taller.browser_cmd("u", have("wslview", "xdg-open")),
                         ["wslview", "u"])
        self.assertEqual(taller.browser_cmd("u", have("explorer.exe", "xdg-open")),
                         ["explorer.exe", "u"])
        self.assertEqual(taller.browser_cmd("u", have("xdg-open")), ["xdg-open", "u"])
        self.assertIsNone(taller.browser_cmd("u", have()))

    def test_branch_title_and_dir(self):
        self.assertEqual(taller.branch_title("feat/convert-images"), "Convert Images")
        self.assertEqual(taller.branch_title("fix/api_v2"), "Api V2")
        self.assertEqual(taller.branch_title("wsl"), "Wsl")
        self.assertEqual(taller.branch_title("user/x-y"), "User X Y")
        self.assertEqual(taller.worktree_dir("/r", "feat/a-b"), "/r/.worktrees/feat-a-b")

    def test_pane_of(self):
        self.assertEqual(taller.pane_of({"result": {"root_pane": {"pane_id": "w1:p1"}}}),
                         "w1:p1")
        self.assertEqual(taller.pane_of({"result": {"workspace": {
            "root_pane": {"pane_id": "w5:p1"}}}}), "w5:p1")
        self.assertIsNone(taller.pane_of({"result": {}}))
        self.assertIsNone(taller.pane_of(None))

    def test_resume_plan(self):
        with tempfile.TemporaryDirectory() as d:
            wt = os.path.join(d, "wt")
            os.makedirs(wt)
            p = project("alpha", d, last_exchange={"tool": "claude", "path": wt})
            plan = taller.resume_plan(p, "alpha", None, ["--model", "claude-haiku-5-5[1m]"])
            self.assertEqual(plan[0], ["herdr", "workspace", "create", "--label",
                                       "alpha", "--cwd", wt, "--focus"])
            self.assertEqual(plan[1][:8], ["herdr", "agent", "start", "alpha",
                                           "--kind", "claude", "--pane", "<pane>"])
            self.assertEqual(plan[1][-4:], ["--", "--model", "claude-haiku-5-5[1m]", "--continue"])
            # pi gets no claude args; a worktree that is gone falls back to
            # the project; an existing workspace gets a tab.
            p["last_exchange"] = {"tool": "pi", "path": os.path.join(d, "gone")}
            plan = taller.resume_plan(p, "alpha", "w7", ["--model", "claude-haiku-5-5[1m]"])
            self.assertEqual(plan[0], ["herdr", "tab", "create", "--workspace", "w7",
                                       "--cwd", d, "--label", "alpha", "--focus"])
            self.assertEqual(plan[1][5], "pi")
            self.assertEqual(plan[1][-2:], ["--", "--continue"])
            # No conversation: a plain claude.
            p["last_exchange"] = None
            self.assertNotIn("--", taller.resume_plan(p, "alpha")[1])

    def test_fresh_plan(self):
        p = project("beta", "/b")
        plan = taller.fresh_plan(p, "beta-2", "w3")
        self.assertEqual(plan[0][:5], ["herdr", "tab", "create", "--workspace", "w3"])
        self.assertEqual(plan[1][3], "beta-2")
        self.assertNotIn("--continue", plan[1])


class LaunchTest(TallerCase):
    """resume_project / fresh_agent / new_worktree against a fake herdr and
    real temp repos (alpha, beta from TallerCase)."""

    def setUp(self):
        super().setUp()
        self.state = os.path.join(self.t, "hstate")
        os.makedirs(self.state)
        self.log = os.path.join(self.t, "launch.log")
        s = self.state
        fake_bin(self.bin, "herdr", f"""printf '%s\\n' "herdr $*" >> {self.log}
case "$1 $2" in
  "agent list") cat {s}/agents.json ;;
  "workspace list") cat {s}/workspaces.json ;;
  "workspace create") echo '{{"result":{{"root_pane":{{"pane_id":"w9:p1"}}}}}}' ;;
  "tab create") echo '{{"result":{{"root_pane":{{"pane_id":"w2:p7"}}}}}}' ;;
  "worktree open") echo '{{"result":{{"workspace":{{"workspace_id":"w8"}},"root_pane":{{"pane_id":"w8:p1"}}}}}}' ;;
  "agent start") cat {s}/start.json; exit $(cat {s}/start.code) ;;
  "agent read") cat {s}/screen.txt ;;
  "agent send-keys"|"agent wait") echo '{{"result":{{}}}}' ;;
  *) exit 3 ;;
esac
""")
        self.herdr_agents([])
        self.workspaces([])
        self.start(0)
        write(os.path.join(s, "screen.txt"), "")
        for var in ("ARXIU_DRY_RUN", "TALLER_DRY_RUN"):
            os.environ.pop(var, None)

    def herdr_agents(self, rows):
        write(os.path.join(self.state, "agents.json"),
              json.dumps({"result": {"agents": rows}}))

    def workspaces(self, rows):
        write(os.path.join(self.state, "workspaces.json"),
              json.dumps({"result": {"workspaces": rows}}))

    def start(self, code, error=None):
        write(os.path.join(self.state, "start.json"),
              json.dumps({"error": {"code": error}}) if error else "{}")
        write(os.path.join(self.state, "start.code"), str(code))

    def mutating(self):
        try:
            with open(self.log) as fh:
                calls = fh.read().splitlines()
        except OSError:
            return []
        return [c for c in calls if not c.startswith((
            "herdr agent list", "herdr workspace list", "herdr agent read"))]

    def proj(self, **kw):
        kw.setdefault("remote", None)
        return project("beta", self.beta, **kw)

    def test_resume_starts_a_named_agent_with_continue(self):
        self.herdr_agents([{"name": "beta", "agent_status": "idle", "cwd": "/x",
                            "workspace_id": "w1", "pane_id": "w1:p1"}])
        p = self.proj(last_exchange={"tool": "claude", "path": self.beta})
        ok, msg, name = taller.resume_project(p, ["--model", "claude-haiku-5-5[1m]"])
        self.assertTrue(ok, msg)
        self.assertEqual(name, "beta-2")   # "beta" is taken
        self.assertEqual(self.mutating(), [
            f"herdr workspace create --label beta --cwd {self.beta} --focus",
            "herdr agent start beta-2 --kind claude --pane w9:p1 --timeout 60000 "
            "-- --model claude-haiku-5-5[1m] --continue"])

    def test_resume_goes_into_the_projects_workspace(self):
        self.workspaces([{"label": "beta", "workspace_id": "w4"}])
        ok, msg, _ = taller.resume_project(self.proj())
        self.assertTrue(ok, msg)
        self.assertEqual(self.mutating()[0],
                         f"herdr tab create --workspace w4 --cwd {self.beta} "
                         "--label beta --focus")

    def test_fresh_agent_in_a_tab_of_its_herdr_workspace(self):
        p = self.proj(agents=[agent("idle", name="beta", id="w5", path=self.beta)])
        ok, msg, name = taller.fresh_agent(p)
        self.assertTrue(ok, msg)
        self.assertEqual(self.mutating(), [
            f"herdr tab create --workspace w5 --cwd {self.beta} --label beta "
            "--focus",
            "herdr agent start beta --kind claude --pane w2:p7 --timeout 60000"])

    def test_new_worktree(self):
        run("git", "remote", "add", "origin", os.path.join(self.t, "nowhere.git"),
            cwd=self.beta)
        p = self.proj(remote="/nowhere.git")
        seen = []
        ok, msg, name = taller.new_worktree(p, "feat/new-thing", [], seen.append)
        self.assertTrue(ok, msg)
        self.assertIn("fetch ha fallat", msg)   # offline is only a warning
        wt = os.path.join(self.beta, ".worktrees", "feat-new-thing")
        self.assertTrue(os.path.isdir(wt))
        _, out, _ = taller.git(wt, "branch", "--show-current")
        self.assertEqual(out, "feat/new-thing")
        self.assertEqual(name, "feat-new-thing")
        self.assertEqual(self.mutating(), [
            f"herdr worktree open --cwd {self.beta} --path {wt} --label "
            "New Thing --focus",
            "herdr agent start feat-new-thing --kind claude --pane w8:p1 "
            "--timeout 60000"])
        self.assertTrue(any("git" in s for s in seen), seen)
        # The main checkout is untouched and still clean.
        self.assertEqual(taller.status(self.beta)["branch"], "main")
        self.assertEqual(taller.status(self.beta)["dirty"], 0)
        # Again: the branch exists now.
        ok, msg, _ = taller.new_worktree(p, "feat/new-thing")
        self.assertFalse(ok)
        self.assertIn("ja existeix", msg)

    def test_new_worktree_branches_off_origin_not_the_local_branch(self):
        # alpha's local main is a commit ahead of origin/main: the worktree
        # starts from origin/main, tracks nothing, and main stays as it was.
        p = project("alpha", self.alpha, remote="/alpha.git")
        _, local, _ = taller.git(self.alpha, "rev-parse", "main")
        _, origin, _ = taller.git(self.alpha, "rev-parse", "origin/main")
        ok, msg, _ = taller.new_worktree(p, "fix/z")
        self.assertTrue(ok, msg)
        wt = os.path.join(self.alpha, ".worktrees", "fix-z")
        _, head, _ = taller.git(wt, "rev-parse", "HEAD")
        self.assertEqual(head, origin)
        self.assertNotEqual(head, local)
        code, _, _ = taller.git(wt, "rev-parse", "--abbrev-ref", "@{upstream}")
        self.assertNotEqual(code, 0)
        _, after, _ = taller.git(self.alpha, "rev-parse", "main")
        self.assertEqual(after, local)

    def test_worktree_plan_falls_back_to_the_local_branch(self):
        # A remote without the current branch, and no remote at all.
        p = project("alpha", self.alpha, branch="feat/x", remote="/alpha.git")
        plan = taller.worktree_plan(p, "fix/z", "fix-z")
        wt = os.path.join(self.alpha, ".worktrees", "fix-z")
        self.assertEqual(plan[0][3], "fetch")
        self.assertEqual(plan[1], ["git", "-C", self.alpha, "worktree", "add",
                                   "-b", "fix/z", wt, "feat/x"])
        plan = taller.worktree_plan(self.proj(), "fix/z", "fix-z")
        self.assertEqual(plan[0][3:6], ["worktree", "add", "-b"])
        self.assertEqual(plan[0][-1], "main")

    def test_check_branch(self):
        p = self.proj()
        self.assertIsNone(taller.check_branch(p, "fix/x"))
        self.assertIn("no és un nom", taller.check_branch(p, "bad..name"))
        self.assertIn("no és un nom", taller.check_branch(p, "-x"))
        self.assertIn("ja existeix", taller.check_branch(p, "main"))
        self.assertIn("no és un repositori", taller.check_branch(
            self.proj(git=False), "x"))
        os.makedirs(os.path.join(self.beta, ".worktrees", "fix-y"))
        self.assertIn("ja existeix", taller.check_branch(p, "fix/y"))

    def test_trust_prompt_only_for_the_projects_folder(self):
        self.start(1, "agent_not_ready")
        write(os.path.join(self.state, "screen.txt"),
              "Do you trust this folder?\n> No, exit\n  Yes\n")
        ok, msg, name = taller.fresh_agent(self.proj())
        self.assertTrue(ok, msg)
        self.assertIn("confiança", msg)
        self.assertIn(f"herdr agent send-keys {name} down enter", self.mutating())
        # A dialog that is not the trust prompt stays for the user.
        open(self.log, "w").close()
        write(os.path.join(self.state, "screen.txt"), "Allow this MCP server?\n> Yes\n")
        ok, msg, _ = taller.fresh_agent(self.proj())
        self.assertFalse(ok)
        self.assertIn("Allow this MCP server", msg)
        self.assertFalse([c for c in self.mutating() if "send-keys" in c])

    def test_dry_run_says_and_runs_nothing(self):
        p = self.proj(last_exchange={"tool": "claude", "path": self.beta})
        with mock.patch.dict(os.environ, {"TALLER_DRY_RUN": "1"}):
            ok, msg, _ = taller.resume_project(p)
            self.assertTrue(ok)
            self.assertIn("dry-run: herdr workspace create --label beta", msg)
            self.assertIn("--continue", msg)
            ok, msg, _ = taller.new_worktree(p, "feat/z")
            self.assertTrue(ok)
            self.assertIn("git -C", msg)
            ok, msg, _ = taller.fresh_agent(p)
            self.assertTrue(ok)
            ok, msg = taller.focus(agent("idle", name="beta"))
            self.assertEqual(msg, "dry-run: herdr agent focus beta")
        self.assertEqual(self.mutating(), [])
        self.assertFalse(os.path.exists(os.path.join(self.beta, ".worktrees")))


class CliTest(TallerCase):
    """taller.py's subcommands, what the Taller orchestrator runs."""

    def cli(self, *argv):
        self.fakes()
        out = io.StringIO()
        with mock.patch.object(taller, "load_config", return_value=self.cfg), \
                mock.patch.object(sys, "stdout", out):
            code = taller.main(list(argv))
        return code, out.getvalue()

    def test_show_a_project_and_a_worktree(self):
        code, out = self.cli("show", "alpha")
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual((d["path"], d["branch"]), (self.alpha, "main"))
        self.assertEqual([a["name"] for a in d["agents"]], ["ha"])
        self.assertEqual(d["details"]["changes"], ["?? dirty.txt"])
        self.assertEqual([w["branch"] for w in d["worktrees"]], ["feat/x"])
        code, out = self.cli("show", "ALPHA", "--worktree", "feat-x")
        d = json.loads(out)
        self.assertEqual((d["path"], d["branch"]), (self.wt, "feat/x"))
        self.assertEqual([a["name"] for a in d["agents"]], ["alpha-wt"])

    def test_unknown_names_say_what_there_is(self):
        code, out = self.cli("show", "nope")
        self.assertEqual(code, 1)
        self.assertIn("alpha", out)
        code, out = self.cli("show", "alpha", "--worktree", "nope")
        self.assertEqual(code, 1)
        self.assertIn("feat/x", out)

    def test_sessions(self):
        code, out = self.cli("sessions")
        self.assertEqual(code, 0)
        self.assertIn("alpha-wt", out)
        self.assertIn("alpha ⑂ feat/x", out)
        self.assertIn("treballant", out)

    def test_actions_keep_the_focus_and_prompt_after(self):
        with mock.patch.dict(os.environ, {"TALLER_DRY_RUN": "1"}):
            code, out = self.cli("resume", "beta")
            self.assertEqual(code, 0)
            self.assertIn("--no-focus", out)
            self.assertNotIn("--focus ", out)
            code, out = self.cli("worktree", "beta", "feat/y", "--prompt",
                                 "fix it")
            self.assertEqual(code, 0)
            self.assertIn("git -C " + self.beta + " worktree add -b feat/y", out)
            self.assertIn("--no-focus", out)
            self.assertIn("dry-run: herdr agent prompt feat-y 'fix it'", out)
            code, out = self.cli("new", "alpha", "--worktree", "feat/x")
            self.assertIn(f"--cwd {self.wt}", out)
            code, out = self.cli("worktree", "alpha", "feat/z")
            self.assertIn("worktree add --no-track -b feat/z", out)
            self.assertIn("origin/main", out)
            code, out = self.cli("prompt", "ha", "hola")
            self.assertEqual(out.strip(), "dry-run: herdr agent prompt ha hola")
        self.assertFalse(os.path.exists(os.path.join(self.beta, ".worktrees")))

    def test_agent_args_go_after_the_configured_ones(self):
        self.cfg["taller"]["agent_args"] = ["--model", "haiku"]
        with mock.patch.dict(os.environ, {"TALLER_DRY_RUN": "1"}):
            for argv in (["new", "beta"], ["resume", "beta"],
                         ["worktree", "beta", "feat/y"]):
                code, out = self.cli(*argv, "--agent-args",
                                     "--model claude-sonnet-5-5 --advisor "
                                     "claude-opus-5-5")
                self.assertEqual(code, 0, out)
                self.assertIn("-- --model haiku --model claude-sonnet-5-5 "
                              "--advisor claude-opus-5-5", out)
            code, out = self.cli("new", "beta", "--agent-args=--verbose")
            self.assertIn("-- --model haiku --verbose", out)


class DetailsTest(TallerCase):
    def test_commits_and_changes(self):
        d = taller.details(self.alpha)
        self.assertEqual([c["subject"] for c in d["commits"]], ["ahead", "init"])
        self.assertTrue(d["commits"][0]["at"])
        self.assertEqual(d["changes"], ["?? dirty.txt"])
        self.assertEqual(d["changes_total"], 1)
        self.assertIsNone(d["error"])
        for i in range(12):
            write(os.path.join(self.alpha, f"n{i}.txt"), "x")
        d = taller.details(self.alpha, n_changes=8)
        self.assertEqual((len(d["changes"]), d["changes_total"]), (8, 13))

    def test_an_unstaged_change_keeps_its_leading_space(self):
        # " M" lists first: stripping the output would eat the path's first
        # letter once the columns shift.
        write(os.path.join(self.alpha, "a.txt"), "changed\n")
        d = taller.details(self.alpha)
        self.assertEqual(d["changes"], [" M a.txt", "?? dirty.txt"])

    def test_key_follows_head_and_index(self):
        p = project("alpha", self.alpha)
        k1 = taller.details_key(p)
        self.assertEqual(k1, taller.details_key(p))
        time.sleep(0.01)
        run("git", "add", "dirty.txt", cwd=self.alpha)
        k2 = taller.details_key(p)
        self.assertNotEqual(k1, k2)
        run("git", "commit", "-q", "-m", "more", cwd=self.alpha)
        self.assertNotEqual(k2, taller.details_key(p))

    def test_key_of_a_worktree_follows_its_head(self):
        p = project("feat/x", self.wt, branch="feat/x")
        k1 = taller.details_key(p)
        run("git", "add", ".", cwd=self.wt)
        run("git", "commit", "-q", "-m", "wt", cwd=self.wt)
        self.assertNotEqual(k1, taller.details_key(p))

    def test_broken_path(self):
        d = taller.details(os.path.join(self.t, "nope"))
        self.assertEqual(d["commits"], [])
        self.assertTrue(d["error"])


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
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.toml")
            write(path, '[taller]\nagent_args = ["--model", "claude-haiku-5-5[1m]"]\n')
            with mock.patch.dict(os.environ, {"TALLER_CONFIG": path,
                                              "ARXIU_CONFIG": "/nonexistent.toml"}):
                self.assertEqual(taller.load_config()["taller"]["agent_args"],
                                 ["--model", "claude-haiku-5-5[1m]"])
        cfg = taller.load_config(os.path.join(taller.HERE, "config.toml"))
        self.assertIn(os.path.expanduser("~/.dotfiles"), cfg["taller"]["extra"])
        self.assertEqual(cfg["taller"]["agent_args"], [])


if __name__ == "__main__":
    unittest.main()
