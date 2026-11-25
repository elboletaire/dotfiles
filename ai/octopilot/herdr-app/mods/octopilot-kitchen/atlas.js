// Written by art/make.py: where each piece of the kitchen sits in the scene. Don't edit.
export const SCENE = { w: 360, h: 220 };
export const PAN = { x: 134, w: 216, ballY: 138 };
export const SPRITE = { w: 40, h: 48, cx: 20, cy: 26 };
export const SHELF = { x: 184, rows: [98, 58], pitch: 42, perRow: 4, boat: { w: 38, h: 26, dy: -25 } };
export const ARM_POSES = 6;
export const COOK_STEPS = 5;
// [left, top, width, height] in scene px.
export const BOX = {
  bg: [0, 0, 360, 220],
  shelf: [176, 56, 182, 60],
  counter: [0, 146, 360, 74],
  pan: [120, 124, 244, 76],
  flame: [126, 160, 232, 40],
  chef: [0, 20, 152, 160],
  arm: [90, 30, 266, 146],
};
