import { useEffect, useState } from 'react'
import { Wifi, WifiOff, Plus, Trash2, ExternalLink, Upload, Clock, X } from 'lucide-react'
import clsx from 'clsx'
import { api } from '../api/client'
import type { Circuit, ProxyMode, ProxyRecording, ScheduledJob } from '../types'

interface SavedProxy { id: number; name: string; ws_url: string; created_at: string }

function wsToHttpUrl(wsUrl: string): string {
  return wsUrl.replace(/^ws:\/\//, 'http://').replace(/^wss:\/\//, 'https://').replace(/\/ws$/, '')
}

export function Proxy() {
  const [proxyMode, setProxyMode] = useState<ProxyMode>('idle')
  const [activeWsUrl, setActiveWsUrl] = useState('')
  const [savedProxies, setSavedProxies] = useState<SavedProxy[]>([])
  const [circuits, setCircuits] = useState<Circuit[]>([])

  // Live form
  const [liveCircuit, setLiveCircuit] = useState<Circuit | null>(null)
  const [liveUrl, setLiveUrl] = useState('')
  const [livePort, setLivePort] = useState(0)

  // Proxy form
  const [showForm, setShowForm] = useState(false)
  const [newName, setNewName] = useState('')
  const [newUrl, setNewUrl] = useState('ws://192.168.1.x:9000/ws')

  const [recordings, setRecordings] = useState<ProxyRecording[]>([])
  const [importingName, setImportingName] = useState<string | null>(null)

  const [scheduledJobs, setScheduledJobs] = useState<ScheduledJob[]>([])
  const [showScheduleForm, setShowScheduleForm] = useState(false)
  const [schedCircuit, setSchedCircuit] = useState<Circuit | null>(null)
  const [schedUrl, setSchedUrl] = useState('')
  const [schedPort, setSchedPort] = useState(0)
  const [schedStartAt, setSchedStartAt] = useState('')
  const [schedDuration, setSchedDuration] = useState<string>('')
  const [schedNamePrefix, setSchedNamePrefix] = useState('')

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [replaySpeed, setReplaySpeed] = useState(1)

  const load = async () => {
    try {
      const [proxyStatus, proxyData, cfg, circuitsData] = await Promise.all([
        api.proxy.status().catch(() => null),
        api.proxy.listConfigs(),
        api.config.get(),
        api.circuits.list(),
      ])
      if (proxyStatus) {
        setProxyMode(proxyStatus.mode)
        setReplaySpeed(proxyStatus.replay_speed ?? 1)
      }
      setActiveWsUrl(proxyData.active_ws_url)
      setSavedProxies(proxyData.proxies)
      setCircuits(circuitsData.circuits)
      setLiveUrl(cfg.circuit_url)
      setLivePort(cfg.ws_port_override)
      const matched = circuitsData.circuits.find(c => c.circuit_url === cfg.circuit_url)
      setLiveCircuit(matched ?? null)
      // Load recordings list from proxy (may fail if proxy unreachable)
      api.proxy.recordings().then(r => setRecordings(r.recordings)).catch(() => {})
      api.proxy.schedule.list().then(r => setScheduledJobs(r.jobs)).catch(() => {})
    } catch { /* ignore */ }
  }

  useEffect(() => {
    load()
    const t = setInterval(() => {
      api.proxy.status().catch(() => null).then(s => {
        if (!s) return
        setProxyMode(s.mode)
        setReplaySpeed(s.replay_speed ?? 1)
      })
    }, 2000)
    return () => clearInterval(t)
  }, [])

  const act = async (fn: () => Promise<unknown>) => {
    setLoading(true); setError(null)
    try { await fn(); await load() }
    catch (e: unknown) { setError(e instanceof Error ? e.message : 'Erreur') }
    finally { setLoading(false) }
  }

  // Tell the proxy to start relaying live Apex Timing data for the selected circuit.
  // The backend (already connected to proxy WS) receives data automatically.
  const connectLive = () => {
    if (!window.confirm('Connecter en live sur Apex Timing ?')) return
    act(async () => {
      await api.config.update({ circuit_url: liveUrl, ws_port_override: livePort })
      await api.proxy.startLive({ circuit_url: liveUrl, ws_port: livePort, record: false })
    })
  }

  const activateProxy = (id: number) => {
    if (!window.confirm('Connecter ce proxy ?')) return
    act(() => api.proxy.activateProxy(id))
  }
  const deactivateProxy = () => {
    if (!window.confirm('Déconnecter ce proxy ?')) return
    act(() => api.proxy.switchToLive())
  }
  const addProxy = () => act(async () => {
    await api.proxy.createConfig(newName, newUrl)
    setNewName(''); setNewUrl('ws://192.168.1.x:9000/ws'); setShowForm(false)
  })
  const delProxy = (id: number, name: string) => {
    if (!window.confirm(`Supprimer le proxy « ${name} » ?`)) return
    act(() => api.proxy.deleteConfig(id))
  }

  const liveIsActive = proxyMode === 'live'
  const proxyUiUrl = activeWsUrl ? wsToHttpUrl(activeWsUrl) : null

  return (
    <div className="space-y-5 max-w-xl">
      <h1 className="text-lg font-bold text-white">Source de données</h1>

      {/* Live Apex Timing */}
      <div className={clsx(
        'rounded-lg border p-4 space-y-3 transition-colors',
        liveIsActive ? 'bg-gray-900 border-green-800/50' : 'bg-gray-900 border-gray-800'
      )}>
        <div className="flex items-center gap-2">
          <div className={clsx('w-2 h-2 rounded-full', liveIsActive ? 'bg-green-400' : 'bg-gray-600')} />
          <h2 className="text-sm font-bold text-gray-200">Live Apex Timing</h2>
          {liveIsActive && <span className="text-xs text-green-400 font-semibold ml-1">Actif</span>}
        </div>

        <div className="space-y-2">
          <div>
            <label className="block text-xs text-gray-400 mb-1">Circuit</label>
            <select
              className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-green-600"
              value={liveCircuit?.name ?? ''}
              onChange={e => {
                const c = circuits.find(c => c.name === e.target.value) ?? null
                setLiveCircuit(c)
                if (c) { setLiveUrl(c.circuit_url); setLivePort(c.ws_port_override) }
              }}
            >
              <option value="">— Saisir manuellement —</option>
              {circuits.map(c => (
                <option key={c.name} value={c.name}>{c.name}</option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-[1fr_100px] gap-2">
            <div>
              <label className="block text-xs text-gray-400 mb-1">URL circuit</label>
              <input
                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-green-600"
                value={liveUrl}
                onChange={e => { setLiveUrl(e.target.value); setLiveCircuit(null) }}
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Port WS</label>
              <input
                type="number"
                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-green-600"
                value={livePort}
                onChange={e => { setLivePort(Number(e.target.value)); setLiveCircuit(null) }}
              />
            </div>
          </div>
        </div>

        <button
          onClick={connectLive}
          disabled={loading || !liveUrl}
          className="flex items-center gap-2 px-4 py-2 rounded bg-green-700 hover:bg-green-600 disabled:opacity-40 text-white text-sm font-bold transition-colors"
        >
          <Wifi size={13} /> Connecter
        </button>
      </div>

      {/* Proxy */}
      <div className={clsx(
        'rounded-lg border p-4 space-y-3 transition-colors',
        activeWsUrl ? 'bg-gray-900 border-blue-800/50' : 'bg-gray-900 border-gray-800'
      )}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className={clsx('w-2 h-2 rounded-full', activeWsUrl ? 'bg-blue-400' : 'bg-gray-600')} />
            <h2 className="text-sm font-bold text-gray-200">Proxy</h2>
          </div>
          <button
            onClick={() => setShowForm(v => !v)}
            className="flex items-center gap-1 text-xs px-2 py-1 rounded bg-gray-700 hover:bg-gray-600 text-gray-300 transition-colors"
          >
            <Plus size={12} /> Ajouter
          </button>
        </div>

        {showForm && (
          <div className="border border-gray-700 rounded p-3 space-y-2 bg-gray-800">
            <input
              className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-sm text-white focus:outline-none"
              placeholder="Nom (ex: Proxy Saintes)"
              value={newName}
              onChange={e => setNewName(e.target.value)}
            />
            <input
              className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-sm text-white font-mono focus:outline-none"
              placeholder="ws://192.168.1.x:9000/ws"
              value={newUrl}
              onChange={e => setNewUrl(e.target.value)}
            />
            <div className="flex gap-2">
              <button
                onClick={addProxy}
                disabled={loading || !newName || !newUrl}
                className="px-3 py-1.5 rounded bg-blue-700 hover:bg-blue-600 disabled:opacity-40 text-white text-xs font-bold"
              >
                Sauvegarder
              </button>
              <button
                onClick={() => setShowForm(false)}
                className="px-3 py-1.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs"
              >
                Annuler
              </button>
            </div>
          </div>
        )}

        {savedProxies.length === 0 ? (
          <p className="text-gray-600 text-sm">Aucun proxy sauvegardé</p>
        ) : (
          <div className="divide-y divide-gray-800">
            {savedProxies.map(p => {
              const isActive = activeWsUrl === p.ws_url
              return (
                <div key={p.id} className="flex items-center gap-3 py-2.5">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-white">{p.name}</p>
                    <p className="text-xs font-mono text-gray-500 truncate">{p.ws_url}</p>
                  </div>
                  {isActive ? (
                    <button
                      onClick={deactivateProxy}
                      disabled={loading}
                      className="flex items-center gap-1 px-3 py-1 rounded bg-red-800 hover:bg-red-700 disabled:opacity-40 text-white text-xs font-bold transition-colors"
                    >
                      <WifiOff size={11} /> Déconnecter
                    </button>
                  ) : (
                    <button
                      onClick={() => activateProxy(p.id)}
                      disabled={loading}
                      className="flex items-center gap-1 px-3 py-1 rounded bg-blue-700 hover:bg-blue-600 disabled:opacity-40 text-white text-xs font-bold transition-colors"
                    >
                      <Wifi size={11} /> Connecter
                    </button>
                  )}
                  <button
                    onClick={() => delProxy(p.id, p.name)}
                    disabled={loading || isActive}
                    className="p-1 text-gray-600 hover:text-red-400 disabled:opacity-30 transition-colors"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              )
            })}
          </div>
        )}

        {activeWsUrl && (
          <div className="pt-1 space-y-1">
            <p className="text-xs text-blue-400 font-mono">{activeWsUrl}</p>
            {proxyUiUrl && (
              <a href={proxyUiUrl} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-xs text-gray-400 hover:text-white transition-colors">
                <ExternalLink size={11} /> Ouvrir l'interface du proxy
              </a>
            )}
          </div>
        )}

        {proxyMode !== 'idle' && (
          <div className="border-t border-gray-700 pt-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-400">Vitesse replay</span>
              <span className="text-sm font-bold font-mono text-blue-300">{replaySpeed.toFixed(1)}×</span>
            </div>
            <input
              type="range"
              min={1} max={10} step={0.5}
              value={replaySpeed}
              onChange={async e => {
                const v = parseFloat(e.target.value)
                setReplaySpeed(v)
                try { await api.proxy.setSpeed(v) } catch { /* ignore */ }
              }}
              className="w-full accent-blue-500"
            />
            <div className="flex justify-between text-xs text-gray-600">
              <span>1×</span><span>5×</span><span>10×</span>
            </div>
          </div>
        )}
      </div>

      {/* Scheduler */}
      <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock size={14} className="text-gray-400" />
            <h2 className="text-sm font-bold text-gray-200">Enregistrements planifiés</h2>
          </div>
          <button
            onClick={() => setShowScheduleForm(v => !v)}
            className="flex items-center gap-1 text-xs px-2 py-1 rounded bg-gray-700 hover:bg-gray-600 text-gray-300 transition-colors"
          >
            <Plus size={12} /> Planifier
          </button>
        </div>

        {showScheduleForm && (
          <div className="border border-gray-700 rounded p-3 space-y-2 bg-gray-800">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Circuit</label>
              <select
                className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-sm text-white focus:outline-none"
                value={schedCircuit?.name ?? ''}
                onChange={e => {
                  const c = circuits.find(c => c.name === e.target.value) ?? null
                  setSchedCircuit(c)
                  if (c) { setSchedUrl(c.circuit_url); setSchedPort(c.ws_port_override) }
                }}
              >
                <option value="">— Saisir manuellement —</option>
                {circuits.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
              </select>
            </div>
            <div className="grid grid-cols-[1fr_90px] gap-2">
              <input
                className="bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-xs font-mono text-white focus:outline-none"
                placeholder="URL circuit"
                value={schedUrl}
                onChange={e => { setSchedUrl(e.target.value); setSchedCircuit(null) }}
              />
              <input
                type="number"
                className="bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-sm text-white focus:outline-none"
                placeholder="Port"
                value={schedPort || ''}
                onChange={e => { setSchedPort(Number(e.target.value)); setSchedCircuit(null) }}
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Début (heure locale)</label>
                <input
                  type="datetime-local"
                  className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-sm text-white focus:outline-none"
                  value={schedStartAt}
                  onChange={e => setSchedStartAt(e.target.value)}
                />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Durée (min, optionnel)</label>
                <input
                  type="number"
                  className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-sm text-white focus:outline-none"
                  placeholder="ex: 480"
                  value={schedDuration}
                  onChange={e => setSchedDuration(e.target.value)}
                />
              </div>
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Préfixe nom (optionnel)</label>
              <input
                className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-sm text-white focus:outline-none"
                placeholder="ex: agadir_24h"
                value={schedNamePrefix}
                onChange={e => setSchedNamePrefix(e.target.value)}
              />
            </div>
            <div className="flex gap-2">
              <button
                disabled={loading || !schedUrl || !schedPort || !schedStartAt}
                onClick={() => act(async () => {
                  const startUtc = new Date(schedStartAt).toISOString()
                  const r = await api.proxy.schedule.create({
                    circuit_url: schedUrl,
                    ws_port: schedPort,
                    start_at: startUtc,
                    ...(schedNamePrefix ? { name_prefix: schedNamePrefix } : {}),
                    ...(schedDuration ? { duration_minutes: parseInt(schedDuration) } : {}),
                  })
                  setScheduledJobs(prev => [...prev, r.job])
                  setShowScheduleForm(false)
                  setSchedStartAt(''); setSchedDuration(''); setSchedNamePrefix('')
                })}
                className="px-3 py-1.5 rounded bg-orange-700 hover:bg-orange-600 disabled:opacity-40 text-white text-xs font-bold"
              >
                Planifier
              </button>
              <button
                onClick={() => setShowScheduleForm(false)}
                className="px-3 py-1.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs"
              >
                Annuler
              </button>
            </div>
          </div>
        )}

        {scheduledJobs.length === 0 ? (
          <p className="text-gray-600 text-sm">Aucun enregistrement planifié</p>
        ) : (
          <div className="divide-y divide-gray-800">
            {scheduledJobs.map(j => {
              const statusColor: Record<string, string> = {
                pending: 'text-yellow-400', running: 'text-green-400',
                done: 'text-gray-500', cancelled: 'text-gray-600',
                interrupted: 'text-red-400', failed: 'text-red-500',
              }
              const slug = j.circuit_url.split('/').filter(Boolean).pop() ?? j.circuit_url
              const startLocal = new Date(j.start_at).toLocaleString()
              return (
                <div key={j.id} className="flex items-center gap-3 py-2.5">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={clsx('text-xs font-bold uppercase', statusColor[j.status] ?? 'text-gray-400')}>
                        {j.status}
                      </span>
                      <span className="text-sm text-white truncate">{slug}</span>
                    </div>
                    <p className="text-xs text-gray-500">
                      {startLocal}{j.duration_minutes ? ` · ${j.duration_minutes} min` : ''}
                      {j.recording_name ? ` · ${j.recording_name}` : ''}
                    </p>
                  </div>
                  {(j.status === 'pending' || j.status === 'running') && (
                    <button
                      onClick={() => act(async () => {
                        await api.proxy.schedule.cancel(j.id)
                        setScheduledJobs(prev => prev.map(x => x.id === j.id ? { ...x, status: 'cancelled' } : x))
                      })}
                      disabled={loading}
                      className="p-1 text-gray-600 hover:text-red-400 disabled:opacity-30 transition-colors"
                      title="Annuler"
                    >
                      <X size={14} />
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Recordings — import into DB */}
      {recordings.length > 0 && (
        <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 space-y-3">
          <h2 className="text-sm font-bold text-gray-200">Enregistrements proxy</h2>
          <div className="divide-y divide-gray-800">
            {recordings.map(r => (
              <div key={r.name} className="flex items-center gap-3 py-2.5">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-white truncate">{r.name}</p>
                  <p className="text-xs text-gray-500">
                    {r.msg_count.toLocaleString()} messages · {r.size_kb} Ko
                  </p>
                </div>
                <button
                  onClick={async () => {
                    setImportingName(r.name)
                    setError(null)
                    try {
                      await api.import.start(r.name)
                    } catch (e: unknown) {
                      setError(e instanceof Error ? e.message : 'Erreur import')
                    } finally {
                      setImportingName(null)
                    }
                  }}
                  disabled={importingName !== null}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-purple-700 hover:bg-purple-600 disabled:opacity-40 text-white text-xs font-bold transition-colors"
                >
                  {importingName === r.name ? (
                    <span className="animate-pulse">…</span>
                  ) : (
                    <><Upload size={11} /> Importer</>
                  )}
                </button>
              </div>
            ))}
          </div>
          <p className="text-xs text-gray-600">L'import analyse l'enregistrement et stocke les données en DB pour l'événement actif.</p>
        </div>
      )}

      {error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  )
}
