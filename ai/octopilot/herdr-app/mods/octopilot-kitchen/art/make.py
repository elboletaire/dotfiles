#!/usr/bin/env python3
"""Draws the takoyaki kitchen as layered SVG pieces and renders them to PNG at 2x.

`python3 make.py` rewrites art/svg/*.svg, art/png/*.png and ../atlas.js (where each
piece sits in the scene, for main.js). `--preview [mood]` also writes
art/svg/preview.png, the whole scene composed, to judge the art without the app.
Everything is drawn in scene coordinates (360x220); a piece's file is a crop of it.
"""

import math
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE_W, SCENE_H = 360, 220
SCALE = 2

# The pan: holes spread over PAN_W from PAN_X; a ball's centre is at BALL_Y.
PAN_X, PAN_W, PAN_TOP, PAN_FACE, PAN_RIM = 134, 216, 126, 34, 8
BALL_Y, BALL_R = 138, 13
# A ball sprite's canvas, and the ball's centre in it (room above for the flag).
SPRITE_W, SPRITE_H, SPRITE_CX, SPRITE_CY = 40, 48, 20, 26
ARM_POSES = 6
COUNTER_Y = 152
SHELF_X, SHELF_ROWS, SHELF_PITCH, SHELF_PER_ROW = 184, (58, 98), 42, 4
BOAT_W, BOAT_H = 38, 24

WARM = dict(hi="#ffcdb8", base="#f4705c", mid="#dc5160", shade="#8a3a70", ink="#3b2145",
            suck="#ffe3d8", blush="#ff9fae")
FLUSH = dict(WARM, hi="#ffb3a6", base="#e84a4f", mid="#c5334c", shade="#7a2a62")

MANTLE = ("M24 104 C22 60 42 32 70 32 C98 32 118 60 116 104 "
          "C115 124 100 133 70 133 C40 133 25 124 24 104Z")
EYES = ((53, 95), (87, 95))
EYE_R = 10.5

MOODS = {
    "idle": dict(pupil=(2, 1), lid=0.12, mouth="smile"),
    "busy": dict(pupil=(3.5, 3), lid=0.14, mouth="tongue", brows="focus"),
    "flip": dict(pupil=(3.5, 2.5), lid=0.05, mouth="open", brows="up"),
    "pour": dict(pupil=(3, 4), lid=0.28, mouth="o", brows="focus"),
    "happy": dict(eye="happy", mouth="grin", sparkle=True, blush=0.85),
    "serve": dict(eye="wink", pupil=(2, 0), lid=0, mouth="grin", heart=True, blush=0.85),
    "worried": dict(pupil=(2.5, 1), pupil_r=3.6, lid=0.05, mouth="wavy", brows="worry",
                    sweat=True, palette="flush"),
    "sad": dict(pupil=(0, 3), pupil_r=6, lid=0.32, mouth="frown", brows="worry", tears=True,
                palette="flush"),
    "surprised": dict(pupil=(1, 0), pupil_r=3.2, lid=0, mouth="o_big", pop=True),
    "sleep": dict(eye="closed", mouth="o_tiny", zs=True, bubble=True),
    "doze": dict(pupil=(0, 4), lid=0.62, mouth="flat", doze_z=True),
}


def f1(v):
    return f"{v:.1f}"


def mix(a, b, k):
    k = max(0.0, min(1.0, k))
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * (1 - k) + y * k):02x}" for x, y in zip(ca, cb))


def defs():
    out = ["<defs>"]
    for name, p in (("w", WARM), ("f", FLUSH)):
        out.append(
            f'<radialGradient id="body-{name}" gradientUnits="userSpaceOnUse" cx="56" cy="60" r="84">'
            f'<stop offset="0" stop-color="{p["hi"]}"/><stop offset=".5" stop-color="{p["base"]}"/>'
            f'<stop offset=".86" stop-color="{p["mid"]}"/><stop offset="1" stop-color="{p["shade"]}"/>'
            "</radialGradient>"
            f'<linearGradient id="tent-{name}" gradientUnits="userSpaceOnUse" x1="0" y1="118" x2="0" y2="176">'
            f'<stop offset="0" stop-color="{p["base"]}"/><stop offset="1" stop-color="{p["mid"]}"/>'
            "</linearGradient>"
            f'<linearGradient id="arm-{name}" gradientUnits="userSpaceOnUse" x1="100" y1="0" x2="340" y2="0">'
            f'<stop offset="0" stop-color="{p["mid"]}"/><stop offset=".25" stop-color="{p["base"]}"/>'
            f'<stop offset="1" stop-color="{p["base"]}"/></linearGradient>')
    out.append(f'<clipPath id="mantle"><path d="{MANTLE}"/></clipPath>')
    out.append(
        '<linearGradient id="wall" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#1f3344"/><stop offset="1" stop-color="#37596b"/></linearGradient>'
        '<radialGradient id="lamp" gradientUnits="userSpaceOnUse" cx="70" cy="70" r="150">'
        '<stop offset="0" stop-color="#ffc878" stop-opacity=".42"/>'
        '<stop offset=".6" stop-color="#ffb060" stop-opacity=".1"/>'
        '<stop offset="1" stop-color="#ffb060" stop-opacity="0"/></radialGradient>'
        '<linearGradient id="noren" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#a72f35"/><stop offset="1" stop-color="#d0443f"/></linearGradient>'
        '<linearGradient id="ctop" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#c98d58"/><stop offset="1" stop-color="#e6b47c"/></linearGradient>'
        '<linearGradient id="cfront" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#8f5d38"/><stop offset="1" stop-color="#5e3a22"/></linearGradient>'
        '<linearGradient id="plank" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#d3a06a"/><stop offset="1" stop-color="#8f6238"/></linearGradient>'
        '<linearGradient id="iron" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#5a5f6a"/><stop offset="1" stop-color="#33363d"/></linearGradient>'
        '<linearGradient id="ironrim" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#2a2c32"/><stop offset="1" stop-color="#15161a"/></linearGradient>'
        '<radialGradient id="hole" cx=".5" cy=".3" r=".8">'
        '<stop offset="0" stop-color="#0c0c0e"/><stop offset="1" stop-color="#26282d"/></radialGradient>'
        '<linearGradient id="steel" x1="0" y1="0" x2="1" y2="0">'
        '<stop offset="0" stop-color="#f4f7fa"/><stop offset="1" stop-color="#9aa6b2"/></linearGradient>'
        '<radialGradient id="fglow" cx=".5" cy=".5" r=".5">'
        '<stop offset="0" stop-color="#ffb24a" stop-opacity=".75"/>'
        '<stop offset="1" stop-color="#ff7a1a" stop-opacity="0"/></radialGradient>'
        '<filter id="soft" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="1.2"/></filter>'
        '<filter id="softer" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="2.6"/></filter>')
    out.append("</defs>")
    return "".join(out)


def svg_doc(box, body):
    x, y, w, h = box
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x} {y} {w} {h}" '
            f'width="{w}" height="{h}">{defs()}{body}</svg>\n')


# --- the room -----------------------------------------------------------------

def background():
    out = [f'<rect width="{SCENE_W}" height="{SCENE_H}" rx="10" fill="url(#wall)"/>']
    # Tiles: faint grout lines, brick-laid.
    for row, y in enumerate(range(22, COUNTER_Y, 22)):
        out.append(f'<path d="M0 {y} H{SCENE_W}" stroke="#ffffff" stroke-opacity=".05"/>')
        for x in range(18 if row % 2 else 0, SCENE_W, 36):
            out.append(f'<path d="M{x} {y} v22" stroke="#ffffff" stroke-opacity=".035"/>')
    out.append(f'<rect width="{SCENE_W}" height="{SCENE_H}" rx="10" fill="url(#lamp)"/>')
    # The noren: a short red curtain along the top, split into flaps, each with a crest.
    out.append('<rect x="0" y="0" width="360" height="5" fill="#3a2418"/>')
    flaps = 6
    fw = SCENE_W / flaps
    for i in range(flaps):
        x0, x1 = i * fw + 1, (i + 1) * fw - 1
        out.append(f'<path d="M{f1(x0)} 3 H{f1(x1)} V19 Q{f1((x0 + x1) / 2)} 24 {f1(x0)} 19Z" fill="url(#noren)"/>')
        out.append(f'<path d="M{f1(x0)} 3 V19" stroke="#7d1f27" stroke-opacity=".6"/>')
        cx = (x0 + x1) / 2
        out.append(f'<circle cx="{f1(cx)}" cy="12" r="4.2" fill="#fff3dc" opacity=".92"/>')
        out.append(f'<path d="M{f1(cx - 2.6)} 11.4 q1.3 -1.8 2.6 0 t2.6 0" fill="none" stroke="#a72f35" stroke-width="1"/>')
    out.append('<rect x="0" y="0" width="360" height="26" fill="#000000" opacity=".0"/>')
    # Clip the square top bar to the rounded panel.
    return (f'<clipPath id="panel"><rect width="{SCENE_W}" height="{SCENE_H}" rx="10"/></clipPath>'
            f'<g clip-path="url(#panel)">{"".join(out)}</g>')


