// The dashboard's pieces: header, board cards and columns, the Pick next tree,
// activity and the action bar. Each reads the view and the theme and calls back
// into the view (main.js) for clicks; the state and the keys live there.

import { div } from "gpui-kit";
import { v_flex, h_flex } from "gpui-base";
import {
  AGENT_GLYPH, CI_GLYPH, ago, liveAge, elapsed, pickSummary, FLASH_MS, isRepoKey, isStale,
} from "./model.js";

// Column id -> the theme colour its title, count and card edge take.
export const COLUMN_TONE = { running: "working", orch: "accent", needs: "blocked", done: "done" };
const ACTIVITY_TONE = { report: "accent", spawn: "working", cleanup: "done", capped: "blocked" };
// The key each global action answers to, for its button's hint.
const GLOBAL_HINT = { refresh: "r", pause: "P", resume: "P", investigate: "i", prompter: "a", toggle_done: "D", fold_all: "C" };

// A small tag in a status colour, lightly tinted behind its text.
export function pill(t, text, color) {
  return h_flex().flex_none().h(18).px(6).items_center().rounded(5)
    .bg(color + "26").text_size(10.5).font_semibold().text_color(color).child(text);
}

// A key hint as a little keycap.
function keycap(t, key) {
  return div().flex_none().h(17).px(5).rounded(5).border_1().border_color(t.border)
    .bg(t.background).text_size(10.5).text_color(t.muted).child(key);
}

export function button(t, id, label, { key, tone, active = false, dim = false, on }) {
  return h_flex().id(id).flex_none().h(28).px(9).gap(7).items_center().rounded(8).border_1()
    .border_color(active ? t.accent : t.border).bg(active ? t.raised : t.surface)
    .text_size(12).text_color(tone ? t[tone] : t.foreground).cursor_pointer()
    .hover((s) => s.bg(t.hover))
    .when(dim, (el) => el.opacity(0.45))
    .on_click((ev, cx) => on(ev, cx))
    .child(label)
    .when(Boolean(key), (el) => el.child(keycap(t, key)));
}

