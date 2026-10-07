import type { EngineInterface, RenderInput } from 'claude-code'
import { expect, test } from 'claude-code/testing'

import { newEvents, react, readKitchen } from '../hooks/feed'
import { COLUMNS, ROWS, encode, paint } from '../hooks/scene'

const BAND = {
  component: 'AbovePrompt',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 12,
    bodyColumns: 100,
    scroll: { offset: 0, bodyRows: 12 },
    view: {},
  },
} as const

const TAKOYAKI = {
  command: 'takoyaki',
  args: '',
  origin: { kind: 'composer' },
  presentation: { isFullscreen: false, columns: 120 },
} as const

// What the engine itself draws in the band, beneath the plugin.
const engineBand = ($: EngineInterface, e: RenderInput) => {
  const { Text } = $.ui.resolve(e)
  return <Text key="engine">engine</Text>
}

test('the band stays the engine’s until the kitchen opens', async ($, on) => {
  on('ui.render', engineBand)
  const ui = await $.ui.mount({ plugin: 'autopilot-takoyaki', surface: 'terminal', ...BAND })
  expect(await ui.find({ key: 'kitchen' })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: 'engine' })).toBeDefined()
  await ui.unmount()
})

test('/takoyaki opens the kitchen above the prompt', async ($, on) => {
  on('ui.render', engineBand)
  on('command.run', () => ({ text: '' }))
  await $.command.run(TAKOYAKI)
  const ui = await $.ui.mount({ plugin: 'autopilot-takoyaki', surface: 'terminal', ...BAND })
  const raster = await ui.find({ type: 'Raster', key: 'kitchen' })
  expect(raster?.props.columns).toBe(COLUMNS)
  expect(await ui.find({ type: 'Text', text: /takoyaki kitchen/ })).toBeDefined()
  await ui.unmount()

  await $.command.run(TAKOYAKI)
  const closed = await $.ui.mount({ plugin: 'autopilot-takoyaki', surface: 'terminal', ...BAND })
  expect(await closed.find({ key: 'kitchen' })).toBeUndefined()
  await closed.unmount()
})

test('/pr-autopilot opens the kitchen on its own', async ($, on) => {
  on('ui.render', engineBand)
  on('command.run', () => ({ text: '' }))
  await $.command.run({ ...TAKOYAKI, command: 'pr-autopilot' })
  const ui = await $.ui.mount({ plugin: 'autopilot-takoyaki', surface: 'terminal', ...BAND })
  expect(await ui.find({ type: 'Raster', key: 'kitchen' })).toBeDefined()
  await ui.unmount()
})

test('a tracked item becomes a takoyaki whose doneness follows its report', () => {
  const state = JSON.stringify({
    paused: true,
    items: {
      'o/r#2': { added: 200, session: 's2', last_report: { state: 'failed' } },
      'o/r#1': { added: 100, session: 's1', last_report: { state: 'ready' } },
      'o/r#3': { added: 300 },
    },
  })
  const kitchen = readKitchen(state, 400, 6)
  expect(kitchen.paused).toBe(true)
  // A ready one waits for the user: it stays in the pan.
  expect(kitchen.balls.map(b => [b.key, b.state])).toEqual([
    ['o/r#1', 'ready'],
    ['o/r#2', 'burnt'],
    ['o/r#3', 'raw'],
  ])
  expect(kitchen.boxed).toEqual([])
  expect(readKitchen('not json', 0).balls).toEqual([])
})

test('only done items leave the pan for the shelf', () => {
  const items: Record<string, unknown> = {}
  for (let i = 1; i <= 8; i++) items[`o/r#${i}`] = { added: i, session: `s${i}` }
  const state = JSON.stringify({ items })
  const snapshot = JSON.stringify({
    rows: [
      { kind: 'DONE', key: 'o/r#1' },
      { kind: 'CAPPED', key: 'o/r#2' },
      { kind: 'WORKING', key: 'o/r#3' },
    ],
  })
  const kitchen = readKitchen(state, 100, 6, snapshot)
  expect(kitchen.boxed.map(b => [b.key, b.state])).toEqual([['o/r#1', 'done']])
  // CAPPED waits for the user, so it keeps its hole; the done one freed its
  // hole, so six of the seven left still fit.
  expect(kitchen.balls.map(b => [b.key, b.state])).toEqual([
    ['o/r#2', 'capped'],
    ['o/r#3', 'cooking'],
    ['o/r#4', 'cooking'],
    ['o/r#5', 'cooking'],
    ['o/r#6', 'cooking'],
    ['o/r#7', 'cooking'],
  ])
})

test('events are read once, across a trim of the log', () => {
  const a = '{"at": 10, "kind": "tick"}'
  const b = '{"at": 10, "key": "o/r#1", "kind": "spawn"}'
  const c = '{"at": 11, "kind": "pause"}'
  const first = newEvents(`${a}\n${b}\n`, { at: 0, seen: [] })
  expect(first.events.map(e => e.kind)).toEqual(['tick', 'spawn'])

  // The log was trimmed and grew: only the new line comes through.
  const second = newEvents(`${b}\n${c}\n`, first.cursor)
  expect(second.events.map(e => e.kind)).toEqual(['pause'])
  expect(newEvents(`${b}\n${c}\n`, second.cursor).events).toEqual([])
})

test('reports set the chef’s mood', () => {
  expect(react({ at: 1, kind: 'report', key: 'o/r#1', state: 'ready' }).mood).toBe('happy')
  expect(react({ at: 1, kind: 'report', key: 'o/r#1', state: 'blocked' }).mood).toBe('sad')
  expect(react({ at: 1, kind: 'merged', key: 'o/r#1' }).burst).toBe('heart')
  expect(react({ at: 1, kind: 'spawn', key: 'o/r#1', title: 'X' }).line?.text).toBe('new order r#1 X')
})

test('the scene packs into a full raster', () => {
  const words = paint({
    t: 0,
    mood: 'idle',
    balls: [{ key: 'a', state: 'cooking', ageMin: 0 }],
    boxed: [{ key: 'b', state: 'ready', ageMin: 0 }],
    holes: 6,
    isWorking: true,
    focus: 0,
    particles: [],
  })
  expect(words.length).toBe(COLUMNS * ROWS * 3)
  // 4 bytes per word, base64 of it padded to a multiple of 4.
  expect(encode(words).length).toBe(Math.ceil((words.length * 4) / 3) * 4)
  expect(encode(Uint32Array.of(0x2588, 0xff8800, 0x01000000))).toBe('iCUAAACI/wAAAAAB')
})
