import test from "node:test";
import assert from "node:assert/strict";
import { paneLayout, bubbleRows, PANE } from "../layout.js";
import { SCENE } from "../atlas.js";

test("a wide pane: the scene as tall as the pane, the bubble in the rest", () => {
  const l = paneLayout(950, 300);
  assert.equal(l.text, true);
  assert.equal(l.sceneH, 300 - 2 * PANE.pad);
  assert.ok(Math.abs(l.sceneW / l.sceneH - SCENE.w / SCENE.h) < 1e-9);
  assert.ok(Math.abs(l.textW + PANE.gap + l.sceneW - (950 - 2 * PANE.pad)) < 1e-9);
  assert.ok(l.textW >= PANE.minText);
});

test("a narrower pane: the scene shrinks to leave the bubble its width", () => {
  const l = paneLayout(600, 280);
  assert.equal(l.text, true);
  assert.ok(Math.abs(l.textW - PANE.minText) < 1e-9);
  assert.ok(l.sceneH < 280 - 2 * PANE.pad);
  assert.ok(l.scale >= PANE.minScale);
  assert.ok(Math.abs(l.sceneW / l.sceneH - SCENE.w / SCENE.h) < 1e-9);
});

test("too narrow for both: the scene alone, inside the pane", () => {
  const l = paneLayout(380, 280);
  assert.equal(l.text, false);
  assert.equal(l.textW, 0);
  assert.ok(l.sceneW <= 380 - 2 * PANE.pad + 1e-9);
  assert.ok(l.sceneH <= 280 - 2 * PANE.pad + 1e-9);
});

test("the scene never grows past the art's resolution, nor to nothing", () => {
  assert.equal(paneLayout(4000, 1200).scale, PANE.maxScale);
  assert.ok(paneLayout(0, 0).scale > 0);
});

test("the tail stays on the bubble", () => {
  for (const [w, h] of [[950, 300], [600, 280], [700, 120], [2000, 900]]) {
    const l = paneLayout(w, h);
    assert.ok(l.tailTop >= 12 && l.tailTop <= Math.max(12, l.textH - 32), `${w}x${h}`);
  }
});

test("a taller bubble shows more of the log", () => {
  const short = bubbleRows(450, 180);
  const tall = bubbleRows(450, 284);
  assert.ok(tall.log > short.log);
  assert.ok(tall.log > 4);
  assert.ok(tall.log <= PANE.logMax);
  assert.ok(short.lines >= 3 && tall.lines >= 3);
});

test("log lines the kitchen doesn't have go to the message", () => {
  const full = bubbleRows(450, 284);
  const few = bubbleRows(450, 284, 2);
  assert.equal(few.log, 2);
  assert.ok(few.lines > full.lines);
  assert.equal(bubbleRows(450, 284, 0).log, 0);
});

test("a tiny bubble still gets a line, and a wider one more characters", () => {
  const tiny = bubbleRows(250, 60);
  assert.equal(tiny.log, 0);
  assert.equal(tiny.lines, 1);
  assert.ok(bubbleRows(600, 284).chars > bubbleRows(250, 284).chars);
});
