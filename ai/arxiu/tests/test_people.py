"""Tests for people.py on the fictional tree of people_fixture.py."""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import people_fixture  # noqa: E402
import arbre_data  # noqa: E402
import people  # noqa: E402


class PeopleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "arbre")
        self.t = people_fixture.build(self.root, time.time())
        self.cache = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(arbre_data, "CACHE_DIR",
                                       self.cache.name)
        self.patch.start()
        people._CACHES.clear()
        arbre_data._CACHES.clear()
        self.p = people.load(self.root)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()
        self.cache.cleanup()

    # -- parsing

    def test_person_fields(self):
        josep = self.p["persons"]["josep-ferrer-soler"]
        self.assertEqual(josep["name"], "Josep Ferrer Soler")
        self.assertEqual((josep["father"], josep["mother"]),
                         ("jaume-ferrer", "maria-soler"))
        self.assertEqual(josep["parents_confidence"], "proven")
        self.assertEqual(josep["branches"], ["ferrer", "soler"])
        self.assertEqual((josep["sources"], josep["source_ids"]),
                         (2, ["F001", "F002"]))
        self.assertEqual(josep["born_year"], 1880)
        self.assertEqual(josep["children"], ["pere-ferrer-puig",
                                             "anna-ferrer-puig",
                                             "lluc-ferrer-puig"])

    def test_dates(self):
        persons = self.p["persons"]
        # A bare year is read as an int, "c. 1855" as text.
        self.assertEqual(persons["jaume-ferrer"]["born_year"], 1850)
        self.assertEqual(persons["maria-soler"]["born_year"], 1855)
        self.assertTrue(people.approximate(persons["maria-soler"]["born"]))
        self.assertFalse(people.approximate("1880-02-03"))
        self.assertIsNone(persons["lluc-ferrer-puig"]["born_year"])
        self.assertIsNone(people.year_of("?"))

    def test_research_notes_need_content(self):
        persons = self.p["persons"]
        self.assertTrue(persons["jaume-ferrer"]["research_notes"])
        # An empty «Notas de investigación» does not count.
        self.assertFalse(persons["anna-ferrer-puig"]["research_notes"])
        self.assertFalse(persons["josep-ferrer-soler"]["research_notes"])

    def test_untagged_people_go_to_other(self):
        self.assertEqual(self.p["persons"]["un-vei"]["branches"], ["otras"])
        self.assertEqual(self.p["branches"]["otras"]["members"], ["un-vei"])

    def test_items_by_link_and_by_name(self):
        persons = self.p["persons"]
        # Named in the text ("Jaume Ferrer"), linked ([Maria](...)).
        self.assertEqual([i["line"] for i in persons["jaume-ferrer"]["pending"]],
                         [9])
        self.assertEqual(persons["maria-soler"]["pending"][0]["title"],
                         "Testamento de Maria")
        self.assertEqual(self.p["items"]["pendientes.md:11"],
                         {"people": ["josep-ferrer-soler", "maria-soler"],
                          "sources": ["F002"]})
        # The "no repetir" log names Jaume too, but is not open work.
        self.assertIn("pendientes.md:16", self.p["items"])
        self.assertEqual(len(persons["jaume-ferrer"]["pending"]), 1)
        self.assertEqual(persons["joan-puig"]["contradictions"][0]["kind"],
                         "contradictions")

    def test_item_refs(self):
        tree = arbre_data.load(self.root)
        docs = [i for r in tree["rows"] for items in r["pending"].values()
                for i in items if i["title"].startswith("Testamento")]
        self.assertEqual(people.item_refs(self.p, docs[0])["sources"],
                         ["F002"])
        self.assertEqual(people.item_refs(self.p, {"id": "F009",
                                                   "title": "x"}),
                         {"people": [], "sources": ["F009"]})

    # -- roots

    def test_roots(self):
        b = self.p["branches"]
        self.assertEqual(b["ferrer"]["root"], "jaume-ferrer")
        # Founder "ningu" has no note: the member heading the most
        # descendants inside the branch.
        self.assertEqual(b["vidal"]["root"], "pere-vidal")
        self.assertEqual(b["otras"]["root"], "un-vei")
        fams = self.p["families"]
        # Anna carries all three branches of her family and is `main`.
        self.assertEqual(fams["ferrer"]["root"], "anna-ferrer-puig")
        self.assertEqual(fams["ferrer"]["branches"],
                         ["ferrer", "soler", "puig"])
        self.assertEqual(fams["vidal"]["root"], "pere-vidal")

    # -- pedigree

    def test_pedigree_missing_and_probable(self):
        ped = people.pedigree(self.p, "anna-ferrer-puig", depth=3)
        self.assertEqual(ped["confidence"], "proven")
        father, mother = ped["father"], ped["mother"]
        self.assertEqual(father["slug"], "josep-ferrer-soler")
        self.assertEqual(father["father"]["slug"], "jaume-ferrer")
        self.assertEqual(mother["confidence"], "probable")
        # A link to a note that does not exist: a node with no person.
        self.assertEqual(mother["mother"]["slug"], "nn-vidal")
        self.assertIsNone(mother["mother"]["person"])
        # Third generation: not expanded; jaume has no parents.
        self.assertIsNone(father["father"]["father"])
        self.assertFalse(father["father"]["more"])
        lluc = people.pedigree(self.p, "lluc-ferrer-puig")
        self.assertIsNone(lluc["mother"])

    def test_pedigree_depth_marks_more(self):
        ped = people.pedigree(self.p, "anna-ferrer-puig", depth=2)
        self.assertIsNone(ped["father"]["father"])
        self.assertTrue(ped["father"]["more"])
        self.assertTrue(ped["mother"]["more"])
        self.assertIsNone(people.pedigree(self.p, None))

    # -- branches

    def test_branch_people_order(self):
        order = [r["slug"] for r in people.branch_people(self.p, "ferrer")]
        # Generation from the founder, then birth year (unknown last).
        self.assertEqual(order, ["jaume-ferrer", "josep-ferrer-soler",
                                 "pere-ferrer-puig", "anna-ferrer-puig",
                                 "lluc-ferrer-puig"])
        gens = people.generations(self.p, "puig")
        self.assertEqual(gens["joan-puig"], 0)
        self.assertEqual(gens["anna-ferrer-puig"], 2)
        self.assertEqual(people.branch_people(self.p, "nope"), [])

    def test_completeness(self):
        c = people.completeness(self.p, "ferrer")
        self.assertEqual(c, {
            "people": 5, "with_sources": 4, "without_sources": 1,
            "parents_proven": 3, "parents_probable": 1,
            "parents_missing": 1, "parents_partial": 1, "with_birth": 4,
            "with_research_notes": 1, "with_pending": 2, "pending_items": 2,
            "contradictions": 0})
        puig = people.completeness(self.p, "puig")
        self.assertEqual(puig["contradictions"], 1)
        fam = people.completeness(self.p, family="ferrer")
        self.assertEqual(fam["people"], 8)

    def test_line_of_descent(self):
        self.assertEqual(people.line_of_descent(self.p, "jaume-ferrer"),
                         ["jaume-ferrer", "josep-ferrer-soler",
                          "anna-ferrer-puig"])
        self.assertEqual(people.line_of_descent(self.p, "pere-vidal"), [])

    # -- cache

    def test_cached_until_a_note_changes(self):
        self.assertIs(people.load(self.root), self.p)
        time.sleep(0.01)
        self.t.write("gent/joan-puig.md", people_fixture.note(
            "Joan", "Puig", tags=["puig"], born=1879))
        again = people.load(self.root)
        self.assertIsNot(again, self.p)
        self.assertEqual(again["persons"]["joan-puig"]["born_year"], 1879)

    def test_writes_nothing_in_the_tree(self):
        people.load(self.root)
        self.assertEqual(self.t.git("status", "--porcelain", "--ignored"),
                         "")


if __name__ == "__main__":
    unittest.main()
