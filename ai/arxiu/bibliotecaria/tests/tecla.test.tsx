import type { EngineInterface, On, RenderInput } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'

import {
  DEFAULT_COLOR,
  MOODS,
  PALETTE,
  SPRITE,
  cellsOf,
  decodeCells,
  encodeWords,
  frame,
  frameNames,
  kaomoji,
  rgb,
  shelf,
  stepAt,
  timeline,
  toWords,
} from '../hooks/sprite'
import { diffAgents, inTree, parseAgents, roleOf, trackLine } from '../hooks/herdr'
import type { Agent } from '../hooks/herdr'
import {
  arbreKeyFromToml,
  arbrePathFromToml,
  diffResearch,
  expandHome,
  idRange,
  nameOf,
  parseLog,
  readFamilies,
  readResearch,
  scopeRoot,
  totals,
} from '../hooks/tree'
import { ambient, isValidate, onCommit, onInvestigation, onNotification, onResearch, onTool, onTurnEnd, onValidate } from '../hooks/voice'

const first = () => 0

// --- Scope -------------------------------------------------------------------

test('she only lives inside the tree and its worktrees', () => {
  const tree = '/home/o/src/arbre'
  expect(scopeRoot('/home/o/src/arbre', tree)).toBe(tree)
  expect(scopeRoot('/home/o/src/arbre/', tree)).toBe(tree)
  expect(scopeRoot('/home/o/src/arbre/personas', tree)).toBe(tree)
  expect(scopeRoot('/home/o/src/arbre/.worktrees/telegram', tree)).toBe(`${tree}/.worktrees/telegram`)
  expect(scopeRoot('/home/o/src/arbre/.worktrees/telegram/fuentes', tree)).toBe(`${tree}/.worktrees/telegram`)
  // Not the worktrees folder itself, nor a look-alike, nor anywhere else.
  expect(scopeRoot('/home/o/src/arbre/.worktrees', tree)).toBeUndefined()
  expect(scopeRoot('/home/o/src/arbre2', tree)).toBeUndefined()
  expect(scopeRoot('/home/o/src', tree)).toBeUndefined()
  expect(scopeRoot('/home/o/.dotfiles', tree)).toBeUndefined()
})

test('the tree path comes from [arbre].path in config.toml', () => {
  const toml = [
    '# comment',
    '[arbre]',
    '# A family-tree-kit tree.',
    'path = "~/src/arbre"   # trailing',
    'research_agent = "Investigació"',
    '[taller]',
    'path = "/not/this"',
  ].join('\n')
  expect(arbrePathFromToml(toml)).toBe('~/src/arbre')
  expect(arbrePathFromToml('[taller]\npath = "/x"')).toBeUndefined()
  expect(expandHome('~/src/arbre', '/home/o')).toBe('/home/o/src/arbre')
  expect(expandHome('/abs', '/home/o')).toBe('/abs')
})

// --- Reading the tree ----------------------------------------------------------

const FAMILIES = [
  'language: es',
  'paths:',
  '  people: personas',
  '  sources: fuentes',
  '  research: investigacion',
  'families:',
  '  - key: margarita',
  'branches:',
  '  - {key: alonso, label: Alonso, color: "#2a78d6", founder: x, family: margarita}',
  '  - {key: eguiburu, label: Eguiburu, color: "#eb6834", founder: y, family: margarita}',
].join('\n')

const PENDIENTES = [
  '# Líneas de investigación pendientes',
  '## Familia de Margarita (Alonso Arias)',
  '### Alonso y Espino',
  '#### Documentos a conseguir',
  '- **Partida de bautismo** — falta',
  '- **Padrón de 1924** — falta',
  '#### Búsquedas del 5-10-2026 sin resultado, no repetir',
  '- **FamilySearch** — nada',
  '### Eguiburu',
  '#### Personas por identificar o completar',
  '- **Ignacio Eguiburu** — fechas',
  '## General',
  '- **Escanear el álbum** — pendiente',
].join('\n')

const INCOHERENCIAS = [
  '# Incoherencias',
  '## Familia de Margarita (Alonso Arias)',
  '### Alonso y Espino',
  '#### Fechas',
  '- **Nacimiento de José Manuel** — dos fechas',
  '#### Nombres',
  '- **Crescencia o Cresencia** — dos grafías',
].join('\n')

const REVISION = [
  '# Revisión',
  '**121 documentos pendientes de revisar** (79 de la familia de Margarita)',
  '### Alonso y Espino (10)',
  '#### [F119 — Mariano](../fuentes/F119.md)',
  '### Fernández Banciella y Fernández de la Vara (Obra Pía de Valdés) (18)',
].join('\n')

