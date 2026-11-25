import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { plan, robots, zones } from './demo-site'

const toml = readFileSync(new URL('../../../deploy/demo/fleet.toml', import.meta.url), 'utf-8')
const flat = (v: unknown) => JSON.stringify(v).replace(/\s/g, '')
const inToml = (v: unknown) => toml.replace(/\s/g, '').replaceAll('.0,', ',').includes(flat(v).slice(1, -1))

describe('the in-page demo site', () => {
  it('drives the same routes as the simulator', () => {
    for (const r of robots) {
      expect(toml).toContain(`id = "${r.id}"`)
      expect(inToml(r.route), r.id).toBe(true)
    }
  })

  it('has the same racks and zones as the core', () => {
    expect(inToml(plan.racks)).toBe(true)
    for (const z of zones) expect(inToml(z.polygon), z.id).toBe(true)
  })
})
