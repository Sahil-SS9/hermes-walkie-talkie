/**
 * Local type stub for @hermes/plugin-sdk (external at build time).
 *
 * The Desktop loader injects the real SDK object as
 * window.__HERMES_PLUGIN_SDK__ and rewrites the import to it at load time
 * (see core apps/desktop/src/sdk — "the loader injects this same object as
 * window.__HERMES_PLUGIN_SDK__ and maps the import to it, so a published
 * plugin builds against the types with the SDK marked external").
 *
 * This file declares ONLY the surface Hermes Peer consumes (rest, socket,
 * register, i18n) so the plugin typechecks standalone without pulling the
 * core app's internal `@/…` aliases. It is a type-only declaration; the
 * runtime binding always comes from the host.
 */

export interface PluginRestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
}

export interface PluginContext {
  readonly source: string
  register: (c: {
    id: string
    area: string
    title?: string
    order?: number
    render?: () => unknown
  }) => () => void
  rest: <T>(path: string, opts?: PluginRestOptions) => Promise<T>
  socket: (path: string, onMessage: (data: unknown) => void) => () => void
  i18n?: {
    t: (key: string) => string
  }
}

declare const __hermesPluginSdk: {
  createPluginContext: (pluginId: string, onDispose?: (fn: () => void) => void) => PluginContext
}

export default __hermesPluginSdk