def shelf():
    out = []
    x0, x1 = SHELF_X - 6, SHELF_X + SHELF_PITCH * SHELF_PER_ROW + 2
    for y in SHELF_ROWS:
        out.append(f'<rect x="{x0}" y="{y + 5}" width="{x1 - x0}" height="5" fill="#000000" opacity=".22" filter="url(#soft)"/>')
        for bx in (x0 + 14, x1 - 14):
            out.append(f'<path d="M{bx - 2} {y + 4} h4 v9 q-2 3 -4 0Z" fill="#23262c"/>')
        out.append(f'<rect x="{x0}" y="{y}" width="{x1 - x0}" height="5.5" rx="1.5" fill="url(#plank)"/>')
        out.append(f'<path d="M{x0 + 1.5} {y + .8} H{x1 - 1.5}" stroke="#f3cf9c" stroke-opacity=".8" stroke-width="1"/>')
    return "".join(out)


def counter():
    out = []
    top, front = COUNTER_Y, 198
    out.append(f'<clipPath id="cpanel"><rect width="{SCENE_W}" height="{SCENE_H}" rx="10"/></clipPath>')
    out.append('<g clip-path="url(#cpanel)">')
    out.append(f'<rect x="0" y="{top}" width="{SCENE_W}" height="{front - top}" fill="url(#ctop)"/>')
    for i, y in enumerate((top + 13, top + 27, top + 38)):
        out.append(f'<path d="M0 {y} H{SCENE_W}" stroke="#a8713f" stroke-opacity="{.25 + i * .05:.2f}"/>')
    out.append(f'<path d="M0 {top + .6} H{SCENE_W}" stroke="#f6d2a2" stroke-width="1.2"/>')
    out.append(f'<rect x="0" y="{front}" width="{SCENE_W}" height="{SCENE_H - front}" fill="url(#cfront)"/>')
    out.append(f'<path d="M0 {front + .6} H{SCENE_W}" stroke="#f3c58f" stroke-opacity=".7" stroke-width="1.2"/>')
    for x in range(30, SCENE_W, 66):
        out.append(f'<path d="M{x} {front + 2} V{SCENE_H}" stroke="#3f2616" stroke-opacity=".45"/>')
    # The batter bowl, with a ladle in it.
    out.append('<ellipse cx="33" cy="189" rx="24" ry="4" fill="#000000" opacity=".22"/>')
    out.append('<path d="M11 170 Q12 189 33 189 Q54 189 55 170Z" fill="#e9eef3"/>')
    out.append('<path d="M11 170 Q12 189 33 189 Q54 189 55 170Z" fill="none" stroke="#9aa6b2" stroke-width=".8"/>')
    out.append('<path d="M17 181 Q33 187 49 181" fill="none" stroke="#4d8fc9" stroke-width="1.6" stroke-opacity=".8"/>')
    out.append('<ellipse cx="33" cy="170" rx="22" ry="5.5" fill="#fbfdff" stroke="#9aa6b2" stroke-width=".8"/>')
    out.append('<ellipse cx="33" cy="170.6" rx="19" ry="4.2" fill="#f7e3a0"/>')
    out.append('<path d="M20 169.5 q6 -2 12 0" fill="none" stroke="#fff8d8" stroke-width="1.2" stroke-linecap="round"/>')
    out.append('<path d="M40 170 L52 152" stroke="#7b848f" stroke-width="2.6" stroke-linecap="round"/>')
    out.append('<path d="M40 170 L52 152" stroke="#e3e9ef" stroke-width="1.2" stroke-linecap="round"/>')
    # Sauce and mayo squeeze bottles.
    for x, body, cap, label in ((66, "#5a2c14", "#e23d3d", "#f3d9a8"), (82, "#fff4d6", "#e23d3d", "#f2b04a")):
        out.append(f'<ellipse cx="{x + 5.5}" cy="188" rx="8" ry="2.4" fill="#000000" opacity=".22"/>')
        out.append(f'<path d="M{x} 166 q0 -4 3 -5 h5 q3 1 3 5 v20 q0 2 -2 2 h-7 q-2 0 -2 -2Z" fill="{body}"/>')
        out.append(f'<path d="M{x + 1.6} 166 v19" stroke="#ffffff" stroke-opacity=".35" stroke-width="1.4" stroke-linecap="round"/>')
        out.append(f'<rect x="{x}" y="172" width="11" height="7" fill="{label}" opacity=".9"/>')
        out.append(f'<path d="M{x + 3} 161 h5 l-1.6 -7 h-1.8Z" fill="{cap}"/>')
    out.append("</g>")
    return "".join(out)


def pan():
    x0, x1 = PAN_X - 4, PAN_X + PAN_W + 4
    top, bottom = PAN_TOP, PAN_TOP + PAN_FACE
    rim = bottom + PAN_RIM
    out = []
    # The burner under it: a bar on feet; the flames show between it and the pan.
    out.append(f'<ellipse cx="{PAN_X + PAN_W / 2}" cy="194" rx="{PAN_W / 2 + 6}" ry="5" fill="#000000" opacity=".28"/>')
    out.append(f'<rect x="{x0 + 12}" y="187" width="{x1 - x0 - 24}" height="6" rx="2.5" fill="#2a2d33"/>')
    out.append(f'<path d="M{x0 + 14} 188 H{x1 - 14}" stroke="#7b818c" stroke-opacity=".8"/>')
    for lx in (x0 + 8, x1 - 13):
        out.append(f'<rect x="{lx}" y="{rim - 2}" width="5" height="{194 - rim + 2}" rx="1.5" fill="#1d1f23"/>')
    # Lug handles.
    for hx, d in ((x0, -1), (x1, 1)):
        out.append(f'<path d="M{hx} {top + 12} q{d * 9} 5 0 14" fill="none" stroke="#2a2c32" stroke-width="4" stroke-linecap="round"/>')
        out.append(f'<path d="M{hx} {top + 12} q{d * 9} 5 0 14" fill="none" stroke="#6c727d" stroke-width="1" stroke-linecap="round" opacity=".7"/>')
    # The slab: a front rim under the top face.
    out.append(f'<rect x="{x0}" y="{top + 6}" width="{x1 - x0}" height="{rim - top - 6}" rx="6" fill="url(#ironrim)"/>')
    out.append(f'<rect x="{x0}" y="{top}" width="{x1 - x0}" height="{PAN_FACE}" rx="7" fill="url(#iron)"/>')
    out.append(f'<path d="M{x0 + 6} {top + 1} H{x1 - 6}" stroke="#aab1bd" stroke-opacity=".75" stroke-width="1.2" stroke-linecap="round"/>')
    out.append(f'<path d="M{x0 + 5} {bottom - .5} H{x1 - 5}" stroke="#0e0f11" stroke-opacity=".6"/>')
    out.append(f'<path d="M{x0 + 8} {rim - 2.5} H{x1 - 8}" stroke="#ff9a3a" stroke-opacity=".18" stroke-width="2"/>')
    return "".join(out)


# --- flames -------------------------------------------------------------------

def tongue(x, base, h, w, lean, fill, opacity=1.0):
    return (f'<path d="M{f1(x - w)} {base} C{f1(x - w * 1.15)} {f1(base - h * .45)} {f1(x - w * .2 + lean)} {f1(base - h * .6)} '
            f'{f1(x + lean)} {f1(base - h)} C{f1(x + w * .35 + lean)} {f1(base - h * .6)} {f1(x + w * 1.15)} {f1(base - h * .4)} '
            f'{f1(x + w)} {base}Z" fill="{fill}" opacity="{opacity}"/>')