test('families.yml gives the folders and the shelf colors', () => {
  const fam = readFamilies(FAMILIES)
  expect(fam.paths).toEqual({ people: 'personas', sources: 'fuentes', research: 'investigacion' })
  expect(fam.colors).toEqual(['#2a78d6', '#eb6834'])
  expect(readFamilies('').paths.people).toBe('people')
})

test('research files are counted per branch, done searches left out', () => {
  const r = readResearch(PENDIENTES, INCOHERENCIAS, REVISION)
  expect(r.pending).toBe(4)
  expect(r.pendingBy.map(s => [s.label, s.count])).toEqual([
    ['Alonso i Espino', 2],
    ['Eguiburu', 1],
    ['General', 1],
  ])
  expect(r.contradictions).toBe(2)
  expect(r.contradictionsBy[0]?.kinds).toEqual({ Fechas: 1, Nombres: 1 })
  expect(r.toReview).toBe(121)
  expect(r.reviewBy.map(s => s.label)).toEqual(['Alonso i Espino', 'Fernández Banciella i Fernández de la Vara'])
})

test('a new contradiction of dates makes her puzzled, naming the branch', () => {
  const before = readResearch(PENDIENTES, INCOHERENCIAS, REVISION)
  const after = readResearch(
    PENDIENTES.replace('- **Ignacio Eguiburu** — fechas\n', ''),
    INCOHERENCIAS.replace('#### Nombres', '- **Boda** — 11/12 o 11/10\n#### Nombres'),
    REVISION.replace('**121', '**120'),
  )
  const changes = diffResearch(before, after)
  expect(changes).toContainEqual({ kind: 'contradiction', label: 'Alonso i Espino', of: 'Fechas', delta: 1 })
  expect(changes).toContainEqual({ kind: 'done', label: 'Eguiburu', delta: 1 })
  expect(changes).toContainEqual({ kind: 'reviewed', delta: 1, left: 120 })
  const r = onResearch(changes, first)
  expect(r?.mood).toBe('puzzled')
  expect(r?.line).toBe('Hi ha una incoherència de dates a la branca Alonso i Espino…')
  // With no contradiction, a review is the news.
  expect(onResearch(changes.filter(c => c.kind !== 'contradiction'), first)?.line).toBe('Una font revisada! En queden 120 ✧')
  expect(onResearch([], first)).toBeUndefined()
})

const LOG = [
  '\x1e6233111\t1791240072\tfeat: recerca dels Fernández Díaz de Figaredo (F392-F399)',
  '',
  'A\tfuentes/F393.md',
  'A\tfuentes/F392.md',
  'A\tfuentes/F392/1920_padron_recorte.jpg',
  'M\tpersonas/adolfo-fernandez-diaz.md',
  'A\tpersonas/sinforosa-fernandez-diaz.md',
  '\x1ec02c007\t1791240383\tfix: treu F380, que repetia una pàgina',
  '',
  'D\tfuentes/F380.md',
  '\x1e5d6a0f3\t1791242626\tchore: dates D-M-AAAA de les biografies',
  '',
  'M\tfuentes/F003.md',
].join('\n')

test('git log tells new sources and people apart', () => {
  const [feat, fix, chore] = parseLog(LOG, readFamilies(FAMILIES).paths)
  expect(feat).toEqual({
    hash: '6233111',
    at: 1791240072,
    subject: 'feat: recerca dels Fernández Díaz de Figaredo (F392-F399)',
    addedSources: ['F392', 'F393'],
    removedSources: [],
    addedPeople: ['sinforosa-fernandez-diaz'],
  })
  expect(fix?.removedSources).toEqual(['F380'])
  expect(chore?.addedSources).toEqual([])
  expect(idRange(['F399'])).toBe('F399')
  expect(idRange(['F393', 'F392', 'F394'])).toBe('F392-F394')
  expect(idRange(['F1', 'F5'])).toBe('F1, F5')
  expect(nameOf('juan-fernandez-de-la-vara')).toBe('Juan Fernandez de la Vara')
  expect(totals(['a.md', 'b.md', 'README.md'], ['F1.md', 'F12.md', 'F3.md', 'F12', 'x.txt'])).toEqual({
    people: 2,
    sources: 3,
    last: 'F12',
  })
})

test('a commit with new sources is stamped and filed', () => {
  const [feat, fix, chore] = parseLog(LOG, readFamilies(FAMILIES).paths)
  const r = onCommit(feat!, first)
  expect(r.mood).toBe('stamping')
  expect(r.line).toBe('He arxivat de la F392 a la F393! 📜 (2 fonts) i 1 persona nova 🌱')
  expect(r.isLogged).toBe(true)
  expect(onCommit({ ...feat!, addedSources: ['F399'], addedPeople: [] }, first).line).toBe('He arxivat la F399! 📜')
  expect(onCommit(fix!, first).line).toBe('Retiro F380 del prestatge… adeu 🍂')
  expect(onCommit(chore!, first).line).toBe('Endreçant: dates D-M-AAAA de les biografies 🧹')
})

