// What the kitchen shows, worked out from view.json (`pan`, `kitchen`, `header`): no
// drawing and no herdr calls here, so node can test it.
import { PAN, SPRITE, SHELF, ARM_POSES, COOK_STEPS } from "./atlas.js";

export const STALE_S = 15;
export const LOG_LINES = 4;
export const WALK_MS = 1200;
const BURST_MIN_MS = 2000;
const MAX_HOLES = 12;
// The pitch the ball sprites were drawn for; more holes than fit shrink the balls.
const PITCH = 36;

export const MOODS = ["idle", "busy", "flip", "pour", "happy", "serve", "worried", "sad", "surprised", "sleep", "doze"];
const RESTING = ["sleep", "busy", "doze", "idle"];
const BALL_STATES = ["raw", "cooking", "ready", "capped", "burnt", "stalled"];
export const BURSTS = ["steam", "batter", "sparkle", "smoke", "bang", "heart", "zzz", "ink"];
// Moods drawn in the flushed palette, and those with open eyes (which blink).
const FLUSHED = ["worried", "sad"];
const BLINKS = ["idle", "busy", "flip", "pour", "worried", "doze"];
const ARM = { sleep: "down", doze: "down", sad: "down", happy: "cheer", serve: "cheer", idle: "rest", worried: "rest", surprised: "rest" };

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const list = (v) => (Array.isArray(v) ? v : []);

export function ballSprite(ball) {
  const state = BALL_STATES.includes(ball?.state) ? ball.state : "cooking";
  if (state !== "cooking") return `ball-${state}`;
  const heat = clamp(Number(ball?.heat) || 0, 0, 1);
  return `ball-cooking-${Math.min(COOK_STEPS - 1, Math.floor(heat * COOK_STEPS))}`;
}

// Where hole `i` of `n` sits: its ball's centre x, and the scale its sprites are drawn at.
export function holeAt(i, n) {
  const pitch = PAN.w / n;
  return { x: PAN.x + pitch * (i + 0.5), scale: Math.min(1, pitch / PITCH) };
}

// A sprite's [left, top, width, height] for a ball centred on hole `i`.
export function spriteBox(i, n) {
  const { x, scale } = holeAt(i, n);
  return [x - SPRITE.cx * scale, PAN.ballY - SPRITE.cy * scale, SPRITE.w * scale, SPRITE.h * scale];
}

// Where the `i`th served boat stands: the lower plank first, then the upper one.
export function boatBox(i) {
  const row = SHELF.rows[Math.floor(i / SHELF.perRow)] ?? SHELF.rows[SHELF.rows.length - 1];
  return [SHELF.x + (i % SHELF.perRow) * SHELF.pitch, row + SHELF.boat.dy, SHELF.boat.w, SHELF.boat.h];
}
export const SHELF_SLOTS = SHELF.rows.length * SHELF.perRow;

// The event's mood while its time lasts, then what the chef rests in.
export function chefMood(chef, nowMs) {
  const resting = RESTING.includes(chef?.resting) ? chef.resting : "idle";
  const ms = Number(chef?.ms) || 0;
  const since = Number(chef?.since) || 0;
  if (MOODS.includes(chef?.mood) && ms > 0 && nowMs - since * 1000 < ms) return chef.mood;
  return resting;
}

// When the chef's event mood ends (ms epoch), or null when it already has.
function moodEnd(chef, nowMs) {
  const end = (Number(chef?.since) || 0) * 1000 + (Number(chef?.ms) || 0);
  return MOODS.includes(chef?.mood) && end > nowMs ? end : null;
}

// The hole the chef works on: walking the pan while just busy, else the flagged ball, else the first.
export function focusIndex(balls, walking, walk = 0) {
  if (!balls.length) return -1;
  if (walking) return walk % balls.length;
  const flagged = balls.findIndex((b) => b.focus === true);
  return flagged < 0 ? 0 : flagged;
}

// The drawn arm pose nearest to hole `focus`, and how far (px) to slide it to land on the hole.
export function armReach(focus, holes) {
  const { x } = holeAt(focus, holes);
  const pitch = PAN.w / ARM_POSES;
  const pose = clamp(Math.round((x - PAN.x) / pitch - 0.5), 0, ARM_POSES - 1);
  return { pose, shift: x - (PAN.x + pitch * (pose + 0.5)) };
}

