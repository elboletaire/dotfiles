// Reads Octopilot's state.json and events.jsonl (see ../scan.py) into
// what the kitchen draws: one takoyaki per tracked item, and a reaction
// plus a log line per event.

import type { LogLine } from '../types'
import type { Ball, BallState, Mood } from './scene'

export type OctopilotEvent = {
  at: number
  kind: string
  key?: string
  [field: string]: unknown
}

export type Reaction = {
  mood: Mood
  ms: number
  burst?: 'steam' | 'smoke' | 'sparkle' | 'heart' | 'ink' | 'batter' | 'zzz' | 'bang'
  key?: string // the item the burst rises from
  line?: LogLine
}

// `balls` are on the pan, one per hole; `boxed` are done and out of it.
export type Kitchen = { balls: Ball[]; boxed: Ball[]; paused: boolean; holes: number }

const str = (v: unknown) => (typeof v === 'string' ? v : '')

// Scan rows (snapshot.json) that set a takoyaki's state. Only DONE (nothing
// left for anyone, e.g. someone else's PR we approved) goes on the shelf;
// READY and CAPPED wait for the user, so they stay in the pan, burning.
const DONE_KINDS = new Set(['READY', 'CAPPED', 'DONE'])

function doneKinds(snapshotText: string): Map<string, string> {
  try {
    const rows = (JSON.parse(snapshotText) as { rows?: { kind?: string; key?: string }[] }).rows
    return new Map(
      (rows ?? []).filter(r => r.key && DONE_KINDS.has(r.kind ?? '')).map(r => [r.key!, r.kind!]),
    )
  } catch {
    return new Map()
  }
}

const isDone = (b: Ball) => b.state === 'done'

export function readKitchen(
  stateText: string,
  nowSec: number,
  maxActive = 6,
  snapshotText = '',
): Kitchen {
  let state: Record<string, unknown>
  try {
    state = JSON.parse(stateText) as Record<string, unknown>
  } catch {
    return { balls: [], boxed: [], paused: false, holes: maxActive }
  }
  const done = doneKinds(snapshotText)
  const items = (state.items ?? {}) as Record<string, Record<string, unknown>>
  const all = Object.entries(items)
    .map(([key, item]) => ({ key, item, added: Number(item.added) || 0 }))
    .sort((a, b) => a.added - b.added)
    .map(({ key, item, added }) => ({
      key,
      state: ballState(item, done.get(key)),
      ageMin: added ? Math.max(0, (nowSec - added) / 60) : 0,
    }))

  return {
    balls: all.filter(b => !isDone(b)).slice(0, maxActive),
    boxed: all.filter(isDone),
    paused: state.paused === true,
    holes: maxActive,
  }
}

function ballState(item: Record<string, unknown>, doneKind?: string): BallState {
  if (doneKind === 'READY') return 'ready'
  if (doneKind === 'CAPPED') return 'capped'
  if (doneKind === 'DONE') return 'done'
  const report = (item.last_report ?? {}) as Record<string, unknown>
  switch (str(report.state)) {
    case 'ready':
      return 'ready'
    case 'capped':
      return 'capped'
    case 'blocked':
    case 'failed':
      return 'burnt'
    case 'stalled':
      return 'stalled'
  }
  return item.session ? 'cooking' : 'raw'
}

// New events since the last read. `seen` holds the lines already taken at
// the newest second, so a rewrite of the file (the log is trimmed in place)
// neither replays nor drops anything.
export function newEvents(
  text: string,
  cursor: { at: number; seen: string[] },
): { events: OctopilotEvent[]; cursor: { at: number; seen: string[] } } {
  const events: OctopilotEvent[] = []
  let at = cursor.at
  let seen = cursor.seen
  for (const line of text.split('\n')) {
    if (!line.trim()) continue
    let ev: OctopilotEvent
    try {
      ev = JSON.parse(line) as OctopilotEvent
    } catch {
      continue
    }
    if (typeof ev.at !== 'number' || ev.at < cursor.at) continue
    if (ev.at === cursor.at && cursor.seen.includes(line)) continue
    events.push(ev)
    if (ev.at > at) {
      at = ev.at
      seen = [line]
    } else if (ev.at === at) {
      seen = [...seen, line]
    }
  }
  return { events, cursor: { at, seen } }
}

const short = (key?: string) => (key ? key.replace(/^[^/]+\//, '') : '')

export function react(ev: OctopilotEvent): Reaction {
  const key = ev.key
  const k = short(key)
  const at = ev.at
  const line = (text: string, tone: LogLine['tone'] = 'info'): LogLine => ({ at, text, tone })

  switch (ev.kind) {
    case 'tick': {
      const active = typeof ev.active === 'number' ? ev.active : 0
      return { mood: 'flip', ms: 2500, burst: 'steam', line: line(`tick · ${active} cooking`) }
    }
    case 'spawn':
      return {
        mood: 'pour',
        ms: 2500,
        burst: 'batter',
        key,
        line: line(`new order ${k} ${str(ev.title)}`.trim(), 'good'),
      }
    case 'sent':
      return { mood: 'flip', ms: 1500, key, line: line(`→ ${k} ${str(ev.text)}`.trim()) }
    case 'report': {
      const state = str(ev.state)
      const msg = str(ev.msg)
      const text = `${state} ${k}${msg ? `: ${msg}` : ''}`
      if (state === 'ready') return { mood: 'happy', ms: 4000, burst: 'sparkle', key, line: line(text, 'good') }
      if (state === 'capped') return { mood: 'happy', ms: 3000, burst: 'steam', key, line: line(text) }
      if (state === 'stalled') return { mood: 'worried', ms: 3000, burst: 'smoke', key, line: line(text, 'bad') }
      return { mood: 'sad', ms: 4500, burst: 'smoke', key, line: line(text, 'bad') }
    }
    case 'request':
      return { mood: 'surprised', ms: 2000, burst: 'bang', line: line(`asked: ${str(ev.text)}`) }
    case 'cleanup':
    case 'merged':
      return { mood: 'serve', ms: 3500, burst: 'heart', key, line: line(`served ${k} (merged)`, 'good') }
    case 'pause':
      return { mood: 'sleep', ms: 2000, burst: 'zzz', line: line('paused') }
    case 'resume':
      return { mood: 'surprised', ms: 1500, line: line('resumed') }
    case 'round':
    case 'reviewed':
      return { mood: 'flip', ms: 2000, key, line: line(`review round ${k}`) }
    case 'capped':
      return { mood: 'worried', ms: 2500, key, line: line(`out of review rounds ${k}`, 'bad') }
    case 'feedback':
      return { mood: 'flip', ms: 1500, key, line: line(`feedback ${k}`) }
    case 'heartbeat':
      return { mood: 'idle', ms: 0, burst: 'steam', key }
    case 'reboot':
      return { mood: 'surprised', ms: 2000, burst: 'bang', key, line: line(`reboot ${k}`, 'bad') }
    case 'decline':
    case 'untrack':
    case 'detach':
      return { mood: 'worried', ms: 1500, burst: 'ink', line: line(`${ev.kind} ${k}`) }
    case 'track':
      return { mood: 'pour', ms: 2000, burst: 'batter', key, line: line(`track ${k}`) }
    default:
      return { mood: 'idle', ms: 0, line: line(`${ev.kind} ${k}`.trim()) }
  }
}
