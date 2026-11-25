import { test } from "node:test";
import assert from "node:assert/strict";
import { arrange, resolveSel, stepSel, jumpSel, soloPane, shownTab, keyboardFree } from "../model.js";

const view = {
  columns: [
    { id: "running", entries: [{ key: "a1", open: true }, { key: "a2", open: true }] },
    { id: "orch", entries: [] },
    { id: "needs", entries: [{ key: "n1", open: true }] },
    { id: "done", entries: [] },
  ],
  pick: [{ repo: "acme/x", entries: [{ key: "p1" }, { key: "p2" }] }],
};

test("h/l from a resolved null cursor land on a row, as j/k do", () => {
  const arr = arrange(view, { showDone: false, expanded: new Set(["acme/x"]) });
  const sel = resolveSel(null, arr);
  assert.equal(sel, "a1");
  assert.equal(jumpSel(arr, sel, 1), "n1");
  assert.equal(jumpSel(arr, sel, -1), "a1");
  assert.equal(jumpSel(arr, "n1", -1), "a1");
});

test("a stale cursor keeps its row while it exists, else falls back", () => {
  const arr = arrange(view, { showDone: false, expanded: new Set() });
  assert.equal(resolveSel("n1", arr), "n1");
  assert.equal(resolveSel("gone", arr), "a1");
  assert.equal(stepSel(arr, "n1", 1), "repo:acme/x");
});

test("soloPane finds a mod that has exactly one pane", () => {
  const panes = [
    { pane: "p1", mod: "octopilot-dashboard", tab: "t1" },
    { pane: "p2", mod: "octopilot-chat", tab: "t1" },
  ];
  assert.deepEqual(soloPane(panes, "octopilot-dashboard"), panes[0]);
  assert.equal(soloPane(panes, "octopilot-kitchen"), null);
  assert.equal(soloPane([...panes, { pane: "p3", mod: "octopilot-dashboard", tab: "t2" }], "octopilot-dashboard"), null);
});

test("shownTab is the active tab of the active space", () => {
  const spaces = [
    { active: false, tabs: [{ id: "x", active: true }] },
    { active: true, tabs: [{ id: "t1", active: false }, { id: "t2", active: true }] },
  ];
  assert.equal(shownTab(spaces), "t2");
  assert.equal(shownTab([]), null);
});

test("keyboardFree leaves the keyboard to a terminal or another pane", () => {
  assert.equal(keyboardFree(null, "p1"), true);
  assert.equal(keyboardFree({ pane: null, terminal: null }, "p1"), true);
  assert.equal(keyboardFree({ pane: "p1", terminal: null }, "p1"), true);
  assert.equal(keyboardFree({ pane: "p2", terminal: null }, "p1"), false);
  assert.equal(keyboardFree({ pane: "p1", terminal: "t9" }, "p1"), false);
  assert.equal(keyboardFree({ pane: null, terminal: "t9" }, "p1"), false);
});
