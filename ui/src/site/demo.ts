import { localSource } from '../shared/local'
import { mountMap } from '../shared/map'
import type { FleetEvent, Source, Telemetry, Teleop } from '../shared/types'
import { drive } from '../shared/keys'

const WORDS: Record<string, string> = {
  ok: 'on route',
  needs_assistance: 'needs a hand',
  estop: 'e-stop',
  paused: 'paused',
  teleop: 'driven by you',
  offline: 'silent',
}

const SAY: Record<string, (e: FleetEvent) => string> = {
  needs_assistance: () => 'asks for help',
  takeover: () => 'taken over',
  released: () => 'handed back',
  deadman_stop: e => `dead-man stop after ${Math.round(Number(e.detail.silent_for) * 1000)} ms`,
  zone_stop: e => `stopped short of ${String(e.detail.zone)}`,
  zone_warning: e => `close to ${String(e.detail.zone)}`,
  estop: () => 'e-stop pressed',
  battery_low: () => 'battery under 10 %',
  incident_opened: () => 'recording the window',
  incident_sealed: e => `sealed, head ${String(e.detail.head).slice(0, 10)}…`,
  // lines the page writes itself, not events from the fleet
  injected: e => String(e.detail.what),
  refused: e => String(e.detail.reason),
}

export function mountDemo(card: HTMLElement, src: Source = localSource()) {
  const $ = <T extends Element>(s: string) => card.querySelector<T>(s)!
  const map = mountMap($('.demo__map'), src.site.plan, src.site.zones, { pad: 8 })
  const list = $<HTMLUListElement>('.demo__robots')
  const log = $<HTMLOListElement>('.demo__log')
  const assist = $<HTMLElement>('.demo__assist')
  const driving = $<HTMLElement>('.demo__drive')
  const last = new Map<string, Telemetry>()
  let selected = 'Humanoid-Inspect-02'
  let helpFor: string | null = null
  let session: { teleop: Teleop; stop: () => void; robot: string } | null = null

  list.innerHTML = src.site.robots
    .map(r => `<li data-id="${r.id}"><b>${r.label}</b><span>${r.protocol === 'vda5050' ? 'VDA 5050' : r.protocol === 'ros2' ? 'ROS 2' : 'REST'}</span> · <span class="st">…</span></li>`)
    .join('')
  const row = (id: string) => list.querySelector<HTMLElement>(`[data-id="${id}"]`)!
  const select = (id: string | null) => {
    if (!id) return
    selected = id
    map.select(id)
    for (const li of list.children) li.classList.toggle('is-on', (li as HTMLElement).dataset.id === id)
  }
  list.addEventListener('click', e => select((e.target as HTMLElement).closest('li')?.dataset.id ?? null))
  map.onPick(select)
  select(selected)

  const note = (e: FleetEvent) => {
    const say = SAY[e.kind]
    if (!say) return
    const li = document.createElement('li')
    li.classList.toggle('is-amber', ['needs_assistance', 'deadman_stop', 'zone_stop', 'estop', 'incident_sealed'].includes(e.kind))
    const time = new Date(e.t * 1000).toTimeString().slice(0, 8)
    li.innerHTML = `${time} <b>${e.robot.split('-')[0]}</b> ${say(e)}`
    log.prepend(li)
    while (log.children.length > 7) log.lastChild!.remove()
  }

  const showAssist = () => {
    assist.hidden = !helpFor || !!session
    if (helpFor) $('.demo__who').textContent = `${src.site.robots.find(r => r.id === helpFor)?.label} is stuck behind a pallet`
  }

  src.subscribe(m => {
    if (m.type === 'telemetry') {
      const t = m.data
      last.set(t.robot, t)
      map.update(t)
      const li = row(t.robot)
      li.querySelector('.st')!.textContent = WORDS[t.status] ?? t.status
      li.classList.toggle('is-alert', t.status === 'needs_assistance' || t.status === 'estop')
      if (session?.robot === t.robot) $('.hud__v').textContent = Math.abs(t.speed).toFixed(2)
      return
    }
    const e = m.data
    note(e)
    if (e.kind === 'needs_assistance') {
      helpFor = e.robot
      select(e.robot)
    }
    if (e.kind === 'assistance_cleared' && helpFor === e.robot) helpFor = null
    if (e.kind === 'deadman_stop') $('.hud__link').textContent = 'lost'
    showAssist()
  })

  const take = async () => {
    const id = helpFor ?? selected
    if (session) return
    let teleop: Teleop
    try {
      teleop = await src.take(id)
    } catch (err) {
      note({ kind: 'refused', robot: id, detail: { reason: (err as Error).message }, t: Date.now() / 1000 })
      return
    }
    const bar = $<HTMLElement>('.deadman i')
    const stop = drive(teleop, {
      onSend: () => {
        $('.hud__link').textContent = 'ok'
        bar.style.transition = 'none'
        bar.style.transform = 'scaleX(1)'
        requestAnimationFrame(() => {
          bar.style.transition = 'transform 250ms linear'
          bar.style.transform = 'scaleX(0)'
        })
      },
    })
    session = { teleop, stop, robot: id }
    teleop.onClose(() => release())
    driving.hidden = false
    showAssist()
  }

  const release = () => {
    if (!session) return
    const s = session
    session = null
    s.stop()
    s.teleop.release()
    driving.hidden = true
    showAssist()
  }

  $('.demo__take').addEventListener('click', take)
  $('.demo__release').addEventListener('click', release)
  addEventListener('keydown', e => {
    const inView = card.getBoundingClientRect().top < innerHeight * 0.6 && card.getBoundingClientRect().bottom > innerHeight * 0.4
    if (!inView) return
    if (e.code === 'Space' && !session && helpFor) {
      e.preventDefault()
      take()
    } else if (e.code === 'Enter' && session) {
      e.preventDefault()
      release()
    }
  })

  for (const b of card.querySelectorAll<HTMLButtonElement>('[data-fail]')) {
    b.addEventListener('click', () => {
      const kind = b.dataset.fail as 'obstacle' | 'battery' | 'estop'
      // the obstacle is the humanoid's, so the takeover is possible; the rest hit whatever is selected
      const id = kind === 'obstacle' ? 'Humanoid-Inspect-02' : selected
      src.fail(id, kind)
      if (kind === 'obstacle') note({ kind: 'injected', robot: id, detail: { what: 'pallet in the aisle' }, t: Date.now() / 1000 })
    })
  }

  return { src }
}
