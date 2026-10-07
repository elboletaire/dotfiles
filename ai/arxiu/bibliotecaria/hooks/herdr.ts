// Pure readings for the investigation tracker and the role: `herdr agent
// list`'s JSON, which agents are in the tree, what changed between two
// polls, and the band's line. The module runs herdr; nothing here does.

export type Role = 'orchestrator' | 'research'
export type AgentState = 'working' | 'blocked' | 'done' | 'idle' | 'unknown'
export type Agent = { name: string; pane: string; cwd: string; state: AgentState }

const STATES: readonly AgentState[] = ['working', 'blocked', 'done', 'idle', 'unknown']

// `herdr agent list` -> its agents, or undefined when herdr said nothing
// usable (not installed, the server not running, an error): then nothing is
// known, which is not the same as no agents.
export function parseAgents(stdout: string): Agent[] | undefined {
  let data: unknown
  try {
    data = JSON.parse(stdout)
  } catch {
    return undefined
  }
  const list = (data as { result?: { agents?: unknown } } | null)?.result?.agents
  if (!Array.isArray(list)) return undefined
  const agents: Agent[] = []
  for (const a of list as Record<string, unknown>[]) {
    if (!a || typeof a !== 'object') continue
    const cwd = typeof a.cwd === 'string' ? a.cwd : ''
    const pane = typeof a.pane_id === 'string' ? a.pane_id : ''
    const name = typeof a.name === 'string' && a.name ? a.name : pane
    const status = String(a.agent_status ?? 'unknown') as AgentState
    agents.push({ name, pane, cwd, state: STATES.includes(status) ? status : 'unknown' })
  }
  return agents
}

const trimSlash = (p: string) => (p.length > 1 ? p.replace(/\/+$/, '') : p)
export const isInside = (path: string, dir: string) => {
  const p = trimSlash(path)
  const d = trimSlash(dir)
  return d !== '' && (p === d || p.startsWith(`${d}/`))
}

// The agents the orchestrator follows: in the tree (any of its spellings,
// resolved or not), never her own pane.
export const inTree = (agents: Agent[], trees: string[], ownPane: string, ownName = '') =>
  agents.filter(a => a.cwd && trees.some(t => isInside(a.cwd, t)) && a.pane !== ownPane && !(ownName && a.name === ownName))

// The session's role: ARXIU_ROLE when set; otherwise, inside herdr, by its
// agent's name (the orchestrator's is `[arbre].orchestrator_agent`); a plain
// session outside herdr keeps the full Tecla, with nothing to track.
// Undefined: inside herdr, but its agent is not listed yet; ask again later.
export function roleOf(env: string | undefined, isHerdr: boolean, ownName: string | undefined, orchestrator: string): Role | undefined {
  const r = (env ?? '').trim().toLowerCase()
  if (r === 'orchestrator' || r === 'research') return r
  if (r) return 'research'
  if (!isHerdr) return 'orchestrator'
  if (ownName === undefined) return undefined
  return ownName === orchestrator ? 'orchestrator' : 'research'
}

export type Change =
  | { kind: 'appeared'; agent: Agent }
  | { kind: 'working'; agent: Agent }
  | { kind: 'blocked'; agent: Agent }
  | { kind: 'finished'; agent: Agent }
  | { kind: 'vanished'; agent: Agent }

// What happened between two polls, keyed by pane. A new agent is announced
// once (its state then is where it starts); a finish is leaving work
// (working or blocked) for done or idle.
export function diffAgents(before: Agent[], after: Agent[]): Change[] {
  const was = new Map(before.map(a => [a.pane || a.name, a]))
  const now = new Set(after.map(a => a.pane || a.name))
  const changes: Change[] = []
  for (const a of after) {
    const b = was.get(a.pane || a.name)
    if (!b) {
      changes.push({ kind: 'appeared', agent: a })
      if (a.state === 'blocked') changes.push({ kind: 'blocked', agent: a })
      continue
    }
    if (a.state === b.state) continue
    if (a.state === 'blocked') changes.push({ kind: 'blocked', agent: a })
    else if (a.state === 'working') changes.push({ kind: 'working', agent: a })
    else if ((a.state === 'done' || a.state === 'idle') && (b.state === 'working' || b.state === 'blocked'))
      changes.push({ kind: 'finished', agent: a })
  }
  for (const b of before) if (!now.has(b.pane || b.name)) changes.push({ kind: 'vanished', agent: b })
  // The loudest news last, so it keeps the bubble: a call for Òscar wins.
  const order: Change['kind'][] = ['vanished', 'working', 'appeared', 'finished', 'blocked']
  return changes.sort((x, y) => order.indexOf(x.kind) - order.indexOf(y.kind))
}

export const GLYPH: Record<AgentState, string> = { working: '◐', blocked: '⏸', done: '✓', idle: '○', unknown: '○' }

// The band's line: `🔎 investigacio ◐ · cosins ⏸`; empty with none tracked.
export const trackLine = (agents: readonly Pick<Agent, 'name' | 'state'>[]) =>
  agents.length === 0 ? '' : `🔎 ${agents.map(a => `${a.name} ${GLYPH[a.state]}`).join(' · ')}`
