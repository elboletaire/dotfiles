"""Tests for board.py: the sections and rows it shows, the header, the
footer, the filter and the action keys (dry-run), plus a `--once --keys`
frame against a throwaway world. Needs rich:

    uv run --with rich python -m unittest discover -s ai/taller/tests
"""
import io
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from test_taller import TallerCase, agent, project, write  # noqa: E402

try:
    from rich.console import Console
    import board
except ImportError:          # bare python3: only the stdlib tests run
    board = None


@unittest.skipIf(board is None, "needs rich (uv run --with rich)")
class BoardCase(TallerCase):
    """A board over hand-made projects; alpha and beta are TallerCase's real
    repos, so the git keys have something to work on."""

    def setUp(self):
        super().setUp()
        # herdr runs only alpha's agent, so beta's name is free.
        self.herdr_out["result"]["agents"] = self.herdr_out["result"]["agents"][:1]
        self.fakes()
        for var in ("ARXIU_DRY_RUN", "TALLER_DRY_RUN"):
            os.environ.pop(var, None)
        now = int(time.time())
        self.cfg["ui"] = {"agents_secs": 3, "git_secs": 20}
        self.model = board.Model(self.cfg)
        self.model.sync = True
        self.model.projects = [
            project("alpha", self.alpha, last_touch=now - 60, agents=[
                agent("waiting", name="ha", path=self.alpha),
                agent("working", name="alpha-wt", path=self.wt, id="w2")],
                flags=["unpushed"], ahead=1,
                worktrees=[{"path": self.wt, "branch": "feat/x", "dirty": 2,
                            "ahead": None}],
                exchanges={self.alpha: None, self.wt: {
                    "tool": "claude", "path": self.wt, "user": "wt q",
                    "agent": "wt a", "title": "WT", "at": now - 60}}),
            project("beta", self.beta, remote=None, flags=["no_remote"],
                    last_touch=now - 7200,
                    last_exchange={"tool": "claude", "path": self.beta,
                                   "user": "hola", "agent": "adéu",
                                   "title": "Salutacions", "at": now - 7200}),
            project("busy", "/nowhere/busy", last_touch=now - 30, agents=[
                agent("working", name="busy")]),
            project("plain", "/nowhere/plain", git=False, remote=None,
                    branch=None, flags=["no_git"], last_touch=now - 100),
            project("old", "/nowhere/old", dormant=True,
                    last_touch=now - 90 * 86400, flags=["dormant"]),
            project("older", "/nowhere/older", dormant=True,
                    last_touch=now - 200 * 86400, flags=["dormant"]),
        ]
        self.b = board.Board(self.model, Console(width=150, height=40,
                                                 force_terminal=True))
        # An action's thread must finish while the fake herdr is still on
        # PATH: cleanups run last-in first-out, so this one runs first.
        self.addCleanup(self.wait)
        self.b.render()

    def text(self, renderable=None, width=150, height=40):
        console = Console(width=width, height=height, record=True,
                          file=io.StringIO())
        console.print(renderable if renderable is not None
                      else self.b.render())
        return console.export_text()

    def go(self, name):
        self.b.cursor = next(p["path"] for p in self.model.projects
                             if p["name"] == name)
        self.b.build_rows()

    def go_path(self, path):
        self.b.cursor = path
        self.b.build_rows()

    def keys(self, seq):
        for k in board.split_keys(seq):
            self.b.handle(k, None, None)

    def wait(self):
        deadline = time.time() + 15
        while self.b.busy and time.time() < deadline:
            time.sleep(0.02)

    def dry(self):
        return mock.patch.dict(os.environ, {"TALLER_DRY_RUN": "1"})


