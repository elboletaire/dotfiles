#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["rich>=13.7"]
# ///
"""Print Arxiu's right panel for the real tree, to eyeball it.

    uv run --script ai/arxiu/tools/panel_preview.py [--branch KEY |
        --family KEY | --person SLUG | --item N] [--width 60] [--height 40]
        [--tree PATH] [--wait] [--plain]

--item N picks the Nth pending item of the tree (in the board's row order).
--wait waits for the lookup card instead of showing the placeholder.
--plain prints without colours. A few fictional queue entries are shown.
"""
import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import arbre_data  # noqa: E402
import panel  # noqa: E402
import people as people_mod  # noqa: E402
from rich.console import Console  # noqa: E402


def items_of(tree):
    out = []
    for row in tree["rows"]:
        for bucket in ("pending", "contradictions"):
            for items in row[bucket].values():
                out.extend(items)
        out.extend(row["review"])
    return out


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--branch")
    g.add_argument("--family")
    g.add_argument("--person")
    g.add_argument("--item", type=int)
    ap.add_argument("--width", type=int, default=60)
    ap.add_argument("--height", type=int, default=40)
    ap.add_argument("--tree", default="~/src/arbre")
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--plain", action="store_true")
    a = ap.parse_args()

    path = os.path.expanduser(a.tree)
    t0 = time.time()
    tree = arbre_data.load(path)
    t1 = time.time()
    ppl = people_mod.load(path, tree)
    t2 = time.time()
    sel = {"kind": "family", "family": None, "branch": None, "person": None,
           "item": None}
    if a.branch:
        sel.update(kind="branch", branch=a.branch)
    elif a.person:
        sel.update(kind="person", person=a.person)
    elif a.item is not None:
        items = items_of(tree)
        sel.update(kind="item", item=items[a.item % len(items)])
    else:
        sel.update(family=a.family or next(
            (f["key"] for f in tree["families"] if f["default"]),
            tree["families"][0]["key"] if tree["families"] else None))
    now = time.time()
    queue = [
        {"id": "q1", "at": now - 40, "kind": "person", "target": "x",
         "label": "Investigar el bateig", "agent": "investigacio",
         "mode": "send", "status": "working"},
        {"id": "q2", "at": now - 3600 * 3, "kind": "branch", "target": "y",
         "label": "Preparar entrevista a la família", "agent": "arbre",
         "mode": "prefill", "status": "waiting"},
        {"id": "q3", "at": now - 86400 * 2, "kind": "item", "target": "z",
         "label": "Resoldre la incoherència de dates", "agent": "investigacio",
         "mode": "send", "status": "done"},
        {"id": "q4", "at": now - 5, "kind": "item", "target": "z",
         "label": "Buscar la partida de matrimoni", "agent": "investigacio",
         "mode": "send", "status": "sent"},
    ]
    done = threading.Event()
    panel.set_on_ready(done.set)
    r = panel.render(tree, ppl, sel, queue, a.width, a.height)
    t3 = time.time()
    if a.wait and panel.pending_lookups():
        done.wait(90)
        r = panel.render(tree, ppl, sel, queue, a.width, a.height)
    con = Console(width=a.width, no_color=a.plain, force_terminal=not a.plain,
                  highlight=False)
    con.print(r)
    print(f"[tree {t1 - t0:.3f}s · people {t2 - t1:.3f}s · render "
          f"{t3 - t2:.3f}s]", file=sys.stderr)


if __name__ == "__main__":
    main()
