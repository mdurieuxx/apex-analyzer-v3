# WebSocket vs API Stats — Différentiel des sources de données

Analyse des deux mécanismes de collecte pour un backend complet.  
Sources : `ws-protocol-analysis.md`, `stats-api-protocol.md`, empirique sur 24H Brignoles 2026.

---

## 1. Vue d'ensemble — Ce que chaque source apporte

| Donnée | WebSocket (JSONL) | API request.php | Gagnant |
|--------|------------------|-----------------|---------|
| Temps au tour (ms exact) | ✅ `rN\|*\|ms` — temps réel | ✅ `.L` — historique complet | **WS** (timestampé) |
| Position en course | ✅ `rN\|#\|pos` — live | ❌ absent | **WS** uniquement |
| Countdown restant | ✅ `dyn1\|countdown\|ms` | ❌ absent | **WS** uniquement |
| Pit in/out (détection) | ✅ `*in` / `*out` — live | ✅ `.P` champ `in_ms`/`out_ms` | **API** (durées exactes) |
| Durée exacte d'un pit | ⚠️ calcul `*out - *in` (drift possible) | ✅ `pit_duration_ms` — authoritative | **API** |
| Nombre de tours du relais | ⚠️ comptage `*` entre pits | ✅ `relay_laps` — authoritative | **API** |
| Pilote actuel | ✅ `drteam` — live (pas tous circuits) | ✅ `.INF` `current="1"` — snapshot | **WS** (temps réel) |
| Liste complète pilotes | ❌ absent | ✅ `.INF` XML — tous les pilotes | **API** uniquement |
| Attribution tour → pilote | ❌ absent | ✅ croisement `.P` × `.L` | **API** uniquement |
| Temps cumulé par pilote | ❌ absent | ✅ `driver_total_ms` dans `.P` | **API** uniquement |
| Kart number | ✅ `notcXXX`/`noN` live | ✅ `.INF` attribut `num` (kart) | **WS** (changements live) |
| Changement de kart | ✅ nouveau `notcXXX` | ❌ absent | **WS** uniquement |
| Catégorie équipe | ✅ class CSS `noN`/`notcXXXX` | ❌ absent | **WS** uniquement |
| Nom équipe | ✅ `dr` — stable | ✅ `.INF` attribut `name` | égal |
| Meilleur tour équipe | ✅ display string (formaté) | ✅ `best_lap_ms` ms exact | **API** (numérique) |
| Secteurs (S1/S2) | ✅ `*i1`/`*i2` ms (Misanino) | ❌ absent | **WS** uniquement |
| Commentaires/pénalités | ✅ `com\|\|<p>` live | ❌ absent | **WS** uniquement |
| Titre session | ✅ `title1`/`title2` | ❌ absent | **WS** uniquement |
| Timestamp absolu de chaque tour | ✅ `t` dans JSONL (offset depuis started_at) | ❌ absent | **WS** uniquement |
| Timestamp absolu pit in/out | ✅ `t` dans JSONL | ✅ `in_ms`/`out_ms` race time | **WS** (unix), **API** (race time) |
| Flag vert / Safety car | ✅ `light\|lg\|` + `com\|\|` | ❌ absent | **WS** uniquement |

---

## 2. Données uniquement dans le WebSocket

### 2.1 Temps réel et ordre chronologique
- **Timestamp absolu de chaque tour** : le champ `t` du JSONL donne l'offset depuis `started_at`. Combiné avec le header, on obtient l'heure UTC exacte de chaque `*` lap. L'API ne retourne que le numéro de tour et son temps, pas quand il a été fait.
- **Countdown restant** : `dyn1|countdown|ms`. Permet de connaître le temps de course restant au moment de chaque événement. Absent de l'API.
- **Ordre d'arrivée des événements** : le JSONL préserve l'ordre exact pit-in → tours → pit-out → nouveau pilote. L'API donne les pits triés mais sans les événements intermédiaires.

### 2.2 Données live non persistées par l'API
- **Position en course** à chaque instant (`#`) — l'API ne stocke pas l'historique des positions
- **Changements de kart** (`notcXXX`) — détectable seulement via le flux WS
- **Catégorie de l'équipe** (classe CSS `noN`/`notcXXXXX`) — clé pour les algorithmes de performance par catégorie
- **Secteurs S1/S2** (Misanino, Agadir) — jamais dans l'API
- **Pénalités et commentaires** (`com||`) — live uniquement

