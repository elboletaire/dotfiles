// The messenger as an octopus: poses from the speech and kitchen state, and a bubble
// with the last message, the kitchen log and the pan count. Props: { fixture?, dir?, state_dir?, overlay? }.
// For the full-text dialog: { full: true, text, status, overlay }.

import { View, div, image } from "gpui-kit";
import { v_flex, h_flex, TextView } from "gpui-base";
import { exec, readTextFile, run, theme, props, shared, home, window, openOverlay, closeOverlay, checking } from "herdr";
import { clip } from "./clip.js";

const OCTO_W = 125;
const OCTO_H = 150;
const BUBBLE_W = 250;
const FAST_MS = 2000;
const SLOW_MS = 10000;
const TALK_MS = 4000;
const DOZE_S = 600;
const LOG_LINES = 4;

const WORD = { working: "working", blocked: "needs you", idle: "idle", done: "finished", offline: "offline", paused: "paused" };
const DOT = { working: "working", blocked: "blocked", idle: "idle", done: "done", offline: "unknown", paused: "idle" };
// Kitchen moods (scene.ts) that show a pose for a while; the rest of the moods come from status.
const MOOD_POSE = { happy: "happy", serve: "happy", worried: "worried", sad: "sad", surprised: "surprised", flip: "working", pour: "working", sleep: "sleeping" };
// How long each event's mood shows, from feed.ts: by event kind, else by mood for a report.
const KIND_MS = { tick: 2500, spawn: 2500, sent: 1500, request: 2000, cleanup: 3500, merged: 3500, pause: 2000, resume: 1500, round: 2000, reviewed: 2000, capped: 2500, feedback: 1500, reboot: 2000, decline: 1500, untrack: 1500, detach: 1500, track: 2000 };
const MOOD_MS = { happy: 4000, worried: 3000, sad: 4500, surprised: 2000, serve: 3500, flip: 2000, pour: 2500, sleep: 2000 };
// Poses whose second frame fades in and out over the first: [frame names, cycle ms].
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

const artPath = (name) => `mods/octopilot-octopus/art/png/${name}-320.png`;

// The art in mods/octopilot-octopus/art/png, 320 px tall, shown at OCTO_H.
function art(name) {
  return image(artPath(name)).w(OCTO_W).h(OCTO_H).flex_none();
}

// The first frame stays put; the second fades in and out over it, natively.
function flip([first, second], period) {
  return div().relative().flex_none().w(OCTO_W).h(OCTO_H).children([
    image(artPath(first)).w(OCTO_W).h(OCTO_H),
    image(artPath(second)).absolute().top(0).left(0).w(OCTO_W).h(OCTO_H)
      .loop("opacity", { from: 0, to: 1, period }),
  ]);
}

const pad = (n) => String(n).padStart(2, "0");
const clock = (at) => {
  const d = new Date(at * 1000);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

const eventMs = (ev) => KIND_MS[ev.kind] ?? MOOD_MS[ev.mood] ?? 0;

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
    this.sig = null;
    this.shownMood = null;
    if (checking() || props()?.full) return;
    this.watch(cx);
    this.sighs(cx);
  }

  // Polls the messenger and the kitchen: fast while the window shows, slow while hidden.
  // Redraws only when something shown changed, and once when a kitchen mood ends.
  watch(cx) {
    cx.spawn(async (cx) => {
      for (;;) {
        await this.poll(cx);
        const sig = this.signature();
        const mood = this.activeMood();
        if (sig !== this.sig || (this.shownMood && !mood)) cx.notify();
        this.sig = sig;
        this.shownMood = mood;
        await cx.sleep(window()?.visible === false ? SLOW_MS : FAST_MS);
      }
    });
  }

  signature() {
    const h = this.view?.header;
    return [this.seq, this.pose(), this.data?.status, this.data?.paused, this.error, this.newest()?.at,
      h?.active, h?.max_active, h?.paused].join("|");
  }

  // An occasional sigh: the second idle frame for a moment, only while idle and shown.
  sighs(cx) {
    cx.spawn(async (cx) => {
      for (;;) {
        await cx.sleep(7000 + Math.random() * 5000);
        if (window()?.visible === false || this.pose() !== "idle") continue;
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

  // The pose of the newest kitchen event, while its time is not up.
  activeMood() {
    const ev = this.newest();
    if (!ev || !MOOD_POSE[ev.mood]) return null;
    return Date.now() / 1000 - ev.at < eventMs(ev) / 1000 ? MOOD_POSE[ev.mood] : null;
  }

  pose() {
    if (this.error || this.data?.status === "offline") return "offline";
    if (!this.data) return "idle";
    if (this.talking) return "talking";
    if (this.data.status === "blocked") return "blocked";
    if (this.data.paused || this.view?.header?.paused) return "sleeping";
    const mood = this.activeMood();
    if (mood) return mood;
    if (this.data.status === "working") return "working";
    const ev = this.newest();
    if (ev && Date.now() / 1000 - ev.at > DOZE_S) return "doze";
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
    if (!d.text) return muted(d.status === "offline" ? "The messenger is offline." : "The messenger hasn't said anything yet.");
    return div().text_size(13).text_color(t.foreground)
      .child(TextView.markdown("octopilot-speech", clip(d.text)).raw_html(false));
  }

  // The last kitchen lines: older ones dim, the newest green (good), red (bad) or plain.
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
                p.overlay ? this.button(t, "close", "✕", () => closeOverlay(p.overlay)) : null,
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
      h_flex().justify_between().items_center().flex_none().children([
        div().text_size(13).font_semibold().text_color(t.foreground)
          .child(`Messenger · ${WORD[p.status] ?? p.status ?? ""}`),
        p.overlay ? this.button(t, "close", "✕", () => closeOverlay(p.overlay)) : null,
      ].filter(Boolean)),
      div().id("speech-full").flex_1().overflow_y_scrollbar().text_size(13).text_color(t.foreground)
        .child(TextView.markdown("octopilot-speech-full", p.text ?? "").raw_html(false)),
    ]);
  }
}
