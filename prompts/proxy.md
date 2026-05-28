# Prompt de recréation — Apex Proxy

> **Note de cohérence** : Ce prompt décrit le proxy de façon autonome, mais le proxy fait partie d'un système plus large. Chaque fois que tu modifies le proxy (nouveau endpoint, changement de format, nouveau champ dans les réponses), vérifie si le backend ou le frontend doivent être adaptés en conséquence et documente ces besoins explicitement dans la section [Contrat avec le backend](#contrat-avec-le-backend).

Crée un service Python nommé **Apex Proxy**. Il fait l'intermédiaire entre les WebSockets du système de chronométrage **Apex Timing** et un backend applicatif. Il expose un WS `/ws` auquel le backend se connecte pour recevoir les données de course en temps réel.

---

## Stack

- Python 3.12, FastAPI, uvicorn, websockets 13.1, tzdata
- Pas de SQLAlchemy — la seule DB est SQLite via `sqlite3` stdlib (circuits uniquement)
- State en mémoire uniquement, pas de persistance des données live
- Port 9000, containerisé Docker

## Structure des fichiers

```
proxy/
  Dockerfile
  docker-compose.yml
  requirements.txt          # fastapi, uvicorn[standard], websockets, tzdata
  app/
    main.py                 # application FastAPI + toute la logique
    circuits_db.py          # DB SQLite des circuits
    circuit_discovery.py    # découverte DDG des URLs Apex Timing
    calendar_sources.py     # scrapers calendrier courses karting
    static/
      index.html            # UI SPA vanilla JS — admin du proxy
```

`Dockerfile` :
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./
RUN mkdir -p /data/recordings
EXPOSE 9000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000"]
```

`docker-compose.yml` :
```yaml
services:
  proxy:
    build: .
    container_name: karting-proxy
    ports:
      - "9000:9000"
    volumes:
      - recordings_data:/data/recordings
      - circuits_data:/data/circuits
    restart: unless-stopped
volumes:
  recordings_data:
  circuits_data:
```

Variables d'environnement :
- `RECORDINGS_DIR` — chemin des fichiers JSONL (défaut : `/data/recordings`)
- `CIRCUITS_DIR` — chemin de circuits.db (défaut : `/data/circuits`)

---

## Protocole WebSocket Apex Timing

**INVARIANT ABSOLU : ne jamais envoyer de message après connexion** — même vide déconnecte le serveur Java.

Les messages WS sont des strings UTF-8, potentiellement multi-lignes (séparateur `\n`). Chaque ligne est une commande `cmd|sub|val`.

Commandes pertinentes :
| Commande | Description |
|----------|-------------|
| `init\|r\|` | Reset complet — nouvelle session de course |
| `init\|p\|` | Reset partiel — reconnexion, même session |
| `title1\|<valeur>` | Nom de la session (ex : "24H AGADIR") |
| `title2\|<valeur>` | Sous-titre de la session |
| `dyn1\|countdown\|N` | Compte à rebours : N est en **millisecondes** si N > 86400, sinon en **secondes** |
| `grid\|\|<html>` | Grille complète HTML (**deux pipes**, pas `grid\|html\|`) |
| `rNcM\|*\|value` | Mise à jour de cellule incrémentale |
| `rN\|*out` / `rN\|*in` | Pilote sortant/entrant aux stands |

Il existe trois hôtes WS possibles selon le circuit :
- `www.apex-timing.com`
- `live-data.apex-timing.com`
- `live.apex-timing.com`

Chaque circuit a un port WS spécifique (ex : 8523 pour Eupen). La formule générale est `configPort + 3` mais les ports sont hardcodés dans la DB.

---

## Format JSONL des enregistrements

Chaque fichier `.jsonl` dans `RECORDINGS_DIR` :

**Ligne 1 — en-tête** (toujours présente) :
```json
{"v": 1, "circuit_url": "https://...", "ws_port": 8523, "name": "eupen_20260517_143022", "started_at": "2026-05-17T12:30:00+00:00"}
```

**Lignes de données** — un message WS par ligne :
```json
{"t": 1.234, "msg": "dyn1|countdown|86400000\ntitle1|24H Race Eupen"}
```
`t` = secondes depuis le début de l'enregistrement (float, 3 décimales). `msg` peut contenir plusieurs commandes séparées par `\n`.

**Lignes `event_meta`** (intercalées, sans `t` ni `msg`) — **une par session**, écrite dès que `title1` ET `countdown > 0` sont connus :
```json
{"event_meta": {"event_key": "a8aceb466283", "title1": "24H Race Eupen", "title2": "", "countdown_s": 86400}}
```

Ces lignes sont silencieuses pour le replay (pas de `t`/`msg`, ignorées). Elles servent uniquement au backend pour dédupliquer les events lors de l'import.

---

## State machine

```
         POST /api/live
