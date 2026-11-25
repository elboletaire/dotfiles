// The messenger as a reluctant octopus: a floating window with the octopus, a
// speech bubble holding the orchestrator's last message and the kitchen's last
// lines. Click the octopus to peek the messenger's terminal, the bubble to read
// the whole message, – to fold the bubble, ✕ to close.
// Props: { fixture?, dir?, state_dir?, overlay? }, or for the full-text dialog
// { full: true, text, status }.

import { View, div, image } from "gpui-kit";
import { v_flex, h_flex, TextView } from "gpui-base";
import { exec, readTextFile, run, theme, props, shared, home, window, openOverlay, closeOverlay, checking } from "herdr";

const OCTO_W = 125;
const OCTO_H = 150;
const BUBBLE_W = 250;
const FAST_MS = 2000;
const SLOW_MS = 10000;
const TALK_MS = 4000;
const MOOD_S = 5;
const DOZE_S = 600;
const LOG_LINES = 4;
const MAX_LINES = 6;
const MAX_CHARS = 280;

const WORD = { working: "working", blocked: "needs you", idle: "idle", done: "finished", offline: "offline", paused: "paused" };
const DOT = { working: "working", blocked: "blocked", idle: "idle", done: "done", offline: "unknown", paused: "idle" };
// The kitchen's mood names (scene.ts) as poses; only the first group shows for a while.
const MOOD_POSE = { happy: "happy", serve: "happy", worried: "worried", sad: "sad", surprised: "surprised", flip: "working", pour: "working", busy: "working", sleep: "sleeping", doze: "doze", idle: "idle" };
const TRANSIENT = new Set(["happy", "serve", "worried", "sad", "surprised"]);
// Poses whose frames cross-fade back and forth: [frame names, cycle ms].
const FLIPS = {
  talking: [["talking-0", "talking-1"], 360],
  working: [["working-0", "working-1"], 1200],
  blocked: [["blocked-0", "blocked-1"], 900],
  sleeping: [["sleeping-0", "sleeping-1"], 2400],
  happy: [["happy-0", "happy-1"], 900],
  worried: [["worried-0", "worried-1"], 1400],
  sad: [["sad-0", "sad-1"], 2000],
  surprised: [["surprised-0", "surprised-1"], 500],
};

// A path setting from props, else shared, else the default.
function pick(prop, sharedKey, fallback) {
  const value = props()?.[prop] ?? shared(sharedKey);
  return typeof value === "string" && value ? value : fallback;
}

const octopilotDir = () => pick("dir", "octopilot.dir", `${home()}/.dotfiles/ai/octopilot`);
const stateDir = () => pick("state_dir", "octopilot.state_dir", `${home()}/.local/state/octopilot`);

// The art in mods/octopilot-octopus/art/png, 320 px tall, shown at OCTO_H.
function art(name) {
  return image(`mods/octopilot-octopus/art/png/${name}-320.png`).w(OCTO_W).h(OCTO_H).flex_none();
}

// Two poses cross-fading back and forth forever: native motion, no redraws.
function flip(names, period) {
  return div().relative().flex_none().w(OCTO_W).h(OCTO_H).children(
    names.map((name, i) =>
      image(`mods/octopilot-octopus/art/png/${name}-320.png`).absolute().top(0).left(0).w(OCTO_W).h(OCTO_H)
        .loop("opacity", { from: i === 0 ? 1 : 0, to: i === 0 ? 0 : 1, period })));
}

// Long messages are cut to a few lines; the bubble opens the rest.
function clip(text) {
  const lines = text.split("\n");
  if (lines.length <= MAX_LINES && text.length <= MAX_CHARS) return text;
  const cut = lines.slice(0, MAX_LINES).join("\n").slice(0, MAX_CHARS).trimEnd();
  return `${cut} …*more*`;
}

