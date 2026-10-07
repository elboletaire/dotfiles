#!/usr/bin/env python3
"""Preview Tecla's pixel art in a truecolor terminal, from the very maps the
mod draws (hooks/art.ts), as the mod draws them: half blocks, each cell two
stacked pixels (▀ over a truecolor foreground and background).

    python3 tools/preview.py                  every pose, full and mini
    python3 tools/preview.py reading          the frames of one pose
    python3 tools/preview.py reading --anim   play it (ctrl+c stops)
    python3 tools/preview.py --anim           play every pose in turn
    python3 tools/preview.py --mini ...       the 8-row version
    python3 tools/preview.py --frames         every frame by name

Poses: idle, reading, stamping, ladder, puzzled, happy, sleepy, lookup.
"""
import json
import os
import re
import sys
import time

ART_TS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks", "art.ts")


def load_art(path=ART_TS):
    """The JSON object between `export const ART =` and `as const`."""
    text = open(path, encoding="utf-8").read()
    m = re.search(r"export const ART\s*=\s*(\{.*\})\s*as const", text, re.S)
    if not m:
        sys.exit(f"no `export const ART = {{...}} as const` in {path}")
    body = re.sub(r",(\s*[}\]])", r"\1", m.group(1))  # forgive trailing commas
    return json.loads(body)


ART = load_art()


def frame(size, name, depth=0):
    d = ART[size][name]
    if "rows" in d:
        return list(d["rows"])
    rows = frame(size, d["from"], depth + 1)
    for i, row in d["patch"].items():
        rows[int(i)] = row
    return rows


def rgb(hexc):
    return tuple(int(hexc[i:i + 2], 16) for i in (1, 3, 5))


PAL = {k: rgb(v) for k, v in ART["palette"].items()}
RESET = "\x1b[0m"


def fg(c):
    return "\x1b[38;2;%d;%d;%dm" % c


def bg(c):
    return "\x1b[48;2;%d;%d;%dm" % c


def cells(px):
    """Pairs of pixel rows -> one line of half blocks per pair, transparent
    halves left to the terminal's background (the mod's default colour)."""
    width = max(len(r) for r in px)
    out = []
    for y in range(0, len(px), 2):
        top = px[y].ljust(width, ".")
        bot = (px[y + 1] if y + 1 < len(px) else "").ljust(width, ".")
        line = ""
        for t, b in zip(top, bot):
            if t == "." and b == ".":
                line += RESET + " "
            elif b == ".":
                line += RESET + fg(PAL[t]) + "▀"
            elif t == ".":
                line += RESET + fg(PAL[b]) + "▄"
            else:
                line += fg(PAL[t]) + bg(PAL[b]) + "▀"
        out.append(line + RESET)
    return out


def row_of(blocks, labels, width):
    print("  " + "".join(f"{label:<{width + 2}}" for label in labels))
    for lines in zip(*blocks):
        print("  " + "  ".join(lines))
    print()


def show(size, names, labels=None):
    width = len(frame(size, names[0])[0])
    per = max(1, (os.get_terminal_size().columns - 2) // (width + 2)) if sys.stdout.isatty() else 6
    labels = labels or names
    for i in range(0, len(names), per):
        row_of([cells(frame(size, n)) for n in names[i:i + per]], labels[i:i + per], width)


def poses():
    return list(ART["poses"])


def anim(size, which):
    steps = [(p, n, ms) for p in which for _ in range(2 if len(which) > 1 else 1) for n, ms in ART["poses"][p]]
    height = len(cells(frame(size, "idle")))
    print("\n" * (height + 1), end="")
    try:
        while True:
            for pose, name, ms in steps:
                print(f"\x1b[{height + 1}A", end="")
                print(f"  \x1b[1m{pose}\x1b[0m · {name}\x1b[K")
                for line in cells(frame(size, name)):
                    print("  " + line + "\x1b[K")
                sys.stdout.flush()
                time.sleep(ms / 1000)
    except KeyboardInterrupt:
        print(RESET)


def main(argv):
    size = "mini" if "--mini" in argv else "full"
    args = [a for a in argv if not a.startswith("--")]
    for a in args:
        if a not in ART["poses"]:
            sys.exit(f"unknown pose {a!r}; poses: {', '.join(poses())}")
    if "--anim" in argv:
        anim(size, args or poses())
        return
    print()
    if "--frames" in argv:
        show(size, list(ART[size]))
    elif args:
        for p in args:
            names = list(dict.fromkeys(n for n, _ in ART["poses"][p]))
            print(f"  \x1b[1m{p}\x1b[0m")
            show(size, names)
    else:
        for s in ([size] if "--mini" in argv else ["full", "mini"]):
            show(s, [ART["poses"][p][0][0] for p in poses()], poses())


if __name__ == "__main__":
    main(sys.argv[1:])
