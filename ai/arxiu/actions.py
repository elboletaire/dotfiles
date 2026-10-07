"""The board's actions on the tree's agents: per kind of selection (a
family, a branch, a person, a pending item), the keys, their Catalan labels
and the prompt each one builds.

Stdlib only. A lowercase key types the prompt into the orchestrator's input
(`[arbre].orchestrator_agent`, below the board) without sending it, and
focuses it: nothing runs until the user reads it and presses Enter there. The
uppercase key sends the same prompt to the background research agent
(`[arbre].research_agent`), starting it first when needed; the board asks for
a second press before that. Either way the action goes into the queue
(research_queue.py). See CONTRACT.md.

Prompts are in Catalan (the user talks to the tree's agents in Catalan; the
tree's content stays Spanish), one line, and name the skill, the people (full
name and slug), the branch and the family, with `uv run scripts/lookup.py`
as the starting point.
"""
import os

import agents
import arbre_data
import research_queue

ITEM_TEXT_MAX = 700    # how much of an item's text goes into a prompt

# Catalan labels of arbre_data's item kinds, in the board's order.
KIND_LABEL = {"docs": "documents a aconseguir",
              "people": "persones per identificar o completar",
              "cut": "branques que es tallen",
              "photos": "fotos per identificar",
              "leads": "pistes de cerques",
              "other": "altres pendents",
              "contradictions": "incoherències",
              "review": "fonts de la IA per revisar"}
# What the agent is asked to do with each kind of item.
KIND_VERB = {"contradictions": "resoldre aquesta incoherència",
             "review": "preparar la revisió d'aquesta font trobada per la IA"}

# kind -> [(key, what, label)]. The uppercase twin of each key sends the
# same prompt to the research agent instead of prefilling the orchestrator.
CATALOGUE = {
    "family": [("r", "research", "investiga la família")],
    "branch": [("r", "research", "investiga la branca")],
    "person": [("r", "research", "investiga la persona"),
               ("e", "interview", "preguntes d'entrevista")],
    "item": [("i", "item", "investiga el punt")],
}


def catalogue(kind):
    """-> [{key, what, label, mode}] for a selection kind: each lowercase
    action (mode "prefill") and its uppercase twin (mode "send")."""
    out = []
    for key, what, label in CATALOGUE.get(kind, []):
        out.append({"key": key, "what": what, "label": label,
                    "mode": "prefill"})
        out.append({"key": key.upper(), "what": what, "label": label,
                    "mode": "send"})
    return out


def find(kind, key):
    """The action `key` does on a selection of `kind`, or None."""
    return next((a for a in catalogue(kind) if a["key"] == key), None)


# ---------------------------------------------------------------- naming

def clip(text, n):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:max(0, n - 1)].rstrip() + "…"


def family_of(tree, key):
    """families.yml's family `key` -> {key, label, title}; a heading no
    family matches ("~general") gets its own label."""
    for f in tree.get("families") or []:
        if f.get("key") == key:
            return f
    label = (key or "").lstrip("~").capitalize() or "General"
    return {"key": key, "label": label, "title": label}


def branch_of(tree, key):
    return next((b for b in tree.get("branches") or []
                 if b.get("key") == key), None)


def row_of(tree, selection):
    """The branch-table row of a selection (its `row` id, else the first
    row holding its branch), or None."""
    rows = tree.get("rows") or []
    rid = selection.get("row")
    if rid:
        hit = next((r for r in rows if r.get("id") == rid), None)
        if hit:
            return hit
    b = selection.get("branch")
    return next((r for r in rows if b and b in r.get("branches", [])), None)


def branch_list(tree, keys):
    """"Alonso (`alonso`) i Espino (`espino`)"."""
    names = []
    for k in keys:
        b = branch_of(tree, k)
        names.append(f"{b['name']} (`{k}`)" if b else f"`{k}`")
    if len(names) > 1:
        return ", ".join(names[:-1]) + " i " + names[-1]
    return names[0] if names else ""


def counts_text(rows):
    pend = sum(r.get("counts", {}).get("pending", 0) for r in rows)
    contra = sum(r.get("counts", {}).get("contradictions", 0) for r in rows)
    review = sum(r.get("counts", {}).get("review", 0) for r in rows)
    bits = [f"{pend} pendents"]
    if contra:
        bits.append(f"{contra} incoherències")
    if review:
        bits.append(f"{review} fonts per revisar")
    return ", ".join(bits[:-1]) + " i " + bits[-1] if len(bits) > 1 \
        else bits[0]


def research_files(tree):
    rdir = (tree.get("paths") or {}).get("research") or "research"
    return (f"{rdir}/{arbre_data.PENDING_FILE}",
            f"{rdir}/{arbre_data.CONTRADICTIONS_FILE}")


def lookup_cmd(*queries):
    return "`uv run scripts/lookup.py " + " ".join(queries) + "`"


def person_name(person, slug):
    if not person:
        return slug
    name = person.get("name") or " ".join(
        x for x in (person.get("given_name"), person.get("surnames")) if x)
    return name or slug


