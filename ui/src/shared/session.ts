const base = import.meta.env.BASE_URL.replace(/\/$/, '')

export type Role = 'viewer' | 'operator' | 'driver' | 'admin'
export interface Me {
  name: string
  role: Role
  open: boolean
  accounts: boolean
}

const RANK: Record<Role, number> = { viewer: 1, operator: 2, driver: 3, admin: 4 }
export const can = (me: Me | null, role: Role) => !me || RANK[me.role] >= RANK[role]

/** Who is logged in: a user, 'login' when the core wants one, or null when there is no core at all. */
export async function whoami(): Promise<Me | 'login' | null> {
  try {
    const r = await fetch(`${base}/api/me`, { signal: AbortSignal.timeout(1500) })
    if (r.status === 401) return 'login'
    if (!r.ok || !r.headers.get('content-type')?.includes('json')) return null
    return r.json()
  } catch {
    return null
  }
}

export async function login(name: string, password: string): Promise<Me | string> {
  const r = await fetch(`${base}/api/login`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ name, password }),
  })
  if (!r.ok) return (await r.json().catch(() => null))?.detail ?? r.statusText
  return (await whoami()) as Me
}

export const logout = () => fetch(`${base}/api/logout`, { method: 'POST' }).then(() => location.reload())
