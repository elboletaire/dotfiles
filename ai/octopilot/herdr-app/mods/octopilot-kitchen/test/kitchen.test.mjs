import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { derive, ballSprite, chefMood, focusIndex, armPiece, holeAt, spriteBox, boatBox, toneOf, logLines, headerLine, MOODS, BURSTS } from "../kitchen.js";
import { PAN, ARM_POSES, COOK_STEPS } from "../atlas.js";

const here = new URL(".", import.meta.url);
const fixture = (name) => JSON.parse(readFileSync(new URL(`../../../fixtures/${name}`, here), "utf8"));
const png = (name) => existsSync(new URL(`../art/png/${name}.png`, here));

test("a ball's sprite follows its state, and its heat while cooking", () => {
  assert.equal(ballSprite({ state: "raw", heat: 1 }), "ball-raw");
  assert.equal(ballSprite({ state: "cooking", heat: 0 }), "ball-cooking-0");
  assert.equal(ballSprite({ state: "cooking", heat: 0.5 }), "ball-cooking-2");
  assert.equal(ballSprite({ state: "cooking", heat: 1 }), `ball-cooking-${COOK_STEPS - 1}`);
  assert.equal(ballSprite({ state: "cooking", heat: 7 }), `ball-cooking-${COOK_STEPS - 1}`);
  assert.equal(ballSprite({ state: "cooking" }), "ball-cooking-0");
  assert.equal(ballSprite({ state: "who-knows" }), "ball-cooking-0");
  for (const state of ["ready", "capped", "burnt", "stalled"]) assert.equal(ballSprite({ state }), `ball-${state}`);
});

test("the chef shows the event's mood for its time, then rests", () => {
  const chef = { mood: "happy", since: 100, ms: 4000, resting: "busy" };
  assert.equal(chefMood(chef, 100_000), "happy");
  assert.equal(chefMood(chef, 103_999), "happy");
  assert.equal(chefMood(chef, 104_000), "busy");
  assert.equal(chefMood({ mood: "nonsense", since: 100, ms: 4000, resting: "doze" }, 100_000), "doze");
  assert.equal(chefMood({ mood: "happy", since: 100, ms: 4000, resting: "nonsense" }, 200_000), "idle");
  assert.equal(chefMood(null, 0), "idle");
});

test("the focus is the flagged ball, else the first, and walks while busy", () => {
  const balls = [{}, { focus: true }, {}];
  assert.equal(focusIndex([], false), -1);
  assert.equal(focusIndex(balls, false), 1);
  assert.equal(focusIndex([{}, {}], false), 0);
  assert.deepEqual([0, 1, 2, 3].map((walk) => focusIndex(balls, true, walk)), [0, 1, 2, 0]);
});

test("holes spread over the pan and shrink when there are many", () => {
  assert.equal(holeAt(0, 6).x, PAN.x + PAN.w / 12);
  assert.equal(holeAt(0, 6).scale, 1);
  assert.ok(holeAt(0, 8).scale < 1);
  const [left, , width] = spriteBox(7, 8);
  assert.ok(left + width <= PAN.x + PAN.w + 4);
  assert.notDeepEqual(boatBox(0), boatBox(4));
  assert.equal(boatBox(0)[0], boatBox(4)[0]);
});

test("the arm reaches the focused hole, or takes the mood's own pose", () => {
  assert.equal(armPiece("busy", 0, 6), "arm-point-0");
  assert.equal(armPiece("flip", 5, 6), `arm-point-${ARM_POSES - 1}`);
  assert.equal(armPiece("pour", 2, 6), "arm-pour-2");
  assert.equal(armPiece("busy", 7, 8), `arm-point-${ARM_POSES - 1}`);
  assert.equal(armPiece("busy", -1, 6), "arm-rest-w");
  assert.equal(armPiece("happy", 2, 6), "arm-cheer-w");
  assert.equal(armPiece("sad", 2, 6), "arm-down-f");
  assert.equal(armPiece("worried", 2, 6), "arm-rest-f");
  assert.equal(armPiece("sleep", -1, 6), "arm-down-w");
});

test("every piece the scene can ask for has its art", () => {
  for (const mood of MOODS) {
    for (const frame of [0, 1]) assert.ok(png(`chef-${mood}-${frame}`), `chef-${mood}-${frame}`);
    for (const focus of [-1, 0, 3, 5]) assert.ok(png(armPiece(mood, focus, 6)), armPiece(mood, focus, 6));
  }
  for (const kind of BURSTS) assert.ok(png(`burst-${kind}`), kind);
  for (const state of ["raw", "ready", "capped", "burnt", "stalled"]) assert.ok(png(`ball-${state}`));
  for (let step = 0; step < COOK_STEPS; step++) assert.ok(png(`ball-cooking-${step}`));
  for (const name of ["bg", "shelf", "counter", "pan", "boat", "hole", "focus", "glow-ready", "glow-capped", "smoke", "steam",
    "blink-w", "blink-f", "flame-big-0", "flame-big-1", "flame-pilot-0", "flame-pilot-1"]) assert.ok(png(name), name);
});

