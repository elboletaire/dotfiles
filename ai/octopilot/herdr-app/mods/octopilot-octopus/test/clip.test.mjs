import { test } from "node:test";
import assert from "node:assert/strict";
import { clip, MAX_CHARS } from "../clip.js";

const body = (out) => out.replace(/\s*…\*more\*$/, "");

test("short messages come back whole", () => {
  assert.equal(clip("one line\nand two"), "one line\nand two");
});

test("a bold run cut mid-way is closed", () => {
  const text = `${"plain words ".repeat(18)}**${"bold ".repeat(60)}**`;
  const out = clip(text);
  assert.ok(out.endsWith("…*more*"));
  // Was `== 0` (the run was cut away); the run is now kept and closed instead.
  assert.equal(count(body(out), "**"), 2);
  assert.ok(body(out).endsWith("**"));
});

test("a fence cut mid-way is closed before the ellipsis", () => {
  const text = `intro\n\`\`\`js\n${"const x = 1;\n".repeat(20)}\`\`\`\n`;
  const out = clip(text);
  assert.equal(count(out, "```") % 2, 0);
  assert.ok(out.endsWith("\n```\n…*more*"));
});

test("a long word is cut without breaking the length limit", () => {
  const out = clip("a".repeat(500));
  assert.ok(out.length <= MAX_CHARS + 12);
  assert.ok(out.startsWith("aaaa"));
});

test("long text is cut at a word boundary", () => {
  const text = "alpha beta gamma delta ".repeat(40);
  const out = body(clip(text));
  assert.equal(text[out.length], " ");
});

const filler = "lorem ipsum dolor sit amet ".repeat(12);

test("snake_case and identifiers are not emphasis", () => {
  const out = clip(`Raised MAX_ACTIVE from 4 to 6 ${filler}`);
  assert.ok(out.startsWith("Raised MAX_ACTIVE from 4 to 6 lorem"));
  const path = clip(`See ~/.local/state/octopilot/view_json ${filler}`);
  assert.ok(path.startsWith("See ~/.local/state/octopilot/view_json lorem"));
});

test("an open inline code span is closed, not cut", () => {
  const out = clip(`Set \`max_active\` to 6 ${filler}`.replace("to 6", "x".repeat(0) + "to 6"));
  assert.ok(out.startsWith("Set `max_active` to 6"));
  const cutInside = clip(`${"word ".repeat(52)}\`max_active_value and more text here ${filler}`);
  assert.equal(count(body(cutInside), "`") % 2, 0);
  assert.ok(body(cutInside).includes("`max_active_value"));
});

test("a three-item star list keeps every item", () => {
  const out = clip("* first item\n* second item\n* third item\n" + filler);
  assert.ok(out.includes("* third item"));
});

test("nested bold and code are closed in order", () => {
  const out = body(clip(`**bold \`code ${filler}${filler}`));
  assert.ok(out.endsWith("`**"));
  assert.equal(count(out, "`"), 2);
});

test("a cut exactly inside ** finishes the marker", () => {
  const head = `**${"b".repeat(5)} bold`;
  const text = `${"x ".repeat(100)}`;
  const out = body(clip(`${head} ${text}`, 6, head.length + 1 - 0));
  assert.equal(count(out, "**") % 2, 0);
  const inside = clip("**" + "bold ".repeat(10) + "**tail", 6, 5 * 10 + 3);
  assert.equal(count(body(inside), "**") % 2, 0);
  assert.ok(!/\*\*\*/.test(inside));
});

test("clipping is idempotent", () => {
  const once = clip(`**bold \`code ${filler}${filler}`);
  assert.equal(clip(once), once);
});

test("text under the limit is unchanged", () => {
  const text = "Set `max_active` to **6**\n* a\n* b";
  assert.equal(clip(text), text);
});

function count(text, marker) {
  return text.split(marker).length - 1;
}
