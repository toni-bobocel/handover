import { plan, robots, zones as demoZones } from './demo-site'
import type { Failure, FleetEvent, Incident, Source, Status, Telemetry, Teleop } from './types'

// The demo fleet, simulated in the page. Same rules as the core, smaller:
// six seconds blocked asks for help, 250 ms of silence stops a driven robot,
// zones pause robots a metre out. Used on GitHub Pages, where there is no core.

const BLOCKED_AFTER = 6
const DEADMAN = 0.25
const LIMITS = { linear: 0.5, angular: 0.8 }
const TRIGGERS = new Set(['estop', 'battery_low', 'link_lost', 'needs_assistance', 'takeover', 'zone_stop', 'deadman_stop'])

const wrap = (a: number) => Math.atan2(Math.sin(a), Math.cos(a))

interface Bot {
  id: string
  route: [number, number][]
  speed: number
  canDrive: boolean
  x: number
  y: number
  heading: number
  v: number
  battery: number
  leg: number
  paused: boolean
  blockedAt: [number, number] | null
  blockedSince: number
  assisting: boolean
  estopUntil: number
  silentUntil: number
  cmd: [number, number] | null
  cmdT: number
  driven: boolean
  stopped: boolean
  zoneHeld: Set<string>
}

function distToPoly(px: number, py: number, poly: [number, number][]) {
  let inside = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i]!
    const [xj, yj] = poly[j]!
    if (yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside
  }
  if (inside) return 0
  let best = Infinity
  for (let i = 0; i < poly.length; i++) {
    const [ax, ay] = poly[i]!
    const [bx, by] = poly[(i + 1) % poly.length]!
    const dx = bx - ax
    const dy = by - ay
    const u = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy || 1)))
    best = Math.min(best, Math.hypot(px - ax - u * dx, py - ay - u * dy))
  }
  return best
}

const zones = [...demoZones]

function zoneActive(z: (typeof zones)[number], now = new Date()) {
  if (!z.start || !z.end) return true
  const m = now.getHours() * 60 + now.getMinutes()
  const [a, b] = [z.start, z.end].map(s => Number(s.slice(0, 2)) * 60 + Number(s.slice(3)))
  return a! <= b! ? m >= a! && m < b! : m >= a! || m < b!
}

