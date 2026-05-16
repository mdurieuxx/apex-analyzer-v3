export interface Driver {
  driver_id: string
  position: number
  kart: string          // bib / team number
  team: string
  kart_label: string    // physical kart label (e.g. "K07")
  kart_rating?: KartRating
  gap: string
  interval: string
  s1: string
  s2: string
  s3: string
  last_lap: string
  last_lap_class: string
  best_lap: string
  laps: number
  on_track: string
  pits: number
  penalty: string
}

export type RatingLevel = 'GOOD' | 'MEDIUM' | 'BAD' | 'UNKNOWN'

export interface KartRating {
  kart_label: string
  rating: RatingLevel
  confidence: number    // 0–100
  delta_pct: number     // negative = faster than baseline
  observations: number
}

export interface ReserveSummary {
  good: number
  medium: number
  bad: number
  unknown: number
}

export interface PitQueueKart {
  kart_label: string
  physical_kart_id: number
  seconds_in_pit: number
  is_eligible: boolean
  rating?: KartRating
}

export interface PitLane {
  lane: number
  karts: PitQueueKart[]
}

export interface ActivePitStop {
  driver_id: string
  bib: string
  team: string
  kart_label: string
  position: number
  pit_number: number
  seconds_in_pit: number
}

export interface PitHistoryEntry {
  bib: string
  team: string
  kart_in: string
  kart_out: string | null
  position: number
  pit_number: number
  timestamp: string
  duration_s: number | null
}

export interface KartPerformance {
  kart_label: string
  physical_kart_id: number
  total_laps: number
  avg_lap_ms: number
  best_lap_ms: number
  std_dev_ms: number
  relative_score: number
  rating: 'EXCELLENT' | 'GOOD' | 'AVERAGE' | 'POOR'
  laps_in_pit: number
  time_in_pit_s: number
}

export interface AppConfig {
  circuit_url: string
  ws_port_override: number
  num_lanes: number
  karts_per_lane: number
  min_pit_duration_s: number
  min_relay_duration_s: number
  max_relay_duration_s: number
}

export interface PhysicalKart {
  id: number
  label: string
  notes: string
}

export interface WsSnapshot {
  title1: string
  title2: string
  session_type: string
  countdown: number
  connected: boolean
  drivers: Driver[]
  lanes: PitLane[]
  reserve_summary: ReserveSummary
  pit_history: PitHistoryEntry[]
}

export interface WsMessage {
  event: string
  data: unknown
  ts: string
}

export interface Circuit {
  id: number | null
  is_preset: boolean
  name: string
  country: string
  city: string
  length_km: number
  circuit_url: string
  ws_port_override: number
  created_at?: string
}

// Keep for backward compat
export type CircuitPreset = Circuit

export interface KartingEvent {
  id: number
  name: string
  circuit_url: string
  ws_port_override: number
  event_date: string | null
  duration_hours: number
  min_pit_duration_s: number
  min_relay_s: number
  max_relay_s: number
  num_lanes: number
  total_reserve_karts: number
  is_active: boolean
  created_at: string
}

export interface KartingEventCreate {
  name: string
  circuit_url: string
  ws_port_override: number
  event_date: string | null
  duration_hours: number
  min_pit_duration_s: number
  min_relay_s: number
  max_relay_s: number
  num_lanes: number
  total_reserve_karts: number
}
