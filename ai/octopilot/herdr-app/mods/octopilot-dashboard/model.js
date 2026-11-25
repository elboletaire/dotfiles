// The dashboard's view model: view.json arranged the way the board and the
// Pick next tree show it. No Herdr calls here, so the keys and cards read the
// same numbers the TUI does.

export const REPO_PREFIX = "repo:";
// A second press of the same action within this window confirms it (CONFIRM_SECS).
export const CONFIRM_MS = 4000;
export const FLASH_MS = 6000;
// The kitchen-closed dialog cancels itself after this long (KITCHEN_SECS).
export const KITCHEN_S = 15;
// Global keys, and the view.json global action ids they stand for.
export const GLOBAL_KEYS = {
  r: ["refresh"], P: ["pause", "resume"], i: ["investigate"], a: ["prompter"],
};
// Keys the selected row's own actions answer to: with a repo header selected
// they say so instead of doing nothing.
export const ROW_KEYS = ["v", "t", "o", "g", "n", "R", "e", "x", "z", "d", "delete"];

export const AGENT_GLYPH = {
  running: ["◐", "working"], waiting: ["⏸", "blocked"], idle: ["○", "dim"],
  stopped: ["■", "dim"], error: ["✗", "blocked"],
};
export const CI_GLYPH = {
  pass: ["✓", "done"], fail: ["✗", "blocked"], pending: ["⏳", "working"], none: ["–", "dim"],
};

export const repoKey = (slug) => REPO_PREFIX + slug;
export const slugOf = (key) => key.slice(REPO_PREFIX.length);
export const isRepoKey = (key) => Boolean(key) && key.startsWith(REPO_PREFIX);

// dashboard.py's ago(): 12s, 5m, 2h05, 3d.
export function ago(secs) {
  if (secs == null) return "–";
  const s = Math.max(0, Math.floor(secs));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}`;
  return `${Math.floor(s / 86400)}d`;
}

// Seconds since view.json was written, so ages keep counting between writes.
export const elapsed = (view, now) => Math.max(0, now / 1000 - (view.generated_at ?? 0));
export const liveAge = (secs, view, now) => (secs == null ? null : secs + elapsed(view, now));

// Board columns with the rows they show (Done hides closed rows unless asked),
// and the Pick next tree as the lines it draws, plus every key the cursor can
// stand on, in the order j/k walk them.
export function arrange(view, { showDone, expanded }) {
  const columns = view.columns.map((c) => {
    if (c.id !== "done") return { ...c, shown: c.entries, hidden: 0 };
    const open = c.entries.filter((e) => e.open);
    return {
      ...c,
      shown: showDone ? c.entries : open,
      hidden: showDone ? 0 : c.entries.length - open.length,
    };
  });
  const order = columns.flatMap((c) => c.shown.map((e) => e.key));
  const repoOf = {};
  const tree = [];
  for (const group of view.pick ?? []) {
    const key = repoKey(group.repo);
    const open = expanded.has(group.repo);
    tree.push({ kind: "repo", key, slug: group.repo, entries: group.entries, open });
    order.push(key);
    for (const e of group.entries) repoOf[e.key] = key;
    if (!open) continue;
    group.entries.forEach((e, i) => {
      tree.push({ kind: "row", key: e.key, entry: e, last: i === group.entries.length - 1 });
      order.push(e.key);
    });
  }
  return { columns, tree, repoOf, selectable: [...new Set(order)] };
}

// The cursor stays where it is; a row hidden by its repo's fold falls back to
// that repo's header, and anything gone falls back to the first row.
export function resolveSel(sel, arr) {
  if (arr.selectable.includes(sel)) return sel;
  const header = arr.repoOf[sel];
  if (header && arr.selectable.includes(header)) return header;
  return arr.selectable[0] ?? null;
}

export function entryOf(view, key) {
  if (!key || isRepoKey(key)) return null;
  for (const c of view.columns) {
    const e = c.entries.find((x) => x.key === key);
    if (e) return e;
  }
  for (const g of view.pick ?? []) {
    const e = g.entries.find((x) => x.key === key);
    if (e) return e;
  }
  return null;
}

export function stepSel(arr, sel, d) {
  const i = arr.selectable.indexOf(sel);
  const j = Math.max(0, Math.min(arr.selectable.length - 1, (i < 0 ? 0 : i) + d));
  return arr.selectable[j] ?? sel;
}

// h/l between board columns and then the pick tree, skipping empty ones.
export function jumpSel(arr, sel, d) {
  const groups = [...arr.columns.map((c) => c.shown.map((e) => e.key)), arr.tree.map((l) => l.key)];
  const cur = groups.findIndex((g) => g.includes(sel));
  if (cur < 0) return sel;
  let i = cur + d;
  while (i >= 0 && i < groups.length && !groups[i].length) i += d;
  return i >= 0 && i < groups.length ? groups[i][0] : sel;
}

// "2 issue · 1 your PR", in the order the kinds first appear.
export function pickSummary(entries) {
  const counts = new Map();
  for (const e of entries) counts.set(e.pick_kind, (counts.get(e.pick_kind) ?? 0) + 1);
  return [...counts].map(([kind, n]) => `${n} ${kind}`).join(" · ");
}

// The key a keypress names: printable text as typed (so D is shift-d), else
// the key's own name. Chords with ctrl, alt or cmd belong to Herdr.
export function keyName(e) {
  const m = e.modifiers ?? {};
  if (m.control || m.alt || m.platform) return null;
  const ch = e.key_char;
  if (ch && ch.length === 1 && ch >= " " && ch !== "\x7f") return ch === " " ? "space" : ch;
  return e.key;
}

// Action keys come as "Delete", "Enter" or a single letter.
export const actionKey = (k) => (k.length === 1 ? k : k.toLowerCase());

// The shell's JSON answer: the last line of stdout.
export function parseAnswer(stdout) {
  const text = (stdout ?? "").trim();
  const line = text.split("\n").filter(Boolean).pop() ?? "";
  try {
    const j = JSON.parse(line);
    return { ok: Boolean(j.ok), kitchen: Boolean(j.kitchen), message: String(j.message ?? "") };
  } catch {
    return { ok: false, kitchen: false, message: text || "no answer from octopilot" };
  }
}
