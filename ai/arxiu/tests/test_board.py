"""Tests for board.py's list (families -> branches -> people and items),
the selection it hands to panel.py, its footer and its action keys, on the
fictional tree of people_fixture.py. Needs rich:

    uv run --with rich python -m unittest discover -s tests
"""
import io
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import people_fixture  # noqa: E402
from fake_herdr import HerdrCase  # noqa: E402

try:
    from rich.console import Console
    import board
except ImportError:          # bare python3: only the stdlib tests run
    board = None


@unittest.skipIf(board is None, "needs rich (uv run --with rich)")
class BoardCase(HerdrCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_tree = tempfile.TemporaryDirectory()
        cls.root = os.path.join(os.path.realpath(cls.tmp_tree.name), "arbre")
        people_fixture.build(cls.root, time.time())

    @classmethod
    def tearDownClass(cls):
        cls.tmp_tree.cleanup()

    def setUp(self):
        super().setUp()
        self.cfg["arbre"]["path"] = self.root
        self.model = board.Model(self.cfg)
        self.model.load_tree()
        self.b = board.Board(self.model, Console(width=140, height=40,
                                                 force_terminal=True))
        self.b.render()

    def go(self, node_id):
        self.b.cursor = node_id
        self.b.refresh_nodes()
        self.assertEqual(self.b.cursor, node_id)

    def ids(self):
        return [n["id"] for n in self.b.nodes]


class ListTest(BoardCase):
    def test_families_open_rows_closed(self):
        kinds = [n["kind"] for n in self.b.nodes]
        self.assertEqual(kinds[0], "family")
        self.assertNotIn("person", kinds)
        self.assertNotIn("item", kinds)
        self.assertTrue(self.b.cursor.startswith("r:"))
        self.assertEqual(self.b.selection()["kind"], "branch")

    def test_opening_a_row_shows_its_people_and_items(self):
        row = self.b.node()
        self.assertEqual(row["label"], "Ferrer y Soler")
        self.b.handle("\r", None, None)
        self.b.refresh_nodes()
        under = [n for n in self.b.nodes if n.get("row") is row["row"]
                 and n["kind"] != "row"]
        self.assertEqual(under[0]["kind"], "people")
        self.assertIn("head", [n["kind"] for n in under])
        self.assertIn("item", [n["kind"] for n in under])
        self.assertNotIn("person", [n["kind"] for n in under])
        # The people folder opens on ⏎ too, in people.branch_people's order.
        self.b.move(1)
        self.b.handle("\r", None, None)
        self.b.refresh_nodes()
        people = [n["person"]["slug"] for n in self.b.nodes
                  if n["kind"] == "person"]
        self.assertEqual(people[0], "jaume-ferrer")
        self.assertIn("maria-soler", people)
        self.assertEqual(len(people), len(set(people)))

    def test_escape_backs_out_to_the_row(self):
        rid = self.b.cursor
        self.b.handle("\r", None, None)
        self.b.move(2)
        self.b.handle("\x1b", None, None)
        self.b.refresh_nodes()
        self.assertEqual(self.b.cursor, rid)
        self.assertFalse(self.b.node()["open"])

    def test_selections(self):
        self.b.opened.update({n["id"]: True for n in self.b.nodes})
        self.b.refresh_nodes()
        self.b.opened.update({n["id"]: True for n in self.b.nodes})
        self.b.refresh_nodes()
        by_kind = {}
        for n in self.b.nodes:
            by_kind.setdefault(n["kind"], n)
        fam = board.selection_of(by_kind["family"])
        self.assertEqual((fam["kind"], fam["family"]), ("family", "ferrer"))
        row = board.selection_of(by_kind["row"])
        self.assertEqual((row["kind"], row["family"], row["branch"],
                          row["branches"]),
                         ("branch", "ferrer", "ferrer", ["ferrer", "soler"]))
        person = board.selection_of(by_kind["person"])
        self.assertEqual((person["kind"], person["person"],
                          person["branch"]),
                         ("person", "jaume-ferrer", "ferrer"))
        item = board.selection_of(by_kind["item"])
        self.assertEqual(item["kind"], "item")
        self.assertTrue(item["item"]["title"])
        for s in (fam, row, person, item):
            self.assertTrue({"kind", "family", "branch", "person",
                             "item"} <= set(s))

    def test_footer_follows_the_selection(self):
        self.assertIn("r investiga la branca", self.b.footer().plain)
        self.b.opened.update({n["id"]: True for n in self.b.nodes})
        self.b.refresh_nodes()
        self.b.opened.update({n["id"]: True for n in self.b.nodes})
        self.b.refresh_nodes()
        person = next(n for n in self.b.nodes if n["kind"] == "person")
        self.go(person["id"])
        foot = self.b.footer().plain
        self.assertIn("e preguntes d'entrevista", foot)
        self.assertIn("R/E → inv", foot)
        item = next(n for n in self.b.nodes if n["kind"] == "item")
        self.go(item["id"])
        self.assertIn("i investiga el punt", self.b.footer().plain)
        self.assertNotIn("preguntes", self.b.footer().plain)

    def test_tab_moves_the_focus(self):
        self.b.handle("\t", None, None)
        self.assertEqual(self.b.focus, "panel")
        cur = self.b.cursor
        self.b.handle("j", None, None)
        self.assertEqual(self.b.cursor, cur)
        self.b.handle("\t", None, None)
        self.assertEqual(self.b.focus, "list")

    def test_without_panel_the_column_is_a_placeholder(self):
        with mock.patch.object(board, "panel", None):
            out = self.b.side_panel(self.model.tree, self.model.people, [],
                                    50, 20)
        console = Console(width=50, record=True, file=io.StringIO())
        console.print(out)
        self.assertIn("panel.py no disponible", console.export_text())

    def test_without_people_py_the_notes_are_read(self):
        with mock.patch.object(board, "people_mod", None):
            ppl = board.fallback_people(self.model.tree)
            names = [p["slug"] for p in board.branch_people(ppl, "ferrer")]
        self.assertIn("jaume-ferrer", names)
        self.assertEqual(ppl["persons"]["jaume-ferrer"]["name"],
                         "Jaume Ferrer")

    def test_years(self):
        self.assertEqual(board.years({"born": 1850, "died": "1901-02-03"}),
                         "1850–1901")
        self.assertEqual(board.years({"born": "c. 1842"}), "n. c.1842")
        self.assertEqual(board.years({"died": "antes de 1874"}), "†c.1874")
        self.assertEqual(board.years({}), "")


class ActTest(BoardCase):
    def wait(self):
        deadline = time.time() + 10
        while self.b.busy and time.time() < deadline:
            time.sleep(0.02)
        for t in threading.enumerate():
            if t is not threading.current_thread() and not t.daemon:
                t.join(5)

    def test_lowercase_prefills_at_once(self):
        self.agent("orq", "idle", pane="w1:p2")
        self.b.handle("r", None, None)
        self.wait()
        self.assertEqual(self.calls()[-2][:3], ["pane", "send-text", "w1:p2"])
        self.assertIn("«Ferrer y Soler»", self.calls()[-2][3])
        self.assertIn("escrit a orq", self.b.flash[0])

    def test_uppercase_asks_first(self):
        self.agent("inv", "idle")
        self.model.refresh_agents()
        self.b.handle("R", None, None)
        self.assertEqual(self.mutating(), [])
        self.assertIn("prem R de nou per enviar a inv", self.b.confirm[3])
        self.b.handle("R", None, None)
        self.wait()
        self.assertEqual(self.calls()[-1][:3], ["agent", "prompt", "inv"])

    def test_busy_orchestrator_is_told(self):
        self.agent("orq", "working")
        self.b.handle("r", None, None)
        self.wait()
        self.assertIn("està treballant", self.b.flash[0])
        self.assertIn("R ho envia a inv", self.b.flash[0])
        self.assertEqual(self.mutating(), [])


if __name__ == "__main__":
    unittest.main()
