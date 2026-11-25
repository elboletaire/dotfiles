#!/usr/bin/env python3
"""Draws the messenger octopus poses as SVG, one file per frame.

`python3 make.py` rewrites art/svg/*.svg. `--png` also renders
art/png/<name>-320.png (320 px tall) with inkscape, or magick when inkscape is missing.
"""

import math
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 200, 240

PALETTES = {
    "warm": dict(hi="#ffd3c2", base="#f47f6a", mid="#d25f73", shade="#7a3e8c", ink="#3b2145",
                 sclera="#fff8f4", blush="#ff9fae", suck="#ffe3d8", puff="#ffffff", alarm="#ffc53d"),
    "grey": dict(hi="#eeeff3", base="#c4c7cf", mid="#a2a6b0", shade="#6c717d", ink="#3d4048",
                 sclera="#f4f5f7", blush=None, suck="#e6e7ec", puff="#ffffff", alarm="#c4c7cf"),
}

# Where the tentacles leave the mantle (hidden under it) and where they rest.
STARTS = [(50, 140), (67, 142), (83, 144), (96, 146), (104, 146), (117, 144), (133, 142), (150, 140)]
REST_ENDS = [(24, 212), (42, 224), (66, 228), (92, 231), (110, 231), (136, 228), (158, 224), (178, 210)]

MANTLE = "M32 118 C30 58 60 22 100 22 C140 22 170 58 168 118 C167 146 146 158 100 158 C54 158 33 146 32 118Z"

# Each pose is a list of frames; a frame overrides the defaults in draw().
FRAMES = {
    "idle-0": dict(lid=0.55, pupil=(0, 2.5), dy=0),
    "idle-1": dict(lid=0.7, pupil=(0, 2.5), dy=-2, puff=True),
    "talking-0": dict(lid=0.5, pupil=(0, 2.5), mouth="flat"),
    "talking-1": dict(lid=0.5, pupil=(0, 2.5), mouth="open"),
    "working-0": dict(lid=0.3, pupil=(0, 4), ends={2: (64, 186)}),
    "working-1": dict(lid=0.3, pupil=(0, 4), ends={5: (136, 186)}, sweat=True),
    "blocked-0": dict(lid=0, pupil=(0, 0), pupil_r=3.5, mouth="o", alarm=True,
                      ends={0: (18, 112), 7: (188, 92)}),
    "blocked-1": dict(lid=0, pupil=(-1.5, 0), pupil_r=3.5, mouth="o", alarm=True, dy=-1,
                      ends={0: (16, 116), 7: (184, 100)}),
    "sleeping-0": dict(closed=True, mouth="flat", dy=0, z=[(146, 66, 12), (164, 44, 9)]),
    "sleeping-1": dict(closed=True, mouth="flat", dy=-2, z=[(148, 56, 16), (168, 30, 12)]),
    "offline-0": dict(closed=True, mouth="flat", palette="grey"),
    "happy-0": dict(eye="happy", mouth="smile", ends={0: (18, 176), 7: (182, 184)}),
    "happy-1": dict(eye="happy", mouth="smile", ends={0: (24, 164), 7: (176, 168)}, sparkle=True, dy=-2),
    "worried-0": dict(lid=0.15, pupil=(-1.5, -2), brows=True, mouth="wavy"),
    "worried-1": dict(lid=0.15, pupil=(-1.5, -2), brows=True, mouth="wavy", dy=-1, sweat=True),
    "sad-0": dict(lid=0.6, pupil=(0, 5), mouth="frown_deep", tear=True),
    "sad-1": dict(lid=0.6, pupil=(0, 5), mouth="frown_deep", tear=True, dy=-1),
    "surprised-0": dict(lid=0, pupil_r=3.5, mouth="o_big", burst=True),
    "surprised-1": dict(lid=0, pupil=(0, -1), pupil_r=4.5, mouth="o_big", burst=True, dy=-2),
    "doze-0": dict(closed=True, mouth="flat", dy=-1),
}