export function localSource(): Source {
  const now = () => performance.now() / 1000
  const bots: Bot[] = robots.map(r => {
    const [x, y] = r.route[0]!
    const [nx, ny] = r.route[1]!
    return {
      id: r.id, route: r.route, speed: r.speed, canDrive: r.can_drive,
      x, y, heading: Math.atan2(ny - y, nx - x), v: 0, battery: 0.6 + Math.random() * 0.35, leg: 1,
      paused: false, blockedAt: null, blockedSince: 0, assisting: false, estopUntil: 0, silentUntil: 0,
      cmd: null, cmdT: 0, driven: false, stopped: true, zoneHeld: new Set(),
    }
  })
  const subs: Parameters<Source['subscribe']>[0][] = []
  const incidents: Incident[] = []
  const open = new Map<string, Incident>()
  const flags = new Map<string, boolean>()

  const emit = (kind: string, robot: string, detail: Record<string, unknown> = {}) => {
    const e: FleetEvent = { kind, robot, detail, t: Date.now() / 1000 }
    for (const s of subs) s({ type: 'event', data: e })
    if (TRIGGERS.has(kind) && !open.has(robot)) {
      const inc: Incident = {
        id: `${new Date().toISOString().slice(0, 19).replace(/[-:]/g, '').replace('T', '-')}-${robot}`,
        robot, kind, t: e.t, bundle: null, head: null, bytes: null,
      }
      open.set(robot, inc)
      incidents.unshift(inc)
      emit('incident_opened', robot, { id: inc.id, kind })
      setTimeout(async () => {
        const bytes = new TextEncoder().encode(`${inc.id}:${inc.t}`)
        const digest = await crypto.subtle.digest('SHA-256', bytes)
        inc.head = [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('')
        inc.bundle = `${inc.id}.rbox`
        inc.bytes = 18000 + Math.round(Math.random() * 6000)
        open.delete(robot)
        emit('incident_sealed', robot, { id: inc.id, head: inc.head, bytes: inc.bytes })
      }, 10_000)
    }
  }

  const edge = (b: Bot, flag: string, on: boolean, detail: Record<string, unknown> = {}, off?: string) => {
    const key = `${b.id}:${flag}`
    const was = flags.get(key) ?? false
    if (on && !was) emit(flag, b.id, detail)
    else if (was && !on && off) emit(off, b.id)
    flags.set(key, on)
  }

  const resume = (b: Bot) => {
    b.paused = false
    b.blockedAt = null
    b.cmd = null
    b.leg = b.route.reduce((best, p, i) => (Math.hypot(p[0] - b.x, p[1] - b.y) < Math.hypot(b.route[best]![0] - b.x, b.route[best]![1] - b.y) ? i : best), 0)
  }

  const step = (b: Bot, dt: number, t: number) => {
    b.battery = Math.max(0, b.battery - dt * 0.00004)
    if (t < b.estopUntil) {
      b.v = 0
      return
    }
    if (b.driven) {
      const [lin, ang] = b.cmd ?? [0, 0]
      b.heading = wrap(b.heading + ang * dt)
      b.v = lin
      b.x = Math.max(0.4, Math.min(plan.width - 0.4, b.x + Math.cos(b.heading) * lin * dt))
      b.y = Math.max(0.4, Math.min(plan.height - 0.4, b.y + Math.sin(b.heading) * lin * dt))
      if (b.blockedAt && Math.hypot(b.x - b.blockedAt[0], b.y - b.blockedAt[1]) > 1.6) b.blockedAt = null
      return
    }
    if (b.paused || b.blockedAt) {
      b.v = 0
      return
    }
    const [tx, ty] = b.route[b.leg]!
    const turn = wrap(Math.atan2(ty - b.y, tx - b.x) - b.heading)
    b.heading = wrap(b.heading + Math.max(-2.5 * dt, Math.min(2.5 * dt, turn)))
    b.v = b.speed * Math.max(0.15, Math.cos(turn))
    const d = Math.hypot(tx - b.x, ty - b.y)
    const s = Math.min(d, b.v * dt)
    b.x += Math.cos(b.heading) * s
    b.y += Math.sin(b.heading) * s
    if (d < 0.15) b.leg = (b.leg + 1) % b.route.length
  }

  const status = (b: Bot, t: number): Status =>
    t < b.estopUntil ? 'estop' : b.driven ? 'teleop' : b.paused ? 'paused' : b.assisting ? 'needs_assistance' : 'ok'

  let last = now()
  const tick = () => {
    const t = now()
    const dt = Math.min(0.1, t - last)
    last = t
    for (const b of bots) {
      step(b, dt, t)
      if (b.driven && !b.stopped && t - b.cmdT > DEADMAN) {
        b.stopped = true
        b.cmd = [0, 0]
        emit('deadman_stop', b.id, { silent_for: Math.round((t - b.cmdT) * 1000) / 1000 })
      }
      if (t < b.silentUntil) continue
      if (b.blockedAt) {
        b.blockedSince ||= t
        b.assisting = t - b.blockedSince >= BLOCKED_AFTER
      } else {
        b.blockedSince = 0
        b.assisting = false
      }
      edge(b, 'needs_assistance', b.assisting, { note: 'path blocked: pallet in the aisle' }, 'assistance_cleared')
      edge(b, 'estop', t < b.estopUntil, {}, 'estop_cleared')
      edge(b, 'battery_low', b.battery < 0.1, { battery: b.battery })
      for (const z of zones) {
        if (!zoneActive(z)) continue
        const ahead = 0.6 * b.v
        const d = Math.min(distToPoly(b.x, b.y, z.polygon), distToPoly(b.x + Math.cos(b.heading) * ahead, b.y + Math.sin(b.heading) * ahead, z.polygon))
        if (d < z.margin && !b.zoneHeld.has(z.id)) {
          b.zoneHeld.add(z.id)
          if (b.driven) emit('zone_warning', b.id, { zone: z.id })
          else {
            b.paused = true
            emit('zone_stop', b.id, { zone: z.id, name: z.name, distance: Math.round(d * 100) / 100 })
          }
        } else if (d >= z.margin) b.zoneHeld.delete(z.id)
      }
      const data: Telemetry = {
        robot: b.id, x: b.x, y: b.y, heading: b.heading, speed: b.v, battery: b.battery,
        status: status(b, t), blocked: !!b.blockedAt, estop: t < b.estopUntil,
        note: b.blockedAt ? 'path blocked: pallet in the aisle' : '', t: Date.now() / 1000,
      }
      for (const s of subs) s({ type: 'telemetry', data })
    }
    for (const b of bots) edge(b, 'link_lost', t < b.silentUntil, { after: 3 }, 'link_restored')
  }
  setInterval(tick, 50)

  const bot = (id: string) => bots.find(b => b.id === id)!

  return {
    live: false,
    site: {
      name: 'Demo warehouse (in your browser)',
      plan,
      zones,
      demo: true,
      robots: robots.map(r => ({ id: r.id, label: r.label, kind: r.kind, protocol: r.protocol, can_drive: r.can_drive, last: null })),
    },
    subscribe: fn => void subs.push(fn),
    async take(id) {
      const b = bot(id)
      if (!b.canDrive) throw new Error(`${id} speaks VDA 5050, which has no velocity command`)
      b.paused = true
      b.driven = true
      b.cmd = [0, 0]
      b.cmdT = now()
      emit('takeover', id, { operator: 'you' })
      let closed: ((r: string) => void) | undefined
      return {
        limits: LIMITS,
        send(lin, ang) {
          const l = Math.max(-LIMITS.linear, Math.min(LIMITS.linear, lin))
          const a = Math.max(-LIMITS.angular, Math.min(LIMITS.angular, ang))
          b.cmd = [l, a]
          b.cmdT = now()
          b.stopped = l === 0 && a === 0
        },
        release() {
          b.driven = false
          resume(b)
          emit('released', id, { operator: 'you' })
          closed?.('released')
        },
        onClose: fn => {
          closed = fn
        },
      } satisfies Teleop
    },
    async pause(id) {
      bot(id).paused = true
      emit('paused', id, { by: 'operator' })
    },
    async resume(id) {
      resume(bot(id))
      emit('resumed', id, { by: 'operator' })
    },
    async fail(id, kind: Failure) {
      const b = bot(id)
      const t = now()
      if (kind === 'obstacle') b.blockedAt = [b.x, b.y]
      if (kind === 'battery') b.battery = 0.08
      if (kind === 'estop') b.estopUntil = t + 8
      if (kind === 'link') b.silentUntil = t + 6
    },
    incidents: async () => incidents.slice(0, 20),
    async putZone(z) {
      const i = zones.findIndex(x => x.id === z.id)
      if (i >= 0) zones[i] = z
      else zones.push(z)
      emit('zone_changed', '*', { id: z.id })
    },
    async deleteZone(id) {
      const i = zones.findIndex(x => x.id === id)
      if (i >= 0) zones.splice(i, 1)
      emit('zone_changed', '*', { id })
    },
    zones: async () => [...zones],
    bundleUrl: () => null,
    reportUrl: () => null,
  }
}
