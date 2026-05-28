const BASE = '/api'
const PROXY_BASE = '/proxy-api'

async function proxyReq<T>(path: string, opts?: RequestInit): Promise<T> {
  const r = await fetch(`${PROXY_BASE}${path}`, opts)
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json() as Promise<T>
}

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
  refreshGrid: () => req<{ ok: boolean; source: string }>('/refresh-grid', { method: 'POST' }),
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
  performance: () => req<{ teams: import('../types').TeamPerformance[] }>('/performance'),
  perfTeamStints: (teamId: string) => req<{ stints: import('../types').StintDetail[] }>(`/performance/${teamId}/stints`),
  seedFromHistory: () => req<{ seeded_teams: number; source_event_id: number; source_event_name: string }>('/performance/seed-from-history', { method: 'POST' }),
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
    reset: (id: number) => req(`/events/${id}/reset`, { method: 'POST' }),
    stop: (id: number) => req(`/events/${id}/stop`, { method: 'POST' }),
    start: (id: number) => req(`/events/${id}/start`, { method: 'POST' }),
    reanalyze: (id: number) => req<{ ok: boolean; updated_stints: number }>(`/events/${id}/reanalyze`, { method: 'POST' }),
  },
  disconnect: () => req('/disconnect', { method: 'POST' }),
  connect: (payload: { source: 'live'; circuit_url: string; ws_port_override: number; min_pit_duration_s?: number; min_relay_duration_s?: number; max_relay_duration_s?: number } | { source: 'proxy'; proxy_ws_url: string }) =>
    req('/connect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }),
  proxySessions: () => req<{ sessions: import('../types').ProxySession[] }>('/proxy/sessions'),
  import: {
    start: (recording_name: string, event_id?: number) =>
      req<{ ok: boolean; event_id: number; recording_name: string }>('/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recording_name, ...(event_id ? { event_id } : {}) }),
      }),
    status: () => req<{ status: string; processed: number; total: number; pct: number; error?: string; event_id?: number; resumed_from_t?: number; recording_max_t?: number; recording_name?: string; queue_remaining?: number }>('/import/status'),
    startSession: (recordings: string[]) =>
      req<{ ok: boolean; recordings: string[] }>('/import-session', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recordings }),
      }),
  },
  proxy: {
    status: () => proxyReq<import('../types').ProxyStatus>('/status'),
    recordings: () => proxyReq<{ recordings: import('../types').ProxyRecording[] }>('/recordings'),
    deleteRecording: (name: string) => proxyReq(`/recordings/${name}`, { method: 'DELETE' }),
    startLive: (data: { circuit_url: string; ws_port: number; record: boolean; name?: string }) =>
      proxyReq('/live', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }),
    startReplay: (name: string, speed: number) =>
      proxyReq('/replay', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, speed }) }),
    stop: () => proxyReq('/stop', { method: 'POST' }),
    setSpeed: (speed: number) => proxyReq('/speed', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ speed }) }),
    circuits: () => proxyReq<{ circuits: import('../types').ProxyCircuit[] }>('/circuits'),
    startRecord: (data: { circuit_url: string; ws_port: number; name?: string }) =>
      proxyReq('/record', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }),
    stopRecord: () => proxyReq('/stop-record', { method: 'POST' }),
    schedule: {
      list: () => proxyReq<{ jobs: import('../types').ScheduledJob[] }>('/schedule'),
      create: (data: { circuit_url: string; ws_port: number; start_at: string; name_prefix?: string; duration_minutes?: number }) =>
        proxyReq<{ ok: boolean; job: import('../types').ScheduledJob }>('/schedule', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
        }),
      cancel: (id: string) => proxyReq(`/schedule/${id}`, { method: 'DELETE' }),
    },
    calendar: {
      list: () => proxyReq<{ events: import('../types').CalendarEvent[]; last_sync: string | null }>('/calendar'),
      sync: () => proxyReq<{ ok: boolean }>('/calendar/sync', { method: 'POST' }),
      schedule: (uid: string) => proxyReq<{ ok: boolean; job?: object; already_scheduled?: boolean }>(`/calendar/${uid}/schedule`, { method: 'POST' }),
    },
    discovery: {
      stats: () => proxyReq<import('../types').DiscoveryStats>('/discovery/stats'),
      logs: () => proxyReq<{ logs: import('../types').DiscoveryLog[]; running: boolean }>('/discovery/logs'),
      run: () => proxyReq<{ ok: boolean; processed?: number; msg?: string }>('/discovery/run', { method: 'POST' }),
    },
    listConfigs: () => req<{ source: string; active_ws_url: string; proxies: import('../types').SavedProxy[] }>('/proxy-configs'),
    createConfig: (name: string, ws_url: string) =>
      req('/proxy-configs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, ws_url }) }),
    deleteConfig: (id: number) => req(`/proxy-configs/${id}`, { method: 'DELETE' }),
    activateProxy: (id: number) => req(`/proxy-configs/${id}/activate`, { method: 'POST' }),
    switchToLive: () => req('/source/live', { method: 'POST' }),
  },
  stats: {
    event:        (id: number) => req<import('../types').EventStatsResponse>(`/stats/events/${id}`),
    entry:        (id: number) => req<import('../types').EntryDetail>(`/stats/entries/${id}`),
    pilots:       (id: number) => req<{ pilots: import('../types').PilotStat[] }>(`/stats/events/${id}/pilots`),
    search:       (q: string)  => req<{ results: import('../types').SearchResult[] }>(`/stats/search?q=${encodeURIComponent(q)}`),
    pilotProfile: (name: string) => req<import('../types').PilotProfile>(`/stats/pilot-profile?name=${encodeURIComponent(name)}`),
    teamProfile:  (name: string) => req<import('../types').TeamProfile>(`/stats/team-profile?name=${encodeURIComponent(name)}`),
  },
}
