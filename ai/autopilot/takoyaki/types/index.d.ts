export type LogLine = { at: number; text: string; tone: 'good' | 'bad' | 'info' }

declare module 'claude-code' {
  interface PluginState {
    'autopilot-takoyaki': {
      isActive: boolean
      log: LogLine[]
      header: string
    }
  }
}
