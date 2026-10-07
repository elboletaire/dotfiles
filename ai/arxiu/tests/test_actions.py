"""Tests for actions.py: the catalogue per selection kind, the prompts it
builds on a fictional tree (people_fixture.py), and running them against a
fake `herdr` (fake_herdr.py), queue included."""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import actions  # noqa: E402
import arbre_data  # noqa: E402
import people  # noqa: E402
import people_fixture  # noqa: E402
import research_queue  # noqa: E402
from fake_herdr import HerdrCase  # noqa: E402

CFG = {"arbre": {"path": "/t", "orchestrator_agent": "orq",
                 "research_agent": "inv",
                 "research_skill": "genealogy-research",
                 "interview_skill": "family-interview"}}


def sel(kind, **kw):
    out = {"kind": kind, "family": None, "branch": None, "person": None,
           "item": None}
    out.update(kw)
    return out


class TreeCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = os.path.join(os.path.realpath(cls.tmp.name), "arbre")
        people_fixture.build(root, time.time())
        cls.arbre = arbre_data.load(root)
        cls.people = people.load(root, cls.arbre)
        cls.row = next(r for r in cls.arbre["rows"]
                       if r["title"] == "Ferrer y Soler")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def person(self, slug):
        return self.people["persons"][slug]


class CatalogueTest(unittest.TestCase):
    def test_keys_per_kind(self):
        keys = {k: [a["key"] for a in actions.catalogue(k)]
                for k in ("family", "branch", "person", "item")}
        self.assertEqual(keys, {"family": ["r", "R"], "branch": ["r", "R"],
                                "person": ["r", "R", "e", "E"],
                                "item": ["i", "I"]})
        self.assertEqual(actions.catalogue(None), [])

    def test_case_picks_the_mode(self):
        for kind, key in (("family", "r"), ("person", "e"), ("item", "i")):
            self.assertEqual(actions.find(kind, key)["mode"], "prefill")
            self.assertEqual(actions.find(kind, key.upper())["mode"], "send")
        self.assertIsNone(actions.find("family", "e"))
        self.assertIsNone(actions.find("item", "r"))


class PromptTest(TreeCase):
    def test_family(self):
        p = actions.build(CFG, self.arbre, sel("family", family="ferrer"), "r")
        text = p["prompt"]
        for part in ("skill genealogy-research", "Familia Ferrer",
                     "Ferrer (`ferrer`)", "Soler (`soler`)", "Puig (`puig`)",
                     "recerca/pendientes.md", "recerca/incoherencias.md",
                     "`uv run scripts/lookup.py rama/ferrer rama/soler "
                     "rama/puig`"):
            self.assertIn(part, text)
        self.assertNotIn("rama/otras", text)
        self.assertNotIn("\n", text)
        self.assertEqual((p["mode"], p["agent"], p["target"]),
                         ("prefill", "orq", "ferrer"))

    def test_branch_row(self):
        s = sel("branch", family="ferrer", branch="ferrer",
                row=self.row["id"], branches=["ferrer", "soler"])
        p = actions.build(CFG, self.arbre, s, "r")
        self.assertIn("la branca «Ferrer y Soler» de la Familia Ferrer",
                      p["prompt"])
        self.assertIn("`uv run scripts/lookup.py rama/ferrer rama/soler`",
                      p["prompt"])
        self.assertIn("2 pendents", p["prompt"])
        self.assertEqual(p["label"], "investigar Ferrer y Soler")

    def test_branch_without_row_id(self):
        p = actions.build(CFG, self.arbre, sel("branch", family="ferrer",
                                              branch="puig"), "r")
        self.assertIn("«Puig»", p["prompt"])

    def test_person_research_only_them(self):
        s = sel("person", family="ferrer", branch="ferrer",
                person="jaume-ferrer")
        p = actions.build(CFG, self.arbre, s, "r",
                          person=self.person("jaume-ferrer"))
        text = p["prompt"]
        self.assertIn("skill genealogy-research", text)
        self.assertIn("només Jaume Ferrer (n. 1850) (`jaume-ferrer`)", text)
        self.assertIn("rama Ferrer (`ferrer`) de la Familia Ferrer", text)
        self.assertIn("`uv run scripts/lookup.py jaume-ferrer`", text)
        self.assertEqual(p["target"], "jaume-ferrer")

    def test_person_interview(self):
        s = sel("person", family="ferrer", branch="puig",
                person="rosa-puig-vidal")
        p = actions.build(CFG, self.arbre, s, "e",
                          person=self.person("rosa-puig-vidal"))
        text = p["prompt"]
        self.assertIn("skill family-interview", text)
        self.assertIn("Rosa Puig Vidal", text)
        self.assertIn("`rosa-puig-vidal`", text)
        self.assertIn("rama Puig (`puig`)", text)
        self.assertIn("és el familiar a qui farem les preguntes", text)
        self.assertIn("només la llista numerada de preguntes", text)
        self.assertIn("No registris res encara", text)
        self.assertIn("lookup.py --family rosa-puig-vidal", text)
        self.assertNotIn("genealogy-research", text)
        self.assertEqual(p["label"], "entrevista a Rosa Puig Vidal")

    def test_person_without_record_uses_the_slug(self):
        p = actions.build(CFG, self.arbre, sel("person", family="ferrer",
                                              person="nn-vidal"), "e")
        self.assertIn("entrevista a nn-vidal (`nn-vidal`)", p["prompt"])

    def test_item(self):
        item = next(it for its in self.row["pending"].values() for it in its)
        s = sel("item", family="ferrer", branch="ferrer", row=self.row["id"],
                item=item)
        p = actions.build(CFG, self.arbre, s, "i")
        self.assertIn("investigar aquest punt pendent", p["prompt"])
        self.assertIn("Branca: Ferrer y Soler (Familia Ferrer)", p["prompt"])
        self.assertIn(f"«{item['title']}»", p["prompt"])
        self.assertIn("lookup.py rama/ferrer rama/soler", p["prompt"])
        refs = people.item_refs(self.people, item)
        p = actions.build(CFG, self.arbre, s, "I",
                          refs=refs["people"] + refs["sources"])
        if refs["people"]:
            self.assertIn("lookup.py " + refs["people"][0], p["prompt"])
        self.assertEqual(p["target"], f"pendientes.md:{item['line']}")

    def test_uppercase_goes_to_the_research_agent(self):
        s = sel("person", family="ferrer", branch="ferrer",
                person="jaume-ferrer")
        low = actions.build(CFG, self.arbre, s, "r")
        up = actions.build(CFG, self.arbre, s, "R")
        self.assertEqual((up["mode"], up["agent"]), ("send", "inv"))
        self.assertEqual(up["prompt"], low["prompt"])
        self.assertIsNone(actions.build(CFG, self.arbre, s, "x"))


