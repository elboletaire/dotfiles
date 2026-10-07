export type LogLine = { at: number; text: string; tone: 'good' | 'bad' | 'info' }

declare module 'claude-code' {
  interface PluginState {
    'octopilot': {
      isActive: boolean
      log: LogLine[]
      header: string
    }
  }
}
