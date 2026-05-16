import { useState, useEffect } from 'react'
import { Plus, Trash2, Play, Calendar, Clock, ChevronUp } from 'lucide-react'
import clsx from 'clsx'
import { api } from '../api/client'
import type { KartingEvent, KartingEventCreate, Circuit } from '../types'

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
}

function fmtDate(iso: string | null) {
  if (!iso) return '–'
  return new Date(iso).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

function fmtDurS(s: number) {
  const m = Math.floor(s / 60)
  return m >= 60 ? `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}` : `${m} min`
}

export function Events() {
  const [events, setEvents] = useState<KartingEvent[]>([])
  const [circuits, setCircuits] = useState<Circuit[]>([])
  const [form, setForm] = useState<KartingEventCreate>(DEFAULT_FORM)
  const [showForm, setShowForm] = useState(false)
  const [activating, setActivating] = useState<number | null>(null)

  useEffect(() => {
    api.events.list().then(r => setEvents(r.events)).catch(() => {})
    api.circuits.list().then(r => setCircuits(r.circuits)).catch(() => {})
  }, [])

  function applyCircuit(c: Circuit) {
    setForm(f => ({
      ...f,
      circuit_url: c.circuit_url,
      ws_port_override: c.ws_port_override,
    }))
  }

  async function createEvent() {
    if (!form.name.trim() || !form.circuit_url.trim()) return
    const ev = await api.events.create(form)
    setEvents(prev => [ev, ...prev])
    setForm(DEFAULT_FORM)
    setShowForm(false)
  }

  async function deleteEvent(id: number) {
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

          {/* Circuit presets */}
          <div>
            <label className="block text-xs text-gray-400 mb-1.5">Circuit (présélection)</label>
            <div className="flex flex-wrap gap-2">
              {circuits.map(c => (
                <button
                  key={c.circuit_url}
                  onClick={() => applyCircuit(c)}
                  className={clsx(
                    'px-3 py-1.5 rounded text-xs font-medium border transition-colors text-left',
                    form.circuit_url === c.circuit_url
                      ? 'bg-orange-600 border-orange-500 text-white'
                      : 'bg-gray-800 border-gray-700 text-gray-300 hover:border-orange-500'
                  )}
                >
                  <div>{c.name}</div>
                  {(c.city || c.length_km > 0) && (
                    <div className={clsx('text-xs mt-0.5', form.circuit_url === c.circuit_url ? 'text-orange-200' : 'text-gray-500')}>
                      {[c.city, c.length_km > 0 ? `${c.length_km} km` : null].filter(Boolean).join(' · ')}
                    </div>
                  )}
                </button>
              ))}
              <button
                onClick={() => setForm(f => ({ ...f, circuit_url: '' }))}
                className={clsx(
                  'px-3 py-1.5 rounded text-xs font-medium border transition-colors',
                  !circuits.find(c => c.circuit_url === form.circuit_url)
                    ? 'bg-gray-700 border-gray-500 text-white'
                    : 'bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-500'
                )}
              >
                URL manuelle
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <FormField label="Nom de l'événement" className="sm:col-span-2">
              <input
                className="input"
                placeholder="Ex: 24h Karting Saintes 2025"
                value={form.name}
                onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              />
            </FormField>

            <FormField label="URL du circuit Apex Timing" className="sm:col-span-2">
              <input
                className="input font-mono text-xs"
                value={form.circuit_url}
                onChange={e => setForm(f => ({ ...f, circuit_url: e.target.value }))}
              />
            </FormField>

            <FormField label="Port WS (0 = auto)">
              <input type="number" min={0} className="input w-28"
                value={form.ws_port_override}
                onChange={e => setForm(f => ({ ...f, ws_port_override: parseInt(e.target.value) || 0 }))}
              />
            </FormField>

            <FormField label="Date de l'événement">
              <input type="datetime-local" className="input"
                value={form.event_date?.slice(0, 16) ?? ''}
                onChange={e => setForm(f => ({ ...f, event_date: e.target.value ? new Date(e.target.value).toISOString() : null }))}
              />
            </FormField>

            <FormField label="Durée de course (heures)">
              <input type="number" min={1} max={24} step={0.5} className="input w-24"
                value={form.duration_hours}
                onChange={e => setForm(f => ({ ...f, duration_hours: parseFloat(e.target.value) || 6 }))}
              />
            </FormField>

            <FormField label="Temps min au stand (s)">
              <input type="number" min={0} className="input w-24"
                value={form.min_pit_duration_s}
                onChange={e => setForm(f => ({ ...f, min_pit_duration_s: parseInt(e.target.value) || 300 }))}
              />
              <span className="text-xs text-gray-500 mt-0.5 block">{fmtDurS(form.min_pit_duration_s)}</span>
            </FormField>

            <FormField label="Relais minimum (s)">
              <input type="number" min={0} className="input w-24"
                value={form.min_relay_s}
                onChange={e => setForm(f => ({ ...f, min_relay_s: parseInt(e.target.value) || 3600 }))}
              />
              <span className="text-xs text-gray-500 mt-0.5 block">{fmtDurS(form.min_relay_s)}</span>
            </FormField>

            <FormField label="Relais maximum (s)">
              <input type="number" min={0} className="input w-24"
                value={form.max_relay_s}
                onChange={e => setForm(f => ({ ...f, max_relay_s: parseInt(e.target.value) || 5400 }))}
              />
              <span className="text-xs text-gray-500 mt-0.5 block">{fmtDurS(form.max_relay_s)}</span>
            </FormField>

            <FormField label="Nombre de files">
              <input type="number" min={1} max={10} className="input w-20"
                value={form.num_lanes}
                onChange={e => setForm(f => ({ ...f, num_lanes: parseInt(e.target.value) || 4 }))}
              />
            </FormField>

            <FormField label="Karts de réserve (total)">
              <input type="number" min={1} className="input w-20"
                value={form.total_reserve_karts}
                onChange={e => setForm(f => ({ ...f, total_reserve_karts: parseInt(e.target.value) || 20 }))}
              />
              <span className="text-xs text-gray-500 mt-0.5 block">
                {Math.ceil(form.total_reserve_karts / Math.max(form.num_lanes, 1))} par file
              </span>
            </FormField>
          </div>

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
              'rounded-lg border p-4 transition-colors',
              ev.is_active
                ? 'border-orange-500 bg-orange-950/20'
                : 'border-gray-800 bg-gray-900'
            )}
          >
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
                <div className="text-xs text-gray-400 font-mono mt-0.5 truncate">{ev.circuit_url}</div>
                <div className="flex gap-4 mt-2 text-xs text-gray-400 flex-wrap">
                  {ev.event_date && (
                    <span className="flex items-center gap-1">
                      <Calendar size={11} />
                      {fmtDate(ev.event_date)}
                    </span>
                  )}
                  <span className="flex items-center gap-1">
                    <Clock size={11} />
                    {ev.duration_hours}h
                  </span>
                  <span>{ev.num_lanes} files · {ev.total_reserve_karts} karts réserve</span>
                  <span>Relais {fmtDurS(ev.min_relay_s)}–{fmtDurS(ev.max_relay_s)}</span>
                </div>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                {!ev.is_active && (
                  <button
                    onClick={() => activateEvent(ev.id)}
                    disabled={activating === ev.id}
                    className="flex items-center gap-1.5 bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white px-2.5 py-1.5 rounded text-xs font-medium transition-colors"
                    title="Activer cet événement"
                  >
                    <Play size={12} />
                    {activating === ev.id ? '...' : 'Activer'}
                  </button>
                )}
                <button
                  onClick={() => deleteEvent(ev.id)}
                  className="text-gray-500 hover:text-red-400 transition-colors p-1.5"
                  title="Supprimer"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
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
