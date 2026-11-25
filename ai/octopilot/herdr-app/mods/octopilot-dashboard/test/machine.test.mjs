import { test } from "node:test";
import assert from "node:assert/strict";
import { resolveMachine, machineCache, addressOn, machineOfAddress, bareAddress } from "../machine.js";

const spaces = [
  { id: "s1", active: true, machine: null, tabs: [{ id: "t1", active: false }, { id: "t2", active: true }] },
  { id: "r1", active: false, machine: "bolt", tabs: [{ id: "bolt/t9", active: true }] },
];
const panes = [
  { pane: "p1", mod: "octopilot-dashboard", name: "octopilot-dashboard", tab: "t1" },
  { pane: "p2", mod: "octopilot-chat", name: null, tab: "t1" },
  { pane: "p3", mod: "octopilot-dashboard", name: null, tab: "bolt/t9" },
];
const MOD = "octopilot-dashboard";
const remoteShown = [{ ...spaces[1], active: true }, { ...spaces[0], active: false }];

test("a named pane resolves to its space's machine (null: this computer)", () => {
  assert.equal(resolveMachine(panes, spaces, { mod: MOD, name: "octopilot-dashboard" }), null);
});

test("a remote pane resolves through the prefixed or the bare tab id", () => {
  assert.equal(resolveMachine([panes[2]], spaces, { mod: MOD }), "bolt");
  assert.equal(resolveMachine([{ ...panes[2], tab: "t9" }], spaces, { mod: MOD }), "bolt");
});

test("a name not found, but the mod's only pane: that pane, never the shown tab", () => {
  assert.equal(resolveMachine([panes[2]], remoteShown, { mod: MOD, name: "nope" }), "bolt");
  assert.equal(resolveMachine([panes[2]], spaces, { mod: MOD, name: "octopilot-dashboard" }), "bolt");
});

test("a name not found and two panes of the mod is unknown", () => {
  assert.equal(resolveMachine(panes, remoteShown, { mod: MOD, name: "nope" }), undefined);
});

test("several panes of the mod and no name is unknown", () => {
  assert.equal(resolveMachine(panes, remoteShown, { mod: MOD }), undefined);
});

test("a role name matches the pane renamed role-<hash> when it is the only such pane", () => {
  const hashed = [
    { pane: "h1", mod: MOD, name: "octopilot-dashboard-2c3bfaaf", tab: "t1" },
    { pane: "h2", mod: MOD, name: "octopilot-dashboard-other", tab: "bolt/t9" },
  ];
  assert.equal(resolveMachine(hashed, spaces, { mod: MOD, name: "octopilot-dashboard" }), undefined);
  assert.equal(resolveMachine([hashed[0], { ...hashed[1], mod: "octopilot-chat" }], spaces, { mod: MOD, name: "octopilot-dashboard" }), null);
  assert.equal(resolveMachine([hashed[0], { ...hashed[1], mod: "octopilot-chat" }], spaces, { mod: MOD, name: "octopilot-dashboard-2c3bfaaf" }), null);
});

test("an exact name wins over a prefix match", () => {
  const both = [
    { pane: "e1", mod: MOD, name: "octopilot-dashboard", tab: "t1" },
    { pane: "e2", mod: MOD, name: "octopilot-dashboard-2c3bfaaf", tab: "bolt/t9" },
  ];
  assert.equal(resolveMachine(both, spaces, { mod: MOD, name: "octopilot-dashboard" }), null);
});

test("a copy with a pane that is not in panes() is unknown", () => {
  assert.equal(resolveMachine([], spaces, { mod: MOD, name: "octopilot-dashboard" }), undefined);
  assert.equal(resolveMachine([], spaces, { mod: MOD }), undefined);
});

test("a floating copy with no pane of its mod uses the shown tab", () => {
  assert.equal(resolveMachine([], spaces, { mod: "octopilot-kitchen", floating: true }), null);
  assert.equal(resolveMachine([], remoteShown, { mod: "octopilot-kitchen", floating: true }), "bolt");
  // A pane of the mod exists: the floating copy does not guess.
  assert.equal(resolveMachine(panes, remoteShown, { mod: MOD, floating: true }), undefined);
});

test("undefined while no tab can be found", () => {
  assert.equal(resolveMachine([], [], { mod: MOD, floating: true }), undefined);
  assert.equal(resolveMachine([], [{ id: "x", active: false, machine: "bolt", tabs: [] }], { mod: MOD, floating: true }), undefined);
});

test("machineCache recomputes when spaces or the mod's panes change, and never keeps an unknown", () => {
  const cache = machineCache();
  const hints = { mod: MOD, name: "octopilot-dashboard" };
  assert.equal(cache(panes, spaces, hints), null);
  assert.equal(cache(panes, spaces, hints), null);
  // The pane moved to the remote tab: recomputed.
  const moved = panes.map((p) => (p.pane === "p1" ? { ...p, tab: "bolt/t9" } : p));
  assert.equal(cache(moved, spaces, hints), "bolt");
  // Spaces change: recomputed.
  assert.equal(cache(moved, remoteShown, { mod: MOD }), undefined);
  // Unknown is not kept: once the pane shows up, it is known.
  const later = machineCache();
  assert.equal(later([], spaces, hints), undefined);
  assert.equal(later(panes, spaces, hints), null);
});

test("addressOn prefixes a bare terminal only for a remote machine", () => {
  assert.equal(addressOn(null, "t7"), "t7");
  assert.equal(addressOn(undefined, "t7"), "t7");
  assert.equal(addressOn("bolt", "t7"), "bolt/t7");
  assert.equal(addressOn("bolt", "bolt/t7"), "bolt/t7");
  assert.equal(addressOn("bolt", null), null);
});

test("machineOfAddress and bareAddress split a terminal address", () => {
  assert.equal(machineOfAddress("bolt/t7"), "bolt");
  assert.equal(machineOfAddress("t7"), null);
  assert.equal(bareAddress("bolt/t7"), "t7");
  assert.equal(bareAddress("t7"), "t7");
});
