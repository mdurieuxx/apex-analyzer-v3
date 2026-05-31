import { useState, useEffect } from 'react'
import { Plus, Trash2, Pencil, Check, X, MapPin, Lock, AlertCircle } from 'lucide-react'
import clsx from 'clsx'
import { api } from '../api/client'
import type { Circuit } from '../types'

const EMPTY: Omit<Circuit, 'id' | 'is_preset' | 'created_at'> = {
  name: '', country: '', city: '', length_km: 0, circuit_url: '', ws_port_override: 0, best_lap_ms: null,
}

/** Parse "m:ss.mmm" or "ss.mmm" → milliseconds. Returns null on invalid input. */
function parseLapMs(s: string): number | null {
  s = s.trim()
  const full = /^(\d+):(\d{1,2})\.(\d{1,3})$/.exec(s)
  if (full) {
    const [, m, sec, milli] = full
    return (parseInt(m) * 60 + parseInt(sec)) * 1000 + parseInt(milli.padEnd(3, '0'))
  }
  const short = /^(\d+)\.(\d{1,3})$/.exec(s)
  if (short) {
    const [, sec, milli] = short
    return parseInt(sec) * 1000 + parseInt(milli.padEnd(3, '0'))
  }
  return null
}

/** Format milliseconds → "m:ss.mmm" */
export function fmtLapMs(ms: number): string {
  const m = Math.floor(ms / 60000)
  const s = Math.floor((ms % 60000) / 1000)
  const milli = ms % 1000
  return `${m}:${String(s).padStart(2, '0')}.${String(milli).padStart(3, '0')}`
}

function FlagEmoji({ country }: { country: string }) {
  const flags: Record<string, string> = {
    France: '🇫🇷', Belgium: '🇧🇪', Morocco: '🇲🇦',
    Belgique: '🇧🇪', Maroc: '🇲🇦',
  }
  return <span>{flags[country] ?? '🏁'}</span>
}

type FormData = Omit<Circuit, 'id' | 'is_preset' | 'created_at'>