def flames(frame, big):
    base = 188
    out = []
    n = 11 if big else 7
    span0, span1 = PAN_X + 16, PAN_X + PAN_W - 16
    if big:
        out.append(f'<ellipse cx="{PAN_X + PAN_W / 2}" cy="184" rx="{PAN_W / 2 + 4}" ry="13" fill="url(#fglow)"/>')
    for i in range(n):
        x = span0 + (span1 - span0) * i / (n - 1)
        wob = math.sin(i * 2.4 + frame * 2.1)
        lean = 1.8 * math.sin(i * 1.7 + frame * 3.0)
        if big:
            h = 17 + 5 * wob
            out.append(tongue(x, base, h, 8.5, lean, "#f2441c", .92))
            out.append(tongue(x + .5, base, h * .74, 6, lean * .7, "#ff8a1f"))
            out.append(tongue(x, base, h * .46, 3.6, lean * .4, "#ffd84a"))
            out.append(tongue(x, base, h * .22, 1.8, 0, "#fff6c4"))
        else:
            h = 9.5 + 2 * wob
            out.append(tongue(x, base, h, 4, lean * .4, "#3f8cff", .9))
            out.append(tongue(x, base, h * .6, 2, lean * .2, "#9fd0ff"))
            out.append(tongue(x, base - h * .55, h * .55, 1.3, lean * .3, "#ffb347", .9))
    return "".join(out)


# --- takoyaki -----------------------------------------------------------------

def sprite(body):
    return f'<g>{body}</g>'


def hole_sprite(frost=False):
    cx, cy = SPRITE_CX, SPRITE_CY + 7
    out = [f'<ellipse cx="{cx}" cy="{cy}" rx="15.5" ry="9.5" fill="url(#hole)"/>',
           f'<path d="M{cx - 14} {cy + 2.5} A15.5 9.5 0 0 0 {cx + 14} {cy + 2.5}" fill="none" stroke="#8a909b" stroke-opacity=".55" stroke-width="1"/>',
           f'<path d="M{cx - 14.5} {cy - 2} A15.5 9.5 0 0 1 {cx + 14.5} {cy - 2}" fill="none" stroke="#000000" stroke-opacity=".5" stroke-width="1"/>']
    return "".join(out)


def sphere(light, base, dark, r=BALL_R, dy=0.0):
    cx, cy = SPRITE_CX, SPRITE_CY + dy
    gid = f"b{light[1:]}{base[1:]}{int(r * 10)}"
    return (f'<radialGradient id="{gid}" cx=".36" cy=".28" r=".8"><stop offset="0" stop-color="{light}"/>'
            f'<stop offset=".55" stop-color="{base}"/><stop offset="1" stop-color="{dark}"/></radialGradient>'
            f'<ellipse cx="{cx}" cy="{SPRITE_CY + 10.5}" rx="{r * .9:.1f}" ry="3.4" fill="#000000" opacity=".45"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#{gid})"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r - .4}" fill="none" stroke="{dark}" stroke-opacity=".55" stroke-width=".8"/>')


def gloss(r=BALL_R, dy=0.0, opacity=.55):
    cx, cy = SPRITE_CX - r * .38, SPRITE_CY + dy - r * .48
    return (f'<ellipse cx="{f1(cx)}" cy="{f1(cy)}" rx="{r * .3:.1f}" ry="{r * .17:.1f}" fill="#ffffff" opacity="{opacity}" '
            f'transform="rotate(-28 {f1(cx)} {f1(cy)})"/>')


def ball_raw():
    cx, cy = SPRITE_CX, SPRITE_CY + 7
    return ('<radialGradient id="batter" cx=".4" cy=".3" r=".8"><stop offset="0" stop-color="#fff8d4"/>'
            '<stop offset="1" stop-color="#eccf7a"/></radialGradient>'
            f'<ellipse cx="{cx}" cy="{cy}" rx="13.6" ry="7.8" fill="url(#batter)" stroke="#cfae5c" stroke-width=".8"/>'
            f'<path d="M{cx - 9} {cy - 2.5} q5 -3.5 11 -2.5" fill="none" stroke="#ffffff" stroke-width="1.4" stroke-linecap="round" opacity=".8"/>'
            # A chunk of octopus, spring onion and red ginger floating in it.
            f'<rect x="{cx + 1}" y="{cy - 1.5}" width="6.5" height="4.6" rx="2" fill="#e8707e" stroke="#b9485a" stroke-width=".6"/>'
            f'<circle cx="{cx + 3}" cy="{cy + .2}" r=".8" fill="#ffd9de"/>'
            f'<circle cx="{cx - 5}" cy="{cy + 2}" r="1.7" fill="none" stroke="#5aa83a" stroke-width="1.1"/>'
            f'<circle cx="{cx - 8.5}" cy="{cy - .5}" r="1.3" fill="none" stroke="#7cc24e" stroke-width="1"/>'
            f'<path d="M{cx + 8} {cy + 3} l2.2 -1 M{cx - 1.5} {cy + 4.2} l2 .6" stroke="#e2473f" stroke-width="1.1" stroke-linecap="round"/>')


COOK_STEPS = 5


def ball_cooking(step):
    k = step / (COOK_STEPS - 1)
    base = mix("#f6d77a", "#c07a2c", k)
    light = mix("#fff6cf", "#f1c070", k)
    dark = mix("#d9b356", "#7d4718", k)
    r = 11 + 2 * min(1, k * 1.6)
    dy = (BALL_R - r)
    out = []
    if step < 2:
        # Still setting: a skirt of batter round the dome.
        out.append(f'<ellipse cx="{SPRITE_CX}" cy="{SPRITE_CY + 7}" rx="13.6" ry="7.6" fill="#f3dc92" stroke="#cfae5c" stroke-width=".8" opacity="{1 - step * .35:.2f}"/>')
    out.append(sphere(light, base, dark, r, dy))
    # Browning: toasted freckles that deepen with the heat.
    spots = [(-5, 3, 2.2), (4, -4, 1.8), (6, 4, 2.4), (-2, -7, 1.5), (0, 6, 1.7), (-8, -2, 1.3)]
    for i, (sx, sy, sr) in enumerate(spots[: 1 + step + (1 if step > 2 else 0)]):
        out.append(f'<ellipse cx="{SPRITE_CX + sx}" cy="{SPRITE_CY + dy + sy}" rx="{sr}" ry="{sr * .7:.1f}" fill="{dark}" opacity="{.25 + k * .35:.2f}"/>')
    out.append(gloss(r, dy, .5))
    return "".join(out)


def toppings():
    cx, cy = SPRITE_CX, SPRITE_CY
    out = [f'<clipPath id="ballclip"><circle cx="{cx}" cy="{cy}" r="{BALL_R}"/></clipPath>',
           '<g clip-path="url(#ballclip)">',
           # Sauce: a glossy dark cap running down in drips.
           f'<path d="M{cx - 14} {cy - 2} C{cx - 14} {cy - 16} {cx + 14} {cy - 16} {cx + 14} {cy - 2} '
           f'C{cx + 12} {cy + 2} {cx + 10} {cy + 6} {cx + 8} {cy + 2} C{cx + 6} {cy - 1} {cx + 4} {cy + 7} {cx + 1.5} {cy + 3} '
           f'C{cx - .5} {cy} {cx - 3} {cy + 5} {cx - 5.5} {cy + 2} C{cx - 8} {cy - 1} {cx - 10} {cy + 5} {cx - 14} {cy - 2}Z" fill="#4b230f"/>',
           f'<path d="M{cx - 9} {cy - 8} q5 -5 12 -3.6" fill="none" stroke="#a8643a" stroke-width="1.6" stroke-linecap="round" opacity=".8"/>',
           # Mayo zigzag.
           f'<path d="M{cx - 10.5} {cy - 3} L{cx - 7} {cy - 8.5} L{cx - 3.5} {cy - 2.5} L{cx} {cy - 9.5} L{cx + 3.5} {cy - 2.5} L{cx + 7} {cy - 8.5} L{cx + 10.5} {cy - 3}" '
           'fill="none" stroke="#fff6dc" stroke-width="1.9" stroke-linejoin="round" stroke-linecap="round"/>',
           "</g>"]
    # Aonori flecks.
    for ax, ay in ((-6, -10), (5, -11), (-1, -5.5), (8, -5), (-9, -5.5), (2, -12)):
        out.append(f'<circle cx="{cx + ax}" cy="{cy + ay}" r=".95" fill="#5aa83a"/>')
    # Bonito flakes curling on top.
    for bx, by, rot in ((-4.5, -12.5, -20), (3, -13.5, 25), (-.5, -15, 0)):
        out.append(f'<path d="M-4 1 Q-2 -4 3 -3 Q5 -1 3.5 1.5 Q0 0 -4 1Z" fill="#f0c49c" stroke="#b9805c" stroke-width=".6" '
                   f'transform="translate({cx + bx} {cy + by}) rotate({rot})"/>')
    return "".join(out)


