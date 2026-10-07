import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { LogLine, Speech, Stats, Tracked } from '../types'
import { diffAgents, inTree, parseAgents, roleOf, trackLine } from './herdr'
import type { Agent, Role } from './herdr'
import { SHELF_W, cellsOf, encodeWords, frame, kaomoji, shelf, stepAt, toWords } from './sprite'
import type { Mood, Size } from './sprite'
import {
  DEFAULT_TREE,
  LOG_FORMAT,
  arbreKeyFromToml,
  arbrePathFromToml,
  diffResearch,
  expandHome,
  parseLog,
  readFamilies,
  readResearch,
  scopeRoot,
  totals,
} from './tree'
import type { Commit, Paths, Research } from './tree'
import {
  GLANCE,
  SLEEP_LINES,
  ambient,
  isValidate,
  onCommit,
  onInvestigation,
  onNotification,
  onResearch,
  onTool,
  onToolError,
  onTurnEnd,
  onTurnStart,
  onValidate,
  pick,
  statsLine,
} from './voice'
import type { Prio, Reaction } from './voice'

// How often the pose is checked for a new frame. Only a new frame is
// painted (a blit of the sprite's cells), so an idle Tecla repaints a few
// times a minute, when she blinks; the shortest step is longer than this.
const FRAME_MS = 125
const POLL_MS = 5000 // tree files: one stat each, a read only on change
const AMBIENT_MS = 3 * 60 * 1000
const SLEEP_MS = 8 * 60 * 1000
const LOG_LINES = 3
// The orchestrator's tracker: one `herdr agent list` every few seconds.
const TRACK_MS = 4000
const GLANCE_ODDS = 0.12 // per poll, while an investigation works and she idles
const ROLE_TRIES = 30 // polls to wait for herdr to list her own agent
const DEMO_MS = 3500
// How long a line holds the bubble against quieter ones, by prio.
const HOLD: Record<Prio, number> = { 0: 4000, 1: 5000, 2: 9000, 3: 14000 }
// Band sizes. The full sprite is 30 x 12 cells, the mini one 20 x 8; the
// shelf (10 cells and a gap) joins her when the band is wide enough.
const FULL = cellsOf('full')
const MINI = cellsOf('mini')
const TEXT_MIN = 24 // the narrowest text column worth drawing
const WIDE = SHELF_W + 1 + FULL.columns + 2 + 44
const SPRITE_KEY = 'sprite'

const isHidden = atom({ plugin: 'arxiu-bibliotecaria', key: 'isHidden' } as const, false)
const speech = atom({ plugin: 'arxiu-bibliotecaria', key: 'speech' } as const, null as Speech | null)
const log = atom({ plugin: 'arxiu-bibliotecaria', key: 'log' } as const, [] as LogLine[])
const stats = atom({ plugin: 'arxiu-bibliotecaria', key: 'stats' } as const, null as Stats | null)
const tracked = atom({ plugin: 'arxiu-bibliotecaria', key: 'tracked' } as const, [] as Tracked[])

// Module state: a reload starts it over and re-reads the tree; what the
// band shows lives in $.state.
const k = {
  root: undefined as string | undefined, // the checkout she follows; undefined: out of scope
  cwd: '',
  tree: '',
  isCommandRegistered: false,
  paths: { people: 'personas', sources: 'fuentes', research: 'investigacion' } as Paths,
  books: [] as string[],
  gitDir: '',
  head: '',
  headMtime: 0,
  mtimes: {} as Record<string, number>,
  texts: {} as Record<string, string>,
  research: undefined as Research | undefined,
  totals: undefined as { people: number; sources: number; last: string } | undefined,
  mood: 'idle' as Mood,
  moodUntil: 0,
  speechPrio: 0 as Prio,
  speechUntil: 0,
  lastSpeech: 0,
  lastActivity: Date.now(),
  isWorking: false,
  isWaitingUser: false,
  isSleepSaid: false,
  isPolling: false,
  isBandShown: false,
  // What the band shows now: the drawing's site, the sprite size (or the
  // kaomoji line), and the frame painted, so a tick paints only a new one.
  requestId: '',
  size: undefined as Size | undefined,
  drawn: '',
  // The pose being played and how far into its timeline, advanced by the
  // frame ticks: a new pose starts at its first step.
  animMood: 'idle' as Mood,
  phase: 0,
  demo: -1,
  // The role: undefined while herdr has not listed her own agent yet (she
  // stays quiet meanwhile). Only the orchestrator, inside herdr, tracks.
  role: undefined as Role | undefined,
  roleTries: 0,
  isHerdr: false,
  ownPane: '',
  orchestrator: 'arbre',
  treeAs: [] as string[], // the tree's spellings, as configured and resolved
  agents: undefined as Agent[] | undefined, // undefined: nothing known (herdr down)
  workingSince: {} as Record<string, number>,
  isTracking: false,
}

