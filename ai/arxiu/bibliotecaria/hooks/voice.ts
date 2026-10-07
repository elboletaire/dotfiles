// What Tecla says and how she looks when something happens: short Catalan
// lines, light and affectionate, about the research itself where she can.

import type { Commit, Research, ResearchChange, Section } from './tree'
import { idRange, nameOf } from './tree'
import type { Mood } from './sprite'
import type { Change } from './herdr'

// prio orders lines that compete for her speech bubble: a louder line
// replaces a quieter one at once, a quieter one waits for it to be read.
export type Prio = 0 | 1 | 2 | 3
export type Reaction = {
  mood: Mood
  ms: number // how long the pose holds; 0 leaves the resting pose
  line?: string
  prio: Prio
  isLogged?: boolean // kept in the band's log beside the speech bubble
}

export type Rng = () => number
export const pick = <T>(list: readonly T[], rnd: Rng): T =>
  list[Math.min(list.length - 1, Math.floor(rnd() * list.length))]!

const fonts = (n: number) => (n === 1 ? '1 font' : `${n} fonts`)
const persones = (n: number) => (n === 1 ? '1 persona' : `${n} persones`)

// "Els Eguiburu" for one surname, the label as it is for several.
const branch = (l: string) => (/[ ,]/.test(l.replace(/^de /, '')) ? l : `els ${l}`)
const Branch = (l: string) => {
  const b = branch(l)
  return b[0]!.toUpperCase() + b.slice(1)
}

const KINDS: Record<string, string> = {
  Fechas: 'dates',
  Nombres: 'noms',
  Lugares: 'llocs',
  'Hijos i relaciones': 'fills i relacions',
  'Fechas i lugares': 'dates i llocs',
  Relaciones: 'relacions',
}

// A new commit on the tree's branch.
export function onCommit(c: Commit, rnd: Rng): Reaction {
  const added = c.addedSources
  const people = c.addedPeople
  if (added.length > 0) {
    const range = idRange(added)
    // "F392-F399" reads "de la F392 a la F399".
    const span = /^(F\d+)-(F\d+)$/.exec(range)
    const what = span ? `de la ${span[1]} a la ${span[2]}` : range
    const line =
      added.length > 1
        ? pick([`He arxivat ${what}! 📜 (${fonts(added.length)})`, `Segell a ${range}: ${fonts(added.length)} noves al prestatge 📜`], rnd)
        : pick([`He arxivat la ${range}! 📜`, `La ${range} ja té el seu segell ✒`, `Benvinguda, ${range}! Cap al prestatge 📜`], rnd)
    const plus = people.length === 1 ? ' i 1 persona nova 🌱' : people.length > 1 ? ` i ${persones(people.length)} noves 🌱` : ''
    return { mood: 'stamping', ms: 5000, line: line + plus, prio: 3, isLogged: true }
  }
  if (people.length > 0) {
    const line =
      people.length === 1
        ? `Hola, ${nameOf(people[0]!)}! Ja ets a l'arbre 🌱`
        : `${persones(people.length)} noves a l'arbre 🌱`
    return { mood: 'happy', ms: 4000, line, prio: 3, isLogged: true }
  }
  if (c.removedSources.length > 0) {
    return {
      mood: 'puzzled',
      ms: 3000,
      line: `Retiro ${idRange(c.removedSources)} del prestatge… adeu 🍂`,
      prio: 3,
      isLogged: true,
    }
  }
  const kind = /^(\w+)(\([^)]*\))?!?:/.exec(c.subject)?.[1] ?? ''
  const subject = c.subject.replace(/^\w+(\([^)]*\))?!?:\s*/, '')
  if (kind === 'fix') return { mood: 'happy', ms: 3000, line: `Esmenat: ${subject} ✓`, prio: 2, isLogged: true }
  if (kind === 'docs') return { mood: 'reading', ms: 3000, line: `Apunts nous: ${subject} 📝`, prio: 2, isLogged: true }
  if (kind === 'chore') return { mood: 'stamping', ms: 2500, line: `Endreçant: ${subject} 🧹`, prio: 2, isLogged: true }
  return { mood: 'stamping', ms: 3000, line: `Commit nou: ${subject} ✒`, prio: 2, isLogged: true }
}

