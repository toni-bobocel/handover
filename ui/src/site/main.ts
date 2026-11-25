import '@fontsource/host-grotesk/400.css'
import '@fontsource/host-grotesk/500.css'
import '@fontsource/host-grotesk/600.css'
import '@fontsource/host-grotesk/800.css'
import '@fontsource/fragment-mono/400.css'
import '@fontsource/doto/700.css'
import '@fontsource/silkscreen/400.css'
import '../styles/site.css'

import gsap from 'gsap'
import { CustomEase } from 'gsap/CustomEase'
import { DrawSVGPlugin } from 'gsap/DrawSVGPlugin'
import { ScrambleTextPlugin } from 'gsap/ScrambleTextPlugin'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { SplitText } from 'gsap/SplitText'
import { mountDemo } from './demo'
import { type HandsState, mountHand, mountHands } from './hands'

gsap.registerPlugin(ScrollTrigger, SplitText, ScrambleTextPlugin, DrawSVGPlugin, CustomEase)
// a hand reaching: quick to leave, long to settle, no overshoot
CustomEase.create('reach', 'M0,0 C0.22,0.6 0.18,0.98 1,1')

const $ = <T extends Element = HTMLElement>(s: string, root: ParentNode = document) => root.querySelector<T>(s)!
const $$ = <T extends Element = HTMLElement>(s: string, root: ParentNode = document) => [...root.querySelectorAll<T>(s)]
const calm = matchMedia('(prefers-reduced-motion: reduce)').matches

const stage = $('.hero__stage')
const top = $('.top')
const state: HandsState = { arrive: 0, dots: 0, night: 0, settle: 0 }
let placeGap = () => {}

// the recorder clock runs from the moment the page starts, like the real thing
const clock = $('.rec__clock')
const t0 = performance.now()
const tickClock = () => {
  const s = (performance.now() - t0) / 1000
  const hh = String(Math.floor(s / 3600)).padStart(2, '0')
  const mm = String(Math.floor(s / 60) % 60).padStart(2, '0')
  clock.textContent = `${hh}:${mm}:${(s % 60).toFixed(1).padStart(4, '0')}`
}
gsap.ticker.add(tickClock)
gsap.to('.rec__dot', { opacity: 0.2, duration: 0.5, repeat: -1, yoyo: true, ease: 'steps(1)' })

const img = new Image()
img.src = `${import.meta.env.BASE_URL}hands.webp`

Promise.all([img.decode(), document.fonts.ready]).then(() => {
  const hands = mountHands($<HTMLCanvasElement>('.hands'), img, state)
  placeGap = () => {
    const g = hands.gap()
    stage.style.setProperty('--gap-x', `${g.x}px`)
    stage.style.setProperty('--gap-y', `${g.y}px`)
  }
  placeGap()
  hands.onLayout(placeGap)

  intro()
  scrollStory()
  bento()
  mountHand($<HTMLCanvasElement>('.word__hand'), img, wordHand)
})

function intro() {
  const lines = new SplitText('.hero__title .line', { type: 'lines', mask: 'lines' })
  const tl = gsap.timeline({ defaults: { ease: 'reach' } })
  tl.set('.hero__copy, .hero__scroll, .sections, .mark, .top__src', { autoAlpha: 1 })
    .from('.mark, .sections, .top__src', { y: -14, autoAlpha: 0, duration: 0.9, stagger: 0.06, ease: 'power3.out' }, 0.2)
    .to(state, { arrive: 1, duration: calm ? 0.01 : 2.3 }, 0.15)
    .fromTo('.spark', { scale: 0, autoAlpha: 1 }, { scale: 1, duration: 0.35, ease: 'back.out(3)' }, 2.05)
    .to('.spark', { boxShadow: '0 0 0 26px rgb(255 166 48 / 0)', duration: 1.1, ease: 'power2.out' }, 2.1)
    .to('.spark', { autoAlpha: 0, duration: 0.8 }, 3)
    .from(lines.lines, { yPercent: 110, duration: 1.2, stagger: 0.12, ease: 'expo.out' }, 1.75)
    .from('.hero__lede', { y: 18, autoAlpha: 0, duration: 1, ease: 'power3.out' }, 2.1)
    .from('.hero__scroll', { autoAlpha: 0, duration: 0.8 }, 2.4)
    .to('.rec', { autoAlpha: 0, duration: 0.6, onComplete: () => gsap.ticker.remove(tickClock) }, 2.6)
}