const now = () => Date.now()
const rnd = () => Math.random()

const isOrchestrator = () => k.role === 'orchestrator'
const isBlocked = () => (k.agents ?? []).some(a => a.state === 'blocked')

function resting(): Mood {
  // An investigation waiting on Òscar keeps her looking up, awake.
  if (isBlocked()) return 'lookup'
  // Waiting long enough sends her to sleep, even waiting for Òscar.
  if (!k.isWorking && now() - k.lastActivity > SLEEP_MS) return 'sleepy'
  if (k.isWaitingUser) return 'lookup'
  if (k.isWorking) return 'reading'
  return 'idle'
}

// Òscar answered (a permission, a question, a prompt): stop looking up.
function answered() {
  k.isWaitingUser = false
  if (k.mood === 'lookup') k.moodUntil = 0
}

const moodNow = (): Mood => (now() < k.moodUntil ? k.mood : resting())

// The pose and its phase; a mood change restarts the timeline.
function pose(): { mood: Mood; phase: number } {
  const mood = moodNow()
  if (mood !== k.animMood) {
    k.animMood = mood
    k.phase = 0
  }
  return { mood, phase: k.phase }
}

const spriteCells = (size: Size, name: string) => encodeWords(toWords(frame(size, name)))

// One frame tick: paint the sprite again only when its frame changed, in
// place (a blit), or redraw the band where it shows the kaomoji line.
async function animate($: EngineInterface) {
  if (!k.isBandShown) return
  k.phase += FRAME_MS
  const { mood, phase } = pose()
  const size = k.size
  if (!size) {
    const face = kaomoji(mood, phase)
    if (face !== k.drawn) $.ui.invalidate('ui.render')
    return
  }
  const name = stepAt(mood, phase).name
  if (name === k.drawn) return
  k.drawn = name
  const got = await $.ui.blit({ requestId: k.requestId, key: SPRITE_KEY, cells: spriteCells(size, name) })
  if ('deny' in got && got.deny !== undefined) $.ui.invalidate('ui.render')
}

async function say($: EngineInterface, text: string, prio: Prio, isLogged = false) {
  const t = now()
  if (isLogged) await update($, log, list => [...list, { at: t, text }].slice(-LOG_LINES))
  if (prio < k.speechPrio && t < k.speechUntil) return
  k.speechPrio = prio
  k.speechUntil = t + HOLD[prio]
  k.lastSpeech = t
  await update($, speech, prev => (prev?.text === text ? prev : { at: t, text }))
}

async function react($: EngineInterface, r: Reaction | undefined) {
  if (!r) return
  k.lastActivity = now()
  k.isSleepSaid = false
  if (r.ms > 0) {
    k.mood = r.mood
    k.moodUntil = now() + r.ms
  }
  if (r.line) await say($, r.line, r.prio, r.isLogged)
}

// --- Where the tree is, and whether this session is in it --------------

async function treePath($: EngineInterface): Promise<string> {
  const home = (await $.env.get('HOME')) ?? ''
  const config = (await $.env.get('ARXIU_CONFIG')) || `${home}/.dotfiles/ai/arxiu/config.toml`
  const text = await $.fs.read(expandHome(config, home)).catch(() => '')
  k.orchestrator = arbreKeyFromToml(text, 'orchestrator_agent') ?? 'arbre'
  const fromEnv = await $.env.get('ARXIU_TREE')
  if (fromEnv) return expandHome(fromEnv, home)
  return expandHome(arbrePathFromToml(text) ?? DEFAULT_TREE, home)
}

const realPath = async ($: EngineInterface, path: string) =>
  (await $.fs.stat(path, { resolve: true }).catch(() => undefined))?.realPath ?? path