// --- The agent's own work ---------------------------------------------------------

test('she follows what the agent does', () => {
  expect(onTool({ tool: 'Read', path: '/t/fuentes/F119.md' }, 'personas', first)).toMatchObject({
    mood: 'reading',
    line: 'Llegint la F119… 📖',
  })
  expect(onTool({ tool: 'Write', path: 'fuentes/F400.md' }, 'personas', first).mood).toBe('stamping')
  expect(onTool({ tool: 'Read', path: 'personas/ignacio-eguiburu.md' }, 'personas', first).line).toBe(
    'Fullejant la fitxa de Ignacio Eguiburu…',
  )
  expect(onTool({ tool: 'WebSearch' }, 'personas', first).mood).toBe('ladder')
  expect(onTool({ tool: 'AskUserQuestion' }, 'personas', first).mood).toBe('lookup')
  // Plain work reads along without a word.
  expect(onTool({ tool: 'Grep' }, 'personas', first).line).toBeUndefined()
  expect(isValidate('make validate')).toBe(true)
  expect(isValidate('uv run scripts/validate.py')).toBe(true)
  expect(isValidate('make -C ~/src/arbre validate 2>&1 | tail')).toBe(true)
  expect(isValidate('make web')).toBe(false)
  expect(onValidate(true, first).mood).toBe('happy')
  expect(onValidate(false, first).mood).toBe('puzzled')
  expect(onNotification('permission_prompt', first)?.mood).toBe('lookup')
  expect(onNotification('auth_success', first)).toBeUndefined()
  expect(onTurnEnd('error', first).mood).toBe('puzzled')
  expect(ambient(undefined, { people: 416, sources: 691, last: 'F399' }, () => 0.99)).toBe("L'última del prestatge és la F399 📜")
})

// --- The sprite -------------------------------------------------------------------

test('every frame of both sizes is a full map in the palette', () => {
  for (const size of ['full', 'mini'] as const) {
    const { width, height } = SPRITE[size]
    expect(frameNames(size).sort()).toEqual(frameNames('full').sort())
    for (const name of frameNames(size)) {
      const px = frame(size, name)
      expect(px.length, `${size}/${name}`).toBe(height)
      px.forEach((row, y) => {
        expect(row.length, `${size}/${name} row ${y}`).toBe(width)
        for (const ch of row) expect(ch === '.' || ch in PALETTE, `${size}/${name} '${ch}'`).toBe(true)
      })
    }
  }
  expect(cellsOf('full')).toEqual({ columns: 30, rows: 12 })
  expect(cellsOf('mini')).toEqual({ columns: 20, rows: 8 })
})

test('pairs of pixel rows become half-block cells', () => {
  const pal = { a: '#ff0000', b: '#00ff00' }
  // Columns: both set, top only, bottom only, neither.
  const w = toWords(['aa.', 'b.b', 'a..'], pal)
  expect(Array.from(w)).toEqual([
    0x2580, 0xff0000, 0x00ff00,
    0x2580, 0xff0000, DEFAULT_COLOR,
    0x2584, 0x00ff00, DEFAULT_COLOR,
    0x2580, 0xff0000, DEFAULT_COLOR, // an odd last row has no bottom half
    0x20, DEFAULT_COLOR, DEFAULT_COLOR,
    0x20, DEFAULT_COLOR, DEFAULT_COLOR,
  ])
  // Little-endian u32s in padded base64, and back.
  expect(encodeWords(Uint32Array.of(0x2588, 0xff8800, 0x01000000))).toBe('iCUAAACI/wAAAAAB')
  expect(Array.from(decodeCells(encodeWords(w)))).toEqual(Array.from(w))
  expect(() => toWords(['#'], pal)).toThrow()
})

test('known pixels of the full sprite land in the right cells', () => {
  const px = frame('full', 'idle')
  const w = toWords(px)
  const cell = (x: number, y: number) => Array.from(w.slice((y * 30 + x) * 3, (y * 30 + x) * 3 + 3))
  // The stray hair on top: two chestnut pixels over the hair below them.
  const hair = rgb(PALETTE.H!)
  const x0 = px[0]!.indexOf('H')
  expect(cell(x0, 0)).toEqual([0x2580, hair, hair])
  // The top-left corner is empty.
  expect(cell(0, 0)).toEqual([0x20, DEFAULT_COLOR, DEFAULT_COLOR])
  // The violet iris sits under the eye shine.
  const eye = px[8]!.indexOf('W')
  expect(cell(eye, 4)).toEqual([0x2580, rgb(PALETTE.W!), rgb(PALETTE.e!)])
  // The shoes are the last pixel row: a lower half block.
  const shoe = px[23]!.indexOf('O')
  expect(cell(shoe, 11)).toEqual([0x2584, rgb(PALETTE.O!), DEFAULT_COLOR])
})

