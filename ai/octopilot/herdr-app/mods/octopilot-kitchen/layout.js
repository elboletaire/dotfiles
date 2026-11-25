// How the kitchen fills a pane: the scene scaled to the pane's height on the right, the
// bubble in the width that is left. Pure, so node can test it.
import { SCENE } from "./atlas.js";

export const PANE = { pad: 8, gap: 14, minText: 250, minScale: 0.6, maxScale: 2, logMax: 12 };
// The pane's size until herdr reports it (and under `herdr-app check`, which lays nothing out).
export const PANE_DEFAULT = { width: 950, height: 300 };
// Heights in px: the bubble's padding and border, its two heading rows with their gaps,
// the rule over the log, a log row, a line of the message, and the gap between parts.
const FRAME = 22;
const HEAD = 44;
const RULE = 7;
const LOG_ROW = 18;
const SPEECH_ROW = 20;
const GAP = 6;
const MIN_SPEECH_ROWS = 3;
const CHAR_W = 6.6;

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

// The scene as tall as the pane, unless that leaves the bubble under `minText` wide: then
// the scene gives way, and below `minScale` the bubble goes and the scene has the pane.
export function paneLayout(width, height) {
  const w = Math.max(0, width - 2 * PANE.pad);
  const h = Math.max(0, height - 2 * PANE.pad);
  const byHeight = h / SCENE.h;
  let text = true;
  let scale = Math.min(byHeight, (w - PANE.gap - PANE.minText) / SCENE.w);
  if (scale < PANE.minScale) {
    text = false;
    scale = Math.min(byHeight, w / SCENE.w);
  }
  scale = clamp(scale, 0.1, PANE.maxScale);
  const sceneW = SCENE.w * scale;
  const sceneH = SCENE.h * scale;
  return {
    scale,
    sceneW,
    sceneH,
    text,
    textW: text ? w - PANE.gap - sceneW : 0,
    textH: h,
    // The bubble's tail, from its top, at the height of the chef's face.
    tailTop: clamp((h - sceneH) / 2 + 82 * scale - 10, 12, Math.max(12, h - 32)),
  };
}

// How a bubble `textW` by `textH` shares its height: as many of the `logCount` log lines as
// fit under a message of at least three lines, and the message's cut (lines and characters).
export function bubbleRows(textW, textH, logCount = PANE.logMax) {
  const body = textH - FRAME - HEAD;
  const fit = Math.floor((body - MIN_SPEECH_ROWS * SPEECH_ROW - GAP - RULE) / LOG_ROW);
  const log = clamp(Math.min(fit, logCount), 0, PANE.logMax);
  const left = body - (log ? log * LOG_ROW + RULE + GAP : 0);
  const lines = clamp(Math.floor(left / SPEECH_ROW), 1, 12);
  const perLine = Math.max(20, Math.floor((textW - FRAME) / CHAR_W));
  return { log, lines, chars: lines * perLine };
}
