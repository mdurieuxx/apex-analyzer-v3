# Guide de reconstruction — Karting Live (apex-analyzer-v3)

Ce document permet de reconstruire l'application complète depuis zéro à partir d'un prompt. Il couvre le contexte métier, la stack, l'architecture, les modules, l'API et les algorithmes clés.

---

## 1. Contexte métier

Application de **live timing karting endurance** connectée à Apex Timing. Elle affiche en temps réel la grille de course, le classement virtuel corrigé des stands, la performance des équipes/pilotes/karts, et gère la réserve de karts physiques aux stands.

### Flux de données

```
Apex Timing WebSocket ──► backend/apex/client.py ──► RaceState en mémoire
                                                   ──► DB SQLite (tours, stints, stands)
                                                   ──► Broadcast WS ──► frontend React
```

En alternative : le proxy (service séparé) enregistre les messages WS bruts et les rejoue → permet le debug sans être sur place.

---

## 2. Stack technique

| Couche | Technologie |
|--------|-------------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, SQLite, websockets, uvicorn |
| Frontend | React 18, TypeScript strict, Tailwind CSS, Vite, lucide-react, clsx |
| Proxy | Python 3.12, FastAPI, websockets |
| Conteneurs | Docker (multi-stage pour le frontend) |
| Dev local | docker-compose |
| Prod | k3s (Kubernetes), images dans registre local `registry.k3s` |

---

## 3. Architecture des fichiers

```
apex-analyzer-v3/
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py                 # lifespan, WS /ws, broadcast, enrichissement
│       ├── models.py               # SQLAlchemy models + Pydantic schemas
│       ├── database.py             # engine SQLite, SessionLocal
│       ├── config_store.py         # lecture/écriture config en DB
│       ├── apex/
│       │   ├── client.py           # connexion WS Apex Timing, dispatch messages
│       │   ├── grid_parser.py      # parsing HTML grille + mises à jour incrémentales
│       │   ├── lap_api.py          # API HTTP Apex, détail tours par pilote
│       │   ├── message_recorder.py # buffer circulaire messages WS bruts (debug)
│       │   └── port_discovery.py   # auto-découverte du port WS depuis la page HTML
│       ├── race/
│       │   ├── state.py            # RaceState (drivers, pit_lanes, pit_history…)
│       │   ├── pit_manager.py      # files FIFO réserve + détection pit in/out
│       │   ├── kart_ranker.py      # modèle performance stint-based (ELITE/FAST/MEDIUM/SLOW)
│       │   ├── track_condition.py  # normalisation tours (médiane par-team best laps)
│       │   ├── event_persister.py  # persistence DB : tours, stints, stands, pilotes
│       │   └── importer.py         # import événements depuis fichiers JSONL (replay)
│       └── api/
│           └── routes.py           # tous les endpoints FastAPI REST
├── frontend/
│   ├── Dockerfile                  # multi-stage : node build → nginx
│   ├── nginx.conf                  # SPA routing + proxy /api/ et /ws vers backend
│   └── src/
│       ├── App.tsx                 # router React
│       ├── types.ts                # tous les types TypeScript
│       ├── api/client.ts           # fonctions fetch vers /api
│       ├── pages/
│       │   ├── LiveTiming.tsx      # tableau live + onglet classement virtuel
│       │   ├── Standings.tsx       # classement qualifs/course par meilleur temps
│       │   ├── KartPerformance.tsx # performance équipes/pilotes (stint-based)
│       │   ├── PitLane.tsx         # files de réserve + historique stands
│       │   ├── Events.tsx          # gestion événements de course
│       │   ├── Circuits.tsx        # gestion circuits
│       │   ├── Settings.tsx        # config globale
│       │   ├── Stats.tsx           # statistiques pilotes/tours
│       │   ├── StatsProfile.tsx    # profil d'un pilote
│       │   └── Proxy.tsx           # interface proxy (enregistrement/replay)
│       ├── components/
│       │   ├── Layout.tsx          # nav + layout principal + compteur WS clients
│       │   ├── RatingBadge.tsx     # badge qualité kart + ReserveQualityInline
│       │   ├── CategoryBadge.tsx   # badge catégorie (notc/no1/no2)
│       │   ├── CategoryFilter.tsx  # filtre par catégorie
│       │   ├── NoEventGate.tsx     # garde "aucun événement actif"
│       │   ├── TrackCondition.tsx  # indicateur condition de piste
│       │   └── HistoricalStandings.tsx # vue classement événement historique
│       ├── hooks/
│       │   ├── useWebSocket.ts     # connexion WS, LiveState, reconnexion auto
│       │   ├── useFavorites.ts     # favoris équipes (localStorage)
│       │   ├── useCategoryColors.ts # décodage couleurs catégories
│       │   └── useEventView.ts     # event historique vs live actif
│       └── utils/
│           ├── lapTime.ts          # parseMs, fmtMs, computePitPenaltyS, parseGapSec…
│           ├── onTrack.ts          # détection équipe en piste + couleur alerte relais
│           └── statsHelpers.tsx    # helpers agrégation stats
├── proxy/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── docker-compose.yml
│   └── app/
│       ├── main.py                 # proxy WS + enregistrement JSONL + replay
│       └── static/index.html       # UI proxy (replay, connexion, recording)
├── k8s/                            # manifests Kubernetes (voir doc CI/CD)
├── docker-compose.yml              # dev/prod local
├── CLAUDE.md                       # instructions contextuelles (protocole Apex…)
└── docs/                           # documentation technique
```

