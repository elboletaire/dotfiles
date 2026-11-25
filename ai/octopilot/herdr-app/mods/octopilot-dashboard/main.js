// The Octopilot dashboard: draws view.json and sends the actions it asks for.
// The backend decides what each row may do; dashboard.sh --action runs them.
// With props.dialog, the same mod is the kitchen alert or the investigate form.

import { View } from "gpui-kit";
import { v_flex, h_flex, ScrollHandle, InputState } from "gpui-base";
import {
  exec, readTextFile, watchFolder, nextCommand, checking, home, props, shared, run, layouts,
  openOverlay, closeOverlay, notify, theme, window, focused, panes, spaces,
} from "herdr";
import {
  CONFIRM_MS, FLASH_MS, KITCHEN_S, GLOBAL_KEYS, ROW_KEYS, arrange, resolveSel,
  entryOf, stepSel, jumpSel, keyName, actionKey, parseAnswer, slugOf, isRepoKey, viewError, isStale,
  ownPane, shownTab, keyboardFree,
} from "./model.js";
import {
  header, paused, column, pickPanel, activityPanel, notesRow, statusLine, actionBar,
  globalActions, emptyState,
} from "./parts.js";
import { kitchenDialog, investigateDialog } from "./dialogs.js";

const MOD = "octopilot-dashboard";
// The name open-gui.sh gives this pane (pane.rename), so it is found among the mod's panes.
const PANE_NAME = "octopilot-dashboard";
// The kitchen corner: the octopilot layout's floating kitchen block.
const KITCHEN_LAYOUT = "octopilot";
// view.json is also read on a timer, besides the folder watch, in case a watch is lost.
const POLL_MS = 2000;
// How long a peek this pane opened is watched for its close before giving up.
const PEEK_WATCH_MS = 10 * 60 * 1000;
const NAV = { j: 1, down: 1, k: -1, up: -1, pagedown: 10, pageup: -10 };

// dashboard.sh under the GUI's backend (hc) and this mod's state dir. herdr's exec()
// has no env option, so env(1) sets them; OCTOPILOT_STATE_DIR only when one was given,
// else dashboard.sh's own default (XDG) applies.
function dashboardArgv(dir, stateDir, argv) {
  const env = ["OCTOPILOT_BACKEND=hc", `OCTOPILOT_DIR=${dir}`];
  if (stateDir) env.push(`OCTOPILOT_STATE_DIR=${stateDir}`);
  return ["env", ...env, `${dir}/dashboard.sh`, ...argv];
}

// One dashboard.sh --action, read from its one-line JSON answer. The TUI gives
// cleanup 400 s; everything else is quick.
async function runAction(dir, stateDir, id, key, args = {}) {
  const argv = ["--action", id];
  if (key) argv.push(key);
  for (const [name, value] of Object.entries(args)) argv.push("--arg", `${name}=${value}`);
  const timeout = (id === "remove" ? 400 : 60) * 1000;
  try {
    const [cmd, ...cmdArgs] = dashboardArgv(dir, stateDir, argv);
    const r = await exec(cmd, cmdArgs, { timeout });
    if (r.code !== 0 && !r.stdout.trim()) return { ok: false, kitchen: false, message: r.stderr.trim() || `exit ${r.code}` };
    return parseAnswer(r.stdout);
  } catch (e) {
    return { ok: false, kitchen: false, message: String(e?.message ?? e) };
  }
}