test('each mood has its own frames, and idle blinks now and then', () => {
  const firsts = new Set(MOODS.map(m => timeline(m)[0]![0]))
  expect(firsts.size).toBe(MOODS.length)
  for (const mood of MOODS) {
    for (const [name] of timeline(mood)) expect(frameNames('full')).toContain(name)
    const names = new Set(Array.from({ length: 100 }, (_, i) => stepAt(mood, i * 125).name))
    expect(names.size, mood).toBeGreaterThan(1)
    expect(kaomoji(mood, 0).length).toBeGreaterThan(2)
  }
  expect(stepAt('idle', 0).name).toBe('idle')
  expect(stepAt('idle', 3700).name).toBe('idle-blink')
  expect(new Set(timeline('reading').map(s => s[0]))).toContain('reading-turn')
  // The shortest step outlasts a frame tick, so none is skipped.
  for (const mood of MOODS) for (const [, ms] of timeline(mood)) expect(ms).toBeGreaterThan(125)
})

test('the shelf takes the branch colours', () => {
  const s = shelf(['#2a78d6', 'teal', '#eb6834'], 24)
  expect(s.pixels.length).toBe(24)
  for (const row of s.pixels) expect(row.length).toBe(10)
  expect(Object.values(s.palette)).toContain('#2a78d6')
  expect(Object.values(s.palette)).not.toContain('teal')
  expect(toWords(s.pixels, s.palette).length).toBe(10 * 12 * 3)
})

// --- In a session ------------------------------------------------------------------

const TREE = '/trees/arbre'
const FILES: Record<string, string> = {
  [`${TREE}/families.yml`]: FAMILIES,
  [`${TREE}/investigacion/pendientes.md`]: PENDIENTES,
  [`${TREE}/investigacion/incoherencias.md`]: INCOHERENCIAS,
  [`${TREE}/investigacion/revision.md`]: REVISION,
  [`${TREE}/.git/logs/HEAD`]: '',
}
const DIRS: Record<string, string[]> = {
  [`${TREE}/personas`]: ['a.md', 'b.md', 'c.md'],
  [`${TREE}/fuentes`]: ['F001.md', 'F399.md', 'F399'],
  [`${TREE}`]: [],
  [`${TREE}/.git`]: [],
}

// The disk and git the plugin sees: a small tree in memory.
type FakeOpts = {
  env?: Record<string, string>
  // What `herdr agent list` prints, or undefined: the server is not running.
  herdr?: () => string | undefined
}

function fakeTree(on: On, opts: FakeOpts = {}) {
  mock.env(on, { HOME: '/home/o', ARXIU_TREE: TREE, ...opts.env })
  const clock = mock.clock(on)
  const missing = (path: string) => ({ deny: `ENOENT ${path}` })
  on('fs.read', ($, e) => {
    const text = FILES[e.path]
    return text === undefined ? missing(e.path) : { value: text }
  })
  on('fs.stat', ($, e) => {
    const isDir = e.path in DIRS
    if (!isDir && !(e.path in FILES)) return missing(e.path)
    return { value: { kind: isDir ? 'dir' : 'file', size: 0, mtimeMs: 1, isLink: false, realPath: e.path } as const }
  })
  on('fs.list', ($, e) => ({
    value: (DIRS[e.path] ?? []).map(name => ({ name, kind: name.endsWith('.md') ? 'file' : 'dir', size: 0, mtimeMs: 1, isLink: false }) as const),
  }))
  on('process.run', ($, e) => {
    if (e.argv[0] === 'herdr') {
      const out = opts.herdr?.()
      return {
        value: {
          exitCode: out === undefined ? 1 : 0,
          stdout: out ?? '',
          stderr: out === undefined ? 'server_not_running' : '',
          isStdoutTruncated: false,
          isStderrTruncated: false,
        },
      }
    }
    const since = e.argv.find(a => a.startsWith('--since='))
    return {
    value: {
      exitCode: 0,
      stdout: since ? 'feat: F401, la partida dels Eguiburu\n' : e.argv.includes('log') ? LOG : '6233111\n',
      stderr: '',
      isStdoutTruncated: false,
      isStderrTruncated: false,
    },
    }
  })
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('classic.Notification', () => ({}))
  on('command.run', () => ({ text: '' }))
  on('command.register', ($, e) => ({ value: { command: e.name } }))
  return clock
}

// Which frame of the full sprite some Raster cells draw.
const frameOfCells = (cells: unknown) =>
  frameNames('full').find(name => encodeWords(toWords(frame('full', name))) === cells) ?? 'unknown'

