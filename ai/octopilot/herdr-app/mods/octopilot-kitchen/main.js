// The takoyaki kitchen, as a pane or a floating block: the octopus chef behind the pan, one
// ball per tracked item, flames, the shelf of served boats, and a speech bubble with the
// orchestrator's last message and the kitchen log. Props: see README.md.

import { View, div, image, svg } from "gpui-kit";
import { v_flex, h_flex, TextView } from "gpui-base";
import { exec, readTextFile, watchFolder, run, theme, props, shared, home, window, placement, openOverlay, closeOverlay, checking, panes, spaces } from "herdr";
import { clip } from "./clip.js";
import { SCENE, BOX, SPRITE } from "./atlas.js";
import { derive, holeAt, spriteBox, boatBox, offlineReason, WALK_MS, LOG_LINES } from "./kitchen.js";
import { paneLayout, bubbleRows, PANE, PANE_DEFAULT } from "./layout.js";
import { machineCache, addressOn } from "./machine.js";

const MOD = "octopilot-kitchen";
const BUBBLE_W = 340;
const FAST_MS = 2000;
const SLOW_MS = 10000;
const BLINK_MS = 4600;
const FOLD_KEY = "octopilot-kitchen.folded";

const WORD = { working: "working", blocked: "needs you", idle: "idle", done: "finished", offline: "offline" };
const DOT = { working: "working", blocked: "blocked", idle: "idle", done: "done", offline: "unknown" };
// How the chef moves per mood: [bob period, frame crossfade period] in ms; 0 holds still.
const MOTION = {
  idle: [2600, 2200], busy: [900, 700], flip: [800, 600], pour: [1400, 900], happy: [700, 600], serve: [700, 600],
  worried: [1600, 1200], sad: [3000, 1600], surprised: [500, 500], sleep: [3400, 3000], doze: [0, 3200],
};
// Fixed colours for what is written on the art, which keeps its own palette in every theme.
const INK = { chip: "#1b2430cc", hover: "#1b2430", text: "#fff3dc", dim: "#000000" };

// A path the layout (props) or another mod (shared) set, or null.
function setting(prop, sharedKey) {
  const value = props()?.[prop] ?? shared(sharedKey);
  return typeof value === "string" && value ? value : null;
}

// scan.sh would otherwise take herdr-app's own environment: name the backend and the code,
// and the state folder only when one was set, so its own default stands otherwise.
function scanArgs(where, ...args) {
  return ["OCTOPILOT_BACKEND=hc", `OCTOPILOT_DIR=${where.dir}`,
    ...(where.stateExplicit ? [`OCTOPILOT_STATE_DIR=${where.stateExplicit}`] : []),
    `${where.dir}/scan.sh`, ...args];
}

const art = (name) => `mods/${MOD}/art/png/${name}.png`;
// The scale the scene is being drawn at: 1 floating, the pane's fit otherwise. scene() sets it.
let K = 1;
// A piece of art at [left, top, width, height] of the scene.
const piece = (name, [x, y, w, h]) => image(art(name)).absolute().left(x * K).top(y * K).w(w * K).h(h * K);
const layer = ([x, y, w, h]) => div().absolute().left(x * K).top(y * K).w(w * K).h(h * K);
// Floating blocks have a placement; a pane (or an overlay) has none.
const inPane = () => placement() == null;

async function readJson(path, on) {
  const text = await readTextFile(path, { on });
  if (text == null) throw new Error(`no file at ${path}`);
  return JSON.parse(text);
}

export default class Kitchen extends View {
  init(_props, cx) {
    this.machineOf = machineCache();
    this.view = null;
    this.viewError = null;
    this.speech = null;
    this.error = null;
    this.walk = 0;
    this.blink = false;
    this.wake = 0;
    this.sig = null;
    this.size = null;
    // Folded as last left, else as the layout asks.
    this.folded = props()?.folded === true;
    try {
      const kept = localStorage.getItem(FOLD_KEY);
      if (kept != null) this.folded = kept === "1";
    } catch (_e) { /* no storage */ }
    this.model = derive(null, Date.now());
    if (checking() || props()?.full) return;
    this.poll(cx);
    this.watch(cx);
    this.walks(cx);
    this.blinks(cx);
  }

