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
  assert.equal(count(body(out), "**"), 0);
  assert.equal(count(out, "**") % 2, 0);
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

function count(text, marker) {
  return text.split(marker).length - 1;
}
