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

test("a local pane resolves to this computer (null)", () => {
  assert.equal(resolveMachine(panes, spaces, { mod: MOD, name: "octopilot-dashboard" }), null);
});

test("a remote pane resolves to its space's machine, through the prefixed tab id", () => {
  assert.equal(resolveMachine([panes[2]], spaces, { mod: MOD }), "bolt");
  assert.equal(resolveMachine([{ ...panes[2], tab: "t9" }], spaces, { mod: MOD }), "bolt");
});

test("a named pane is preferred; with two panes and no name, the shown tab decides", () => {
  assert.equal(resolveMachine(panes, spaces, { mod: MOD, name: "octopilot-dashboard" }), null);
  // Two dashboard panes and no name: neither is the mod's only pane, so the shown tab (t2) decides.
  const shownRemote = [{ ...spaces[1], active: true }, { ...spaces[0], active: false }];
  assert.equal(resolveMachine(panes, shownRemote, { mod: MOD }), "bolt");
});

test("a tab hint (the side panel's agent tab) wins over the pane", () => {
  assert.equal(resolveMachine(panes, spaces, { mod: MOD, name: "octopilot-dashboard", tab: "bolt/t9" }), "bolt");
});

test("without a pane, the shown tab's space decides", () => {
  assert.equal(resolveMachine([], spaces, { mod: MOD }), null);
  const remoteShown = [{ ...spaces[1], active: true }, { ...spaces[0], active: false }];
  assert.equal(resolveMachine([], remoteShown, { mod: MOD }), "bolt");
});

test("undefined while no tab can be found", () => {
  assert.equal(resolveMachine([], [], { mod: MOD }), undefined);
  assert.equal(resolveMachine([], [{ id: "x", active: false, machine: "bolt", tabs: [] }], { mod: MOD, tab: "t1" }), undefined);
});

test("machineCache recomputes only when spaces or hints change, or while unknown", () => {
  const cache = machineCache();
  assert.equal(cache(panes, spaces, { mod: MOD, name: "octopilot-dashboard" }), null);
  // Same spaces: the cached answer, even if the panes handed in now say otherwise.
  assert.equal(cache([panes[2]], spaces, { mod: MOD, name: "octopilot-dashboard" }), null);
  // Spaces change: recomputed.
  const moved = [{ ...spaces[1], active: true }, { ...spaces[0], active: false }];
  assert.equal(cache([panes[2]], moved, { mod: MOD }), "bolt");
  // A hint change recomputes too.
  assert.equal(cache(panes, moved, { mod: MOD, name: "x", tab: "t1" }), null);
  // Nothing found is not cached.
  const empty = machineCache();
  assert.equal(empty([], [], { mod: MOD }), undefined);
  assert.equal(empty(panes, spaces, { mod: MOD, name: "octopilot-dashboard" }), null);
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