def life(person):
    """" (n. 1923, m. 1990)" from a person's dates, or ""."""
    bits = []
    if person and person.get("born"):
        bits.append(f"n. {person['born']}")
    if person and person.get("died"):
        bits.append(f"m. {person['died']}")
    return f" ({', '.join(bits)})" if bits else ""


# ---------------------------------------------------------------- prompts

def family_prompt(cfg, tree, sel):
    skill = cfg["arbre"].get("research_skill") or "genealogy-research"
    fam = family_of(tree, sel.get("family"))
    rows = [r for r in tree.get("rows") or [] if r.get("family") == fam["key"]]
    # The family's own branches: not the "other" one (everyone untagged),
    # which a family's "Otras familias" heading points at.
    keys = []
    for r in rows:
        for k in r.get("branches", []):
            b = branch_of(tree, k)
            if k not in keys and (b is None or b.get("family")):
                keys.append(k)
    pend, inc = research_files(tree)
    where = f"la {fam['label']}" + (f" (`{fam['key']}` a families.yml)"
                                    if not str(fam["key"]).startswith("~")
                                    else "")
    parts = [f"Fes servir la skill {skill} per investigar {where}"
             + (f", de les rames {branch_list(tree, keys)}." if keys else ".")]
    parts.append(f"Comença pels seus punts oberts ({counts_text(rows)}) a "
                 f"{pend} i {inc}, a la secció «{fam.get('title')}».")
    if keys:
        parts.append("Punt de partida: " + lookup_cmd(*(f"rama/{k}"
                                                        for k in keys))
                     + " (la gent de cada rama i els seus punts oberts) i, per "
                     "a cada persona, " + lookup_cmd("<slug>") + ".")
    else:
        parts.append("Per a cada persona, el punt de partida és "
                     + lookup_cmd("<slug>") + ".")
    parts.append("Abans de cercar, digues-me per quins punts començaràs i "
                 "quines cerques poden anar en paral·lel.")
    return " ".join(parts)


def branch_prompt(cfg, tree, sel):
    skill = cfg["arbre"].get("research_skill") or "genealogy-research"
    row = row_of(tree, sel) or {}
    keys = row.get("branches") or ([sel["branch"]] if sel.get("branch")
                                   else [])
    title = row.get("title") or branch_list(tree, keys)
    fam = family_of(tree, row.get("family") or sel.get("family"))
    pend, inc = research_files(tree)
    parts = [f"Fes servir la skill {skill} per investigar la branca "
             f"«{title}» de la {fam['label']}"
             + (f" (rames {branch_list(tree, keys)})." if keys else ".")]
    parts.append(f"Comença pels seus punts oberts ({counts_text([row])}) a "
                 f"{pend} i {inc}, a la secció «{title}».")
    if keys:
        parts.append("Punt de partida: " + lookup_cmd(*(f"rama/{k}"
                                                        for k in keys))
                     + " (la gent de la branca i els seus punts oberts) i, "
                     "per a cada persona, " + lookup_cmd("<slug>") + ".")
    parts.append("Abans de cercar, digues-me per quins punts començaràs.")
    return " ".join(parts)


def _person_where(tree, sel):
    fam = family_of(tree, sel.get("family"))
    b = branch_of(tree, sel.get("branch"))
    if b:
        return f"de la rama {b['name']} (`{b['key']}`) de la {fam['label']}"
    return f"de la {fam['label']}"


def person_prompt(cfg, tree, sel, person=None):
    skill = cfg["arbre"].get("research_skill") or "genealogy-research"
    slug = sel["person"]
    name = person_name(person, slug)
    pend, inc = research_files(tree)
    return " ".join([
        f"Fes servir la skill {skill} per investigar només {name}"
        f"{life(person)} (`{slug}`), {_person_where(tree, sel)}.",
        "Punt de partida: " + lookup_cmd(slug) + " (fitxa, família, fonts i "
        "punts oberts).",
        f"Comença pels seus punts oberts a {pend} i {inc}; altres persones, "
        "només si cal per identificar-la.",
        "Abans de cercar, digues-me què buscaràs i on."])


def interview_prompt(cfg, tree, sel, person=None):
    skill = cfg["arbre"].get("interview_skill") or "family-interview"
    slug = sel["person"]
    name = person_name(person, slug)
    return " ".join([
        f"Fes servir la skill {skill} per preparar una entrevista a {name}"
        f"{life(person)} (`{slug}`), {_person_where(tree, sel)}: és el "
        "familiar a qui farem les preguntes.",
        "Punt de partida: " + lookup_cmd("--family", slug) + " (els seus "
        "parents, amb noms i dates) i " + lookup_cmd("--items", "<slug>...")
        + " per als parents de qui pot parlar.",
        "Dona'm només la llista numerada de preguntes, en castellà, agrupades "
        "per persona i les més importants primer (10-15), sobre el que pot "
        "saber de primera mà: pares, avis, germans, oncles, cosins, i els "
        "documents i fotos que guardi.",
        "No registris res encara: les respostes vindran després."])