def ball_ready():
    return sphere("#f7cf85", "#c98a3c", "#7d4718") + toppings() + gloss(opacity=.6)


def ball_capped():
    cx, cy = SPRITE_CX, SPRITE_CY
    flag = (f'<path d="M{cx + 3} {cy - 9} L{cx + 6.5} {cy - 25}" stroke="#7a5a34" stroke-width="2.2" stroke-linecap="round"/>'
            f'<path d="M{cx + 3} {cy - 9} L{cx + 6.5} {cy - 25}" stroke="#f0d9a8" stroke-width="1.1" stroke-linecap="round"/>'
            f'<path d="M{cx + 6.3} {cy - 25} L{cx + 17} {cy - 21.5} L{cx + 5} {cy - 16.5}Z" fill="#ec3b3b" stroke="#9c1f26" stroke-width=".7" stroke-linejoin="round"/>'
            f'<path d="M{cx + 7.5} {cy - 23.4} L{cx + 13} {cy - 21.6}" stroke="#ffffff" stroke-opacity=".6" stroke-width="1" stroke-linecap="round"/>')
    return ball_ready() + flag


def ball_burnt():
    cx, cy = SPRITE_CX, SPRITE_CY
    out = [sphere("#6a5145", "#2c1d16", "#0f0906")]
    # Lumps and cracks glowing like embers.
    for lx, ly, lr in ((-7, -6, 4), (6, -8, 3.4), (8, 3, 3.8), (-4, 6, 3.2)):
        out.append(f'<circle cx="{cx + lx}" cy="{cy + ly}" r="{lr}" fill="#1a110d" opacity=".75"/>')
    out.append(f'<path d="M{cx - 8} {cy - 1} l4 -3 l3 3.5 l4 -2 M{cx + 1} {cy + 5} l3 -2.5 l4 1.5 M{cx - 3} {cy - 8} l2.5 2.5" '
               'fill="none" stroke="#ff7a1a" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round" opacity=".9"/>')
    out.append(f'<path d="M{cx - 8} {cy - 1} l4 -3 l3 3.5 l4 -2" fill="none" stroke="#ffd23f" stroke-width=".5" stroke-linecap="round" opacity=".8"/>')
    out.append(gloss(opacity=.18))
    return "".join(out)


def star4(x, y, r, fill="#ffffff", stroke=None, opacity=1.0):
    s = f' stroke="{stroke}" stroke-width=".6" stroke-linejoin="round"' if stroke else ""
    k = r * .22
    return (f'<path d="M{f1(x)} {f1(y - r)} Q{f1(x + k)} {f1(y - k)} {f1(x + r)} {f1(y)} Q{f1(x + k)} {f1(y + k)} {f1(x)} {f1(y + r)} '
            f'Q{f1(x - k)} {f1(y + k)} {f1(x - r)} {f1(y)} Q{f1(x - k)} {f1(y - k)} {f1(x)} {f1(y - r)}Z" fill="{fill}" opacity="{opacity}"{s}/>')


def ball_stalled():
    cx, cy = SPRITE_CX, SPRITE_CY
    out = [f'<ellipse cx="{cx}" cy="{cy + 7}" rx="15.5" ry="9.5" fill="none" stroke="#bfe2ff" stroke-opacity=".7" stroke-width="1.2"/>',
           sphere("#dfeaf4", "#93a7ba", "#566679")]
    # A rind of frost over the top, and ice crystals.
    out.append(f'<path d="M{cx - 11} {cy - 6} Q{cx} {cy - 17} {cx + 11} {cy - 6} Q{cx + 6} {cy - 3} {cx + 3} {cy - 6} Q{cx} {cy - 2} {cx - 4} {cy - 6} Q{cx - 7} {cy - 3} {cx - 11} {cy - 6}Z" fill="#f4faff" opacity=".8"/>')
    out.append(star4(cx + 11, cy - 11, 4.2, "#ffffff", "#7fb4e0"))
    out.append(star4(cx - 12, cy + 2, 2.8, "#ffffff", "#7fb4e0"))
    out.append(star4(cx + 4, cy + 4, 1.8, "#eaf6ff"))
    return "".join(out)


def focus_ring():
    cx, cy = SPRITE_CX, SPRITE_CY + 7
    return (f'<ellipse cx="{cx}" cy="{cy}" rx="17" ry="10.8" fill="none" stroke="#ffe27a" stroke-width="4" opacity=".55" filter="url(#soft)"/>'
            f'<ellipse cx="{cx}" cy="{cy}" rx="17" ry="10.8" fill="none" stroke="#fff3b0" stroke-width="1.6"/>')


def glow(color):
    gid = f"g{color[1:]}"
    return (f'<radialGradient id="{gid}" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="{color}" stop-opacity=".95"/>'
            f'<stop offset=".55" stop-color="{color}" stop-opacity=".45"/><stop offset="1" stop-color="{color}" stop-opacity="0"/></radialGradient>'
            f'<circle cx="{SPRITE_CX}" cy="{SPRITE_CY}" r="20" fill="url(#{gid})"/>')


def puff(cx, cy, r, fill, opacity=.85):
    return f'<circle cx="{f1(cx)}" cy="{f1(cy)}" r="{f1(r)}" fill="{fill}" opacity="{opacity}"/>'


def cloud(cx, cy, s, fill, edge):
    parts = [(-.55, .15, .42), (0, -.2, .55), (.55, .1, .44), (0, .28, .5)]
    out = [puff(cx + x * s, cy + y * s, r * s + .9, edge, .55) for x, y, r in parts]
    out += [puff(cx + x * s, cy + y * s, r * s, fill, .95) for x, y, r in parts]
    return "".join(out)


def smoke_sprite():
    return (cloud(20, 30, 12, "#6f6a6a", "#2b2626") + cloud(14, 17, 9, "#8a8585", "#2b2626")
            + cloud(24, 7, 6, "#a09a9a", "#2b2626"))


def steam_sprite():
    return ('<path d="M12 34 C6 28 18 24 12 18 C6 12 16 8 12 2" fill="none" stroke="#ffffff" stroke-width="5" '
            'stroke-linecap="round" opacity=".35" filter="url(#soft)"/>'
            '<path d="M12 34 C6 28 18 24 12 18 C6 12 16 8 12 2" fill="none" stroke="#ffffff" stroke-width="2" '
            'stroke-linecap="round" opacity=".8"/>')


def boat():
    out = ['<ellipse cx="19" cy="22.5" rx="16" ry="1.6" fill="#000000" opacity=".3"/>']
    # Three sauced takoyaki in a bamboo boat.
    for i, x in enumerate((9.5, 19, 28.5)):
        gid = f"bt{i}"
        out.append(f'<radialGradient id="{gid}" cx=".36" cy=".28" r=".8"><stop offset="0" stop-color="#f7cf85"/>'
                   '<stop offset=".55" stop-color="#c98a3c"/><stop offset="1" stop-color="#7d4718"/></radialGradient>')
        out.append(f'<circle cx="{x}" cy="10.5" r="6.4" fill="url(#{gid})"/>')
        out.append(f'<path d="M{x - 6} 9 Q{x} 0 {x + 6} 9 Q{x + 3} 12.5 {x + 1} 9.5 Q{x - 1.5} 12.5 {x - 6} 9Z" fill="#4b230f"/>')
        out.append(f'<path d="M{x - 4} 8 l2 -3 l2 3 l2 -3 l2 3" fill="none" stroke="#fff6dc" stroke-width="1.1" stroke-linejoin="round" stroke-linecap="round"/>')
        out.append(f'<circle cx="{x - 2}" cy="4.6" r=".7" fill="#5aa83a"/><circle cx="{x + 2.6}" cy="5.4" r=".7" fill="#5aa83a"/>')
    out.append('<path d="M27.5 7 L33 -1" stroke="#7a5a34" stroke-width="1.6" stroke-linecap="round" transform="translate(0 2)"/>')
    out.append('<path d="M1 11 Q4 22 19 22 Q34 22 37 11 Q30 15.5 19 15.5 Q8 15.5 1 11Z" fill="#ecd29a" stroke="#a9834a" stroke-width=".8" stroke-linejoin="round"/>')
    out.append('<path d="M6 16.5 Q19 20.5 32 16.5" fill="none" stroke="#c9a566" stroke-width=".8"/>')
    out.append('<path d="M3.5 13 Q10 16.8 19 16.8" fill="none" stroke="#fff3cf" stroke-width=".9" opacity=".8"/>')
    return "".join(out)


