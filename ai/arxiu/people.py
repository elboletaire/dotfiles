#!/usr/bin/env python3
"""Reads the person notes of a family-tree-kit tree for Arxiu's right panel.

Stdlib only, like arbre_data.py, whose YAML-subset frontmatter parser, folder
mapping (`paths`) and families/branches it reuses. Nothing here writes into
the tree.

`load(tree_path, tree=None) -> People` (the shape is documented on load()).
The whole result is cached per tree by arbre_data's fingerprint of the notes
and research files, and each note by its stat, so a refresh with nothing new
costs one scandir per folder.

The founder of a branch is the `founder` slug families.yml gives it: the
earliest known person of the branch's paternal (or maternal) line. When a
branch has none, or its note is missing (the "other" branch never has one),
the root is the branch member with no parent inside the branch who has the
most descendants in it (then the earliest born). A family has no founder of
its own: its root is the person who carries the most of the family's branch
tags and the fewest of other families' (the one where the family's lines
meet, e.g. the mother whose ancestors make up "her" family), preferring
`main` and main's ancestors, then the earliest born.
"""
import os
import re
import sys
import threading
import time
import unicodedata

import arbre_data

# The «Notas de investigación» heading in the languages a tree may use
# (compared folded: no accents, no case, no punctuation).
RESEARCH_HEADINGS = {"notas de investigacion", "notes de recerca",
                     "notes d investigacio", "research notes"}
YEAR = re.compile(r"(\d{4})")
# A person or source linked in markdown: [label](../<folder>/<slug>.md) or an
# Obsidian [[slug]].
MD_LINK = re.compile(r"\]\(([^)\s]*?)([^/)\s]+)\.md(?:#[^)]*)?\)")
WIKI_LINK = re.compile(r"\[\[([^\]|#]+)")
SOURCE_REF = re.compile(r"\bF\d{2,}\b")
_NON_WORD = re.compile(r"[^a-z0-9]+")


# ------------------------------------------------------------------ helpers

def fold(text):
    """No accents, no case, single spaces: how names are compared."""
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    text = text.encode("ascii", "ignore").decode()
    return " ".join(_NON_WORD.split(text)).strip()


def year_of(value):
    """A frontmatter date (`1896-12-19`, `"c. 1844"`, `"antes de 1938"`,
    `1896` read as an int, `"?"`) -> its year, or None."""
    if value is None or value is True or value is False:
        return None
    m = YEAR.search(str(value))
    return int(m.group(1)) if m else None


def approximate(value):
    """True when a date is not certain: c., antes/después de, ¿…?"""
    s = str(value or "").strip()
    return bool(s) and not re.fullmatch(r"\d{4}(-\d{2}){0,2}", s)


def has_research_notes(body):
    """The note has a non-empty «Notas de investigación» section."""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if not m or fold(m.group(1)) not in RESEARCH_HEADINGS:
            continue
        for nxt in lines[i + 1:]:
            if re.match(r"^#{1,2}\s", nxt):
                break
            if nxt.strip():
                return True
    return False


def _raw_items(text):
    """The research file -> {line: raw markdown of the item}: a top-level
    `- ` bullet and what is indented (or wrapped) under it, the same items
    and line numbers as arbre_data.parse_research, but with the links."""
    out, cur, blank = {}, None, False
    for n, line in enumerate(text.splitlines(), 1):
        if re.match(r"^#{1,6}\s", line):
            cur = None
        elif line.startswith("- ") or line == "-":
            cur = n
            out[n] = [line[2:]]
        elif not line.strip():
            blank = True
            continue
        elif cur and (line.startswith((" ", "\t")) or not blank):
            out[cur].append(line.strip())
        else:
            cur = None
        blank = False
    return {n: " ".join(v) for n, v in out.items()}


# ------------------------------------------------------------------- cache