export default class OctopilotDashboard extends View {
  init(_props, cx) {
    const p = props() ?? {};
    this.handle = cx.focus_handle();
    if (p.dialog) return this.initDialog(p, cx);
    this.dir = p.dir ?? shared("octopilot.dir") ?? `${home()}/.dotfiles/ai/octopilot`;
    // Only an explicit state dir is passed to the actions; unset, their default applies.
    this.stateExplicit = p.state_dir ?? shared("octopilot.state_dir") ?? null;
    this.stateDir = this.stateExplicit ?? `${home()}/.local/state/octopilot`;
    // A fixture file stands in for view.json (a test layout): no folder watch.
    this.fixture = p.fixture ?? null;
    this.viewFile = this.fixture ?? `${this.stateDir}/view.json`;
    this.view = null;
    this.raw = null;
    this.error = null;
    this.sel = null;
    this.showDone = false;
    this.expanded = new Set();
    this.pending = null;   // an armed confirm: { id, key, text, until }
    this.prior = null;     // the press armed before the one being handled
    this.held = false;     // the key being handled is auto-repeating
    this.flash = null;     // { text, ok, at }
    this.peeking = null;   // the peek this pane opened, until focus comes back: see followPeek
    this.tabShown = null;  // whether this pane's tab was the shown one on the last tick: see followTab
    this.scrolls = {
      running: ScrollHandle.new(), orch: ScrollHandle.new(), needs: ScrollHandle.new(),
      done: ScrollHandle.new(), pick: ScrollHandle.new(),
    };
    if (checking()) return;
    cx.timer.every(1000, (cx) => {
      this.followPeek();
      this.followTab();
      if (window()?.visible !== false) cx.notify();   // the clock and the ages
    });
    cx.timer.every(POLL_MS, (cx) => {
      if (window()?.visible !== false) this.reload(cx);
    });
    cx.spawn((cx) => this.reload(cx));
    if (!this.fixture) this.watchState(cx);
    cx.spawn(async (cx) => {
      for (;;) {
        const command = await nextCommand();
        if (command === "focus") this.takeFocus();
        cx.notify();
      }
    });
  }

  close() {
    this.closed = true;
    this.watch?.cancel();
  }

  watchState(cx) {
    cx.spawn(async (cx) => {
      for (;;) {
        if (this.closed) return;
        let watch;
        try {
          watch = watchFolder(this.stateDir);
          this.watch = watch;
          await watch;
        } catch {
          return;   // the poll carries on alone
        }
        await this.reload(cx);
      }
    });
  }

  async reload(cx) {
    let text;
    try {
      text = await readTextFile(this.viewFile);
    } catch (e) {
      this.error = String(e?.message ?? e);
      cx.notify();
      return;
    }
    if (text === this.raw) return;
    this.raw = text;
    this.error = null;
    if (text == null) {
      this.view = null;
    } else {
      let next;
      try {
        next = JSON.parse(text);
      } catch {
        next = null;
      }
      const bad = next ? viewError(next) : "view.json is not valid JSON yet";
      // A bad write keeps the last good view on screen, with the reason.
      if (bad) {
        this.error = bad;
      } else {
        next.kitchen = (next.kitchen ?? []).filter((k) => k.text);
        this.view = next;
      }
    }
    cx.notify();
  }

  kitchenOpen() {
    return shared("layout") === KITCHEN_LAYOUT;
  }

  // Shows or hides the kitchen corner by switching layouts; the layout's own
  // floating block holds the kitchen mod.
  toggleKitchen(cx) {
    if (!layouts().includes(KITCHEN_LAYOUT)) {
      this.say("kitchen layout not installed: run herdr-app/install.sh", false, cx);
      return;
    }
    run("layout.switch", { name: this.kitchenOpen() ? "main" : KITCHEN_LAYOUT });
  }

  // ---- dialogs: this mod opened with props.dialog ----

  initDialog(p, cx) {
    this.dir = p.dir;
    this.stateExplicit = p.state_dir ?? null;
    this.openedAt = Date.now();
    this.busy = false;
    this.readOnly = false;
    this.error = null;
    this.left = KITCHEN_S;
    this.repo = InputState.new({ placeholder: "owner/repo or name" });
    this.question = InputState.new({ placeholder: "what should it look into?" });
    this.repo.on("submit", () => this.question.focus());
    this.question.on("submit", (_e, cx) => this.investigateSubmit(cx));
    if (p.dialog === "kitchen") {
      cx.timer.every(1000, (cx) => {
        this.left -= 1;
        if (this.left <= 0) closeOverlay(p.overlay);
        else cx.notify();
      });
    }
    this.handle.focus();
    if (p.dialog === "investigate") this.repo.focus();
  }

  openDialog(kind, extra) {
    const tall = kind === "investigate";
    return openOverlay({
      mod: MOD, kind: "dialog", width: tall ? 520 : 440, height: tall ? 340 : 260,
      props: { dialog: kind, dir: this.dir, state_dir: this.stateExplicit, ...extra },
    });
  }