test("a line's tone comes from `tone`, else only a good one is coloured", () => {
  assert.equal(toneOf({ tone: "bad", good: false }), "bad");
  assert.equal(toneOf({ tone: "info", good: true }), "info");
  assert.equal(toneOf({ good: true }), "good");
  assert.equal(toneOf({ good: false }), "info");
});

test("the log keeps the last lines in order, one line each, the older ones dim", () => {
  const kitchen = [3, 1, 5, 2, 4].map((at) => ({ at, text: `line ${at}\nmore`, good: at === 5 }));
  const lines = logLines(kitchen, 4);
  assert.deepEqual(lines.map((l) => l.text), ["line 2", "line 3", "line 4", "line 5"]);
  assert.deepEqual(lines.map((l) => l.dim), [true, true, false, false]);
  assert.equal(lines[3].tone, "good");
  assert.match(lines[0].clock, /^\d\d:\d\d$/);
  assert.deepEqual(logLines(null), []);
});

test("the header counts the pan and the shelf", () => {
  assert.equal(headerLine({ onPan: 2, holes: 6, shelf: 0 }), "🐙 takoyaki kitchen · 2/6 on the pan");
  assert.equal(headerLine({ onPan: 2, holes: 6, shelf: 3, paused: true }),
    "🐙 takoyaki kitchen · 2/6 on the pan · 3 on the shelf · paused");
});

test("the fixture kitchen: every ball state, a focus, a shelf and a live burst", () => {
  const view = fixture("kitchen-view.json");
  const now = view.generated_at * 1000;
  const m = derive(view, now);
  assert.deepEqual(m.balls.map((b) => b.sprite),
    ["ball-raw", "ball-cooking-1", "ball-cooking-4", "ball-ready", "ball-capped", "ball-burnt"]);
  assert.equal(m.mood, "happy");
  assert.equal(m.arm, "arm-cheer-w");
  assert.equal(m.focus, 2);
  assert.equal(m.boats, 3);
  assert.equal(m.flames, "big");
  assert.deepEqual(m.burst, { kind: "sparkle", hole: 3, boat: -1 });
  assert.equal(m.header, "🐙 takoyaki kitchen · 6/6 on the pan · 3 on the shelf");
  assert.equal(m.offline, false);
  // The mood and its burst both end 4 s after the event: that is the next change.
  assert.equal(m.until, (view.generated_at - 1) * 1000 + 4000);

  // Once the mood is over he is just busy, and walks the pan.
  const later = derive(view, now + 5000, 4);
  assert.equal(later.mood, "busy");
  assert.equal(later.burst, null);
  assert.equal(later.until, null);
  assert.equal(later.focus, 4);
  assert.equal(later.arm, "arm-point-4");
});

test("paused: the chef sleeps and the flames are out", () => {
  const view = fixture("kitchen-view-paused.json");
  const m = derive(view, view.generated_at * 1000);
  assert.equal(m.mood, "sleep");
  assert.equal(m.flames, "none");
  assert.equal(m.arm, "arm-down-w");
  assert.equal(m.holes, 8);
  assert.ok(m.balls.some((b) => b.sprite === "ball-stalled"));
  assert.ok(m.header.endsWith("· paused"));
});

test("a stale or missing view is an offline kitchen", () => {
  const view = fixture("kitchen-view.json");
  const m = derive(view, (view.generated_at + 16) * 1000);
  assert.equal(m.offline, true);
  assert.equal(m.flames, "none");
  assert.equal(m.mood, "doze");
  assert.equal(m.burst, null);
  assert.equal(m.until, null);
  assert.equal(derive(view, (view.generated_at + 15) * 1000).offline, false);
  const none = derive(null, Date.now());
  assert.equal(none.offline, true);
  assert.equal(none.holes, 6);
  assert.deepEqual(none.balls, []);
});

test("without `pan` (an older backend) the newest event still moves the chef", () => {
  const view = fixture("kitchen-view.json");
  delete view.pan;
  const m = derive(view, view.generated_at * 1000);
  assert.equal(m.mood, "happy");
  assert.deepEqual(m.balls, []);
  assert.equal(m.header, "🐙 takoyaki kitchen · 3/6 on the pan");
});
