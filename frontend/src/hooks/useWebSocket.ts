import { useEffect, useRef, useCallback, useState } from 'react'
import type { WsMessage, WsSnapshot, Driver, PitLane, PitHistoryEntry, ReserveSummary } from '../types'

const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`
const RECONNECT_DELAY = 3000

export interface LiveState {
  connected: boolean
  wsConnected: boolean
  title1: string
  title2: string
  sessionType: string
  countdown: number
  drivers: Driver[]
  lanes: PitLane[]
  reserveSummary: ReserveSummary
  pitHistory: PitHistoryEntry[]
  lastPitStop: { bib: string; team: string; kart_label: string; position: number; timestamp: string } | null
}

const DEFAULT_STATE: LiveState = {
  connected: false,
  wsConnected: false,
  title1: '',
  title2: '',
  sessionType: 'unknown',
  countdown: 0,
  drivers: [],
  lanes: [],
  reserveSummary: { good: 0, medium: 0, bad: 0, unknown: 100 },
  pitHistory: [],
  lastPitStop: null,
}

export function useWebSocket() {
  const [live, setLive] = useState<LiveState>(DEFAULT_STATE)
  const ws = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>()

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
      setLive(s => ({
        ...s,
        title1: d.title1,
        title2: d.title2,
        sessionType: d.session_type,
        countdown: d.countdown,
        connected: d.connected,
        drivers: d.drivers ?? s.drivers,
        lanes: d.lanes ?? s.lanes,
        reserveSummary: d.reserve_summary ?? s.reserveSummary,
        pitHistory: d.pit_history ?? s.pitHistory,
      }))
    } else if (event === 'grid') {
      const d = data as { drivers?: Driver[]; lanes?: PitLane[]; reserve_summary?: ReserveSummary }
      setLive(s => ({
        ...s,
        ...(d.drivers ? { drivers: d.drivers } : {}),
        ...(d.lanes ? { lanes: d.lanes } : {}),
        ...(d.reserve_summary ? { reserveSummary: d.reserve_summary } : {}),
      }))
    } else if (event === 'connected') {
      setLive(s => ({ ...s, connected: true }))
    } else if (event === 'disconnected') {
      setLive(s => ({ ...s, connected: false }))
    } else if (event === 'session_update') {
      const d = data as { title1: string; title2: string }
      setLive(s => ({ ...s, title1: d.title1, title2: d.title2 }))
    } else if (event === 'pit_stop') {
      const d = data as { bib: string; team: string; kart_label: string; position: number; timestamp: string; driver_id: string; pit_number: number }
      setLive(s => ({
        ...s,
        lastPitStop: d,
        pitHistory: [
          { bib: d.bib, team: d.team, kart_in: d.kart_label, kart_out: null, position: d.position, pit_number: d.pit_number, timestamp: d.timestamp, duration_s: null },
          ...s.pitHistory,
        ].slice(0, 100),
      }))
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
