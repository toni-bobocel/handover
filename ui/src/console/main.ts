import '@fontsource/host-grotesk/500.css'
import '@fontsource/host-grotesk/600.css'
import '@fontsource/fragment-mono/400.css'
import '../styles/console.css'

import { drive } from '../shared/keys'
import { liveSource } from '../shared/live'
import { localSource } from '../shared/local'
import { mountMap } from '../shared/map'
import { can, login, logout, type Me, whoami } from '../shared/session'
import { watch } from '../shared/video'
import type { Failure, FleetEvent, Incident, Source, Telemetry, Teleop, Zone } from '../shared/types'

const $ = <T extends Element = HTMLElement>(s: string) => document.querySelector<T>(s)!

const STATUS: Record<string, string> = {
  ok: 'on route', needs_assistance: 'needs a hand', estop: 'e-stop', paused: 'paused', teleop: 'driven', offline: 'silent',
}
const PROTO = { vda5050: 'VDA 5050 · MQTT', ros2: 'ROS 2 · rosbridge', rest: 'REST · webhooks' }
const LOUD = new Set(['needs_assistance', 'estop', 'deadman_stop', 'zone_stop', 'link_lost', 'battery_low', 'incident_sealed'])

function askLogin(): Promise<Me> {
  const form = $<HTMLFormElement>('.login')
  form.hidden = false
  form.querySelector('input')!.focus()
  return new Promise(resolve => {
    form.addEventListener('submit', async e => {
      e.preventDefault()
      const data = new FormData(form)
      const got = await login(String(data.get('name')), String(data.get('password')))
      if (typeof got === 'string') {
        $('.login__err').textContent = got
        return
      }
      form.hidden = true
      resolve(got)
    })
  })
}

const found = await whoami()
const me: Me | null = found === 'login' ? await askLogin() : found
const src: Source = (me && (await liveSource())) || localSource()
const { site } = src
if (me && !me.open) {
  $('.bar__user').hidden = false
  $('.bar__user').innerHTML = `<b>${me.name}</b> · ${me.role} · <button type="button" class="act">log out</button>`
  $('.bar__user button').addEventListener('click', logout)
}

$('.bar__site').textContent = site.name
$('.bar__mode').innerHTML = src.live ? 'connected to <b>this site</b>' : 'no core found · <b>simulated in this tab</b>'
if (site.demo && can(me, 'operator')) $('.demo-only').hidden = false
setInterval(() => ($('.bar__clock').textContent = new Date().toTimeString().slice(0, 8)), 1000)

const map = mountMap($<HTMLCanvasElement>('.floor__map'), site.plan, site.zones)
const last = new Map<string, Telemetry>()
let selected = site.robots[0]?.id ?? ''
let help: string | null = null
let session: { robot: string; teleop: Teleop; stop: () => void } | null = null

$('.robots__list').innerHTML = site.robots
  .map(
    r => `<li class="robot" data-id="${r.id}">
      <span class="robot__name">${r.label}</span>
      <span class="robot__meta">${r.kind} · ${PROTO[r.protocol]}</span>
      <span class="robot__state"><b>…</b><span class="batt"><i></i></span><span class="robot__pct">–</span></span>
      <span class="robot__acts">${actions(r.can_drive)}</span>
    </li>`,
  )
  .join('')

function actions(canDrive: boolean) {
  if (!can(me, 'operator')) return ''
  const drive = !canDrive
    ? '<span title="VDA 5050 has no velocity command">no remote driving</span>'
    : can(me, 'driver')
      ? '<button type="button" class="act" data-act="take">drive</button>'
      : ''
  return `<button type="button" class="act" data-act="pause">pause</button>
    <button type="button" class="act" data-act="resume">resume</button>${drive}`
}

// -- camera: the selected robot's, bigger while someone drives it ----------

let unwatch: (() => void) | null = null
let watching: string | null = null
async function showCamera(id: string) {
  const robot = site.robots.find(r => r.id === id)
  if (watching === id) return
  unwatch?.()
  unwatch = null
  watching = null
  $('.cam').hidden = !(src.live && robot?.camera && can(me, 'operator'))
  if ($('.cam').hidden) return
  watching = id
  $('.cam__who').textContent = robot!.label
  $('.cam__state').textContent = 'connecting'
  try {
    const stop = await watch(id, $<HTMLVideoElement>('.cam__video'))
    if (watching !== id) return stop()
    unwatch = stop
    $('.cam__state').textContent = 'live, local network only'
  } catch (err) {
    $('.cam__state').textContent = (err as Error).message
  }
}