  // The machine of this copy's space: null here, a name when remote, undefined while not known
  // yet. A floating copy has no pane: it may use the shown tab, when the mod has no pane at all.
  // Fixtures are always local.
  machine() {
    if (props()?.fixture) return null;
    return this.machineOf(panes(), spaces(), { mod: MOD, name: props()?.pane_name ?? null, floating: placement() != null });
  }

  // Where the octopilot is, on its machine (`on`, null here): the code dir, the state dir (null:
  // scan.sh's own default). A remote space needs its props (dir and state_dir); home() and shared
  // paths are this computer's. `missing` says what the props lack, else null. `unknown`: no
  // machine yet, so nothing is read.
  where() {
    const p = props() ?? {};
    const on = this.machine();
    if (on === undefined) return { on, unknown: true, dir: null, stateExplicit: null, stateDir: null, missing: null };
    if (on) {
      const dir = p.dir || null;
      const stateExplicit = p.state_dir || null;
      const missing = !dir ? `no octopilot dir for ${on}` : !stateExplicit ? `no octopilot state dir for ${on}` : null;
      return { on, unknown: false, dir, stateExplicit, stateDir: stateExplicit, missing };
    }
    const stateExplicit = setting("state_dir", "octopilot.state_dir");
    return {
      on: null,
      unknown: false,
      dir: setting("dir", "octopilot.dir") ?? `${home()}/.dotfiles/ai/octopilot`,
      stateExplicit,
      stateDir: stateExplicit ?? `${home()}/.local/state/octopilot`,
      missing: null,
    };
  }

  // A fixture's clock stands still at the moment it was made, so its moods and bursts stay on show.
  now() {
    const p = props() ?? {};
    if (!p.fixture) return Date.now();
    return (Number(p.fixture_now) || Number(this.view?.generated_at) || 0) * 1000;
  }

  shown() {
    return window()?.visible !== false;
  }

  // A pane has no fold: whatever a floating copy last kept doesn't hide its bubble.
  isFolded() {
    return this.folded && !inPane();
  }

  // Reads everything every FAST_MS while the window shows (the fallback for the watch below,
  // and what notices a kitchen gone stale), slowly while hidden.
  poll(cx) {
    cx.spawn(async (cx) => {
      for (;;) {
        // Folded, the bubble is gone: no need to ask for the speech.
        await Promise.all([this.loadView(), this.isFolded() ? null : this.loadSpeech()]);
        this.refresh(cx);
        await cx.sleep(this.shown() ? FAST_MS : SLOW_MS);
      }
    });
  }

  // view.json the moment the dashboard rewrites it.
  watch(cx) {
    if (props()?.fixture) return;
    cx.spawn(async (cx) => {
      for (;;) {
        // A folder on another machine cannot be watched from here: the poll reads it instead.
        if (this.machine() !== null) {
          await cx.sleep(FAST_MS);
          continue;
        }
        try {
          await watchFolder(this.where().stateDir);
        } catch (_e) {
          return;
        }
        await this.loadView();
        this.refresh(cx);
      }
    });
  }

  // While the orchestrator works, the chef's pick walks along the pan.
  walks(cx) {
    cx.spawn(async (cx) => {
      for (;;) {
        await cx.sleep(WALK_MS);
        if (!this.shown() || this.model.mood !== "busy" || !this.model.busy || this.model.balls.length < 2) continue;
        this.walk += 1;
        this.refresh(cx);
      }
    });
  }

  blinks(cx) {
    cx.spawn(async (cx) => {
      for (;;) {
        await cx.sleep(BLINK_MS + Math.random() * 2400);
        if (!this.shown() || !this.model.blinks) continue;
        this.blink = true;
        cx.notify();
        await cx.sleep(140);
        this.blink = false;
        cx.notify();
      }
    });
  }

