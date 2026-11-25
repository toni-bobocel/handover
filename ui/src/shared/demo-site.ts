import type { Plan, Robot, Zone } from './types'

// Mirrors deploy/demo/fleet.toml so the page can run the demo with no core
// behind it (GitHub Pages). demo-site.test.ts fails if the two drift apart.

export const plan: Plan = {
  width: 48,
  height: 28,
  racks: [
    [6, 4, 14, 1.2], [6, 8.5, 14, 1.2], [6, 13, 14, 1.2], [6, 17.5, 14, 1.2],
    [24, 4, 10, 1.2], [24, 8.5, 10, 1.2], [24, 13, 10, 1.2],
  ],
  dock: [40, 2, 7, 7],
  charger: [2, 24],
}

export const zones: Zone[] = [
  { id: 'dock', name: 'Truck dock, doors open', polygon: [[40, 2], [47, 2], [47, 9], [40, 9]], margin: 1 },
  {
    id: 'picking',
    name: 'Manual picking, morning shift',
    polygon: [[24, 18], [34, 18], [34, 24], [24, 24]],
    margin: 1,
    start: '08:00',
    end: '10:00',
  },
]

export interface SimRobot extends Omit<Robot, 'last'> {
  speed: number
  route: [number, number][]
}

export const robots: SimRobot[] = [
  {
    id: 'AMR-Logistics-01', label: 'AMR Logistics 01', kind: 'Autonomous mobile robot', protocol: 'vda5050',
    can_drive: false, speed: 1.2,
    route: [[3, 6.5], [22, 6.5], [22, 15.2], [37, 15.2], [37, 11], [38.5, 5.5], [37, 2.5], [3, 2.5]],
  },
  {
    id: 'Humanoid-Inspect-02', label: 'Humanoid Inspect 02', kind: 'Humanoid, inspection rounds', protocol: 'ros2',
    can_drive: true, speed: 0.7,
    route: [[4, 11], [21, 11], [21, 16.2], [36, 16.2], [36, 26], [4, 26]],
  },
  {
    id: 'Cleaner-Bot-03', label: 'Cleaner Bot 03', kind: 'Floor scrubber', protocol: 'rest',
    can_drive: true, speed: 0.5,
    route: [[23, 6.5], [35, 6.5], [35, 11], [23, 11], [23, 15.6], [36, 15.6], [36, 3], [23, 3]],
  },
]