const li = (id: string) => document.querySelector<HTMLElement>(`.robot[data-id="${id}"]`)!
const select = (id: string | null) => {
  if (!id) return
  selected = id
  map.select(id)
  showCamera(id)
  for (const el of document.querySelectorAll<HTMLElement>('.robot')) el.classList.toggle('is-on', el.dataset.id === id)
}
select(selected)
map.onPick(select)

$('.robots__list').addEventListener('click', async e => {
  const t = e.target as HTMLElement
  const id = t.closest<HTMLElement>('.robot')?.dataset.id
  if (!id) return
  select(id)
  const act = t.dataset.act
  try {
    if (act === 'pause') await src.pause(id)
    if (act === 'resume') await src.resume(id)
    if (act === 'take') await take(id)
  } catch (err) {
    log({ kind: 'refused', robot: id, detail: { why: (err as Error).message }, t: Date.now() / 1000 })
  }
})

const SAY: Record<string, (e: FleetEvent) => string> = {
  needs_assistance: e => `needs a hand: ${e.detail.note ?? 'blocked'}`,
  assistance_cleared: () => 'clear again',
  takeover: e => `taken over by ${e.detail.operator}`,
  released: e => `handed back after ${e.detail.held_for ?? '?'} s`,
  deadman_stop: e => `dead-man stop, ${Math.round(Number(e.detail.silent_for) * 1000)} ms of silence`,
  operator_lost: () => 'operator connection lost',
  zone_stop: e => `stopped ${e.detail.distance} m from ${e.detail.name ?? e.detail.zone}`,
  zone_warning: e => `driven close to ${e.detail.zone}`,
  estop: () => 'e-stop pressed',
  estop_cleared: () => 'e-stop released',
  battery_low: e => `battery at ${Math.round(Number(e.detail.battery) * 100)} %`,
  link_lost: () => 'silent for 3 s',
  link_restored: () => 'back online',
  paused: () => 'paused by an operator',
  resumed: () => 'resumed by an operator',
  incident_opened: e => `recording ${e.detail.kind}`,
  incident_sealed: e => `sealed, chain head ${String(e.detail.head).slice(0, 12)}`,
  refused: e => String(e.detail.why),
}

function log(e: FleetEvent) {
  const say = SAY[e.kind]
  if (!say) return
  const el = document.createElement('li')
  el.classList.toggle('is-amber', LOUD.has(e.kind))
  el.innerHTML = `${new Date(e.t * 1000).toTimeString().slice(0, 8)} <b>${e.robot}</b> ${say(e)}`
  $('.events').prepend(el)
  while ($('.events').children.length > 60) $('.events').lastChild!.remove()
}

const kb = (n: number | null) => (n ? `${(n / 1024).toFixed(1)} kB` : '')
async function incidents() {
  const list: Incident[] = await src.incidents()
  $('.incidents').innerHTML = list.length
    ? list
        .slice(0, 8)
        .map(i => {
          const url = can(me, 'operator') ? src.bundleUrl(i) : null
          const pdf = can(me, 'operator') ? src.reportUrl(i) : null
          const head = i.head ? `head ${i.head.slice(0, 16)}… ${kb(i.bytes)}` : '<span class="pending">recording…</span>'
          const files = url
            ? ` <a class="act" href="${url}" download>.rbox</a> <a class="act" href="${pdf}" download>pdf</a>`
            : i.pruned
              ? ' · removed by retention'
              : ''
          return `<li><b>${i.kind.replace('_', ' ')} · ${i.robot}</b><span>${new Date(i.t * 1000).toLocaleTimeString()} · ${head}${files}</span></li>`
        })
        .join('')
    : '<li><span>nothing yet, which is the point</span></li>'
}
incidents()

function showHelp() {
  $('.assist').hidden = !help || session !== null || !can(me, 'driver')
  if (help) $('.assist__what').textContent = `${site.robots.find(r => r.id === help)?.label}: ${last.get(help)?.note || 'blocked'}`
}

src.subscribe(m => {
  if (m.type === 'telemetry') {
    const t = m.data
    last.set(t.robot, t)
    map.update(t)
    const el = li(t.robot)
    if (!el) return
    el.querySelector('.robot__state b')!.textContent = STATUS[t.status] ?? t.status
    el.querySelector<HTMLElement>('.batt i')!.style.width = `${Math.round(t.battery * 100)}%`
    el.querySelector('.robot__pct')!.textContent = `${Math.round(t.battery * 100)}%`
    el.classList.toggle('is-alert', t.status === 'needs_assistance' || t.status === 'estop')
    el.classList.toggle('is-low', t.battery < 0.15)
    if (session?.robot === t.robot) $('.driving__v').textContent = Math.abs(t.speed).toFixed(2)
    return
  }
  const e = m.data
  log(e)
  if (e.kind === 'needs_assistance') {
    help = e.robot
    select(e.robot)
  }
  if ((e.kind === 'assistance_cleared' || e.kind === 'released') && help === e.robot) help = null
  if (e.kind === 'deadman_stop') $('.driving__link').textContent = 'lost'
  if (e.kind.startsWith('incident_')) incidents()
  if (e.kind === 'zone_changed') refreshZones()
  showHelp()
})

