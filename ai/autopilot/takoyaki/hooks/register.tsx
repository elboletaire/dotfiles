import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { LogLine } from '../types'
import { newEvents, react, readKitchen } from './feed'
import type { AutopilotEvent, Kitchen, Reaction } from './feed'
import { COLUMNS, PALETTE, ROWS, encode, holeX, paint, step } from './scene'
import type { Mood, Particle, Scene } from './scene'

const ORCH_AGENT = 'autopilot' // scan.py's ORCH_AGENT
const RASTER = 'kitchen'
const FRAME_MS = 100
const POLL_MS = 1000
const DOZE_MS = 10 * 60 * 1000
const LOG_LINES = 5
// herdr names the agent only once it has seen claude start, which can land
// after session.start: keep asking for this long.
const DETECT_MS = 2000
const DETECT_TRIES = 15

const isActive = atom({ plugin: 'autopilot-takoyaki', key: 'isActive' } as const, false)
const log = atom({ plugin: 'autopilot-takoyaki', key: 'log' } as const, [] as LogLine[])
const header = atom({ plugin: 'autopilot-takoyaki', key: 'header' } as const, '')

// The order of events `/takoyaki demo` plays, one every DEMO_MS.
const DEMO_MS = 2500
const DEMO: Omit<AutopilotEvent, 'at'>[] = [
  { kind: 'tick', active: 0 },
  { kind: 'spawn', key: 'demo/app#101', title: 'Fix login redirect' },
  { kind: 'spawn', key: 'demo/app#102', title: 'Add dark mode' },
  { kind: 'sent', key: 'demo/app#101', text: 'work on the issue' },
  { kind: 'heartbeat', key: 'demo/app#102', note: 'tests' },
  { kind: 'report', key: 'demo/app#101', state: 'ready', msg: 'PR open, CI green' },
  { kind: 'request', text: 'go demo/lib#7' },
  { kind: 'spawn', key: 'demo/lib#7', title: 'Bump deps' },
  { kind: 'report', key: 'demo/app#102', state: 'failed', msg: 'tests are red' },
  { kind: 'round', key: 'demo/app#102', round: 2 },
  { kind: 'report', key: 'demo/lib#7', state: 'stalled' },
  { kind: 'merged', key: 'demo/app#101' },
  { kind: 'pause' },
  { kind: 'resume' },
]

// Module state: a reload starts it over, which only restarts the animation;
// whether the kitchen is open and its log live in $.state.
const k = {
  active: false,
  bandId: undefined as string | undefined,
  kitchen: { balls: [], boxed: [], paused: false, holes: 6 } as Kitchen,
  mood: 'idle' as Mood,
  moodUntil: 0,
  focus: -1,
  particles: [] as Particle[],
  isWorking: false,
  lastActivity: Date.now(),
  lastFrame: Date.now(),
  cursor: { at: 0, seen: [] as string[] },
  mtimes: { state: 0, events: 0, snapshot: 0 },
  stateDir: '',
  demo: undefined as { step: number; balls: Kitchen['balls'] } | undefined,
  isBlitting: false,
}

const now = () => Date.now()

const holeOf = (key?: string) => (key ? k.kitchen.balls.findIndex(b => b.key === key) : -1)

