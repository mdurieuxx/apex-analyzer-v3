import { NavLink } from 'react-router-dom'
import { Activity, GitFork, BarChart2, Settings, Wifi, WifiOff, Trophy, CalendarDays, MapPin, Radio, Power, X, TrendingUp, History, ChevronDown, Users, RefreshCw } from 'lucide-react'
import clsx from 'clsx'
import type { LiveState } from '../hooks/useWebSocket'
import type { Circuit, SavedProxy, KartingEvent, ProxyStatus } from '../types'
import { TrackCondition } from './TrackCondition'
import { api } from '../api/client'
import { useState, useEffect, useRef } from 'react'
import { useEventView } from '../hooks/useEventView'

interface Props {
  live: LiveState
  children: React.ReactNode
}

type SourceOption =
  | { kind: 'live'; name: string; circuit_url: string; ws_port_override: number; min_pit_duration_s?: number | null; min_relay_s?: number | null; max_relay_s?: number | null }
  | { kind: 'proxy'; name: string; ws_url: string }

export function Layout({ live, children }: Props) {
  const [dismissedImport, setDismissedImport] = useState(false)
  const imp = live.importStatus

  const [circuits, setCircuits] = useState<Circuit[]>([])
  const [proxies, setProxies] = useState<SavedProxy[]>([])
  const [selectedIdx, setSelectedIdx] = useState(0)
  const [connecting, setConnecting] = useState(false)
  const [connectPending, setConnectPending] = useState(false)
  const [disconnectPending, setDisconnectPending] = useState(false)
  const [proxyStarting, setProxyStarting] = useState(false)
  const [refreshingGrid, setRefreshingGrid] = useState(false)

  const [allEvents, setAllEvents] = useState<KartingEvent[]>([])
  const [showEventPicker, setShowEventPicker] = useState(false)
  const [eventSearch, setEventSearch] = useState('')
  const pickerRef = useRef<HTMLDivElement>(null)
  const { viewedEventId, viewedEventName, setViewed } = useEventView()
  const [proxyStatus, setProxyStatus] = useState<ProxyStatus | null>(null)

  useEffect(() => {
    api.circuits.list().then(r => setCircuits(r.circuits)).catch(() => {})
    api.proxy.listConfigs().then(r => setProxies(r.proxies)).catch(() => {})
    api.events.list().then(r => setAllEvents(r.events)).catch(() => {})
  }, [])

  useEffect(() => {
    const poll = () => api.proxy.status().then(setProxyStatus).catch(() => {})
    poll()
    const t = setInterval(poll, 5000)
    return () => clearInterval(t)
  }, [])

  // Close picker on outside click
  useEffect(() => {
    if (!showEventPicker) return
    function onDown(e: MouseEvent) {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node))
        setShowEventPicker(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [showEventPicker])

  // Auto-dismiss 'done' banner after 8 s
  useEffect(() => {
    if (imp.status === 'done') {
      const t = setTimeout(() => setDismissedImport(true), 8000)
      return () => clearTimeout(t)
    }
    if (imp.status === 'running') {
      setDismissedImport(false)
    }
  }, [imp.status])

  const showImportBanner = !dismissedImport && imp.status !== 'idle'

  const liveCircuitUrl = proxyStatus?.mode === 'live' ? (proxyStatus.circuit_url ?? '') : ''
  const recordingUrls = new Set((proxyStatus?.bg_recordings ?? []).map(r => r.circuit_url).filter(Boolean))
  const activeUrls = new Set([...(liveCircuitUrl ? [liveCircuitUrl] : []), ...recordingUrls])

  function _circuitMeta(url: string): Circuit | undefined {
    return circuits.find(c => c.circuit_url === url)
  }

  // Proxy control dropdown: all circuits grouped by country, active ones on top
  const proxyActiveCircuits = circuits.filter(c => activeUrls.has(c.circuit_url))
  const proxyByCountry = Object.entries(
    circuits.reduce((acc, c) => {
      if (activeUrls.has(c.circuit_url)) return acc
      const key = c.country || '?'
      ;(acc[key] = acc[key] || []).push(c)
      return acc
    }, {} as Record<string, Circuit[]>)
  ).sort(([a], [b]) => a === '?' ? 1 : b === '?' ? -1 : a.localeCompare(b, 'fr'))

  async function handleProxySelect(url: string) {
    if (!url || url === liveCircuitUrl) return
    const c = _circuitMeta(url)
    if (!c) return
    setProxyStarting(true)
    try {
      await api.proxy.startLive({ circuit_url: url, ws_port: c.ws_port_override, record: !recordingUrls.has(url) })
    } catch {}
    setProxyStarting(false)
  }

  // "En direct" connect dropdown: only saved proxy configs
  const sourceOptions: SourceOption[] = proxies.map(p => ({ kind: 'proxy' as const, name: p.name, ws_url: p.ws_url }))

  const selected = sourceOptions[selectedIdx] ?? sourceOptions[0]

  async function handleConnect() {
    if (!selected) return
    setConnecting(true)
    setConnectPending(false)
    try {
      if (selected.kind === 'proxy') {
        await api.connect({ source: 'proxy', proxy_ws_url: selected.ws_url })
      } else {
        await api.connect({
          source: 'live',
          circuit_url: selected.circuit_url,
          ws_port_override: selected.ws_port_override,
          ...(selected.min_pit_duration_s != null ? { min_pit_duration_s: selected.min_pit_duration_s } : {}),
          ...(selected.min_relay_s != null ? { min_relay_duration_s: selected.min_relay_s } : {}),
          ...(selected.max_relay_s != null ? { max_relay_duration_s: selected.max_relay_s } : {}),
        })
      }
    } catch { /* ignore */ } finally {
      setConnecting(false)
    }
  }

  async function handleDisconnect() {
    setDisconnectPending(false)
    await api.disconnect().catch(() => {})
  }

  const nav = [
    { to: '/',            icon: Activity,      label: 'Live'        },
    { to: '/standings',   icon: Trophy,        label: 'Classement'  },
    { to: '/pits',        icon: GitFork,       label: 'Stands'      },
    { to: '/performance', icon: BarChart2,     label: 'Perf.'       },
    { to: '/stats',       icon: TrendingUp,    label: 'Stats'       },
    { to: '/circuits',    icon: MapPin,        label: 'Circuits'    },
    { to: '/events',      icon: CalendarDays,  label: 'Événements'  },
    { to: '/proxy',       icon: Radio,         label: 'Proxy'       },
    { to: '/settings',    icon: Settings,      label: 'Config'      },
  ]

  const countdown = live.countdown
  const hh = Math.floor(countdown / 3600)
  const mm = String(Math.floor((countdown % 3600) / 60)).padStart(2, '0')
  const ss = String(countdown % 60).padStart(2, '0')

  return (
    <div className="min-h-screen flex flex-col bg-gray-950 text-white">
      {/* Header */}
      <header className="bg-gray-900 border-b border-gray-800 px-4 py-3 flex items-center gap-4">
        <div className="flex-1 min-w-0">
          <h1 className="text-lg font-bold text-white leading-none truncate flex items-center gap-2">
            {live.title1 || live.activeEventName || 'Karting Live'}
          </h1>
          {(live.title2 || (live.activeEventName && !live.title1)) && (
            <p className="text-sm text-gray-400 mt-0.5 truncate">
              {live.title2 || live.activeEventName}
            </p>
          )}
        </div>

        {countdown > 0 && (
          <div className="text-2xl font-mono font-bold text-yellow-400">
            {hh > 0 ? `${hh}:${mm}:${ss}` : `${mm}:${ss}`}
          </div>
        )}

        <div className="flex items-center gap-3">
          {live.drivers.length > 0 && <TrackCondition drivers={live.drivers} />}

          {/* Event viewer picker */}
          <div className="relative" ref={pickerRef}>
            <button
              onClick={() => setShowEventPicker(v => !v)}
              className={clsx(
                'flex items-center gap-1 px-2 py-1 text-xs border rounded transition-colors',
                viewedEventId
                  ? 'bg-yellow-900/30 border-yellow-700/50 text-yellow-300 hover:border-yellow-600'
                  : 'bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-500'
              )}
            >
              <History size={12} />
              <span className="max-w-[120px] truncate">
                {viewedEventId ? viewedEventName : 'En direct'}
              </span>
              <ChevronDown size={10} className={clsx('transition-transform shrink-0', showEventPicker && 'rotate-180')} />
            </button>

            {showEventPicker && (
              <div className="absolute right-0 top-full mt-1 z-50 bg-gray-900 border border-gray-700 rounded-lg shadow-xl w-72">
                <div className="p-2 border-b border-gray-800">
                  <input
                    type="text"
                    value={eventSearch}
                    onChange={e => setEventSearch(e.target.value)}
                    placeholder="Filtrer événement…"
                    autoFocus
                    className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white placeholder-gray-600 focus:outline-none focus:border-gray-500"
                  />
                </div>
                <div className="max-h-72 overflow-y-auto">
                  <button
                    onClick={() => { setViewed(null, ''); setShowEventPicker(false) }}
                    className={clsx(
                      'w-full text-left px-3 py-2 text-xs transition-colors border-b border-gray-800',
                      !viewedEventId ? 'bg-green-900/30 text-green-400' : 'text-gray-400 hover:bg-gray-800'
                    )}
                  >
                    ▶ En direct
                  </button>
                  {allEvents
                    .filter(e => !eventSearch || e.name.toLowerCase().includes(eventSearch.toLowerCase()))
                    .map(ev => (
                      <button
                        key={ev.id}
                        onClick={() => { setViewed(ev.id, ev.name); setShowEventPicker(false); setEventSearch('') }}
                        className={clsx(
                          'w-full text-left px-3 py-2 text-xs transition-colors hover:bg-gray-800',
                          viewedEventId === ev.id ? 'bg-blue-900/30 text-blue-300' : ev.is_active ? 'text-green-400' : 'text-gray-300'
                        )}
                      >
                        <div className="font-medium truncate">{ev.name}</div>
                        <div className="text-gray-600 mt-0.5">{ev.event_date ?? '—'}{ev.is_active ? ' · En cours' : ''}</div>
                      </button>
                    ))
                  }
                </div>
              </div>
            )}
          </div>

          {/* Connection controls */}
          <div className="flex items-center gap-2">
            {/* Status indicator */}
            <div className="flex items-center gap-1.5 text-sm">
              {live.connected ? (
                <span className="flex items-center gap-1 text-green-400">
                  <Wifi size={15} /> Apex
                </span>
              ) : (
                <span className="flex items-center gap-1 text-red-400">
                  <WifiOff size={15} /> Déconnecté
                </span>
              )}
              {live.wsConnected ? (
                <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" title="WebSocket OK" />
              ) : (
                <span className="w-2 h-2 rounded-full bg-yellow-400" title="Reconnexion..." />
              )}
              {live.wsClients > 0 && (
                <span className="flex items-center gap-0.5 text-gray-500 text-xs" title={`${live.wsClients} connecté${live.wsClients > 1 ? 's' : ''}`}>
                  <Users size={11} />
                  {live.wsClients}
                </span>
              )}
              {live.connected && (
                <button
                  onClick={async () => {
                    setRefreshingGrid(true)
                    try { await api.refreshGrid() } catch {}
                    setRefreshingGrid(false)
                  }}
                  disabled={refreshingGrid}
                  className="text-gray-500 hover:text-gray-300 disabled:opacity-40"
                  title="Recharger la grille depuis le proxy"
                >
                  <RefreshCw size={13} className={refreshingGrid ? 'animate-spin' : ''} />
                </button>
              )}
            </div>

            {/* Proxy control dropdown — all circuits, selecting starts live+record on proxy */}
            {!disconnectPending && circuits.length > 0 && (
              <select
                value={liveCircuitUrl || ''}
                onChange={e => handleProxySelect(e.target.value)}
                disabled={proxyStarting}
                title="Démarrer live + enregistrement sur le proxy"
                className="text-sm bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white disabled:opacity-50 max-w-[160px]"
              >
                <option value="">Proxy…</option>
                {proxyActiveCircuits.length > 0 && (
                  <optgroup label="En cours">
                    {proxyActiveCircuits.map((c, i) => (
                      <option key={`a${i}`} value={c.circuit_url}>
                        {c.circuit_url === liveCircuitUrl ? '▶ ' : '⏺ '}{c.name}
                      </option>
                    ))}
                  </optgroup>
                )}
                {proxyByCountry.map(([country, items]) => (
                  <optgroup key={country} label={country === '?' ? 'Pays inconnu' : country}>
                    {items.map((c, i) => (
                      <option key={`c${i}`} value={c.circuit_url}>{c.name}</option>
                    ))}
                  </optgroup>
                ))}
              </select>
            )}

            {/* En direct — connect source (only proxy-active circuits) */}
            {!disconnectPending && sourceOptions.length > 0 && (
              <select
                value={selectedIdx}
                onChange={e => { setSelectedIdx(Number(e.target.value)); setConnectPending(false) }}
                title="Source de connexion pour le frontend"
                className="text-sm bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white max-w-[160px]"
              >
                {sourceOptions.map((opt, i) => (
                  <option key={i} value={i}>
                    {opt.kind === 'live' && opt.circuit_url === liveCircuitUrl ? '▶ ' : ''}
                    {opt.kind === 'live' && recordingUrls.has(opt.circuit_url) ? '⏺ ' : ''}
                    {opt.name}
                  </option>
                ))}
              </select>
            )}

            {/* Action button — Connecter or Déconnecter */}
            {live.connected ? (
              disconnectPending ? (
                <div className="flex items-center gap-1 text-sm">
                  <span className="text-yellow-300">Déconnecter ?</span>
                  <button onClick={handleDisconnect} className="px-2 py-1 bg-red-700 hover:bg-red-600 rounded text-white transition-colors">Oui</button>
                  <button onClick={() => setDisconnectPending(false)} className="px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded text-white transition-colors">Non</button>
                </div>
              ) : (
                <button
                  onClick={() => setDisconnectPending(true)}
                  className="flex items-center gap-1 px-3 py-1.5 text-sm bg-red-800 hover:bg-red-700 rounded transition-colors"
                >
                  <Power size={14} /> Déconnecter
                </button>
              )
            ) : (
              connectPending ? (
                <div className="flex items-center gap-1 text-sm">
                  <span className="text-yellow-300">Connecter ?</span>
                  <button onClick={handleConnect} className="px-2 py-1 bg-green-700 hover:bg-green-600 rounded text-white transition-colors">Oui</button>
                  <button onClick={() => setConnectPending(false)} className="px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded text-white transition-colors">Non</button>
                </div>
              ) : (
                <button
                  onClick={() => setConnectPending(true)}
                  disabled={connecting}
                  className="flex items-center gap-1 px-3 py-1.5 text-sm bg-green-700 hover:bg-green-600 rounded disabled:opacity-50 transition-colors"
                >
                  <Power size={14} /> {connecting ? '…' : 'Connecter'}
                </button>
              )
            )}
          </div>
        </div>
      </header>

      {/* Nav */}
      <nav className="bg-gray-900 border-b border-gray-800 flex">
        {nav.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
                isActive
                  ? 'border-orange-500 text-orange-400'
                  : 'border-transparent text-gray-400 hover:text-white'
              )
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Import progress banner */}
      {showImportBanner && (
        <div className={clsx(
          'px-4 py-2 flex items-center gap-3 text-sm',
          imp.status === 'running' && 'bg-blue-900/60 text-blue-200',
          imp.status === 'done' && 'bg-green-900/60 text-green-200',
          imp.status === 'error' && 'bg-red-900/60 text-red-200',
        )}>
          {imp.status === 'running' && (
            <>
              <div className="w-3 h-3 rounded-full bg-blue-400 animate-pulse shrink-0" />
              <span className="flex-1">
                Import en cours… {imp.processed.toLocaleString()} / {imp.total.toLocaleString()} messages ({imp.pct}%)
              </span>
              <div className="w-40 h-1.5 bg-blue-900 rounded-full overflow-hidden">
                <div className="h-full bg-blue-400 transition-all" style={{ width: `${imp.pct}%` }} />
              </div>
            </>
          )}
          {imp.status === 'done' && (
            <span className="flex-1">Import terminé — {imp.processed.toLocaleString()} messages traités.</span>
          )}
          {imp.status === 'error' && (
            <span className="flex-1">Erreur import : {imp.error}</span>
          )}
          <button onClick={() => setDismissedImport(true)} className="ml-2 opacity-60 hover:opacity-100">
            <X size={14} />
          </button>
        </div>
      )}

      {/* Content */}
      <main className="flex-1 overflow-auto p-4">{children}</main>
    </div>
  )
}
