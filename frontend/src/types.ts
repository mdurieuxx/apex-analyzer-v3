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
  last_lap_ms: number
  last_lap_received_at: number  // unix timestamp (s) when last lap was recorded
  best_lap: string
  laps: number
  on_track: string
  pits: number
  in_pit: boolean         // currently in an active pit stop
  penalty: string
  category?: string       // detected from CSS class or name prefix
  driver_name?: string    // current driver, if the grid exposes it
}

export type RatingLevel = 'ROCKET' | 'FAST' | 'MEDIUM' | 'BAD' | 'UNKNOWN'
export type TeamLevel = 'ELITE' | 'FAST' | 'MEDIUM' | 'SLOW' | 'UNKNOWN'
export type KartQuality = 'ROCKET' | 'FAST' | 'MEDIUM' | 'BAD' | 'UNKNOWN'

export interface KartRating {
  kart_label: string
  rating: RatingLevel
  confidence: number    // 0–100
  delta_pct: number     // negative = faster than expected for level
  observations: number
  team_level: TeamLevel
  kart_quality: KartQuality
}

export interface DriverPerformance {
  name: string
  level: TeamLevel
  total_laps: number
  avg_delta_pct: number | null
  stint_count: number
}

export interface StintDetail {
  driver: string
  lap_count: number
  total_laps_ms: number
  avg_ms: number
  best_ms: number
  std_ms: number
  delta_pct: number | null
  is_current: boolean
  kart_quality?: string
  level?: string
  started_at?: string
  kart_label?: string
}

export interface TeamPerformance {
  team_id: string
  team_name: string
  team_level: TeamLevel
  kart_quality: KartQuality
  kart_score_pct: number | null
  current_delta_pct: number | null
  current_stint_laps: number
  completed_stints: number
  drivers: DriverPerformance[]
  stints: StintDetail[]
}

export interface ReserveSummary {
  rocket: number
  fast: number
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
  from_bib?: string          // bib of the team that deposited this kart
  is_placeholder?: boolean   // true when kart label is unknown
  reserved_for_bib?: string  // bib of the team pre-assigned to receive this kart
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
  pit_lap_ms: number | null
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
  active_event_id: number | null
  active_event_name: string
  title1: string
  title2: string
  session_type: string
  countdown: number
  min_relay_s: number
  max_relay_s: number
  connected: boolean
  ws_clients: number
  track_ref_lap_ms: number | null
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
  best_lap_ms?: number | null
  min_pit_duration_s?: number | null
  min_relay_s?: number | null
  max_relay_s?: number | null
  created_at?: string
}

// Keep for backward compat
export type CircuitPreset = Circuit

// ── Proxy types ───────────────────────────────────────────────────────────────

export type ProxyMode = 'idle' | 'live' | 'replaying'

export type ScheduledJobStatus = 'pending' | 'running' | 'done' | 'cancelled' | 'interrupted' | 'failed'

export interface ScheduledJob {
  id: string
  circuit_url: string
  ws_port: number
  start_at: string
  name_prefix: string | null
  duration_minutes: number | null
  status: ScheduledJobStatus
  recording_name: string | null
}

export interface ProxyStatus {
  mode: ProxyMode
  clients: number
  circuit_url: string
  ws_port: number
  recording_name: string | null
  recording_msg_count: number
  replay_name: string | null
  replay_speed: number
  replay_progress: number
  bg_recordings: { name: string; msg_count: number; circuit_url: string; ws_port: number; is_live_rec: boolean; event_key: string | null }[]
  scheduled_jobs: ScheduledJob[]
}

export interface SavedProxy {
  id: number
  name: string
  ws_url: string
  created_at: string
}

export interface ProxyRecording {
  name: string
  circuit_url: string
  ws_port: number
  started_at: string
  msg_count: number
  size_kb: number
  resolved?: boolean
}

export interface ProxyCircuit {
  name: string
  url: string
  port: number
}