idle ─────────────────► live
  ▲                       │
  │   POST /api/stop       │  POST /api/stop
  └───────────────────────┘

         POST /api/replay
idle ─────────────────► replaying ──► idle (fin automatique)
```

**`bg_recordings`** : dict indépendant du mode, **jamais touché par `_stop()`**. Plusieurs circuits peuvent être enregistrés simultanément, y compris pendant un replay ou un live.

### State en mémoire

```python
class _State:
    mode: str = "idle"                # "idle" | "live" | "replaying"
    circuit_url: str = ""
    ws_port: int = 0
    ws_host: str = ""
    recording_name: Optional[str] = None    # enregistrement inline du live (legacy)
    recording_file = None
    recording_msg_count: int = 0
    recording_start: float = 0.0
    replay_name: Optional[str] = None
    replay_speed: float = 1.0               # clampé 0.1–20.0
    replay_progress: int = 0
    replay_total: int = 0
    clients: set                            # WebSockets backend connectés
    last_grid_msg: Optional[str] = None     # dernier msg grid, renvoyé aux nouveaux clients
    _apex_task: Optional[asyncio.Task] = None
    _replay_task: Optional[asyncio.Task] = None
    bg_recordings: dict                     # {name: {task, msg_count, circuit_url, ws_port, event_key?}}
```

---

## Connexion WS Apex Timing — `_ws_attempts()`

Retourne une liste `[(url, ssl_ctx_or_None)]` à essayer dans l'ordre :
1. `wss://{ws_host_du_circuit}:{ws_port}/` — SSL sans vérification de certificat
2. `ws://{ws_host_du_circuit}:{ws_port}/` — sans SSL
3. `wss://www.apex-timing.com:{ws_port}/` — fallback si ws_host est différent
4. `ws://www.apex-timing.com:{ws_port}/` — fallback

Le `ws_host` vient de la DB circuits. En cas d'échec : retry avec backoff `min(3 × tentative, 30)` secondes.

---

## `_run_live(circuit_url, ws_port, record, name)`

Tâche asyncio pour le relais live. Boucle `while state.mode == "live"` :
- Se connecte avec `_ws_attempts()`
- Reçoit chaque message, l'appelle `await _broadcast(msg)`
- Si enregistrement inline actif (`state.recording_file`), écrit `{"t": ..., "msg": ...}`
- Sur déconnexion WS : retry

`_broadcast(msg)` :
- Si `msg` commence par `{"t":` (replay JSON) → extrait le `.msg` intérieur pour détecter les lignes `grid|`
- Met à jour `state.last_grid_msg` si une ligne `grid|` est trouvée
- Envoie à tous les clients connectés, supprime les clients morts

---

## `_run_bg_record(circuit_url, ws_port, name)`

Tâche asyncio indépendante. Connexion directe Apex, **sans broadcast**. Écrit dans `RECORDINGS_DIR/{name}.jsonl`.

Logique d'extraction des métadonnées de session (pour `event_meta`) :

```
Variables locales : _title1="", _title2="", _countdown_s=0, _event_meta_written=False

Pour chaque message reçu, parse chaque ligne (split \n) :
  - "init|r|"          → reset : _title1="", _title2="", _countdown_s=0, _event_meta_written=False
  - "init|p|"          → ignorer (reconnexion, même session)
  - "title1|..."        → _title1 = valeur
  - "title2|..."        → _title2 = valeur
  - "dyn1|countdown|N"  → _countdown_s = N // 1000 si N > 86400 sinon N

Si _title1 non-vide ET _countdown_s > 0 ET NOT _event_meta_written :
  → écrire ligne event_meta dans le fichier
  → state.bg_recordings[name]["event_key"] = clé calculée
  → _event_meta_written = True
```

---

## `_compute_event_key(circuit_url, countdown_s, title1, title2="")`

Identifiant stable de 12 caractères hex (SHA-1 tronqué) :

```python
slug = circuit_url.rstrip('/').split('/')[-1]
hours = round(countdown_s / 3600)
title = f"{title1} {title2}".strip()
title_norm = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
canon = f"{slug}|{hours}h|{title_norm}"
return hashlib.sha1(canon.encode()).hexdigest()[:12]
```

---

## `_run_replay(name, speed)`

1. Broadcast `"__proxy_reset__"` → attend 100ms
2. Lit les lignes du fichier en `run_in_executor` (non-bloquant)
3. Pour chaque ligne : extrait `t`, calcule le délai `(t - prev_t) / speed`, `await asyncio.sleep(delay)`
4. Broadcast `json.dumps({"t": entry["t"], "msg": entry["msg"]})`
5. Ignore les lignes sans `t`/`msg` (ex : `event_meta`)
6. À la fin : `state.mode = "idle"`, `state.replay_name = None`

---

## `_stop()`

Annule `state._apex_task` et `state._replay_task`, ferme l'enregistrement inline, remet le state à zéro. **Ne touche pas** `state.bg_recordings`.

---