// Re-checked when the session's directory changes (/cd, a worktree move).
async function checkScope($: EngineInterface, cwd: string) {
  if (cwd === k.cwd && k.tree) return
  k.cwd = cwd
  const configured = await treePath($)
  k.tree = await realPath($, configured)
  k.treeAs = [...new Set([configured, k.tree])]
  const root = scopeRoot(await realPath($, cwd), k.tree)
  if (root === k.root) return
  k.root = root
  k.gitDir = ''
  k.head = ''
  k.headMtime = 0
  k.mtimes = {}
  k.research = undefined
  if (!root) {
    $.ui.invalidate('ui.render')
    return
  }
  if (k.role === undefined) await findRole($)
  if (!k.isCommandRegistered) {
    k.isCommandRegistered = true
    await $.command.register({
      name: 'tecla',
      description: 'Show or hide Tecla, the tree\'s archivist, above the prompt (`demo` plays sample events)',
    })
  }
  await loadTree($, root)
}

// --- Reading the tree ----------------------------------------------------

async function git($: EngineInterface, args: string[]): Promise<string | undefined> {
  const root = k.root
  if (!root) return undefined
  const got = await $.process.run(['git', '-C', root, ...args], { timeoutMs: 5000 }).catch(() => undefined)
  return got && got.exitCode === 0 ? got.stdout : undefined
}

async function loadTree($: EngineInterface, root: string) {
  const fam = readFamilies(await $.fs.read(`${root}/families.yml`).catch(() => ''))
  k.paths = fam.paths
  k.books = fam.colors

  // A worktree's .git is a file naming its git dir.
  const dotGit = `${root}/.git`
  const st = await $.fs.stat(dotGit).catch(() => undefined)
  if (st?.kind === 'dir') k.gitDir = dotGit
  else if (st?.kind === 'file') {
    const to = /gitdir:\s*(.+)/.exec(await $.fs.read(dotGit).catch(() => ''))?.[1]?.trim() ?? ''
    k.gitDir = to.startsWith('/') ? to : `${root}/${to}`
  }

  // The last few commits fill the log without a fuss.
  const out = await git($, ['log', '-n', String(LOG_LINES), `--format=${LOG_FORMAT}`, '--name-status', '--no-renames'])
  const commits = out ? parseLog(out, k.paths) : []
  k.head = commits[0]?.hash ?? ''
  k.headMtime = (await $.fs.stat(`${k.gitDir}/logs/HEAD`).catch(() => undefined))?.mtimeMs ?? 0
  await update($, log, () =>
    [...commits].reverse().map(c => ({ at: c.at * 1000, text: onCommit(c, () => 0).line ?? c.subject })),
  )
  await refreshTotals($)
  await pollResearch($, true)
  if (isOrchestrator()) await say($, pick(['Hola, Òscar! Obro l\'arxiu 📚', 'Bon dia! Els lligalls ja són a punt ♥', 'Arxivera de guàrdia! 📚'], rnd), 1)
}

async function refreshTotals($: EngineInterface) {
  const root = k.root
  if (!root) return
  const names = async (dir: string) =>
    (await $.fs.list(`${root}/${dir}`).catch(() => [])).filter(e => e.kind === 'file').map(e => e.name)
  k.totals = totals(await names(k.paths.people), await names(k.paths.sources))
  await writeStats($)
}

async function writeStats($: EngineInterface) {
  const t = k.totals
  const r = k.research
  await update($, stats, () => ({
    people: t?.people ?? 0,
    sources: t?.sources ?? 0,
    last: t?.last ?? '',
    pending: r?.pending ?? 0,
    contradictions: r?.contradictions ?? 0,
    toReview: r?.toReview ?? 0,
  }))
}

const RESEARCH = ['pendientes.md', 'incoherencias.md', 'revision.md'] as const

async function pollResearch($: EngineInterface, isFirst = false) {
  const root = k.root
  if (!root) return
  let isChanged = false
  for (const name of RESEARCH) {
    const path = `${root}/${k.paths.research}/${name}`
    const s = await $.fs.stat(path).catch(() => undefined)
    const m = s?.mtimeMs ?? 0
    if (m === (k.mtimes[path] ?? -1)) continue
    k.mtimes[path] = m
    k.texts[name] = s ? await $.fs.read(path).catch(() => '') : ''
    isChanged = true
  }
  if (!isChanged) return
  const next = readResearch(k.texts['pendientes.md'] ?? '', k.texts['incoherencias.md'] ?? '', k.texts['revision.md'] ?? '')
  const before = k.research
  k.research = next
  await writeStats($)
  if (!isFirst && before) await react($, onResearch(diffResearch(before, next), rnd))
}