  dialogKey(e, cx) {
    // A held or just-opened g is a leftover press, not a decision.
    if (e.is_held || props()?.dialog !== "kitchen") return;
    const name = keyName(e);
    if (name === "g" && Date.now() - this.openedAt >= 500) this.kitchenStart(cx);
    else if (name === "n") this.dialogClose();
  }

  dialogClose() {
    closeOverlay(props().overlay);
  }

  kitchenStart(cx) {
    const p = props();
    if (this.busy) return;
    this.busy = true;
    cx.spawn(async () => {
      const res = await runAction(p.dir, p.state_dir, p.action, p.key, { ...(p.args ?? {}), confirmed: 1 });
      notify({
        title: "Octopilot", body: res.message || (res.ok ? "started" : "failed"),
        level: res.ok ? "success" : "error",
      });
      closeOverlay(p.overlay);
    });
  }

  investigateSubmit(cx) {
    const p = props();
    const repo = this.repo.value().trim();
    const question = this.question.value().trim();
    if (!repo || !question) {
      this.error = "a repo and a question are needed";
      cx.notify();
      return;
    }
    if (this.busy) return;
    this.busy = true;
    const args = { repo, question, read_only: this.readOnly ? 1 : 0 };
    cx.spawn(async (cx) => {
      const res = await runAction(p.dir, p.state_dir, p.action, null, args);
      if (res.kitchen) {
        this.openDialog("kitchen", { action: p.action, args, message: res.message });
        closeOverlay(p.overlay);
      } else if (res.ok) {
        notify({ title: "Octopilot", body: res.message, level: "success" });
        closeOverlay(p.overlay);
      } else {
        this.busy = false;
        this.error = res.message || "investigate failed";
        cx.notify();
      }
    });
  }

  // ---- state ----

  arr() {
    return arrange(this.view, { showDone: this.showDone, expanded: this.expanded });
  }

  anyCollapsed(view) {
    return (view.pick ?? []).some((g) => !this.expanded.has(g.repo));
  }

  doneLabel(view) {
    const done = view.columns.find((c) => c.id === "done");
    const hidden = done ? done.entries.filter((e) => !e.open).length : 0;
    if (this.showDone) return "hide done";
    return hidden ? `show done (+${hidden} hidden)` : "show done";
  }

  select(sel, cx) {
    this.sel = sel;
    this.reveal();
    cx.notify();
  }

  // Scroll the selected card or row into view. Only on a key or a click: the
  // scroll request would undo a manual scroll if it ran on every redraw.
  reveal() {
    if (!this.view) return;
    const arr = this.arr();
    for (const c of arr.columns) {
      const i = c.shown.findIndex((e) => e.key === this.sel);
      if (i >= 0) this.scrolls[c.id].scroll_to_item(i);
    }
    const r = arr.tree.findIndex((l) => l.key === this.sel);
    if (r >= 0) this.scrolls.pick.scroll_to_item(r);
  }

  say(text, ok, cx) {
    this.flash = { text, ok, at: Date.now() };
    cx.timer.after(FLASH_MS, (cx) => cx.notify());
    cx.notify();
  }

  // Every press starts here: an armed confirm belongs to the press before this one.
  begin() {
    this.prior = this.pending;
    this.pending = null;
    this.held = false;
    this.handle.focus();
  }

  toggleRepo(slug) {
    if (this.expanded.has(slug)) this.expanded.delete(slug);
    else this.expanded.add(slug);
  }

  toggleAll(cx) {
    if (this.anyCollapsed(this.view)) for (const g of this.view.pick ?? []) this.expanded.add(g.repo);
    else this.expanded.clear();
    cx.notify();
  }

  toggleDone(cx) {
    this.showDone = !this.showDone;
    cx.notify();
  }

