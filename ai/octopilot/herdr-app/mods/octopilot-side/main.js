// The code agent's side panel beside its claude terminal: status, sub-agents, model, commands.
// Sends go through `scan.sh chat-send --agent <agent>`, one at a time, never into a prompt or
// an open /resume picker. Props: dir, state_dir, agent, title (see herdr/README.md).
import { View, div } from "gpui-kit";
import { v_flex, h_flex } from "gpui-base";
import { exec, hc, run, props, shared, home, theme, terminals, nextCommand, window, checking } from "herdr";

const MODELS = ["opus", "sonnet", "haiku"];
const WORDS = { working: "working", blocked: "needs you", idle: "idle", done: "finished", offline: "offline" };
// Polls: the status every second (herdr's terminals() is live), Claude's own sub-agents every 3 s.
const RECORDS_MS = 3000;
// The buttons wait this long after a send, so a double click sends once.
const LOCK_MS = 1500;
// A notice goes after this long, or sooner when the agent's status changes.
const NOTICE_MS = 8000;

// scan.sh under the hc backend, with the dashboard's folder and state dir, set by env(1).
// The agent prop goes right after the verb, where scan.sh reads it. -> [command, argv]
function scanCall(args) {
  const dir = props()?.dir || shared("octopilot.dir") || `${home()}/.dotfiles/ai/octopilot`;
  const stateDir = props()?.state_dir || shared("octopilot.state_dir");
  const agent = props()?.agent;
  const env = ["OCTOPILOT_BACKEND=hc", `OCTOPILOT_DIR=${dir}`];
  if (stateDir) env.push(`OCTOPILOT_STATE_DIR=${stateDir}`);
  const argv = agent ? [args[0], "--agent", agent, ...args.slice(1)] : args;
  return ["env", [...env, `${dir}/scan.sh`, ...argv]];
}

// The agent's terminal: labelled with its name and this checkout's dir, if any.
function agentTerminal(agent, dir) {
  return terminals().find((t) => t.labels?.["octopilot.agent"] === agent
    && (!dir || t.labels?.["octopilot.dir"] === dir)) ?? null;
}

export default class Side extends View {
  init(_props, cx) {
    this.title = props()?.title || "Code changes";
    this.handle = cx.focus_handle();
    this.agent = null;      // the agent's terminal, null when offline
    this.subs = [];         // its sub-agents: herdr's terminals whose parent it is
    this.records = [];      // Claude's own sub-agents (hc get's records), read-only
    this.recordsAt = 0;
    this.reading = false;
    this.sending = false;
    this.lockedUntil = 0;
    this.notice = null;
    this.noticeAt = 0;
    this.noticeStatus = null;
    this.picker = null;     // after /resume: the agent's status and title then; sends wait until they change
    this.confirming = false;
    this.fp = "";
    // `herdr-app check` runs init for real: no scan.sh, timers or key waits there.
    if (checking()) return;
    cx.spawn(async (cx) => this.tick(cx));
    cx.timer.every(1000, (cx) => this.tick(cx));
    cx.spawn(async (cx) => {
      for (;;) {
        const command = await nextCommand();
        if (command === "focus") this.handle.focus();
        cx.notify();
      }
    });
  }

  online() {
    return this.agent !== null;
  }

  blocked() {
    return this.agent?.status === "blocked";
  }

  busy() {
    return this.sending || Date.now() < this.lockedUntil;
  }

  canSend() {
    return this.online() && !this.blocked() && !this.busy() && !this.picker;
  }

  setNotice(text) {
    this.notice = text;
    this.noticeAt = Date.now();
    this.noticeStatus = this.agent?.status ?? null;
  }

  tick(cx) {
    if (window()?.visible === false) return;
    const agent = agentTerminal(props()?.agent ?? "octopilot-code", props()?.dir || null);
    this.agent = agent;
    this.subs = agent ? terminals().filter((t) => t.parent === agent.address) : [];
    if (this.picker && (!agent || agent.status !== this.picker.status || agent.title !== this.picker.title)) {
      this.picker = null;
    }
    if (this.notice && (Date.now() - this.noticeAt > NOTICE_MS || (agent?.status ?? null) !== this.noticeStatus)) {
      this.notice = null;
    }
    if (!agent) {
      this.records = [];
      this.confirming = false;
    } else if (!this.reading && Date.now() - this.recordsAt >= RECORDS_MS) {
      cx.spawn(async (cx) => this.readRecords(cx, agent.address));
    }
    const fp = this.fingerprint();
    if (fp !== this.fp) {
      this.fp = fp;
      cx.notify();
    }
  }

  fingerprint() {
    return JSON.stringify([
      this.agent?.address, this.agent?.status, this.agent?.title,
      this.subs.map((s) => [s.address, s.status, s.title, s.name]),
      this.records, this.notice, this.confirming, this.sending, this.busy(), this.picker,
    ]);
  }