export function Circuits() {
  const [circuits, setCircuits] = useState<Circuit[]>([])
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<FormData>({ ...EMPTY })
  const [editId, setEditId] = useState<string | null>(null)  // circuit_url for presets, id for custom
  const [editForm, setEditForm] = useState<FormData>({ ...EMPTY })
  const [editIsPreset, setEditIsPreset] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.circuits.list().then(r => setCircuits(r.circuits)).catch(() => {})
  }, [])

  async function create() {
    if (!form.name.trim() || !form.circuit_url.trim()) return
    try {
      const c = await api.circuits.create(form)
      setCircuits(prev => [...prev, c])
      setForm({ ...EMPTY })
      setShowForm(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur lors de la création')
    }
  }

  async function save(c: Circuit) {
    setError(null)
    try {
      if (editIsPreset) {
        // Convert preset to a custom circuit (override)
        const created = await api.circuits.create(editForm)
        setCircuits(prev => [
          // Remove the preset from list (backend will hide it next time), add the custom
          ...prev.filter(x => x.circuit_url !== editForm.circuit_url || !x.is_preset),
          created,
        ])
      } else {
        const updated = await api.circuits.update(c.id as number, editForm)
        setCircuits(prev => prev.map(x => (x.id === c.id ? updated : x)))
      }
      setEditId(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur lors de la sauvegarde')
    }
  }

  async function remove(id: number) {
    try {
      await api.circuits.delete(id)
      setCircuits(prev => prev.filter(x => x.id !== id))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur lors de la suppression')
    }
  }

  function startEdit(c: Circuit) {
    const key = c.is_preset ? c.circuit_url : String(c.id)
    setEditId(key)
    setEditIsPreset(!!c.is_preset)
    setEditForm({
      name: c.name, country: c.country, city: c.city,
      length_km: c.length_km, circuit_url: c.circuit_url,
      ws_port_override: c.ws_port_override, best_lap_ms: c.best_lap_ms ?? null,
    })
    setError(null)
  }

  function isEditing(c: Circuit): boolean {
    if (!editId) return false
    return c.is_preset ? editId === c.circuit_url : editId === String(c.id)
  }

  const presets = circuits.filter(c => c.is_preset)
  const custom = circuits.filter(c => !c.is_preset)

  return (
    <div className="max-w-3xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-bold text-white">Circuits</h1>
        <button
          onClick={() => setShowForm(f => !f)}
          className="flex items-center gap-2 bg-orange-600 hover:bg-orange-500 text-white px-3 py-1.5 rounded text-sm font-medium transition-colors"
        >
          <Plus size={14} />
          Ajouter un circuit
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-sm text-red-400 bg-red-950/30 border border-red-800/50 rounded px-3 py-2">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {/* Add form */}
      {showForm && (
        <section className="bg-gray-900 rounded-lg border border-orange-600/40 p-5 space-y-4">
          <h2 className="text-sm font-bold uppercase text-orange-400 tracking-wide">Nouveau circuit</h2>
          <CircuitForm form={form} onChange={setForm} />
          <div className="flex gap-2">
            <button
              onClick={create}
              disabled={!form.name.trim() || !form.circuit_url.trim()}
              className="flex items-center gap-2 bg-orange-600 hover:bg-orange-500 disabled:opacity-40 text-white px-4 py-2 rounded text-sm font-medium transition-colors"
            >
              <Plus size={14} /> Créer
            </button>
            <button onClick={() => setShowForm(false)} className="px-4 py-2 rounded text-sm text-gray-400 hover:text-white transition-colors">
              Annuler
            </button>
          </div>
        </section>
      )}

      {/* Presets */}
      <section>
        <h2 className="text-xs font-bold uppercase text-gray-500 tracking-wide mb-3 flex items-center gap-2">
          <Lock size={11} /> Circuits intégrés ({presets.length})
        </h2>
        <div className="space-y-2">
          {presets.map(c => (
            isEditing(c) ? (
              <div key={c.circuit_url} className="bg-gray-900 rounded-lg border border-orange-500/60 p-4 space-y-3">
                <p className="text-xs text-orange-400/80">
                  Les modifications créeront une version personnalisée de ce circuit.
                </p>
                <CircuitForm form={editForm} onChange={setEditForm} />
                <div className="flex gap-2">
                  <button onClick={() => save(c)} className="flex items-center gap-1.5 bg-green-700 hover:bg-green-600 text-white px-3 py-1.5 rounded text-xs font-medium transition-colors">
                    <Check size={12} /> Enregistrer
                  </button>
                  <button onClick={() => setEditId(null)} className="flex items-center gap-1.5 bg-gray-700 hover:bg-gray-600 text-white px-3 py-1.5 rounded text-xs font-medium transition-colors">
                    <X size={12} /> Annuler
                  </button>
                </div>
              </div>
            ) : (
              <CircuitRow key={c.circuit_url} c={c} onEdit={() => startEdit(c)} />
            )
          ))}
        </div>
      </section>

      {/* User-defined */}
      <section>
        <h2 className="text-xs font-bold uppercase text-gray-500 tracking-wide mb-3">
          Circuits personnalisés ({custom.length})
        </h2>
        {custom.length === 0 && (
          <p className="text-sm text-gray-600">Aucun circuit ajouté.</p>
        )}
        <div className="space-y-2">
          {custom.map(c => (
            isEditing(c) ? (
              <div key={c.id} className="bg-gray-900 rounded-lg border border-orange-500/60 p-4 space-y-3">
                <CircuitForm form={editForm} onChange={setEditForm} />
                <div className="flex gap-2">
                  <button onClick={() => save(c)} className="flex items-center gap-1.5 bg-green-700 hover:bg-green-600 text-white px-3 py-1.5 rounded text-xs font-medium transition-colors">
                    <Check size={12} /> Enregistrer
                  </button>
                  <button onClick={() => setEditId(null)} className="flex items-center gap-1.5 bg-gray-700 hover:bg-gray-600 text-white px-3 py-1.5 rounded text-xs font-medium transition-colors">
                    <X size={12} /> Annuler
                  </button>
                </div>
              </div>
            ) : (
              <CircuitRow key={c.id} c={c} onEdit={() => startEdit(c)} onDelete={() => remove(c.id as number)} />
            )
          ))}
        </div>
      </section>
    </div>
  )
}

function CircuitRow({ c, onEdit, onDelete }: { c: Circuit; onEdit?: () => void; onDelete?: () => void }) {
  return (
    <div className={clsx(
      'rounded-lg border p-3 flex items-center gap-3',
      c.is_preset ? 'border-gray-800 bg-gray-900/50' : 'border-gray-800 bg-gray-900'
    )}>
      <div className="text-xl w-8 text-center">
        <FlagEmoji country={c.country} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-white">{c.name}</span>
          {c.is_preset && (
            <span className="text-xs bg-gray-700 text-gray-400 px-1.5 py-0.5 rounded">intégré</span>
          )}
          {c.length_km > 0 && (
            <span className="text-xs text-gray-500">{c.length_km} km</span>
          )}
        </div>
        {c.city && (
          <div className="flex items-center gap-1 text-xs text-gray-500 mt-0.5">
            <MapPin size={10} />
            {c.city}{c.country ? `, ${c.country}` : ''}
          </div>
        )}
        <div className="text-xs text-gray-600 font-mono mt-0.5 truncate">{c.circuit_url}</div>
        <div className="flex gap-3 text-xs text-gray-600 mt-0.5 flex-wrap">
          <span>Port WS : {c.ws_port_override || 'auto'}</span>
          {c.best_lap_ms && (
            <span className="text-purple-400 font-mono">Record : {fmtLapMs(c.best_lap_ms)}</span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <button onClick={onEdit} className="p-1.5 text-gray-500 hover:text-orange-400 transition-colors" title="Modifier">
          <Pencil size={13} />
        </button>
        {onDelete && (
          <button onClick={onDelete} className="p-1.5 text-gray-500 hover:text-red-400 transition-colors" title="Supprimer">
            <Trash2 size={13} />
          </button>
        )}
      </div>
    </div>
  )
}

function CircuitForm({
  form,
  onChange,
}: {
  form: FormData
  onChange: (f: FormData) => void
}) {
  const [lapInput, setLapInput] = useState(
    form.best_lap_ms ? fmtLapMs(form.best_lap_ms) : ''
  )

  const f = (field: keyof FormData) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = field === 'length_km' || field === 'ws_port_override'
      ? +e.target.value
      : e.target.value
    onChange({ ...form, [field]: val })
  }

  function handleLapBlur() {
    if (lapInput.trim() === '') {
      onChange({ ...form, best_lap_ms: null })
    } else {
      const ms = parseLapMs(lapInput)
      if (ms !== null) {
        onChange({ ...form, best_lap_ms: ms })
        setLapInput(fmtLapMs(ms))
      }
    }
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      <div className="sm:col-span-2">
        <label className="block text-xs text-gray-400 mb-1">Nom *</label>
        <input className="input" placeholder="Karting de Saintes" value={form.name} onChange={f('name')} />
      </div>
      <div className="sm:col-span-2">
        <label className="block text-xs text-gray-400 mb-1">URL Apex Timing *</label>
        <input className="input font-mono text-xs" placeholder="https://www.apex-timing.com/live-timing/mon-circuit/" value={form.circuit_url} onChange={f('circuit_url')} />
      </div>
      <div>
        <label className="block text-xs text-gray-400 mb-1">Port WS (0 = auto)</label>
        <input type="number" min={0} className="input w-28" value={form.ws_port_override} onChange={f('ws_port_override')} />
      </div>
      <div>
        <label className="block text-xs text-gray-400 mb-1">Longueur (km)</label>
        <input type="number" min={0} step={0.1} className="input w-28" value={form.length_km} onChange={f('length_km')} />
      </div>
      <div>
        <label className="block text-xs text-gray-400 mb-1">Ville</label>
        <input className="input" value={form.city} onChange={f('city')} />
      </div>
      <div>
        <label className="block text-xs text-gray-400 mb-1">Pays</label>
        <input className="input" value={form.country} onChange={f('country')} />
      </div>
      <div>
        <label className="block text-xs text-gray-400 mb-1">
          Record tour <span className="text-gray-600">(m:ss.mmm)</span>
        </label>
        <input
          className="input w-36 font-mono"
          placeholder="1:23.456"
          value={lapInput}
          onChange={e => setLapInput(e.target.value)}
          onBlur={handleLapBlur}
        />
      </div>
    </div>
  )
}
