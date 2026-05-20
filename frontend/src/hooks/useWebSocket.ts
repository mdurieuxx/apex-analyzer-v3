import { useEffect, useRef, useCallback, useState } from 'react'
import type { WsMessage, WsSnapshot, Driver, PitLane, PitHistoryEntry, ReserveSummary } from '../types'

const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`
const RECONNECT_DELAY = 3000
const FLASH_DURATION_MS = 900

export interface ImportStatus {
  status: 'idle' | 'running' | 'done' | 'error'
  processed: number
  total: number
  pct: number
  error?: string
}

export interface LiveState {
  connected: boolean
  wsConnected: boolean
  activeEventId: number | null
  activeEventName: string
  title1: string
  title2: string
  sessionType: string
  countdown: number
  minRelayS: number
  maxRelayS: number
  drivers: Driver[]
  lanes: PitLane[]
  reserveSummary: ReserveSummary
  pitHistory: PitHistoryEntry[]
  lastPitStop: { bib: string; team: string; kart_label: string; position: number; timestamp: string } | null
  flashingIds: Set<string>
  // Accumulated pilot names per team across the session
  pilotsByTeam: Map<string, string[]>
  // Wall-clock time (ms) when each driver entered the pits (for live timer)
  pitEntryTimes: Record<string, number>
  importStatus: ImportStatus
  wsClients: number
  trackRefLapMs: number | null
}

const DEFAULT_STATE: LiveState = {
  connected: false,
  wsConnected: false,
  activeEventId: null,
  activeEventName: '',
  title1: '',
  title2: '',
  sessionType: 'unknown',
  countdown: 0,
  minRelayS: 3600,
  maxRelayS: 5400,
  drivers: [],
  lanes: [],
  reserveSummary: { rocket: 0, fast: 0, medium: 0, bad: 0, unknown: 100 },
  pitHistory: [],
  lastPitStop: null,
  flashingIds: new Set(),
  pilotsByTeam: new Map(),
  pitEntryTimes: {},
  importStatus: { status: 'idle', processed: 0, total: 0, pct: 0 },
  wsClients: 0,
  trackRefLapMs: null,
}

export function useWebSocket() {
  const [live, setLive] = useState<LiveState>(DEFAULT_STATE)
  const ws = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>()
  // Previous values for change detection
  const prevLastLap = useRef<Map<string, string>>(new Map())
  const prevPosition = useRef<Map<string, number>>(new Map())
  // Flash timers per driver
  const flashTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  const flashDrivers = useCallback((ids: string[]) => {
    if (!ids.length) return
    setLive(s => {
      const next = new Set(s.flashingIds)
      ids.forEach(id => next.add(id))
      return { ...s, flashingIds: next }
    })
    ids.forEach(id => {
      const existing = flashTimers.current.get(id)
      if (existing) clearTimeout(existing)
      flashTimers.current.set(id, setTimeout(() => {
        setLive(s => {
          const next = new Set(s.flashingIds)
          next.delete(id)
          return { ...s, flashingIds: next }
        })
        flashTimers.current.delete(id)
      }, FLASH_DURATION_MS))
    })
  }, [])

  const trackDrivers = useCallback((drivers: Driver[]) => {
    const changed: string[] = []
    drivers.forEach(d => {
      const lapChanged = d.last_lap && d.last_lap !== prevLastLap.current.get(d.driver_id)
      const posChanged = prevPosition.current.has(d.driver_id) && d.position !== prevPosition.current.get(d.driver_id)
      if (lapChanged || posChanged) changed.push(d.driver_id)
      if (d.last_lap) prevLastLap.current.set(d.driver_id, d.last_lap)
      prevPosition.current.set(d.driver_id, d.position)
    })
    flashDrivers(changed)
    // Accumulate pilot names per team
    setLive(s => {
      const pilots = new Map(s.pilotsByTeam)
      drivers.forEach(d => {
        if (!d.driver_name) return
        const list = pilots.get(d.driver_id) ?? []
        if (!list.includes(d.driver_name)) {
          pilots.set(d.driver_id, [...list, d.driver_name])
        }
      })
      return { ...s, pilotsByTeam: pilots }
    })
  }, [flashDrivers])

  const connect = useCallback(() => {
    if (ws.current?.readyState === WebSocket.OPEN) return

    const socket = new WebSocket(WS_URL)
    ws.current = socket

    socket.onopen = () => setLive(s => ({ ...s, wsConnected: true }))

    socket.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data) as WsMessage
        handleMessage(msg)
      } catch { /* ignore */ }
    }

    socket.onclose = () => {
      setLive(s => ({ ...s, wsConnected: false }))
      reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY)
    }

    socket.onerror = () => socket.close()
  }, [])

  const handleMessage = useCallback((msg: WsMessage) => {
    const { event, data } = msg

    if (event === 'snapshot') {
      const d = data as WsSnapshot
      const now = Date.now()
      setLive(s => {
        const pitEntryTimes = { ...s.pitEntryTimes }
        if (d.drivers) {
          d.drivers.forEach(dr => {
            if (dr.in_pit && !pitEntryTimes[dr.driver_id]) pitEntryTimes[dr.driver_id] = now
            else if (!dr.in_pit) delete pitEntryTimes[dr.driver_id]
          })
        }
        return {
          ...s,
          activeEventId: d.active_event_id ?? null,
          activeEventName: d.active_event_name ?? '',
          title1: d.title1,
          title2: d.title2,
          sessionType: d.session_type,
          countdown: d.countdown,
          minRelayS: d.min_relay_s ?? s.minRelayS,
          maxRelayS: d.max_relay_s ?? s.maxRelayS,
          connected: d.connected,
          wsClients: d.ws_clients ?? s.wsClients,
          trackRefLapMs: d.track_ref_lap_ms ?? s.trackRefLapMs,
          drivers: d.drivers ?? s.drivers,
          lanes: d.lanes ?? s.lanes,
          reserveSummary: d.reserve_summary ?? s.reserveSummary,
          pitHistory: d.pit_history ?? s.pitHistory,
          pitEntryTimes,
        }
      })
      if (d.drivers) trackDrivers(d.drivers)
    } else if (event === 'grid') {
      const d = data as { drivers?: Driver[]; lanes?: PitLane[]; reserve_summary?: ReserveSummary }
      setLive(s => ({
        ...s,
        ...(d.drivers ? { drivers: d.drivers } : {}),
        ...(d.lanes ? { lanes: d.lanes } : {}),
        ...(d.reserve_summary ? { reserveSummary: d.reserve_summary } : {}),
      }))
      if (d.drivers) trackDrivers(d.drivers)
    } else if (event === 'connected') {
      setLive(s => ({ ...s, connected: true }))
    } else if (event === 'disconnected') {
      setLive(s => ({ ...s, connected: false }))
    } else if (event === 'session_update') {
      const d = data as { title1: string; title2: string }
      setLive(s => ({ ...s, title1: d.title1, title2: d.title2 }))
    } else if (event === 'pit_stop') {
      const d = data as { bib: string; team: string; kart_label: string; position: number; timestamp: string; driver_id: string; pit_number: number }
      const now = Date.now()
      setLive(s => ({
        ...s,
        pitEntryTimes: { ...s.pitEntryTimes, [d.driver_id]: now },
        drivers: s.drivers.map(dr => dr.driver_id === d.driver_id ? { ...dr, in_pit: true } : dr),
        lastPitStop: d,
        pitHistory: [
          { bib: d.bib, team: d.team, kart_in: d.kart_label, kart_out: null, position: d.position, pit_number: d.pit_number, pit_lap_ms: null, timestamp: d.timestamp, duration_s: null },
          ...s.pitHistory,
        ].slice(0, 100),
      }))
    } else if (event === 'pit_out') {
      const d = data as { driver_id: string; bib: string; team: string; new_kart_label: string | null; pit_lap_ms: number | null; duration_s: number | null }
      setLive(s => {
        const { [d.driver_id]: _, ...restTimes } = s.pitEntryTimes
        return {
          ...s,
          pitEntryTimes: restTimes,
          drivers: s.drivers.map(dr => dr.driver_id === d.driver_id ? { ...dr, in_pit: false } : dr),
          pitHistory: s.pitHistory.map(p =>
            p.bib === d.bib && p.kart_out === null
              ? { ...p, kart_out: d.new_kart_label, pit_lap_ms: d.pit_lap_ms, duration_s: d.duration_s }
              : p
          ),
        }
      })
    } else if (event === 'pit_lap_update') {
      const d = data as { bib: string; pit_number: number; pit_lap_ms: number }
      setLive(s => ({
        ...s,
        pitHistory: s.pitHistory.map(p =>
          p.bib === d.bib && p.pit_number === d.pit_number
            ? { ...p, pit_lap_ms: d.pit_lap_ms }
            : p
        ),
      }))
    } else if (event === 'import_progress') {
      const d = data as { processed: number; total: number; pct: number }
      setLive(s => ({ ...s, importStatus: { status: 'running', processed: d.processed, total: d.total, pct: d.pct } }))
    } else if (event === 'import_done') {
      const d = data as { processed: number; duration_s: number }
      setLive(s => ({ ...s, importStatus: { status: 'done', processed: d.processed, total: d.processed, pct: 100 } }))
    } else if (event === 'import_error') {
      const d = data as { error: string }
      setLive(s => ({ ...s, importStatus: { ...s.importStatus, status: 'error', error: d.error } }))
    }
  }, [])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      ws.current?.close()
    }
  }, [connect])

  return live
}
