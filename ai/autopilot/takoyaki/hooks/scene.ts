// The kitchen: a pixel scene of an octopus chef and a takoyaki pan, packed
// into Raster cells two pixels per cell (upper and lower half blocks).

export const COLUMNS = 40
export const ROWS = 6
const W = COLUMNS
const H = ROWS * 2

export type BallState = 'raw' | 'cooking' | 'ready' | 'capped' | 'burnt' | 'stalled'
export type Ball = { key: string; state: BallState; ageMin: number }

export type Mood =
  | 'idle'
  | 'busy'
  | 'doze'
  | 'sleep'
  | 'flip'
  | 'pour'
  | 'happy'
  | 'sad'
  | 'worried'
  | 'surprised'
  | 'serve'

export type Particle = {
  x: number
  y: number
  vx: number
  vy: number
  color: number
  life: number
}

export type Scene = {
  t: number // ms
  mood: Mood
  balls: Ball[]
  holes: number
  isWorking: boolean
  focus: number // hole the chef is working on, -1 for none
  particles: Particle[]
}

const DEFAULT = 0x01000000
const NONE = -1

const C = {
  body: 0xe8585e,
  shade: 0xb83a44,
  flush: 0xc8303c,
  band: 0xf5f1e8,
  eye: 0xffffff,
  pupil: 0x1a1a1a,
  blush: 0xff9aa8,
  mouth: 0x7a1e2a,
  tear: 0x6ab0ff,
  pick: 0xd9b38c,
  pan: 0x4a4a4e,
  panDark: 0x2e2e32,
  hole: 0x18181a,
  flame1: 0xff7a1a,
  flame2: 0xffd23f,
  batter: 0xf2e2b0,
  batterEdge: 0xdcc58a,
  golden: 0xb5692b,
  goldenEdge: 0x8f4f1e,
  sauce: 0x4a2410,
  mayo: 0xfff8e8,
  aonori: 0x4c8a2a,
  burnt: 0x3a2418,
  burntTop: 0x1d120c,
  cold: 0x9a8f78,
  coldEdge: 0x7a705c,
}

export const PALETTE = {
  steam: 0xdedede,
  smoke: 0x6a6a6a,
  sparkle: 0xfff27a,
  heart: 0xff6b9a,
  ink: 0x3b2a5a,
  batter: C.batter,
  zzz: 0xbfd7ff,
  bang: 0xffd23f,
}

// Body, rows 0..6 of the sprite; tentacles below come in two frames.
const HEAD = [
  '   DRRRRD   ',
  '  WWWWWWWWW ',
  ' RRRRRRRRRR ',
  ' RRRRRRRRRR ',
  ' R..RRRR..R ',
  ' R.RR..RR.R ',
  '  RRRRRRRR  ',
]
const LEGS = [
  [' R R RR R R ', 'R  R  R  R R'],
  [' R R RR R R ', ' R  R  R R  '],
]

export const holeX = (i: number) => 16 + i * 4

const mix = (a: number, b: number, k: number) => {
  const f = Math.max(0, Math.min(1, k))
  const ch = (s: number) =>
    Math.round(((a >> s) & 255) * (1 - f) + ((b >> s) & 255) * f) << s
  return ch(16) | ch(8) | ch(0)
}

export function paint(scene: Scene): Uint32Array {
  const px = new Int32Array(W * H).fill(NONE)
  const set = (x: number, y: number, c: number) => {
    const ix = Math.round(x)
    const iy = Math.round(y)
    if (ix >= 0 && ix < W && iy >= 0 && iy < H) px[iy * W + ix] = c
  }

  drawPan(scene, set)
  drawChef(scene, set)
  for (const p of scene.particles) set(p.x, p.y, p.color)

  return pack(px)
}

function drawPan(scene: Scene, set: (x: number, y: number, c: number) => void) {
  const { t, holes, balls, isWorking } = scene
  for (let x = 15; x < W; x++) {
    set(x, 8, C.pan)
    set(x, 9, C.pan)
    set(x, 10, C.panDark)
  }
  for (let i = 0; i < holes; i++) {
    const hx = holeX(i)
    const ball = balls[i]
    if (!ball) {
      for (let dx = 0; dx < 3; dx++) set(hx + dx, 8, C.hole)
      continue
    }
    const [top, mid, edge] = ballColors(ball, t)
    set(hx, 7, edge)
    set(hx + 1, 7, top)
    set(hx + 2, 7, edge)
    set(hx, 8, edge)
    set(hx + 1, 8, mid)
    set(hx + 2, 8, edge)
  }
  // Flames: always a low simmer, roaring while the orchestrator works.
  for (let x = 16; x < W - 1; x += 2) {
    const flicker = Math.floor(t / 120 + x * 7) % 5
    if (!isWorking && flicker > 1) continue
    set(x, 11, flicker % 2 === 0 ? C.flame2 : C.flame1)
  }
}

function ballColors(ball: Ball, t: number): [number, number, number] {
  switch (ball.state) {
    case 'raw':
      return [C.batter, C.batter, C.batterEdge]
    case 'cooking': {
      const done = mix(0xf0c870, 0xc88636, ball.ageMin / 25)
      return [done, done, mix(done, 0x000000, 0.2)]
    }
    case 'ready':
      return [Math.floor(t / 700) % 2 ? C.mayo : C.sauce, C.golden, C.goldenEdge]
    case 'capped':
      return [C.aonori, C.golden, C.goldenEdge]
    case 'burnt':
      return [C.burntTop, C.burnt, C.burntTop]
    case 'stalled':
      return [C.cold, C.cold, C.coldEdge]
  }
}