class _Cache:
    def __init__(self):
        self.notes = {}       # path -> (stat, record)
        self.raw = {}         # path -> (stat, {line: raw})
        self.people = None    # (fingerprint, People)


_CACHES = {}
_LOCK = threading.Lock()


def _cache(tree):
    with _LOCK:
        return _CACHES.setdefault(tree, _Cache())


def _person(cache, path, other):
    st = arbre_data.stat_key(path)
    hit = cache.notes.get(path)
    if hit and hit[0] == st:
        return hit[1]
    text = arbre_data.read(path)
    meta = arbre_data.frontmatter(text[:20000])
    end = text.find("\n---", 3) if text.startswith("---") else -1
    body = text[end + 4:] if end >= 0 else text
    slug = os.path.basename(path)[:-3]
    given = str(meta.get("given_name") or "").strip()
    surnames = str(meta.get("surnames") or "").strip()
    link, as_list = arbre_data.wikilink, arbre_data._as_list
    srcs = [link(s) for s in as_list(meta.get("sources"))]
    rec = {
        "slug": slug,
        "name": " ".join(x for x in (given, surnames) if x) or slug,
        "given_name": given, "surnames": surnames,
        "aliases": [str(a) for a in as_list(meta.get("aliases"))],
        "sex": meta.get("sex"),
        "born": meta.get("born"), "died": meta.get("died"),
        "born_year": year_of(meta.get("born")),
        "died_year": year_of(meta.get("died")),
        "birth_place": meta.get("birth_place"),
        "death_place": meta.get("death_place"),
        "living": meta.get("living"),
        "father": link(meta["father"]) if meta.get("father") else None,
        "mother": link(meta["mother"]) if meta.get("mother") else None,
        "parents_confidence": meta.get("parents_confidence"),
        "spouses": [arbre_data.wikilink(s) for s in
                    arbre_data._as_list(meta.get("spouses"))],
        "branches": [str(t)[len("rama/"):] for t in
                     arbre_data._as_list(meta.get("tags"))
                     if str(t).startswith("rama/")] or [other],
        "sources": len(srcs), "source_ids": srcs,
        "research_notes": has_research_notes(body),
        "photo": meta.get("photo"),
    }
    cache.notes[path] = (st, rec)
    return rec


def _raw(cache, path):
    st = arbre_data.stat_key(path)
    hit = cache.raw.get(path)
    if hit and hit[0] == st:
        return hit[1]
    val = _raw_items(arbre_data.read(path)) if st else {}
    cache.raw[path] = (st, val)
    return val


# ------------------------------------------------------------------- load

