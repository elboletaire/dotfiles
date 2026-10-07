"""Tests for arbre_data.py on a fictional tree made in a temp folder: its own
folder names (so nothing can lean on the kit's defaults), a git history with
dated commits, and a stub in place of the tree's validate script."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import arbre_data  # noqa: E402

GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
DAY = 86400

FAMILIES = """\
# A fictional tree.
language: es
paths:
  people: gent
  sources: docs
  research: recerca
  portraits: fotos

main: anna-ferrer-puig

families:
  - key: ferrer
    label: Familia Ferrer
    title: Familia Ferrer (Ferrer Puig)
    of: de la familia Ferrer
    default: true
  - key: vidal
    label: Familia Vidal
    title: Familia Vidal

branches:
  - {key: ferrer, label: Ferrer, color: "#2a78d6", founder: jaume-ferrer, family: ferrer}
  - {key: soler, label: Soler, color: "#eb6834", founder: maria-soler, family: ferrer}
  - {key: puig, label: Puig, color: "#1baf7a", founder: joan-puig, family: ferrer}
  - {key: vidal, label: Vidal, color: "#4a3aa7", founder: pere-vidal, family: vidal}

other_branch: {key: otras, label: Otras familias, color: "#9a958c"}

groups:
  - {family: ferrer, title: Ferrer y Soler, branches: [ferrer, soler]}
  - {family: ferrer, title: Puig, branches: [puig]}
  - family: vidal
    title: "Vidal: la casa"
    branches:
      - vidal
"""

PENDING = """\
# Pendientes

Intro paragraph, not an item.

## Familia Ferrer (Ferrer Puig)

### Ferrer y Soler

#### Documentos a conseguir

- **Partida de bautismo de Jaume Ferrer** (Girona, 1850), para fijar
  la fecha (12/3 o 13/3).
- **Testamento de Maria Soler**:
  1. primera copia;
  2. segunda copia.

- Una línea sin negrita que también es un punto.

#### Personas por identificar o completar

- **¿Quién es el padrino?** — sale en la foto.

#### Búsquedas del 5-10-2026 sin resultado, no repetir

- **FamilySearch, Ferrer de Girona**: nada.

### Familia reciente

#### Ramas que se cortan

- **Abuelos de Anna**.

## Familia Vidal

- **Algo de la familia Vidal sin rama**.

## General

- **Un punto general**.
"""

CONTRA = """\
# Incoherencias

## Familia Ferrer (Ferrer Puig)

### Puig

#### Fechas

- **Nacimiento de Joan Puig** — 1880 o 1881.

### Familia reciente: padres deducidos del dibujo

- **Padres de Anna**.
"""

REVIEW = """\
# Revisión

## Familia Ferrer (Ferrer Puig)

**2 documentos pendientes.**

### Ferrer y Soler (1)

#### [F002 — Jaume Ferrer en la prensa](../docs/F002.md)

- **Documento**: [abrir F002](../docs/F002.md)

### Otras familias (1)

#### [F003 — Un vecino](../docs/F003.md)

## General