---

## 4. Backend — Modules clés

### 4.1 `main.py` — Orchestrateur

Responsabilités :
- **lifespan FastAPI** : démarre/arrête l'`ApexClient`, initialise `RaceState`, `PitManager`, `KartRanker`
- **`/ws` WebSocket** : liste `_ws_clients`, broadcast de tous les événements live
- **`_build_snapshot()`** : construit le payload complet envoyé à chaque nouveau client ou sur événement majeur. Inclut `track_ref_lap_ms` (référence tour courante)
- **`_enrich_driver(d)`** : ajoute `kart_rating` (via KartRanker) et `in_pit` à chaque driver
- **`restart_apex_client(cfg)`** : arrête le client courant, vide le state, recrée tout, relance

### 4.2 `apex/client.py` — Connexion Apex Timing

**CRITIQUE : ne jamais envoyer de message après connexion** — même vide = déconnexion serveur Java.

Gère :
- Connexion WS directe (port découvert par `port_discovery.py`) ou via proxy (`PROXY_WS_URL`)
- Reconnexion automatique avec backoff
- Dispatch des messages :
  - `grid|html|<html>` → `grid_parser.parse_full_grid()`
  - `rNcM|css|value` → mise à jour incrémentale
  - `rN|*in|0` / `rN|*out|0` → pit in/out
  - `rN|*|lap_ms|` → tour chronométré
  - `title1`, `title2`, `dyn1|countdown` → métadonnées session

### 4.3 `apex/grid_parser.py` — Parsing de la grille

Détecte la carte colonnes (`detect_column_map`) via l'attribut `data-type` sur les `<td>` de la ligne `head` :

| `data-type` | Champ |
|-------------|-------|
| `rk` | position |
| `no` | kart (bib) |
| `dr` / `drteam` | team (contient `NomPilote [M:SS]` à stripper) |
| `drv` | driver |
| `llp` | last_lap |
| `blp` | best_lap |
| `gap` | gap depuis leader |
| `int` | interval (écart au précédent) |
| `s1/s2/s3` | secteurs |
| `tlp` | laps |
| `otr` | on_track |
| `pit` | pits |
| `pen` | penalty |

Fallbacks : Method 1 (`data-id="r{row}c{N}"` + texte header), Method 2 (position ordinale).

### 4.4 `race/state.py` — RaceState

Dataclass en mémoire (non persistée) :
```python
@dataclass
class RaceState:
    drivers: dict[str, Driver]      # driver_id → Driver
    pit_lanes: list[PitLane]        # files de réserve
    pit_history: list[PitStop]      # derniers 200 stands
    kart_assignments: dict          # bib → kart_label
    title1, title2: str
    countdown: int
    connected: bool
    last_update: datetime
    ws_port: int
    col_map: ColumnMap
```

`session_type()` : détecte "race"/"qualifying"/"unknown" par mots-clés dans `title1/title2`.

### 4.5 `race/pit_manager.py` — Gestion des stands

- **Files FIFO** : `num_lanes` lanes, chacune avec `karts_per_lane` karts physiques
- **Détection pit in** : message `rN|*in|0` → assigne le prochain kart de la lane correspondante
- **Détection pit out** : message `rN|*out|0` → calcule `duration_s`, enregistre en `pit_history`
- **`pit_lap_ms`** : temps du tour de stand (depuis Apex) — utilisé pour le calcul de pénalité virtuelle

### 4.6 `race/kart_ranker.py` — Performance en live

Logique stint-based. Voir `docs/performance-algorithms.md` pour les détails complets.

- **4 niveaux équipe** : `ELITE/FAST/MEDIUM/SLOW` par quartile du delta pondéré historique
- **Kart quality** : `GOOD/NEUTRAL/BAD` selon `team_delta - expected_delta`
  - `< -1.5%` → GOOD, `> +2.0%` → BAD
  - Requiert `MIN_STINT_LAPS = 4` tours valides
  - 1er tour post-pit toujours ignoré (out-lap)