// The arm piece for a mood: the pick (or the batter jug) over the focused hole, or a pose of its own.
export function armPiece(mood, focus, holes) {
  const fixed = focus < 0 ? ARM[mood] ?? "rest" : ARM[mood];
  if (fixed) return `arm-${fixed}-${FLUSHED.includes(mood) && fixed !== "cheer" ? "f" : "w"}`;
  return `arm-${mood === "pour" ? "pour" : "point"}-${armReach(focus, holes).pose}`;
}

export function newest(kitchen) {
  let best = null;
  for (const ev of list(kitchen)) if (typeof ev?.at === "number" && (!best || ev.at >= best.at)) best = ev;
  return best;
}

const burstMs = (ev) => Math.max(Number(ev?.ms) || 0, BURST_MIN_MS);

export function toneOf(ev) {
  if (ev?.tone === "good" || ev?.tone === "bad" || ev?.tone === "info") return ev.tone;
  return ev?.good === true ? "good" : "info";
}

const pad = (n) => String(n).padStart(2, "0");
export function clock(at) {
  const d = new Date(at * 1000);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// The last lines of the kitchen log, oldest first; all but the newest two are dim.
export function logLines(kitchen, max = LOG_LINES) {
  const lines = list(kitchen).filter((ev) => typeof ev?.at === "number" && ev.text)
    .sort((a, b) => a.at - b.at).slice(-max);
  return lines.map((ev, i) => ({
    clock: clock(ev.at),
    text: String(ev.text).split("\n")[0],
    tone: toneOf(ev),
    dim: i < lines.length - 2,
  }));
}

export function headerLine({ onPan, holes, shelf, paused, offline }) {
  return `🐙 takoyaki kitchen · ${onPan}/${holes} on the pan`
    + (shelf > 0 ? ` · ${shelf} on the shelf` : "")
    + (paused ? " · paused" : "")
    + (offline ? " · offline" : "");
}

// Everything the scene and the bubble draw, for `view` at `nowMs`. `walk` counts the steps
// the chef has taken along the pan. `until` is when this stops being true (a mood or a
// burst ends), or null.
export function derive(view, nowMs, walk = 0) {
  const nowS = nowMs / 1000;
  const header = view?.header ?? {};
  const pan = view?.pan ?? null;
  const kitchen = list(view?.kitchen);
  const offline = !view || !(nowS - (Number(view.generated_at) || 0) <= STALE_S);
  const paused = pan?.paused === true || header.paused === true;
  const holes = clamp(Math.round(Number(pan?.holes ?? header.max_active) || 6), 1, MAX_HOLES);
  const balls = list(pan?.balls).slice(0, holes);
  const shelf = list(pan?.shelf).slice(0, SHELF_SLOTS);
  const last = newest(kitchen);
  // Without `pan` (an older backend) the newest event stands in for the chef.
  const chef = pan?.chef ?? (last ? { mood: last.mood, since: last.at, ms: last.ms, resting: "idle" } : null);

  // An event's mood shows even while paused; `pan` already rests in sleep then.
  let mood = chefMood(chef, nowMs);
  if (paused && !pan && mood === "idle") mood = "sleep";
  if (offline) mood = "doze";
  const busy = pan?.busy === true && !paused && !offline;
  const focus = focusIndex(balls, busy && mood === "busy", walk);

  let burst = null;
  let until = offline ? null : moodEnd(chef, nowMs);
  if (!offline && last && BURSTS.includes(last.burst)) {
    const end = last.at * 1000 + burstMs(last);
    if (end > nowMs) {
      burst = { kind: last.burst, hole: balls.findIndex((b) => b.key && b.key === last.key),
        boat: shelf.findIndex((b) => b.key && b.key === last.key) };
      until = until == null ? end : Math.min(until, end);
    }
  }

  return {
    offline,
    paused,
    busy,
    holes,
    mood,
    flushed: FLUSHED.includes(mood),
    blinks: BLINKS.includes(mood) && !offline,
    arm: armPiece(mood, focus, holes),
    armShift: armPiece(mood, focus, holes).match(/point|pour/) ? armReach(focus, holes).shift : 0,
    // Never out while the kitchen is open: a pilot simmer, roaring while the orchestrator works.
    flames: offline ? "none" : busy ? "big" : "pilot",
    balls: balls.map((b, i) => ({ sprite: ballSprite(b), state: b.state, label: b.label ?? b.key ?? "", focus: i === focus })),
    focus,
    boats: shelf.length,
    burst,
    header: headerLine({
      onPan: pan ? balls.length : Number(header.active) || 0,
      holes,
      shelf: Number(pan?.shelf_total) || list(pan?.shelf).length,
      paused,
      offline,
    }),
    log: logLines(kitchen),
    until,
  };
}