const pad = (n) => String(n).padStart(2, "0");
const clock = (at) => {
  const d = new Date(at * 1000);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

export default class Octopus extends View {
  init(_props, cx) {
    this.data = null;
    this.view = null;
    this.error = null;
    this.seq = undefined;
    this.talking = false;
    this.talkGen = 0;
    this.sigh = false;
    this.collapsed = false;
    if (checking() || props()?.full) return;
    this.watch(cx);
    this.sighs(cx);
  }

  // Polls the messenger and the kitchen: fast while the window shows, slow while hidden.
  watch(cx) {
    cx.spawn(async (cx) => {
      for (;;) {
        await this.poll(cx);
        cx.notify();
        await cx.sleep(window()?.visible === false ? SLOW_MS : FAST_MS);
      }
    });
  }

  // An occasional sigh: the second idle frame for a moment.
  sighs(cx) {
    cx.spawn(async (cx) => {
      for (;;) {
        await cx.sleep(7000 + Math.random() * 5000);
        this.sigh = true;
        cx.notify();
        await cx.sleep(1600);
        this.sigh = false;
        cx.notify();
      }
    });
  }

  async read() {
    const p = props() ?? {};
    if (p.fixture) {
      const text = await readTextFile(p.fixture);
      if (text == null) throw new Error(`no fixture at ${p.fixture}`);
      return JSON.parse(text);
    }
    const r = await exec(`${octopilotDir()}/scan.sh`, ["speech", "--json"], { timeout: 15000 });
    if (r.code !== 0) throw new Error(r.stderr.trim().split("\n")[0] || `exit ${r.code}`);
    return JSON.parse(r.stdout);
  }

  // view.json is the headless dashboard's state; a missing or unreadable one just means no kitchen.
  async readView() {
    try {
      const text = await readTextFile(`${stateDir()}/view.json`);
      return text == null ? null : JSON.parse(text);
    } catch (_e) {
      return null;
    }
  }

  async poll(cx) {
    this.view = await this.readView();
    let next;
    try {
      next = await this.read();
      this.error = null;
    } catch (e) {
      this.data = null;
      this.error = String(e?.message ?? e).slice(0, 120);
      return;
    }
    if (this.seq !== undefined && next.seq !== this.seq && next.text) this.talk(cx);
    this.seq = next.seq;
    this.data = next;
  }

  talk(cx) {
    const gen = ++this.talkGen;
    this.talking = true;
    cx.spawn(async (cx) => {
      await cx.sleep(TALK_MS);
      if (this.talkGen !== gen) return;
      this.talking = false;
      cx.notify();
    });
  }

  kitchen() {
    return Array.isArray(this.view?.kitchen) ? this.view.kitchen : [];
  }

  newest() {
    let best = null;
    for (const ev of this.kitchen()) if (!best || ev.at > best.at) best = ev;
    return best;
  }

  pose() {
    if (this.error || this.data?.status === "offline") return "offline";
    if (!this.data) return "idle";
    if (this.talking) return "talking";
    if (this.data.status === "blocked") return "blocked";
    if (this.data.paused || this.view?.header?.paused) return "sleeping";
    const ev = this.newest();
    const age = ev ? Date.now() / 1000 - ev.at : 0;
    if (ev && TRANSIENT.has(ev.mood) && age < MOOD_S) return MOOD_POSE[ev.mood];
    if (this.data.status === "working") return "working";
    if (ev && age > DOZE_S) return "doze";
    return "idle";
  }

  octopus(pose) {
    if (FLIPS[pose]) return flip(...FLIPS[pose]);
    if (pose === "offline") return art("offline-0");
    // Breathing: the whole octopus drifts up and down, natively.
    return div().relative().flex_none().loop("top", { from: 0, to: -3, period: 2600 })
      .child(art(pose === "idle" && this.sigh ? "idle-1" : `${pose}-0`));
  }

  peek() {
    const terminal = this.data?.terminal;
    if (terminal) run("terminal.peek", { terminal });
  }

  openFull() {
    if (!this.data?.text) return;
    openOverlay({
      mod: "octopilot-octopus",
      kind: "dialog",
      width: 0.6,
      height: 0.7,
      props: { full: true, text: this.data.text, status: this.data.status },
    });
  }

  button(t, id, label, onClick) {
    return div()
      .id(id)
      .px(6)
      .rounded(5)
      .text_color(t.muted)
      .cursor_pointer()
      .hover((s) => s.bg(t.hover).text_color(t.foreground))
      .on_mouse_down("left", (_e, cx) => cx.stop_propagation())
      .on_click((_e, cx) => {
        cx.stop_propagation();
        onClick(cx);
      })
      .child(label);
  }

  status() {
    if (this.error || this.data?.status === "offline") return "offline";
    if (this.data?.paused || this.view?.header?.paused) return "paused";
    return this.data?.status ?? "waiting";
  }

  bubbleBody(t) {
    const d = this.data;
    const muted = (text) => div().text_size(12).text_color(t.muted).child(text);
    if (this.error) return muted(`Can't reach the messenger: ${this.error}`);
    if (!d) return muted("Waiting for the messenger…");
    if (!d.text) return muted("The messenger hasn't said anything yet.");
    return div().text_size(13).text_color(t.foreground)
      .child(TextView.markdown("octopilot-speech", clip(d.text)).raw_html(false));
  }

  // The last kitchen lines, oldest dim, the newest green (good), red (bad) or plain.
  logLines(t) {
    const lines = [...this.kitchen()].sort((a, b) => a.at - b.at).slice(-LOG_LINES);
    if (!lines.length) return null;
    return v_flex().gap(2).text_size(11).children(lines.map((ev, i) => {
      const newest = i === lines.length - 1;
      const color = !newest ? t.dim : ev.good === true ? t.done : ev.good === false ? t.blocked : t.foreground;
      return h_flex().gap(6).items_center()
        .child(div().flex_none().text_color(t.dim).child(clock(ev.at)))
        .child(div().flex_1().overflow_hidden().truncate().text_color(color).child(ev.text ?? ""));
    }));
  }

  render() {
    const p = props() ?? {};
    if (p.full) return this.renderFull(p);
    const t = theme();
    const pose = this.pose();
    const status = this.status();
    const dot = t[DOT[status]] ?? t.muted;
    const header = this.view?.header;
    const pans = header && typeof header.active === "number" ? `pans ${header.active}/${header.max_active}` : null;
    const log = this.logLines(t);
    return h_flex().p(4).gap(8).items_end().children([
      div().id("octopus").flex_none().cursor_pointer().on_click(() => this.peek()).child(this.octopus(pose)),
      this.collapsed
        ? this.button(t, "show", "▸", (cx) => { this.collapsed = false; cx.notify(); })
        : v_flex().id("bubble").w(BUBBLE_W).p(10).gap(6).rounded(12).bg(t.popover).border(1).border_color(t.border)
          .cursor_pointer().on_click(() => this.openFull())
          .children([
            h_flex().justify_between().items_center().children([
              h_flex().gap(6).items_center().children([
                div().size(7).rounded(4).flex_none().bg(dot),
                div().text_size(11).text_color(t.muted).child(`messenger · ${WORD[status] ?? status}`),
              ]),
              h_flex().gap(2).items_center().children([
                pans ? div().text_size(11).text_color(t.dim).child(pans) : null,
                this.button(t, "fold", "–", (cx) => { this.collapsed = true; cx.notify(); }),
                this.button(t, "close", "✕", () => closeOverlay(p.overlay)),
              ].filter(Boolean)),
            ]),
            this.bubbleBody(t),
            ...(log ? [log] : []),
          ]),
    ]);
  }

  renderFull(p) {
    const t = theme();
    return v_flex().size_full().p(16).gap(10).bg(t.popover).children([
      h_flex().justify_between().items_center().flex_none()
        .child(div().text_size(13).font_semibold().text_color(t.foreground)
          .child(`Messenger · ${WORD[p.status] ?? p.status ?? ""}`))
        .child(this.button(t, "close", "✕", () => closeOverlay(p.overlay))),
      div().id("speech-full").flex_1().overflow_y_scrollbar().text_size(13).text_color(t.foreground)
        .child(TextView.markdown("octopilot-speech-full", p.text ?? "").raw_html(false)),
    ]);
  }
}