const hhmm = (epoch) => {
  const d = new Date(epoch * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};
const clockText = (now) => {
  const d = new Date(now);
  return [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, "0")).join(":");
};
const ref = (key) => {
  const i = key.search(/[#!?]/);
  return i < 0 ? key : key.slice(i);
};
const shortKey = (key) => (key.includes("/") ? key.split("/", 2)[1] : key);

function github(t, gh, elapsedSecs) {
  if (gh.state === "refreshing") {
    return h_flex().gap(6).items_center().text_color(t.accent)
      .child(div().w(10).frames(["◐", "◓", "◑", "◒"], 120).child("◐"))
      .child("GitHub refreshing");
  }
  const tone = { ok: "done", stale: "working", old: "blocked" }[gh.state] ?? "working";
  const age = gh.age_s == null ? null : gh.age_s + elapsedSecs;
  const text = gh.state === "none" || age == null ? "GitHub: no snapshot yet" : `GitHub ${ago(age)} ago`;
  return h_flex().gap(6).items_center()
    .child(div().size(6).rounded_full().bg(t[tone]))
    .child(div().text_color(t[tone]).child(text))
    .when(Boolean(gh.error), (el) => el.child(div().text_color(t.blocked).child(`(${gh.error})`)));
}

function windDown(t, wd) {
  if (!wd || wd.state === "off") return null;
  return wd.state === "yes"
    ? pill(t, `🌇 past ${wd.at}, kitchen closed`, t.blocked)
    : pill(t, `🌇 wind-down at ${wd.at}`, t.muted);
}

export function header(v, t, now) {
  const { view } = v;
  const h = view.header;
  const elapsedSecs = elapsed(view, now);
  const lastTick = liveAge(h.last_tick_s, view, now);
  const stale = isStale(view, now);
  return v_flex().gap(6)
    .child(h_flex().items_center().gap(12)
      .child(h_flex().h(28).px(12).items_center().rounded(9).bg(t.solid)
        .text_color(t.solid_foreground).font_semibold().child("🐙 Octopilot"))
      .child(div().text_size(12.5).font_semibold().text_color(h.needs ? t.blocked : t.dim)
        .child(`🔴 ${h.needs} needs you`))
      .child(div().text_size(12.5).text_color(t.working).child(`🟡 ${h.running} running`))
      .child(div().text_size(12.5).text_color(t.muted).child(`⚪ ${h.pick} to pick`))
      .when(h.active != null, (el) => el.child(div().text_size(12.5).text_color(t.muted)
        .child(`${h.active}/${h.max_active} slots`
          + (h.untracked ? ` (+${h.untracked} untracked)` : ""))))
      .child(div().flex_1())
      .child(windDown(t, h.wind_down))
      .child(div().text_size(12).text_color(t.dim).child(clockText(now))))
    .child(h_flex().items_center().gap(14).text_size(11.5).text_color(t.dim)
      .when(stale, (el) => el.child(div().font_semibold().text_color(t.blocked)
        .child(`engine not running (view ${Math.floor(elapsedSecs)} s old)`)))
      .child(github(t, h.github ?? {}, elapsedSecs))
      .child(`last tick ${lastTick == null ? "never" : `${ago(lastTick)} ago`}`)
      .child(`orchestrator ${h.orch_label}`));
}

export function paused(t) {
  return h_flex().h(30).px(14).items_center().rounded(9).bg(t.working + "26")
    .text_color(t.working).font_semibold().text_size(12)
    .child("⏸  PAUSED: the orchestrator acts on nothing until resumed (P)");
}

// The selected card's edge is a bar that springs in, not a jump; inset so it stays inside
// the rounded corners (clipping is rectangular).
function card(v, t, e, tone, now) {
  const sel = v.sel === e.key;
  const { view } = v;
  const quiet = liveAge(e.quiet_s, view, now);
  const stalled = Boolean(e.stalled) || e.kind === "STALLED";
  const agent = e.agent ? AGENT_GLYPH[e.agent] ?? ["?", "dim"] : null;
  const ci = CI_GLYPH[e.checks];
  return v_flex().id(`card-${e.key}`).relative().overflow_hidden().flex_none()
    .rounded(12).border_1().border_color(sel ? t[tone] : t.border)
    .bg(sel ? t.raised : t.background).pl(14).pr(12).py(9).gap(5).cursor_pointer()
    .hover((s) => s.border_color(sel ? t[tone] : t.input))
    .on_click((ev, cx) => v.pickEntry(e.key, ev.click_count, cx))
    .child(div().id(`bar-${e.key}`).absolute().left_0().top(10).bottom(10).w(3).rounded_r(2)
      .bg(t[tone]).opacity(sel ? 1 : 0).spring("opacity"))
    .child(h_flex().items_center().gap(6).min_w_0()
      .child(div().font_semibold().text_size(12.5).text_color(t.foreground).truncate().child(e.label))
      .when(Boolean(e.draft), (el) => el.child(pill(t, "draft", t.muted)))
      .child(div().flex_1())
      .when(Boolean(ci), (el) => el.child(div().text_size(12).text_color(t[ci[1]]).child(ci[0]))))
    .child(div().h(34).overflow_hidden().text_size(12).line_height("17px")
      .text_color(t.foreground).child(e.title || "untitled"))
    .child(h_flex().items_center().gap(6).text_size(11).text_color(t.muted)
      .when(Boolean(agent), (el) => el.child(div().text_color(t[agent[1]]).child(agent[0])))
      .child(e.kind.toLowerCase())
      .when(e.rounds != null, (el) => el.child(`${e.rounds}/${e.max_rounds}`))
      .child(div().flex_1())
      .child(div().text_color(stalled ? t.blocked : t.dim).child(ago(quiet))))
    .when(Boolean(e.note), (el) => el.child(div().h(30).overflow_hidden().text_size(11)
      .line_height("15px").text_color(t.dim).child(e.note)));
}

export function column(v, t, col, now) {
  const tone = COLUMN_TONE[col.id] ?? "dim";
  const cards = col.shown.map((e) => card(v, t, e, tone, now));
  return v_flex().flex_1().min_w_0().min_h(0).overflow_hidden().rounded(14).border_1().border_color(t.border)
    .bg(t.surface).p(8).gap(8)
    .child(h_flex().items_center().gap(7).px(4).pt(2)
      .child(div().text_size(12.5).font_semibold().text_color(t[tone]).truncate().child(col.title))
      .child(pill(t, String(col.shown.length), t[tone]))
      .child(div().flex_1())
      .when(col.hidden > 0, (el) => el.child(div().text_size(10.5).text_color(t.dim)
        .child(`+${col.hidden} hidden`))))
    .child(div().flex_1().min_h(0).relative()
      .child(v_flex().id(`col-${col.id}`).absolute().inset_0().overflow_y_scroll()
        .track_scroll(v.scrolls[col.id]).gap(8)
        .children(cards.length ? cards : [div().py(24).text_center().text_color(t.dim).child("—")])));
}

function repoRow(v, t, line) {
  const sel = v.sel === line.key;
  const name = line.slug.split("/").pop();
  return h_flex().id(`repo-${line.slug}`).h(30).px(10).gap(8).items_center().rounded(8)
    .when(sel, (el) => el.bg(t.raised).border_1().border_color(t.border))
    .cursor_pointer().hover((s) => s.bg(t.hover))
    .on_click((ev, cx) => v.pickEntry(line.key, ev.click_count, cx))
    .child(div().w(12).text_color(t.muted).child(line.open ? "▾" : "▸"))
    .child(div().font_semibold().text_size(12.5).text_color(t.foreground).child(name))
    .child(pill(t, String(line.entries.length), t.muted))
    .child(div().flex_1().min_w_0().truncate().text_size(11).text_color(t.dim)
      .child(line.open ? "" : pickSummary(line.entries)));
}

function pickRow(v, t, line) {
  const e = line.entry;
  const sel = v.sel === e.key;
  return h_flex().id(`pick-${e.key}`).h(28).pl(22).pr(10).gap(8).items_center().rounded(8)
    .when(sel, (el) => el.bg(t.raised).border_1().border_color(t.border))
    .cursor_pointer().hover((s) => s.bg(t.hover))
    .on_click((ev, cx) => v.pickEntry(e.key, ev.click_count, cx))
    .child(div().w(18).text_color(t.dim).child(line.last ? "└─" : "├─"))
    .child(div().w(30).text_size(11).text_color(t.dim).child(`${e.index}`))
    .child(div().w(72).flex_none().font_semibold().text_size(12).text_color(t.foreground).truncate()
      .child(ref(e.key)))
    .child(div().flex_1().min_w_0().truncate().text_size(12).text_color(t.muted).child(e.title || ""))
    .child(pill(t, e.pick_kind, t.muted));
}

export function pickPanel(v, t, arr, total) {
  return v_flex().flex_1().min_w_0().min_h(0).overflow_hidden().rounded(14).border_1().border_color(t.border)
    .bg(t.surface).p(8).gap(6)
    .child(h_flex().items_center().gap(7).px(4).pt(2)
      .child(div().text_size(12.5).font_semibold().child("⚪ Pick next"))
      .child(pill(t, String(total), t.muted))
      .child(div().flex_1())
      .child(div().text_size(10.5).text_color(t.dim).child("# is what go N takes")))
    .child(div().flex_1().min_h(0).relative()
      .child(v_flex().id("pick").absolute().inset_0().overflow_y_scroll()
        .track_scroll(v.scrolls.pick).gap(1)
        .children(arr.tree.length
          ? arr.tree.map((line) => (line.kind === "repo" ? repoRow(v, t, line) : pickRow(v, t, line)))
          : [div().py(20).text_center().text_size(12).text_color(t.dim).child("nothing to pick")])));
}

export function activityPanel(t, view, now) {
  const rows = view.activity ?? [];
  return v_flex().w(372).flex_none().min_h(0).overflow_hidden().rounded(14).border_1().border_color(t.border)
    .bg(t.surface).p(10).gap(4)
    .child(div().px(4).pt(2).pb(4).text_size(12.5).font_semibold().child("Activity"))
    .children(rows.length
      ? rows.map((a) => h_flex().h(22).px(4).gap(8).items_center()
        .child(div().w(38).flex_none().text_size(11).text_color(t.dim).child(hhmm(a.at)))
        .child(div().w(62).flex_none().text_size(11).font_semibold()
          .text_color(t[ACTIVITY_TONE[a.kind]] ?? t.muted).child(a.kind))
        .child(div().w(104).flex_none().truncate().text_size(11).text_color(t.muted).child(shortKey(a.key)))
        .child(div().flex_1().min_w_0().truncate().text_size(11).text_color(t.dim).child(a.detail)))
      : [div().px(4).text_size(11.5).text_color(t.dim).child("no events yet")]);
}

export function notesRow(t, notes) {
  return h_flex().flex_wrap().gap(6).items_center().min_h(20)
    .child(div().text_size(11).text_color(t.dim).child("notes"))
    .children((notes ?? []).map((n) => pill(t, `${n.kind.toLowerCase()} ${shortKey(n.key)}`, t.working)));
}

// The confirm bar while a press is armed, else the last flash, else an empty
// line of the same height so nothing jumps.
export function statusLine(v, t, now) {
  const p = v.pending;
  if (p && now < p.until) {
    return h_flex().h(32).px(12).items_center().rounded(9).bg(t.working).text_color(t.background)
      .font_semibold().text_size(12.5).truncate()
      .child(p.text);
  }
  if (v.error) {
    return h_flex().h(32).px(12).items_center().rounded(9).bg(t.raised)
      .text_size(12.5).text_color(t.blocked).truncate().child(v.error);
  }
  const f = v.flash;
  if (f && now - f.at < FLASH_MS) {
    return h_flex().h(32).px(12).gap(8).items_center().rounded(9).bg(t.raised)
      .text_size(12.5).text_color(f.ok ? t.foreground : t.blocked).truncate()
      .child(div().size(6).rounded_full().bg(f.ok ? t.done : t.blocked))
      .child(f.text);
  }
  return div().h(32);
}

// The selected row's actions on the left, the board's and the mod's own on the right.
// With the engine stale the row actions are greyed: they still send, but may not apply.
export function actionBar(v, t, entry, globals, stale) {
  const rowButtons = entry
    ? entry.actions.map((a) => button(t, `act-${a.id}`, a.label, {
      key: a.key, tone: a.id === "remove" ? "blocked" : undefined, dim: stale,
      on: (_ev, cx) => v.press(a, entry, cx),
    }))
    : [];
  const hint = isRepoKey(v.sel) ? "enter folds this repo · h/l opens it" : "select a card or a row";
  return h_flex().h(46).px(8).gap(8).items_center().rounded(12).border_1().border_color(t.border).bg(t.surface)
    .child(h_flex().flex_1().min_w_0().gap(6).items_center().overflow_hidden()
      .children(rowButtons.length ? rowButtons : [div().px(4).text_size(11.5).text_color(t.dim).child(hint)]))
    .child(h_flex().flex_none().gap(6).items_center()
      .children(globals.map((g) => button(t, `g-${g.id}`, g.label, {
        key: GLOBAL_HINT[g.id], active: g.active, tone: g.tone, on: (_ev, cx) => v.press(g, null, cx),
      }))));
}

// The buttons the board's keys also reach, for the bar's right side.
export function globalActions(view, v) {
  const list = (view.global_actions ?? []).filter((a) => a.id !== "toggle_done");
  const shown = list.map((a) => ({ ...a, tone: a.id === "pause" || a.id === "resume" ? "working" : undefined }));
  return [
    ...shown,
    { id: "fold_all", label: v.anyCollapsed(view) ? "open all" : "fold all" },
    { id: "toggle_done", label: v.doneLabel(view), active: v.showDone },
  ];
}

export function emptyState(t, path, error) {
  return v_flex().size_full().items_center().justify_center().gap(8).p(24)
    .child(div().text_size(15).font_semibold().child("🐙 Waiting for octopilot"))
    .child(div().text_size(12).text_color(t.muted).text_center()
      .child("No view.json yet. The headless engine writes it: start dashboard.sh --headless in the Octopilot tab."))
    .child(div().text_size(11).text_color(t.dim).child(path))
    .when(Boolean(error), (el) => el.child(div().text_size(11.5).text_color(t.blocked).child(error)));
}