class ListTest(BoardCase):
    def test_sections_in_order_and_dormant_collapsed(self):
        rows = [(r[0], r[1] if r[0] == "head" else
                 r[1]["name"] if r[0] == "project" else
                 r[2]["branch"] if r[0] == "worktree" else len(r[1]))
                for r in self.b.rows]
        self.assertEqual(rows, [
            ("head", "need"), ("project", "alpha"), ("worktree", "feat/x"),
            ("head", "working"), ("project", "busy"),
            ("head", "parked"), ("project", "plain"), ("project", "beta"),
            ("head", "dormant"), ("dormant", 2)])
        self.assertEqual(self.b.project()["name"], "alpha")
        self.keys("d")
        self.b.build_rows()
        self.assertEqual([r[1]["name"] for r in self.b.rows
                          if r[0] == "project"][-2:], ["old", "older"])
        self.assertIn("amaga adormits", self.b.footer().plain)

    def test_header_counts_and_backup_warning(self):
        head = self.b.header(150).plain
        self.assertIn("🔴 1", head)
        self.assertIn("🟡 1", head)
        self.assertIn("💤 2", head)
        self.assertIn("⚠ 2 projectes sense còpia", head)

    def test_rows_show_agents_and_flags(self):
        out = self.text()
        self.assertIn("Et necessita (1)", out)
        self.assertIn("Aparcats (2)", out)
        self.assertIn("old, older", out)
        beta = next(ln for ln in out.splitlines() if " beta " in ln)
        self.assertIn("⚠", beta)
        self.assertIn("sense git", next(ln for ln in out.splitlines()
                                        if " plain " in ln))

    def test_worktree_rows_sit_under_their_project(self):
        lines = self.text(self.b.list_panel(100, 30), 100).splitlines()
        i = next(i for i, ln in enumerate(lines) if " alpha " in ln)
        self.assertIn("└ feat-x", lines[i + 1])
        self.assertIn("feat/x", lines[i + 1])
        self.assertIn("✎2", lines[i + 1])
        self.assertIn("◐", lines[i + 1])        # its own agent
        self.assertNotIn("✎2", lines[i])        # not the main checkout's
        self.assertNotIn("◐", lines[i])

    def test_moving_skips_heads(self):
        self.keys("j")
        self.assertEqual(self.b.cursor, self.wt)
        self.assertEqual(self.b.selected()["branch"], "feat/x")
        self.assertEqual(self.b.project()["name"], "alpha")
        self.keys("j")
        self.assertEqual(self.b.project()["name"], "busy")
        self.keys("jjj")
        self.assertEqual(self.b.project()["name"], "beta")
        self.keys("\x1b[5~")
        self.assertEqual(self.b.project()["name"], "alpha")

    def test_filter(self):
        self.keys("/be")
        self.assertEqual(self.b.filter, "be")
        self.b.build_rows()
        self.assertEqual([r[1]["name"] for r in self.b.rows
                          if r[0] == "project"], ["beta"])
        self.keys("\r")
        self.assertIsNone(self.b.input)
        self.assertEqual(self.b.filter, "be")
        self.keys("/\x1b")
        self.assertEqual(self.b.filter, "")
        # A filter looks into the dormant ones too.
        self.keys("/olde\r")
        self.b.build_rows()
        self.assertEqual([r[1]["name"] for r in self.b.rows
                          if r[0] == "project"], ["older"])

    def test_detail(self):
        self.go("beta")
        out = self.text(self.b.detail_panel(self.b.project(), 70, 40), 70)
        self.assertIn("sense remot", out)
        self.assertIn("cap · ⏎ reprèn l'última conversa a herdr", out)
        self.assertIn("«Salutacions»", out)
        self.assertIn("tu    hola", out)
        self.assertIn("agent adéu", out)
        self.assertIn("init", out)          # a commit, read lazily
        self.go("alpha")
        out = self.text(self.b.detail_panel(self.b.project(), 70, 40), 70)
        self.assertIn("?? dirty.txt", out)
        self.assertIn("↑1 per pujar", out)

    def test_detail_follows_the_worktree(self):
        self.go_path(self.wt)
        out = self.text(self.b.detail_panel(self.b.selected(), 70, 40), 70)
        self.assertIn("alpha ⑂ feat/x", out)
        self.assertIn("alpha-wt", out)
        self.assertNotIn(" ha ", out)
        self.assertIn("«WT»", out)
        self.assertIn("tu    wt q", out)
        self.assertIn("?? w1.txt", out)          # the worktree's own changes

    def test_narrow_puts_the_detail_below(self):
        self.b.console = Console(width=90, height=40, force_terminal=True)
        lines = self.text(self.b.render(), 90).splitlines()
        top = next(i for i, ln in enumerate(lines) if "Projectes" in ln)
        detail = next(i for i, ln in enumerate(lines) if "─ alpha " in ln)
        self.assertGreater(detail, top + 3)

    def test_column_stacks_even_when_wide_and_fits_the_list(self):
        # herdr frames the pane: the sections are title lines, not boxes.
        with mock.patch.object(board, "COLUMN", True):
            lines = self.text(self.b.render(), 150, 60).splitlines()
        self.assertFalse(any("╭" in ln or "│" in ln for ln in lines))
        top = next(i for i, ln in enumerate(lines)
                   if ln.startswith("📂 Projectes ─"))
        detail = next(i for i, ln in enumerate(lines)
                      if ln.startswith("alpha ─"))
        # Below the list, right after its rows rather than halfway down.
        self.assertEqual(detail - top, len(self.b.rows) + 3)
        self.assertTrue(lines[top + 1].startswith(" 🔴"))   # indented by one

    def test_footer_follows_the_project(self):
        foot = self.b.footer().plain
        self.assertIn("⏎ → ha", foot)
        self.assertIn("w worktree", foot)
        self.assertIn("o web", foot)
        self.go("beta")
        foot = self.b.footer().plain
        self.assertIn("⏎ reprèn a herdr", foot)
        self.assertNotIn("o web", foot)
        self.go("plain")
        self.assertNotIn("w worktree", self.b.footer().plain)