- **TrackConditionMonitor** : médiane des meilleurs tours de stint par équipe → référence courante

### 4.7 `race/event_persister.py` — Persistence

Écrit en DB lors des événements live :
- Tours : `entry_laps` (lap_ms, is_pit_lap, pilot_id)
- Stints : `event_stints` + `event_stint_laps`
- Stands : `event_pit_stops`
- Résumés pilotes : `pilot_event_summaries`

### 4.8 `race/importer.py` — Import replay

Import depuis fichiers JSONL (format proxy). Reconstruit l'historique complet d'un événement en DB. Utilisé pour charger des courses passées et afficher leurs statistiques.

---

## 5. Frontend — Pages et composants

### 5.1 `LiveTiming.tsx` — Page principale

Vue temps réel avec deux onglets :

**Onglet Live** : tableau complet avec `Gap`, `Gap Σ` (cumul calculé frontend), `Int.`, secteurs, dernier tour, meilleur tour, en piste, stands.

**Onglet Virtuel ✦** : classement corrigé des stands.
- Gap source : `cumulGapMap` (cumul des intervalles depuis P1, robuste aux valeurs corrompues Apex)
- Formule : `virtualGapS = cumulGap + (maxPits - team.pits) × penaltyS`
- Tri par `virtualGapS` croissant → positions virtuelles
- Colonnes : `Δ pos`, `Gap virt.`, `Int. virt.`, `Dernier`, `Meilleur`, `En piste`, `Tours`, `Stands`
- Détection doublé : `interval` contient "lap/tour"

**`computePitPenaltyS`** (utils/lapTime.ts) : calcule la pénalité nette d'un stand.
- Utilise `track_ref_lap_ms` du backend (médiane meilleurs tours stints) si disponible
- Sinon : médiane des `best_lap` des drivers
- `penaltyS = median(pit_lap_ms - refLapMs) / 1000` sur tous les stands enregistrés

### 5.2 `useWebSocket.ts` — État live

`LiveState` complet :
```typescript
interface LiveState {
  connected: boolean          // connexion Apex Timing
  wsConnected: boolean        // connexion WS frontend→backend
  activeEventId: number|null
  activeEventName: string
  title1, title2: string
  sessionType: string         // "race" | "qualifying" | "unknown"
  countdown: number
  minRelayS, maxRelayS: number
  drivers: Driver[]
  lanes: PitLane[]
  reserveSummary: ReserveSummary
  pitHistory: PitHistoryEntry[]
  lastPitStop: {...}|null
  flashingIds: Set<string>    // drivers clignotants (nouveau tour)
  pilotsByTeam: Map<string, string[]>
  pitEntryTimes: Record<string, number>  // ms wall-clock d'entrée aux stands
  importStatus: ImportStatus
  wsClients: number           // nombre de clients WS connectés au backend
  trackRefLapMs: number|null  // référence tour courante du backend
}
```

### 5.3 Structure `Driver` (types.ts)

```typescript
interface Driver {
  driver_id: string           // identifiant Apex (ex: "r12")
  position: number
  kart: string                // numéro de dossard (bib)
  team: string
  kart_label: string          // ex: "K03" (kart physique assigné)
  kart_rating: KartRating     // performance kart en cours
  gap: string                 // gap brut Apex (peut être corrompu)
  interval: string
  s1, s2, s3: string
  last_lap: string
  last_lap_class: string      // "best"|"pb"|"improved"|…
  best_lap: string
  laps: number
  on_track: string
  pits: number
  penalty: string
  in_pit: boolean             // enrichi en live
  driver_name: string|null
  category: string|null
}
```

### 5.4 `Layout.tsx` — Navigation

- Sélecteur d'événement dans le header (live actif + historiques)
- Indicateur connexion Apex (vert/rouge)
- Dot WS animé (connexion WS frontend)
- Compteur `👤N` clients connectés (affiché si N > 0)

---

## 6. WebSocket — Protocole backend→frontend