// The research files changed: say the most telling change.
export function onResearch(changes: ResearchChange[], rnd: Rng): Reaction | undefined {
  const order: ResearchChange['kind'][] = ['contradiction', 'reviewed', 'solved', 'done', 'to-review', 'pending']
  const c = [...changes].sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind))[0]
  if (!c) return undefined
  switch (c.kind) {
    case 'contradiction': {
      const of = KINDS[c.of] ?? (c.of ? c.of.toLowerCase() : '')
      const what = c.delta === 1 ? `una incoherència${of ? ` de ${of}` : ''}` : `${c.delta} incoherències${of ? ` (${of})` : ''}`
      return {
        mood: 'puzzled',
        ms: 6000,
        line: pick([`Hi ha ${what} a la branca ${c.label}…`, `Mmm… ${what} a ${branch(c.label)} 🤔`], rnd),
        prio: 3,
        isLogged: true,
      }
    }
    case 'solved':
      return { mood: 'happy', ms: 4000, line: `Incoherència resolta a ${branch(c.label)}! ✨`, prio: 2, isLogged: true }
    case 'reviewed':
      return {
        mood: 'happy',
        ms: 4000,
        line: `${c.delta === 1 ? 'Una font revisada' : `${fonts(c.delta)} revisades`}! En queden ${c.left} ✧`,
        prio: 2,
        isLogged: true,
      }
    case 'to-review':
      return { mood: 'reading', ms: 3000, line: `${fonts(c.delta)} més per revisar (${c.left}) 📚`, prio: 1, isLogged: true }
    case 'done':
      return {
        mood: 'happy',
        ms: 3500,
        line: pick([`Un pendent menys a ${branch(c.label)}! ♥`, `${Branch(c.label)}: ${c.delta} pendent${c.delta > 1 ? 's' : ''} fet${c.delta > 1 ? 's' : ''} ✓`], rnd),
        prio: 2,
        isLogged: true,
      }
    case 'pending':
      return { mood: 'reading', ms: 3000, line: `Apunto ${c.delta} pendent${c.delta > 1 ? 's' : ''} nou${c.delta > 1 ? 's' : ''} a ${branch(c.label)} ✎`, prio: 1, isLogged: true }
  }
}

const F_FILE = /(?:^|\/)(F\d+)\.md$/
const PERSON = (people: string) => new RegExp(`(?:^|/)${people}/([^/]+)\\.md$`)

export type ToolSeen = {
  tool: string
  path?: string // file_path of Read, Write, Edit
  command?: string // Bash
  isNew?: boolean // a Write to a file that did not exist
}

// The agent is about to run a tool: what she does meanwhile.
export function onTool(t: ToolSeen, people: string, rnd: Rng): Reaction {
  const path = t.path ?? ''
  const f = F_FILE.exec(path)?.[1]
  const who = PERSON(people).exec(path)?.[1]
  switch (t.tool) {
    case 'Read':
      if (f) return { mood: 'reading', ms: 2500, line: `Llegint la ${f}… 📖`, prio: 1 }
      if (who) return { mood: 'reading', ms: 2500, line: `Fullejant la fitxa de ${nameOf(who)}…`, prio: 1 }
      return { mood: 'reading', ms: 1500, prio: 0 }
    case 'Write':
      if (f) return { mood: 'stamping', ms: 3000, line: `Catalogant la ${f}… ✒`, prio: 2 }
      if (who) return { mood: 'stamping', ms: 3000, line: `Fitxa nova: ${nameOf(who)} 🌱`, prio: 2 }
      return { mood: 'reading', ms: 1500, prio: 0 }
    case 'Edit':
      if (f) return { mood: 'stamping', ms: 2000, line: `Esmenant la ${f} ✎`, prio: 1 }
      if (who) return { mood: 'reading', ms: 2000, line: `Retocant ${nameOf(who)} ✎`, prio: 1 }
      return { mood: 'reading', ms: 1500, prio: 0 }
    case 'WebSearch':
    case 'WebFetch':
      return {
        mood: 'ladder',
        ms: 4000,
        line: pick(['Repasso la lletra petita amb la lupa… 🔍', 'Remenant hemeroteques… 🔎', 'Buscant als arxius de fora… 📰'], rnd),
        prio: 1,
      }
    case 'Agent':
    case 'Task':
      return { mood: 'ladder', ms: 3000, line: 'Envio un ajudant a buscar als arxius 🏃‍♀️', prio: 1 }
    case 'AskUserQuestion':
      return { mood: 'lookup', ms: 20000, line: 'Òscar! Tenim una pregunta per a tu 🙋‍♀️', prio: 3 }
    case 'Bash': {
      const cmd = t.command ?? ''
      if (isValidate(cmd)) return { mood: 'reading', ms: 8000, line: 'Repassant que tot quadri… 🔍', prio: 2 }
      if (/\bgit\s+commit\b/.test(cmd)) return { mood: 'stamping', ms: 3000, line: 'Segellant… ✒', prio: 1 }
      return { mood: 'reading', ms: 1500, prio: 0 }
    }
    default:
      return { mood: 'reading', ms: 1500, prio: 0 }
  }
}

export const isValidate = (cmd: string) => /\bmake\s+(?:[^|;&]*\s)?(validate|all)\b|\bvalidate\.py\b/.test(cmd)

// `make validate` finished.
export function onValidate(isOk: boolean, rnd: Rng): Reaction {
  return isOk
    ? { mood: 'happy', ms: 5000, line: pick(['Validació neta! ✨', 'Tot quadra! ✧', 'Ni una errada, quin goig ♥'], rnd), prio: 3, isLogged: true }
    : { mood: 'puzzled', ms: 7000, line: pick(['La validació es queixa… 🤔', 'Alguna cosa no quadra a la validació…'], rnd), prio: 3, isLogged: true }
}

