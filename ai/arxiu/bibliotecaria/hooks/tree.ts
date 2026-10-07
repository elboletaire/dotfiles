// Cheap, pure readings of a family-tree-kit tree: the config's tree path,
// the scope check, families.yml's folders and colors, the research files'
// counts and `git log` output. The module hands the text in; nothing here
// touches the disk.

export type Paths = { people: string; sources: string; research: string }

export const DEFAULT_TREE = '~/src/arbre'
const DEFAULT_PATHS: Paths = { people: 'people', sources: 'sources', research: 'research' }

export const expandHome = (path: string, home: string) =>
  path === '~' ? home : path.startsWith('~/') ? `${home}${path.slice(1)}` : path

const trimSlash = (p: string) => (p.length > 1 ? p.replace(/\/+$/, '') : p)

// One string key of `[arbre]` in ai/arxiu/config.toml (`path`,
// `orchestrator_agent`, ...): a minimal read, enough for this file.
export function arbreKeyFromToml(text: string, key: string): string | undefined {
  let table = ''
  for (const raw of text.split('\n')) {
    const line = raw.replace(/\s+#.*$/, '').trim()
    if (!line || line.startsWith('#')) continue
    const header = /^\[([^\]]+)\]$/.exec(line)
    if (header) {
      table = header[1]!.trim()
      continue
    }
    if (table !== 'arbre') continue
    const kv = /^([A-Za-z_]+)\s*=\s*(?:"([^"]*)"|'([^']*)')$/.exec(line)
    if (kv && kv[1] === key) return kv[2] ?? kv[3]
  }
  return undefined
}

// `[arbre].path`: where the tree is.
export const arbrePathFromToml = (text: string) => arbreKeyFromToml(text, 'path')

// The checkout Tecla follows: the tree itself, or the worktree under
// `<tree>/.worktrees/<name>` the session runs in. Undefined outside the tree,
// where she never shows up. Both paths are absolute and already resolved.
export function scopeRoot(cwd: string, tree: string): string | undefined {
  const c = trimSlash(cwd)
  const t = trimSlash(tree)
  if (c !== t && !c.startsWith(`${t}/`)) return undefined
  const wt = /^\/\.worktrees\/([^/]+)/.exec(c.slice(t.length))
  if (wt) return `${t}/.worktrees/${wt[1]}`
  if (c === `${t}/.worktrees`) return undefined
  return t
}