export interface CalendarEvent {
  uid: string
  source: string
  circuit_name: string
  event_name: string
  start_dt: string      // ISO UTC
  end_dt: string | null
  duration_h: number
  kart_type: string
  country: string
  city: string
  source_url: string
  apex_url: string | null
  apex_ws_port: number | null
  scheduled_job_id: string | null
}

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
  source: string          // "live" | "proxy"
  proxy_ws_url: string
  event_key: string | null
  imported_through_t: number | null
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
  source: string
  proxy_ws_url: string
}

export interface ProxySessionRecording {
  name: string
  resolved: boolean
  started_at_utc: string | null
  started_at_local: string | null
  timezone: string
}

export interface ProxySession {
  event_key: string
  title1: string
  title2: string
  countdown_s: number | null
  circuit_url: string
  circuit_name: string | null
  country: string | null
  recordings: ProxySessionRecording[]
  // enriched by backend
  event_id: number | null
  imported_through_t: number | null
}

// ── Track Discovery ───────────────────────────────────────────────────────────

export interface DiscoveryCircuit {
  slug: string
  name: string
  url: string
  port: number
  country: string
}

export interface DiscoveryStats {
  total: number
  discovered: number
  pending: number
  failed: number
  recent: DiscoveryCircuit[]
}

export interface DiscoveryLog {
  ts: string
  level: 'info' | 'warn' | 'error'
  msg: string
  slug: string
}

// ── Stats ──────────────────────────────────────────────────────────────────

export interface EntryStats {
  id: number
  bib: string
  team_name: string
  total_laps: number
  best_lap_ms: number | null
  avg_lap_ms: number | null
  avg_std_dev_ms: number | null
  pit_count: number
  stint_count: number
}

export interface StintStat {
  id: number
  stint_number: number
  driver_name: string
  driver_in: string
  lap_count: number
  best_lap_ms: number | null
  avg_lap_ms: number | null
  std_dev_ms: number | null
  kart_quality: KartQuality
  kart_label: string
  pit_duration_ms: number | null
  out_lap_ms: number | null
  started_at: string | null
  ended_at: string | null
  level?: string
}

export interface EntryDetail {
  id: number
  bib: string
  team_name: string
  stints: StintStat[]
}

export interface PilotStat {
  driver_name: string
  stint_count: number
  total_laps: number
  best_lap_ms: number | null
  avg_lap_ms: number | null
  avg_std_dev_ms: number | null
  bibs: string
  teams: string
}

export interface EventStatsResponse {
  event_id: number
  event_name: string
  entries: EntryStats[]
}

export interface SearchResult {
  entry_id: number
  bib: string
  team_name: string
  event_id: number
  event_name: string
  event_date: string | null
  total_laps: number
  best_lap_ms: number | null
  match_type: 'team' | 'pilot'
  driver_name?: string
}

export interface PilotEventStat {
  event_id: number
  event_name: string
  event_date: string | null
  entry_id: number
  bib: string
  team_name: string
  stint_count: number
  total_laps: number
  best_lap_ms: number | null
  avg_lap_ms: number | null
  avg_std_dev_ms: number | null
}

export interface PilotProfile {
  driver_name: string
  event_count: number
  total_stints: number
  total_laps: number
  best_lap_ms: number | null
  avg_lap_ms: number | null
  avg_std_dev_ms: number | null
  events: PilotEventStat[]
}

export interface TeamEventStat {
  event_id: number
  event_name: string
  event_date: string | null
  entry_id: number
  bib: string
  total_laps: number
  stint_count: number
  best_lap_ms: number | null
  avg_lap_ms: number | null
  avg_std_dev_ms: number | null
  pit_count: number
}

export interface TeamProfile {
  team_name: string
  event_count: number
  total_stints: number
  total_laps: number
  best_lap_ms: number | null
  avg_lap_ms: number | null
  avg_std_dev_ms: number | null
  events: TeamEventStat[]
}
