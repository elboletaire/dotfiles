// The two dialogs the mod opens over itself: the kitchen-closed alert, and the
// investigate form. Both draw from the view's state (main.js owns it and the
// actions they send).

import { div } from "gpui-kit";
import { v_flex, h_flex, Input } from "gpui-base";
import { button } from "./parts.js";

export function kitchenDialog(v, t, p) {
  return v_flex().id("kitchen").track_focus(v.handle).on_key_down((e, cx) => v.dialogKey(e, cx))
    .size_full().p(20).gap(12).rounded(14).bg(t.popover).border_1().border_color(t.blocked)
    .child(h_flex().items_center().gap(10)
      .child(div().text_size(16).font_semibold().text_color(t.blocked).child("🍳 Kitchen closed"))
      .child(div().flex_1())
      .child(div().text_size(11).text_color(t.dim).child(`cancels in ${v.left}s`)))
    .child(div().text_size(12.5).text_color(t.foreground).child(p.message || "The kitchen is closed."))
    .when(Boolean(p.key), (el) => el.child(div().px(12).py(9).rounded(10).bg(t.surface)
      .font_semibold().text_size(13).child(p.key)))
    .child(div().text_size(12).text_color(t.muted).child("Start it anyway, or leave it for tomorrow."))
    .child(div().flex_1())
    .child(h_flex().justify_end().gap(8)
      .child(button(t, "kitchen-cancel", "Cancel", { key: "n", on: (_e, cx) => v.dialogClose(cx) }))
      .child(button(t, "kitchen-start", "Start anyway", {
        key: "g", active: true, tone: "working", on: (_e, cx) => v.kitchenStart(cx),
      })));
}

function field(t, label, state) {
  return v_flex().gap(6)
    .child(div().text_size(11.5).text_color(t.dim).child(label))
    .child(Input.new(state).h(36).px(10).rounded(9).border_1().border_color(t.input)
      .bg(t.background).text_size(12.8).text_color(t.foreground));
}

export function investigateDialog(v, t) {
  return v_flex().id("investigate").track_focus(v.handle).on_key_down((e, cx) => v.dialogKey(e, cx))
    .size_full().p(20).gap(12).rounded(14).bg(t.popover).border_1().border_color(t.border)
    .child(h_flex().items_center().gap(10)
      .child(div().flex_1().text_size(16).font_semibold().child("🔎 Investigate"))
      .child(div().text_size(11).text_color(t.dim).child("Esc to close")))
    .child(field(t, "Repo (owner/repo or name)", v.repo))
    .child(field(t, "Question", v.question))
    .child(h_flex().id("investigate-ro").items_center().gap(9).cursor_pointer()
      .on_click((_e, cx) => { v.readOnly = !v.readOnly; cx.notify(); })
      .child(div().size(16).rounded(4).border_1().border_color(v.readOnly ? t.accent : t.input)
        .bg(v.readOnly ? t.accent : t.background).text_size(11).text_color(t.accent_foreground)
        .flex().items_center().justify_center()
        .child(v.readOnly ? "✓" : ""))
      .child(div().text_size(12.5).text_color(t.muted).child("Read-only: a report, no commits or PR")))
    .when(Boolean(v.error), (el) => el.child(div().text_size(12).text_color(t.blocked).child(v.error)))
    .child(div().flex_1())
    .child(h_flex().justify_end().gap(8)
      .child(button(t, "inv-cancel", "Cancel", { key: "esc", on: (_e, cx) => v.dialogClose(cx) }))
      .child(button(t, "inv-send", "Investigate", {
        active: true, tone: "accent", on: (_e, cx) => v.investigateSubmit(cx),
      })));
}