### [F004 — Una foto sin personas](../docs/F004.md)
"""


def person(tags, sources):
    tag_list = ", ".join(f"rama/{t}" for t in tags)
    src = ", ".join(f'"[[{s}]]"' for s in sources)
    return (f"---\ngiven_name: \"X\"\nsex: M\ntags: [{tag_list}]\n"
            f"sources: [{src}]\n---\n# X\n")


def source(fid):
    return f'---\nid: "{fid}"\ntitle: "Doc {fid}"\ncategory: genealogia\n---\n'


class Tree:
    """A git repo built commit by commit, each at a chosen age."""

    def __init__(self, root, now):
        self.root, self.now = root, now
        self.git("init", "-q", "-b", "main")

    def git(self, *args, at=None):
        env = dict(os.environ, **GIT_ENV)
        if at is not None:
            stamp = f"@{int(at)} +0000"
            env.update(GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
        return subprocess.run(["git", "-C", self.root, *args], check=True,
                              capture_output=True, text=True, env=env).stdout

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def commit(self, msg, days_ago, files):
        for rel, text in files.items():
            self.write(rel, text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg, at=self.now - days_ago * DAY)


class ArbreDataTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "arbre")
        os.makedirs(self.root)
        self.now = time.time()
        t = self.t = Tree(self.root, self.now)
        t.commit("feat: start", 40, {
            "families.yml": FAMILIES,
            "gent/jaume-ferrer.md": person(["ferrer"], ["F001"]),
            "gent/joan-puig.md": person(["puig"], ["F005"]),
            "gent/pere-vidal.md": person(["vidal"], []),
            "gent/un-vei.md": person([], ["F003"]),
            "docs/F001.md": source("F001"),
            "docs/F005.md": source("F005"),
            "recerca/pendientes.md": PENDING,
            "recerca/incoherencias.md": CONTRA,
            "recerca/descartados.md": "# Descartados\n",
            "recerca/revision.md": REVIEW,
        })
        # Puig researched 30 days ago (stale), Ferrer 2 days ago.
        t.commit("feat: Joan Puig", 30, {
            "gent/joan-puig.md": person(["puig"], ["F005"]) + "bio\n"})
        t.commit("feat: F002 and F003", 2, {
            "docs/F002.md": source("F002"), "docs/F003.md": source("F003"),
            "docs/F004.md": source("F004"),
            "docs/F002/scan.jpg": "x",
            "gent/maria-soler.md": person(["soler", "ferrer"], ["F002"])})
        # A sweep touching Puig yesterday: maintenance, not research.
        t.commit("chore: dates in long form", 1, {
            "gent/joan-puig.md": person(["puig"], ["F005"]) + "bio.\n"})
        self.patch = mock.patch.object(arbre_data, "CACHE_DIR",
                                       self.cache.name)
        self.patch.start()
        self.env = mock.patch.dict(os.environ, {
            "ARXIU_VALIDATE_CMD": "echo 'warning: x: isolated'; "
                                  "echo; echo '5 people, 5 sources, "
                                  "0 errors, 1 warnings'"})
        self.env.start()
        arbre_data._CACHES.clear()

    def tearDown(self):
        self.env.stop()
        self.patch.stop()
        self.tmp.cleanup()
        self.cache.cleanup()

    def row(self, tree, title):
        hit = [r for r in tree["rows"] if r["title"] == title]
        self.assertEqual(len(hit), 1, [r["title"] for r in tree["rows"]])
        return hit[0]

    # -- families.yml

    def test_yaml_subset(self):
        cfg = arbre_data.parse_yaml(FAMILIES)
        self.assertEqual(cfg["paths"]["people"], "gent")
        self.assertEqual(cfg["families"][0]["default"], True)
        self.assertEqual(cfg["branches"][1],
                         {"key": "soler", "label": "Soler", "color": "#eb6834",
                          "founder": "maria-soler", "family": "ferrer"})
        self.assertEqual(cfg["other_branch"]["color"], "#9a958c")
        self.assertEqual(cfg["groups"][2],
                         {"family": "vidal", "title": "Vidal: la casa",
                          "branches": ["vidal"]})

    def test_frontmatter_lists(self):
        meta = arbre_data.frontmatter(
            '---\ntags:\n  - rama/a\n  - rama/b\nsources: ["[[F001]]"]\n'
            'marriages:\n  - spouse: x\n    date: 1900\n---\nbody')
        self.assertEqual(meta["tags"], ["rama/a", "rama/b"])
        self.assertEqual(meta["sources"], ["[[F001]]"])
        self.assertEqual(meta["marriages"], [{"spouse": "x", "date": 1900}])

    # -- research files

    def test_totals_and_folders_from_families(self):
        tree = arbre_data.load(self.root, now=self.now)
        t = tree["totals"]
        self.assertEqual((t["people"], t["sources"]), (5, 5))
        self.assertEqual(t["last_source"], "F005")
        self.assertEqual(tree["paths"]["research"], "recerca")
        # 3 docs + 1 person + 1 cut + 1 family Vidal + 1 general.
        self.assertEqual(t["pending"], 7)
        self.assertEqual(t["searched"], 1)
        self.assertEqual(t["contradictions"], 2)
        self.assertEqual(t["review"], 3)

    def test_items_wrap_and_categories(self):
        tree = arbre_data.load(self.root, now=self.now)
        fs = self.row(tree, "Ferrer y Soler")
        self.assertTrue(fs["matched"])
        self.assertEqual(fs["branches"], ["ferrer", "soler"])
        docs = fs["pending"]["Documentos a conseguir"]
        self.assertEqual([i["title"] for i in docs],
                         ["Partida de bautismo de Jaume Ferrer",
                          "Testamento de Maria Soler",
                          "Una línea sin negrita que también es un punto."])
        self.assertIn("la fecha (12/3 o 13/3)", docs[0]["text"])
        self.assertIn("segunda copia", docs[1]["text"])
        self.assertEqual(fs["counts"]["docs"], 3)
        self.assertEqual(fs["counts"]["people"], 1)
        # "sin resultado, no repetir" is a log of searches, not pending work.
        self.assertEqual(fs["counts"]["pending"], 4)
        self.assertEqual(fs["counts"]["searched"], 1)
        self.assertEqual(fs["counts"]["review"], 1)

    def test_unmatched_headings_are_kept(self):
        tree = arbre_data.load(self.root, now=self.now)
        recent = self.row(tree, "Familia reciente")
        self.assertFalse(recent["matched"])
        # Same section in both files, though one heading has a ": ..." tail.
        self.assertEqual(recent["counts"]["cut"], 1)
        self.assertEqual(recent["counts"]["contradictions"], 1)
        puig = self.row(tree, "Puig")
        self.assertEqual(puig["counts"]["contradictions"], 1)
        # Items right under a family with one group go to that group.
        vidal = self.row(tree, "Vidal: la casa")
        self.assertEqual(vidal["counts"]["pending"], 1)
        general = self.row(tree, "General")
        self.assertEqual((general["counts"]["pending"],
                          general["counts"]["review"]), (1, 1))
        other = self.row(tree, "Otras familias")
        self.assertEqual(other["branches"], ["otras"])
        self.assertEqual(other["review"][0]["id"], "F003")

    def test_row_order_follows_families(self):
        tree = arbre_data.load(self.root, now=self.now)
        fams = [r["family"] for r in tree["rows"]]
        self.assertEqual(fams.index("ferrer"), 0)
        self.assertLess(max(i for i, f in enumerate(fams) if f == "ferrer"),
                        fams.index("vidal"))

    # -- git

    def test_last_research_skips_maintenance(self):
        tree = arbre_data.load(self.root, now=self.now)
        fs = self.row(tree, "Ferrer y Soler")
        self.assertAlmostEqual(fs["last_research"], self.now - 2 * DAY,
                               delta=5)
        self.assertFalse(fs["stale"])
        puig = self.row(tree, "Puig")
        # The chore commit of yesterday does not count.
        self.assertAlmostEqual(puig["last_research"], self.now - 30 * DAY,
                               delta=5)
        self.assertTrue(puig["stale"])
        # The untagged neighbour cites F003: the "other" branch.
        other = self.row(tree, "Otras familias")
        self.assertAlmostEqual(other["last_research"], self.now - 2 * DAY,
                               delta=5)

    def test_week_and_diary(self):
        tree = arbre_data.load(self.root, now=self.now)
        self.assertEqual(tree["week"], {"people": 1, "sources": 3,
                                        "first_source": "F002",
                                        "last_source": "F004"})
        self.assertEqual([c["text"] for c in tree["diary"]],
                         ["dates in long form", "F002 and F003",
                          "Joan Puig", "start"])
        self.assertEqual(tree["diary"][0]["kind"], "chore")

    def test_reload_sees_new_commit(self):
        arbre_data.load(self.root, now=self.now)
        self.t.commit("feat: F006", 0, {"docs/F006.md": source("F006")})
        tree = arbre_data.load(self.root, now=self.now)
        self.assertEqual(tree["totals"]["last_source"], "F006")
        self.assertEqual(tree["diary"][0]["text"], "F006")

    # -- validation

    def test_validation_cached_and_staled_by_changes(self):
        v = arbre_data.validation(self.root)
        self.assertEqual(v["state"], "unknown")
        v = arbre_data.run_validation(self.root)
        self.assertEqual((v["state"], v["errors"], v["warnings"]),
                         ("ok", 0, 1))
        self.assertFalse(v["stale"])
        # Fresh: an async kick does nothing.
        self.assertFalse(arbre_data.validate_async(self.root))
        time.sleep(0.01)
        self.t.write("gent/joan-puig.md", person(["puig"], []) + "edit\n")
        self.assertTrue(arbre_data.validation(self.root)["stale"])

    def test_validation_errors(self):
        with mock.patch.dict(os.environ, {
                "ARXIU_VALIDATE_CMD": "echo 'ERROR: x: bad date'; exit 1"}):
            v = arbre_data.run_validation(self.root)
        self.assertEqual((v["state"], v["errors"]), ("error", 1))
        self.assertEqual(v["lines"], ["ERROR: x: bad date"])

    def test_writes_nothing_in_the_tree(self):
        arbre_data.load(self.root, now=self.now)
        arbre_data.run_validation(self.root)
        self.assertEqual(self.t.git("status", "--porcelain",
                                    "--ignored"), "")


if __name__ == "__main__":
    unittest.main()