function burst(kind: NonNullable<Reaction['burst']>, hole: number) {
  const x = hole >= 0 ? holeX(hole) + 1 : 6
  const y = hole >= 0 ? 6 : 1
  const n = kind === 'zzz' || kind === 'bang' ? 3 : 6
  const add = (p: Particle) => k.particles.push(p)
  for (let i = 0; i < n; i++) {
    const spread = (Math.random() - 0.5) * 3
    switch (kind) {
      case 'batter':
        add({ x: x + (i % 3) - 1, y: -i, vx: 0, vy: 9, color: PALETTE.batter, life: 900 })
        break
      case 'zzz':
        add({ x: 11 + i, y: 2 - i, vx: 1.5, vy: -1.2, color: PALETTE.zzz, life: 2500 })
        break
      case 'bang':
        add({ x: 13, y: 1 + i, vx: 0, vy: 0, color: PALETTE.bang, life: i === 2 ? 900 : 1500 })
        break
      case 'ink':
        add({ x: 4 + spread, y: 9, vx: spread * 2, vy: -1 - Math.random() * 2, color: PALETTE.ink, life: 1500 })
        break
      case 'heart':
        add({ x: x + spread, y, vx: spread, vy: -3 - Math.random() * 2, color: PALETTE.heart, life: 2200 })
        break
      case 'sparkle':
        add({ x: x + spread * 2, y: y - Math.random() * 3, vx: 0, vy: -1, color: PALETTE.sparkle, life: 300 + i * 250 })
        break
      case 'smoke':
        add({ x: x + spread, y, vx: spread * 0.5, vy: -2.5, color: PALETTE.smoke, life: 2500 })
        break
      case 'steam':
        if (i < 2) add({ x: x + spread, y, vx: 0, vy: -2, color: PALETTE.steam, life: 1600 })
        break
    }
  }
}

function resting(): Mood {
  if (k.kitchen.paused) return 'sleep'
  if (k.isWorking) return 'busy'
  if (now() - k.lastActivity > DOZE_MS) return 'doze'
  return 'idle'
}

function frame(): Scene {
  const t = now()
  if (t > k.moodUntil) k.mood = resting()
  const cooking = k.kitchen.balls.length
  if (k.focus < 0 || k.focus >= cooking) k.focus = cooking > 0 ? 0 : -1
  // A busy chef works its way along the pan.
  if (k.mood === 'busy' && cooking > 0) k.focus = Math.floor(t / 1200) % cooking
  return {
    t,
    mood: k.mood,
    balls: k.kitchen.balls,
    boxed: k.kitchen.boxed,
    holes: k.kitchen.holes,
    isWorking: k.isWorking,
    focus: k.focus,
    particles: k.particles,
  }
}

async function apply($: EngineInterface, events: AutopilotEvent[], isReplay: boolean) {
  const lines: LogLine[] = []
  for (const ev of events) {
    const r = react(ev)
    if (r.line) lines.push(r.line)
    if (isReplay) continue
    k.lastActivity = now()
    if (r.ms > 0) {
      k.mood = r.mood
      k.moodUntil = now() + r.ms
    }
    const hole = holeOf(r.key)
    if (hole >= 0) k.focus = hole
    if (r.burst) burst(r.burst, hole)
  }
  if (lines.length > 0) await update($, log, list => [...list, ...lines].slice(-LOG_LINES))
}

async function refreshHeader($: EngineInterface) {
  const { balls, boxed, holes, paused } = k.kitchen
  const served = boxed.length > 0 ? ` · ${boxed.length} on the shelf` : ''
  const label = `${served}${paused ? ' · paused' : ''}${k.demo ? ' · demo' : ''}`
  await update($, header, () => `🐙 takoyaki kitchen · ${balls.length}/${holes} on the pan${label}`)
}

async function pollFiles($: EngineInterface) {
  if (!k.active || k.demo) return
  const stateFile = `${k.stateDir}/state.json`
  const eventsFile = `${k.stateDir}/events.jsonl`

  // The snapshot says which items are done (READY, CAPPED, DONE), so a new
  // one moves them onto the shelf even when state.json did not change.
  const snapFile = `${k.stateDir}/snapshot.json`
  const s = await $.fs.stat(stateFile).catch(() => undefined)
  const sn = await $.fs.stat(snapFile).catch(() => undefined)
  if ((s && s.mtimeMs !== k.mtimes.state) || (sn && sn.mtimeMs !== k.mtimes.snapshot)) {
    k.mtimes.state = s?.mtimeMs ?? 0
    k.mtimes.snapshot = sn?.mtimeMs ?? 0
    const snapshot = await $.fs.read(snapFile).catch(() => '')
    const maxActive = Number(/"max_active":\s*(\d+)/.exec(snapshot)?.[1]) || 6
    const stateText = await $.fs.read(stateFile).catch(() => '')
    k.kitchen = readKitchen(stateText, now() / 1000, maxActive, snapshot)
    await refreshHeader($)
  }

  const ev = await $.fs.stat(eventsFile).catch(() => undefined)
  if (ev && ev.mtimeMs !== k.mtimes.events) {
    const isReplay = k.mtimes.events === 0
    k.mtimes.events = ev.mtimeMs
    const found = newEvents(await $.fs.read(eventsFile), k.cursor)
    k.cursor = found.cursor
    // On first sight, fill the log with the latest events without
    // replaying their animations.
    await apply($, isReplay ? found.events.slice(-LOG_LINES) : found.events, isReplay)
  }
}