class ActTest(BoardCase):
    def test_enter_focuses_the_herdr_agent(self):
        with self.dry():
            self.keys("\r")
            self.wait()
        self.assertEqual(self.b.flash[0], "dry-run: herdr agent focus ha")

    def test_enter_without_herdr_agent_asks_then_resumes(self):
        self.go("beta")
        with self.dry():
            self.keys("\r")
            self.assertIn("prem ⏎ de nou per obrir beta a herdr: claude "
                          "--continue («Salutacions»)", self.b.confirm["msg"])
            self.keys("\r")
            self.wait()
        msg = self.b.flash[0]
        self.assertIn("herdr workspace create --label beta", msg)
        self.assertIn("agent start beta --kind claude", msg)
        self.assertIn("--continue", msg)

    def test_enter_on_a_worktree_focuses_its_agent(self):
        self.go_path(self.wt)
        with self.dry():
            self.keys("\r")
            self.wait()
        self.assertEqual(self.b.flash[0], "dry-run: herdr agent focus alpha-wt")

    def test_enter_on_a_worktree_without_agent_resumes_there(self):
        alpha = self.model.projects[0]
        alpha["agents"] = alpha["agents"][:1]
        self.go_path(self.wt)
        with self.dry():
            self.keys("\r")
            self.assertIn("prem ⏎ de nou per obrir feat-x a herdr: claude "
                          "--continue («WT»)", self.b.confirm["msg"])
            self.keys("\r")
            self.wait()
        msg = self.b.flash[0]
        self.assertIn(f"herdr worktree open --cwd {self.alpha} --path "
                      f"{self.wt}", msg)
        self.assertIn("agent start feat-x --kind claude", msg)

    def test_v_shows_the_agent_in_a_popup(self):
        with mock.patch.object(board, "DRY_RUN", True):
            self.keys("v")
            self.assertIn("--entrypoint agent", self.b.flash[0])
            self.assertIn("--env TALLER_AGENT=ha", self.b.flash[0])
            # Titled as the row is in the list.
            self.assertIn("herdr pane rename '<popup>' alpha", self.b.flash[0])
            self.go_path(self.wt)
            self.keys("v")
            self.assertIn("--env TALLER_AGENT=alpha-wt", self.b.flash[0])
            self.assertIn("herdr pane rename '<popup>' feat-x", self.b.flash[0])
        # No session yet: its last conversation resumes in the background
        # (no focus taken, no second press), then the popup opens on it.
        self.go("beta")
        self.assertIn("v mostra", self.b.footer().plain)
        with self.dry(), mock.patch.object(board, "DRY_RUN", True):
            self.keys("v")
            self.wait()
        msg = self.b.flash[0]
        self.assertIn("herdr workspace create --label beta", msg)
        self.assertIn("--no-focus", msg)
        self.assertNotIn("--focus ", msg)
        self.assertIn("--continue", msg)
        self.assertIn("--entrypoint agent", msg)
        self.assertIn("--env TALLER_AGENT=beta", msg)
        self.assertIsNone(self.b.confirm)

    def test_first_pane_id(self):
        self.assertEqual(board.first_pane_id({"plugin_pane": {
            "entrypoint": "agent", "pane": {"pane_id": "w1:p3"}}}), "w1:p3")
        self.assertIsNone(board.first_pane_id({"type": "ok"}))

    def test_quit_asks_first(self):
        self.assertTrue(self.b.handle("q", None, None))
        self.assertIn("prem q o ctrl-c de nou", self.b.confirm["msg"])
        self.assertFalse(self.b.handle("q", None, None))

    def test_ctrl_c_asks_first_too(self):
        self.assertTrue(self.b.handle("\x03", None, None))
        self.assertFalse(self.b.handle("\x03", None, None))

    def test_quit_is_dropped_by_another_key(self):
        self.keys("q")
        self.keys("\x1b")
        self.assertTrue(self.b.handle("q", None, None))

    def test_moving_drops_the_confirmation(self):
        self.go("beta")
        self.keys("n")
        self.assertIsNotNone(self.b.confirm)
        self.keys("k")
        self.assertIsNone(self.b.confirm)

    def test_new_agent_asks_first(self):
        self.go("beta")
        with self.dry():
            self.keys("n")
            self.assertIn("prem n de nou", self.b.confirm["msg"])
            self.keys("n")
            self.wait()
        self.assertIn("agent start beta --kind claude", self.b.flash[0])
        self.assertNotIn("--continue", self.b.flash[0])

    def test_worktree_asks_a_branch_then_confirms(self):
        self.go("beta")
        with self.dry():
            self.keys("w")
            self.assertEqual(self.b.input["kind"], "branch")
            self.keys("main\r")       # exists already
            self.assertIn("ja existeix", self.b.flash[0])
            self.assertIsNone(self.b.confirm)
            self.keys("wfeat/x-y\r")
            self.assertIn("prem w de nou per crear el worktree feat/x-y",
                          self.b.confirm["msg"])
            self.assertNotIn("git fetch", self.b.confirm["preview"])
            self.keys("w")
            self.wait()
        self.assertIn("git -C " + self.beta + " worktree add -b feat/x-y",
                      self.b.flash[0])
        self.assertFalse(os.path.exists(os.path.join(self.beta, ".worktrees")))

    def test_popups_and_web_in_dry_run(self):
        with mock.patch.object(board, "DRY_RUN", True):
            self.keys("t")
            self.assertIn("--entrypoint shell", self.b.flash[0])
            self.assertIn(f"--cwd {self.alpha}", self.b.flash[0])
            self.keys("o")
            self.assertIn("https://github.com/o/p", self.b.flash[0])


@unittest.skipIf(board is None, "needs rich (uv run --with rich)")
class OnceTest(TallerCase):
    """board.py --once --keys, as taller.sh would run it, on TallerCase's
    world (fake herdr, temp HOME)."""

    def test_frame_and_keys(self):
        self.fakes()
        cfg = os.path.join(self.t, "config.toml")
        write(cfg, f'[taller]\nroots = ["{self.src}"]\nextra = ["{self.extra}"]\n'
                   'hide = ["hidden"]\n')
        env = dict(os.environ, TALLER_CONFIG=cfg, TALLER_DRY_RUN="1",
                   COLUMNS="140", LINES="40")
        env.pop("ARXIU_CONFIG", None)
        out = subprocess.run(
            [sys.executable, os.path.join(board.DIR, "board.py"), "--once",
             "--keys", "/beta\\r\\rn"],
            env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        text = out.stdout
        self.assertIn("Projectes", text)
        self.assertIn("beta", text)
        self.assertIn("filtre «beta»", text)
        self.assertIn("prem n de nou", text)


if __name__ == "__main__":
    unittest.main()
