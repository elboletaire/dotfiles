export type LogLine = { at: number; text: string }
export type Speech = { at: number; text: string }
export type Stats = {
  people: number
  sources: number
  last: string
  pending: number
  contradictions: number
  toReview: number
}

// An investigation the orchestrator follows, as her band lists it.
export type Tracked = { name: string; state: 'working' | 'blocked' | 'done' | 'idle' | 'unknown' }

declare module 'claude-code' {
  interface PluginState {
    'arxiu-bibliotecaria': {
      isHidden: boolean
      speech: Speech | null
      log: LogLine[]
      stats: Stats | null
      tracked: Tracked[]
    }
  }
}