## API REST

### `GET /api/status`
```json
{
  "mode": "live",
  "clients": 2,
  "circuit_url": "https://...",
  "ws_port": 8523,
  "ws_host": "www.apex-timing.com",
  "recording_name": null,
  "recording_msg_count": 0,
  "replay_name": null,
  "replay_speed": 1.0,
  "replay_progress": 0,
  "bg_recordings": [
    {
      "name": "eupen_20260517_143022",
      "msg_count": 12345,
      "circuit_url": "https://...",
      "ws_port": 8523,
      "is_live_rec": true,
      "event_key": "a8aceb466283"
    }
  ],
  "scheduled_jobs": [...]
}
```

`is_live_rec = true` pour **le premier** bg_recording dont le `circuit_url` == `state.circuit_url` quand `state.mode == "live"`. Un seul au maximum.

---

### `POST /api/live`
Body : `{circuit_url, ws_port, record?: bool, name?: str}`

- Si mode non-idle : appelle `_stop()` (les bg_recordings survivent)
- Met à jour `state.mode = "live"`, `state.circuit_url`, etc.
- Si aucun bg_recording n'existe déjà pour ce `circuit_url` → en crée un automatiquement (le `name` du body sert de nom pour ce bg_recording si fourni)
- Le relais live lui-même n'enregistre **jamais** en inline : `_run_live(circuit_url, ws_port, False, None)` — le paramètre `record` dans le body est accepté mais **ignoré**

### `POST /api/live/record`
Lance l'enregistrement inline du live en cours. `400` si pas en live. `409` si déjà en cours d'enregistrement.

### `POST /api/live/stop-record`
Arrête l'enregistrement inline sans couper le relais. Fermeture atomique (vide `state.recording_file` avant de fermer).

### `POST /api/replay`
Body : `{name, speed?: float}`
Compte les lignes du fichier (hors en-tête) pour remplir `state.replay_total`, puis lance la tâche. Broadcast `__proxy_reset__` d'abord. Retourne `{"ok": true, "total": N}`.

### `POST /api/speed`
Body : `{speed: float}` — clampé 0.1–20.0. Modifie `state.replay_speed` à la volée.

### `POST /api/stop`
Arrête live ou replay. Pas les bg_recordings.

### `POST /api/grid`
Re-broadcast le `last_grid_msg` en cache. Si pas de cache et en mode live : se connecte brièvement à Apex pour récupérer la grille (timeout 15s, cherche la première ligne `grid|`).

### `GET /api/recordings`
Liste les `.jsonl` triés par date de modif décroissante.
```json
{"recordings": [{"name", "circuit_url", "ws_port", "started_at", "msg_count", "size_kb"}]}
```
`msg_count` = nombre de toutes les lignes après l'en-tête (données WS + lignes `event_meta` incluses).

### `GET /api/recordings/sessions`
**Important : définir cette route AVANT les routes `/{name}` pour éviter les conflits.**

Scan asynchrone (thread executor) de tous les JSONL. Pour chaque fichier :
- Lit l'en-tête
- Parcourt les lignes en trackant `prev_t` (via regex `\{"t":\s*([\d.]+)`) pour estimer l'offset de chaque session
- Extrait les lignes contenant `"event_meta"`
- Groupe les sessions par `event_key`
- Calcule `started_at_local` = `started_at_utc + prev_t` converti dans le timezone du circuit

```json
{
  "sessions": [
    {
      "event_key": "a8aceb466283",
      "title1": "24H Race Eupen",
      "title2": "",
      "countdown_s": 86400,
      "circuit_url": "https://...",
      "recordings": [
        {
          "name": "eupen_20260517_143022",
          "started_at_utc": "2026-05-17T07:30:00+00:00",
          "started_at_local": "2026-05-17T09:30:00+02:00",
          "timezone": "Europe/Brussels"
        }
      ]
    }
  ],
  "unidentified": [
    {"name": "old_recording", "circuit_url": "...", "started_at_utc": "...", "started_at_local": "...", "timezone": "UTC"}
  ]
}
```

Les enregistrements sans lignes `event_meta` (anciens formats) sont dans `unidentified`.

### `GET /api/recordings/{name}/download`
Télécharge le JSONL brut (`application/x-ndjson`).

### `DELETE /api/recordings/{name}`
`409` si le fichier est en cours d'utilisation (replay, bg_recording, ou enregistrement inline).

### `POST /api/record`
Body : `{circuit_url, ws_port, name?: str}`
Démarre un bg_recording sans diffusion. `409` si nom déjà existant.

### `POST /api/stop-record?name={name}`
Arrête un bg_recording. Sans paramètre → arrête tous.

### `GET /api/circuits`
```json
{"circuits": [{"slug", "name", "url", "port", "ws_host", "country", "timezone", "tested"}]}
```
`tested` : `true` = port joignable, `false` = injoignable, `null` = jamais testé.