# --- bursts (36x36 each) ------------------------------------------------------

def heart(x, y, s, fill, stroke):
    return (f'<path d="M0 {.9 * s} C{-1.3 * s} {-.1 * s} {-1.1 * s} {-1.1 * s} {-.5 * s} {-1.1 * s} C{-.2 * s} {-1.1 * s} 0 {-.9 * s} 0 {-.6 * s} '
            f'C0 {-.9 * s} {.2 * s} {-1.1 * s} {.5 * s} {-1.1 * s} C{1.1 * s} {-1.1 * s} {1.3 * s} {-.1 * s} 0 {.9 * s}Z" '
            f'fill="{fill}" stroke="{stroke}" stroke-width=".8" stroke-linejoin="round" transform="translate({x} {y})"/>')


def zed(x, y, s, w=2.2, fill="#dcebff", edge="#27406b"):
    d = f"M{x} {y} h{s} l-{s} {s} h{s}"
    return (f'<path d="{d}" fill="none" stroke="{edge}" stroke-width="{w + 1.8}" stroke-linejoin="round" stroke-linecap="round"/>'
            f'<path d="{d}" fill="none" stroke="{fill}" stroke-width="{w}" stroke-linejoin="round" stroke-linecap="round"/>')


def drop(x, y, rot, s, fill, edge):
    return (f'<path d="M0 {-1.6 * s} C{.9 * s} {-.3 * s} {.9 * s} {.9 * s} 0 {.9 * s} C{-.9 * s} {.9 * s} {-.9 * s} {-.3 * s} 0 {-1.6 * s}Z" '
            f'fill="{fill}" stroke="{edge}" stroke-width=".7" transform="translate({x} {y}) rotate({rot})"/>')


def burst(kind):
    if kind == "steam":
        return cloud(18, 24, 13, "#ffffff", "#8fa3b5") + cloud(12, 10, 8, "#f2f6fa", "#8fa3b5") + cloud(27, 8, 5, "#ffffff", "#8fa3b5")
    if kind == "smoke":
        return cloud(18, 24, 13, "#5d5757", "#1d1919") + cloud(13, 10, 8, "#777070", "#1d1919") + cloud(27, 7, 5, "#8d8686", "#1d1919")
    if kind == "sparkle":
        return (star4(13, 20, 11, "#ffe95a", "#a8741a") + star4(13, 20, 4.5, "#fffbe0")
                + star4(27, 9, 6.5, "#fff27a", "#a8741a") + star4(28, 28, 4.5, "#fff27a", "#a8741a"))
    if kind == "heart":
        return (heart(15, 20, 10, "#ff6b9a", "#a3284f") + '<ellipse cx="10.5" cy="14" rx="2.6" ry="1.5" fill="#ffffff" opacity=".7" transform="rotate(-30 10.5 14)"/>'
                + heart(28, 9, 5, "#ff9bbb", "#a3284f"))
    if kind == "zzz":
        return zed(5, 20, 10, 2.6) + zed(18, 9, 7.5, 2.2) + zed(28, 2, 5, 1.8)
    if kind == "batter":
        out = ['<path d="M9 26 Q7 18 14 19 Q16 12 22 17 Q29 14 28 22 Q33 27 26 30 Q18 34 11 30 Q7 29 9 26Z" fill="#f7e3a0" stroke="#b9963f" stroke-width=".8"/>',
               '<path d="M13 23 q4 -3 8 -1" fill="none" stroke="#ffffff" stroke-width="1.4" stroke-linecap="round" opacity=".8"/>']
        for x, y, rot, s in ((6, 12, -35, 3), (18, 6, 0, 3.4), (30, 11, 35, 2.8), (33, 21, 70, 2), (3, 22, -70, 2)):
            out.append(drop(x, y, rot, s, "#f7e3a0", "#b9963f"))
        return "".join(out)
    if kind == "ink":
        out = ['<path d="M8 22 Q4 14 12 14 Q13 6 20 11 Q28 6 28 15 Q35 18 29 25 Q30 33 21 30 Q13 35 11 28 Q5 28 8 22Z" fill="#3b2a5a" stroke="#1c1230" stroke-width=".8"/>',
               '<path d="M13 19 q3 -4 8 -3" fill="none" stroke="#8d78c0" stroke-width="1.4" stroke-linecap="round" opacity=".8"/>']
        for x, y, rot, s in ((4, 8, -40, 2.4), (31, 6, 40, 2.6), (33, 31, 140, 2), (5, 33, -140, 1.8)):
            out.append(drop(x, y, rot, s, "#3b2a5a", "#1c1230"))
        return "".join(out)
    if kind == "bang":
        pts = []
        for i in range(16):
            a = math.pi * 2 * i / 16 - math.pi / 2
            r = 17 if i % 2 == 0 else 10.5
            pts.append(f"{18 + r * math.cos(a):.1f} {18 + r * math.sin(a):.1f}")
        return (f'<path d="M{" L".join(pts)}Z" fill="#ffd23f" stroke="#a8541a" stroke-width="1" stroke-linejoin="round"/>'
                '<path d="M18 9.5 L18 20" stroke="#3b2145" stroke-width="3.6" stroke-linecap="round"/>'
                '<circle cx="18" cy="25.5" r="2.1" fill="#3b2145"/>')
    raise ValueError(kind)


BURSTS = ("steam", "batter", "sparkle", "smoke", "bang", "heart", "zzz", "ink")


# --- the chef -----------------------------------------------------------------

def bezier(p0, p1, p2, p3, t):
    u = 1 - t
    return (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


def tentacle(p0, c1, c2, p3, w0, w1, fill, p, suckers=(), side=1):
    """A tapered tentacle along a cubic curve, with suckers on one side."""
    n = 36
    left, right, dots = [], [], []
    for i in range(n + 1):
        t = i / n
        x, y = bezier(p0, c1, c2, p3, t)
        ax, ay = bezier(p0, c1, c2, p3, max(0, t - 0.01))
        bx, by = bezier(p0, c1, c2, p3, min(1, t + 0.01))
        tx, ty = bx - ax, by - ay
        length = math.hypot(tx, ty) or 1
        nx, ny = -ty / length * side, tx / length * side
        w = w0 + (w1 - w0) * t
        left.append((x + nx * w, y + ny * w))
        right.append((x - nx * w, y - ny * w))
        if i in suckers:
            dots.append(f'<circle cx="{x + nx * w * .45:.1f}" cy="{y + ny * w * .45:.1f}" r="{max(.8, w * .24):.1f}" '
                        f'fill="{p["suck"]}" opacity=".7"/>')
    tip = bezier(p0, c1, c2, p3, 1)
    pts = left + right[::-1]
    d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + "Z"
    return (f'<path d="{d}" fill="{fill}" stroke="{p["shade"]}" stroke-opacity=".45" stroke-width=".8" stroke-linejoin="round"/>'
            f'<circle cx="{tip[0]:.1f}" cy="{tip[1]:.1f}" r="{w1:.1f}" fill="{fill}"/>' + "".join(dots))


LEG_STARTS = [(36, 122), (48, 126), (62, 128), (78, 128), (92, 126), (104, 122)]
LEG_ENDS = [[(15, 170), (36, 176), (58, 178), (82, 178), (104, 176), (125, 170)],
            [(19, 172), (33, 176), (61, 178), (79, 178), (107, 176), (121, 172)]]


def legs(frame, p, tag):
    out = []
    for (x0, y0), (x1, y1) in zip(LEG_STARTS, LEG_ENDS[frame]):
        c1 = (x0 + (x1 - x0) * .1, y0 + 20)
        c2 = (x1 - (x1 - x0) * .2, y1 - 14)
        out.append(tentacle((x0, y0), c1, c2, (x1, y1), 8.5, 3, f"url(#tent-{tag})", p, (12, 18, 24)))
    return "".join(out)


def eye(cx, cy, m, p, tag, kind=None):
    ink = p["ink"]
    kind = kind or m.get("eye")
    if kind == "happy":
        return (f'<path d="M{cx - 8.5} {cy + 2.5} Q{cx} {cy - 8} {cx + 8.5} {cy + 2.5}" fill="none" stroke="{ink}" '
                'stroke-width="2.8" stroke-linecap="round"/>')
    if kind == "closed":
        return (f'<path d="M{cx - 8.5} {cy} Q{cx} {cy + 6} {cx + 8.5} {cy}" fill="none" stroke="{ink}" '
                'stroke-width="2.6" stroke-linecap="round"/>')
    r = EYE_R
    px, py = m.get("pupil", (0, 0))
    pr = m.get("pupil_r", 5.2)
    out = [f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#fffaf6" stroke="{ink}" stroke-width="1.5"/>',
           f'<circle cx="{cx + px}" cy="{cy + py}" r="{pr}" fill="{ink}"/>',
           f'<circle cx="{cx + px - pr * .35:.1f}" cy="{cy + py - pr * .4:.1f}" r="{pr * .34:.1f}" fill="#ffffff"/>']
    if m.get("tears"):
        out.append(f'<circle cx="{cx + px + pr * .35:.1f}" cy="{cy + py + pr * .35:.1f}" r="{pr * .2:.1f}" fill="#ffffff" opacity=".85"/>')
        out.append(f'<path d="M{cx - 8} {cy + 5.5} Q{cx} {cy + 10.5} {cx + 8} {cy + 5.5} Q{cx} {cy + 8} {cx - 8} {cy + 5.5}Z" fill="#8fd8ff" opacity=".9"/>')
    out.append(lid(cx, cy, m.get("lid", 0), p, tag))
    return "".join(out)


def lid(cx, cy, amount, p, tag):
    if amount <= 0:
        return ""
    r = EYE_R + 1.4
    if amount >= 1:
        return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#body-{tag})"/>'
                f'<path d="M{cx - 8.5} {cy + 2} Q{cx} {cy + 6.5} {cx + 8.5} {cy + 2}" fill="none" stroke="{p["ink"]}" '
                'stroke-width="2.4" stroke-linecap="round"/>')
    ly = cy - r + 2 * r * amount
    dx = math.sqrt(max(r * r - (ly - cy) ** 2, 0))
    large = 1 if ly > cy else 0
    return (f'<path d="M{cx - dx:.2f} {ly:.2f} A{r} {r} 0 {large} 1 {cx + dx:.2f} {ly:.2f}Z" fill="url(#body-{tag})"/>'
            f'<path d="M{cx - dx:.2f} {ly:.2f} L{cx + dx:.2f} {ly:.2f}" stroke="{p["ink"]}" stroke-width="1.8" stroke-linecap="round"/>')