### 2.3 Précision temporelle
- Le timestamp WS `t` est en secondes avec précision milliseconde depuis `started_at`
- L'API `in_ms`/`out_ms` est en race time (ms depuis le départ de la course) → nécessite de connaître `started_at` pour aligner les deux

---

## 3. Données uniquement dans l'API

### 3.1 Identités nominatives des pilotes
- **Liste complète des pilotes d'une équipe** (`.INF`) : le WS ne donne que le pilote actuel via `drteam`, jamais la liste. Pour connaître les 3-6 pilotes d'une équipe, l'API est obligatoire.
- **ID interne de chaque pilote** : clé de jointure entre `.P` et `.INF`, absente du WS.

### 3.2 Données authoritative des pit stops
- **`pit_duration_ms`** : durée exacte calculée côté serveur Apex. Le WS permet de calculer `t(out) - t(in)` mais avec un léger drift (latence réseau, délai de traitement). L'API est la référence.
- **`relay_laps`** : nombre de tours du relais se terminant à ce pit, calculé côté serveur. Via le WS, on compte les `*` entre deux `*in`, mais avec risque de raté (message perdu, reconnexion).
- **`track_ms`** : durée totale du stint sur piste. Non calculable proprement depuis le WS sans timestamp précis du début de stint.
- **`driver_total_ms`** : temps cumulé du pilote au fil de la course. Nécessite un recalcul complet depuis le WS ; l'API le donne directement.

### 3.3 Attribution tours → pilotes
- L'algorithme de croisement `.P` × `.L` (cf. `stats-api-protocol.md` §5) donne pour chaque tour son pilote. Impossible depuis le WS seul : `drteam` change au moment du pit-out mais le numéro de tour correspondant est ambigu pendant la transition.

---

## 4. Données présentes dans les deux — comparaison de qualité

| Donnée | WS | API | Différence |
|--------|-----|-----|------------|
| **Temps au tour** | ms exact, timestampé | ms exact, non timestampé | WS préférable pour analyse temporelle |
| **Pit in time** | `t` JSONL (secondes depuis start) | `in_ms` (ms race time) | Même info, unités différentes |
| **Pit out time** | `t` JSONL | `out_ms` | Même info, unités différentes |
| **Durée pit** | calculée (drift possible) | `pit_duration_ms` authoritative | API préférable |
| **Nom équipe** | `dr` | `.INF` name | Identiques |
| **Pilote actuel** | `drteam` (live) | `.INF` current="1" (snapshot) | WS pour live, API pour vérification post-course |
| **Meilleur tour** | display string ("1:02.047") | ms entier (62047) | API préférable (calcul direct) |
| **Nombre de tours** | comptage des `*` | `D#-1#D{id}.L` total | API authoritative (comptage WS peut rater) |

---

## 5. Ce que la combinaison des deux permet — valeur ajoutée

### 5.1 Attribution tour → pilote avec timestamp
```
WS :  tour N arrived at t=12345.6s  (timestamp absolu)
API : tour N belongs to driver REMI LOTH (via .P cross-reference)
→ "REMI LOTH a fait son tour N à 14h23:45 UTC en 1:01.644"
```
Impossible avec une seule source.

### 5.2 Validation de la détection de pit stop
```
WS :  *in à t=4521.3s, *out à t=4643.7s → durée calculée = 122.4s
API : pit_duration_ms = 121547 → durée authoritative = 121.5s
→ delta = 0.9s (latence réseau) → le WS est fiable à ~1s près
```
Permet de calibrer la tolérance d'erreur du WS.

### 5.3 Détection de kart physique par stint
```
WS :  stint 8 de HIVE-X → kart notc8388863 (kart jaune)
API : stint 8 = driver DURIEUX MARC, relay_laps=9, track_ms=...
→ "DURIEUX MARC a conduit le kart jaune pendant 9 tours à 20h"
```
Le WS donne le kart (via CSS class), l'API donne le pilote → corrélation possible.