  // h/l on the pick tree: l opens a repo, then steps into it; h closes it, or
  // from a row closes its repo and goes to the header.
  treeStep(d, arr, cx) {
    const repo = isRepoKey(this.sel) ? slugOf(this.sel) : null;
    if (d > 0) {
      if (!repo) return;
      if (!this.expanded.has(repo)) {
        this.expanded.add(repo);
      } else {
        const next = arr.tree[arr.tree.findIndex((l) => l.key === this.sel) + 1];
        if (next?.kind === "row") this.sel = next.key;
        this.reveal();
      }
    } else if (repo && !this.expanded.has(repo)) {
      this.select(jumpSel(arr, this.sel, -1), cx);
      return;
    } else if (!repo) {
      const header = arr.repoOf[this.sel];
      this.expanded.delete(slugOf(header));
      this.sel = header;
      this.reveal();
    } else {
      this.expanded.delete(repo);
    }
    cx.notify();
  }

  // ---- keys and presses ----

  key(e, cx) {
    const name = keyName(e);
    this.begin();
    this.held = Boolean(e.is_held);
    if (!name || !this.view) return;
    if (this.handleKey(name, cx)) cx.stop_propagation();
  }

  // -> whether the key was one this view answers to.
  handleKey(name, cx) {
    const view = this.view;
    const arr = this.arr();
    // The cursor may sit off the rows between a refocus and the next render: settle it first.
    this.sel = resolveSel(this.sel, arr);
    const repo = isRepoKey(this.sel) ? slugOf(this.sel) : null;
    const entry = entryOf(view, this.sel);
    if (NAV[name]) return this.select(stepSel(arr, this.sel, NAV[name]), cx), true;
    if (name === "h" || name === "left" || name === "l" || name === "right") {
      const d = name === "l" || name === "right" ? 1 : -1;
      if (repo || arr.repoOf[this.sel]) this.treeStep(d, arr, cx);
      else this.select(jumpSel(arr, this.sel, d), cx);
      return true;
    }
    if (name === "C") return this.toggleAll(cx), true;
    if (name === "D") return this.toggleDone(cx), true;
    if (name === "space" && repo) return this.toggleRepo(repo), cx.notify(), true;
    if (name === "enter" && repo) return this.toggleRepo(repo), cx.notify(), true;
    if (name === "space" && arr.repoOf[this.sel]) {
      // Collapse the row's repo and put the cursor on its header.
      this.expanded.delete(slugOf(arr.repoOf[this.sel]));
      this.sel = arr.repoOf[this.sel];
      this.reveal();
      cx.notify();
      return true;
    }
    if (entry) {
      const action = entry.actions.find((a) => actionKey(a.key) === name);
      if (action) return this.act(action, entry, cx), true;
      if (ROW_KEYS.includes(name)) {
        this.say(name === "enter" ? "no session for this row" : `${name}: not available for this row`, false, cx);
        return true;
      }
    } else if (repo && ROW_KEYS.includes(name)) {
      this.say("select a row, not a repo header", false, cx);
      return true;
    }
    const ids = GLOBAL_KEYS[name];
    const global = ids && (view.global_actions ?? []).find((a) => ids.includes(a.id));
    if (global) return this.act(global, null, cx), true;
    return false;
  }

  // A press on a button, or a double click, goes through the same path as a key.
  press(action, entry, cx) {
    this.begin();
    this.act(action, entry, cx);
  }

  pickEntry(key, clicks, cx) {
    this.begin();
    if (clicks < 2) return this.select(key, cx);
    this.sel = key;
    if (isRepoKey(key)) return this.toggleRepo(slugOf(key)), cx.notify();
    const entry = entryOf(this.view, key);
    const focus = entry?.actions.find((a) => a.id === "focus");
    if (focus) this.act(focus, entry, cx);
    else this.say("no session for this row", false, cx);
  }

  act(action, entry, cx) {
    const key = entry?.key ?? null;
    if (action.id === "toggle_done") return this.toggleDone(cx);
    if (action.id === "fold_all") return this.toggleAll(cx);
    if (action.id === "kitchen") return this.toggleKitchen(cx), cx.notify();
    if (action.id === "investigate" && action.args?.length) {
      this.openDialog("investigate", { action: action.id });
      return;
    }
    // A key held down must not repeat an action: only navigation repeats.
    if (this.held) return;
    const prior = this.prior;
    const armed = prior && Date.now() < prior.until && prior.id === action.id && prior.key === key;
    if (action.confirm && !armed) {
      this.pending = { id: action.id, key, text: action.confirm, until: Date.now() + CONFIRM_MS };
      cx.timer.after(CONFIRM_MS, (cx) => cx.notify());
      cx.notify();
      return;
    }
    this.perform(action.id, key, {}, cx);
  }