def mouth(kind, p, frame):
    ink = p["ink"]
    x, y = 70, 114
    line = f'fill="none" stroke="{ink}" stroke-width="2.2" stroke-linecap="round"'
    if kind == "smile":
        return f'<path d="M{x - 7} {y - 1} Q{x} {y + 5} {x + 7} {y - 1}" {line}/>'
    if kind == "grin":
        h = 8 if frame == 0 else 6.5
        return (f'<path d="M{x - 9} {y - 2} Q{x} {y + h * 1.6} {x + 9} {y - 2}Z" fill="{ink}" stroke="{ink}" stroke-width="1.6" stroke-linejoin="round"/>'
                f'<path d="M{x - 4.5} {y + h * .55} Q{x} {y + h * .2} {x + 4.5} {y + h * .55} Q{x} {y + h * .95} {x - 4.5} {y + h * .55}Z" fill="#ff7b8a"/>')
    if kind == "tongue":
        return (f'<path d="M{x - 6} {y} Q{x} {y + 3.5} {x + 6} {y}" {line}/>'
                f'<path d="M{x + 1} {y + 1.6} q4.6 .2 4 3.4 q-.8 2.6 -3.4 1.6 q-1.8 -1 -.6 -5Z" fill="#ff7b8a" stroke="{ink}" stroke-width=".9"/>')
    if kind == "open":
        return (f'<ellipse cx="{x}" cy="{y + 1}" rx="5.5" ry="{5 if frame == 0 else 4}" fill="{ink}"/>'
                f'<ellipse cx="{x}" cy="{y + 3.4}" rx="3" ry="1.6" fill="#ff7b8a"/>')
    if kind == "o":
        return f'<ellipse cx="{x}" cy="{y + 1}" rx="3.2" ry="3.8" fill="{ink}"/>'
    if kind == "o_tiny":
        return f'<ellipse cx="{x}" cy="{y + 1}" rx="2.6" ry="{2.8 if frame == 0 else 3.6}" fill="{ink}"/>'
    if kind == "o_big":
        return (f'<ellipse cx="{x}" cy="{y + 2}" rx="5.5" ry="{7.5 if frame == 0 else 8.5}" fill="{ink}"/>'
                f'<ellipse cx="{x}" cy="{y + 5.5}" rx="3" ry="2" fill="#ff7b8a"/>')
    if kind == "flat":
        return f'<path d="M{x - 5.5} {y + 1} H{x + 5.5}" {line}/>'
    if kind == "wavy":
        return f'<path d="M{x - 8} {y + 2} q4 -5 8 0 t8 0" {line}/>'
    if kind == "frown":
        return f'<path d="M{x - 7.5} {y + 5} Q{x} {y - 4} {x + 7.5} {y + 5}" {line}/>'
    raise ValueError(kind)


def brows(kind, p):
    line = f'fill="none" stroke="{p["ink"]}" stroke-width="2.4" stroke-linecap="round"'
    (lx, ly), (rx, ry) = EYES
    y = ly - EYE_R - 4
    if kind == "focus":
        return f'<path d="M{lx - 7} {y - .5} L{lx + 7} {y + 1.5} M{rx - 7} {y + 1.5} L{rx + 7} {y - .5}" {line}/>'
    if kind == "worry":
        return f'<path d="M{lx - 8} {y + 2.5} L{lx + 7} {y - 2.5} M{rx - 7} {y - 2.5} L{rx + 8} {y + 2.5}" {line}/>'
    return f'<path d="M{lx - 7} {y - 2} Q{lx} {y - 5} {lx + 7} {y - 2} M{rx - 7} {y - 2} Q{rx} {y - 5} {rx + 7} {y - 2}" {line}/>'


def hachimaki(frame, knot=True):
    """The headband: a white band across the brow, knotted at the side, tails fluttering."""
    band = "M18 78 Q70 56 122 78"
    out = ['<g clip-path="url(#mantle)">',
           f'<path d="{band}" fill="none" stroke="#3b2145" stroke-opacity=".28" stroke-width="12" transform="translate(0 2.2)"/>',
           f'<path d="{band}" fill="none" stroke="#fdfaf2" stroke-width="10.5"/>',
           '<path d="M18 81.5 Q70 59.5 122 81.5" fill="none" stroke="#d9d2c0" stroke-width="1.6"/>',
           '<path d="M18 74.6 Q70 52.6 122 74.6" fill="none" stroke="#ffffff" stroke-width="1.4"/>',
           '</g>']
    if not knot:
        return "".join(out)
    # Mirrored to the left temple, clear of the arm that works the pan.
    tails = [("M28 73 Q14 74 6 84 Q10 86 14 82 Q20 79 28 80Z", "M29 76 Q20 84 19 97 Q23 96 24 91 Q27 85 32 82Z"),
             ("M28 73 Q13 70 3 78 Q7 81 12 78 Q20 77 28 80Z", "M29 76 Q17 82 13 94 Q17 94 19 89 Q24 84 32 82Z")][frame]
    for d in tails:
        out.append(f'<path d="{d}" fill="#fdfaf2" stroke="#b9b09c" stroke-width=".8" stroke-linejoin="round"/>')
    out.append('<ellipse cx="27.5" cy="76" rx="4.6" ry="5.4" fill="#ffffff" stroke="#b9b09c" stroke-width=".8"/>')
    out.append('<path d="M29.5 73.5 q-2.5 2.5 -.5 5.5" fill="none" stroke="#d9d2c0" stroke-width=".9"/>')
    return "".join(out)