def load(tree_path, tree=None):
    """Read every person note. `tree` (arbre_data.load's result) is optional:
    its branches, families and fingerprint are reused when given. -> People:

    {
      "path", "fingerprint", "main": slug | None, "load_secs",
      "persons": {slug: Person},
      "branches": {key: {key, name, colour, family, founder,  # as configured
                         "root": slug | None,   # the founder, or derived
                         "members": [slug]}},    # tagged rama/<key>
      "families": {key: {key, label, title, "branches": [key],
                         "root": slug | None}},
      "items": {"<file>:<line>": {"people": [slug], "sources": [F0xx]}},
    }

    Person: {slug, name, given_name, surnames, aliases, sex, born, died,
    born_year, died_year, birth_place, death_place, living, father, mother
    (slugs or None), parents_confidence (proven | probable | None), spouses,
    children (deduced), branches (rama/ keys; the "other" key when none),
    sources (count), source_ids, research_notes (bool), photo,
    "pending": [ref], "contradictions": [ref], "discarded": [ref]}, where a
    ref is {file, line, title, kind} of a research item that links the person
    or names them (full name or an alias of two words or more, the rule of
    the tree's lookup.py). `pending` holds open work only: the "no repetir"
    search logs of pendientes.md are left out."""
    started = time.time()
    path = os.path.abspath(os.path.expanduser(tree_path))
    cache = _cache(path)
    cfg = arbre_data.load_config(path)
    paths = cfg["paths"]
    fp = (tree or {}).get("fingerprint") or arbre_data.fingerprint(path, paths)
    if cache.people and cache.people[0] == fp:
        return cache.people[1]

    other = cfg["other"]["key"]
    persons = {}
    for p in arbre_data._md_files(os.path.join(path, paths["people"])):
        rec = dict(_person(cache, p, other))
        rec.update(children=[], pending=[], contradictions=[], discarded=[])
        persons[rec["slug"]] = rec
    for rec in persons.values():
        for parent in (rec["father"], rec["mother"]):
            if parent in persons:
                persons[parent]["children"].append(rec["slug"])
    for rec in persons.values():
        rec["children"].sort(key=lambda s: _birth_key(persons[s]))

    items = _research(path, paths, cache, persons)

    branch_cfg = (tree or {}).get("branches") or \
        cfg["branches"] + [cfg["other"]]
    branches = {}
    for b in branch_cfg:
        members = sorted(s for s, r in persons.items()
                         if b["key"] in r["branches"])
        branches[b["key"]] = dict(b, members=members, root=None)
    for b in branches.values():
        b["root"] = _branch_root(persons, b)
    main = cfg.get("main") if cfg.get("main") in persons else None
    families = {}
    for f in (tree or {}).get("families") or cfg["families"]:
        keys = [b["key"] for b in branch_cfg if b.get("family") == f["key"]]
        families[f["key"]] = dict(f, branches=keys,
                                  root=_family_root(persons, keys, main))

    people = {"path": path, "fingerprint": fp, "main": main,
              "persons": persons, "branches": branches, "families": families,
              "items": items, "load_secs": round(time.time() - started, 3)}
    cache.people = (fp, people)
    return people


def _research(path, paths, cache, persons):
    """Link the research items to the people and sources they mention."""
    # Names by their first word, longest first: one pass over the words of
    # an item finds them all (a regex alternation of 600 names is 10x slower).
    forms = {}
    for slug, rec in persons.items():
        for form in [rec["name"], *rec["aliases"]]:
            words = tuple(fold(form).split())
            if len(words) >= 2:
                forms.setdefault(words, set()).add(slug)
    by_first = {}
    for words in sorted(forms, key=len, reverse=True):
        by_first.setdefault(words[0], []).append(words)
    rdir = os.path.join(path, paths["research"])
    items = {}
    files = (("pending", arbre_data.PENDING_FILE),
             ("contradictions", arbre_data.CONTRADICTIONS_FILE),
             ("discarded", arbre_data.DISCARDED_FILE))
    for what, name in files:
        fpath = os.path.join(rdir, name)
        parsed = {it["line"]: it for it in arbre_data._parsed(
            arbre_data._cache(path), fpath, arbre_data.parse_research)}
        for line, raw in _raw(cache, fpath).items():
            slugs = {m.group(2) for m in MD_LINK.finditer(raw)}
            slugs |= {m.group(1).strip() for m in WIKI_LINK.finditer(raw)}
            slugs = {s for s in slugs if s in persons}
            words = fold(arbre_data.plain(raw)).split()
            for i, w in enumerate(words):
                for cand in by_first.get(w, ()):
                    if tuple(words[i:i + len(cand)]) == cand:
                        slugs |= forms[cand]
                        break
            srcs = sorted(set(SOURCE_REF.findall(raw)),
                          key=lambda s: int(s[1:]))
            items[f"{name}:{line}"] = {"people": sorted(slugs), "sources": srcs}
            it = parsed.get(line) or {}
            kind = arbre_data.category_kind(it.get("category")) \
                if what == "pending" else what
            if kind == "searched":
                continue
            ref = {"file": name, "line": line, "kind": kind,
                   "title": it.get("title") or arbre_data.plain(raw)[:80]}
            for s in slugs:
                persons[s][what].append(ref)
    return items