  perform(id, key, args, cx) {
    // A fixture with no state dir of its own must never act on the live octopilot.
    if (this.fixture && !this.stateExplicit) return this.say("Fixture mode: nothing was sent.", false, cx);
    if (id === "peek" || id === "prompter") this.watchPeek();
    cx.spawn(async (cx) => {
      const res = await runAction(this.dir, this.stateExplicit, id, key, args);
      if (res.kitchen) this.openDialog("kitchen", { action: id, key, args, message: res.message });
      else this.say(res.message || (res.ok ? "done" : "failed"), res.ok, cx);
      cx.notify();
    });
  }

  // A peek over the tab takes the keyboard from this pane, and closing it does not
  // send "focus" back (only a popup does). Note where the press came from.
  watchPeek() {
    const f = focused();
    if (!f?.pane) return;
    this.peeking = { since: Date.now(), pane: f.pane, tab: f.tab, before: f.terminal, terminal: null };
  }

  // On the clock tick: once the peek is closed and the focus is still in this pane's tab
  // (here, or on nothing), take the keyboard back, once. Another pane focused by the user stays.
  followPeek() {
    const w = this.peeking;
    if (!w) return;
    if (Date.now() - w.since > PEEK_WATCH_MS) {
      this.peeking = null;
      return;
    }
    const f = focused();
    if (!f) return;
    // The peek's terminal is the first one focused after the press.
    if (!w.terminal) {
      if (f.terminal && f.terminal !== w.before) w.terminal = f.terminal;
      return;
    }
    if (f.terminal === w.terminal) return;
    const back = f.tab === w.tab && (f.pane === w.pane || (f.pane === null && f.terminal === null));
    if (!back) return;
    this.peeking = null;
    this.takeFocus();
  }

  // On the clock tick: when this pane's tab becomes the shown one, take the keyboard, once,
  // unless a terminal or another pane of that tab has it.
  followTab() {
    const me = ownPane(panes(), MOD, PANE_NAME);
    const shown = me !== null && me.tab === shownTab(spaces());
    const was = this.tabShown;
    this.tabShown = shown;
    if (shown && was !== true && keyboardFree(focused(), me.pane)) this.takeFocus();
  }

  // Every refocus (peek closed, "focus", tab shown) lands on a valid cursor: the old row
  // while it exists, else the first one. h/l need that; j/k would recover on their own.
  takeFocus() {
    if (this.view) this.sel = resolveSel(this.sel, this.arr());
    this.handle.focus();
  }

  // ---- render ----

  render(cx) {
    const t = theme();
    const p = props() ?? {};
    if (p.dialog === "kitchen") return kitchenDialog(this, t, p);
    if (p.dialog === "investigate") return investigateDialog(this, t);
    const now = Date.now();
    const root = v_flex().id("octopilot-dashboard").track_focus(this.handle)
      .on_key_down((e, cx) => this.key(e, cx)).size_full().min_h(0).overflow_hidden().p(14).gap(10)
      .bg(t.background).text_color(t.foreground).text_size(12.5);
    const { view } = this;
    if (!view) return root.child(emptyState(t, this.viewFile, this.error));
    const arr = this.arr();
    this.sel = resolveSel(this.sel, arr);
    const entry = entryOf(view, this.sel);
    const globals = [...globalActions(view, this), { id: "kitchen", label: "🍳 kitchen", active: this.kitchenOpen() }];
    const notes = view.notes ?? [];
    return root
      .child(header(this, t, now))
      .when(Boolean(view.header.paused), (el) => el.child(paused(t)))
      .child(h_flex().flex_1().min_h_0().gap(10).items_stretch()
        .children(arr.columns.map((col) => column(this, t, col, now))))
      .when(notes.length > 0, (el) => el.child(notesRow(t, notes)))
      .child(h_flex().h(220).flex_none().gap(10).items_stretch()
        .child(pickPanel(this, t, arr, view.header.pick))
        .child(activityPanel(t, view, now)))
      .child(statusLine(this, t, now))
      .child(actionBar(this, t, entry, globals, isStale(view, now)));
  }
}
