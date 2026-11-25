import type { Plan, Telemetry, Zone } from './types'

// A floor plan, not a 3D scene: an operator reads a flat plan at a glance,
// and a site PC with integrated graphics draws it without its fan spinning up.

const INK = 'rgba(236,235,230,'
const AMBER = '#ffa630'

interface Seen {
  t: Telemetry
  x: number
  y: number
  h: number
  trail: [number, number][]
}

export interface MapView {
  update(t: Telemetry): void
  select(id: string | null): void
  onPick(fn: (id: string | null) => void): void
  setZones(z: Zone[]): void
  destroy(): void
}

export function mountMap(canvas: HTMLCanvasElement, plan: Plan, zones: Zone[], opts: { labels?: boolean; pad?: number } = {}): MapView {
  const ctx = canvas.getContext('2d')!
  const seen = new Map<string, Seen>()
  let selected: string | null = null
  let pick: ((id: string | null) => void) | undefined
  let raf = 0
  let scale = 1
  let ox = 0
  let oy = 0
  const pad = opts.pad ?? 24

  const resize = () => {
    const dpr = Math.min(2, devicePixelRatio)
    const r = canvas.getBoundingClientRect()
    canvas.width = Math.round(r.width * dpr)
    canvas.height = Math.round(r.height * dpr)
    scale = Math.min((r.width - pad * 2) / plan.width, (r.height - pad * 2) / plan.height) * dpr
    ox = (canvas.width - plan.width * scale) / 2
    oy = (canvas.height - plan.height * scale) / 2
  }
  const ro = new ResizeObserver(resize)
  ro.observe(canvas)
  resize()

  const X = (x: number) => ox + x * scale
  const Y = (y: number) => oy + y * scale
  const trace = (pts: [number, number][]) => {
    ctx.beginPath()
    for (const [i, [x, y]] of pts.entries()) {
      if (i) ctx.lineTo(X(x), Y(y))
      else ctx.moveTo(X(x), Y(y))
    }
  }

  canvas.addEventListener('click', e => {
    const r = canvas.getBoundingClientRect()
    const dpr = canvas.width / r.width
    const px = (e.clientX - r.left) * dpr
    const py = (e.clientY - r.top) * dpr
    let best: string | null = null
    let bd = 28 * dpr
    for (const [id, s] of seen) {
      const d = Math.hypot(X(s.x) - px, Y(s.y) - py)
      if (d < bd) [best, bd] = [id, d]
    }
    pick?.(best)
  })

  const draw = (now: number) => {
    raf = requestAnimationFrame(draw)
    const dpr = canvas.width / Math.max(1, canvas.getBoundingClientRect().width)
    ctx.clearRect(0, 0, canvas.width, canvas.height)

    // floor grid, one line every two metres
    ctx.strokeStyle = `${INK}0.05)`
    ctx.lineWidth = 1
    ctx.beginPath()
    for (let x = 0; x <= plan.width; x += 2) {
      ctx.moveTo(X(x), Y(0))
      ctx.lineTo(X(x), Y(plan.height))
    }
    for (let y = 0; y <= plan.height; y += 2) {
      ctx.moveTo(X(0), Y(y))
      ctx.lineTo(X(plan.width), Y(y))
    }
    ctx.stroke()
    ctx.strokeStyle = `${INK}0.35)`
    ctx.strokeRect(X(0), Y(0), plan.width * scale, plan.height * scale)

    ctx.fillStyle = `${INK}0.09)`
    ctx.strokeStyle = `${INK}0.28)`
    for (const [x, y, w, h] of plan.racks) {
      ctx.fillRect(X(x), Y(y), w * scale, h * scale)
      ctx.strokeRect(X(x), Y(y), w * scale, h * scale)
    }

    for (const z of zones) {
      ctx.save()
      trace(z.polygon)
      ctx.closePath()
      ctx.clip()
      ctx.strokeStyle = 'rgba(255,166,48,0.35)'
      ctx.lineWidth = 1.2 * dpr
      const [minX, minY] = [Math.min(...z.polygon.map(p => p[0])), Math.min(...z.polygon.map(p => p[1]))]
      for (let k = -40; k < 80; k++) {
        ctx.beginPath()
        ctx.moveTo(X(minX + k * 0.6), Y(minY))
        ctx.lineTo(X(minX + k * 0.6 - 14), Y(minY + 14))
        ctx.stroke()
      }
      ctx.restore()
      trace(z.polygon)
      ctx.closePath()
      ctx.strokeStyle = AMBER
      ctx.lineWidth = 1.2 * dpr
      ctx.stroke()
      if (opts.labels !== false) {
        ctx.fillStyle = 'rgba(255,166,48,0.9)'
        ctx.font = `${10 * dpr}px "Fragment Mono", monospace`
        // inside the zone, top left: outside it, the dock's label ran off the plan
        const [lx, ly] = [Math.min(...z.polygon.map(p => p[0])), Math.min(...z.polygon.map(p => p[1]))]
        ctx.fillText(z.name.split(',')[0]!.toUpperCase(), X(lx) + 5 * dpr, Y(ly) + 13 * dpr)
      }
    }

    for (const [id, s] of seen) {
      // ease towards the last report: telemetry is 5 to 10 Hz, the screen is 60
      s.x += (s.t.x - s.x) * 0.25
      s.y += (s.t.y - s.y) * 0.25
      s.h += Math.atan2(Math.sin(s.t.heading - s.h), Math.cos(s.t.heading - s.h)) * 0.25
      const x = X(s.x)
      const y = Y(s.y)
      const st = s.t.status
      const alert = st === 'needs_assistance' || st === 'estop'
      const pulse = 0.5 + 0.5 * Math.sin(now / 180)

      ctx.strokeStyle = `${INK}0.16)`
      ctx.lineWidth = 1 * dpr
      trace(s.trail)
      ctx.stroke()

      // the lidar's forward cone
      const range = 3.2 * scale
      const grad = ctx.createRadialGradient(x, y, 0, x, y, range)
      const c = alert || st === 'teleop' ? '255,166,48' : '236,235,230'
      grad.addColorStop(0, `rgba(${c},0.22)`)
      grad.addColorStop(1, `rgba(${c},0)`)
      ctx.fillStyle = grad
      ctx.beginPath()
      ctx.moveTo(x, y)
      ctx.arc(x, y, range, s.h - 0.6, s.h + 0.6)
      ctx.closePath()
      ctx.fill()

      if (alert) {
        ctx.strokeStyle = `rgba(255,166,48,${0.25 + pulse * 0.5})`
        ctx.lineWidth = 1.5 * dpr
        ctx.beginPath()
        ctx.arc(x, y, (10 + pulse * 8) * dpr, 0, Math.PI * 2)
        ctx.stroke()
      }
      ctx.fillStyle = alert || st === 'teleop' ? AMBER : st === 'paused' ? `${INK}0.5)` : '#ecebe6'
      ctx.beginPath()
      ctx.arc(x, y, 4.5 * dpr, 0, Math.PI * 2)
      ctx.fill()
      ctx.strokeStyle = ctx.fillStyle
      ctx.lineWidth = 1.5 * dpr
      ctx.beginPath()
      ctx.moveTo(x, y)
      ctx.lineTo(x + Math.cos(s.h) * 12 * dpr, y + Math.sin(s.h) * 12 * dpr)
      ctx.stroke()
      if (id === selected) {
        ctx.strokeStyle = '#ecebe6'
        ctx.lineWidth = 1 * dpr
        ctx.strokeRect(x - 11 * dpr, y - 11 * dpr, 22 * dpr, 22 * dpr)
      }
      if (opts.labels !== false) {
        ctx.fillStyle = `${INK}${id === selected ? 0.95 : 0.55})`
        ctx.font = `${10 * dpr}px "Fragment Mono", monospace`
        ctx.fillText(id.split('-').slice(0, 2).join(' ').toUpperCase(), x + 12 * dpr, y - 9 * dpr)
      }
    }
  }
  raf = requestAnimationFrame(draw)

  return {
    update(t) {
      const s = seen.get(t.robot)
      if (!s) {
        seen.set(t.robot, { t, x: t.x, y: t.y, h: t.heading, trail: [[t.x, t.y]] })
        return
      }
      s.t = t
      const [lx, ly] = s.trail[s.trail.length - 1]!
      if (Math.hypot(t.x - lx, t.y - ly) > 0.3) {
        s.trail.push([t.x, t.y])
        if (s.trail.length > 40) s.trail.shift()
      }
    },
    select(id) {
      selected = id
    },
    onPick(fn) {
      pick = fn
    },
    setZones(z) {
      zones = z
    },
    destroy() {
      cancelAnimationFrame(raf)
      ro.disconnect()
    },
  }
}