function scrollStory() {
  const win = $('.win')
  const lines = $$('.win__line')
  const cmd = $('.win__cmd [data-text]')
  const night = { v: 0 }

  const tl = gsap.timeline({
    defaults: { ease: 'none' },
    scrollTrigger: {
      trigger: '.hero',
      start: 'top top',
      end: 'bottom bottom',
      scrub: calm ? true : 0.8,
      onUpdate: self => {
        stage.style.setProperty('--p', String(self.progress))
        $('.hero__scroll').style.setProperty('--p', String(Math.min(1, self.progress * 4)))
      },
    },
  })

  tl.to('.hero__copy', { y: -60, autoAlpha: 0, duration: 0.14, ease: 'power2.in' }, 0.02)
    .to('.hero__scroll', { autoAlpha: 0, duration: 0.06 }, 0.02)
    .to(state, { dots: 1, duration: 0.42, ease: 'power1.inOut' }, 0.08)
    .to(state, { settle: 1, duration: 0.4, ease: 'power2.inOut', onUpdate: () => placeGap() }, 0.1)
    .to(night, {
      v: 1,
      duration: 0.36,
      ease: 'power2.inOut',
      onUpdate: () => {
        state.night = night.v
        const c = gsap.utils.interpolate('#dbdad6', '#0a0a0b', night.v)
        stage.style.backgroundColor = c
        top.classList.toggle('is-night', night.v > 0.5)
      },
    }, 0.16)
    .set(win, { visibility: 'visible' }, 0.56)
    .fromTo('.win__frame rect', { drawSVG: '50% 50%' }, { drawSVG: '0% 100%', duration: 0.08, ease: 'power2.out' }, 0.56)
    .fromTo('.win__frame rect', { fillOpacity: 0 }, { fillOpacity: 1, duration: 0.05 }, 0.6)
    .from('.win__bar', { autoAlpha: 0, y: -6, duration: 0.05 }, 0.62)
    .from('.win__meta', { autoAlpha: 0, duration: 0.04 }, 0.65)

  lines.forEach((el, i) => {
    tl.fromTo(el, { scrambleText: { text: ' ', chars: '░▒▓█' } },
      { scrambleText: { text: el.dataset.text!, chars: 'upperAndLowerCase', speed: 0.6 }, duration: 0.07 }, 0.68 + i * 0.07)
  })
  tl.fromTo(cmd, { scrambleText: { text: ' ', chars: '01' } }, { scrambleText: { text: cmd.dataset.text!, chars: '01', speed: 0.8 }, duration: 0.08 }, 0.9)
    .to({}, { duration: 0.02 })

  // past the hero, the top bar stays in its night colours
  ScrollTrigger.create({
    trigger: '.bento',
    start: 'top 60px',
    onEnter: () => top.classList.add('is-night', 'is-solid'),
    onLeaveBack: () => {
      top.classList.remove('is-solid')
      top.classList.toggle('is-night', night.v > 0.5)
    },
  })
}

const wordHand = { gather: 0 }

function bento() {
  // the section index: a thin bar slides under whichever card is in view
  const links = $$<HTMLAnchorElement>('.sections a')
  const bar = $('.sections__bar')
  const mark = (a: HTMLAnchorElement | null) => {
    for (const l of links) l.classList.toggle('is-on', l === a)
    if (!a) return void gsap.to(bar, { width: 0, duration: 0.4, ease: 'power3.out' })
    gsap.to(bar, { x: a.offsetLeft, width: a.offsetWidth, duration: 0.5, ease: 'power3.out' })
  }
  for (const a of links) {
    const target = $(a.hash)
    ScrollTrigger.create({
      trigger: target,
      start: 'top 55%',
      end: 'bottom 45%',
      onToggle: self => self.isActive && mark(a),
    })
  }
  ScrollTrigger.create({ trigger: '.hero', start: 'top top', end: 'bottom 55%', onEnter: () => mark(null), onEnterBack: () => mark(null) })

  const chars = new SplitText('.word span', { type: 'chars' })
  gsap.timeline({ scrollTrigger: { trigger: '.card--word', start: 'top 80%' } })
    .from('.card--word', { clipPath: 'inset(18% 6% 0% 6% round 18px)', duration: 1.4, ease: 'expo.out' })
    .from(chars.chars, { yPercent: 105, duration: 1.1, stagger: 0.045, ease: 'expo.out' }, 0.1)
    .to(wordHand, { gather: 1, duration: 2.4, ease: 'power2.out' }, 0.3)
    .from('.card--word__foot > *', { y: 14, autoAlpha: 0, duration: 0.8, stagger: 0.1, ease: 'power3.out' }, 0.6)

  gsap.from('.grid > .card', {
    clipPath: 'inset(28% 0% 0% 0% round 18px)',
    y: 50,
    autoAlpha: 0,
    duration: 1.1,
    stagger: { each: 0.07, from: 'start' },
    ease: 'expo.out',
    scrollTrigger: { trigger: '.grid', start: 'top 85%' },
  })

  for (const s of $$('.stat')) {
    ScrollTrigger.create({
      trigger: s,
      start: 'top 90%',
      once: true,
      onEnter: () => gsap.fromTo(s, { scrambleText: { text: '000', chars: '0123456789' } },
        { scrambleText: { text: s.dataset.value!, chars: '0123456789', speed: 0.4 }, duration: 1.3, delay: 0.3 }),
    })
  }

  chain()
  zones()
  mountDemo($('.card--demo'))

  const copy = $('.copy')
  copy.addEventListener('click', async () => {
    await navigator.clipboard.writeText($('.cmd code').textContent ?? '')
    gsap.timeline()
      .to(copy, { scrambleText: { text: 'copied', chars: 'lowerCase' }, duration: 0.4 })
      .to(copy, { scrambleText: { text: 'copy', chars: 'lowerCase' }, duration: 0.4 }, 1.6)
  })
}

