"""Tests for agents.py against a fake `herdr` on PATH (fake_herdr.py)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import agents  # noqa: E402
from fake_herdr import HerdrCase, write  # noqa: E402

PROMPT = "Fes servir la skill genealogy-research per investigar «X» (`x`)."


class PrefillTest(HerdrCase):
    def test_types_without_enter_then_focuses(self):
        self.agent("orq", "idle", pane="w1:p2")
        ok, msg = agents.prefill("orq", PROMPT)
        self.assertTrue(ok, msg)
        self.assertEqual(self.mutating(), [
            "pane send-text w1:p2 " + PROMPT,
            "agent focus orq"])
        # The exact argv: the prompt is one argument, and no key is pressed.
        self.assertEqual(self.calls()[-2],
                         ["pane", "send-text", "w1:p2", PROMPT])
        self.assertFalse([c for c in self.calls()
                          if "enter" in c or c[:2] == ["agent", "prompt"]])

    def test_newlines_become_spaces(self):
        self.agent("orq", "done")
        ok, _ = agents.prefill({"name": "orq"}, "primera línia\n  segona")
        self.assertTrue(ok)
        self.assertEqual(self.calls()[-2][-1], "primera línia segona")

    def test_working_or_blocked_gets_nothing(self):
        for status, words in (("working", "està treballant"),
                              ("blocked", "espera una resposta")):
            self.agent("orq", status)
            ok, msg = agents.prefill("orq", PROMPT)
            self.assertFalse(ok)
            self.assertIn(words, msg)
        self.assertEqual(self.mutating(), [])

    def test_missing_agent(self):
        ok, msg = agents.prefill("orq", PROMPT)
        self.assertFalse(ok)
        self.assertIn("no corre", msg)
        self.assertEqual(self.mutating(), [])

    def test_dry_run_reads_but_runs_nothing(self):
        self.agent("orq", "idle", pane="w1:p2")
        with mock.patch.dict(os.environ, {"ARXIU_DRY_RUN": "1"}):
            ok, msg = agents.prefill("orq", "hola món")
        self.assertTrue(ok)
        self.assertEqual(msg, "dry-run: herdr pane send-text w1:p2 "
                         "'hola món' ; herdr agent focus orq")
        self.assertEqual(self.mutating(), [])


class PromptTest(HerdrCase):
    def test_prompt_submits(self):
        self.agent("inv", "working")
        ok, msg = agents.prompt("inv", PROMPT)
        self.assertTrue(ok, msg)
        self.assertEqual(self.calls()[-1], ["agent", "prompt", "inv", PROMPT])

    def test_blocked_gets_nothing(self):
        self.agent("inv", "blocked")
        ok, msg = agents.prompt("inv", PROMPT)
        self.assertFalse(ok)
        self.assertEqual(self.mutating(), [])

    def test_focus_and_dry_run(self):
        ok, _ = agents.focus({"name": "inv", "pane": "w1:p1"})
        self.assertTrue(ok)
        self.assertEqual(self.mutating(), ["agent focus inv"])
        with mock.patch.dict(os.environ, {"ARXIU_DRY_RUN": "1"}):
            self.assertEqual(agents.focus("inv"),
                             (True, "dry-run: herdr agent focus inv"))
            self.assertEqual(agents.prompt("inv", "hi"),
                             (True, "dry-run: herdr agent prompt inv hi"))
        self.assertEqual(self.mutating(), ["agent focus inv"])


class ListTest(HerdrCase):
    def test_list_and_tree_agents(self):
        self.agent("orq", "blocked", pane="w1:p2")
        self.agent("other", "working", pane="w3:p1", cwd="/elsewhere")
        found = agents.list_agents()
        self.assertEqual({a["name"]: a["state"] for a in found},
                         {"orq": "waiting", "other": "working"})
        self.assertEqual([a["name"] for a in agents.tree_agents(self.cfg,
                                                                found)],
                         ["orq"])
        a = agents.get_agent("orq")
        self.assertEqual((a["pane"], a["host"], a["id"]),
                         ("w1:p2", "herdr", "w1"))

    def test_strict_tells_failure_from_none(self):
        os.remove(os.path.join(self.bin, "herdr"))
        write(os.path.join(self.bin, "herdr"), "#!/bin/sh\nexit 1\n")
        os.chmod(os.path.join(self.bin, "herdr"), 0o755)
        self.assertEqual(agents.list_agents(), [])
        self.assertIsNone(agents.list_agents(strict=True))


class ResearchTest(HerdrCase):
    """prompt_research, as the board's uppercase actions use it."""

    def test_running_agent_is_prompted(self):
        self.agent("inv", "idle")
        ok, msg = agents.prompt_research(self.cfg, "hola món")
        self.assertTrue(ok, msg)
        self.assertEqual(self.mutating(), ["agent prompt inv hola món"])

    def test_blocked_agent_gets_nothing(self):
        self.agent("inv", "blocked")
        ok, msg = agents.prompt_research(self.cfg, "hola")
        self.assertFalse(ok)
        self.assertIn("espera una resposta", msg)
        self.assertEqual(self.mutating(), [])

    def test_missing_agent_starts_in_a_tab_of_arxiu(self):
        seen = []
        ok, msg = agents.prompt_research(self.cfg, "hola", seen.append)
        self.assertTrue(ok, msg)
        self.assertEqual(self.mutating(), [
            f"tab create --workspace w2 --cwd {self.tree} --label inv "
            "--env ARXIU_ROLE=research --no-focus",
            "agent start inv --kind claude --pane w2:p7 --timeout 60000 "
            "-- --model claude-haiku-5-5[1m]",
            "agent prompt inv hola"])
        self.assertTrue(any("engegant inv" in s for s in seen), seen)

    def test_without_arxiu_workspace_it_gets_its_own(self):
        self.workspaces([{"label": "other", "workspace_id": "w1"}])
        ok, _ = agents.prompt_research(self.cfg, "hola")
        self.assertTrue(ok)
        self.assertEqual(self.mutating()[0],
                         f"workspace create --label inv --cwd {self.tree} "
                         "--env ARXIU_ROLE=research --no-focus")

    def test_trust_prompt_in_the_tree_is_accepted(self):
        self.start(1, "agent_not_ready")
        write(os.path.join(self.state, "screen.txt"),
              "Do you trust this folder?\n> No, exit\n  Yes\n")
        ok, msg = agents.prompt_research(self.cfg, "hola")
        self.assertTrue(ok, msg)
        calls = self.mutating()
        self.assertIn("agent send-keys inv down enter", calls)
        self.assertEqual(calls[-1], "agent prompt inv hola")

    def test_other_dialogs_are_left_for_the_user(self):
        self.start(1, "agent_not_ready")
        write(os.path.join(self.state, "screen.txt"),
              "Allow this MCP server?\n> Yes\n  No\n")
        ok, msg = agents.prompt_research(self.cfg, "hola")
        self.assertFalse(ok)
        self.assertIn("Allow this MCP server", msg)
        self.assertFalse([c for c in self.mutating()
                          if "send-keys" in c or "prompt" in c])

    def test_trust_outside_the_tree_is_refused(self):
        write(os.path.join(self.state, "screen.txt"), "trust this folder")
        self.assertFalse(agents.accept_trust("inv", self.t, self.tree))
        self.assertTrue(agents.accept_trust("inv", self.tree + "/x",
                                            self.tree))

    def test_dry_run_says_and_runs_nothing(self):
        with mock.patch.dict(os.environ, {"ARXIU_DRY_RUN": "1"}):
            ok, msg = agents.prompt_research(self.cfg, "hola")
            self.assertTrue(ok)
            self.assertIn("herdr tab create --workspace w2", msg)
            self.assertIn("herdr agent start inv --kind claude --pane "
                          "'<pane>'", msg)
            self.assertIn("herdr agent prompt inv hola", msg)
            self.agent("inv", "idle")
            ok, msg = agents.prompt_research(self.cfg, "hola")
            self.assertEqual(msg, "dry-run: herdr agent prompt inv hola")
        self.assertEqual(self.mutating(), [])


class ConfigTest(unittest.TestCase):
    def test_defaults_and_expansion(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.toml")
            write(path, '[arbre]\npath = "~/x"\n[taller]\nroots = []\n')
            with mock.patch.dict(os.environ, {"HOME": "/h"}):
                cfg = agents.load_config(path)
        self.assertEqual(cfg["arbre"]["path"], "/h/x")
        self.assertEqual(cfg["arbre"]["orchestrator_agent"], "arbre")
        self.assertEqual(cfg["arbre"]["interview_skill"], "family-interview")
        self.assertEqual(cfg["ui"]["agents_secs"], 3)

    def test_env_and_shipped_config(self):
        with mock.patch.dict(os.environ, {"ARXIU_CONFIG": "/nonexistent"}):
            self.assertEqual(agents.load_config()["arbre"]["research_agent"],
                             "investigacio")
        cfg = agents.load_config(os.path.join(agents.HERE, "config.toml"))
        self.assertNotIn("taller", cfg)
        self.assertEqual(cfg["arbre"]["research_skill"], "genealogy-research")


if __name__ == "__main__":
    unittest.main()
