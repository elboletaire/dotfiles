"""Tests for panel.py: every kind of selection rendered at 50 and 80
columns on the fictional tree of people_fixture.py, the queue, and the
lookup card that never blocks. Needs rich:

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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import people_fixture  # noqa: E402
import arbre_data  # noqa: E402
import people  # noqa: E402

try:
    from rich.cells import cell_len
    from rich.console import Console
    import panel
except ImportError:          # bare python3: only the stdlib tests run
    panel = None

CARD = """\
## Anna Ferrer Puig [anna-ferrer-puig] — gent/anna-ferrer-puig.md
sex F · born 1910-05-01
father: josep-ferrer-soler · mother: rosa-puig-vidal · proven
sources (1; * pending review): F001
"""


@unittest.skipIf(panel is None, "rich is not installed")
class PanelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "arbre")
        self.now = time.time()
        self.t = people_fixture.build(self.root, self.now)
        self.cache = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(arbre_data, "CACHE_DIR", self.cache.name),
            mock.patch.object(panel, "LOOKUP_DIR",
                              os.path.join(self.cache.name, "lookup")),
        ]
        for p in self.patches:
            p.start()
        people._CACHES.clear()
        arbre_data._CACHES.clear()
        panel._LOOK.clear()
        panel._LAST.clear()
        self.tree = arbre_data.load(self.root, now=self.now)
        self.people = people.load(self.root, self.tree)
        # The lookup: a stub that waits for `release` and counts its calls.
        self.release = threading.Event()
        self.calls = []

        def fake(tree_path, queries):
            self.calls.append(list(queries))
            self.release.wait(5)
            return True, CARD if queries == ["anna-ferrer-puig"] else \
                "".join(f"## {q} [{q}] — x.md\nline of {q}\n" for q in queries)
        self.lookup = mock.patch.object(panel, "_run_lookup", fake)
        self.lookup.start()
        self.ready = threading.Event()
        panel.set_on_ready(self.ready.set)

    def tearDown(self):
        self.release.set()
        panel.set_on_ready(None)
        self.lookup.stop()
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()
        self.cache.cleanup()

    def sel(self, kind, **kw):
        out = {"kind": kind, "family": None, "branch": None, "person": None,
               "item": None}
        out.update(kw)
        return out

    def show(self, selection, width, height=40, queue=()):
        r = panel.render(self.tree, self.people, selection, list(queue),
                         width, height, now=self.now)
        con = Console(record=True, width=width, file=io.StringIO(),
                      color_system=None)
        con.print(r)
        lines = con.export_text().splitlines()
        for ln in lines:
            self.assertLessEqual(cell_len(ln), width, ln)
        self.assertEqual(len(lines), height)
        return "\n".join(lines)

    def item(self, prefix):
        for row in self.tree["rows"]:
            for bucket in ("pending", "contradictions"):
                for items in row[bucket].values():
                    for it in items:
                        if it["title"].startswith(prefix):
                            return it
        raise AssertionError(prefix)

    # -- branch and family

    def test_branch(self):
        for width in (50, 80):
            out = self.show(self.sel("branch", branch="ferrer"), width)
            self.assertIn("■ Ferrer · 5 persones", out)
            self.assertIn("fundador", out)
            # The founder's unknown parents.
            self.assertIn("┌─ ?\nJaume Ferrer *1850\n└─ ?", out)
            self.assertIn("Completesa", out)
            self.assertRegex(out, r"pares provats +█+░+ +3")
            self.assertIn("↓ Josep › Anna", out)
            self.assertIn("Per generacions", out)
            self.assertIn(" 2 Pere, Anna, Lluc", out)

    def test_branch_without_founder_note(self):
        out = self.show(self.sel("branch", branch="vidal"), 50)
        self.assertIn("arrel (deduïda)", out)
        self.assertIn("Pere Vidal", out)

    def test_family(self):
        for width in (50, 80):
            out = self.show(self.sel("family", family="ferrer"), width)
            self.assertIn("Familia Ferrer · 3 branques · 8 persones", out)
            # Anna's pedigree: the probable link to her mother is dashed.
            self.assertIn("Anna Ferrer Puig *1910", out)
            self.assertIn("└─ Rosa Puig Vidal *1882", out)
            self.assertIn("│  ┌╌ Joan Puig *1878", out)
            self.assertIn("   └╌ nn-vidal", out)
            self.assertIn("╌ probable", out)
            self.assertRegex(out, r"Soler +█+.* 5")
            self.assertIn("Completesa de la família", out)

    def test_family_from_branch(self):
        out = self.show(self.sel("family", branch="puig"), 50)
        self.assertIn("Familia Ferrer", out)

    def test_pedigree_fits_and_truncates(self):
        lines, _ = panel.pedigree_lines(
            self.people, "anna-ferrer-puig", 3, 22,
            panel.Colours(self.tree, self.people))
        self.assertEqual(len(lines), 7)
        for t in lines:
            self.assertLessEqual(t.cell_len, 22, t.plain)
        # Surnames become initials, then the years go, before a cut.
        self.assertIn("┌─ Josep F. S. *1880", [t.plain for t in lines])
        self.assertIn("└─ Rosa Puig V. *1882", [t.plain for t in lines])

    # -- person

    def test_person_placeholder_then_card(self):
        sel = self.sel("person", person="anna-ferrer-puig")
        out = self.show(sel, 50)
        self.assertIn("Anna Ferrer Puig  *1910", out)
        self.assertIn("┌─ Josep Ferrer Soler *1880", out)
        self.assertIn("consultant la fitxa…", out)
        # A second render while it runs starts nothing new.
        self.show(sel, 80)
        self.assertEqual(self.calls, [["anna-ferrer-puig"]])
        self.assertEqual(panel.pending_lookups(), 1)
        self.release.set()
        self.assertTrue(self.ready.wait(5))
        out = self.show(sel, 80)
        self.assertNotIn("consultant", out)
        self.assertIn("father: josep-ferrer-soler", out)
        # The card's own title line is dropped: the header says it.
        self.assertNotIn("[anna-ferrer-puig]", out)
        # Cached on disk: a fresh process (empty memory) needs no lookup.
        panel._LOOK.clear()
        self.show(sel, 50)
        self.assertEqual(len(self.calls), 1)

    def test_new_head_shows_old_card_while_refreshing(self):
        sel = self.sel("person", person="anna-ferrer-puig")
        self.release.set()
        self.show(sel, 60)
        self.assertTrue(self.ready.wait(5))
        self.ready.clear()
        self.release.clear()
        self.tree = dict(self.tree, head="other")
        out = self.show(sel, 60)
        self.assertIn("actualitzant…", out)
        self.assertIn("father: josep-ferrer-soler", out)
        self.assertEqual(len(self.calls), 2)

    def test_prefetch(self):
        self.release.set()
        state = panel.prefetch("jaume-ferrer", self.root, self.tree["head"],
                               self.tree["fingerprint"])
        self.assertEqual(state, "pending")
        self.assertTrue(self.ready.wait(5))
        self.assertEqual(panel.prefetch("jaume-ferrer", self.root,
                                        self.tree["head"],
                                        self.tree["fingerprint"]), "done")
        out = self.show(self.sel("person", person="jaume-ferrer"), 50)
        self.assertIn("line of jaume-ferrer", out)
        self.assertEqual(len(self.calls), 1)

    def test_lookup_error_is_shown(self):
        with mock.patch.object(panel, "_run_lookup",
                               lambda *a: (False, "boom")):
            self.show(self.sel("person", person="joan-puig"), 50)
            self.assertTrue(self.ready.wait(5))
            out = self.show(self.sel("person", person="joan-puig"), 50)
        self.assertIn("no s'ha pogut consultar: boom", out)

    def test_lookup_cmd(self):
        self.assertEqual(panel.lookup_cmd(["a", "F001"])[-3:],
                         ["scripts/lookup.py", "a", "F001"])
        with mock.patch.dict(os.environ, {"ARXIU_LOOKUP_CMD": "echo {q}"}):
            self.assertEqual(panel.lookup_cmd(["a"]), ["sh", "-c", "echo a"])

    # -- item

    def test_item_mentions(self):
        self.release.set()
        sel = self.sel("item", item=self.item("Testamento"))
        out = self.show(sel, 50)
        self.assertIn("Testamento de Maria", out)
        self.assertIn("document a aconseguir · pendientes.md:11", out)
        self.assertIn("esmenta: Josep Ferrer Soler, Maria Soler, F002", out)
        self.assertTrue(self.ready.wait(5))
        self.assertEqual(self.calls, [["josep-ferrer-soler", "maria-soler",
                                       "F002"]])
        out = self.show(sel, 80)
        for q in ("josep-ferrer-soler", "maria-soler", "F002"):
            self.assertIn(f"line of {q}", out)

    def test_review_item(self):
        self.release.set()
        item = {"id": "F003", "title": "Un vecino", "kind": "review",
                "file": "revision.md", "line": None}
        out = self.show(self.sel("item", item=item), 50)
        self.assertIn("F003 — Un vecino", out)
        self.assertIn("font per revisar", out)
        self.assertIn("esmenta: F003", out)

    # -- queue

    def queue(self, n):
        statuses = ["sent", "working", "waiting", "done"]
        return [{"id": f"q{i}", "at": self.now - 60 * i, "kind": "person",
                 "target": "anna-ferrer-puig", "label": f"acció {i} " + "x" * 60,
                 "agent": "investigacio", "mode": "send",
                 "status": statuses[i % 4]} for i in range(n)]

    def test_queue_newest_first(self):
        q = self.queue(4)[::-1]
        out = self.show(self.sel("branch", branch="puig"), 50, 30, q)
        tail = out.splitlines()[-5:]
        self.assertTrue(tail[0].startswith("── Cua (4) ──"), tail[0])
        self.assertTrue(tail[1].startswith("✉  ara acció 0"), tail[1])
        self.assertTrue(tail[2].startswith("◐   1m acció 1"), tail[2])
        self.assertTrue(tail[3].startswith("⏸   2m acció 2"), tail[3])
        self.assertTrue(tail[4].startswith("✓   3m acció 3"), tail[4])
        self.assertTrue(tail[1].endswith("…"))

    def test_queue_cut_to_room(self):
        out = self.show(self.sel("branch", branch="puig"), 50, 20,
                        self.queue(30))
        lines = out.splitlines()
        self.assertIn("── Cua (30) ──", out)
        self.assertTrue(lines[-1].startswith("… "), lines[-1])
        self.assertIn("més", lines[-1])

    def test_empty_queue(self):
        out = self.show(self.sel("branch", branch="puig"), 50, 30)
        self.assertTrue(out.splitlines()[-1].startswith("── Cua · buida"))

    # -- small and odd

    def test_degrades_when_small(self):
        sels = [self.sel("branch", branch="ferrer"),
                self.sel("family", family="ferrer"),
                self.sel("person", person="anna-ferrer-puig"),
                self.sel("item", item=self.item("Testamento")),
                self.sel(None), self.sel("person", person="nobody")]
        for s in sels:
            for w, h in ((50, 30), (30, 12), (20, 6), (12, 3), (50, 1)):
                self.show(s, w, h, self.queue(3))

    def test_nothing_selected(self):
        out = self.show(self.sel(None), 50, 10)
        self.assertIn("selecciona", out)

    def test_readable_colours(self):
        self.assertEqual(panel.readable("#ffffff"), "#ffffff")
        dark = panel.readable("#4a3aa7")
        self.assertNotEqual(dark, "#4a3aa7")
        self.assertEqual(panel.readable("bad"), "white")


if __name__ == "__main__":
    unittest.main()
