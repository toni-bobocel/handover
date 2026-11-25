import type { Failure, Incident, Site, Source, Teleop } from './types'

const base = import.meta.env.BASE_URL.replace(/\/$/, '')
const ws = (path: string) => `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${base}${path}`

/** The real core, or null when there is none (the page is served from GitHub Pages). */
export async function liveSource(): Promise<Source | null> {
  let site: Site
  try {
    const r = await fetch(`${base}/api/site`, { signal: AbortSignal.timeout(1500) })
    if (!r.ok || !r.headers.get('content-type')?.includes('json')) return null
    site = await r.json()
  } catch {
    return null
  }

  const subs: Parameters<Source['subscribe']>[0][] = []
  const connect = () => {
    const s = new WebSocket(ws('/api/stream'))
    s.onmessage = e => {
      const { type, ...data } = JSON.parse(e.data)
      for (const fn of subs) fn({ type, data })
    }
    // the core restarted or the site's wifi blinked: keep trying, quietly
    s.onclose = () => setTimeout(connect, 1000)
  }
  connect()

  const post = async (path: string) => {
    const r = await fetch(`${base}${path}`, { method: 'POST' })
    if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? r.statusText)
  }

  return {
    live: true,
    site,
    subscribe: fn => void subs.push(fn),
    take: robot =>
      new Promise<Teleop>((resolve, reject) => {
        const s = new WebSocket(ws(`/api/teleop/${robot}`))
        let closed: ((r: string) => void) | undefined
        let granted = false
        s.onmessage = e => {
          const m = JSON.parse(e.data)
          if (m.type !== 'granted') return
          granted = true
          resolve({
            limits: m.limits,
            send: (linear, angular) => s.readyState === 1 && s.send(JSON.stringify({ linear, angular })),
            release: () => s.readyState === 1 && s.send(JSON.stringify({ type: 'release' })),
            onClose: fn => {
              closed = fn
            },
          })
        }
        s.onclose = e => (granted ? closed?.(e.reason || 'closed') : reject(new Error(e.reason || 'refused')))
      }),
    pause: robot => post(`/api/robots/${robot}/pause`),
    resume: robot => post(`/api/robots/${robot}/resume`),
    fail: (robot, kind: Failure) => post(`/api/demo/${robot}/${kind}`),
    incidents: async () => (await fetch(`${base}/api/incidents`)).json() as Promise<Incident[]>,
    bundleUrl: i => (i.bundle ? `${base}/api/incidents/${i.id}/bundle` : null),
    reportUrl: i => (i.bundle ? `${base}/api/incidents/${i.id}/report.pdf` : null),
  }
}