def _birth_key(rec):
    y = rec.get("born_year")
    return (y is None, y or 0, rec.get("name") or "")


def _branch_root(persons, branch):
    founder = branch.get("founder")
    if founder in persons:
        return founder
    members = set(branch["members"])
    if not members:
        return None
    roots = [s for s in members
             if persons[s]["father"] not in members and
             persons[s]["mother"] not in members]
    best = max(roots or members, key=lambda s: (
        len(_descendants(persons, s, members)),
        -(persons[s]["born_year"] or 9999), persons[s]["name"]))
    return best


def _family_root(persons, keys, main):
    if not keys:
        return None
    keys = set(keys)
    ancestors = set(ancestors_of(persons, main)) | {main} if main else set()
    best, best_key = None, None
    for s, r in persons.items():
        own = len(keys & set(r["branches"]))
        if not own:
            continue
        k = (-own, len(set(r["branches"]) - keys), s not in ancestors,
             r["born_year"] or 9999, r["name"])
        if best_key is None or k < best_key:
            best, best_key = s, k
    return best


def _descendants(persons, slug, within=None):
    out, todo = set(), [slug]
    while todo:
        cur = todo.pop()
        for c in persons.get(cur, {}).get("children", ()):
            if c not in out and (within is None or c in within):
                out.add(c)
                todo.append(c)
    return out


def ancestors_of(persons, slug):
    out, todo = set(), [slug]
    while todo:
        rec = persons.get(todo.pop())
        for p in (rec["father"], rec["mother"]) if rec else ():
            if p and p not in out:
                out.add(p)
                todo.append(p)
    return out


# ----------------------------------------------------------------- helpers

def pedigree(people, slug, depth=3):
    """The ancestors of `slug`, `depth` generations counting the person:

    {"slug", "name", "person": Person | None (a link to a missing note),
     "confidence": the person's parents_confidence (of the links to the two
                   nodes below),
     "father": node | None, "mother": node | None,  # None: not recorded
     "more": bool}   # on the last generation: they have parents beyond it

    On the last generation `father`/`mother` are None and `more` says whether
    the tree knows more. Cycles stop the walk."""
    persons = people["persons"]

    def node(s, gen, seen):
        rec = persons.get(s)
        out = {"slug": s, "name": rec["name"] if rec else s, "person": rec,
               "confidence": rec.get("parents_confidence") if rec else None,
               "father": None, "mother": None, "more": False}
        if not rec:
            return out
        if gen >= depth or s in seen:
            out["more"] = bool(rec["father"] or rec["mother"])
            return out
        for role in ("father", "mother"):
            if rec[role]:
                out[role] = node(rec[role], gen + 1, seen | {s})
        return out

    return node(slug, 1, frozenset()) if slug else None


def generations(people, branch_key):
    """{slug: generation} of the members of a branch, the root being 0, by
    walking children down from it inside the branch; members the walk does
    not reach are left out."""
    b = people["branches"].get(branch_key)
    if not b or not b["root"]:
        return {}
    members = set(b["members"])
    persons = people["persons"]
    gen = {b["root"]: 0}
    todo = [b["root"]]
    while todo:
        cur = todo.pop(0)
        for c in persons[cur]["children"]:
            if c in members and c not in gen:
                gen[c] = gen[cur] + 1
                todo.append(c)
    return gen


def branch_people(people, branch_key):
    """The members of a branch: by generation from its root, then by birth
    year and name; those the root's line does not reach go last, by birth
    year and name."""
    b = people["branches"].get(branch_key)
    if not b:
        return []
    persons = people["persons"]
    gen = generations(people, branch_key)
    return [persons[s] for s in sorted(b["members"], key=lambda s: (
        s not in gen, gen.get(s, 0), *_birth_key(persons[s])))]