### `GET /api/circuits/testlog`
200 dernières entrées du log de test TCP. Colonnes : `slug`, `name`, `tested_at`, `reachable`.

### `POST /api/circuits`
Body : `{slug, name, url, port, ws_host, country?: str, timezone?: str}`. `409` si slug existe.

### `PUT /api/circuits/{slug}`
Met à jour. `404` si introuvable.

### `DELETE /api/circuits/{slug}`
`404` si introuvable.

### `GET /api/schedule`
Retourne tous les jobs (tous statuts).

### `POST /api/schedule`
Body : `{circuit_url, ws_port, start_at: ISO8601, name_prefix?: str, duration_minutes?: int}`

### `PATCH /api/schedule/{job_id}`
Modifie un job `pending`. Body : `{circuit_url, ws_port, start_at, name_prefix?, duration_minutes?}`. `400` si statut ≠ `pending`.

### `DELETE /api/schedule/{job_id}`
Annule. Si `status == "running"` : arrête aussi le bg_recording associé.

### `GET /api/circuits/{slug}/tracks`
Retourne le tracks.json parsé pour le circuit. `404` si pas encore fetchée.
```json
{"slug": "karting-mariembourg", "list": [{"title": "Grand Circuit", "size": {...}, "times": {"track": 74000, "s1": 15000, ...}, "svg": "<path data-type=\"track\" ..."}]}
```

### `GET /api/discovery/stats`
```json
{"total": 105, "discovered": 49, "pending": 33, "failed": 23, "recent": [...circuits...]}
```

### `GET /api/discovery/logs`
```json
{"logs": [{"ts": "...", "level": "info|warn|error", "msg": "...", "slug": "..."}], "running": false}
```
200 entrées les plus récentes, ordre anti-chronologique.

### `POST /api/discovery/run`
Lance une découverte manuelle de 10 circuits (port=0). Retourne `{"ok", "processed"}`.

### `GET /api/calendar`
```json
{"events": [CalendarEvent...], "last_sync": "ISO UTC ou null"}
```

### `GET /api/settings`
Retourne `{"settings": {...}, "defaults": {...}}` — valeurs courantes + défauts (depuis `config_store.py`).

### `PUT /api/settings`
Body : dict partiel des clés à modifier (toutes dans `DEFAULTS`). Applique immédiatement ; `log_level` change le logger root ; `scan_workers` recrée le `ThreadPoolExecutor`.

---

### `POST /api/calendar/sync`
Déclenche `_sync_calendar()` en tâche background. Retourne `{"ok": true}` immédiatement.

### `POST /api/calendar/{uid}/schedule`
Crée un job planifié pour un événement calendrier (30 min avant le départ). Retourne `{"ok", "job"?, "already_scheduled"?}`.

---

## `calendar_sources.py`

Scrapers async retournant des `RaceEvent`. Exécutés en parallèle via `fetch_all()`.

```python
@dataclass
class RaceEvent:
    uid: str           # SHA-1[:12] de "source|circuit|date"
    source: str
    circuit_name: str
    event_name: str
    start_dt: str      # ISO UTC
    end_dt: Optional[str]
    duration_h: float
    kart_type: str
    country: str
    city: str
    source_url: str
    apex_url: Optional[str]    # pré-rempli si circuit connu, sinon découvert par DDG
    apex_ws_port: Optional[int]
    scheduled_job_id: Optional[str]
```

`LOOKAHEAD_DAYS = 21` pour les scrapers live (sites web). Le scraper `scrape_static_2026` ignore cette fenêtre et retourne tous les événements futurs.

### Scrapers inclus
- `scrape_francorchamps` — Spa Francorchamps endurances
- `scrape_actua` — 24H Lyon
- `scrape_solokart` — Solokart Plessé
- `scrape_drs` — Dutch Racing Series
- `scrape_karting4u` — karting4u.info
- `scrape_enclos` — Circuit de l'Enclos
- `scrape_mariembourg` — Karting des Fagnes
- `scrape_kartingbenelux` — kartingbenelux.com
- `scrape_static_2026` — ~26 événements confirmés mai–décembre 2026 (dates fixes hardcodées)

### `_sync_calendar()`

1. Appelle `fetch_all()`
2. Pour chaque événement : conserve `apex_url`/`apex_ws_port`/`scheduled_job_id` précédemment découverts
3. Si `apex_url` manquant : appelle `circuit_discovery.discover(circuit_name, country)`
4. Si `apex_url` + `apex_ws_port` connus et pas encore de job : crée automatiquement un `ScheduledJob` (départ = start - 30 min, durée = dur_h × 60 + 45 min)
5. Persiste dans `CALENDAR_FILE`

Calendrier auto-syncé une fois par jour (`_calendar_loop`, premier sync 5 min après démarrage).

---

## `circuit_discovery.py`

Découverte d'URL Apex Timing via DuckDuckGo + base de données locale.