function drawChef(scene: Scene, set: (x: number, y: number, c: number) => void) {
  const { t, mood } = scene
  const fast = mood === 'busy' || mood === 'flip' || mood === 'happy' || mood === 'serve'
  const still = mood === 'sleep' || mood === 'doze'
  const bob = still ? 0 : Math.floor(t / (fast ? 220 : 650)) % 2
  const ox = 1
  const oy = 1 + bob
  const body = mood === 'sad' || mood === 'worried' ? C.flush : C.body

  HEAD.forEach((row, y) => {
    for (let x = 0; x < row.length; x++) {
      const ch = row[x]
      if (ch === 'R' || ch === '.') set(ox + x, oy + y, body)
      else if (ch === 'D') set(ox + x, oy + y, C.shade)
      else if (ch === 'W') set(ox + x, oy + y, C.band)
    }
  })
  // The headband's knot flutters behind the head.
  set(ox + 11, oy + 1 + (Math.floor(t / 300) % 2), C.band)

  drawFace(scene, set, ox, oy)

  const legs = LEGS[Math.floor(t / (fast ? 180 : 500)) % 2]!
  legs.forEach((row, y) => {
    for (let x = 0; x < row.length; x++) {
      if (row[x] === 'R') set(ox + x, oy + 7 + y, body)
    }
  })

  // One long arm reaches over the pan with a pick while cooking.
  const reaching = mood === 'flip' || mood === 'pour' || mood === 'busy' || mood === 'serve'
  if (reaching && scene.focus >= 0) {
    const hx = holeX(scene.focus) + 1
    const dip = Math.floor(t / 250) % 2
    for (let x = ox + 11; x < hx; x++) set(x, oy + 5, body)
    set(hx, oy + 5, body)
    set(hx, 5 + dip, C.pick)
    set(hx, 6 + dip, C.pick)
  }
}

function drawFace(
  scene: Scene,
  set: (x: number, y: number, c: number) => void,
  ox: number,
  oy: number,
) {
  const { t, mood } = scene
  const blink = Math.floor(t / 100) % 40 === 0
  const eyes: [number, number][] = [
    [ox + 2, oy + 4],
    [ox + 8, oy + 4],
  ]
  for (const [x, y] of eyes) {
    if (mood === 'sleep' || mood === 'doze' || blink) {
      set(x, y, C.shade)
      set(x + 1, y, C.shade)
    } else if (mood === 'happy' || mood === 'serve') {
      // Squeezed-shut happy eyes, a little higher.
      set(x, y - 1, C.pupil)
      set(x + 1, y - 1, C.pupil)
    } else if (mood === 'surprised') {
      set(x, y, C.eye)
      set(x + 1, y, C.eye)
      set(x, y - 1, C.pupil)
    } else {
      const look = mood === 'flip' || mood === 'pour' || mood === 'busy' ? 1 : 0
      set(x, y, look ? C.eye : C.pupil)
      set(x + 1, y, look ? C.pupil : C.eye)
    }
  }
  // Blush, or tears when things burn.
  if (mood === 'sad') {
    set(ox + 2, oy + 5 + (Math.floor(t / 200) % 2), C.tear)
    set(ox + 9, oy + 5 + (Math.floor(t / 200 + 1) % 2), C.tear)
  } else {
    set(ox + 2, oy + 5, C.blush)
    set(ox + 9, oy + 5, C.blush)
  }
  const open = mood === 'happy' || mood === 'surprised' || mood === 'serve'
  set(ox + 5, oy + 5, C.mouth)
  set(ox + 6, oy + 5, C.mouth)
  if (open) set(ox + 5, oy + 6, C.mouth)
}

function pack(px: Int32Array): Uint32Array {
  const words = new Uint32Array(COLUMNS * ROWS * 3)
  for (let r = 0; r < ROWS; r++) {
    for (let x = 0; x < W; x++) {
      const top = px[2 * r * W + x]!
      const bot = px[(2 * r + 1) * W + x]!
      const i = (r * COLUMNS + x) * 3
      if (top === NONE && bot === NONE) {
        words.set([0x20, DEFAULT, DEFAULT], i)
      } else if (top === NONE) {
        words.set([0x2584, bot, DEFAULT], i)
      } else if (bot === NONE) {
        words.set([0x2580, top, DEFAULT], i)
      } else {
        words.set([0x2580, top, bot], i)
      }
    }
  }
  return words
}

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'

// Raster cells as padded base64 of the little-endian words.
export function encode(words: Uint32Array): string {
  const bytes = new Uint8Array(words.length * 4)
  const view = new DataView(bytes.buffer)
  words.forEach((w, i) => view.setUint32(i * 4, w, true))
  let out = ''
  for (let i = 0; i < bytes.length; i += 3) {
    const a = bytes[i]!
    const b = bytes[i + 1]
    const c = bytes[i + 2]
    const n = (a << 16) | ((b ?? 0) << 8) | (c ?? 0)
    out += B64[(n >> 18) & 63]! + B64[(n >> 12) & 63]!
    out += b === undefined ? '=' : B64[(n >> 6) & 63]!
    out += c === undefined ? '=' : B64[n & 63]!
  }
  return out
}

// Moves particles on by `dt` ms and drops the spent ones.
export function step(particles: Particle[], dt: number): Particle[] {
  const s = dt / 1000
  return particles
    .map(p => ({ ...p, x: p.x + p.vx * s, y: p.y + p.vy * s, life: p.life - dt }))
    .filter(p => p.life > 0 && p.y > -1 && p.y < H + 1)
}