  async loadView() {
    const p = props() ?? {};
    const w = this.where();
    if (w.unknown) return;   // not known yet: the next poll asks again
    try {
      if (w.missing) throw new Error(w.missing);
      this.view = await readJson(p.fixture ?? `${w.stateDir}/view.json`, w.on);
      this.viewError = null;
    } catch (e) {
      // A missing or half-written view.json: no kitchen for now, and the chip says why.
      this.view = null;
      this.viewError = String(e?.message ?? e).split("\n")[0].slice(0, 80);
    }
  }

  async loadSpeech() {
    const p = props() ?? {};
    try {
      if (p.fixture_speech) this.speech = await readJson(p.fixture_speech);
      else if (p.fixture) this.speech = null;
      else {
        const w = this.where();
        if (w.unknown) return;   // not known yet: the speech waits for the next poll
        if (w.missing) throw new Error(w.missing);
        const r = await exec("env", scanArgs(w, "speech", "--json"), { timeout: 15000, on: w.on });
        if (r.code !== 0) throw new Error(r.stderr.trim().split("\n")[0] || `exit ${r.code}`);
        this.speech = JSON.parse(r.stdout);
      }
      this.error = null;
    } catch (e) {
      this.speech = null;
      this.error = String(e?.message ?? e).slice(0, 120);
    }
  }

  // Works out what to show and redraws only when it changed; then sleeps until the mood or
  // burst on show ends, to take it down on time.
  refresh(cx) {
    this.model = derive(this.view, this.now(), this.walk, inPane() ? PANE.logMax : LOG_LINES);
    const s = this.speech;
    const sig = JSON.stringify([this.model, s?.seq, s?.status, s?.text, s?.terminal, this.error]);
    if (sig !== this.sig) cx.notify();
    this.sig = sig;
    // A fixture's clock stands still, so nothing on show ever ends.
    if (props()?.fixture) return;
    const wake = ++this.wake;
    const wait = this.model.until == null ? 0 : this.model.until - this.now();
    if (wait <= 0) return;
    cx.spawn(async (cx) => {
      await cx.sleep(wait + 30);
      if (this.wake === wake) this.refresh(cx);
    });
  }

  peek() {
    const terminal = this.speech?.terminal;
    const on = this.machine();
    if (terminal && on !== undefined) run("terminal.peek", { terminal: addressOn(on, terminal) });
  }

  openFull() {
    if (!this.speech?.text) return;
    openOverlay({
      mod: MOD,
      kind: "dialog",
      width: 0.6,
      height: 0.7,
      props: { full: true, text: this.speech.text, status: this.speech.status },
    });
  }

  fold(cx) {
    this.folded = !this.folded;
    try { localStorage.setItem(FOLD_KEY, this.folded ? "1" : "0"); } catch (_e) { /* not kept, that's all */ }
    cx.notify();
    if (this.folded) return;
    cx.spawn(async (cx) => {
      await this.loadSpeech();
      this.refresh(cx);
    });
  }

  chef(m) {
    const [bob, fade] = MOTION[m.mood] ?? MOTION.idle;
    const [x, y, w, h] = BOX.chef;
    const full = [0, 0, w, h];
    const body = div().relative().w(w * K).h(h * K).children([
      piece(`chef-${m.mood}-0`, full),
      piece(`chef-${m.mood}-1`, full).loop("opacity", { from: 0, to: 1, period: fade }),
      this.blink && m.blinks ? piece(`blink-${m.flushed ? "f" : "w"}`, full) : null,
    ].filter(Boolean));
    return layer([x, y, w, h]).child(bob ? body.loop("top", { from: 0, to: -2.5 * K, period: bob }) : body);
  }

