// The photograph and its dot-matrix double, drawn on one canvas.
//
// The dots are sampled from the photograph itself, so the hands on black are
// the same hands, cell for cell. Tone becomes density through a 4x4 Bayer
// matrix, the ordered dither old screens used: the dark robot arm turns into
// the densest, brightest part.

// where the fingertips almost touch, as a fraction of the image
export const GAP = { x: 0.5055, y: 0.48 }
const PAPER = 219
const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5]
const dithered = (d: number, i: number, j: number) => d > ((BAYER[(j % 4) * 4 + (i % 4)]! + 0.5) / 16) * 0.92 + 0.04

/** The photo flattened on the paper colour, at one pixel per cell. */
function tones(img: HTMLImageElement, sw: number, cols: number, rows: number) {
  const off = document.createElement('canvas')
  off.width = cols
  off.height = rows
  const o = off.getContext('2d', { willReadFrequently: true })!
  o.fillStyle = `rgb(${PAPER},${PAPER},${PAPER})`
  o.fillRect(0, 0, cols, rows)
  o.drawImage(img, 0, 0, sw, img.naturalHeight, 0, 0, cols, rows)
  const px = o.getImageData(0, 0, cols, rows).data
  return (i: number, j: number) => {
    const k = (j * cols + i) * 4
    const lum = px[k]! * 0.3 + px[k + 1]! * 0.59 + px[k + 2]! * 0.11
    return Math.min(1, ((PAPER - lum) / PAPER) * 1.5)
  }
}

export interface HandsState {
  /** 0 = hands off screen, 1 = in place */
  arrive: number
  /** 0 = photograph, 1 = dots */
  dots: number
  /** background, 0..1 from paper to night */
  night: number
  /** 0 = hands sit high, clear of the headline; 1 = centred, around the window */
  settle: number
}

interface Dot {
  x: number
  y: number
  d: number
  seed: number
  side: -1 | 1
  sx: number
  sy: number
  ox: number
  oy: number
}

export function mountHands(canvas: HTMLCanvasElement, img: HTMLImageElement, state: HandsState) {
  const ctx = canvas.getContext('2d')!
  let dots: Dot[] = []
  let W = 0
  let H = 0
  let dpr = 1
  let rect = { x: 0, y: 0, w: 0, h: 0 }
  let cell = 5
  const pointer = { x: -1e4, y: -1e4, active: false }

  const layout = () => {
    dpr = Math.min(2, devicePixelRatio)
    W = canvas.clientWidth
    H = canvas.clientHeight
    canvas.width = Math.round(W * dpr)
    canvas.height = Math.round(H * dpr)
    const aspect = img.naturalWidth / img.naturalHeight
    // wide screens show both arms whole; tall ones crop the arms and keep the fingers
    const w = W / H > 1.5 ? W * 1.02 : Math.max(W * 1.9, H * 0.55 * aspect)
    const h = w / aspect
    rect = { x: W * 0.5 - w * GAP.x, y: H * 0.5 - h * GAP.y, w, h }
    cell = W < 720 ? 4 : W < 1500 ? 5 : 6
    sample()
  }

  const sample = () => {
    const cols = Math.round(rect.w / cell)
    const rows = Math.round(rect.h / cell)
    const tone = tones(img, img.naturalWidth, cols, rows)
    dots = []
    for (let j = 0; j < rows; j++) {
      for (let i = 0; i < cols; i++) {
        const d = tone(i, j)
        if (!dithered(d, i, j)) continue
        const x = rect.x + (i + 0.5) * cell
        const y = rect.y + (j + 0.5) * cell
        if (x < -cell || x > W + cell || y < -cell || y > H + cell) continue
        const a = Math.random() * Math.PI * 2
        const r = 30 + Math.random() * 90
        dots.push({
          x, y, d, seed: Math.random(),
          side: i / cols < GAP.x ? -1 : 1,
          sx: Math.cos(a) * r, sy: Math.sin(a) * r, ox: 0, oy: 0,
        })
      }
    }
  }

  const ease = (t: number) => (t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t))
  const lift = () => -(1 - state.settle) * H * 0.13

  const frame = (now: number) => {
    const { arrive, dots: p, night } = state
    ctx.setTransform(dpr, 0, 0, dpr, 0, lift() * dpr)
    ctx.clearRect(0, -H, W, H * 3)

    // the two halves come in from their own edge, then hold
    const travel = (1 - arrive) * W * 0.55
    const split = rect.x + rect.w * GAP.x
    const photo = 1 - ease(p * 1.8)
    if (photo > 0.001) {
      ctx.globalAlpha = photo
      const iw = img.naturalWidth
      const ih = img.naturalHeight
      const sx = iw * GAP.x
      const blur = (1 - arrive) * 14
      if (blur > 0.3) ctx.filter = `blur(${blur.toFixed(1)}px)`
      ctx.drawImage(img, 0, 0, sx, ih, rect.x - travel, rect.y, split - rect.x, rect.h)
      ctx.drawImage(img, sx, 0, iw - sx, ih, split + travel, rect.y, rect.x + rect.w - split, rect.h)
      ctx.filter = 'none'
    }

    if (p > 0.001) {
      // ink on paper first, then light on black once the ground has turned
      const v = Math.round(20 + (236 - 20) * ease((night - 0.35) / 0.4))
      const repel = pointer.active && p > 0.95
      const t = now / 1000
      for (const dot of dots) {
        const a = ease((p - dot.seed * 0.45) / 0.4)
        if (a <= 0) continue
        if (repel) {
          const dx = dot.x - pointer.x
          const dy = dot.y + lift() - pointer.y
          const r2 = dx * dx + dy * dy
          if (r2 < 110 * 110) {
            const f = (1 - Math.sqrt(r2) / 110) * 22
            const len = Math.sqrt(r2) || 1
            dot.ox += ((dx / len) * f - dot.ox) * 0.2
            dot.oy += ((dy / len) * f - dot.oy) * 0.2
          } else {
            dot.ox *= 0.9
            dot.oy *= 0.9
          }
        } else {
          dot.ox *= 0.9
          dot.oy *= 0.9
        }
        // a few cells flicker, like a display refreshing unevenly
        const flick = dot.seed > 0.985 ? 0.5 + 0.5 * Math.sin(t * 6 + dot.seed * 400) : 1
        const s = cell * (0.5 + 0.22 * dot.d) * a
        ctx.globalAlpha = (0.55 + 0.45 * dot.d) * a * flick
        const x = dot.x + dot.sx * (1 - a) + dot.ox + dot.side * travel
        const y = dot.y + dot.sy * (1 - a) + dot.oy
        ctx.fillStyle = `rgb(${v},${v},${v - 4})`
        ctx.fillRect(x - s / 2, y - s / 2, s, s)
      }
    }
    ctx.globalAlpha = 1
    raf = requestAnimationFrame(frame)
  }

  let raf = requestAnimationFrame(frame)
  addEventListener('resize', layout)
  canvas.parentElement!.addEventListener('pointermove', e => {
    const r = canvas.getBoundingClientRect()
    pointer.x = e.clientX - r.left
    pointer.y = e.clientY - r.top
    pointer.active = true
  })
  canvas.parentElement!.addEventListener('pointerleave', () => {
    pointer.active = false
  })
  layout()

  return {
    /** where the fingertips meet, in CSS pixels of the stage */
    gap: () => ({ x: rect.x + rect.w * GAP.x, y: rect.y + rect.h * GAP.y + lift() }),
    stop: () => cancelAnimationFrame(raf),
    onLayout: (fn: () => void) => addEventListener('resize', fn),
  }
}

