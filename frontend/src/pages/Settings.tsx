import { useState, useEffect } from 'react'
import { Plus, Trash2, Save } from 'lucide-react'
import { api } from '../api/client'
import type { AppConfig, PhysicalKart, Circuit } from '../types'
import type { Driver } from '../types'
import type { LiveState } from '../hooks/useWebSocket'

interface Props { live: LiveState }

export function Settings({ live }: Props) {
  const [cfg, setCfg] = useState<AppConfig | null>(null)
  const [karts, setKarts] = useState<PhysicalKart[]>([])
  const [circuits, setCircuits] = useState<Circuit[]>([])
  const [newKart, setNewKart] = useState('')
  const [saved, setSaved] = useState(false)
  const [assignments, setAssignments] = useState<Record<string, string>>({})

  useEffect(() => {
    api.config.get().then(setCfg).catch(() => {})
    api.karts.list().then(r => setKarts(r.karts)).catch(() => {})
    api.circuits.list().then(r => setCircuits(r.circuits)).catch(() => {})
  }, [])

  async function saveConfig() {
    if (!cfg) return
    await api.config.update(cfg)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  async function addKart() {
    if (!newKart.trim()) return
    await api.karts.create(newKart.trim())
    setNewKart('')
    api.karts.list().then(r => setKarts(r.karts)).catch(() => {})
  }

  async function deleteKart(id: number) {
    await api.karts.delete(id)
    setKarts(karts.filter(k => k.id !== id))
  }

  async function assignKart(driverId: string, label: string) {
    await api.assignments.set(driverId, label)
    setAssignments(a => ({ ...a, [driverId]: label }))
  }

  if (!cfg) return <div className="text-gray-500 py-20 text-center">Chargement...</div>

  return (
    <div className="max-w-2xl space-y-8">

      {/* Race config */}
      <section className="bg-gray-900 rounded-lg border border-gray-800 p-5">
        <h2 className="text-sm font-bold uppercase text-gray-300 mb-4 tracking-wide">Configuration de la course</h2>
        <div className="space-y-4">
          {circuits.length > 0 && (
            <Field label="Circuit connu">
              <select
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-orange-500"
                value={circuits.find(c => c.circuit_url === cfg.circuit_url)?.name ?? ''}
                onChange={e => {
                  const c = circuits.find(c => c.name === e.target.value)
                  if (c) setCfg({ ...cfg, circuit_url: c.circuit_url, ws_port_override: c.ws_port_override })
                }}
              >
                <option value="">— Saisir manuellement —</option>
                {circuits.map(c => (
                  <option key={c.name} value={c.name}>{c.name}</option>
                ))}
              </select>
            </Field>
          )}
          <Field label="URL du circuit Apex Timing">
            <input
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-orange-500"
              value={cfg.circuit_url}
              onChange={e => setCfg({ ...cfg, circuit_url: e.target.value })}
            />
          </Field>
          <Field label="Port WebSocket (0 = auto-discover)">
            <input
              type="number"
              className="w-32 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-orange-500"
              value={cfg.ws_port_override}
              onChange={e => setCfg({ ...cfg, ws_port_override: parseInt(e.target.value) || 0 })}
            />
          </Field>
        </div>
      </section>

      {/* Pit config */}
      <section className="bg-gray-900 rounded-lg border border-gray-800 p-5">
        <h2 className="text-sm font-bold uppercase text-gray-300 mb-4 tracking-wide">Configuration des stands</h2>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Nombre de files">
            <input type="number" min={1} max={10}
              className="w-20 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-orange-500"
              value={cfg.num_lanes}
              onChange={e => setCfg({ ...cfg, num_lanes: parseInt(e.target.value) || 4 })}
            />
          </Field>
          <Field label="Karts de réserve par file">
            <input type="number" min={1} max={20}
              className="w-20 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-orange-500"
              value={cfg.karts_per_lane}
              onChange={e => setCfg({ ...cfg, karts_per_lane: parseInt(e.target.value) || 5 })}
            />
          </Field>
          <Field label="Temps minimum aux stands (s)">
            <input type="number" min={0}
              className="w-24 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-orange-500"
              value={cfg.min_pit_duration_s}
              onChange={e => setCfg({ ...cfg, min_pit_duration_s: parseInt(e.target.value) || 300 })}
            />
            <span className="text-xs text-gray-500 mt-1 block">{Math.floor(cfg.min_pit_duration_s / 60)} min {cfg.min_pit_duration_s % 60}s</span>
          </Field>
          <Field label="Durée min de relais (s)">
            <input type="number" min={0}
              className="w-24 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-orange-500"
              value={cfg.min_relay_duration_s}
              onChange={e => setCfg({ ...cfg, min_relay_duration_s: parseInt(e.target.value) || 3600 })}
            />
            <span className="text-xs text-gray-500 mt-1 block">{Math.floor(cfg.min_relay_duration_s / 60)} min</span>
          </Field>
          <Field label="Durée max de relais (s)">
            <input type="number" min={0}
              className="w-24 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-orange-500"
              value={cfg.max_relay_duration_s}
              onChange={e => setCfg({ ...cfg, max_relay_duration_s: parseInt(e.target.value) || 5400 })}
            />
            <span className="text-xs text-gray-500 mt-1 block">{Math.floor(cfg.max_relay_duration_s / 60)} min</span>
          </Field>
        </div>
        <button
          onClick={saveConfig}
          className="mt-4 flex items-center gap-2 bg-orange-600 hover:bg-orange-500 text-white px-4 py-2 rounded text-sm font-medium transition-colors"
        >
          <Save size={14} />
          {saved ? 'Enregistré !' : 'Enregistrer'}
        </button>
      </section>

      {/* Physical karts */}
      <section className="bg-gray-900 rounded-lg border border-gray-800 p-5">
        <h2 className="text-sm font-bold uppercase text-gray-300 mb-4 tracking-wide">Karts physiques</h2>
        <div className="flex gap-2 mb-4">
          <input
            className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-orange-500"
            placeholder="Label (ex: K07, KA, Rouge...)"
            value={newKart}
            onChange={e => setNewKart(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addKart()}
          />
          <button onClick={addKart} className="bg-orange-600 hover:bg-orange-500 text-white px-3 py-2 rounded transition-colors">
            <Plus size={16} />
          </button>
        </div>
        <div className="space-y-2">
          {karts.map(k => (
            <div key={k.id} className="flex items-center justify-between bg-gray-800 rounded px-3 py-2">
              <span className="font-mono text-white">{k.label}</span>
              <button onClick={() => deleteKart(k.id)} className="text-gray-500 hover:text-red-400 transition-colors">
                <Trash2 size={14} />
              </button>
            </div>
          ))}
          {karts.length === 0 && <p className="text-sm text-gray-600">Aucun kart physique enregistré.</p>}
        </div>
      </section>

      {/* Kart assignments */}
      {live.drivers.length > 0 && karts.length > 0 && (
        <section className="bg-gray-900 rounded-lg border border-gray-800 p-5">
          <h2 className="text-sm font-bold uppercase text-gray-300 mb-1 tracking-wide">Assignation kart → équipe</h2>
          <p className="text-xs text-gray-500 mb-4">Indiquez quel kart physique chaque équipe utilise au départ.</p>
          <div className="space-y-2">
            {live.drivers.map((d: Driver) => (
              <div key={d.driver_id} className="flex items-center gap-3 bg-gray-800 rounded px-3 py-2">
                <span className="text-sm text-white flex-1">#{d.kart} {d.team}</span>
                <select
                  className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-white focus:outline-none focus:border-orange-500"
                  value={assignments[d.driver_id] || d.kart_label || ''}
                  onChange={e => assignKart(d.driver_id, e.target.value)}
                >
                  <option value="">-- Choisir --</option>
                  {karts.map(k => <option key={k.id} value={k.label}>{k.label}</option>)}
                </select>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs text-gray-400 mb-1">{label}</label>
      {children}
    </div>
  )
}
