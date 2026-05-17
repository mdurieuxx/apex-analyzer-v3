# CLAUDE.md — Karting Live (apex-analyzer-v3)

Application full-stack de live timing karting endurance via Apex Timing.
Branche de développement active : `develop`. Feature branch : `claude/setup-karting-live-LQHoC`.

---

## Architecture

```
backend/app/
  apex/
    client.py          — connexion WebSocket Apex Timing, dispatch des messages
    grid_parser.py     — parsing HTML grille initiale + mises à jour incrémentales
    lap_api.py         — API HTTP Apex pour le détail des tours par pilote
    message_recorder.py — buffer circulaire des messages WS bruts (debug)
    port_discovery.py  — auto-découverte du port WS depuis la page HTML du circuit
  race/
    state.py           — RaceState (drivers, pit_lanes, pit_history, kart_assignments)
    pit_manager.py     — logique files FIFO réserve + détection pit in/out
    kart_ranker.py     — modèle de performance stint-based (ELITE/FAST/MEDIUM/SLOW)
    kart_performance.py — analyse DB (legacy, non utilisé en live)
    track_condition.py — normalisation des temps de tour (fenêtre glissante)
  api/
    routes.py          — tous les endpoints FastAPI REST
  main.py              — lifespan, WebSocket /ws, broadcast, enrichissement drivers
  models.py            — SQLAlchemy models + Pydantic schemas
  config_store.py      — lecture/écriture config en DB
  database.py          — engine SQLite

frontend/src/
  pages/
    LiveTiming.tsx     — tableau live principal
    KartPerformance.tsx — performance équipes/pilotes (nouveau modèle stint-based)
    PitLane.tsx        — files de réserve + historique stands
    Standings.tsx      — classement (course et qualifs)
    Circuits.tsx       — gestion circuits
    Events.tsx         — gestion événements de course
    Settings.tsx       — config globale
  components/
    RatingBadge.tsx    — badge kart quality (GOOD/NEUTRAL/BAD) + ReserveSummaryBar
    CategoryBadge.tsx  — badge catégorie (notc/no1/no2 CSS Apex)
    CategoryFilter.tsx — filtre par catégorie
    Layout.tsx         — nav + layout principal
  hooks/
    useWebSocket.ts    — connexion WS, état live, reconnexion auto
    useFavorites.ts    — favoris équipes (localStorage)
    useCategoryColors.ts — décodage couleurs catégories
  api/client.ts        — fonctions fetch vers /api
  types.ts             — tous les types TypeScript
```

---

## Protocole Apex Timing WebSocket

**CRITIQUE : ne jamais envoyer de message après connexion** — même vide = déconnexion serveur Java.

### Messages entrants
| Format | Description |
|--------|-------------|
| `grid\|html\|<html>` | Dump HTML complet grille (envoyé à la connexion) |
| `rNcM\|css\|value` | Mise à jour cellule incrémentale (ligne N, colonne M) |
| `rN\|*in\|0` | Équipe N entre aux stands |
| `rN\|*out\|0` | Équipe N quitte les stands |
| `rN\|*\|lap_ms\|` | Temps au tour (sans secteurs) |
| `rN\|*\|lap_ms\|s1_ms` | Temps au tour avec secteur 1 |
| `title1\|...\|val` | Titre session ligne 1 |
| `title2\|...\|val` | Titre session ligne 2 |
| `dyn1\|countdown\|N` | Compte à rebours (secondes) |

### CSS classes importantes
| Class CSS | Signification |
|-----------|--------------|
| `drteam` | Colonne team → contient `NomPilote [M:SS]` à stripper |
| `dr` | Refresh nom équipe (ignorer) |
| `tb` / `sb` / `best` | Meilleur tour session (violet) |
| `ti` / `pb` / `improved` | Meilleur tour personnel (vert) |
| `notc{decimal}` | Catégorie Misanino → décoder en `#RRGGBB` |
| `no1` / `no2` | Catégories Agadir |

### Détection colonnes (Method 0, priorité)
`detect_column_map` dans `grid_parser.py` lit l'attribut `data-type` sur chaque `<th>` :
- `pos` → position, `krt` → kart (bib), `nam` → team, `tlp` → laps, `lap` → last_lap
- `sla` → best_lap, `gap` → gap, `pit` → pits, `s1`/`s2`/`s3` → secteurs

### Layouts connus

| Circuit | pos | kart | team | last_lap | best_lap | gap | laps | pits | secteurs |
|---------|-----|------|------|----------|----------|-----|------|------|----------|
| Mariembourg | c3 | c4 | c5 | c6 | c7 | c8 | c9 | c11 | — |
| Misanino | c2 | c4 | c5 | c6 | c9 | c7 | — | c11 | — |
| Agadir | c2 | c3 | c5 | c7 | c8 | c10 | c6 | c16 | c12/c13/c14 |

---