const engineBand = ($: EngineInterface, e: RenderInput) => {
  const { Text } = $.ui.resolve(e)
  return <Text key="engine">engine</Text>
}

const band = (bodyColumns: number, maxRows = 12) =>
  ({
    plugin: 'arxiu-bibliotecaria',
    surface: 'terminal',
    component: 'AbovePrompt',
    props: {
      hasSurvey: false,
      isWorking: false,
      maxRows,
      bodyColumns,
      scroll: { offset: 0, bodyRows: 12 },
      view: {},
    },
  }) as const

const start = ($: Engine, cwd: string) =>
  $.session.start({ cwd, surface: 'terminal', isInteractive: true })

test('outside the tree the band stays the engine’s', async ($, on) => {
  fakeTree(on)
  on('ui.render', engineBand)
  await start($, '/somewhere/else')
  const ui = await $.ui.mount(band(120))
  expect(await ui.find({ key: 'tecla' })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: 'engine' })).toBeDefined()
  await ui.unmount()
})

test('in a worktree of the tree she sits above the prompt', async ($, on) => {
  fakeTree(on)
  on('ui.render', engineBand)
  await start($, `${TREE}/.worktrees/recerca/personas`)
  const wt = await $.ui.mount(band(120))
  expect(await wt.find({ type: 'Text', text: /🌿 recerca/ })).toBeDefined()
  await wt.unmount()

  await start($, `${TREE}/personas`)
  const ui = await $.ui.mount(band(120))
  expect(await ui.find({ key: 'tecla' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /📚 Tecla · 3 persones · 2 fonts · última F399/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /4 pendents · 🤔 2 incoherències · 📚 121 per revisar/ })).toBeDefined()
  // The last commits are already in the log.
  expect(await ui.find({ type: 'Text', text: /He arxivat de la F392 a la F393/ })).toBeDefined()
  // Her pixels, 30 x 12 cells, with the shelf beside her.
  const sprite = await ui.find({ key: 'sprite' })
  expect(sprite?.type).toBe('Raster')
  expect(sprite?.props.columns).toBe(30)
  expect(sprite?.props.rows).toBe(12)
  expect(frameOfCells(sprite?.props.cells)).toBe('idle')
  expect((await ui.find({ key: 'shelf' }))?.props.rows).toBe(12)
  await ui.unmount()
})

test('smaller bands drop the shelf, then shrink her, then a kaomoji line', async ($, on) => {
  fakeTree(on)
  on('ui.render', engineBand)
  await start($, TREE)
  const size = async (cols: number, rows: number) => {
    const ui = await $.ui.mount(band(cols, rows))
    const sprite = await ui.find({ key: 'sprite' })
    const got = {
      sprite: sprite ? `${String(sprite.props.columns)}x${String(sprite.props.rows)}` : undefined,
      shelf: (await ui.find({ key: 'shelf' })) !== undefined,
      kaomoji: (await ui.find({ type: 'Text', text: /\(◕‿◕\)|\(-‿-\)/ })) !== undefined,
      tecla: (await ui.find({ key: 'tecla' })) !== undefined,
    }
    await ui.unmount()
    return got
  }
  expect(await size(120, 12)).toEqual({ sprite: '30x12', shelf: true, kaomoji: false, tecla: true })
  expect(await size(60, 12)).toEqual({ sprite: '30x12', shelf: false, kaomoji: false, tecla: true })
  // Narrower, or short: the mini Tecla, 20 x 8.
  expect(await size(50, 12)).toEqual({ sprite: '20x8', shelf: false, kaomoji: false, tecla: true })
  expect(await size(120, 9)).toEqual({ sprite: '20x8', shelf: false, kaomoji: false, tecla: true })
  // Smaller still, a line.
  expect(await size(30, 12)).toEqual({ sprite: undefined, shelf: false, kaomoji: true, tecla: true })
  expect(await size(120, 4)).toEqual({ sprite: undefined, shelf: false, kaomoji: true, tecla: true })
})

test('on the desktop she is a kaomoji line', async ($, on) => {
  fakeTree(on)
  on('ui.render', engineBand)
  await start($, TREE)
  const ui = await $.ui.mount({ ...band(120), surface: 'desktop' })
  expect(await ui.find({ key: 'sprite' })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /\(◕‿◕\)|\(-‿-\)/ })).toBeDefined()
  await ui.unmount()
})