  arm(m) {
    const [left, y, w, h] = BOX.arm;
    const x = left + m.armShift;
    const working = m.arm.startsWith("arm-point") || m.arm.startsWith("arm-pour");
    const inner = image(art(m.arm)).w(w * K).h(h * K);
    // The pick dips into the ball while he works it.
    return layer([x, y, w, h]).child(working
      ? div().relative().w(w * K).h(h * K).loop("top", { from: -1.5 * K, to: 2 * K, period: m.arm.startsWith("arm-pour") ? 1100 : 480 }).child(inner)
      : inner);
  }

  flames(m) {
    if (m.flames === "none") return [];
    const period = m.flames === "big" ? 260 : 900;
    return [
      piece(`flame-${m.flames}-0`, BOX.flame),
      piece(`flame-${m.flames}-1`, BOX.flame).loop("opacity", { from: 0, to: 1, period }),
    ];
  }

  // The holes and what's in them, back to front: hole, glow, focus ring, ball.
  pan(m) {
    const out = [];
    for (let i = 0; i < m.holes; i++) {
      const box = spriteBox(i, m.holes);
      const ball = m.balls[i];
      out.push(piece("hole", box));
      if (!ball) continue;
      if (ball.state === "ready" || ball.state === "capped") {
        out.push(piece(`glow-${ball.state}`, box)
          .loop("opacity", { from: 0.25, to: 1, period: ball.state === "capped" ? 800 : 1500 }));
      }
      if (ball.focus) out.push(piece("focus", box).loop("opacity", { from: 0.45, to: 1, period: 1000 }));
      out.push(piece(ball.sprite, box));
    }
    return out;
  }

  // Steam off what's cooking and smoke off what's burnt, drifting up natively.
  wisps(m) {
    const out = [];
    m.balls.forEach((ball, i) => {
      const burnt = ball.state === "burnt";
      if (!burnt && (ball.state !== "cooking" || m.flames === "none")) return;
      const { x, scale } = holeAt(i, m.holes);
      const [w, h] = burnt ? [34 * scale, 37 * scale] : [20 * scale, 30 * scale];
      const period = 2200 + (i % 3) * 500;
      out.push(layer([x - w / 2 + (burnt ? 5 : 0), BOX.pan[1] - h - 2, w, h])
        .child(div().relative().w(w * K).h(h * K).loop("top", { from: 3 * K, to: -5 * K, period })
          .child(image(art(burnt ? "smoke" : "steam")).w(w * K).h(h * K)
            .loop("opacity", { from: burnt ? 0.5 : 0.15, to: burnt ? 0.95 : 0.8, period }))));
    });
    return out;
  }

  // The newest event's burst: over its ball, over its boat, or by the chef's head.
  burst(m) {
    const b = m.burst;
    if (!b) return null;
    const size = 34;
    let x = 2;
    let y = 22;
    if (b.hole >= 0) {
      x = holeAt(b.hole, m.holes).x - size / 2;
      y = BOX.pan[1] - size + 8;
    } else if (b.boat >= 0) {
      const [bx, by, bw] = boatBox(b.boat);
      x = bx + bw / 2 - size / 2;
      y = by - size + 8;
    }
    return layer([x, y, size, size])
      .child(div().relative().size(size * K).loop("top", { from: 4 * K, to: -4 * K, period: 700 })
        .child(image(art(`burst-${b.kind}`)).size(size * K).loop("opacity", { from: 0.7, to: 1, period: 700 })));
  }

  chip(text) {
    return div().px(7).py(2).rounded(8).bg(INK.chip).text_size(11).text_color(INK.text).child(text);
  }