export function onToolError(tool: string): Reaction {
  return { mood: 'puzzled', ms: 2500, line: tool === 'Bash' ? 'Uix, una ordre ha fallat…' : `Uix, ${tool} s'ha queixat…`, prio: 1 }
}

export function onNotification(type: string, rnd: Rng): Reaction | undefined {
  if (type === 'permission_prompt') {
    return { mood: 'lookup', ms: 60000, line: pick(['Òscar, cal el teu permís 🙏', 'Psst, Òscar! Puc passar? 🙏'], rnd), prio: 3 }
  }
  if (type === 'idle_prompt') return { mood: 'lookup', ms: 15000, line: 'Et toca, Òscar ♥', prio: 2 }
  if (type === 'elicitation_dialog') return { mood: 'lookup', ms: 30000, line: 'Òscar, et necessitem un moment 🙋‍♀️', prio: 3 }
  return undefined
}

export function onTurnStart(wasAsleep: boolean, rnd: Rng): Reaction {
  if (wasAsleep) return { mood: 'happy', ms: 2500, line: pick(['Ah! Ja sóc aquí, ja sóc aquí! ☕', 'Bon dia! Obro l\'arxiu ☕'], rnd), prio: 2 }
  return { mood: 'reading', ms: 1500, prio: 0 }
}

export function onTurnEnd(reason: string, rnd: Rng): Reaction {
  if (reason === 'error') return { mood: 'puzzled', ms: 6000, line: 'Uf, alguna cosa s\'ha encallat… 😵‍💫', prio: 3 }
  if (reason === 'aborted') return { mood: 'puzzled', ms: 3000, line: 'Ui! Aturat. Deso el punt de lectura 🔖', prio: 2 }
  return { mood: 'happy', ms: 2500, line: pick(['Fet! ✓', 'Llest! Ho deixo tot endreçat ♥', 'Fet i arxivat ✧'], rnd), prio: 1 }
}

export const SLEEP_LINES = ['zZz… els lligalls fan tanta sonsoneta…', 'zZz…', 'Només tanco els ulls un moment… zZz']

// Something to say while nothing happens, about the research.
export function ambient(r: Research | undefined, t: { people: number; sources: number; last: string } | undefined, rnd: Rng): string {
  const lines: string[] = ['M\'encanta l\'olor de paper vell 📜', 'Tot endreçat i a punt ♥', 'Quants avantpassats per conèixer! 🌳']
  if (t && t.people > 0) lines.push(`Ja som ${t.people} persones a l'arbre 🌳`)
  if (t && t.last) lines.push(`L'última del prestatge és la ${t.last} 📜`)
  if (r) {
    const any = (list: Section[]) => (list.length > 0 ? pick(list, rnd) : undefined)
    const p = any(r.pendingBy)
    if (p) lines.push(`${Branch(p.label)} tenen ${p.count} pendents… 📋`)
    const i = any(r.contradictionsBy)
    if (i) lines.push(`${Branch(i.label)}: ${i.count} incoherències per aclarir 🤔`)
    if (r.toReview > 0) lines.push(`${r.toReview} documents esperen que algú els revisi 📚`)
  }
  return pick(lines, rnd)
}

// The status line under her speech bubble.
export function statsLine(r: Pick<Research, 'pending' | 'contradictions' | 'toReview'> | undefined): string {
  if (!r) return ''
  return `📋 ${r.pending} pendents · 🤔 ${r.contradictions} incoherències · 📚 ${r.toReview} per revisar`
}

// --- The investigations the orchestrator follows ----------------------------

// A research agent changed: what she says and does. `commit` is the subject
// of the agent's last commit since it started working, when it made one.
export function onInvestigation(c: Change, rnd: Rng, commit?: string): Reaction | undefined {
  const name = c.agent.name
  switch (c.kind) {
    case 'appeared':
      return {
        mood: 'stamping',
        ms: 3500,
        line: pick([`Comença una investigació: ${name} 🔎`, `Comença una investigació: ${name} 🔎 Bona cacera!`], rnd),
        prio: 3,
        isLogged: true,
      }
    case 'working':
      return undefined
    case 'blocked':
      return {
        // She looks up at once; after that her resting pose keeps looking up
        // while any investigation is blocked.
        mood: 'lookup',
        ms: 4000,
        line: pick([`${name} et necessita, Òscar! 🙋`, `Òscar! ${name} et necessita 🙋`], rnd),
        prio: 3,
        isLogged: true,
      }
    case 'finished': {
      const what = commit ? ` · ${commit}` : ''
      return {
        mood: 'happy',
        ms: 5000,
        line: pick([`${name} ha acabat ✨${what}`, `${name} ha acabat ✨ Quina feinada!${what}`], rnd),
        prio: 3,
        isLogged: true,
      }
    }
    case 'vanished':
      return {
        mood: 'idle',
        ms: 0,
        line: pick([`${name} plega. Fins aviat! 👋`, `Adeu, ${name}! Gràcies per la feina ♥`], rnd),
        prio: 1,
        isLogged: true,
      }
  }
}

// A glance at the working investigations now and then, without a word.
export const GLANCE: Reaction = { mood: 'reading', ms: 2500, prio: 0 }