// A real SHA-256 chain over made-up telemetry, computed here as the list scrolls.
function chain() {
  const list = $('.chain')
  let prev = '0'.repeat(64)
  let seq = 0
  const enc = new TextEncoder()
  const hex = (b: ArrayBuffer) => [...new Uint8Array(b)].map(x => x.toString(16).padStart(2, '0')).join('')
  const add = async () => {
    seq++
    const x = (12 + Math.sin(seq / 7) * 6).toFixed(2)
    const y = (6.5 + Math.cos(seq / 9) * 2).toFixed(2)
    const rec = seq % 23 === 0 ? `event  takeover` : `telemetry  x ${x}  y ${y}`
    prev = hex(await crypto.subtle.digest('SHA-256', enc.encode(prev + rec)))
    const li = document.createElement('li')
    li.innerHTML = `${String(seq).padStart(4, '0')}  ${rec}  <b>${prev.slice(0, 12)}</b>`
    list.append(li)
    if (list.children.length > 14) list.firstElementChild!.remove()
    gsap.from(li, { y: 10, autoAlpha: 0, duration: 0.4, ease: 'power2.out' })
  }
  let timer = 0
  ScrollTrigger.create({
    trigger: list,
    start: 'top bottom',
    end: 'bottom top',
    onToggle: self => {
      clearInterval(timer)
      if (self.isActive) timer = window.setInterval(add, 380)
    },
  })
  for (let i = 0; i < 10; i++) add()
}

function zones() {
  const svg = $<SVGSVGElement>('.zones__art')
  const hatch = $('.zones__hatch', svg)
  const ns = 'http://www.w3.org/2000/svg'
  // hatching clipped to the zone by hand: three-line SVG beats a clipPath id for one card
  for (let k = 0; k < 22; k++) {
    const l = document.createElementNS(ns, 'line')
    const x = 196 + k * 10
    l.setAttribute('x1', String(Math.min(x, 300)))
    l.setAttribute('y1', String(22 + Math.max(0, x - 300)))
    l.setAttribute('x2', String(Math.max(196, x - 106)))
    l.setAttribute('y2', String(128 - Math.max(0, 196 - (x - 106))))
    hatch.append(l)
  }
  const bot = $('.zones__bot', svg)
  const tl = gsap.timeline({ repeat: -1, repeatDelay: 0.6, paused: true })
  tl.set(bot, { x: 20, y: 75, rotation: 0 })
    .set('.zones__dim, .zones__mm', { opacity: 0 })
    .call(() => bot.classList.remove('is-stopped'))
    .to(bot, { x: 148, duration: 2.6, ease: 'power2.out' })
    .call(() => bot.classList.add('is-stopped'))
    .to('.zones__dim', { opacity: 1, duration: 0.3 })
    .fromTo('.zones__mm', { opacity: 0, y: 4 }, { opacity: 1, y: 0, duration: 0.3 }, '<')
    .to({}, { duration: 1.6 })
    .to(bot, { opacity: 0, duration: 0.4 })
    .set(bot, { opacity: 1 })
  ScrollTrigger.create({ trigger: svg, start: 'top bottom', end: 'bottom top', onToggle: s => (s.isActive ? tl.play() : tl.pause()) })
}