  // The scene at `scale` times its 360x220; `fold` adds the floating block's fold button.
  scene(t, m, scale = 1, fold = true) {
    K = scale;
    const [W, H] = [SCENE.w * K, SCENE.h * K];
    const focused = m.balls[m.focus];
    const kids = [
      piece("bg", BOX.bg),
      piece("shelf", BOX.shelf),
      ...Array.from({ length: m.boats }, (_v, i) => piece("boat", boatBox(i))),
      this.chef(m),
      piece("counter", BOX.counter),
      ...this.flames(m),
      piece("pan", BOX.pan),
      ...this.pan(m),
      this.arm(m),
      ...this.wisps(m),
      this.burst(m),
      // What the chef is on, written on the counter's front.
      focused?.label && !m.offline
        ? div().absolute().left(0).w(W).top(H - 20).flex().justify_center().child(this.chip(`▸ ${focused.label}`))
        : null,
      m.offline ? div().absolute().left(0).top(0).w(W).h(H).rounded(10).bg(INK.dim).opacity(0.45) : null,
      m.offline
        ? div().absolute().left(0).w(W).top(H / 2 - 12).flex().justify_center()
          .child(this.chip(`kitchen offline: ${offlineReason(this.view, this.now(), this.viewError)}`))
        : null,
      // Click the chef to look into the orchestrator's terminal.
      layer([BOX.chef[0] + 14, BOX.chef[1] + 8, 112, 124]).id("chef").cursor_pointer()
        .on_mouse_down("left", (_e, cx) => cx.stop_propagation()).on_click(() => this.peek()),
      !fold ? null : div().id("fold").absolute().left(W - 26).top(H - 22).w(20).h(16).rounded(8).bg(INK.chip)
        .flex().items_center().justify_center().text_size(11).text_color(INK.text).cursor_pointer()
        .hover((s) => s.bg(INK.hover))
        .on_mouse_down("left", (_e, cx) => cx.stop_propagation())
        .on_click((_e, cx) => { cx.stop_propagation(); this.fold(cx); })
        .child(this.folded ? "+" : "–"),
    ];
    return div().relative().flex_none().w(W).h(H).children(kids.filter(Boolean));
  }

  status() {
    if (this.error) return "offline";
    return this.speech?.status ?? "offline";
  }

  speechBody(t, lines, chars) {
    const s = this.speech;
    const muted = (text) => div().text_size(12).text_color(t.muted).child(text);
    if (this.error) return muted(`Can't reach the orchestrator: ${this.error}`);
    if (!s) return muted("Waiting for the orchestrator…");
    if (!s.text) return muted(s.status === "offline" ? "The orchestrator is offline." : "The orchestrator hasn't said anything yet.");
    return div().id("speech").text_size(13).text_color(t.foreground).cursor_pointer()
      .on_mouse_down("left", (_e, cx) => cx.stop_propagation()).on_click(() => this.openFull())
      .child(TextView.markdown("octopilot-speech", clip(s.text, lines, chars)).raw_html(false));
  }

  logLines(t, m, max = LOG_LINES) {
    const lines = max > 0 ? m.log.slice(-max) : [];
    if (!lines.length) return null;
    const color = (line) => (line.tone === "good" ? t.ansi2 : line.tone === "bad" ? t.ansi1 : t.foreground);
    return v_flex().gap(2).pt(6).border_t(1).border_color(t.border).text_size(11).children(lines.map((line) =>
      h_flex().gap(6).items_center().opacity(line.dim ? 0.55 : 1)
        .child(div().flex_none().text_color(t.dim).child(line.clock))
        .child(div().flex_1().overflow_hidden().truncate().text_color(color(line)).child(line.text))));
  }

  // The kitchen's line, then who is talking and how they are doing.
  heading(t, m) {
    const status = this.status();
    const on = this.machine();
    return [
      div().flex_none().overflow_hidden().truncate().text_size(11).text_color(t.muted).child(m.header),
      h_flex().flex_none().gap(6).items_center().children([
        div().size(7).rounded(4).flex_none().bg(t[DOT[status]] ?? t.muted),
        div().text_size(11).text_color(t.dim).child(`octopilot · ${WORD[status] ?? status}${on ? ` · on ${on}` : ""}`),
      ]),
    ];
  }