// families.yml: the data folders (`paths:`) and the branches' colors.
export function readFamilies(text: string): { paths: Paths; colors: string[] } {
  const paths = { ...DEFAULT_PATHS }
  const colors: string[] = []
  let block = ''
  for (const line of text.split('\n')) {
    const top = /^([a-z_]+):/.exec(line)
    if (top) block = top[1]!
    if (block === 'paths') {
      const kv = /^\s+(people|sources|research):\s*["']?([^"'#\s]+)/.exec(line)
      if (kv) paths[kv[1] as keyof Paths] = kv[2]!
    }
    if (block === 'branches') {
      const color = /color:\s*["']?(#[0-9a-fA-F]{6})/.exec(line)
      if (color) colors.push(color[1]!)
    }
  }
  return { paths, colors }
}

export type Section = { label: string; count: number; kinds: Record<string, number> }
export type Research = {
  pending: number
  contradictions: number
  toReview: number
  pendingBy: Section[]
  contradictionsBy: Section[]
  reviewBy: Section[]
}

// "Fernández Banciella y Fernández de la Vara (Obra Pía de Valdés) (18)"
// -> "Fernández Banciella i Fernández de la Vara": Tecla speaks Catalan.
export const label = (heading: string) =>
  heading
    .replace(/^#+\s*/, '')
    .replace(/\s*\([^)]*\)/g, '')
    .replace(/:.*$/, '')
    .replace(/ y /g, ' i ')
    .trim()

// Sub-sections that record searches already done, not work pending.
const isDoneSearches = (heading: string) => /^#+\s*Búsquedas|sin resultado|no repetir/i.test(heading)

// Counts the `- **` items of a research file per branch section (`###`, or
// `##` where a family has no branches), and per kind of item (`####`).
export function countItems(text: string, skipDone = false): Section[] {
  const out: Section[] = []
  let current: Section | undefined
  let kind = ''
  let skipping = false
  const open = (heading: string) => {
    const l = label(heading)
    current = out.find(s => s.label === l)
    if (!current) {
      current = { label: l, count: 0, kinds: {} }
      out.push(current)
    }
    kind = ''
    skipping = false
  }
  for (const line of text.split('\n')) {
    if (/^## /.test(line) || /^### /.test(line)) open(line)
    else if (/^#### /.test(line)) {
      kind = label(line)
      skipping = skipDone && isDoneSearches(line)
    } else if (/^- \*\*/.test(line) && current && !skipping) {
      current.count += 1
      if (kind) current.kinds[kind] = (current.kinds[kind] ?? 0) + 1
    }
  }
  return out.filter(s => s.count > 0)
}

// revision.md: "**121 documentos pendientes de revisar**" and the branch
// headings that carry their count, "### Eguiburu (10)".
export function readRevision(text: string): { total: number; by: Section[] } {
  const total = Number(/\*\*(\d+) documentos? pendientes? de revisar\*\*/.exec(text)?.[1] ?? 0)
  const by: Section[] = []
  for (const m of text.matchAll(/^### (.+?) \((\d+)\)\s*$/gm)) {
    by.push({ label: label(m[1]!), count: Number(m[2]), kinds: {} })
  }
  return { total, by }
}

export function readResearch(pendientes: string, incoherencias: string, revision: string): Research {
  const pendingBy = countItems(pendientes, true)
  const contradictionsBy = countItems(incoherencias)
  const rev = readRevision(revision)
  const sum = (s: Section[]) => s.reduce((n, x) => n + x.count, 0)
  return {
    pending: sum(pendingBy),
    contradictions: sum(contradictionsBy),
    toReview: rev.total,
    pendingBy,
    contradictionsBy,
    reviewBy: rev.by,
  }
}

// What changed between two readings of the research files, for her to say.
export type ResearchChange =
  | { kind: 'contradiction'; label: string; of: string; delta: number }
  | { kind: 'solved'; label: string; delta: number }
  | { kind: 'pending'; label: string; delta: number }
  | { kind: 'done'; label: string; delta: number }
  | { kind: 'reviewed'; delta: number; left: number }
  | { kind: 'to-review'; delta: number; left: number }

export function diffResearch(before: Research, after: Research): ResearchChange[] {
  const out: ResearchChange[] = []
  // Every section of either reading: one that emptied is gone from `after`.
  const pairs = (a: Section[], b: Section[]) =>
    [...new Set([...a, ...b].map(s => s.label))].map(l => ({
      label: l,
      was: a.find(s => s.label === l),
      is: b.find(s => s.label === l),
    }))
  for (const { label: l, was, is } of pairs(before.contradictionsBy, after.contradictionsBy)) {
    const delta = (is?.count ?? 0) - (was?.count ?? 0)
    if (delta > 0) {
      // The kind of contradiction that grew: dates, names, places...
      const kinds = is?.kinds ?? {}
      const of = Object.keys(kinds).find(k => kinds[k]! > (was?.kinds[k] ?? 0)) ?? ''
      out.push({ kind: 'contradiction', label: l, of, delta })
    } else if (delta < 0) out.push({ kind: 'solved', label: l, delta: -delta })
  }
  for (const { label: l, was, is } of pairs(before.pendingBy, after.pendingBy)) {
    const delta = (is?.count ?? 0) - (was?.count ?? 0)
    if (delta > 0) out.push({ kind: 'pending', label: l, delta })
    else if (delta < 0) out.push({ kind: 'done', label: l, delta: -delta })
  }
  const r = after.toReview - before.toReview
  if (r < 0) out.push({ kind: 'reviewed', delta: -r, left: after.toReview })
  if (r > 0) out.push({ kind: 'to-review', delta: r, left: after.toReview })
  return out
}

export type Commit = {
  hash: string
  at: number // epoch seconds
  subject: string
  addedSources: string[] // F-ids, in order
  removedSources: string[]
  addedPeople: string[] // slugs
}

export const LOG_FORMAT = '%x1e%H%x09%at%x09%s'

// `git log --format=<LOG_FORMAT> --name-status --no-renames`, newest first.
export function parseLog(text: string, paths: Paths): Commit[] {
  const src = new RegExp(`^${reEscape(paths.sources)}/(F\\d+)\\.md$`)
  const ppl = new RegExp(`^${reEscape(paths.people)}/([^/]+)\\.md$`)
  const commits: Commit[] = []
  for (const chunk of text.split('\x1e')) {
    const lines = chunk.split('\n').filter(l => l.trim())
    const head = lines.shift()
    if (!head) continue
    const [hash, at, ...rest] = head.split('\t')
    if (!hash || !at) continue
    const c: Commit = {
      hash,
      at: Number(at),
      subject: rest.join('\t'),
      addedSources: [],
      removedSources: [],
      addedPeople: [],
    }
    for (const l of lines) {
      const [status, file] = l.split('\t')
      if (!status || !file) continue
      const s = src.exec(file)
      const p = ppl.exec(file)
      if (status === 'A' && s) c.addedSources.push(s[1]!)
      if (status === 'D' && s) c.removedSources.push(s[1]!)
      if (status === 'A' && p && p[1] !== 'README') c.addedPeople.push(p[1]!)
    }
    c.addedSources.sort(byId)
    commits.push(c)
  }
  return commits
}

const reEscape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const fnum = (id: string) => Number(id.replace(/^F/, ''))
const byId = (a: string, b: string) => fnum(a) - fnum(b)

// "F392" .. "F399" as one range, or a list when they are not contiguous.
export function idRange(ids: string[]): string {
  if (ids.length === 0) return ''
  if (ids.length === 1) return ids[0]!
  const sorted = [...ids].sort(byId)
  const first = sorted[0]!
  const last = sorted[sorted.length - 1]!
  if (fnum(last) - fnum(first) === sorted.length - 1) return `${first}-${last}`
  return sorted.length <= 3 ? sorted.join(', ') : `${first}…${last}`
}

// A slug as a name: "sinforosa-fernandez-diaz" -> "Sinforosa Fernandez Diaz".
export const nameOf = (slug: string) =>
  slug
    .split('-')
    .filter(Boolean)
    .map(w => (['de', 'del', 'la', 'i', 'y'].includes(w) ? w : w[0]!.toUpperCase() + w.slice(1)))
    .join(' ')

// The totals the header shows, from the listing of the two data folders.
export function totals(people: string[], sources: string[]): { people: number; sources: number; last: string } {
  const ids = sources.map(n => /^(F\d+)\.md$/.exec(n)?.[1]).filter((x): x is string => !!x)
  ids.sort(byId)
  return {
    people: people.filter(n => n.endsWith('.md') && n !== 'README.md').length,
    sources: ids.length,
    last: ids[ids.length - 1] ?? '',
  }
}