## Modèle de performance (kart_ranker.py)

Constat clé : **on ne sait pas quel kart physique une équipe a** — l'organisation décide au stand. Donc pas de tracking par `kart_label` possible en pratique.

### Nouveau modèle stint-based (implémenté)

**4 niveaux équipe et pilote :** `ELITE` / `FAST` / `MEDIUM` / `SLOW`
- Calculé par quartile du delta historique pondéré vs moyenne champ
- Top 25% → ELITE, 25-50% → FAST, 50-75% → MEDIUM, bottom 25% → SLOW

**Kart quality :** `GOOD` / `NEUTRAL` / `BAD`
- `field_avg` = médiane glissante des 200 derniers tours (tous teams confondus)
- `team_delta` = `(team_recent_avg - field_avg) / field_avg`
- `kart_score` = `team_current_delta - expected_delta_for_team_level`
  - `< -1.5%` → GOOD (kart meilleur qu'attendu pour ce niveau d'équipe)
  - `> +2.0%` → BAD
  - sinon → NEUTRAL
- Requiert `MIN_STINT_LAPS = 4` tours valides sur le stint actuel
- Le 1er tour après un pit est toujours ignoré (out-lap)

**Niveaux pilote** : même logique, agrégée sur tous les stints nommés (quand `driver_name` est connu).

### API
- `GET /api/performance` → `{ teams: TeamPerformance[] }`
- `GET /api/performance/{team_id}` → `TeamPerformance`
- `kart_ranker.kart_quality_for_team(team_id)` → KartRating-compatible pour badge LiveTiming

---

## WebSocket frontend `/ws`

### Événements envoyés par le backend
| Event | Données clés |
|-------|-------------|
| `snapshot` | état complet : `drivers`, `lanes`, `reserve_summary`, `pit_history` |
| `grid` | mise à jour grille : `drivers`, `lanes`, `reserve_summary` |
| `pit_stop` | `bib`, `team`, `kart_label`, `position`, `pit_number`, `timestamp` |
| `pit_out` | `driver_id`, `bib`, `team`, `new_kart_label` |
| `connected` / `disconnected` | état connexion Apex |
| `session_update` | `title1`, `title2` |

### Structure `Driver` (enrichie dans `main.py`)
```typescript
{
  driver_id, position, kart (bib), team, kart_label,
  kart_rating: {
    rating: 'GOOD'|'MEDIUM'|'BAD'|'UNKNOWN',
    confidence: 0-100,
    delta_pct: number,
    observations: number,
    team_level: 'ELITE'|'FAST'|'MEDIUM'|'SLOW'|'UNKNOWN',
    kart_quality: 'GOOD'|'NEUTRAL'|'BAD'|'UNKNOWN',
  },
  gap, interval, s1, s2, s3,
  last_lap, last_lap_class, best_lap,
  laps, on_track, pits, penalty,
  category?, driver_name?
}
```

---

## Variables d'environnement

| Variable | Description |
|----------|-------------|
| `CIRCUIT_URL` | Priorité sur la config DB |
| `WS_PORT` | Port WS forcé (priorité sur config DB et auto-découverte) |
| `DATABASE_URL` | Chemin SQLite (défaut : `/data/karting.db`) |

---

## Circuits connus et ports

| Circuit | URL | Port WS |
|---------|-----|---------|
| Karting de Saintes | `https://www.apex-timing.com/live-timing/karting-de-saintes/` | 8583 |
| Karting des Fagnes (Mariembourg) | `https://www.apex-timing.com/live-timing/karting-mariembourg/` | 8313 |
| Karting de Genk | `https://www.apex-timing.com/live-timing/karting-genk/` | 8243 |
| Spa Francorchamps | `https://live.apex-timing.com/spa-francorchamps-karting/` | 9723 |
| Karting Eupen | `https://www.apex-timing.com/live-timing/karting-eupen/` | 8523 |
| MRK Agadir | `https://www.apex-timing.com/live-timing/mrkagadir/` | 8023 |

> **Spa** : sous-domaine `live.apex-timing.com` (pas `www`), header `Origin` doit correspondre.

---

## Commandes utiles

```bash
# Dev local
docker compose up --build

# Backend seul (depuis backend/)
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend seul (depuis frontend/)
npm install && npm run dev

# Capture WS brute pour debug
python tools/capture_ws.py <circuit_url> <ws_port>
```

---

## Conventions de code

- Backend : Python 3.11+, FastAPI, SQLAlchemy (SQLite), dataclasses, pas de Pydantic v1
- Frontend : React 18, TypeScript strict, Tailwind CSS, Vite, pas de Redux
- Pas de commentaires évidents — seulement les invariants non-triviaux
- Pas de backwards-compat inutile : supprimer proprement le code mort
- Les modèles live (RaceState, PitManager, KartRanker) sont **en mémoire uniquement** — pas de persistance DB pour les données temps réel