### 5.4 Reconstruction de la timeline complète d'une course
```
Pour chaque tour T de l'équipe E :
  - timestamp UTC    : WS (t + started_at)
  - lap_ms           : WS ou API (identique)
  - countdown restant: WS (dyn1|countdown interpolé)
  - pilote           : API (.P × .L)
  - kart             : WS (notcXXX au moment du tour)
  - catégorie        : WS (noN class)
  - position         : WS (#)
```

### 5.5 Calibration des seuils de performance par circuit
```
field_median(t) = médiane glissante des tours dans la fenêtre [t-15min, t+15min]
               → calculable depuis WS uniquement (timestamps nécessaires)

driver_delta = best_lap_driver - expected_from_level
             → nécessite attribution pilote (API) + timestamp (WS)
```

---

## 6. Gaps — ce qui manque dans les deux sources

| Information | Disponible ? | Workaround |
|-------------|-------------|------------|
| Heure de départ exacte de la course | ⚠️ JSONL `started_at` + offset `dyn1|countdown` | Calculable si countdown = durée race |
| Conditions météo | ❌ sauf `wth1` vide à Misanino | External |
| Tour exact du changement de kart | ⚠️ WS donne l'événement mais pas le tour # | Interpoler avec dernier `*` avant le changement |
| Identité pilote au démarrage (avant 1er pit) | ⚠️ WS `drteam` si dispo sinon ❌ | `.INF` `current="1"` au 1er appel |
| Out-lap / in-lap flaggés | ⚠️ déductible (lap # = `pits[N].lap` ±1) | Croisement `.P` + `.L` |
| Pénalités avec tour exact | ⚠️ `com||` donne le tour en texte libre | Parser le message texte |

---

## 7. Recommandations pour le backend temps réel

### Sources à combiner au démarrage d'un event
1. **Appel API initial** (`D#-999#D{id}.P#1#D{id}.INF`) pour chaque équipe :
   - Récupère la liste des pilotes (INF)
   - Récupère l'historique des pits avec attribution pilote
   - Base pour l'attribution tours → pilotes

2. **Flux WS** en continu :
   - Catégories, positions, karts, timestamps, pénalités
   - Nouveaux tours et pits en live

3. **Rafraîchissement API périodique** (toutes les N minutes ou post-pit) :
   - Mettre à jour `relay_laps` et `driver_total_ms` authoritative
   - Corriger les attributions pilote si `drteam` absent du WS

### Priorité source par donnée
| Donnée | Source prioritaire | Source fallback |
|--------|-------------------|-----------------|
| Temps au tour | WS (timestampé) | API (non timestampé) |
| Attribution pilote | API (authoritative) | WS drteam |
| Durée pit | API (authoritative) | WS calculé |
| Position | WS (live) | — |
| Catégorie/kart | WS (live, changements) | — |
| Liste pilotes | API (seule source) | — |
| Timestamp événements | WS (seule source) | — |
| Pénalités | WS (seule source) | — |

---

## 8. Impact sur les algorithmes existants

### `kart_ranker.py` — Détection de bon/mauvais kart
**Données manquantes actuellement** :
- Attribution tour → kart physique : le WS donne `notcXXX` mais pas par tour, seulement les changements. Il faut propager la dernière valeur connue à chaque tour.
- Attribution tour → pilote : actuellement absent, l'API le fournit.

**Amélioration possible** :
```
score_kart = best_lap_du_stint - expected_from_driver_level
           (au lieu de best_lap_du_stint - expected_from_team_level)
```
Nécessite : attribution pilote (API) + historique des niveaux pilotes (plusieurs courses).

### `event_persister.py` — Persistance des stints
**Actuel** : détecte les stints via `*in`/`*out` WS, compte les tours par comptage.  
**Amélioration** : enrichir post-pit avec `relay_laps` et `driver_id` depuis l'API → stints exacts avec pilote nommé.

### Médiane champ temporelle `field_avg`
**Actuel** : fenêtre glissante de 200 tours (sans dimension temporelle).  
**Amélioration** : fenêtre temporelle ±30min basée sur timestamp WS → plus robuste aux variations de piste (cf. `race-analysis-findings.md`, variation jusqu'à 2.4% sur 24h).