def chef(mood, frame):
    m = MOODS[mood]
    tag = "f" if m.get("palette") == "flush" else "w"
    p = FLUSH if tag == "f" else WARM
    out = ['<ellipse cx="70" cy="150" rx="52" ry="5" fill="#000000" opacity=".18"/>',
           legs(frame, p, tag),
           f'<path d="{MANTLE}" fill="url(#body-{tag})"/>',
           f'<path d="{MANTLE}" fill="none" stroke="{p["shade"]}" stroke-opacity=".35" stroke-width="1"/>',
           # Rim light on the lamp side, and a soft sheen on the crown.
           f'<path d="M30 62 C36 46 50 37 62 35" fill="none" stroke="#ffffff" stroke-width="3.6" stroke-linecap="round" opacity=".38"/>',
           f'<path d="M104 50 C113 66 116 86 115 104" fill="none" stroke="{p["hi"]}" stroke-width="2.2" stroke-linecap="round" opacity=".55"/>']
    blush = m.get("blush", .55)
    for ex, _ in EYES:
        bx = ex + (-9 if ex < 70 else 9)
        out.append(f'<ellipse cx="{bx}" cy="111" rx="6" ry="3.4" fill="{p["blush"]}" opacity="{blush}"/>')
    (lx, ly), (rx, ry) = EYES
    if m.get("eye") == "wink":
        out.append(eye(lx, ly, m, p, tag, "happy"))
        out.append(eye(rx, ry, m, p, tag, "open"))
    else:
        out.append(eye(lx, ly, m, p, tag))
        out.append(eye(rx, ry, m, p, tag))
    # The headband goes over the eyelids, which reach up under it.
    out.append(hachimaki(frame))
    if m.get("brows"):
        out.append(brows(m["brows"], p))
    out.append(mouth(m["mouth"], p, frame))
    if m.get("tears"):
        dy = 0 if frame == 0 else 7
        for ex, side in ((lx - 6, -1), (rx + 6, 1)):
            out.append(f'<path d="M{ex} {ly + 9} q{side * 2} 6 0 {11 + dy}" fill="none" stroke="#8fd8ff" stroke-width="3.4" stroke-linecap="round" opacity=".9"/>')
            out.append(drop(ex + side * .5, ly + 24 + dy, 0, 2.6, "#bfe8ff", "#3a8fc0"))
    if m.get("sweat"):
        dy = 0 if frame == 0 else 6
        out.append(drop(104, 52 + dy, 12, 5, "#9fdcff", "#3a8fc0"))
        out.append(f'<ellipse cx="102.6" cy="{53 + dy}" rx="1.2" ry="2.2" fill="#ffffff" opacity=".8"/>')
    if m.get("sparkle"):
        s = 0 if frame == 0 else 1
        out.append(star4(16, 54 - s * 4, 6 + s, "#fff27a", "#a8741a"))
        out.append(star4(128, 44 + s * 3, 4.5 - s, "#fff27a", "#a8741a"))
    if m.get("heart"):
        out.append(heart(130, 46 - frame * 4, 6 + frame, "#ff6b9a", "#a3284f"))
    if m.get("pop"):
        d = "M124 50 l8 -6 M118 36 l5 -9 M22 36 l-5 -9 M16 50 l-8 -6" if frame == 0 else "M125 49 l10 -7 M119 35 l6 -11 M21 35 l-6 -11 M15 49 l-10 -7"
        out.append(f'<path d="{d}" fill="none" stroke="#fff3a6" stroke-width="5" stroke-linecap="round"/>')
        out.append(f'<path d="{d}" fill="none" stroke="{p["ink"]}" stroke-width="2" stroke-linecap="round"/>')
    if m.get("zs"):
        if frame == 0:
            out.append(zed(118, 52, 8, 2.2) + zed(130, 37, 6, 1.9))
        else:
            out.append(zed(120, 48, 9, 2.4) + zed(133, 31, 7, 2) + zed(143, 23, 4.5, 1.6))
    if m.get("bubble"):
        r = 4.5 if frame == 0 else 7
        out.append(f'<circle cx="{70 + 5 + r * .5:.1f}" cy="{116 + r * .5:.1f}" r="{r}" fill="#cfeaff" fill-opacity=".55" stroke="#7fb4e0" stroke-width=".9"/>')
        out.append(f'<circle cx="{70 + 5 + r * .2:.1f}" cy="{116 + r * .2:.1f}" r="{r * .25:.1f}" fill="#ffffff" opacity=".9"/>')
    if m.get("doze_z") and frame == 1:
        out.append(zed(120, 50, 7, 2))
    return "".join(out)


def blink(tag):
    p = FLUSH if tag == "f" else WARM
    return "".join(lid(cx, cy, 1, p, tag) for cx, cy in EYES) + hachimaki(0, knot=False)


# --- the arm ------------------------------------------------------------------

SHOULDER = (110, 121)


def pose_x(k):
    return PAN_X + PAN_W * (k + .5) / ARM_POSES


def pick(x0, y0, x1, y1):
    """The takoyaki pick: a wooden handle from (x0, y0) and a steel needle to (x1, y1)."""
    mx, my = x0 + (x1 - x0) * .45, y0 + (y1 - y0) * .45
    return (f'<path d="M{f1(mx)} {f1(my)} L{f1(x1)} {f1(y1)}" stroke="#4b5560" stroke-width="2.6" stroke-linecap="round"/>'
            f'<path d="M{f1(mx)} {f1(my)} L{f1(x1)} {f1(y1)}" stroke="#eef2f6" stroke-width="1.3" stroke-linecap="round"/>'
            f'<path d="M{f1(x0)} {f1(y0)} L{f1(mx)} {f1(my)}" stroke="#6b4423" stroke-width="5.2" stroke-linecap="round"/>'
            f'<path d="M{f1(x0)} {f1(y0)} L{f1(mx)} {f1(my)}" stroke="#d9a868" stroke-width="3.4" stroke-linecap="round"/>')


def jug(x, y):
    """A steel batter pitcher, tilted to pour from its spout at the lower right."""
    return (f'<g transform="translate({f1(x)} {f1(y)}) rotate(38)">'
            '<path d="M-9 -9 H7 L12 -12 L10 -6 L8 9 Q8 11 6 11 H-8 Q-10 11 -10 9Z" fill="url(#steel)" stroke="#5b6672" stroke-width=".9" stroke-linejoin="round"/>'
            '<path d="M-9 -6 H9" stroke="#f7e3a0" stroke-width="2.4"/>'
            '<path d="M-6.5 -3 V8" stroke="#ffffff" stroke-width="1.6" stroke-linecap="round" opacity=".8"/>'
            '</g>')


def arm(kind, k=0, tag="w"):
    p = FLUSH if tag == "f" else WARM
    fill = f"url(#arm-{tag})"
    s = SHOULDER
    suck = (10, 15, 20, 25, 30)
    if kind == "point":
        hx = pose_x(k)
        tip = (hx + 3, 108)
        c1 = (s[0] + 26 + k * 6, s[1] - 8 - k * 7)
        c2 = (tip[0] - 22 - k * 6, tip[1] - 26 - k * 3)
        body = tentacle(s, c1, c2, tip, 8, 3.4, fill, p, suck)
        return pick(hx + 5.5, 99, hx + .5, BALL_Y - BALL_R + 3) + body_curl(tip, p, fill) + body
    if kind == "pour":
        hx = pose_x(k)
        tip = (hx - 13, 103)
        c1 = (s[0] + 24 + k * 6, s[1] - 10 - k * 7)
        c2 = (tip[0] - 20 - k * 6, tip[1] - 24 - k * 3)
        stream = (f'<path d="M{f1(hx + 1.5)} 109 Q{f1(hx + 3)} 120 {f1(hx + .5)} {BALL_Y - 2}" fill="none" stroke="#d9bf74" stroke-width="4.4" stroke-linecap="round"/>'
                  f'<path d="M{f1(hx + 1.5)} 109 Q{f1(hx + 3)} 120 {f1(hx + .5)} {BALL_Y - 2}" fill="none" stroke="#fbeeb4" stroke-width="3" stroke-linecap="round"/>')
        return stream + jug(hx - 6, 100) + tentacle(s, c1, c2, tip, 8, 3.6, fill, p, suck)
    if kind == "rest":
        tip = (131, 103)
        return pick(131, 112, 135, 76) + tentacle(s, (122, 133), (137, 124), tip, 8, 3.6, fill, p, (12, 18, 24))
    if kind == "cheer":
        tip = (133, 62)
        return pick(131, 70, 146, 38) + tentacle(s, (128, 122), (142, 92), tip, 8, 3.6, fill, p, (10, 16, 22, 28))
    if kind == "down":
        tip = (126, 158)
        return pick(131, 162, 99, 168) + tentacle(s, (124, 124), (132, 142), tip, 8, 3.6, fill, p, (12, 18, 24))
    raise ValueError(kind)


def body_curl(tip, p, fill):
    # The tip curls round the pick's handle.
    return f'<circle cx="{tip[0] + 2:.1f}" cy="{tip[1] - 3:.1f}" r="4.2" fill="{fill}" stroke="{p["shade"]}" stroke-opacity=".45" stroke-width=".8"/>'


# --- pieces -------------------------------------------------------------------

CHEF_BOX = (0, 20, 152, 160)
ARM_BOX = (90, 30, 266, 146)
SPRITE_BOX = (0, 0, SPRITE_W, SPRITE_H)