test('frame ticks repaint her in place, and only on a new frame', async ($, on) => {
  const clock = fakeTree(on)
  const blits: { requestId: string; key: string; cells?: string }[] = []
  on('ui.blit', ($, e) => {
    blits.push(e as { requestId: string; key: string; cells?: string })
    return { value: {} }
  })
  on('ui.render', engineBand)
  await start($, TREE)
  const ui = await $.ui.mount({ ...band(120), requestId: 'band' })
  // Idle: nothing to paint until she blinks, 3.6 s in.
  await clock.advance(3000)
  expect(blits).toHaveLength(0)
  await clock.advance(750)
  expect(blits).toHaveLength(1)
  expect(blits[0]).toMatchObject({ requestId: 'band', key: 'sprite' })
  expect(frameOfCells(blits[0]?.cells)).toBe('idle-blink')
  await clock.advance(250)
  expect(blits).toHaveLength(2)
  expect(frameOfCells(blits[1]?.cells)).toBe('idle')
  await ui.unmount()
})

test('/tecla sends her for a coffee and back', async ($, on) => {
  fakeTree(on)
  on('ui.render', engineBand)
  await start($, TREE)
  const cmd = { command: 'tecla', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 120 } } as const
  expect((await $.command.run(cmd)).text).toMatch(/cafè/)
  const hidden = await $.ui.mount(band(120))
  expect(await hidden.find({ key: 'tecla' })).toBeUndefined()
  await hidden.unmount()
  expect((await $.command.run(cmd)).text).toMatch(/torna/)
  const back = await $.ui.mount(band(120))
  expect(await back.find({ key: 'tecla' })).toBeDefined()
  await back.unmount()
})

test('events switch her pose', async ($, on) => {
  const clock = fakeTree(on)
  const blits: string[] = []
  on('ui.blit', ($, e) => {
    blits.push(frameOfCells((e as { cells?: string }).cells))
    return { value: {} }
  })
  on('tool.call', () => ({ result: 'ok' }) as never)
  on('ui.render', engineBand)
  await start($, TREE)
  const ui = await $.ui.mount({ ...band(120), requestId: 'band' })
  const sprite = async () => frameOfCells((await ui.find({ key: 'sprite' }))?.props.cells)
  // The agent searches the web: out comes the magnifier. What she says
  // redraws the band, the new pose with it.
  await $.tool.call({ tool: 'WebSearch', query: 'Eguiburu', tool_use_id: 't1' } as never)
  expect(await sprite()).toBe('search')
  // A new source: the stamp goes up first, then comes down, painted in
  // place by the frame ticks with no redraw.
  await $.tool.call({ tool: 'Write', file_path: `${TREE}/fuentes/F400.md`, content: '', tool_use_id: 't2' } as never)
  expect(await sprite()).toBe('stamp-up')
  await clock.advance(700)
  expect(blits.at(-1)).toBe('stamp-down')
  expect(await sprite()).toBe('stamp-up')
  await ui.unmount()
})

test('a permission prompt makes her look up at Òscar', async ($, on) => {
  fakeTree(on)
  on('ui.render', engineBand)
  await start($, TREE)
  await $.classic.Notification({ message: 'Claude needs your permission', notification_type: 'permission_prompt' })
  const ui = await $.ui.mount(band(120))
  expect(await ui.find({ type: 'Text', text: /Òscar, cal el teu permís|Psst, Òscar/ })).toBeDefined()
  expect(frameOfCells((await ui.find({ key: 'sprite' }))?.props.cells)).toBe('lookup')
  await ui.unmount()
})

// --- Roles and the investigation tracker ----------------------------------------

test('the role comes from ARXIU_ROLE, or from her herdr agent\'s name', () => {
  expect(roleOf('orchestrator', true, undefined, 'arbre')).toBe('orchestrator')
  expect(roleOf('research', true, 'arbre', 'arbre')).toBe('research')
  expect(roleOf(' Research ', false, undefined, 'arbre')).toBe('research')
  // Unset inside herdr: the agent named [arbre].orchestrator_agent leads.
  expect(roleOf(undefined, true, 'arbre', 'arbre')).toBe('orchestrator')
  expect(roleOf('', true, 'investigacio', 'arbre')).toBe('research')
  // Not listed yet: ask again later.
  expect(roleOf(undefined, true, undefined, 'arbre')).toBeUndefined()
  // A plain session outside herdr keeps the full Tecla.
  expect(roleOf(undefined, false, undefined, 'arbre')).toBe('orchestrator')
  const toml = '[arbre]\npath = "~/src/arbre"\norchestrator_agent = "cap"\n[taller]\norchestrator_agent = "no"'
  expect(arbreKeyFromToml(toml, 'orchestrator_agent')).toBe('cap')
  expect(arbreKeyFromToml(toml, 'research_agent')).toBeUndefined()
})

const herdrList = (agents: Record<string, string>[]) => JSON.stringify({ id: 'cli:agent:list', result: { type: 'agent_list', agents } })
const herdrAgent = (name: string, pane: string, status: string, cwd = TREE) => ({
  name,
  agent: 'claude',
  agent_status: status,
  cwd,
  workspace_id: 'w1',
  pane_id: pane,
})