```python
async def discover(name: str, country: str) -> tuple[Optional[str], Optional[int]]:
    """Retourne (apex_url, ws_port) ou (None, None)."""
```

Stratégie :
1. Cherche dans `circuits_db` par nom/pays
2. Sinon : requête DDG `"live timing karting {name} apex-timing.com {country}"`, extrait les URLs `apex-timing.com`
3. Résout le port via `configPort` regex sur la page trouvée

---

## WebSocket `/ws`

Endpoint pour les clients backend (un seul en pratique) :
1. À la connexion : si `last_grid_msg` en cache → l'envoie immédiatement
2. Ajoute dans `state.clients`
3. Boucle `receive_text()` (les clients ne sont pas censés envoyer)
4. À la déconnexion : retire de `state.clients`

### Format des messages reçus par les clients

Les messages broadcastés ont deux formats selon la source :

- **Live** : string brut Apex — ex : `"dyn1|countdown|86400000\ntitle1|24H Race"`
- **Replay** : JSON enveloppé — `{"t": 1.234, "msg": "dyn1|countdown|86400000\ntitle1|24H Race"}`
- **Reset replay** : string spécial `"__proxy_reset__"` — envoyé avant tout replay pour signaler au client de réinitialiser son état

Le backend doit gérer les deux formats. Si le message commence par `{"t":`, c'est un replay — extraire `.msg`. Sinon c'est du live brut.

---

## `circuits_db.py`

DB SQLite, **pas SQLAlchemy**. Chemin : `$CIRCUITS_DIR/circuits.db`.

### Schema

```sql
circuits (
  slug        TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  url         TEXT NOT NULL UNIQUE,
  port        INTEGER NOT NULL,     -- 0=à découvrir, -1=introuvable, >0=connu
  ws_host     TEXT NOT NULL,
  country     TEXT NOT NULL DEFAULT '',
  timezone    TEXT NOT NULL DEFAULT 'UTC',
  tested      INTEGER DEFAULT NULL, -- NULL=jamais, 1=joignable, 0=injoignable
  tracks_json TEXT DEFAULT NULL     -- NULL=pas encore fetchée, ""=404/vide, "[...]"=données
)

circuit_test_log (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  slug      TEXT NOT NULL,
  tested_at TEXT NOT NULL,
  reachable INTEGER NOT NULL
)
```

### Migrations au démarrage

```python
for col, defn in [
    ("tested",      "INTEGER DEFAULT NULL"),
    ("timezone",    "TEXT NOT NULL DEFAULT 'UTC'"),
    ("tracks_json", "TEXT DEFAULT NULL"),
]:
    try: conn.execute(f"ALTER TABLE circuits ADD COLUMN {col} {defn}")
    except: pass
```

### Seed data — deux listes combinées

