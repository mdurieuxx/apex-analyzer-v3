const BASE = '/api'

async function req<T>(path: string, opts?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, opts)
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json() as Promise<T>
}

export const api = {
  config: {
    get: () => req<import('../types').AppConfig>('/config'),
    update: (data: Partial<import('../types').AppConfig>) =>
      req<import('../types').AppConfig>('/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      }),
  },
  status: () => req<{ connected: boolean; title1: string; title2: string; session_type: string; countdown: number; ws_port: number }>('/status'),
  grid: () => req<{ drivers: import('../types').Driver[] }>('/grid'),
  pits: {
    live: () => req<{ lanes: import('../types').PitLane[]; active: import('../types').ActivePitStop[] }>('/pits/live'),
    history: () => req<{ history: import('../types').PitHistoryEntry[] }>('/pits/history'),
  },
  karts: {
    list: () => req<{ karts: import('../types').PhysicalKart[] }>('/karts'),
    create: (label: string, notes = '') =>
      req('/karts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ label, notes }) }),
    delete: (id: number) => req(`/karts/${id}`, { method: 'DELETE' }),
  },
  assignments: {
    set: (driver_id: string, kart_label: string) =>
      req('/assignments', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ driver_id, kart_label }) }),
  },
  reserve: {
    add: (kart_label: string, lane: number) =>
      req('/pit-reserve/add', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kart_label, lane }) }),
    remove: (kart_label: string) => req(`/pit-reserve/${kart_label}`, { method: 'DELETE' }),
  },
  performance: () => req<{ karts: import('../types').KartPerformance[] }>('/performance'),
  driverLaps: (driver_id: string) => req(`/driver/${driver_id}/laps`),
  circuits: {
    list: () => req<{ circuits: import('../types').Circuit[] }>('/circuits'),
    create: (data: Partial<import('../types').Circuit>) =>
      req<import('../types').Circuit>('/circuits', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      }),
    update: (id: number, data: Partial<import('../types').Circuit>) =>
      req<import('../types').Circuit>(`/circuits/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      }),
    delete: (id: number) => req(`/circuits/${id}`, { method: 'DELETE' }),
  },
  circuitPresets: () => req<{ presets: import('../types').CircuitPreset[] }>('/circuit-presets'),
  events: {
    list: () => req<{ events: import('../types').KartingEvent[] }>('/events'),
    create: (data: import('../types').KartingEventCreate) =>
      req<import('../types').KartingEvent>('/events', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      }),
    update: (id: number, data: Partial<import('../types').KartingEventCreate>) =>
      req<import('../types').KartingEvent>(`/events/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      }),
    delete: (id: number) => req(`/events/${id}`, { method: 'DELETE' }),
    activate: (id: number) => req(`/events/${id}/activate`, { method: 'POST' }),
  },
}