def family_people(people, family_key):
    """The members of every branch of a family, without repeats."""
    fam = people["families"].get(family_key) or {}
    seen = []
    for k in fam.get("branches", ()):
        for s in people["branches"].get(k, {}).get("members", ()):
            if s not in seen:
                seen.append(s)
    return [people["persons"][s] for s in seen]


def completeness(people, branch_key=None, family=None, members=None):
    """How documented the members of a branch (or a family, or a given list
    of slugs) are:

    {"people", "with_sources", "without_sources", "parents_proven",
     "parents_probable", "parents_missing" (neither parent recorded),
     "parents_partial" (only one), "with_birth", "with_research_notes",
     "with_pending" (open items in pendientes.md), "pending_items",
     "contradictions" (people with one)}"""
    persons = people["persons"]
    if members is None:
        if family:
            members = [r["slug"] for r in family_people(people, family)]
        else:
            members = people["branches"].get(branch_key, {}).get("members", [])
    recs = [persons[s] for s in members if s in persons]
    c = {"people": len(recs)}
    c["with_sources"] = sum(1 for r in recs if r["sources"])
    c["without_sources"] = c["people"] - c["with_sources"]
    both = [r for r in recs if r["father"] or r["mother"]]
    c["parents_proven"] = sum(1 for r in both
                              if r["parents_confidence"] == "proven")
    c["parents_probable"] = sum(1 for r in both
                                if r["parents_confidence"] != "proven")
    c["parents_missing"] = c["people"] - len(both)
    c["parents_partial"] = sum(1 for r in both
                               if not (r["father"] and r["mother"]))
    c["with_birth"] = sum(1 for r in recs if r["born_year"])
    c["with_research_notes"] = sum(1 for r in recs if r["research_notes"])
    c["with_pending"] = sum(1 for r in recs if r["pending"])
    c["pending_items"] = len({(i["file"], i["line"]) for r in recs
                              for i in r["pending"]})
    c["contradictions"] = sum(1 for r in recs if r["contradictions"])
    return c


def line_of_descent(people, root, target=None):
    """The chain of slugs from `root` down to `target` (default: `main`),
    or [] when target does not descend from root."""
    target = target or people.get("main")
    persons = people["persons"]
    if not root or not target or root not in persons:
        return []
    chain, cur, seen = [target], target, set()
    while cur != root:
        rec = persons.get(cur)
        if not rec or cur in seen:
            return []
        seen.add(cur)
        nxt = [p for p in (rec["father"], rec["mother"])
               if p and (p == root or root in ancestors_of(persons, p))]
        if not nxt:
            return []
        cur = nxt[0]
        chain.append(cur)
    return chain[::-1]


def item_refs(people, item):
    """The people and sources an arbre_data item mentions: {people, sources}."""
    if not item:
        return {"people": [], "sources": []}
    hit = people["items"].get(f"{item.get('file')}:{item.get('line')}")
    if hit:
        return hit
    text = " ".join(str(item.get(k) or "") for k in ("id", "title", "text"))
    srcs = sorted(set(SOURCE_REF.findall(text)), key=lambda s: int(s[1:]))
    return {"people": [], "sources": srcs}


if __name__ == "__main__":
    # `people.py [tree] [slug]`: timings, a branch summary, a pedigree.
    import json
    target = sys.argv[1] if len(sys.argv) > 1 else "~/src/arbre"
    t0 = time.time()
    ppl = load(target)
    t1 = time.time()
    load(target)
    t2 = time.time()
    print(f"load {t1 - t0:.3f}s, reload {t2 - t1:.4f}s, "
          f"{len(ppl['persons'])} people")
    for key, b in ppl["branches"].items():
        print(f"{key:22} root={b['root']} {json.dumps(completeness(ppl, key))}")
    for key, f in ppl["families"].items():
        print(f"family {key}: root={f['root']}")
    if len(sys.argv) > 2:
        print(json.dumps(pedigree(ppl, sys.argv[2]), default=lambda o: None,
                         ensure_ascii=False, indent=1)[:3000])
