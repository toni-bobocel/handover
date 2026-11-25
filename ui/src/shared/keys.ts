import type { Teleop } from './types'

// QWERTY and AZERTY both: WASD and ZQSD share S and D, and arrows work everywhere.
const FWD = new Set(['ArrowUp', 'KeyW', 'KeyZ'])
const BACK = new Set(['ArrowDown', 'KeyS'])
const LEFT = new Set(['ArrowLeft', 'KeyA', 'KeyQ'])
const RIGHT = new Set(['ArrowRight', 'KeyD'])
const ALL = new Set([...FWD, ...BACK, ...LEFT, ...RIGHT])

/**
 * Sends a command every 100 ms for as long as control is held, keys down or
 * not: that steady beat is what the dead-man switch on the other end listens
 * for. A hidden tab stops sending, on purpose.
 */
export function drive(teleop: Teleop, opts: { onSend?: (lin: number, ang: number) => void } = {}) {
  const down = new Set<string>()
  const any = (s: Set<string>) => [...down].some(k => s.has(k))
  const onDown = (e: KeyboardEvent) => {
    if (!ALL.has(e.code)) return
    e.preventDefault()
    down.add(e.code)
  }
  const onUp = (e: KeyboardEvent) => down.delete(e.code)
  const onBlur = () => down.clear()
  addEventListener('keydown', onDown)
  addEventListener('keyup', onUp)
  addEventListener('blur', onBlur)

  const beat = setInterval(() => {
    if (document.hidden) return
    const lin = (any(FWD) ? 1 : 0) - (any(BACK) ? 1 : 0)
    // the plan is drawn with y down, so turning left on screen is a negative angle
    const ang = (any(LEFT) ? -1 : 0) + (any(RIGHT) ? 1 : 0)
    const l = lin * teleop.limits.linear
    const a = ang * teleop.limits.angular
    teleop.send(l, a)
    opts.onSend?.(l, a)
  }, 100)

  return () => {
    clearInterval(beat)
    removeEventListener('keydown', onDown)
    removeEventListener('keyup', onUp)
    removeEventListener('blur', onBlur)
  }
}