test('herdr agents in the tree, never her own pane, nothing when herdr is down', () => {
  const listed = parseAgents(
    herdrList([
      herdrAgent('arbre', 'p1', 'working'),
      herdrAgent('investigacio', 'p2', 'working', `${TREE}/.worktrees/eguiburu`),
      herdrAgent('cosins', 'p3', 'weird'),
      herdrAgent('web', 'p4', 'working', '/home/o/src/web'),
    ]),
  )!
  expect(listed.map(a => a.state)).toEqual(['working', 'working', 'unknown', 'working'])
  expect(inTree(listed, [TREE], 'p1').map(a => a.name)).toEqual(['investigacio', 'cosins'])
  expect(parseAgents('')).toBeUndefined()
  expect(parseAgents('{"error":"server_not_running"}')).toBeUndefined()
  expect(parseAgents(herdrList([]))).toEqual([])
})

test('the tracker tells appearing, blocked, finished and vanished agents apart', () => {
  const a = (name: string, state: Agent['state']): Agent => ({ name, pane: `p-${name}`, cwd: TREE, state })
  expect(diffAgents([], [a('inv', 'working')]).map(c => c.kind)).toEqual(['appeared'])
  expect(diffAgents([], [a('inv', 'blocked')]).map(c => c.kind)).toEqual(['appeared', 'blocked'])
  expect(diffAgents([a('inv', 'idle')], [a('inv', 'working')]).map(c => c.kind)).toEqual(['working'])
  expect(diffAgents([a('inv', 'working')], [a('inv', 'blocked')]).map(c => c.kind)).toEqual(['blocked'])
  expect(diffAgents([a('inv', 'working')], [a('inv', 'done')]).map(c => c.kind)).toEqual(['finished'])
  expect(diffAgents([a('inv', 'blocked')], [a('inv', 'idle')]).map(c => c.kind)).toEqual(['finished'])
  // Idle to done is no news.
  expect(diffAgents([a('inv', 'idle')], [a('inv', 'done')])).toEqual([])
  expect(diffAgents([a('inv', 'done')], []).map(c => c.kind)).toEqual(['vanished'])

  const inv = a('investigacio', 'working')
  expect(onInvestigation({ kind: 'appeared', agent: inv }, first)).toMatchObject({
    mood: 'stamping',
    line: 'Comença una investigació: investigacio 🔎',
  })
  expect(onInvestigation({ kind: 'working', agent: inv }, first)).toBeUndefined()
  expect(onInvestigation({ kind: 'blocked', agent: inv }, first)?.line).toBe('investigacio et necessita, Òscar! 🙋')
  expect(onInvestigation({ kind: 'finished', agent: inv }, first)).toMatchObject({ mood: 'happy', line: 'investigacio ha acabat ✨' })
  expect(onInvestigation({ kind: 'finished', agent: inv }, first, 'feat: F401')?.line).toBe('investigacio ha acabat ✨ · feat: F401')
  expect(onInvestigation({ kind: 'vanished', agent: inv }, first)).toMatchObject({ ms: 0, isLogged: true })

  expect(trackLine([a('investigacio', 'working'), a('cosins', 'blocked'), a('avis', 'done'), a('tia', 'idle')])).toBe(
    '🔎 investigacio ◐ · cosins ⏸ · avis ✓ · tia ○',
  )
  expect(trackLine([])).toBe('')
})