async function pollCommits($: EngineInterface) {
  if (!k.gitDir) return
  const s = await $.fs.stat(`${k.gitDir}/logs/HEAD`).catch(() => undefined)
  if (!s || s.mtimeMs === k.headMtime) return
  k.headMtime = s.mtimeMs
  const head = (await git($, ['rev-parse', 'HEAD']))?.trim()
  if (!head || head === k.head) return
  const range = k.head ? `${k.head}..${head}` : head
  const out =
    (await git($, ['log', '-n', '15', `--format=${LOG_FORMAT}`, '--name-status', '--no-renames', range])) ??
    (await git($, ['log', '-n', '1', `--format=${LOG_FORMAT}`, '--name-status', '--no-renames', head]))
  k.head = head
  const commits: Commit[] = out ? parseLog(out, k.paths).reverse() : []
  // Each commit gets its log line; the bubble keeps the loudest, latest one.
  for (const c of commits) await react($, onCommit(c, rnd))
  if (commits.length > 0) await refreshTotals($)
}

async function poll($: EngineInterface) {
  if (!k.root || k.isPolling || k.demo >= 0) return
  k.isPolling = true
  try {
    await pollCommits($)
    await pollResearch($)
  } finally {
    k.isPolling = false
  }
}

async function tick($: EngineInterface) {
  if (!k.root) return
  const t = now()
  const mood = moodNow()
  if (mood === 'sleepy' && !k.isSleepSaid) {
    k.isSleepSaid = true
    await say($, pick(SLEEP_LINES, rnd), 0)
  } else if (isOrchestrator() && mood === 'idle' && t - k.lastSpeech > AMBIENT_MS) {
    await say($, ambient(k.research, k.totals, rnd), 0)
  }
}

// --- The role and the investigations ----------------------------------------

// `herdr agent list`, parsed; undefined when herdr is missing, its server is
// not running or it answers anything else.
async function herdrAgents($: EngineInterface): Promise<Agent[] | undefined> {
  const got = await $.process.run(['herdr', 'agent', 'list'], { timeoutMs: 3000 }).catch(() => undefined)
  return got && got.exitCode === 0 ? parseAgents(got.stdout) : undefined
}

// ARXIU_ROLE, or, inside herdr with none, the name of her own agent.
async function findRole($: EngineInterface, listed?: Agent[]) {
  k.isHerdr = (await $.env.get('HERDR_ENV')) === '1'
  k.ownPane = (await $.env.get('HERDR_PANE_ID')) ?? ''
  const env = await $.env.get('ARXIU_ROLE')
  let own: string | undefined
  if (!env && k.isHerdr) {
    const agents = listed ?? (await herdrAgents($))
    own = agents?.find(a => k.ownPane !== '' && a.pane === k.ownPane)?.name
    k.roleTries += 1
    if (own === undefined && k.roleTries >= ROLE_TRIES) own = ''
  }
  const role = roleOf(env, k.isHerdr, own, k.orchestrator)
  if (role === k.role) return
  k.role = role
  $.ui.invalidate('ui.render')
}

const sinceOf = (a: Agent) => k.workingSince[a.pane || a.name]

// The subject of the agent's last commit since it started working, if any.
async function lastCommit($: EngineInterface, a: Agent): Promise<string | undefined> {
  const since = sinceOf(a)
  if (!since || !a.cwd) return undefined
  const got = await $.process
    .run(['git', '-C', a.cwd, 'log', '-1', `--since=@${Math.floor(since / 1000)}`, '--format=%s'], { timeoutMs: 3000 })
    .catch(() => undefined)
  const subject = got && got.exitCode === 0 ? got.stdout.trim() : ''
  return subject || undefined
}

async function writeTracked($: EngineInterface) {
  const list = (k.agents ?? []).map(a => ({ name: a.name, state: a.state }))
  await update($, tracked, prev =>
    prev.length === list.length && prev.every((p, i) => p.name === list[i]!.name && p.state === list[i]!.state) ? prev : list,
  )
}

