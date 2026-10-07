"""A small fictional tree for the people.py and panel.py tests: three
generations of Ferrer, Soler and Puig, a Vidal branch whose founder has no
note, an unrelated neighbour, and research files that link or name them."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from test_arbre_data import FAMILIES, Tree  # noqa: E402

# The Vidal founder is a slug with no note: its root has to be derived.
PEOPLE_FAMILIES = FAMILIES.replace("founder: pere-vidal", "founder: ningu")


def note(given, surnames, sex="M", tags=(), sources=(), born=None,
         father=None, mother=None, conf=None, notes=None, extra=""):
    fm = [f'given_name: "{given}"', f'surnames: "{surnames}"', f"sex: {sex}"]
    if born is not None:
        fm.append(f"born: {born}")
    if father:
        fm.append(f'father: "[[{father}]]"')
    if mother:
        fm.append(f'mother: "[[{mother}]]"')
    if conf:
        fm.append(f"parents_confidence: {conf}")
    if tags:
        fm.append("tags: [" + ", ".join(f"rama/{t}" for t in tags) + "]")
    fm.append("sources: [" + ", ".join(f'"[[{s}]]"' for s in sources) + "]")
    body = f"# {given} {surnames}\n\n## Biografía\n\nBio.\n"
    if notes is not None:
        body += f"\n## Notas de investigación\n\n{notes}\n"
    body += "\n## Referencias\n"
    return "---\n" + "\n".join(fm) + "\n" + extra + "---\n" + body


NOTES = {
    "jaume-ferrer": note("Jaume", "Ferrer", tags=["ferrer"],
                         sources=["F001"], born=1850,
                         notes="Falta la partida de bautismo."),
    "maria-soler": note("Maria", "Soler", sex="F", tags=["soler"],
                        sources=["F002"], born='"c. 1855"'),
    "josep-ferrer-soler": note("Josep", "Ferrer Soler",
                               tags=["ferrer", "soler"],
                               sources=["F001", "F002"], born="1880-02-03",
                               father="jaume-ferrer", mother="maria-soler",
                               conf="proven"),
    "joan-puig": note("Joan", "Puig", tags=["puig"], born=1878),
    # Her mother has no note: a dangling link.
    "rosa-puig-vidal": note("Rosa", "Puig Vidal", sex="F", tags=["puig"],
                            sources=["F005"], born=1882, father="joan-puig",
                            mother="nn-vidal", conf="probable"),
    "anna-ferrer-puig": note("Anna", "Ferrer Puig", sex="F",
                             tags=["ferrer", "soler", "puig"],
                             sources=["F001"], born="1910-05-01",
                             father="josep-ferrer-soler",
                             mother="rosa-puig-vidal", conf="proven",
                             notes=""),
    "pere-ferrer-puig": note("Pere", "Ferrer Puig",
                             tags=["ferrer", "soler", "puig"],
                             sources=["F001"], born=1905,
                             father="josep-ferrer-soler",
                             mother="rosa-puig-vidal", conf="probable"),
    "lluc-ferrer-puig": note("Lluc", "Ferrer Puig",
                             tags=["ferrer", "soler", "puig"],
                             father="josep-ferrer-soler", conf="proven"),
    "pere-vidal": note("Pere", "Vidal", tags=["vidal"], born=1800,
                       notes="Res."),
    "marta-vidal": note("Marta", "Vidal Roca", sex="F", tags=["vidal"],
                        born=1830, father="pere-vidal", conf="probable"),
    "un-vei": note("Un", "Veí", sources=["F003"]),
}

PENDING = """\
# Pendientes

## Familia Ferrer (Ferrer Puig)

### Ferrer y Soler

#### Documentos a conseguir

- **Partida de bautismo de Jaume Ferrer** (Girona, 1850), para fijar
  la fecha.
- **Testamento de [Maria](../gent/maria-soler.md)**
  ([F002](../docs/F002.md)) y de [Josep](../gent/josep-ferrer-soler.md).

#### Búsquedas del 5-10-2026 sin resultado, no repetir

- **FamilySearch**: nada sobre Jaume Ferrer.

### Puig

#### Personas por identificar o completar

- **La madre de Rosa Puig Vidal**: ¿una Vidal?
"""

CONTRA = """\
# Incoherencias

## Familia Ferrer (Ferrer Puig)

### Puig

#### Fechas

- **Nacimiento de Joan Puig** — 1878 o 1881.
"""


def source(fid):
    return f'---\nid: "{fid}"\ntitle: "Doc {fid}"\ncategory: genealogia\n---\n'


def build(root, now):
    """Write the tree into `root` (a git repo with one commit)."""
    os.makedirs(root, exist_ok=True)
    t = Tree(root, now)
    files = {"families.yml": PEOPLE_FAMILIES,
             "recerca/pendientes.md": PENDING,
             "recerca/incoherencias.md": CONTRA,
             "recerca/descartados.md": "# Descartados\n",
             "recerca/revision.md": "# Revisión\n"}
    files.update({f"gent/{slug}.md": text for slug, text in NOTES.items()})
    files.update({f"docs/{f}.md": source(f)
                  for f in ("F001", "F002", "F003", "F005")})
    t.commit("feat: start", 3, files)
    return t