def item_prompt(cfg, tree, sel, refs=None):
    """The research prompt for one pending item: names it, its branch and
    its category, and asks for the research skill. `refs` are the person
    slugs and source ids it mentions (people.item_refs), the lookup's
    starting point; without them, its branches."""
    skill = cfg["arbre"].get("research_skill") or "genealogy-research"
    item = sel["item"]
    row = row_of(tree, sel) or {}
    keys = row.get("branches") or []
    verb = KIND_VERB.get(item.get("kind"), "investigar aquest punt pendent")
    kind = KIND_LABEL.get(item.get("kind"), item.get("kind") or "")
    cat = item.get("category")
    fam = family_of(tree, row.get("family") or sel.get("family"))
    where = (row.get("title") or "") + f" ({fam['label']})"
    title = f"{item['id']} — {item['title']}" if item.get("id") \
        else item["title"]
    parts = [f"Fes servir la skill {skill} per {verb} de l'arbre.",
             f"Branca: {where.strip()}.",
             f"Categoria: {kind}" + (f" («{cat}»)" if cat else "") + ".",
             f"Punt: «{title}»."]
    text = item.get("text") or ""
    if text and text != item["title"]:
        parts.append(f"Text a {item.get('file')}: "
                     f"«{clip(text, ITEM_TEXT_MAX)}»")
    else:
        parts.append(f"És a {item.get('file')}.")
    mentioned = [x for x in ([item["id"]] if item.get("id") else []) +
                 list(refs or []) if x]
    mentioned = list(dict.fromkeys(mentioned))[:6]
    if mentioned:
        parts.append("Punt de partida: " + lookup_cmd(*mentioned) + ".")
    elif keys:
        parts.append("Punt de partida: " + lookup_cmd(*(f"rama/{k}"
                                                        for k in keys))
                     + " i, per a cada persona que hi surti, "
                     + lookup_cmd("<slug>") + ".")
    return " ".join(parts)


# ---------------------------------------------------------------- plans

def _target(sel):
    kind = sel.get("kind")
    if kind == "family":
        return sel.get("family") or ""
    if kind == "branch":
        return sel.get("row") or sel.get("branch") or ""
    if kind == "person":
        return sel.get("person") or ""
    it = sel.get("item") or {}
    return it.get("id") or f"{it.get('file')}:{it.get('line')}"


def _label(tree, sel, what, person):
    kind = sel.get("kind")
    if what == "interview":
        return f"entrevista a {person_name(person, sel['person'])}"
    if kind == "family":
        return f"investigar la {family_of(tree, sel.get('family'))['label']}"
    if kind == "branch":
        row = row_of(tree, sel) or {}
        return f"investigar {row.get('title') or sel.get('branch')}"
    if kind == "person":
        return f"investigar {person_name(person, sel['person'])}"
    it = sel.get("item") or {}
    return "investigar «" + clip(it.get("id") and
                                 f"{it['id']} — {it.get('title')}"
                                 or it.get("title"), 60) + "»"


def build(cfg, tree, selection, key, person=None, refs=None):
    """The plan of the action `key` on `selection` (CONTRACT.md's shape;
    `person` is the selected person's record, for their name and dates;
    `refs`, the slugs and source ids an item mentions).
    -> {key, kind, what, mode, agent, target, label, prompt}, or None when
    the key does nothing there."""
    kind = selection.get("kind")
    act = find(kind, key)
    if not act:
        return None
    what = act["what"]
    if what == "interview":
        text = interview_prompt(cfg, tree, selection, person)
    elif kind == "family":
        text = family_prompt(cfg, tree, selection)
    elif kind == "branch":
        text = branch_prompt(cfg, tree, selection)
    elif kind == "person":
        text = person_prompt(cfg, tree, selection, person)
    else:
        text = item_prompt(cfg, tree, selection, refs)
    a = cfg["arbre"]
    agent = a.get("orchestrator_agent") if act["mode"] == "prefill" \
        else a.get("research_agent")
    return {"key": key, "kind": kind, "what": what, "mode": act["mode"],
            "agent": agent, "target": _target(selection),
            "label": _label(tree, selection, what, person), "prompt": text}


def run(cfg, plan, status=None, queue_path=None):
    """Carry out a plan: prefill the orchestrator, or send to the research
    agent (starting it first). Recorded in the queue when it worked (not in
    a dry run). -> (ok, message)."""
    if not plan.get("agent"):
        which = "orchestrator_agent" if plan["mode"] == "prefill" \
            else "research_agent"
        return False, f"[arbre].{which} buit a config.toml"
    if plan["mode"] == "prefill":
        ok, msg = agents.prefill(plan["agent"], plan["prompt"])
    else:
        ok, msg = agents.prompt_research(cfg, plan["prompt"], status)
    if ok and not agents.dry_run():
        try:
            research_queue.append(plan["kind"], plan["target"], plan["label"],
                               plan["agent"], plan["mode"], path=queue_path)
        except OSError as e:
            msg += f" (cua: {e})"
    return ok, msg

