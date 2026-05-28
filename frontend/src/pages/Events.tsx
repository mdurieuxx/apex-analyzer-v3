import { useState, useEffect, useRef } from 'react'
import { Plus, Trash2, Play, Calendar, Clock, ChevronUp, Pencil, RotateCcw, Check, X, Square, RefreshCw, DatabaseZap, Download } from 'lucide-react'
import clsx from 'clsx'
import { api } from '../api/client'
import type { KartingEvent, KartingEventCreate, Circuit, ProxySession } from '../types'

const DEFAULT_FORM: KartingEventCreate = {
  name: '',
  circuit_url: '',
  ws_port_override: 0,
  event_date: null,
  duration_hours: 6,
  min_pit_duration_s: 300,
  min_relay_s: 3600,
  max_relay_s: 5400,
  num_lanes: 4,
  total_reserve_karts: 20,
  source: 'live',
  proxy_ws_url: 'wss://apex-proxy.durdur.eu/ws',
}

function fmtDate(iso: string | null) {
  if (!iso) return '–'
  return new Date(iso).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

function fmtDurS(s: number) {
  const m = Math.floor(s / 60)
  return m >= 60 ? `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}` : `${m} min`
}

function fmtT(s: number) {
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return m > 0 ? `${h}h${String(m).padStart(2, '0')}` : `${h}h`
}

function countryFlag(code: string) {
  if (!code || code.length !== 2) return ''
  const base = 0x1F1E6 - 65
  return String.fromCodePoint(base + code.toUpperCase().charCodeAt(0)) +
         String.fromCodePoint(base + code.toUpperCase().charCodeAt(1))
}

// recording name = proxy_ws_url that doesn't look like a ws:// URL
function isRecordingName(url: string) {
  return url && !url.startsWith('ws')
}

// strip resolved/{circuit}/ prefix for display
function shortRecordingName(url: string) {
  const parts = url.split('/')
  if (parts[0] === 'resolved' && parts.length >= 3) return parts.slice(2).join('/')
  return url
}

function eventToForm(ev: KartingEvent): KartingEventCreate {
  return {
    name: ev.name,
    circuit_url: ev.circuit_url,
    ws_port_override: ev.ws_port_override,
    event_date: ev.event_date,
    duration_hours: ev.duration_hours,
    min_pit_duration_s: ev.min_pit_duration_s,
    min_relay_s: ev.min_relay_s,
    max_relay_s: ev.max_relay_s,
    num_lanes: ev.num_lanes,
    total_reserve_karts: ev.total_reserve_karts,
    source: ev.source ?? 'live',
    proxy_ws_url: ev.proxy_ws_url ?? '',
  }
}

export function Events() {
  const [events, setEvents] = useState<KartingEvent[]>([])
  const [circuits, setCircuits] = useState<Circuit[]>([])
  const [form, setForm] = useState<KartingEventCreate>(DEFAULT_FORM)
  const [showForm, setShowForm] = useState(false)
  const [activating, setActivating] = useState<number | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editForm, setEditForm] = useState<KartingEventCreate>(DEFAULT_FORM)
  const [confirmReset, setConfirmReset] = useState<number | null>(null)
  const [resetting, setResetting] = useState<number | null>(null)
  const [stopping, setStopping] = useState<number | null>(null)
  const [starting, setStarting] = useState<number | null>(null)
  const [seeding, setSeeding] = useState(false)
  const [seedResult, setSeedResult] = useState<string | null>(null)
  const [reanalyzing, setReanalyzing] = useState<number | null>(null)
  const [importRunning, setImportRunning] = useState<{ evId: number; pct: number; resumedFrom: number; maxT: number; sessionKey?: string } | null>(null)
  const [importError, setImportError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [proxySessions, setProxySessions] = useState<ProxySession[]>([])
  const [showProxyImport, setShowProxyImport] = useState(false)
  const [loadingProxySessions, setLoadingProxySessions] = useState(false)

  useEffect(() => {
    api.events.list().then(r => setEvents(r.events)).catch(() => {})
    api.circuits.list().then(r => setCircuits(r.circuits)).catch(() => {})
  }, [])

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current) }, [])

  async function startImport(ev: KartingEvent) {
    if (importRunning) return
    setImportError(null)
    setImportRunning({ evId: ev.id, pct: 0, resumedFrom: ev.imported_through_t ?? 0, maxT: 0 })
    try {
      await api.import.start(ev.proxy_ws_url, ev.id)
    } catch (e) {
      setImportRunning(null)
      setImportError(e instanceof Error ? e.message : 'Erreur import')
      return
    }
    pollRef.current = setInterval(async () => {
      try {
        const s = await api.import.status()
        setImportRunning(prev => prev
          ? { ...prev, pct: s.pct, resumedFrom: s.resumed_from_t ?? prev.resumedFrom, maxT: s.recording_max_t ?? prev.maxT }
          : prev
        )
        if (s.status === 'done' || s.status === 'error') {
          if (pollRef.current) clearInterval(pollRef.current)
          setImportRunning(null)
          if (s.status === 'error') {
            setImportError(s.error ?? 'Erreur import')
          } else {
            // Refresh events to get updated imported_through_t
            api.events.list().then(r => setEvents(r.events)).catch(() => {})
          }
        }
      } catch { /* ignore poll errors */ }
    }, 1000)
  }

  function applyCircuit(c: Circuit) {
    setForm(f => ({ ...f, circuit_url: c.circuit_url, ws_port_override: c.ws_port_override }))
  }

  function applyCircuitToEdit(c: Circuit) {
    setEditForm(f => ({ ...f, circuit_url: c.circuit_url, ws_port_override: c.ws_port_override }))
  }

  async function createEvent() {
    if (!form.name.trim() || !form.circuit_url.trim()) return
    const ev = await api.events.create(form)
    setEvents(prev => [ev, ...prev])
    setForm(DEFAULT_FORM)
    setShowForm(false)
  }

  async function deleteEvent(id: number, name: string) {
    if (!window.confirm(`Supprimer l'événement « ${name} » ?`)) return
    await api.events.delete(id)
    setEvents(prev => prev.filter(e => e.id !== id))
  }

  async function activateEvent(id: number) {
    setActivating(id)
    try {
      await api.events.activate(id)
      setEvents(prev => prev.map(e => ({ ...e, is_active: e.id === id })))
    } finally {
      setActivating(null)
    }
  }

  function startEdit(ev: KartingEvent) {
    setEditingId(ev.id)
    setEditForm(eventToForm(ev))
  }

  function cancelEdit() {
    setEditingId(null)
  }

  async function saveEdit(id: number) {
    const updated = await api.events.update(id, editForm)
    setEvents(prev => prev.map(e => e.id === id ? { ...e, ...updated } : e))
    setEditingId(null)
  }

  async function stopEvent(id: number) {
    setStopping(id)
    try { await api.events.stop(id) } finally { setStopping(null) }
  }

  async function startEvent(id: number) {
    setStarting(id)
    try { await api.events.start(id) } finally { setStarting(null) }
  }

  async function reanalyzeEvent(id: number) {
    setReanalyzing(id)
    try { await api.events.reanalyze(id) } finally { setReanalyzing(null) }
  }

  async function seedFromHistory() {
    setSeeding(true)
    setSeedResult(null)
    try {
      const r = await api.seedFromHistory()
      setSeedResult(`✓ ${r.seeded_teams} équipes chargées depuis « ${r.source_event_name} »`)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setSeedResult(`Erreur: ${msg}`)
    } finally {
      setSeeding(false)
    }
  }

  async function loadProxySessions() {
    setLoadingProxySessions(true)
    try {
      const r = await api.proxySessions()
      setProxySessions(r.sessions)
    } catch { /* ignore */ }
    finally { setLoadingProxySessions(false) }
  }

  async function startSessionImport(session: ProxySession) {
    if (importRunning) return
    setImportError(null)
    setImportRunning({ evId: -1, pct: 0, resumedFrom: 0, maxT: 0, sessionKey: session.event_key })
    try {
      await api.import.startSession(session.recordings.map(r => r.name))
    } catch (e) {
      setImportRunning(null)
      setImportError(e instanceof Error ? e.message : 'Erreur import')
      return
    }
    pollRef.current = setInterval(async () => {
      try {
        const s = await api.import.status()
        setImportRunning(prev => prev
          ? { ...prev, pct: s.pct, resumedFrom: s.resumed_from_t ?? prev.resumedFrom, maxT: s.recording_max_t ?? prev.maxT }
          : prev
        )
        if (s.status === 'done' || s.status === 'error') {
          if (pollRef.current) clearInterval(pollRef.current)
          setImportRunning(null)
          if (s.status === 'error') {
            setImportError(s.error ?? 'Erreur import')
          } else {
            api.events.list().then(r => setEvents(r.events)).catch(() => {})
            loadProxySessions()
          }
        }
      } catch { /* ignore poll errors */ }
    }, 1000)
  }

  async function resetEvent(id: number) {
    setResetting(id)
    try {
      await api.events.reset(id)
      setEvents(prev => prev.map(e => e.id === id ? { ...e, best_lap_ms: null, best_lap_bib: '', best_lap_pilot_name: '' } : e))
    } finally {
      setResetting(null)
      setConfirmReset(null)
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-bold text-white">Événements</h1>
        <button
          onClick={() => setShowForm(f => !f)}
          className="flex items-center gap-2 bg-orange-600 hover:bg-orange-500 text-white px-3 py-1.5 rounded text-sm font-medium transition-colors"
        >
          {showForm ? <ChevronUp size={14} /> : <Plus size={14} />}
          {showForm ? 'Annuler' : 'Nouvel événement'}
        </button>
      </div>

      {/* Creation form */}
      {showForm && (
        <section className="bg-gray-900 rounded-lg border border-orange-600/40 p-5 space-y-4">
          <h2 className="text-sm font-bold uppercase text-orange-400 tracking-wide">Créer un événement</h2>
          <CircuitPicker circuits={circuits} selectedUrl={form.circuit_url} onPick={applyCircuit} />
          <EventFormFields form={form} onChange={setForm} />
          <button
            onClick={createEvent}
            disabled={!form.name.trim() || !form.circuit_url.trim()}
            className="flex items-center gap-2 bg-orange-600 hover:bg-orange-500 disabled:opacity-40 disabled:cursor-not-allowed text-white px-4 py-2 rounded text-sm font-medium transition-colors"
          >
            <Plus size={14} />
            Créer l'événement
          </button>
        </section>
      )}

      {seedResult && (
        <div className={clsx(
          'text-xs px-3 py-2 rounded border',
          seedResult.startsWith('✓') ? 'bg-purple-950/40 border-purple-600/40 text-purple-300' : 'bg-red-950/40 border-red-600/40 text-red-300'
        )}>
          {seedResult}
        </div>
      )}

      {importError && (
        <div className="text-xs px-3 py-2 rounded border bg-red-950/40 border-red-600/40 text-red-300 flex items-center justify-between">
          <span>Import : {importError}</span>
          <button onClick={() => setImportError(null)} className="ml-2 text-red-500 hover:text-red-300"><X size={12} /></button>
        </div>
      )}

      {/* Proxy import panel */}
      <section className="bg-gray-900 rounded-lg border border-blue-600/40">
        <div className="flex items-center justify-between p-4">
          <h2 className="text-sm font-bold uppercase text-blue-400 tracking-wide flex items-center gap-2">
            <Download size={14} />
            Importer depuis le proxy
          </h2>
          <div className="flex items-center gap-2">
            {showProxyImport && (
              <button
                onClick={loadProxySessions}
                disabled={loadingProxySessions}
                className="text-gray-500 hover:text-gray-300 disabled:opacity-40 transition-colors p-1"
                title="Actualiser"
              >
                <RefreshCw size={13} className={loadingProxySessions ? 'animate-spin' : ''} />
              </button>
            )}
            <button
              onClick={() => {
                if (!showProxyImport) loadProxySessions()
                setShowProxyImport(f => !f)
              }}
              className="flex items-center gap-1.5 text-gray-400 hover:text-white text-xs transition-colors"
            >
              {showProxyImport ? <ChevronUp size={14} /> : <Plus size={14} />}
              {showProxyImport ? 'Masquer' : 'Afficher'}
            </button>
          </div>
        </div>
        {showProxyImport && (
          <div className="px-4 pb-4 space-y-2">
            {loadingProxySessions && (
              <div className="text-center text-gray-500 py-6 text-xs">Chargement…</div>
            )}
            {!loadingProxySessions && proxySessions.length === 0 && (
              <div className="text-center text-gray-500 py-6 text-xs">Aucune session détectée</div>
            )}
            {proxySessions.map(sess => {
              const isImporting = importRunning?.sessionKey === sess.event_key
              const firstRec = sess.recordings[0]
              return (
                <div key={sess.event_key} className="bg-gray-800 rounded border border-gray-700 p-3 flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium text-white">{sess.title1}</span>
                      {sess.title2 && <span className="text-xs text-gray-400">{sess.title2}</span>}
                      {sess.country && <span className="text-base leading-none">{countryFlag(sess.country)}</span>}
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5 font-mono truncate">
                      {sess.circuit_name || sess.circuit_url}
                    </div>
                    <div className="flex gap-3 mt-1.5 text-xs text-gray-400 flex-wrap">
                      {sess.countdown_s != null && (
                        <span className="flex items-center gap-1">
                          <Clock size={11} />{fmtT(sess.countdown_s)}
                        </span>
                      )}
                      {firstRec?.started_at_local && (
                        <span className="flex items-center gap-1">
                          <Calendar size={11} />{firstRec.started_at_local.slice(0, 10)}
                        </span>
                      )}
                      <span>{sess.recordings.length} enreg.</span>
                    </div>
                    {isImporting && importRunning ? (
                      <div className="mt-2 flex items-center gap-2">
                        <div className="flex-1 bg-gray-700 rounded-full h-1.5 min-w-[80px]">
                          <div className="bg-blue-500 h-1.5 rounded-full transition-all" style={{ width: `${importRunning.pct}%` }} />
                        </div>
                        <span className="text-xs text-blue-400 shrink-0">{importRunning.pct}%</span>
                        {importRunning.resumedFrom > 0 && (
                          <span className="text-xs text-gray-500 shrink-0">reprise {fmtT(importRunning.resumedFrom)}</span>
                        )}
                      </div>
                    ) : sess.event_id != null && sess.imported_through_t != null ? (
                      <span className="mt-1.5 inline-block text-xs text-green-600">
                        ✓ importé {fmtT(sess.imported_through_t)}
                      </span>
                    ) : sess.event_id != null ? (
                      <span className="mt-1.5 inline-block text-xs text-gray-500">Créé</span>
                    ) : null}
                  </div>
                  <button
                    onClick={() => startSessionImport(sess)}
                    disabled={importRunning !== null}
                    className="flex items-center gap-1.5 bg-blue-700 hover:bg-blue-600 disabled:opacity-40 text-white px-2.5 py-1.5 rounded text-xs font-medium transition-colors shrink-0"
                    title="Importer tous les enregistrements de cette session"
                  >
                    <Download size={12} />
                    {isImporting ? '…' : 'Importer'}
                  </button>
                </div>
              )
            })}
          </div>
        )}
      </section>

      {/* Event list */}
      <div className="space-y-3">
        {events.length === 0 && (
          <div className="text-center text-gray-500 py-12 text-sm">
            Aucun événement créé. Cliquez sur &quot;Nouvel événement&quot; pour commencer.
          </div>
        )}
        {events.map(ev => (
          <div
            key={ev.id}
            className={clsx(
              'rounded-lg border transition-colors',
              ev.is_active ? 'border-orange-500 bg-orange-950/20' : 'border-gray-800 bg-gray-900'
            )}
          >
            {editingId === ev.id ? (
              /* ── Edit mode ── */
              <div className="p-4 space-y-4">
                <h3 className="text-sm font-bold text-yellow-400 uppercase tracking-wide">Modifier l'événement</h3>
                <CircuitPicker circuits={circuits} selectedUrl={editForm.circuit_url} onPick={applyCircuitToEdit} />
                <EventFormFields form={editForm} onChange={setEditForm} />
                <div className="flex gap-2">
                  <button
                    onClick={() => saveEdit(ev.id)}
                    disabled={!editForm.name.trim() || !editForm.circuit_url.trim()}
                    className="flex items-center gap-1.5 bg-green-700 hover:bg-green-600 disabled:opacity-40 text-white px-3 py-1.5 rounded text-xs font-medium transition-colors"
                  >
                    <Check size={13} /> Enregistrer
                  </button>
                  <button
                    onClick={cancelEdit}
                    className="flex items-center gap-1.5 bg-gray-700 hover:bg-gray-600 text-white px-3 py-1.5 rounded text-xs font-medium transition-colors"
                  >
                    <X size={13} /> Annuler
                  </button>
                </div>
              </div>
            ) : (
              /* ── Normal view ── */
              <div className="p-4">
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-bold text-white">{ev.name}</span>
                      {ev.is_active && (
                        <span className="bg-orange-600 text-white text-xs px-2 py-0.5 rounded-full font-medium">
                          Actif
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-gray-400 font-mono mt-0.5 truncate">
                      {ev.source === 'proxy' && ev.proxy_ws_url
                        ? <span className="text-blue-400">proxy: {shortRecordingName(ev.proxy_ws_url)}</span>
                        : ev.circuit_url
                      }
                    </div>
                    <div className="flex gap-4 mt-2 text-xs text-gray-400 flex-wrap">
                      {ev.event_date && (
                        <span className="flex items-center gap-1">
                          <Calendar size={11} />{fmtDate(ev.event_date)}
                        </span>
                      )}
                      <span className="flex items-center gap-1">
                        <Clock size={11} />{ev.duration_hours}h
                      </span>
                      <span>{ev.num_lanes} files · {ev.total_reserve_karts} karts réserve</span>
                      <span>Stand min {fmtDurS(ev.min_pit_duration_s)}</span>
                      <span>Relais {fmtDurS(ev.min_relay_s)}–{fmtDurS(ev.max_relay_s)}</span>
                    </div>
                    {/* Import status for recording-backed events */}
                    {ev.source === 'proxy' && isRecordingName(ev.proxy_ws_url) && (() => {
                      const running = importRunning?.evId === ev.id ? importRunning : null
                      return (
                        <div className="mt-2 flex items-center gap-2 flex-wrap">
                          {running ? (
                            <div className="flex items-center gap-2 flex-1 min-w-0">
                              <div className="flex-1 bg-gray-800 rounded-full h-1.5 min-w-[80px]">
                                <div className="bg-blue-500 h-1.5 rounded-full transition-all" style={{ width: `${running.pct}%` }} />
                              </div>
                              <span className="text-xs text-blue-400 shrink-0">{running.pct}%</span>
                              {running.resumedFrom > 0 && (
                                <span className="text-xs text-gray-500 shrink-0">reprise {fmtT(running.resumedFrom)}</span>
                              )}
                            </div>
                          ) : ev.imported_through_t != null ? (
                            <span className="text-xs text-green-600">
                              ✓ importé {fmtT(ev.imported_through_t)}
                            </span>
                          ) : (
                            <span className="text-xs text-gray-600">non importé</span>
                          )}
                        </div>
                      )
                    })()}
                  </div>

                  <div className="flex items-center gap-1.5 shrink-0 flex-wrap justify-end">
                    {!ev.is_active ? (
                      <button
                        onClick={() => activateEvent(ev.id)}
                        disabled={activating === ev.id}
                        className="flex items-center gap-1.5 bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white px-2.5 py-1.5 rounded text-xs font-medium transition-colors"
                        title="Activer cet événement"
                      >
                        <Play size={12} />
                        {activating === ev.id ? '...' : 'Activer'}
                      </button>
                    ) : (
                      <>
                        <button
                          onClick={() => stopEvent(ev.id)}
                          disabled={stopping === ev.id}
                          className="flex items-center gap-1.5 bg-red-800 hover:bg-red-700 disabled:opacity-50 text-white px-2.5 py-1.5 rounded text-xs font-medium transition-colors"
                          title="Déconnecter"
                        >
                          <Square size={11} />
                          {stopping === ev.id ? '...' : 'Stop'}
                        </button>
                        <button
                          onClick={() => startEvent(ev.id)}
                          disabled={starting === ev.id}
                          className="flex items-center gap-1.5 bg-green-800 hover:bg-green-700 disabled:opacity-50 text-white px-2.5 py-1.5 rounded text-xs font-medium transition-colors"
                          title="Reconnecter"
                        >
                          <RefreshCw size={11} />
                          {starting === ev.id ? '...' : 'Start'}
                        </button>
                        <button
                          onClick={seedFromHistory}
                          disabled={seeding}
                          className="flex items-center gap-1.5 bg-purple-800 hover:bg-purple-700 disabled:opacity-50 text-white px-2.5 py-1.5 rounded text-xs font-medium transition-colors"
                          title="Charger les niveaux d'équipes depuis la course précédente sur ce circuit"
                        >
                          <DatabaseZap size={11} />
                          {seeding ? '...' : 'Sync stints'}
                        </button>
                      </>
                    )}
                    {ev.source === 'proxy' && isRecordingName(ev.proxy_ws_url) && (
                      <button
                        onClick={() => startImport(ev)}
                        disabled={importRunning !== null}
                        className="flex items-center gap-1.5 text-gray-400 hover:text-blue-400 disabled:opacity-40 transition-colors p-1.5"
                        title={ev.imported_through_t != null ? 'Compléter l\'import' : 'Importer l\'enregistrement'}
                      >
                        {importRunning?.evId === ev.id
                          ? <Download size={13} className="animate-bounce" />
                          : <Download size={13} />}
                      </button>
                    )}
                    {ev.source === 'proxy' && (
                      <button
                        onClick={() => reanalyzeEvent(ev.id)}
                        disabled={reanalyzing === ev.id}
                        className="flex items-center gap-1 text-gray-400 hover:text-blue-400 disabled:opacity-50 transition-colors p-1.5"
                        title="Réanalyser la qualité kart avec les données complètes"
                      >
                        {reanalyzing === ev.id
                          ? <RefreshCw size={13} className="animate-spin" />
                          : <RefreshCw size={13} />}
                      </button>
                    )}
                    <button
                      onClick={() => startEdit(ev)}
                      className="flex items-center gap-1 text-gray-400 hover:text-yellow-400 transition-colors p-1.5"
                      title="Modifier"
                    >
                      <Pencil size={13} />
                    </button>
                    {confirmReset === ev.id ? (
                      <span className="flex items-center gap-1">
                        <span className="text-xs text-orange-400">Réinitialiser ?</span>
                        <button
                          onClick={() => resetEvent(ev.id)}
                          disabled={resetting === ev.id}
                          className="text-xs bg-orange-600 hover:bg-orange-500 text-white px-2 py-1 rounded font-medium transition-colors disabled:opacity-50"
                        >
                          {resetting === ev.id ? '...' : 'Oui'}
                        </button>
                        <button
                          onClick={() => setConfirmReset(null)}
                          className="text-xs text-gray-500 hover:text-gray-300 px-1 py-1 transition-colors"
                        >
                          Non
                        </button>
                      </span>
                    ) : (
                      <button
                        onClick={() => setConfirmReset(ev.id)}
                        className="flex items-center gap-1 text-gray-500 hover:text-orange-400 transition-colors p-1.5"
                        title="Réinitialiser les données (garde la config)"
                      >
                        <RotateCcw size={13} />
                      </button>
                    )}
                    <button
                      onClick={() => deleteEvent(ev.id, ev.name)}
                      className="text-gray-500 hover:text-red-400 transition-colors p-1.5"
                      title="Supprimer"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function CircuitPicker({ circuits, selectedUrl, onPick }: {
  circuits: Circuit[]
  selectedUrl: string
  onPick: (c: Circuit) => void
}) {
  return (
    <div>
      <label className="block text-xs text-gray-400 mb-1.5">Circuit</label>
      <div className="flex flex-wrap gap-2">
        {circuits.map(c => (
          <button
            key={c.circuit_url}
            onClick={() => onPick(c)}
            className={clsx(
              'px-3 py-1.5 rounded text-xs font-medium border transition-colors text-left',
              selectedUrl === c.circuit_url
                ? 'bg-orange-600 border-orange-500 text-white'
                : 'bg-gray-800 border-gray-700 text-gray-300 hover:border-orange-500'
            )}
          >
            <div>{c.name}</div>
            {(c.city || c.length_km > 0) && (
              <div className={clsx('text-xs mt-0.5', selectedUrl === c.circuit_url ? 'text-orange-200' : 'text-gray-500')}>
                {[c.city, c.length_km > 0 ? `${c.length_km} km` : null].filter(Boolean).join(' · ')}
              </div>
            )}
          </button>
        ))}
      </div>
    </div>
  )
}

function EventFormFields({ form, onChange }: {
  form: KartingEventCreate
  onChange: (f: KartingEventCreate) => void
}) {
  const set = (patch: Partial<KartingEventCreate>) => onChange({ ...form, ...patch })
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      <FormField label="Nom de l'événement" className="sm:col-span-2">
        <input className="input" placeholder="Ex: 24h Karting Saintes 2025"
          value={form.name} onChange={e => set({ name: e.target.value })} />
      </FormField>

      <FormField label="URL circuit Apex Timing" className="sm:col-span-2">
        <input className="input font-mono text-xs" value={form.circuit_url}
          onChange={e => set({ circuit_url: e.target.value })} />
      </FormField>

      <FormField label="Port WS (0 = auto)">
        <input type="number" min={0} className="input w-28" value={form.ws_port_override}
          onChange={e => set({ ws_port_override: parseInt(e.target.value) || 0 })} />
      </FormField>

      <FormField label="Date de l'événement">
        <input type="datetime-local" className="input"
          value={form.event_date?.slice(0, 16) ?? ''}
          onChange={e => set({ event_date: e.target.value ? new Date(e.target.value).toISOString() : null })} />
      </FormField>

      <FormField label="Durée (heures)">
        <input type="number" min={1} max={24} step={0.5} className="input w-24"
          value={form.duration_hours} onChange={e => set({ duration_hours: parseFloat(e.target.value) || 6 })} />
      </FormField>

      <FormField label="Temps min au stand (s)">
        <input type="number" min={0} className="input w-24" value={form.min_pit_duration_s}
          onChange={e => set({ min_pit_duration_s: parseInt(e.target.value) || 300 })} />
        <span className="text-xs text-gray-500 mt-0.5 block">{fmtDurS(form.min_pit_duration_s)}</span>
      </FormField>

      <FormField label="Relais minimum (s)">
        <input type="number" min={0} className="input w-24" value={form.min_relay_s}
          onChange={e => set({ min_relay_s: parseInt(e.target.value) || 3600 })} />
        <span className="text-xs text-gray-500 mt-0.5 block">{fmtDurS(form.min_relay_s)}</span>
      </FormField>

      <FormField label="Relais maximum (s)">
        <input type="number" min={0} className="input w-24" value={form.max_relay_s}
          onChange={e => set({ max_relay_s: parseInt(e.target.value) || 5400 })} />
        <span className="text-xs text-gray-500 mt-0.5 block">{fmtDurS(form.max_relay_s)}</span>
      </FormField>

      <FormField label="Nombre de files">
        <input type="number" min={1} max={10} className="input w-20" value={form.num_lanes}
          onChange={e => set({ num_lanes: parseInt(e.target.value) || 4 })} />
      </FormField>

      <FormField label="Karts de réserve (total)">
        <input type="number" min={1} className="input w-20" value={form.total_reserve_karts}
          onChange={e => set({ total_reserve_karts: parseInt(e.target.value) || 20 })} />
        <span className="text-xs text-gray-500 mt-0.5 block">
          {Math.ceil(form.total_reserve_karts / Math.max(form.num_lanes, 1))} par file
        </span>
      </FormField>

      <FormField label="Source de connexion" className="sm:col-span-2">
        <div className="flex gap-2">
          {(['live', 'proxy'] as const).map(src => (
            <button
              key={src}
              type="button"
              onClick={() => set({
                source: src,
                ...(src === 'proxy' && !form.proxy_ws_url
                  ? { proxy_ws_url: 'wss://apex-proxy.durdur.eu/ws' }
                  : {}),
              })}
              className={clsx(
                'px-3 py-1.5 text-xs rounded border transition-colors',
                form.source === src
                  ? 'bg-orange-600 border-orange-500 text-white'
                  : 'bg-gray-800 border-gray-700 text-gray-300 hover:border-orange-500'
              )}
            >
              {src === 'live' ? 'Apex Live' : 'Proxy'}
            </button>
          ))}
        </div>
      </FormField>

      {form.source === 'proxy' && (
        <FormField label="URL Proxy WebSocket" className="sm:col-span-2">
          <input
            className="input font-mono text-xs"
            placeholder="wss://apex-proxy.durdur.eu/ws"
            value={form.proxy_ws_url}
            onChange={e => set({ proxy_ws_url: e.target.value })}
          />
        </FormField>
      )}
    </div>
  )
}

function FormField({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={className}>
      <label className="block text-xs text-gray-400 mb-1">{label}</label>
      {children}
    </div>
  )
}