**`SEED_CIRCUITS`** (~49 circuits avec ports connus). **`SEED_CIRCUITS_LIVE`** (~64 circuits port=0 à découvrir, générés par `_make_apex(slug, country, name)` → URL `https://www.apex-timing.com/live-timing/{slug}/`.

À chaque démarrage :
1. `DELETE FROM circuits WHERE url LIKE '%live.apex-timing.com%'` — nettoie les vieilles entrées à URL incorrecte
2. Fusionne les deux listes, **déduplique par URL** (SEED_CIRCUITS en premier, port connu prioritaire)
3. UPSERT via `ON CONFLICT(slug) DO UPDATE SET url=…, ws_host=…, name=…, country=…` — préserve `port` et `tracks_json` déjà découverts
4. Backfill timezone depuis `COUNTRY_TZ` pour les circuits encore à `'UTC'`

`_to_dict()` expose `has_tracks: bool` (= `tracks_json not in (None, "")`) et ne retourne jamais le JSON brut.

### Fonctions publiques

```python
get_all() → list[dict]
get_untested() → list[dict]            # tested IS NULL ou 0
get_undiscovered(limit) → list[dict]   # port == 0
get_without_tracks(limit) → list[dict] # tracks_json IS NULL AND port != -1
get_stats() → dict                     # total/discovered/pending/failed + recent[]
get_by_url(url) → Optional[dict]
get_by_slug(slug) → Optional[dict]
get_by_slug_full(slug) → Optional[dict]  # inclut tracks_json brut
get_tracks(slug) → Optional[str]         # JSON brut ou None
update_port(slug, port) → None
update_tracks(slug, tracks_json) → None
set_tested(slug, reachable) → None
upsert(circuit) → dict
delete(slug) → bool
```

### Tester de circuits (`_circuit_tester_loop`)

Au démarrage, après 5s : teste tous les circuits non testés (tested IS NULL ou 0) par TCP connect (`asyncio.open_connection`, timeout 3s). 1s entre chaque test. Toutes les 30 min : reteste les échecs.

### Découverte de ports (`_port_discovery_loop`)

Démarre après 120s. Toutes les 60s, traite 5 circuits avec `port == 0` :
- Fetche l'URL du circuit, extrait `configPort` via regex, calcule `port = configPort + 3`
- Fallback : `circuit_discovery.discover(name, country)` via DDG
- Si introuvable : `update_port(slug, -1)`

Endpoints : `GET /api/discovery/stats`, `GET /api/discovery/logs`, `POST /api/discovery/run` (batch manuel ×10).

Logs en mémoire (`_discovery_logs`, 400 entrées max) via `_disc_log(level, msg, slug)`.

### Fetch tracks.json (`_tracks_loop`)

Démarre après 10s. Par batch de 10 circuits sans `tracks_json` (NULL, port ≠ -1) :
- GET `{url}ftp/tracks.json` (via executor, non-bloquant)
- Si `list[]` non-vide → `update_tracks(slug, raw_json)`
- Sinon (404 ou vide) → `update_tracks(slug, "")`
- 2s entre chaque circuit, 30s entre les batches, 600s si aucun circuit en attente

Endpoint : `GET /api/circuits/{slug}/tracks` → `{"slug", "list": [{"title", "size", "times", "svg"}]}`

### Scan sessions actives (`_session_scan_loop`)

Démarre après 30s. Toutes les 60s, scanne tous les circuits avec `tested=True` et `port > 0` :
- Exécuté dans un `ThreadPoolExecutor(max_workers=30, thread_name_prefix="session-scan")` → **complètement isolé du main event loop**
- Chaque thread lance `asyncio.run(_scan_session_async(c))` avec `os.nice(10)` (basse priorité CPU)
- Probe WS : connexion `wss://` (fallback `ws://`), attend jusqu'à 4s les messages
- **Session active** = réception d'un message de type `{grid, dyn1, dyn2, pass, flag, countdown, best, entry, message}` — les messages `init` seuls (server online, pas de session en cours) ne comptent pas
- Résultats stockés dans `_active_sessions: dict[str, dict]` (slug → `{active, checked_at, info, name, country, port, url}`)

Endpoints :
- `GET /api/circuits/sessions` → `{"sessions": [...], "total": N}`
- `POST /api/circuits/sessions/scan` → force un scan immédiat (`{"ok": true, "scanning": N}`)

---

## Planificateur

Jobs persistés dans `RECORDINGS_DIR/schedule.json`. Chargement au démarrage ; les jobs `"running"` passent à `"interrupted"`.

Chaque job :
```json
{
  "id": "a1b2c3d4",
  "circuit_url": "...",
  "ws_port": 8523,
  "start_at": "2026-05-17T08:00:00Z",
  "name_prefix": "eupen_24h",
  "duration_minutes": 1500,
  "status": "pending",
  "recording_name": null
}
```

Loop toutes les 15s : si `now >= start_at` et `status == "pending"` → démarre `_launch_scheduled_job`.

`_launch_scheduled_job` :
1. Génère le nom (préfixe + timestamp, ou `_default_name`)
2. Lance `_run_bg_record` dans `state.bg_recordings`
3. Si `duration_minutes` fourni : `await asyncio.sleep(duration * 60)` puis `_stop_bg_record`
4. Sinon : attend la fin naturelle de la tâche

Statuts : `pending | running | done | cancelled | interrupted | failed`

---

## UI — `static/index.html`

SPA vanilla JS (aucun framework). Servi sur `GET /`. Auto-refresh des données toutes les 2 secondes (appels parallèles `/api/status`, `/api/recordings`, `/api/schedule`). **Le scan des sessions n'est pas dans l'auto-refresh** (trop coûteux), uniquement sur bouton.

**Internationalisation** : 3 langues (FR / EN / NL). Système `I18N` dict + `t(key, ...args)` + `changeLang(l)` + `applyI18n()`. Langue persistée dans `localStorage`. Attributs `data-i18n` sur les éléments HTML statiques, `t()` pour les chaînes dynamiques JS. `locale()` helper pour les dates (`fr-FR` / `en-GB` / `nl-NL`).

### Header

- Badge mode : `Inactif` (gris) / `Live` (vert pulsé) / `Replay` (bleu pulsé)
- Chip nombre de clients WS connectés
- Horloge temps réel (date + heure locale, rafraîchie chaque seconde)
- Bouton `■ Arrêter` (visible si mode ≠ idle)
- Bouton `↻` (refresh manuel)
- Sélecteur de langue (drapeaux 🇫🇷 🇬🇧 🇳🇱)

### Onglet Live

**Carte statut replay** (visible si mode `replaying`) :
- Nom du fichier, vitesse actuelle
- Barre de progression (pourcentage sur msg_count)
- Slider vitesse **1×–20×** (step 0.5) avec mise à jour live via `POST /api/speed`
- Labels : 1× / 5× / 10× / 15× / 20×
- Bouton ■ Stop

**Carte statut live** (visible si mode `live`) :
- Nom du circuit (résolu depuis la liste des circuits)
- Bouton `⟳ Get Grid` → `POST /api/grid`
- Bouton toggle `● Rec` / `■ Stop rec` → `POST /api/live/record` ou `POST /api/live/stop-record`
- Bouton ■ Stop

**Formulaire démarrage live** :
- Filtre texte + `<select>` circuit groupé par pays avec drapeaux (🇫🇷🇧🇪🇲🇦🇮🇹🇬🇧🇳🇱🇪🇸🌍) — chaque option affiche `nom (:port)` + ` ?` si jamais testé avec succès
- Champs manuels URL + port
- Checkbox "Enregistrer" + nom optionnel
- Bouton `▶ Démarrer` / `↺ Changer` (si déjà en live)

### Onglet Enregistrer

**Enregistrements actifs** (bg_recordings) — pour chaque entrée :
- Indicateur `▶ LIVE` (vert) ou `●` (rouge pulsé)
- Nom du circuit + nom de fichier + compteur de messages
- Si `is_live_rec` : boutons `↺ Restart` (stop-record + record), `■ Stop rec`
- Sinon : boutons `▶ Live` (POST /api/live avec ce circuit), `↺ Restart` (stop + re-record), `■ Stop`

**Formulaire nouvel enregistrement** : filtre + select circuit, URL, port, nom optionnel → `POST /api/record`

### Onglet Planifier

**Contrôles de filtrage/tri** (au-dessus de la liste) :
- Recherche texte (nom événement + circuit)
- Filtre pays (dropdown auto-peuplé depuis les circuits connus)
- Filtre statut (pending / running / done / cancelled)
- Tri : date ↑ (défaut), date ↓, nom, circuit, durée

**Liste des jobs** : nom de l'événement (`name_prefix`) en titre gras + drapeau pays, circuit + date/heure + durée en meta. Bouton `✏` (pending uniquement) ouvre le modal d'édition. Bouton `✕ Annuler` (pending/running) ou `✕` (terminés).

**Modal d'édition** (`PATCH /api/schedule/{id}`) : circuit URL, port WS, début (datetime-local), durée (minutes), nom de l'événement.

**Formulaire création** :
- Circuit (filtre + select)
- Date avec boutons rapides : Aujourd'hui / Demain / +2j / +7j
- Heure avec boutons rapides : 08h / 10h / 14h
- Durée (minutes) avec boutons : 4h / 8h / 10h / 24h
- Préfixe nom (auto-rempli avec le slug du circuit sélectionné + `_`)

### Onglet Circuits

3 sous-onglets (nav pill) :

**📡 Sessions actives** (défaut)
- Compteurs actifs / scannés, bouton "Scanner maintenant" → `POST /api/circuits/sessions/scan`
- Filtres : texte (nom/pays), pays, statut (actives / inactives), tri (actives d'abord / nom / pays)
- Grille de cartes regroupées par pays ; cartes actives = fond vert + point clignotant ; nom = lien vers la page Apex live timing
- Auto-refresh 30s tant que l'onglet est actif

**📋 Circuits**
- Liste circuits avec filtre texte, bouton supprimer, formulaire ajout

**🔍 Découverte & Logs**
- Stats découverte : total / trouvés / en attente / échec
- Bouton "Lancer batch ×10" → `POST /api/discovery/run`
- Tableau des dernières découvertes
- Terminal de logs (auto-refresh 5s quand sous-onglet actif)

### Onglet Fichiers

**Section Sessions détectées** (lazy-load, pas d'auto-refresh) :
- Bouton `🔍 Scanner` → `GET /api/recordings/sessions` (désactivé pendant le scan)
- Pour chaque session : titre, durée, nom du circuit, event_key (monospace gris)
- Pour chaque enregistrement dans la session : nom de fichier (monospace), heure locale + timezone, bouton `▶ replay`
- Section séparée "Sans métadonnées" pour les anciens enregistrements sans `event_meta`

**Liste des fichiers** : nom, circuit (résolu), date, nb messages, taille KB, bouton `▶ ×N` (replay à vitesse courante), bouton `✕` supprimer (désactivé si en cours d'utilisation)

**Boutons de vitesse** pour le replay : `[0.5×, 1×, 2×, 5×, 10×, 20×]` — définit la vitesse qui sera utilisée au clic `▶`

**Logbook tests circuits** : bouton `↻` + tableau slug/date/résultat (✓ vert / ✗ rouge)

### Onglet Paramètres

Configurables persistés dans `config_store.py` → `RECORDINGS_DIR/settings.json`. 4 sections :

1. **Scan sessions actives** : `scan_interval_s` (60), `probe_timeout_s` (5.0), `ws_connect_timeout_s` (3), `scan_workers` (30)
2. **Découverte ports** : `discovery_interval_s` (60), `discovery_batch_size` (5), `discovery_idle_s` (3600)
3. **Tests connectivité** : `tester_retry_s` (1800)
4. **Système** : `log_level` (INFO / DEBUG / WARNING / ERROR)

Endpoints :
- `GET /api/settings` → `{"settings": {...}, "defaults": {...}}`
- `PUT /api/settings` (body = dict partiel) → applique immédiatement ; `log_level` change le logger root ; `scan_workers` recrée le ThreadPoolExecutor

---

## Invariants critiques

1. **Ne jamais envoyer sur le WS Apex** — même un message vide déconnecte le serveur Java.
2. **`_stop()` ne touche jamais `bg_recordings`** — ils survivent à tout changement de circuit/mode.
3. **Un seul `is_live_rec: true`** — même si plusieurs bg_recordings ont le même `circuit_url`, seul le premier dans le dict reçoit `is_live_rec: true`.
4. **`POST /api/live` ne crée pas de bg_recording** si un existe déjà pour ce `circuit_url`.
5. **`event_meta` ne se réécrit pas sur `init|p|`** — seulement `init|r|` reset le mécanisme.
6. **Le replay envoie `__proxy_reset__`** en premier message — le backend l'utilise pour réinitialiser son état.
7. **Les lignes `event_meta` dans le JSONL sont ignorées par le replay** — pas de clé `t`/`msg`, le replayer les skip silencieusement.
8. **`started_at` dans les JSONL est toujours UTC** — la conversion en heure locale se fait via le `timezone` du circuit (IANA, ex : `Europe/Brussels`).
9. **Le WS `/ws` renvoie immédiatement `last_grid_msg`** aux nouveaux clients connectés pour qu'ils aient tout de suite la grille.

---

## Contrat avec le backend

Cette section décrit les points de couplage entre le proxy et le reste du système (backend FastAPI + frontend React). Chaque modification du proxy qui touche ces points doit s'accompagner des adaptations correspondantes.

### Ce que le backend consomme du proxy

**WS `/ws`** (le backend s'y connecte en tant que client) :
- Messages live : chaînes brutes issues du WS Apex Timing, transmises telles quelles.
- Messages replay : même format que le live.
- Message spécial `__proxy_reset__` : envoyé en premier lors d'un replay. Le backend doit vider tout son état (`RaceState`, `PitManager`, `KartRanker`) et recréer les objets à réception.

**`GET /api/status`** — le backend (et le frontend via le backend) l'interroge pour connaître l'état courant du proxy. Champs importants :
- `mode` : `"idle"` / `"live"` / `"replay"`
- `circuit_url` / `circuit_name` / `ws_port`
- `bg_recordings` : liste avec `name`, `circuit_url`, `circuit_name`, `is_live_rec`, `msg_count`, `event_key`
- `ws_clients` : nombre de clients WS connectés

Si un nouveau champ est ajouté à cette réponse, mettre à jour `ProxyStatus` dans `frontend/src/types.ts`.

**`GET /api/recordings/sessions`** — utilisé par l'UI proxy pour la réconciliation. Le backend ne l'appelle pas directement (pour l'instant).

### Ce que le backend produit à partir des données proxy

**Import JSONL** (`backend/app/race/importer.py`) :
- Scanne l'intégralité du fichier pour trouver toutes les lignes `event_meta` (un fichier peut contenir plusieurs sessions).
- Construit un dict `(title1, title2) → event_key` avant de rejouer les messages.
- Sur chaque changement de session (`init|r|`) : cherche d'abord un `Event` par `event_key`, sinon par `(circuit_url, name)`. Backfille `event_key` si l'event existait sans lui.
- Un `event_key` manquant dans la DB `events` ne bloque pas l'import — il est simplement `NULL`.

**Création d'events live** (`backend/app/apex/client.py`) :
- À la réception de `__proxy_reset__` : réinitialise l'état.
- Les events live ne reçoivent pas encore d'`event_key` automatiquement — à implémenter quand le backend appellera `GET /api/status` au démarrage d'une session.

### Modèle `Event` backend

```
event_key: TEXT nullable, index  ← ajouté dans backend/app/models.py + migration database.py
```

Si le proxy ajoute des champs dans `event_meta`, les propager ici.

### Frontend (`frontend/src/types.ts`)

```typescript
interface KartingEvent {
  event_key: string | null   // ← déjà ajouté
  // ...
}

interface ProxyStatus {
  bg_recordings: Array<{
    event_key: string | null  // ← déjà ajouté
    // ...
  }>
}
```

### Adaptations en attente

| Sujet | Composant | Description |
|-------|-----------|-------------|
| Timezone `event_date` | backend importer | `event_date` doit être en heure locale du circuit (via `timezone` IANA du proxy `circuits_db`), pas en UTC. Actuellement le backend utilise `started_at` UTC. |
| `event_key` sur events live | backend apex client | Quand le backend reçoit `__proxy_reset__`, il pourrait appeler `GET /api/status` pour récupérer l'`event_key` courant et l'associer à l'event en cours. |
