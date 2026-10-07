// Tecla in pixels: the character maps of art.ts turned into Raster cells,
// half blocks (each terminal cell two stacked pixels), the pose timelines,
// the pixel bookshelf, and the one-line kaomoji for where pixels don't fit.

import { ART } from './art'

export type Mood =
  | 'idle' // standing by the shelf, blinking
  | 'reading' // the agent works: she reads along
  | 'stamping' // a new document arrived: she stamps it
  | 'ladder' // the agent searches: she looks around with a magnifier
  | 'puzzled' // a contradiction, an error, a failed validation
  | 'happy' // validation passed, a document reviewed, a turn done
  | 'sleepy' // nothing happened for a while
  | 'lookup' // the agent needs Òscar

export const MOODS: readonly Mood[] = ['idle', 'reading', 'stamping', 'ladder', 'puzzled', 'happy', 'sleepy', 'lookup']

export type Size = 'full' | 'mini'
export type Pixels = readonly string[]

type FrameDef = { readonly rows: readonly string[] } | { readonly from: string; readonly patch: Readonly<Record<string, string>> }
type Art = {
  readonly palette: Readonly<Record<string, string>>
  readonly full: Readonly<Record<string, FrameDef>>
  readonly mini: Readonly<Record<string, FrameDef>>
  readonly poses: Readonly<Record<Mood, readonly (readonly [string, number])[]>>
}
const art: Art = ART

// A cell's colour as Raster takes it: 0x00RRGGBB, or bit 24 alone for the
// terminal's default (what a transparent pixel shows: the band's background).
export const DEFAULT_COLOR = 0x01000000
const UPPER_HALF = 0x2580 // ▀
const LOWER_HALF = 0x2584 // ▄
const SPACE = 0x20

export const rgb = (hex: string) => parseInt(hex.slice(1, 7), 16)

export type Palette = Readonly<Record<string, string>>
export const PALETTE: Palette = art.palette

// --- Frames -----------------------------------------------------------------

function resolve(size: Size, name: string, depth = 0): string[] {
  const def = art[size][name]
  if (!def || depth > 8) throw new Error(`no frame ${size}/${name}`)
  if ('rows' in def) return [...def.rows]
  const rows = resolve(size, def.from, depth + 1)
  for (const [i, row] of Object.entries(def.patch)) rows[Number(i)] = row
  return rows
}

const cache = new Map<string, Pixels>()
export function frame(size: Size, name: string): Pixels {
  const key = `${size}/${name}`
  let got = cache.get(key)
  if (!got) {
    got = resolve(size, name)
    cache.set(key, got)
  }
  return got
}

export const frameNames = (size: Size) => Object.keys(art[size])

// Pixel size of each sprite, and the terminal cells it takes.
export const SPRITE = {
  full: { width: frame('full', 'idle')[0]!.length, height: frame('full', 'idle').length },
  mini: { width: frame('mini', 'idle')[0]!.length, height: frame('mini', 'idle').length },
}
export const cellsOf = (size: Size) => ({ columns: SPRITE[size].width, rows: Math.ceil(SPRITE[size].height / 2) })

// --- Timelines --------------------------------------------------------------

export const timeline = (mood: Mood) => art.poses[mood]
const length = (mood: Mood) => timeline(mood).reduce((n, [, ms]) => n + ms, 0)

// The step a pose is at `phase` ms after it started, looping.
export function stepAt(mood: Mood, phase: number): { index: number; name: string } {
  const steps = timeline(mood)
  let t = ((phase % length(mood)) + length(mood)) % length(mood)
  for (let i = 0; i < steps.length; i++) {
    const [name, ms] = steps[i]!
    if (t < ms) return { index: i, name }
    t -= ms
  }
  return { index: 0, name: steps[0]![0] }
}

// --- Pixels to Raster cells --------------------------------------------------