def bezier(p0, p1, p2, p3, t):
    u = 1 - t
    return (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


def tentacle(start, end, ink, p):
    """A tapered tentacle along a cubic curve, with suckers on its near side."""
    (x0, y0), (x1, y1) = start, end
    c1 = (x0 + (x1 - x0) * 0.1, y0 + 42)
    c2 = (x1 - (x1 - x0) * 0.15, y1 - 24)
    n = 30
    left, right, dots = [], [], []
    for i in range(n + 1):
        t = i / n
        x, y = bezier(start, c1, c2, end, t)
        ax, ay = bezier(start, c1, c2, end, max(0, t - 0.01))
        bx, by = bezier(start, c1, c2, end, min(1, t + 0.01))
        tx, ty = bx - ax, by - ay
        length = math.hypot(tx, ty) or 1
        nx, ny = -ty / length, tx / length
        w = 12 + (2.5 - 12) * t
        left.append((x + nx * w, y + ny * w))
        right.append((x - nx * w, y - ny * w))
        if i in (9, 13, 17, 21):
            dots.append(f'<circle cx="{x + nx * w * 0.45:.1f}" cy="{y + ny * w * 0.45:.1f}" '
                        f'r="{max(0.9, w * 0.2):.1f}" fill="{p["suck"]}" opacity=".6"/>')
    pts = left + right[::-1]
    d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + "Z"
    return (f'<path d="{d}" fill="url(#tent)" stroke="{p["shade"]}" stroke-opacity=".25" '
            f'stroke-width=".8"/>' + "".join(dots))


def eye(cx, cy, f, p):
    ink = p["ink"]
    if f.get("eye") == "happy":
        return (f'<path d="M{cx - 9} {cy + 3} Q{cx} {cy - 6} {cx + 9} {cy + 3}" fill="none" '
                f'stroke="{ink}" stroke-width="2.6" stroke-linecap="round"/>')
    if f.get("closed"):
        return (f'<path d="M{cx - 9} {cy + 1} Q{cx} {cy + 6} {cx + 9} {cy + 1}" fill="none" '
                f'stroke="{ink}" stroke-width="2.6" stroke-linecap="round"/>')
    r = 13
    px, py = f.get("pupil", (0, 0))
    pr = f.get("pupil_r", 6)
    out = [
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{p["sclera"]}" stroke="{ink}" stroke-width="1.6"/>',
        f'<circle cx="{cx + px}" cy="{cy + py}" r="{pr}" fill="{ink}"/>',
        f'<circle cx="{cx + px - pr * 0.35:.1f}" cy="{cy + py - pr * 0.4:.1f}" r="{pr * 0.3:.1f}" fill="#ffffff" opacity=".9"/>',
    ]
    lid = f.get("lid", 0.5)
    if lid > 0:
        ly = cy - r + 2 * r * lid
        dx = math.sqrt(max(r * r - (ly - cy) ** 2, 0))
        large = 1 if ly > cy else 0
        out.append(f'<path d="M{cx - dx:.2f} {ly:.2f} A{r} {r} 0 {large} 1 {cx + dx:.2f} {ly:.2f}Z" fill="url(#body)"/>')
        out.append(f'<path d="M{cx - dx:.2f} {ly:.2f} L{cx + dx:.2f} {ly:.2f}" stroke="{ink}" '
                   f'stroke-width="1.8" stroke-linecap="round"/>')
    return "".join(out)


def mouth(kind, p):
    ink = p["ink"]
    if kind == "open":
        return f'<ellipse cx="100" cy="134" rx="5.5" ry="6.2" fill="{ink}"/>'
    if kind == "o":
        return f'<ellipse cx="100" cy="134" rx="4" ry="5" fill="{ink}"/>'
    if kind == "flat":
        return f'<path d="M94 133 L106 133" stroke="{ink}" stroke-width="2.2" stroke-linecap="round"/>'
    if kind == "o_big":
        return f'<ellipse cx="100" cy="135" rx="5.5" ry="7.5" fill="{ink}"/>'
    if kind == "smile":
        return f'<path d="M90 131 Q100 140 110 131" fill="none" stroke="{ink}" stroke-width="2.2" stroke-linecap="round"/>'
    if kind == "frown_deep":
        return f'<path d="M90 139 Q100 128 110 139" fill="none" stroke="{ink}" stroke-width="2.2" stroke-linecap="round"/>'
    if kind == "wavy":
        return f'<path d="M90 136 Q95 130 100 136 T110 136" fill="none" stroke="{ink}" stroke-width="2.2" stroke-linecap="round"/>'
    return f'<path d="M92 133 Q100 127 108 133" fill="none" stroke="{ink}" stroke-width="2.2" stroke-linecap="round"/>'


def puff(p):
    # The sigh: three soft clouds drifting off the mouth.
    circles = [(150, 136, 7), (159, 127, 9), (168, 137, 6), (157, 142, 5)]
    return "".join(
        f'<circle cx="{x}" cy="{y}" r="{r}" fill="{p["puff"]}" opacity=".8" stroke="{p["shade"]}" '
        f'stroke-opacity=".25" stroke-width=".8"/>' for x, y, r in circles)


def tear():
    return ('<path d="M84 116 C86 121 88 124 88 126 A4 4 0 0 1 80 126 C80 124 82 121 84 116Z" '
            'fill="#8fd8ff" stroke="#3a8fc0" stroke-width=".8"/>')


def sparkle(p):
    x, y = 26, 70
    return (f'<path d="M{x} {y - 7} Q{x + 1.5} {y - 1.5} {x + 7} {y} Q{x + 1.5} {y + 1.5} {x} {y + 7} '
            f'Q{x - 1.5} {y + 1.5} {x - 7} {y} Q{x - 1.5} {y - 1.5} {x} {y - 7}Z" fill="#fff3a6" '
            f'stroke="{p["ink"]}" stroke-width=".6"/>')


def burst(p):
    # Pop lines round the head: the surprise mark, where blocked gets the "!".
    d = "M150 40 L143 34 M160 30 L157 21 M172 30 L178 22 M182 42 L190 38"
    # A light halo under the ink keeps the lines readable on dark backgrounds.
    return (f'<path d="{d}" fill="none" stroke="#fff3a6" stroke-width="5.4" stroke-linecap="round"/>'
            f'<path d="{d}" fill="none" stroke="{p["ink"]}" stroke-width="2.2" stroke-linecap="round"/>')


def sweat():
    return ('<path d="M150 56 C156 66 160 72 160 78 A10 10 0 0 1 140 78 C140 72 144 66 150 56Z" '
            'fill="#8fd8ff" stroke="#3a8fc0" stroke-width=".8"/>'
            '<ellipse cx="146" cy="76" rx="2" ry="3.5" fill="#ffffff" opacity=".8"/>')


def alarm(p):
    return (f'<circle cx="172" cy="36" r="11" fill="{p["alarm"]}" stroke="{p["ink"]}" stroke-width="1.2"/>'
            f'<rect x="170.5" y="28" width="3" height="11" rx="1.5" fill="{p["ink"]}"/>'
            f'<circle cx="172" cy="44.5" r="1.9" fill="{p["ink"]}"/>')


def zs(items, p):
    out = []
    for x, y, s in items:
        out.append(f'<path d="M{x} {y} h{s} l-{s} {s} h{s}" fill="none" stroke="{p["ink"]}" '
                   f'stroke-width="2.4" stroke-linejoin="round" opacity=".75"/>')
    return "".join(out)


def draw(frame):
    p = PALETTES[frame.get("palette", "warm")]
    dy = frame.get("dy", 0)
    ends = dict(enumerate(REST_ENDS))
    ends.update(frame.get("ends", {}))
    tentacles = "".join(tentacle(STARTS[i], ends[i], p["ink"], p) for i in range(len(STARTS)))
    face = []
    face.append(f'<path d="{MANTLE}" fill="url(#body)"/>')
    face.append('<path d="M150 46 C162 64 168 90 167 116" fill="none" stroke="%s" stroke-width="3" '
                'stroke-linecap="round" opacity=".7"/>' % p["hi"])
    face.append('<path d="M52 62 C62 42 78 32 92 30" fill="none" stroke="#ffffff" stroke-width="4" '
                'stroke-linecap="round" opacity=".3"/>')
    if p["blush"]:
        face.append(f'<ellipse cx="72" cy="126" rx="6" ry="3.5" fill="{p["blush"]}" opacity=".5"/>')
        face.append(f'<ellipse cx="128" cy="126" rx="6" ry="3.5" fill="{p["blush"]}" opacity=".5"/>')
    face.append(eye(78, 104, frame, p))
    face.append(eye(122, 104, frame, p))
    face.append(mouth(frame.get("mouth", "frown"), p))
    if frame.get("brows"):
        face.append(f'<path d="M66 94 L88 88 M112 88 L134 94" fill="none" stroke="{p["ink"]}" '
                    f'stroke-width="2.2" stroke-linecap="round"/>')
    extras = []
    if frame.get("tear"):
        extras.append(tear())
    if frame.get("sparkle"):
        extras.append(sparkle(p))
    if frame.get("puff"):
        extras.append(puff(p))
    if frame.get("sweat"):
        extras.append(sweat())
    if frame.get("alarm"):
        extras.append(alarm(p))
    if frame.get("burst"):
        extras.append(burst(p))
    if frame.get("z"):
        extras.append(zs(frame["z"], p))
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
        "<defs>",
        '<radialGradient id="body" cx="0.38" cy="0.3" r="0.75">'
        f'<stop offset="0" stop-color="{p["hi"]}"/><stop offset="0.55" stop-color="{p["base"]}"/>'
        f'<stop offset="0.9" stop-color="{p["mid"]}"/><stop offset="1" stop-color="{p["shade"]}"/>'
        "</radialGradient>",
        '<linearGradient id="tent" gradientUnits="userSpaceOnUse" x1="100" y1="140" x2="100" y2="232">'
        f'<stop offset="0" stop-color="{p["base"]}"/><stop offset="1" stop-color="{p["mid"]}"/>'
        "</linearGradient>",
        '<radialGradient id="shadow">'
        f'<stop offset="0" stop-color="{p["shade"]}" stop-opacity=".45"/>'
        f'<stop offset="1" stop-color="{p["shade"]}" stop-opacity="0"/>'
        "</radialGradient>",
        "</defs>",
        '<ellipse cx="100" cy="233" rx="70" ry="7" fill="url(#shadow)"/>',
        tentacles,
        f'<g transform="translate(0 {dy})">',
        *face,
        "</g>",
        *extras,
        "</svg>",
    ]) + "\n"


def render(svg, png, height):
    if shutil.which("inkscape"):
        cmd = ["inkscape", svg, "--export-type=png", f"--export-filename={png}", f"--export-height={height}"]
    else:
        cmd = ["magick", "-background", "none", svg, "-resize", f"x{height}", png]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main(argv):
    svg_dir = os.path.join(HERE, "svg")
    png_dir = os.path.join(HERE, "png")
    os.makedirs(svg_dir, exist_ok=True)
    for name, frame in FRAMES.items():
        path = os.path.join(svg_dir, f"{name}.svg")
        with open(path, "w", encoding="utf-8") as f:
            f.write(draw(frame))
        print(path)
    if "--png" in argv:
        os.makedirs(png_dir, exist_ok=True)
        for name in FRAMES:
            png = os.path.join(png_dir, f"{name}-320.png")
            render(os.path.join(svg_dir, f"{name}.svg"), png, 320)
            print(png)


if __name__ == "__main__":
    main(sys.argv[1:])