/** The same sampling, for one hand only, drawn bright on black: the robot hand in the fleet card. */
export function mountHand(canvas: HTMLCanvasElement, img: HTMLImageElement, state: { gather: number }) {
  const ctx = canvas.getContext('2d')!
  let pts: { x: number; y: number; d: number; seed: number; sx: number; sy: number }[] = []
  let W = 0
  let H = 0
  let dpr = 1
  let cell = 5
  const pointer = { x: -1e4, y: -1e4 }

  const layout = () => {
    dpr = Math.min(2, devicePixelRatio)
    W = canvas.clientWidth
    H = canvas.clientHeight
    canvas.width = Math.round(W * dpr)
    canvas.height = Math.round(H * dpr)
    cell = W < 720 ? 3.5 : 4.5
    // the robot half of the photo, reaching in from the left edge to the centre
    const srcW = img.naturalWidth * GAP.x
    const aspect = srcW / img.naturalHeight
    const w = W * 0.62
    const h = w / aspect
    const x0 = -w * 0.06
    const y0 = H * 0.52 - h * GAP.y
    const cols = Math.round(w / cell)
    const rows = Math.round(h / cell)
    const tone = tones(img, srcW, cols, rows)
    pts = []
    for (let j = 0; j < rows; j++) {
      for (let i = 0; i < cols; i++) {
        const d = tone(i, j)
        if (!dithered(d, i, j)) continue
        pts.push({
          x: x0 + (i + 0.5) * cell, y: y0 + (j + 0.5) * cell, d, seed: Math.random(),
          sx: (Math.random() - 0.2) * W * 0.5, sy: (Math.random() - 0.5) * H * 0.8,
        })
      }
    }
  }

  const frame = () => {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, W, H)
    const g = state.gather
    ctx.fillStyle = '#ecebe6'
    for (const p of pts) {
      const a = Math.min(1, Math.max(0, (g - p.seed * 0.4) / 0.6))
      if (a <= 0) continue
      const k = 1 - (1 - a) ** 3
      let x = p.x + p.sx * (1 - k)
      let y = p.y + p.sy * (1 - k)
      const dx = x - pointer.x
      const dy = y - pointer.y
      const r = Math.hypot(dx, dy)
      if (r < 90) {
        x += (dx / (r || 1)) * (90 - r) * 0.35
        y += (dy / (r || 1)) * (90 - r) * 0.35
      }
      const s = cell * (0.5 + 0.22 * p.d)
      ctx.globalAlpha = (0.55 + 0.45 * p.d) * k
      ctx.fillRect(x - s / 2, y - s / 2, s, s)
    }
    raf = requestAnimationFrame(frame)
  }

  let raf = 0
  const io = new IntersectionObserver(([e]) => {
    cancelAnimationFrame(raf)
    if (e?.isIntersecting) raf = requestAnimationFrame(frame)
  })
  io.observe(canvas)
  addEventListener('resize', layout)
  canvas.addEventListener('pointermove', e => {
    const r = canvas.getBoundingClientRect()
    pointer.x = e.clientX - r.left
    pointer.y = e.clientY - r.top
  })
  canvas.addEventListener('pointerleave', () => {
    pointer.x = pointer.y = -1e4
  })
  layout()
}