class RunTest(HerdrCase, TreeCase):
    def plan(self, key):
        s = sel("person", family="ferrer", branch="ferrer",
                person="jaume-ferrer")
        cfg = dict(self.cfg, arbre=dict(CFG["arbre"], path=self.tree_root))
        return cfg, actions.build(cfg, self.arbre, s, key)

    @property
    def tree_root(self):
        return self.arbre["path"]

    def test_prefill_types_into_the_orchestrator_and_queues(self):
        self.agent("orq", "idle", pane="w1:p2")
        cfg, plan = self.plan("r")
        ok, msg = actions.run(cfg, plan)
        self.assertTrue(ok, msg)
        self.assertEqual(self.calls()[-2],
                         ["pane", "send-text", "w1:p2", plan["prompt"]])
        self.assertEqual(self.calls()[-1], ["agent", "focus", "orq"])
        q = research_queue.load()
        self.assertEqual([(e["mode"], e["agent"], e["status"], e["target"])
                          for e in q],
                         [("prefill", "orq", "prefilled", "jaume-ferrer")])

    def test_busy_orchestrator_gets_nothing_and_nothing_is_queued(self):
        self.agent("orq", "working")
        cfg, plan = self.plan("r")
        ok, msg = actions.run(cfg, plan)
        self.assertFalse(ok)
        self.assertEqual(self.mutating(), [])
        self.assertEqual(research_queue.load(), [])

    def test_send_prompts_the_research_agent_and_queues(self):
        self.agent("inv", "idle")
        cfg, plan = self.plan("R")
        ok, msg = actions.run(cfg, plan)
        self.assertTrue(ok, msg)
        self.assertEqual(self.calls()[-1],
                         ["agent", "prompt", "inv", plan["prompt"]])
        self.assertEqual([(e["mode"], e["status"])
                          for e in research_queue.load()],
                         [("send", "sent")])

    def test_dry_run_queues_nothing(self):
        self.agent("orq", "idle")
        cfg, plan = self.plan("r")
        with mock.patch.dict(os.environ, {"ARXIU_DRY_RUN": "1"}):
            ok, msg = actions.run(cfg, plan)
        self.assertTrue(ok)
        self.assertTrue(msg.startswith("dry-run: herdr pane send-text"))
        self.assertEqual(self.mutating(), [])
        self.assertEqual(research_queue.load(), [])

    def test_empty_agent_name(self):
        cfg, plan = self.plan("r")
        plan["agent"] = ""
        ok, msg = actions.run(cfg, plan)
        self.assertFalse(ok)
        self.assertIn("orchestrator_agent", msg)


if __name__ == "__main__":
    unittest.main()