// Pairs of pixel rows -> one row of half-block cells, row-major, each cell
// [codePoint, foreground, background]: ▀ over two colours, ▀ or ▄ over the
// default background where one half is transparent, a space where both are.
export function toWords(pixels: Pixels, palette: Palette = PALETTE): Uint32Array {
  const width = pixels.reduce((n, r) => Math.max(n, r.length), 0)
  const rows = Math.ceil(pixels.length / 2)
  const words = new Uint32Array(width * rows * 3)
  const color = (ch: string | undefined): number | undefined => {
    if (ch === undefined || ch === '.' || ch === ' ') return undefined
    const hex = palette[ch]
    if (!hex) throw new Error(`no colour for pixel '${ch}'`)
    return rgb(hex)
  }
  for (let y = 0; y < rows; y++) {
    const top = pixels[2 * y] ?? ''
    const bottom = pixels[2 * y + 1] ?? ''
    for (let x = 0; x < width; x++) {
      const t = color(top[x])
      const b = color(bottom[x])
      const at = (y * width + x) * 3
      if (t === undefined && b === undefined) words.set([SPACE, DEFAULT_COLOR, DEFAULT_COLOR], at)
      else if (b === undefined) words.set([UPPER_HALF, t!, DEFAULT_COLOR], at)
      else if (t === undefined) words.set([LOWER_HALF, b, DEFAULT_COLOR], at)
      else words.set([UPPER_HALF, t, b], at)
    }
  }
  return words
}

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'

// Little-endian u32s, standard padded base64: what RasterProps.cells takes.
export function encodeWords(words: Uint32Array): string {
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

export function decodeCells(cells: string): Uint32Array {
  const clean = cells.replace(/=+$/, '')
  const bytes = new Uint8Array(Math.floor((clean.length * 3) / 4))
  let bits = 0
  let acc = 0
  let o = 0
  for (const ch of clean) {
    acc = (acc << 6) | B64.indexOf(ch)
    bits += 6
    if (bits >= 8) {
      bits -= 8
      bytes[o++] = (acc >> bits) & 0xff
    }
  }
  const view = new DataView(bytes.buffer)
  const words = new Uint32Array(bytes.length / 4)
  for (let i = 0; i < words.length; i++) words[i] = view.getUint32(i * 4, true)
  return words
}

// --- The bookshelf ------------------------------------------------------------

export const SHELF_W = 10
const DEFAULT_BOOKS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#b0449f']
const WOOD = '#8b5a2b'
const BACK = '#4a3324'

// Four shelves of books in the tree's branch colours, as pixels with a
// palette of their own (digits for the books).
export function shelf(books: readonly string[], height: number): { pixels: string[]; palette: Palette } {
  const valid = books.filter(c => /^#[0-9a-f]{6}$/i.test(c))
  const colors = (valid.length > 0 ? valid : DEFAULT_BOOKS).slice(0, 10)
  const palette: Record<string, string> = { '#': WOOD, '_': BACK }
  colors.forEach((c, i) => (palette[String(i)] = c))
  const inner = SHELF_W - 2
  const tiers = 4
  const tierH = Math.floor((height - 2) / tiers) // books and a plank
  // Each tier's books: a colour (never the same as its neighbour's), short
  // ones with a gap above them, and one empty slot.
  const tierBooks = (s: number) => {
    let prev = -1
    return Array.from({ length: inner }, (_, x) => {
      const hash = (s * 31 + x * 17 + 7) % 97
      let color = hash % colors.length
      if (color === prev && colors.length > 1) color = (color + 1) % colors.length
      prev = color
      return { color: String(color), isShort: hash % 3 === 0, isEmpty: x === (s * 3 + 2) % inner }
    })
  }
  const rows: string[] = ['#'.repeat(SHELF_W)]
  for (let s = 0; s < tiers; s++) {
    const books = tierBooks(s)
    for (let y = 0; y < tierH - 1; y++) {
      const row = books.map(b => (b.isEmpty || (b.isShort && y === 0) ? '_' : b.color)).join('')
      rows.push(`#${row}#`)
    }
    rows.push('#'.repeat(SHELF_W))
  }
  // What's left is the plinth.
  while (rows.length < height) rows.push('#'.repeat(SHELF_W))
  return { pixels: rows.slice(0, height), palette }
}

// --- The kaomoji ----------------------------------------------------------------

const KAOMOJI: Record<Mood, [string, string]> = {
  idle: ['(◕‿◕)', '(-‿-)'],
  reading: ['(ᵕ‿ᵕ)📖', '(ᵕ‿ᵕ)📖'],
  stamping: ['(>ᴗ<)ノ▀', '(>ᴗ<)ノ▄'],
  ladder: ['(◕ᴗ◕)🔍', '(◕‿◕)🔍'],
  puzzled: ['(•_•)?', '(•_•) ?'],
  happy: ['(^▽^)✧', '✧(^▽^)'],
  sleepy: ['(-ω-)z', '(-ω-)zZ'],
  lookup: ['(◕o◕)!', '(◕o◕)ノ'],
}

export const kaomoji = (mood: Mood, phase: number) => KAOMOJI[mood][stepAt(mood, phase).index % 2]!