// One poll of herdr: the role while it is unknown, then, for the
// orchestrator, what the investigations in the tree did since the last one.
async function track($: EngineInterface) {
  if (!k.root || !k.isHerdr || k.isTracking || k.role === 'research') return
  k.isTracking = true
  try {
    const listed = await herdrAgents($)
    if (k.role === undefined) await findRole($, listed)
    if (!isOrchestrator()) return
    if (!listed) {
      // Nothing known: nothing tracked, nothing said.
      k.agents = undefined
      k.workingSince = {}
      await writeTracked($)
      return
    }
    const ownName = listed.find(a => k.ownPane !== '' && a.pane === k.ownPane)?.name ?? ''
    const next = inTree(listed, k.treeAs, k.ownPane, ownName)
    const before = k.agents
    k.agents = next
    const t = now()
    const keys = new Set(next.map(a => a.pane || a.name))
    for (const key of Object.keys(k.workingSince)) if (!keys.has(key)) delete k.workingSince[key]
    for (const a of next) {
      const key = a.pane || a.name
      if (a.state === 'working' || a.state === 'blocked') k.workingSince[key] ??= t
    }
    await writeTracked($)
    if (before) {
      for (const c of diffAgents(before, next)) {
        const commit = c.kind === 'finished' ? await lastCommit($, c.agent) : undefined
        if (c.kind === 'finished') delete k.workingSince[c.agent.pane || c.agent.name]
        await react($, onInvestigation(c, rnd, commit))
      }
    }
    if (moodNow() === 'idle' && next.some(a => a.state === 'working') && rnd() < GLANCE_ODDS) await react($, GLANCE)
  } finally {
    k.isTracking = false
  }
}

// --- The demo -------------------------------------------------------------

const DEMO_COMMIT: Commit = {
  hash: 'demo',
  at: 0,
  subject: 'feat: recerca dels Fernández Díaz de Figaredo (F392-F399)',
  addedSources: ['F392', 'F393', 'F394', 'F395', 'F396', 'F397', 'F398', 'F399'],
  removedSources: [],
  addedPeople: ['sinforosa-fernandez-diaz'],
}
const DEMO: (() => Reaction | undefined)[] = [
  () => onTurnStart(true, rnd),
  () => onTool({ tool: 'Read', path: 'fuentes/F119.md' }, 'personas', rnd),
  () => onTool({ tool: 'WebSearch' }, 'personas', rnd),
  () => onTool({ tool: 'Write', path: 'fuentes/F399.md' }, 'personas', rnd),
  () => onCommit(DEMO_COMMIT, rnd),
  () => onResearch([{ kind: 'contradiction', label: 'Alonso i Espino', of: 'Fechas', delta: 1 }], rnd),
  () => onTool({ tool: 'Bash', command: 'make validate' }, 'personas', rnd),
  () => onValidate(true, rnd),
  () => onNotification('permission_prompt', rnd),
  () => onTurnEnd('answer', rnd),
  () => ({ mood: 'sleepy', ms: 4000, line: pick(SLEEP_LINES, rnd), prio: 0 }),
]

async function playDemo($: EngineInterface) {
  if (k.demo < 0) return
  const r = DEMO[k.demo % DEMO.length]!()
  k.demo += 1
  k.speechPrio = 0
  k.speechUntil = 0
  await react($, r)
}

// --- Drawing --------------------------------------------------------------