async function take(id: string) {
  if (session) return
  const teleop = await src.take(id)
  const bar = $('.deadman i')
  const stop = drive(teleop, {
    onSend: () => {
      $('.driving__link').textContent = 'ok'
      bar.animate([{ transform: 'scaleX(1)' }, { transform: 'scaleX(0)' }], { duration: 250, fill: 'forwards' })
    },
  })
  session = { robot: id, teleop, stop }
  teleop.onClose(() => end(false))
  $('.driving__who').textContent = site.robots.find(r => r.id === id)?.label ?? id
  $('.driving__cap').textContent = String(teleop.limits.linear)
  $('.driving').hidden = false
  showCamera(id)
  $('.cam').classList.add('is-driving')
  showHelp()
}

function end(send = true) {
  if (!session) return
  const s = session
  session = null
  s.stop()
  if (send) s.teleop.release()
  $('.driving').hidden = true
  $('.cam').classList.remove('is-driving')
  showHelp()
}

// -- zones ---------------------------------------------------------------

let zones: Zone[] = site.zones
let draft: [number, number][] | null = null

function listZones() {
  $('.zones').innerHTML = zones
    .map(z => {
      const hours = z.start ? ` · ${z.start}–${z.end}` : ''
      const del = can(me, 'admin') ? `<button type="button" class="act" data-zone="${z.id}">delete</button>` : ''
      return `<li><b>${z.name}<span>${hours}</span></b>${del}</li>`
    })
    .join('')
  map.setZones(zones)
}
listZones()
if (can(me, 'admin')) $('.admin-only').hidden = false

async function refreshZones() {
  zones = await src.zones()
  listZones()
}

function stopDrawing() {
  draft = null
  map.setDraft(null)
  map.onPlanClick(null)
  $('.zone-form').hidden = true
  $('.zones__acts').hidden = !can(me, 'admin')
}

$('.zones__draw').addEventListener('click', () => {
  draft = []
  map.setDraft(draft)
  map.onPlanClick((x, y) => {
    draft?.push([x, y])
    map.setDraft(draft)
  })
  $('.zone-form').hidden = false
  $('.zones__acts').hidden = true
  $('.zone-form__err').textContent = ''
})
$('.zone-form__undo').addEventListener('click', () => {
  draft?.pop()
  map.setDraft(draft)
})
$('.zone-form__cancel').addEventListener('click', stopDrawing)
$('.zone-form').addEventListener('submit', async e => {
  e.preventDefault()
  if (!draft || draft.length < 3) {
    $('.zone-form__err').textContent = 'three corners at least'
    return
  }
  const data = new FormData(e.target as HTMLFormElement)
  const name = String(data.get('name')).trim()
  const [start, end] = [String(data.get('start') ?? ''), String(data.get('end') ?? '')]
  if (!!start !== !!end) {
    $('.zone-form__err').textContent = 'both hours, or neither'
    return
  }
  const id = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || `zone-${Date.now()}`
  try {
    await src.putZone({ id, name, polygon: draft, margin: 1, ...(start ? { start, end } : {}) })
  } catch (err) {
    $('.zone-form__err').textContent = (err as Error).message
    return
  }
  ;(e.target as HTMLFormElement).reset()
  stopDrawing()
  refreshZones()
})
$('.zones').addEventListener('click', async e => {
  const id = (e.target as HTMLElement).dataset.zone
  if (!id || !confirm(`Delete the zone "${zones.find(z => z.id === id)?.name}"? Robots will no longer stop at it.`)) return
  await src.deleteZone(id)
  refreshZones()
})

$('.assist__take').addEventListener('click', () => help && take(help))
$('.driving__release').addEventListener('click', () => end())
addEventListener('keydown', e => {
  if (e.code === 'Space' && help && !session && can(me, 'driver')) {
    e.preventDefault()
    take(help)
  } else if (e.code === 'Enter' && session) {
    e.preventDefault()
    end()
  } else if (e.code === 'Escape' && draft) {
    stopDrawing()
  }
})

for (const b of document.querySelectorAll<HTMLButtonElement>('[data-fail]')) {
  b.addEventListener('click', () => src.fail(selected, b.dataset.fail as Failure))
}