  // Claude's own sub-agents of the agent's claude: the records of its hc get.
  async readRecords(cx, address) {
    this.reading = true;
    this.recordsAt = Date.now();
    try {
      const r = await hc(["get", address, "--json"]);
      const records = r.code === 0 ? JSON.parse(r.stdout)?.records ?? {} : {};
      this.records = Object.entries(records).map(([id, rec]) => ({ id, title: rec?.title || id, state: rec?.state ?? "" }));
    } catch {
      this.records = [];
    } finally {
      this.reading = false;
    }
    cx.notify();
  }

  // scan.sh's result: { code, error }. Exit 4 is a prompt waiting, 3 an agent not running.
  async say(args) {
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

  sendNotice(r) {
    if (r.code === 4) return "The agent is waiting on a prompt. Answer it in its terminal.";
    if (r.code === 3) return "The code changes agent isn't running.";
    return r.error || `scan.sh exited ${r.code}`;
  }

  // Sends one command to the agent: the buttons wait for it, then for a short lock. `done`
  // runs once it went through.
  act(cx, args, done = null) {
    if (!this.canSend()) return;
    this.sending = true;
    this.notice = null;
    cx.notify();
    cx.spawn(async (cx) => {
      const r = await this.say(args);
      this.sending = false;
      this.lockedUntil = Date.now() + LOCK_MS;
      cx.timer.after(LOCK_MS, (cx) => cx.notify());
      if (r.code === 0) done?.();
      else this.setNotice(this.sendNotice(r));
      cx.notify();
    });
  }

  // Focuses the agent's terminal, where a picker (/resume) is answered.
  focusTerminal() {
    if (this.agent) run("pane.focus", { terminal: this.agent.address });
  }

  button(t, id, label, onClick, { primary = false, disabled = false, flex = false } = {}) {
    return h_flex()
      .id(id)
      .h(26)
      .px(8)
      .items_center()
      .justify_center()
      .rounded(7)
      .border_1()
      .border_color(primary ? t.solid : t.input)
      .bg(primary ? t.solid : t.raised)
      .text_size(12)
      .text_color(primary ? t.solid_foreground : t.foreground)
      .when(flex, (el) => el.flex_1())
      .when(disabled, (el) => el.opacity(0.45))
      .when(!disabled, (el) => el.cursor_pointer().hover((s) => s.opacity(0.88)).on_click(onClick))
      .child(label);
  }

  // A header control: no box until hovered.
  ghost(t, id, label, onClick) {
    return h_flex()
      .id(id)
      .h(24)
      .px(7)
      .items_center()
      .rounded(6)
      .text_size(11.5)
      .text_color(t.muted)
      .cursor_pointer()
      .hover((s) => s.bg(t.hover).text_color(t.foreground))
      .on_click(onClick)
      .child(label);
  }

  header(t) {
    const st = this.agent ? (this.agent.status ?? "idle") : "offline";
    const color = t[st] ?? t.dim;
    return h_flex()
      .h(44)
      .flex_none()
      .px(12)
      .gap(8)
      .items_center()
      .bg(t.chrome)
      .border_b(1)
      .border_color(t.border)
      .child(div().size(8).flex_none().rounded_full().bg(color))
      .child(v_flex()
        .flex_1()
        .min_w(0)
        .child(div().font_semibold().text_size(13).truncate().child(this.title))
        .child(div().text_size(11).text_color(color).child(WORDS[st] ?? st)))
      .when(this.online(), (el) => el.child(this.ghost(t, "side-focus", "Terminal", () => this.focusTerminal())));
  }

  // The prompt the agent waits on: answered in its terminal, which opens here.
  banner(t) {
    return v_flex()
      .flex_none()
      .mx(10)
      .mt(10)
      .p(10)
      .gap(8)
      .rounded(10)
      .bg(t.blocked + "1a")
      .border_1()
      .border_color(t.blocked + "66")
      .child(div().text_size(12).text_color(t.blocked).child("Waiting on a prompt. Answer it in the terminal."))
      .child(this.button(t, "side-open", "Open terminal", () => this.focusTerminal(), { primary: true }));
  }

  section(t, label, children) {
    return v_flex()
      .gap(6)
      .px(12)
      .py(10)
      .border_b(1)
      .border_color(t.border)
      .child(div().text_size(10.5).font_semibold().text_color(t.dim).child(label.toUpperCase()))
      .children(children);
  }

  // A sub-agent: a click peeks at it, its keep button gives it a tab.
  subRow(t, s) {
    const st = s.status ?? "idle";
    const label = s.title || s.name || s.address;
    return h_flex()
      .id(`sub-${s.address}`)
      .h(28)
      .px(6)
      .gap(6)
      .items_center()
      .rounded(7)
      .cursor_pointer()
      .hover((h) => h.bg(t.hover))
      .on_click(() => run("terminal.peek", { terminal: s.address }))
      .child(div().size(7).flex_none().rounded_full().bg(t[st] ?? t.dim))
      .child(div().flex_1().min_w(0).overflow_hidden().truncate().text_size(12).child(label))
      .child(div().text_size(10.5).text_color(t.muted).child(WORDS[st] ?? st))
      .child(h_flex()
        .id(`keep-${s.address}`)
        .h(22)
        .px(6)
        .items_center()
        .rounded(6)
        .border_1()
        .border_color(t.input)
        .text_size(10.5)
        .text_color(t.muted)
        .cursor_pointer()
        .hover((h) => h.bg(t.hover).text_color(t.foreground))
        .on_mouse_down("left", (_e, cx) => cx.stop_propagation())
        .on_click((_e, cx) => {
          cx.stop_propagation();
          run("terminal.keep", { terminal: s.address, place: "tab" });
        })
        .child("keep"));
  }

  // Claude's own sub-agents: listed, not peeked at (they have no terminal of their own).
  recordRow(t, r) {
    const color = t[r.state] ?? t.dim;
    return h_flex()
      .id(`rec-${r.id}`)
      .h(26)
      .px(6)
      .gap(6)
      .items_center()
      .child(div().size(7).flex_none().rounded_full().bg(color))
      .child(div().flex_1().min_w(0).overflow_hidden().truncate().text_size(12).text_color(t.muted).child(r.title))
      .child(div().text_size(10.5).text_color(t.dim).child(r.state));
  }

  subsSection(t) {
    const rows = [];
    if (this.subs.length) rows.push(...this.subs.map((s) => this.subRow(t, s)));
    else rows.push(div().text_size(11.5).text_color(t.dim).child("No sub-agents running."));
    if (this.records.length) {
      rows.push(div().mt(4).text_size(10.5).text_color(t.dim).child("Claude's own"));
      rows.push(...this.records.map((r) => this.recordRow(t, r)));
    }
    return this.section(t, `Subagents${this.subs.length ? ` · ${this.subs.length}` : ""}`, rows);
  }

  modelSection(t) {
    const enabled = this.canSend();
    return this.section(t, "Model", [h_flex()
      .gap(6)
      .children(MODELS.map((m) => this.button(t, `model-${m}`, m[0].toUpperCase() + m.slice(1),
        (_e, cx) => this.act(cx, ["chat-send", `/model ${m}`]), { flex: true, disabled: !enabled })))]);
  }

  commandsSection(t) {
    const enabled = this.canSend();
    const rows = [
      h_flex()
        .gap(6)
        .children([
          this.button(t, "cmd-compact", "/compact", (_e, cx) => this.act(cx, ["chat-send", "/compact"]),
            { flex: true, disabled: !enabled }),
          this.button(t, "cmd-clear", "/clear", (_e, cx) => {
            this.confirming = true;
            cx.notify();
          }, { flex: true, disabled: !enabled }),
        ]),
      this.button(t, "cmd-resume", "/resume", (_e, cx) => {
        // The picker is answered in the terminal: it comes up there, and every send waits
        // until the agent's status or title changes (or "Picker done"), so none types into it.
        const address = this.agent?.address;
        this.act(cx, ["chat-send", "/resume"], () => {
          this.picker = { status: this.agent?.status, title: this.agent?.title };
          run("pane.focus", { terminal: address });
        });
      }, { disabled: !enabled }),
    ];
    if (this.picker) {
      rows.push(h_flex()
        .gap(6)
        .items_center()
        .child(div().flex_1().text_size(11.5).text_color(t.muted).child("The /resume picker is open in the terminal."))
        .child(this.ghost(t, "picker-done", "Picker done", (_e, cx) => {
          this.picker = null;
          cx.notify();
        })));
    }
    if (this.confirming) {
      rows.push(v_flex()
        .gap(8)
        .p(10)
        .rounded(10)
        .bg(t.surface)
        .border_1()
        .border_color(t.border)
        .child(div().text_size(11.5).text_color(t.muted).child("Clear this conversation? This sends /clear."))
        .child(h_flex()
          .gap(6)
          .children([
            this.button(t, "clear-no", "Cancel", (_e, cx) => {
              this.confirming = false;
              cx.notify();
            }, { flex: true }),
            this.button(t, "clear-yes", "Clear", (_e, cx) => {
              this.confirming = false;
              this.act(cx, ["chat-send", "/clear"]);
            }, { flex: true, primary: true }),
          ])));
    }
    return this.section(t, "Commands", rows);
  }

  render(cx) {
    const t = theme();
    const notice = this.notice && this.online()
      ? div().mx(10).mt(8).px(8).py(6).rounded(8).bg(t.blocked + "1a").text_size(11.5).text_color(t.blocked).child(this.notice)
      : null;
    return v_flex()
      .id("side")
      .track_focus(this.handle)
      .size_full()
      .min_h(0)
      .bg(t.chrome)
      .text_color(t.foreground)
      .text_size(12.5)
      .border_l(1)
      .border_color(t.border)
      .child(this.header(t))
      .when(this.blocked(), (el) => el.child(this.banner(t)))
      .child(v_flex()
        .id("side-body")
        .flex_1()
        .min_h(0)
        .overflow_y_scrollbar()
        .when(!this.online(), (el) => el.child(div().p(12).text_size(12).text_color(t.muted)
          .child("The code changes agent is offline. Start Octopilot to see it here.")))
        .when(this.online(), (el) => el
          .child(this.subsSection(t))
          .child(this.modelSection(t))
          .child(this.commandsSection(t))))
      .children(notice ? [notice] : []);
  }
}
