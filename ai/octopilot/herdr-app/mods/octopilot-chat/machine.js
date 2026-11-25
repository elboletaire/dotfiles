// Where a mod's space lives, for herdr's `on` option: null for this computer, else the machine's
// name. A remote space's folders and terminals are that machine's, so its commands run there.
// Each mod has a copy of this file (a mod folder stands alone); keep them identical.

// The machine of the mod's space, from its tab: the tab given (the side panel's agent tab), else
// the tab of the mod's pane: the one named `name`, else the mod's only pane (name null). A copy
// that should have a pane but finds none it can name gets undefined: not known yet. Only a
// floating copy (no pane at all) falls back to the shown tab. Remote tab ids may carry the
// machine's prefix. -> the machine (null here), or undefined.
export function resolveMachine(panes, spaces, { mod, name = null, tab = null, floating = false }) {
  let id = tab;
  if (id == null) {
    const mine = panes.filter((p) => p.mod === mod);
    if (mine.length === 0) {
      if (!floating) return undefined;
      id = spaces.find((s) => s.active)?.tabs.find((t) => t.active)?.id ?? null;
    } else {
      const pane = name != null ? mine.find((p) => p.name === name) : (mine.length === 1 ? mine[0] : undefined);
      if (!pane) return undefined;
      id = pane.tab;
    }
  }
  if (id == null) return undefined;
  const space = spaces.find((s) => s.tabs.some((t) => t.id === id || (s.machine != null && t.id === `${s.machine}/${id}`)));
  return space ? (space.machine ?? null) : undefined;
}

// resolveMachine(), again when spaces(), the mod's panes or the hints change. An unknown answer
// (undefined) is never kept: the next call asks again.
export function machineCache() {
  let key = null;
  let machine;
  return (panes, spaces, hints) => {
    const mine = panes.filter((p) => p.mod === hints.mod).map((p) => [p.pane, p.name, p.tab]);
    const next = JSON.stringify([hints, mine, spaces.map((s) => [s.id, s.machine, s.active, s.tabs.map((t) => [t.id, t.active])])]);
    if (next !== key || machine === undefined) {
      key = next;
      machine = resolveMachine(panes, spaces, hints);
    }
    return machine;
  };
}

// A terminal address for herdr from a bare one (scan.sh's `t7`): remote ones are `<machine>/t7`.
export function addressOn(on, terminal) {
  if (!on || !terminal || terminal.includes("/")) return terminal;
  return `${on}/${terminal}`;
}

// The machine a terminal address names (`bolt/t7` -> bolt), null for a bare one, and the bare id.
export function machineOfAddress(address) {
  return address.includes("/") ? address.slice(0, address.indexOf("/")) : null;
}

export function bareAddress(address) {
  return address.slice(address.lastIndexOf("/") + 1);
}