async function playDemo($: EngineInterface) {
  const demo = k.demo
  if (!demo) return
  const ev = { ...DEMO[demo.step % DEMO.length]!, at: Math.floor(now() / 1000) } as AutopilotEvent
  demo.step += 1
  const key = ev.key
  if (ev.kind === 'tick') demo.balls = []
  if (ev.kind === 'spawn' && key) demo.balls.push({ key, state: 'raw', ageMin: 0 })
  if (ev.kind === 'sent' || ev.kind === 'heartbeat' || ev.kind === 'round') {
    for (const b of demo.balls) if (b.key === key) b.state = 'cooking'
  }
  if (ev.kind === 'report') {
    const st = String(ev.state)
    const next = st === 'ready' ? 'ready' : st === 'stalled' ? 'stalled' : 'burnt'
    for (const b of demo.balls) if (b.key === key) b.state = next
  }
  if (ev.kind === 'merged') demo.balls = demo.balls.filter(b => b.key !== key)
  // Only done ones are served onto the shelf, as in the real kitchen.
  k.kitchen = {
    balls: demo.balls.filter(b => b.state !== 'done'),
    boxed: demo.balls.filter(b => b.state === 'done'),
    paused: ev.kind === 'pause',
    holes: 6,
  }
  await refreshHeader($)
  await apply($, [ev], false)
}

async function animate($: EngineInterface) {
  const bandId = k.bandId
  if (!k.active || !bandId || k.isBlitting) return
  const t = now()
  k.particles = step(k.particles, t - k.lastFrame)
  k.lastFrame = t
  // Ambient steam off whatever is cooking.
  if (k.kitchen.balls.length > 0 && Math.random() < 0.04) {
    burst('steam', Math.floor(Math.random() * k.kitchen.balls.length))
  }
  k.isBlitting = true
  try {
    const res = await $.ui.blit({ requestId: bandId, key: RASTER, cells: encode(paint(frame())) })
    if ('deny' in res && res.deny) k.bandId = undefined
  } finally {
    k.isBlitting = false
  }
}

async function activate($: EngineInterface, isOn: boolean) {
  k.active = isOn
  await update($, isActive, () => isOn)
  if (isOn) {
    k.lastActivity = now()
    await refreshHeader($)
    await pollFiles($)
  }
}

async function isOrchestrator($: EngineInterface) {
  const pane = await $.env.get('HERDR_PANE_ID')
  if (!pane) return false
  const got = await $.process
    .run(['herdr', 'agent', 'get', pane], { timeoutMs: 5000 })
    .catch(() => undefined)
  if (!got || got.exitCode !== 0) return false
  try {
    const data = JSON.parse(got.stdout) as { result?: { agent?: { name?: string } } }
    return data.result?.agent?.name === ORCH_AGENT
  } catch {
    return false
  }
}

async function detectOrchestrator($: EngineInterface) {
  for (let i = 0; i < DETECT_TRIES && !k.active; i++) {
    if (await isOrchestrator($)) return activate($, true)
    await $.clock.sleep(DETECT_MS)
  }
}

const tone = (l: LogLine) => (l.tone === 'good' ? 'green' : l.tone === 'bad' ? 'red' : undefined)

