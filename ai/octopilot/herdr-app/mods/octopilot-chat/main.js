// An octopilot agent as a chat: its messages, a composer that types into it, and the answers
// to a prompt it waits on. Reads `scan.sh chat --json`, writes through `chat-send` and `chat-keys`.
// Props (agent, title, subject, chips): see herdr/README.md; `dir` and `fixture` are for tests.
import { View, div } from "gpui-kit";
import { v_flex, h_flex, ScrollHandle, TextareaState, Textarea, TextView } from "gpui-base";
import { exec, readTextFile, run, props, shared, home, window, theme, nextCommand, checking, panes, spaces, focused } from "herdr";

const SPIN = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const WORDS = { working: "working", blocked: "needs you", idle: "idle", done: "finished", offline: "offline" };
// Fill the composer; the person decides when to send.
const CHIPS = [
  { label: "status", text: "status" },
  { label: "pause", text: "pause" },
  { label: "resume", text: "resume" },
  { label: "go #", text: "go " },
  { label: "investigate…", text: "investigate " },
];
// Polls: a second while the agent works or waits on you, three seconds otherwise.
const LIVE_MS = 1000;
const IDLE_MS = 3000;
// A pending bubble the transcript never confirms is dropped after this, once idle.
const PENDING_MS = 15000;
// After an answer, the buttons stay off until the prompt changes, or this long.
const ANSWER_MS = 5000;
const MAX_MESSAGES = 200;
// How close to the end still counts as "at the bottom", in px.
const BOTTOM_SLACK = 1;

// scan.sh under the hc backend, with the dashboard's folder and state dir, set by env(1)
// (exec() has no env option). The agent prop goes right after the verb, where scan.sh reads it.
// -> [command, argv]
function scanCall(args) {
  const dir = props()?.dir || shared("octopilot.dir") || `${home()}/.dotfiles/ai/octopilot`;
  const stateDir = props()?.state_dir || shared("octopilot.state_dir");
  const agent = props()?.agent;
  const env = ["OCTOPILOT_BACKEND=hc", `OCTOPILOT_DIR=${dir}`];
  if (stateDir) env.push(`OCTOPILOT_STATE_DIR=${stateDir}`);
  const argv = agent ? [args[0], "--agent", agent, ...args.slice(1)] : args;
  return ["env", [...env, `${dir}/scan.sh`, ...argv]];
}

// The character a keypress types, or null: chords with ctrl, alt or cmd type nothing here.
function typedChar(e) {
  const m = e.modifiers ?? {};
  const ch = e.key_char;
  if (m.control || m.alt || m.platform || !ch || ch.length !== 1 || ch < " " || ch === "\x7f") return null;
  return ch;
}

// The only pane of a mod in the window, else null (several copies cannot be told apart).
function soloPane(all, mod) {
  const mine = all.filter((p) => p.mod === mod);
  return mine.length === 1 ? mine[0] : null;
}

// The id of the shown tab, from spaces().
function shownTab(all) {
  return all.find((s) => s.active)?.tabs.find((t) => t.active)?.id ?? null;
}

// Whether a pane may take the keyboard: nothing has it, or no terminal and no other pane does.
function keyboardFree(f, pane) {
  return !f || (f.terminal == null && (f.pane == null || f.pane === pane));
}

