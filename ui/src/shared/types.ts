export type Status = 'ok' | 'needs_assistance' | 'estop' | 'paused' | 'teleop' | 'offline'

export interface Telemetry {
  robot: string
  x: number
  y: number
  heading: number
  speed: number
  battery: number
  status: Status
  blocked: boolean
  estop: boolean
  note: string
  t: number
}

export interface FleetEvent {
  kind: string
  robot: string
  detail: Record<string, unknown>
  t: number
}

export interface Robot {
  id: string
  label: string
  kind: string
  protocol: 'vda5050' | 'ros2' | 'rest'
  can_drive: boolean
  last: Telemetry | null
}

export interface Zone {
  id: string
  name: string
  polygon: [number, number][]
  margin: number
  start?: string
  end?: string
}

export interface Plan {
  width: number
  height: number
  racks: [number, number, number, number][]
  dock?: [number, number, number, number]
  charger?: [number, number]
  /** walls from an imported DXF, metres */
  lines?: [number, number, number, number][]
  /** a scan of the drawing, and where it sits on the plan in metres: x, y, width, height */
  image?: string
  image_box?: [number, number, number, number]
}

export interface Site {
  name: string
  plan: Plan
  robots: Robot[]
  zones: Zone[]
  demo: boolean
}

export interface Incident {
  id: string
  robot: string
  kind: string
  t: number
  bundle: string | null
  head: string | null
  bytes: number | null
  /** when retention removed the file; it may still be in the export folder */
  pruned?: number | null
}

export type Failure = 'obstacle' | 'battery' | 'estop' | 'link'

/** What the console and the site's demo talk to: the real core, or the in-page simulation. */
export interface Source {
  site: Site
  live: boolean
  subscribe(fn: (m: { type: 'telemetry'; data: Telemetry } | { type: 'event'; data: FleetEvent }) => void): void
  take(robot: string): Promise<Teleop>
  pause(robot: string): Promise<void>
  resume(robot: string): Promise<void>
  fail(robot: string, kind: Failure): Promise<void>
  incidents(): Promise<Incident[]>
  putZone(z: Zone): Promise<void>
  deleteZone(id: string): Promise<void>
  zones(): Promise<Zone[]>
  bundleUrl(i: Incident): string | null
  reportUrl(i: Incident): string | null
}

export interface Teleop {
  send(linear: number, angular: number): void
  release(): void
  onClose(fn: (reason: string) => void): void
  limits: { linear: number; angular: number }
}