def pieces():
    """name -> (box, svg body). Scene pieces are drawn where they sit; sprites at 0,0."""
    out = {
        "bg": ((0, 0, SCENE_W, SCENE_H), background()),
        "shelf": ((SHELF_X - 8, SHELF_ROWS[0] - 2, SHELF_PITCH * SHELF_PER_ROW + 14, SHELF_ROWS[1] - SHELF_ROWS[0] + 20), shelf()),
        "counter": ((0, 146, SCENE_W, SCENE_H - 146), counter()),
        "pan": ((PAN_X - 14, PAN_TOP - 2, PAN_W + 28, 200 - PAN_TOP + 2), pan()),
        "boat": ((0, -2, BOAT_W, BOAT_H + 2), boat()),
        "hole": (SPRITE_BOX, hole_sprite()),
        "ball-raw": (SPRITE_BOX, ball_raw()),
        "ball-ready": (SPRITE_BOX, ball_ready()),
        "ball-capped": (SPRITE_BOX, ball_capped()),
        "ball-burnt": (SPRITE_BOX, ball_burnt()),
        "ball-stalled": (SPRITE_BOX, ball_stalled()),
        "focus": (SPRITE_BOX, focus_ring()),
        "glow-ready": (SPRITE_BOX, glow("#ffd86b")),
        "glow-capped": (SPRITE_BOX, glow("#ff5a4a")),
        "smoke": ((0, 0, 40, 44), smoke_sprite()),
        "steam": ((0, 0, 24, 36), steam_sprite()),
        "blink-w": (CHEF_BOX, blink("w")),
        "blink-f": (CHEF_BOX, blink("f")),
    }
    flame_box = (PAN_X - 8, 160, PAN_W + 16, 40)
    for frame in (0, 1):
        out[f"flame-big-{frame}"] = (flame_box, flames(frame, True))
        out[f"flame-pilot-{frame}"] = (flame_box, flames(frame, False))
    for step in range(COOK_STEPS):
        out[f"ball-cooking-{step}"] = (SPRITE_BOX, ball_cooking(step))
    for kind in BURSTS:
        out[f"burst-{kind}"] = ((0, 0, 36, 36), burst(kind))
    for mood in MOODS:
        for frame in (0, 1):
            out[f"chef-{mood}-{frame}"] = (CHEF_BOX, chef(mood, frame))
    # The flushed chef (worried, sad) only ever rests or drops the pick.
    for kind, tag in (("rest", "w"), ("cheer", "w"), ("down", "w"), ("rest", "f"), ("down", "f")):
        out[f"arm-{kind}-{tag}"] = (ARM_BOX, arm(kind, 0, tag))
    for k in range(ARM_POSES):
        out[f"arm-point-{k}"] = (ARM_BOX, arm("point", k))
        out[f"arm-pour-{k}"] = (ARM_BOX, arm("pour", k))
    return out


def atlas(all_pieces):
    scene = ["bg", "shelf", "counter", "pan", "flame-big-0", "chef-idle-0", "arm-rest-w"]
    keys = {"flame-big-0": "flame", "chef-idle-0": "chef", "arm-rest-w": "arm"}
    lines = ["// Written by art/make.py: where each piece of the kitchen sits in the scene. Don't edit.",
             f"export const SCENE = {{ w: {SCENE_W}, h: {SCENE_H} }};",
             f"export const PAN = {{ x: {PAN_X}, w: {PAN_W}, ballY: {BALL_Y} }};",
             f"export const SPRITE = {{ w: {SPRITE_W}, h: {SPRITE_H}, cx: {SPRITE_CX}, cy: {SPRITE_CY} }};",
             f"export const SHELF = {{ x: {SHELF_X}, rows: [{SHELF_ROWS[1]}, {SHELF_ROWS[0]}], pitch: {SHELF_PITCH}, perRow: {SHELF_PER_ROW}, "
             f"boat: {{ w: {BOAT_W}, h: {BOAT_H + 2}, dy: {-BOAT_H - 1} }} }};",
             f"export const ARM_POSES = {ARM_POSES};",
             f"export const COOK_STEPS = {COOK_STEPS};",
             "// [left, top, width, height] in scene px.",
             "export const BOX = {"]
    for name in scene:
        x, y, w, h = all_pieces[name][0]
        lines.append(f"  {keys.get(name, name)}: [{x}, {y}, {w}, {h}],")
    lines.append("};")
    return "\n".join(lines) + "\n"


def preview(all_pieces, mood):
    """The whole scene from the pieces, as main.js stacks them."""
    def at(name, x=None, y=None, scale=1.0):
        box, body = all_pieces[name]
        if x is None:
            return body
        return f'<g transform="translate({x - box[0]} {y - box[1]}) scale({scale})">{body}</g>'

    def ball(name, i, n=6):
        hx = PAN_X + PAN_W * (i + .5) / n
        return at(name, hx - SPRITE_CX, BALL_Y - SPRITE_CY)

    tag = "f" if MOODS[mood].get("palette") == "flush" else "w"
    states = ["ball-raw", "ball-cooking-1", "ball-cooking-4", "ball-ready", "ball-capped", "ball-burnt"]
    if mood in ("sad", "worried", "doze"):
        states = ["ball-cooking-0", "ball-cooking-2", "ball-cooking-3", "ball-stalled", "ball-burnt", None]
    parts = [at("bg"), at("shelf")]
    for i in range(5):
        parts.append(at("boat", SHELF_X + (i % 4) * SHELF_PITCH, SHELF_ROWS[1 - i // 4] - BOAT_H + 1))
    parts += [at(f"chef-{mood}-0"), at("counter")]
    if mood not in ("sleep",):
        parts.append(at("flame-big-0" if mood in ("busy", "flip", "pour") else "flame-pilot-0"))
    parts.append(at("pan"))
    for i, s in enumerate(states):
        parts.append(ball("hole", i))
        if s in ("ball-ready",):
            parts.append(ball("glow-ready", i))
        if i == 2:
            parts.append(ball("focus", i))
        if s:
            parts.append(ball(s, i))
    arm_name = {"sleep": "arm-down-w", "doze": "arm-down-w", "sad": "arm-down-f", "happy": "arm-cheer-w", "serve": "arm-cheer-w",
                "surprised": "arm-rest-w", "idle": "arm-rest-w", "worried": "arm-rest-f", "pour": "arm-pour-4"}.get(mood, "arm-point-2")
    parts.append(at(arm_name))
    parts.append(at("steam", PAN_X + PAN_W * 1.5 / 6 - 12, 92))
    parts.append(at("smoke", PAN_X + PAN_W * (5.5 if states[5] else 4.5) / 6 - 20, 84))
    parts.append(at("burst-sparkle", PAN_X + PAN_W * 3.5 / 6 - 18, 84))
    return svg_doc((0, 0, SCENE_W, SCENE_H), "".join(parts))


def render(svg, png):
    if shutil.which("rsvg-convert"):
        cmd = ["rsvg-convert", "-z", str(SCALE), "-o", png, svg]
    elif shutil.which("inkscape"):
        cmd = ["inkscape", svg, "--export-type=png", f"--export-filename={png}", f"--export-dpi={96 * SCALE}"]
    else:
        cmd = ["magick", "-background", "none", "-density", str(96 * SCALE), svg, png]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main(argv):
    svg_dir = os.path.join(HERE, "svg")
    png_dir = os.path.join(HERE, "png")
    os.makedirs(svg_dir, exist_ok=True)
    os.makedirs(png_dir, exist_ok=True)
    all_pieces = pieces()
    if "--preview" in argv:
        i = argv.index("--preview")
        moods = argv[i + 1:] or ["busy"]
        for mood in moods:
            path = os.path.join(svg_dir, f"preview-{mood}.svg")
            with open(path, "w", encoding="utf-8") as f:
                f.write(preview(all_pieces, mood))
            render(path, path.replace(".svg", ".png"))
            print(path.replace(".svg", ".png"))
        return
    for stale in os.listdir(png_dir):
        if stale.endswith(".png") and stale[:-4] not in all_pieces:
            os.remove(os.path.join(png_dir, stale))
    for name, (box, body) in all_pieces.items():
        path = os.path.join(svg_dir, f"{name}.svg")
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg_doc(box, body))
        render(path, os.path.join(png_dir, f"{name}.png"))
    with open(os.path.join(HERE, "..", "atlas.js"), "w", encoding="utf-8") as f:
        f.write(atlas(all_pieces))
    print(f"{len(all_pieces)} pieces")


if __name__ == "__main__":
    main(sys.argv[1:])