// Sentence start: "the prompter" -> "The prompter".
function sentence(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// HH:MM of an ISO time, in the local zone.
function clock(at) {
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return "";
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export default class Chat extends View {
  init(_props, cx) {
    this.title = props()?.title || "Prompter";
    this.subject = props()?.subject || "the prompter";
    this.chips = (props()?.chips ?? CHIPS).map((c) => (typeof c === "string" ? { label: c, text: c } : c));
    this.scroll = ScrollHandle.new();
    this.handle = cx.focus_handle();
    this.input = TextareaState.new({ placeholder: `Ask ${this.subject}, or type a command` });
    this.input.set_auto_grow(1, 6);
    this.input.on("change", (_e, cx) => {
      const has = this.input.value().trim() !== "";
      if (has !== this.hasText) { this.hasText = has; cx.notify(); }
    });
    this.input.on("submit", (e, cx) => { if (!e.shift) cx.spawn(async (cx) => this.send(cx)); });
    this.input.on("focus", (_e, cx) => { this.focused = true; cx.notify(); });
    this.input.on("blur", (_e, cx) => { this.focused = false; cx.notify(); });
    this.hasText = false;
    this.focused = false;
    this.confirming = false;
    this.answering = false;
    this.answeredMsg = null;
    this.answeredAt = 0;
    this.needFull = false;
    this.terminal = null;
    this.status = null;
    this.blocked = null;
    this.error = null;
    this.notice = null;
    this.messages = [];
    this.index = new Map();
    this.rev = 0;
    this.pending = [];
    this.expanded = new Set();
    this.unseen = 0;
    this.scrollEnd = true;
    this.following = true;     // the reader is at the end: see log
    this.reading = false;
    this.last = 0;
    this.focusWanted = false;  // the composer should take the keyboard once the agent is online
    this.tabShown = null;      // whether this pane's tab was the shown one on the last tick: see followTab
    // `herdr-app check` runs init for real: no scan.sh, timers or key waits there.
    if (checking()) return;
    cx.spawn(async (cx) => this.sync(cx, true));
    cx.timer.every(1000, (cx) => this.tick(cx));
    cx.spawn(async (cx) => {
      for (;;) {
        const command = await nextCommand();
        if (command === "focus") this.focusComposer();
        cx.notify();
      }
    });
  }

  online() {
    return this.status !== null && this.status !== "offline";
  }

  live() {
    return this.status === "working" || this.status === "blocked";
  }

  // The composer takes the keyboard; while the agent is offline (no composer shown), the list does,
  // and the composer follows once it is online.
  focusComposer() {
    this.focusWanted = !this.online();
    if (this.online()) this.input.focus();
    else this.handle.focus();
  }

  // This copy's pane: the one open-gui.sh named for it (props.pane_name), else the window's
  // only chat pane. Null when neither can be told.
  chatPane(all) {
    const name = props()?.pane_name ?? props()?.agent ?? "octopilot-prompter";
    return all.find((p) => p.mod === "octopilot-chat" && p.name === name) ?? soloPane(all, "octopilot-chat");
  }

  // On the clock tick: when this pane's tab becomes the shown one, the composer takes the
  // keyboard, once, unless a terminal or another pane of that tab has it. In a tab with the
  // dashboard (the OCTOPILOT tab) only the dashboard answers this; the chat there takes "focus".
  followTab() {
    const all = panes();
    const me = this.chatPane(all);
    const shown = me !== null && me.tab === shownTab(all);
    const was = this.tabShown;
    this.tabShown = shown;
    if (!shown || was === true) return;
    if (all.some((p) => p.mod === "octopilot-dashboard" && p.tab === me.tab)) return;
    if (!keyboardFree(focused(), me.pane)) return;
    if (this.online()) this.input.focus();
    else this.handle.focus();
  }

  tick(cx) {
    if (window()?.visible === false) return;
    this.followTab();
    // A pending "focus" lands on the composer only while this copy's tab is shown and the keyboard
    // is still free here; once the user has moved on, it is dropped.
    if (this.focusWanted) {
      const all = panes();
      const me = this.chatPane(all);
      const shown = me !== null && me.tab === shownTab(all);
      if (!shown || this.focused || !keyboardFree(focused(), me.pane)) this.focusWanted = false;
      else if (this.online()) {
        this.focusWanted = false;
        this.input.focus();
        cx.notify();
      }
    }
    if (this.answering && Date.now() - this.answeredAt > ANSWER_MS) {
      this.answering = false;
      cx.notify();
    }
    if (this.pending.length && !this.live()) {
      const cut = Date.now() - PENDING_MS;
      const kept = this.pending.filter((p) => Date.parse(p.at) > cut);
      if (kept.length !== this.pending.length) {
        this.pending = kept;
        cx.notify();
      }
    }
    if (this.reading) return;
    if (Date.now() - this.last < (this.live() ? LIVE_MS : IDLE_MS)) return;
    cx.spawn(async (cx) => this.sync(cx, false));
  }

  // The chat --json shape: from the fixture when a test gives one, else from scan.sh.
  async chat(args) {
    const fixture = props()?.fixture;
    if (fixture) {
      const text = await readTextFile(fixture);
      return JSON.parse(text ?? "null");
    }
    const [cmd, argv] = scanCall(["chat", "--json", ...args]);
    const r = await exec(cmd, argv, { timeout: 20000 });
    if (r.code !== 0) throw new Error(r.stderr.trim() || `scan.sh chat exited ${r.code}`);
    return JSON.parse(r.stdout);
  }

  fingerprint() {
    return JSON.stringify([this.status, this.blocked, this.terminal, this.error, this.notice, this.confirming,
      this.answering, this.unseen, this.messages.length, this.pending.length, this.rev]);
  }

  // Reads the messages after the newest one we have; a full read takes the newest 100.
  async sync(cx, full) {
    if (this.reading) return;
    this.reading = true;
    const before = this.fingerprint();
    const wantFull = full || (this.needFull && !this.live());
    try {
      const last = this.messages[this.messages.length - 1]?.id;
      const args = wantFull || !last ? ["--limit", "100"] : ["--after", last];
      this.absorb(await this.chat(args), wantFull);
      this.error = null;
      if (wantFull && !this.live()) this.needFull = false;
    } catch (e) {
      this.error = String(e?.message ?? e);
      this.status = "offline";
    } finally {
      this.reading = false;
      this.last = Date.now();
    }
    if (before !== this.fingerprint()) cx.notify();
  }

  absorb(data, full) {
    this.terminal = data?.terminal ?? null;
    this.status = data?.status ?? "offline";
    this.blocked = data?.blocked ?? null;
    if (this.answering && (!this.blocked || this.blocked.msg !== this.answeredMsg)) this.answering = false;
    if (full || data?.reset) {
      this.messages = [];
      this.index = new Map();
      this.pending = [];
      // A fresh transcript lands at its end, wherever the reader had scrolled.
      this.scrollEnd = true;
      this.following = true;
    }
    const atBottom = this.atBottom();
    let added = 0;
    for (const m of data?.messages ?? []) {
      const i = this.index.get(m.id);
      if (i !== undefined) {
        // A turn still in progress keeps its id while its text grows.
        const old = this.messages[i];
        if (old.text !== m.text || JSON.stringify(old.tools) !== JSON.stringify(m.tools)) {
          this.messages[i] = m;
          this.rev += 1;
        }
        continue;
      }
      this.index.set(m.id, this.messages.length);
      this.messages.push(m);
      added += 1;
      // The transcript's copy of our message replaces the pending bubble: same text, or a later user message.
      if (m.role !== "user") continue;
      const at = Date.parse(m.at);
      this.pending = this.pending.filter((p) => p.text !== m.text.trim() && !(at >= Date.parse(p.at)));
    }
    if (this.messages.length > MAX_MESSAGES) {
      this.messages.splice(0, this.messages.length - MAX_MESSAGES);
      this.index = new Map(this.messages.map((m, i) => [m.id, i]));
    }
    if (!added) return;
    this.rev += 1;
    if (atBottom) {
      this.scrollEnd = true;
      this.following = true;
      this.unseen = 0;
    } else {
      this.unseen += added;
    }
  }

  atBottom() {
    const o = this.scroll.offset();
    const v = this.scroll.viewport_size();
    const c = this.scroll.content_size();
    return o.y + v.height >= c.height - BOTTOM_SLACK;
  }

  // Runs a scan.sh action: { code, error }. In fixture mode nothing is sent.
  async say(args) {
    if (props()?.fixture) return { code: -1, error: "Fixture mode: nothing was sent." };
    try {
      const [cmd, argv] = scanCall(args);
      const r = await exec(cmd, argv, { timeout: 20000 });
      let error = r.stderr.trim();
      if (!error) try { error = JSON.parse(r.stdout)?.error ?? ""; } catch {}
      return { code: r.code, error };
    } catch (e) {
      return { code: -1, error: String(e?.message ?? e) };
    }
  }

  // What a chat-send or clear exit means, as a notice; null when it went through.
  sendNotice(r) {
    if (r.code === 0) return null;
    if (r.code === 4) return `${sentence(this.subject)} is waiting on a prompt. Answer it first.`;
    if (r.code === 3) return `${sentence(this.subject)} isn't running.`;
    return r.error || `scan.sh exited ${r.code}`;
  }

  async send(cx) {
    const text = this.input.value().trim();
    if (!text || !this.online()) return;
    if (this.blocked) {
      this.notice = `${sentence(this.subject)} is waiting on a prompt. Answer it first.`;
      cx.notify();
      return;
    }
    this.input.set_value("");
    const bubble = { id: `pending-${Date.now()}`, role: "user", text, at: new Date().toISOString(), tools: [], pending: true };
    this.pending.push(bubble);
    this.scrollEnd = true;
    this.following = true;
    this.notice = null;
    cx.notify();
    const err = this.sendNotice(await this.say(["chat-send", text]));
    if (err) {
      this.pending = this.pending.filter((p) => p !== bubble);
      if (!this.input.value()) this.input.set_value(text);
      this.notice = err;
      cx.notify();
      return;
    }
    await this.sync(cx, false);
  }

  async answer(cx, keys) {
    if (this.answering || !this.blocked) return;
    this.answering = true;
    this.answeredMsg = this.blocked.msg;
    this.answeredAt = Date.now();
    this.notice = null;
    cx.notify();
    const r = await this.say(["chat-keys", ...keys]);
    // Exit 4: the prompt is no longer waiting, so it was answered already.
    if (r.code === 4) this.answering = false;
    else if (r.code !== 0) {
      this.answering = false;
      this.notice = this.sendNotice(r);
    }
    await this.sync(cx, false);
    cx.notify();
  }

  async clear(cx) {
    this.confirming = false;
    this.needFull = true;
    this.notice = this.sendNotice(await this.say(["chat-send", "/clear"]));
    cx.notify();
    await this.sync(cx, true);
  }

  fill(text) {
    this.input.set_value(text);
    this.input.set_selected_range({ start: text.length, end: text.length });
    this.input.focus();
  }

  // Keys reach here from the list and, bubbling up, from the composer.
  key(e, cx) {
    const m = e.modifiers ?? {};
    if (e.keystroke === "ctrl-l") {
      if (!this.online()) return;
      this.confirming = true;
    } else if (e.key === "escape") {
      if (this.confirming) this.confirming = false;
      else { this.input.blur(); this.handle.focus(); }
    } else if (e.key === "tab") {
      // Tab takes the list to the composer; Shift+Tab brings it back. In the composer Tab is left alone.
      if (!this.focused) {
        if (m.shift || !this.online()) return;
        this.input.focus();
      } else if (m.shift) {
        this.handle.focus();
      } else {
        return;
      }
    } else if (!this.focused && this.online() && typedChar(e)) {
      // A letter typed while the list has the keyboard goes to the composer.
      this.fill(this.input.value() + typedChar(e));
    } else {
      return;
    }
    cx.stop_propagation();
    cx.notify();
  }

  button(t, id, label, onClick, primary = false, disabled = false) {
    return h_flex()
      .id(id)
      .h(26)
      .px(10)
      .items_center()
      .rounded(7)
      .border_1()
      .border_color(primary ? t.solid : t.input)
      .bg(primary ? t.solid : t.raised)
      .text_size(12)
      .text_color(primary ? t.solid_foreground : t.foreground)
      .when(disabled, (el) => el.opacity(0.45))
      .when(!disabled, (el) => el.cursor_pointer().hover((s) => s.opacity(0.88)).on_click(onClick))
      .child(label);
  }

  // A header control: no box until hovered.
  ghost(t, id, label, onClick) {
    return h_flex()
      .id(id)
      .h(26)
      .px(9)
      .items_center()
      .rounded(7)
      .text_size(12)
      .text_color(t.muted)
      .cursor_pointer()
      .hover((s) => s.bg(t.hover).text_color(t.foreground))
      .on_click(onClick)
      .child(label);
  }

  header(t) {
    const st = this.status ?? "offline";
    const color = t[st] ?? t.dim;
    return h_flex()
      .h(48)
      .flex_none()
      .px(14)
      .gap(10)
      .items_center()
      .bg(t.chrome)
      .border_b(1)
      .border_color(t.border)
      .child(div().size(8).flex_none().rounded_full().bg(color))
      .child(v_flex()
        .gap(1)
        .child(div().font_semibold().text_size(14).child(this.title))
        .child(h_flex()
          .gap(6)
          .items_center()
          .text_size(11.5)
          .text_color(color)
          .when(st === "working", (el) => el.child(div().w(10).frames(SPIN, 90).child(SPIN[0])))
          .child(WORDS[st] ?? st)))
      .child(div().flex_1())
      .when(this.online() && this.terminal, (el) => el.child(this.ghost(t, "chat-peek", "Terminal", () => run("terminal.peek", { terminal: this.terminal }))))
      .when(this.online(), (el) => el.child(this.ghost(t, "chat-clear", "Clear", (_e, cx) => {
        this.confirming = true;
        cx.notify();
      })));
  }

  // The prompt the prompter is waiting on, with the answers it takes.
  banner(t) {
    const b = this.blocked;
    const quick = b.kind === "permission" || b.kind === "question";
    const title = b.kind === "question" ? "Question" : b.kind === "auth" ? "Sign in" : "Permission";
    const answers = b.kind === "question"
      ? [["Option 1", ["1"], true], ["Option 2", ["2"]], ["Cancel (esc)", ["esc"]]]
      : [["Allow (1)", ["1"], true], ["Allow always (2)", ["2"]], ["Deny (esc)", ["esc"]]];
    return v_flex()
      .flex_none()
      .mx(14)
      .mt(12)
      .p(12)
      .gap(10)
      .rounded(12)
      .bg(t.blocked + "1a")
      .border_1()
      .border_color(t.blocked + "66")
      .child(div().text_size(11.5).font_semibold().text_color(t.blocked).child(title))
      .child(TextView.markdown("chat-blocked", b.msg ?? "").raw_html(false).selectable(true).text_size(12.5))
      .when(quick, (el) => el.child(h_flex()
        .gap(6)
        .flex_wrap()
        .children(answers.map(([label, keys, primary], i) => this.button(t, `chat-answer-${i}`, label,
          (_e, cx) => cx.spawn(async (cx) => this.answer(cx, keys)), primary, this.answering)))))
      .when(Boolean(this.terminal), (el) => el.child(h_flex()
        .child(div().flex_1())
        .child(this.ghost(t, "chat-open", "Open terminal", () => run("terminal.peek", { terminal: this.terminal })))));
  }

  // Tool calls of one message: the first one, "+n" for the rest, all of them when expanded.
  tools(t, m) {
    const open = this.expanded.has(m.id);
    const list = open ? m.tools : [m.tools[0]];
    const more = m.tools.length - 1;
    return v_flex()
      .id(`tools-${m.id}`)
      .gap(4)
      .cursor_pointer()
      .on_click((_e, cx) => {
        if (this.expanded.has(m.id)) this.expanded.delete(m.id);
        else this.expanded.add(m.id);
        cx.notify();
      })
      .children(list.map((name) => div()
        .px(8)
        .py(2)
        .rounded(6)
        .bg(t.raised)
        .border_1()
        .border_color(t.border)
        .text_size(11.5)
        .text_color(t.muted)
        .child(`🔧 ${name}`)))
      .when(!open && more > 0, (el) => el.child(div().px(4).text_size(11).text_color(t.dim).child(`+${more} more`)));
  }

  bubble(t, m) {
    const me = m.role === "user";
    const card = v_flex()
      .max_w("86%")
      .px(12)
      .py(8)
      .rounded(14)
      .when(me, (el) => el.bg(t.accent).text_color(t.accent_foreground))
      .when(!me, (el) => el.bg(t.surface).border_1().border_color(t.border).text_color(t.foreground));
    if (me) card.child(div().whitespace_normal().text_size(13).text_color(t.accent_foreground).child(m.text));
    else if (m.text) card.child(TextView.markdown(`md-${m.id}`, m.text).raw_html(false).selectable(true).text_size(13));
    const shell = v_flex()
      .id(`m-${m.id}`)
      .w_full()
      .gap(4)
      .when(me, (el) => el.items_end())
      .when(!me, (el) => el.items_start());
    // A turn that only ran tools has no text: show its chips without an empty card.
    if (me || m.text) shell.child(card);
    if (m.tools?.length) shell.child(this.tools(t, m));
    shell.child(div().px(4).text_size(10.5).text_color(t.dim).child(m.pending ? "sending…" : clock(m.at)));
    return shell;
  }

  typing(t) {
    return h_flex().id("typing").w_full().items_start().child(div()
      .px(12)
      .py(9)
      .rounded(14)
      .bg(t.surface)
      .border_1()
      .border_color(t.border)
      .text_color(t.dim)
      .child(div().frames(["•  ", "••  ", "•••", " ••", "  •"], 220).child("•  ")));
  }

  log(t) {
    const items = [
      ...this.messages.map((m) => this.bubble(t, m)),
      ...this.pending.map((m) => this.bubble(t, m)),
      ...(this.status === "working" ? [this.typing(t)] : []),
      // The last child is the scroll target: it keeps the bottom padding in view.
      div().h(8).flex_none(),
    ];
    // The request runs after this frame's layout, so a reader who follows the end gets it on every
    // frame: a message that grows after the request is brought in by the next one.
    if (this.scrollEnd || this.following) {
      this.scroll.scroll_to_item(items.length - 1);
      this.scrollEnd = false;
    }
    return v_flex()
      .id("chat-log")
      .flex_1()
      .min_h(0)
      .px(14)
      .pt(12)
      .gap(12)
      .overflow_y_scrollbar()
      .track_scroll(this.scroll)
      .on_scroll_wheel((_e, cx) => cx.timer.after(60, (cx) => {
        const was = this.unseen;
        // Only a wheel scroll that lands decides whether the transcript follows its end.
        this.following = this.atBottom();
        if (this.following) this.unseen = 0;
        if (was > 0 && this.unseen === 0) cx.notify();
      }))
      .children(items);
  }

  pill(t) {
    return h_flex()
      .absolute()
      .bottom(10)
      .left_0()
      .right_0()
      .justify_center()
      .child(h_flex()
        .id("chat-new")
        .h(28)
        .px(12)
        .items_center()
        .rounded_full()
        .bg(t.popover)
        .border_1()
        .border_color(t.input)
        .shadow_md()
        .text_size(12)
        .text_color(t.foreground)
        .cursor_pointer()
        .hover((s) => s.bg(t.hover))
        .on_click((_e, cx) => {
          this.scrollEnd = true;
          this.following = true;
          this.unseen = 0;
          cx.notify();
        })
        .child(`↓ ${this.unseen === 1 ? "1 new message" : `${this.unseen} new messages`}`));
  }

  // The notice, or the clear confirmation, above the composer.
  notes(t) {
    if (this.confirming) {
      return h_flex()
        .mx(14)
        .mb(8)
        .p(10)
        .gap(8)
        .rounded(10)
        .items_center()
        .bg(t.surface)
        .border_1()
        .border_color(t.border)
        .child(div().flex_1().text_size(12).text_color(t.muted).child(`Clear this conversation? This sends /clear to ${this.subject}.`))
        .child(this.button(t, "chat-clear-no", "Cancel", (_e, cx) => {
          this.confirming = false;
          cx.notify();
        }))
        .child(this.button(t, "chat-clear-yes", "Clear", (_e, cx) => cx.spawn(async (cx) => this.clear(cx)), true));
    }
    const msg = this.error ? `Can't reach ${this.subject}: ${this.error}` : this.notice;
    if (!msg) return null;
    return div()
      .mx(14)
      .mb(8)
      .px(10)
      .py(6)
      .rounded(8)
      .bg(t.blocked + "1a")
      .text_size(12)
      .text_color(t.blocked)
      .child(msg);
  }

  composer(t) {
    if (!this.online()) {
      return v_flex()
        .flex_none()
        .border_t(1)
        .border_color(t.border)
        .bg(t.chrome)
        .px(14)
        .py(12)
        .child(div()
          .px(12)
          .py(10)
          .rounded(12)
          .bg(t.surface)
          .text_size(12.5)
          .text_color(t.muted)
          .child(this.status === null ? `Connecting to ${this.subject}…` : `${sentence(this.subject)} is offline -- start it to chat.`));
    }
    return v_flex()
      .flex_none()
      .border_t(1)
      .border_color(t.border)
      .bg(t.chrome)
      .pt(8)
      .child(h_flex()
        .flex_wrap()
        .gap(6)
        .px(14)
        .pb(8)
        .children(this.chips.map((c, i) => h_flex()
          .id(`chip-${i}`)
          .h(24)
          .px(10)
          .items_center()
          .rounded_full()
          .border_1()
          .border_color(t.input)
          .text_size(11.5)
          .text_color(t.muted)
          .cursor_pointer()
          .hover((s) => s.bg(t.hover).text_color(t.foreground))
          .on_click(() => this.fill(c.text))
          .child(c.label))))
      .child(v_flex()
        .mx(14)
        .mb(14)
        .p(10)
        .gap(8)
        .rounded(14)
        .bg(t.popover)
        .border_1()
        .border_color(this.focused ? t.accent : t.input)
        .child(Textarea.new(this.input).w_full().text_size(13).text_color(t.foreground))
        .child(h_flex()
          .items_center()
          .gap(8)
          .child(div().flex_1().text_size(11).text_color(t.dim).child("Enter sends · Shift+Enter new line · Esc leaves"))
          .child(h_flex()
            .id("chat-send")
            .h(28)
            .px(12)
            .items_center()
            .rounded(8)
            .bg(this.hasText ? t.solid : t.raised)
            .text_size(12.5)
            .font_medium()
            .text_color(this.hasText ? t.solid_foreground : t.dim)
            .cursor_pointer()
            .hover((s) => s.opacity(0.88))
            .on_click((_e, cx) => cx.spawn(async (cx) => this.send(cx)))
            .child("Send"))));
  }

  render(cx) {
    const t = theme();
    const notes = this.notes(t);
    return v_flex()
      .id("chat")
      .track_focus(this.handle)
      .on_key_down((e, cx) => this.key(e, cx))
      .size_full()
      .min_h(0)
      .bg(t.background)
      .text_color(t.foreground)
      .text_size(13)
      .child(this.header(t))
      .when(Boolean(this.blocked), (el) => el.child(this.banner(t)))
      .child(v_flex()
        .flex_1()
        .min_h(0)
        .relative()
        .child(this.log(t))
        .when(this.unseen > 0, (el) => el.child(this.pill(t))))
      .children(notes ? [notes] : [])
      .child(this.composer(t));
  }
}