URL : `/ws` (même host que l'app, via nginx proxy)

### Événements entrants (frontend reçoit)

| Event | Données |
|-------|---------|
| `snapshot` | état complet : drivers, lanes, reserve_summary, pit_history, title1/2, session_type, countdown, connected, ws_clients, track_ref_lap_ms, active_event_id/name, min/max_relay_s |
| `grid` | mise à jour partielle : drivers, lanes, reserve_summary |
| `pit_stop` | bib, team, kart_label, position, pit_number, driver_id, timestamp |
| `pit_out` | driver_id, bib, team, new_kart_label |
| `connected` | — (Apex Timing reconnecté) |
| `disconnected` | — |
| `session_update` | title1, title2 |

---

## 7. API REST — Endpoints

Tous préfixés `/api`.

### Config
| Méthode | Path | Description |
|---------|------|-------------|
| GET | `/config` | Config active |
| PATCH | `/config` | Modifier clés |

### Live
| Méthode | Path | Description |
|---------|------|-------------|
| GET | `/status` | État connexion, session_type, driver_count, track_ref_lap_ms |
| GET | `/grid` | Grille enrichie (kart_label, kart_rating) |
| GET | `/pits/live` | Files de réserve + stands actifs |
| GET | `/pits/history` | Historique 50 derniers stands |

### Événements
| Méthode | Path | Description |
|---------|------|-------------|
| GET | `/events` | Liste événements |
| POST | `/events` | Créer |
| PATCH | `/events/{id}` | Modifier |
| DELETE | `/events/{id}` | Supprimer |
| POST | `/events/{id}/activate` | Activer → applique config + restart ApexClient |

### Performance
| Méthode | Path | Description |
|---------|------|-------------|
| GET | `/performance` | Résumé toutes équipes |
| GET | `/performance/{team_id}` | Résumé une équipe |
| GET | `/ranking` | Teams triées niveau + delta |

### Debug
| Méthode | Path | Description |
|---------|------|-------------|
| GET | `/ws-log?limit=500` | Derniers messages WS bruts |
| DELETE | `/ws-log` | Vider buffer |

---

## 8. Configuration

### Variables d'environnement

| Variable | Défaut | Description |
|----------|--------|-------------|
| `CIRCUIT_URL` | Saintes | URL page HTML circuit (priorité sur DB) |
| `WS_PORT` | auto | Port WS forcé (priorité sur DB + auto-découverte) |
| `DB_PATH` | `/data/karting.db` | Chemin SQLite |
| `PROXY_WS_URL` | — | URL WS du proxy pour relay |
| `PROXY_HTTP_URL` | — | URL HTTP du proxy pour API d'enregistrement |

### ConfigSchema (DB)

| Clé | Défaut | Description |
|-----|--------|-------------|
| `circuit_url` | Saintes | URL circuit |
| `ws_port_override` | 0 | 0 = auto |
| `num_lanes` | 4 | Lanes de réserve |
| `karts_per_lane` | 5 | Karts max par lane |
| `min_pit_duration_s` | 300 | Durée min stand (5 min) |
| `min_relay_duration_s` | 3600 | Durée min relais (60 min) |
| `max_relay_duration_s` | 5400 | Durée max relais (90 min) |

---

## 9. Circuits connus

| Circuit | URL | Port WS |
|---------|-----|---------|
| Karting de Saintes | `apex-timing.com/live-timing/karting-de-saintes/` | 8583 |
| Karting des Fagnes (Mariembourg) | `apex-timing.com/live-timing/karting-mariembourg/` | 8313 |
| Karting de Genk | `apex-timing.com/live-timing/karting-genk/` | 8243 |
| Spa Francorchamps | `live.apex-timing.com/spa-francorchamps-karting/` | 9723 |
| Karting Eupen | `apex-timing.com/live-timing/karting-eupen/` | 8523 |
| MRK Agadir | `apex-timing.com/live-timing/mrkagadir/` | 8023 |

> Spa : sous-domaine `live.apex-timing.com` (pas `www`), header `Origin` doit correspondre.

---

## 10. Dev local

```bash
# Tout en un
docker compose up --build

# Backend seul
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend seul
cd frontend && npm install && npm run dev
# → proxy Vite vers localhost:8000

# Capture WS brute
python tools/capture_ws.py <circuit_url> <ws_port>
```

---

## 11. Proxy (service séparé)

Déployé sur le NAS Synology (`apex-proxy.durdur.eu`). Enregistre les messages WS d'Apex en fichiers JSONL et les rejoue vers le backend.

- **Enregistrement** : `POST /api/record/start` → crée un fichier JSONL horodaté
- **Replay** : `POST /api/replay` avec le nom du fichier → rejoue en WS
- **UI** : `proxy/app/static/index.html` — interface web complète
- **Format JSONL** : une ligne par message, `{"ts": epoch_ms, "data": "message_ws_brut"}`

Le backend s'y connecte si `PROXY_WS_URL` est défini. Le proxy sert de source alternative à la connexion directe Apex.

---

## 12. Références croisées

- `docs/database-schema.md` — schéma DB complet avec diagramme ERD
- `docs/performance-algorithms.md` — algorithmes vitesse/régularité/kart, validés sur 4 courses
- `docs/apex-timing-interface-api.md` — protocole WS Apex Timing complet
- `docs/ws-protocol-analysis.md` — analyse des messages WS capturés
- `CLAUDE.md` — conventions de code, layouts colonnes par circuit, protocole WS résumé