test('the orchestrator follows the investigations in herdr', async ($, on) => {
  let agents: Record<string, string>[] = [herdrAgent('arbre', 'p1', 'idle')]
  let isUp = true
  const clock = fakeTree(on, {
    env: { ARXIU_ROLE: 'orchestrator', HERDR_ENV: '1', HERDR_PANE_ID: 'p1' },
    herdr: () => (isUp ? herdrList(agents) : undefined),
  })
  on('ui.blit', () => ({ value: {} }))
  on('ui.render', engineBand)
  await start($, TREE)
  const look = async () => {
    const ui = await $.ui.mount(band(120))
    const texts = (await ui.findAll({ type: 'Text' })).map(t => String(t.text ?? ''))
    const pose = frameOfCells((await ui.find({ key: 'sprite' }))?.props.cells)
    await ui.unmount()
    return { texts, pose, track: texts.find(t => t.startsWith('🔎')) }
  }
  const poll = () => clock.advance(4000)

  // Herself only: nothing to track.
  await poll()
  expect((await look()).track).toBeUndefined()

  // A research agent starts in a worktree: a stamp and a line.
  agents = [...agents, herdrAgent('investigacio', 'p2', 'working', `${TREE}/.worktrees/eguiburu`)]
  await poll()
  let got = await look()
  expect(got.texts).toContainEqual(expect.stringMatching(/Comença una investigació: investigacio 🔎/))
  expect(got.track).toBe('🔎 investigacio ◐')
  expect(['stamp-up', 'stamp-down', 'stamp-mark']).toContain(got.pose)

  // It waits on Òscar: she looks up and calls him, until it changes.
  agents = [agents[0]!, herdrAgent('investigacio', 'p2', 'blocked'), herdrAgent('cosins', 'p3', 'working')]
  await poll()
  got = await look()
  expect(got.texts).toContainEqual(expect.stringMatching(/investigacio et necessita 🙋|investigacio et necessita, Òscar! 🙋/))
  expect(got.track).toBe('🔎 investigacio ⏸ · cosins ◐')
  expect(['lookup', 'lookup-2']).toContain(got.pose)

  // It finishes, with a commit since it started.
  agents = [agents[0]!, herdrAgent('investigacio', 'p2', 'done'), herdrAgent('cosins', 'p3', 'working')]
  await poll()
  got = await look()
  expect(got.texts).toContainEqual(expect.stringMatching(/investigacio ha acabat ✨.* · feat: F401, la partida dels Eguiburu/))
  expect(got.track).toBe('🔎 investigacio ✓ · cosins ◐')
  expect(['happy', 'happy-2']).toContain(got.pose)

  // It goes: a soft goodbye in the log.
  agents = [agents[0]!, herdrAgent('cosins', 'p3', 'working')]
  await poll()
  got = await look()
  expect(got.texts).toContainEqual(expect.stringMatching(/investigacio plega\. Fins aviat! 👋|Adeu, investigacio!/))
  expect(got.track).toBe('🔎 cosins ◐')

  // The server stops: nothing tracked, nothing said, no error.
  isUp = false
  await poll()
  got = await look()
  expect(got.track).toBeUndefined()
  expect(got.texts).not.toContainEqual(expect.stringMatching(/cosins plega/))
})

test('herdr missing or down: the orchestrator tracks nothing, quietly', async ($, on) => {
  const clock = fakeTree(on, { env: { ARXIU_ROLE: 'orchestrator', HERDR_ENV: '1', HERDR_PANE_ID: 'p1' } })
  on('ui.render', engineBand)
  await start($, TREE)
  await clock.advance(12000)
  const ui = await $.ui.mount(band(120))
  expect(await ui.find({ type: 'Text', text: /^🔎/ })).toBeUndefined()
  expect((await ui.find({ key: 'sprite' }))?.props.rows).toBe(12)
  await ui.unmount()
})

test('a research session gets the quiet mini Tecla, without the tracker', async ($, on) => {
  const clock = fakeTree(on, {
    env: { ARXIU_ROLE: 'research', HERDR_ENV: '1', HERDR_PANE_ID: 'p2' },
    herdr: () => herdrList([herdrAgent('investigacio', 'p2', 'working'), herdrAgent('cosins', 'p3', 'blocked')]),
  })
  on('tool.call', () => ({ result: 'ok' }) as never)
  on('ui.render', engineBand)
  await start($, TREE)
  await clock.advance(8000)
  const ui = await $.ui.mount(band(120))
  const sprite = await ui.find({ key: 'sprite' })
  expect(`${String(sprite?.props.columns)}x${String(sprite?.props.rows)}`).toBe('20x8')
  expect(await ui.find({ key: 'shelf' })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /📚 Tecla · 🔎 investigació/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^🔎/ })).toBeUndefined()
  // No greeting, no small talk.
  expect(await ui.find({ type: 'Text', text: /Hola, Òscar|Bon dia|guàrdia/ })).toBeUndefined()
  await ui.unmount()
  // Her own session's work still moves her.
  await $.tool.call({ tool: 'Read', file_path: `${TREE}/fuentes/F119.md`, tool_use_id: 't1' } as never)
  const after = await $.ui.mount(band(120))
  expect(await after.find({ type: 'Text', text: /Llegint la F119/ })).toBeDefined()
  await after.unmount()
})

// With no ARXIU_ROLE inside herdr, the name of her own agent picks the role.
for (const [own, rows] of [
  ['arbre', 12],
  ['investigacio', 8],
] as const) {
  test(`with no ARXIU_ROLE, her herdr agent named ${own} gets ${rows} rows`, async ($, on) => {
    fakeTree(on, {
      env: { HERDR_ENV: '1', HERDR_PANE_ID: 'p1' },
      herdr: () => herdrList([herdrAgent(own, 'p1', 'idle'), herdrAgent('cosins', 'p3', 'working')]),
    })
    on('ui.render', engineBand)
    await start($, TREE)
    const ui = await $.ui.mount(band(120))
    expect((await ui.find({ key: 'sprite' }))?.props.rows).toBe(rows)
    await ui.unmount()
  })
}