  // The bubble, with its tail towards the chef: below it when stacked, to its right in a row.
  bubble(t, m, vertical) {
    const log = this.logLines(t, m);
    // The tail twice: once in the border's colour, then the fill a pixel inside it.
    const tail = (color, out) => (vertical
      ? svg(`mods/${MOD}/tail-down.svg`).absolute().left(58).bottom(-out).w(20).h(10)
      : svg(`mods/${MOD}/tail-right.svg`).absolute().right(-out).top(70).w(10).h(20)).text_color(color);
    return div().relative().flex_none().w(vertical ? SCENE.w : BUBBLE_W).child(
      v_flex().p(10).gap(6).rounded(12).bg(t.popover).border(1).border_color(t.border).children([
        ...this.heading(t, m),
        this.speechBody(t),
        log,
      ].filter(Boolean)),
    ).child(tail(t.border, 9.5)).child(tail(t.popover, 8));
  }

  // The pane's bubble: all the width the scene leaves and the pane's height, the message
  // cut to what fits over the log, the tail at the chef's face.
  paneBubble(t, m, l) {
    const rows = bubbleRows(l.textW, l.textH, m.log.length);
    const tail = (color, out) => svg(`mods/${MOD}/tail-right.svg`).absolute().right(-out).top(l.tailTop).w(10).h(20)
      .text_color(color);
    return div().relative().flex_1().min_w(0).h(l.textH).child(
      v_flex().size_full().overflow_hidden().p(10).gap(6).rounded(12).bg(t.popover).border(1).border_color(t.border)
        .children([
          ...this.heading(t, m),
          div().flex_1().min_h(0).overflow_hidden().child(this.speechBody(t, rows.lines, rows.chars)),
          this.logLines(t, m, rows.log)?.flex_none(),
        ].filter(Boolean)),
    ).child(tail(t.border, 9.5)).child(tail(t.popover, 8));
  }

  // In a pane: the scene as tall as the pane on the right, the bubble in the rest.
  renderPane(t, m) {
    const { width, height } = this.size ?? PANE_DEFAULT;
    const l = paneLayout(width, height);
    const scene = this.scene(t, m, l.scale, false);
    return h_flex().id("kitchen-pane").size_full().overflow_hidden().bg(t.background)
      .p(PANE.pad).gap(PANE.gap).items_center().justify_center()
      .on_size_change((size, cx) => {
        const next = { width: Math.round(size.width), height: Math.round(size.height) };
        if (next.width === this.size?.width && next.height === this.size?.height) return;
        this.size = next;
        cx.notify();
      })
      .children(l.text ? [this.paneBubble(t, m, l), scene] : [scene]);
  }

  render() {
    const p = props() ?? {};
    if (p.full) return this.renderFull(p);
    const t = theme();
    const m = this.model;
    if (inPane()) return this.renderPane(t, m);
    const vertical = placement()?.vertical !== false;
    const scene = this.scene(t, m);
    if (this.folded) return div().p(6).child(scene);
    const kids = [this.bubble(t, m, vertical), scene];
    return (vertical ? v_flex() : h_flex().items_start()).p(6).gap(10).children(kids);
  }

  renderFull(p) {
    const t = theme();
    return v_flex().size_full().p(16).gap(10).bg(t.popover).children([
      h_flex().justify_between().items_center().flex_none().children([
        div().text_size(13).font_semibold().text_color(t.foreground)
          .child(`Octopilot · ${WORD[p.status] ?? p.status ?? ""}`),
        p.overlay
          ? div().id("close").px(6).rounded(5).text_color(t.muted).cursor_pointer()
            .hover((s) => s.bg(t.hover).text_color(t.foreground))
            .on_click(() => closeOverlay(p.overlay)).child("✕")
          : null,
      ].filter(Boolean)),
      div().id("speech-full").flex_1().overflow_y_scrollbar().text_size(13).text_color(t.foreground)
        .child(TextView.markdown("octopilot-speech-full", p.text ?? "").raw_html(false)),
    ]);
  }
}