const clock = (at: number) => {
  const d = new Date(at * 1000)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const home = (await $.env.get('HOME')) ?? ''
    const xdg = (await $.env.get('XDG_STATE_HOME')) || `${home}/.local/state`
    k.stateDir = (await $.env.get('AUTOPILOT_STATE_DIR')) || `${xdg}/pr-autopilot`

    await $.command.register({
      name: 'takoyaki',
      description: 'Toggle the autopilot takoyaki kitchen above the prompt (`demo` plays sample events)',
    })

    $.clock.every(FRAME_MS, () => void animate($))
    $.clock.every(POLL_MS, () => void pollFiles($))
    $.clock.every(DEMO_MS, () => void playDemo($))

    // A reload keeps the session's state: pick the kitchen up where it was.
    if (await read($, isActive)) await activate($, true)
    else void detectOrchestrator($)

    return next(e)
  })

  on('command.run', { command: 'takoyaki' }, async ($, e) => {
    if ((e.args ?? '').trim() === 'demo') {
      k.demo = k.demo ? undefined : { step: 0, balls: [] }
      if (!k.demo) {
        k.mtimes = { state: 0, events: 0, snapshot: 0 }
        k.kitchen = { balls: [], boxed: [], paused: false, holes: 6 }
      }
      await activate($, true)
      return {
        text: k.demo
          ? 'Takoyaki demo started (run `/takoyaki demo` again to stop).'
          : 'Takoyaki demo stopped.',
      }
    }
    const isOn = !(await read($, isActive))
    if (!isOn) k.demo = undefined
    await activate($, isOn)
    return { text: isOn ? 'Takoyaki kitchen open.' : 'Takoyaki kitchen closed.' }
  })

  // The orchestrator's own scan is the surest sign this session drives autopilot.
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    // The skill calls it as `$A <cmd>` with A=.../scan.sh, so accept both spellings.
    if (!k.active && /(autopilot\/scan\.sh|\$A)"?\s+(scan|inbox|doorbell|pause|resume)\b/.test(e.command)) {
      await activate($, true)
    }
    return next(e)
  })

  // Slash commands run through command.run, never prompt.submit.
  on('command.run', { command: 'pr-autopilot' }, async ($, e, next) => {
    if (!k.active) await activate($, true)
    return next(e)
  })

  on('turn.start', ($, e, next) => {
    k.isWorking = true
    k.lastActivity = now()
    return next(e)
  })

  on('turn.complete', ($, e, next) => {
    k.isWorking = false
    k.lastActivity = now()
    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    // Raster is the terminal's alone.
    if (e.surface !== 'terminal' || e.props.hasSurvey || !(await read($, isActive))) {
      k.bandId = undefined
      return next(e)
    }
    k.bandId = e.requestId
    const { Box, Text, Raster } = $.ui.resolve(e)
    const title = await read($, header)
    const lines = await read($, log)
    const cells = encode(paint(frame()))

    if (e.props.bodyColumns < COLUMNS + 30) {
      const last = lines[lines.length - 1]
      return (
        <Box flexDirection="column">
          <Raster key={RASTER} columns={COLUMNS} rows={ROWS} cells={cells} />
          <Text wrap="truncate-end" dimColor>
            {last ? `${clock(last.at)} ${last.text}` : title}
          </Text>
        </Box>
      )
    }

    return (
      <Box flexDirection="row">
        <Raster key={RASTER} columns={COLUMNS} rows={ROWS} cells={cells} />
        <Box flexDirection="column" marginLeft={2} flexGrow={1}>
          <Text bold wrap="truncate-end">
            {title}
          </Text>
          {lines.length > 0 ? (
            lines.map((l, i) => (
              <Text wrap="truncate-end" color={tone(l)} dimColor={i < lines.length - 2}>
                {clock(l.at)} {l.text}
              </Text>
            ))
          ) : (
            <Text dimColor>Waiting for the first order…</Text>
          )}
        </Box>
      </Box>
    )
  })
}