const clock = (at: number) => {
  const d = new Date(at)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

const SPEECH_COLOR = '#e8607e'

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await checkScope($, e.cwd)
    $.clock.every(FRAME_MS, () => void animate($))
    $.clock.every(POLL_MS, () => void poll($))
    $.clock.every(TRACK_MS, () => void track($))
    $.clock.every(15000, () => void tick($))
    $.clock.every(DEMO_MS, () => void playDemo($))
    return next(e)
  })

  on('command.run', { command: 'tecla' }, async ($, e) => {
    if ((e.args ?? '').trim() === 'demo') {
      k.demo = k.demo >= 0 ? -1 : 0
      await update($, isHidden, () => false)
      return { text: k.demo >= 0 ? 'La Tecla fa una demostració (`/tecla demo` per parar).' : 'Demostració acabada.' }
    }
    const hidden = !(await read($, isHidden))
    await update($, isHidden, () => hidden)
    return { text: hidden ? 'La Tecla se\'n va a fer un cafè ☕' : 'La Tecla torna a l\'arxiu 📚' }
  })

  on('turn.start', async ($, e, next) => {
    await checkScope($, await $.session.cwd())
    if (k.root) {
      const wasAsleep = moodNow() === 'sleepy'
      k.isWorking = true
      answered()
      await react($, onTurnStart(wasAsleep, rnd))
    }
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (k.root && e.agentId === undefined) {
      k.isWorking = false
      await react($, onTurnEnd(e.reason, rnd))
    }
    return next(e)
  })

  on('tool.call', async ($, e, next) => {
    if (!k.root) return next(e)
    const input = e as unknown as { file_path?: string; command?: string }
    const command = e.tool === 'Bash' ? input.command : undefined
    k.isWaitingUser = e.tool === 'AskUserQuestion'
    await react($, onTool({ tool: String(e.tool), path: input.file_path, command }, k.paths.people, rnd))
    const res = await next(e)
    const isError = 'deny' in res && res.deny !== undefined ? true : 'isError' in res && res.isError === true
    // A permission prompt, or the question itself, was answered by now.
    if (k.isWaitingUser) answered()
    if (command && isValidate(command)) await react($, onValidate(!isError, rnd))
    else if (isError && e.tool !== 'AskUserQuestion') await react($, onToolError(String(e.tool)))
    return res
  })

  on('classic.Notification', async ($, e, next) => {
    if (k.root) {
      const r = onNotification(e.notification_type, rnd)
      if (r) {
        k.isWaitingUser = true
        await react($, r)
      }
    }
    return next(e)
  })

  on('prompt.submit', ($, e, next) => {
    answered()
    k.lastActivity = now()
    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey || !k.root || (await read($, isHidden))) {
      k.isBandShown = false
      return next(e)
    }
    k.isBandShown = true
    k.requestId = e.requestId
    const { mood, phase } = pose()
    const said = await read($, speech)
    const lines = await read($, log)
    const s = await read($, stats)
    const following = isOrchestrator() ? trackLine(await read($, tracked)) : ''
    const isQuiet = !isOrchestrator()
    const cols = e.props.bodyColumns
    const rows = e.props.maxRows
    const bubble = said ? `« ${said.text} »` : '…'
    const numbers = s ? statsLine(s) : ''

    // Pixels on the terminal, as tall as the band allows: the full sprite,
    // the mini one, or (too small, or another surface) one kaomoji line.
    const size: Size | undefined =
      e.surface !== 'terminal'
        ? undefined
        : !isQuiet && rows >= FULL.rows && cols >= FULL.columns + 2 + TEXT_MIN
          ? 'full'
          : rows >= MINI.rows && cols >= MINI.columns + 2 + TEXT_MIN
            ? 'mini'
            : undefined
    k.size = size

    if (!size || e.surface !== 'terminal') {
      const { Box, Text } = $.ui.resolve(e)
      const face = kaomoji(mood, phase)
      k.drawn = face
      return (
        <Box flexDirection="column" key="tecla">
          <Text wrap="truncate-end">
            <Text color={SPEECH_COLOR}>{face}</Text> {said?.text ?? ''}
          </Text>
          {following ? <Text wrap="truncate-end">{following}</Text> : null}
          {numbers ? (
            <Text wrap="truncate-end" dimColor>
              {numbers}
            </Text>
          ) : null}
        </Box>
      )
    }

    const { Box, Text, Raster } = $.ui.resolve(e)
    const name = stepAt(mood, phase).name
    k.drawn = name
    const dims = size === 'full' ? FULL : MINI
    const isWide = size === 'full' && cols >= WIDE
    const wt = /\/\.worktrees\/([^/]+)$/.exec(k.root)?.[1]
    const header = [
      '📚 Tecla',
      k.role === 'research' ? '🔎 investigació' : '',
      s && s.people > 0 ? `${s.people} persones` : '',
      s && s.sources > 0 ? `${s.sources} fonts` : '',
      isWide && s?.last ? `última ${s.last}` : '',
      wt ? `🌿 ${wt}` : '',
    ]
      .filter(Boolean)
      .join(' · ')
    const books = isWide ? shelf(k.books, dims.rows * 2) : undefined
    // The log takes what the sprite's height leaves under the header, the
    // bubble and the numbers; the mini sprite keeps one line.
    const logLines = size === 'full' ? lines : lines.slice(-1)

    return (
      <Box flexDirection="row" key="tecla">
        {books ? (
          <Box marginRight={1}>
            <Raster key="shelf" columns={SHELF_W} rows={dims.rows} cells={encodeWords(toWords(books.pixels, books.palette))} />
          </Box>
        ) : null}
        <Raster key={SPRITE_KEY} columns={dims.columns} rows={dims.rows} cells={spriteCells(size, name)} />
        <Box flexDirection="column" marginLeft={2} flexGrow={1}>
          <Text bold wrap="truncate-end">
            {header}
          </Text>
          <Text color={SPEECH_COLOR} wrap="truncate-end">
            {bubble}
          </Text>
          {following ? <Text wrap="truncate-end">{following}</Text> : null}
          {logLines.map(l => (
            <Text wrap="truncate-end" dimColor>
              {clock(l.at)} {l.text}
            </Text>
          ))}
          {numbers ? (
            <Text wrap="truncate-end" dimColor>
              {numbers}
            </Text>
          ) : null}
        </Box>
      </Box>
    )
  })
}
