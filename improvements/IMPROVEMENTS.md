# Analyse & propositions d'améliorations

Basé sur l'exploration complète du repo + la documentation des protocoles WS et HTTP API.
Aucun commit — ces fichiers sont des propositions à valider.

---

## 1. `apex/lap_api.py` — Bugs et lacunes

### 1.1 Port incorrect : `_data_port = ws_port - 3`

**Problème** : La fonction `_data_port` soustrait 3 du ws_port pour obtenir le port API.
Testé en live sur Brignoles : `configPort=8600` → `port=8600` fonctionne directement.
La soustraction `-3` donnerait `8597`, ce qui échouerait silencieusement (timeout).

**Fix** : passer `configPort` directement à `fetch_driver_laps`, sans transformation.

→ Voir `lap_api_improved.py`

### 1.2 Seulement 30 tours récupérés

**Problème** : `D#-30#D{id}.L` ne retourne que les 30 derniers tours.
Pour une course de 8h (>1000 tours/équipe), ça couvre ~20 minutes.

**Fix** : requête `D#-{total+50}#D{id}.L` avec le total depuis `D#-1#D{id}.L`.

→ Voir `lap_api_improved.py` : `fetch_all_laps()`

### 1.3 Pit stops non récupérés

**Problème** : Aucune requête `.P` — les données de pit stops (durée, pilotes, nombre de tours par relais) ne sont pas exploitées.

**Fix** : ajouter `fetch_team_stats()` qui combine `.P` + `.INF` + `.L`.

→ Voir `lap_api_improved.py`

### 1.4 Attribution tours → pilotes absente

**Problème** : `GET /driver/{id}/laps` retourne les tours de l'équipe, sans distinguer quel pilote a fait quoi.

**Fix** : algorithme cross-référence pit stops × laps (documenté dans `docs/stats-api-protocol.md` §5).

→ Voir `lap_api_improved.py` : `get_laps_per_driver()`

---

## 2. `apex/client.py` — Commentaires WS non traités

**Problème** : Les messages `com||<html>` et `comments||<html>` du flux WS sont ignorés.
Ils contiennent : green flags, pénalités, messages officiels, warnings.

**Format** :
```
comments||<p>...</p><p>...</p>    ← snapshot initial
com||<p><b>HH:MM</b><span data-flag="penalty"></span><span class="com_no noN">K</span>TEXT</p>
```

Flags : `green`, `msg`, `warning`, `penalty`

**Fix** : parser ces messages dans `client.py`, broadcaster un event `comment` via `on_event`.

→ Voir `ws_comments_handler.py`

**Impact frontend** : ajouter une section "Journal de course" dans LiveTiming.tsx (pénalités notamment).

---

## 3. `routes.py` — Endpoint `/driver/{id}/laps` limité

**Problème** :
- Appelle `fetch_driver_laps` qui ne retourne que 30 tours (bug 1.2 ci-dessus)
- Pas d'option pour récupérer l'historique complet
- Pas d'attribution par pilote

**Fix** : ajouter `?full=true` pour déclencher `fetch_all_laps()` + `get_laps_per_driver()`.

---

## 4. `kart_ranker.py` — Seuils hardcodés, non configurables

**Observation** : Les seuils `ROCKET_THRESHOLD=-1.5%`, `BAD_THRESHOLD=+1.5%` sont des constantes module.
Pour des circuits très techniques vs très rapides, ces seuils sont inadaptés.

**Proposition** : les rendre configurables via `ConfigSchema` (nouveau champ `ranker_thresholds`).
Faible priorité — à discuter selon le besoin réel.

---

## 5. `event_persister.py` — Réconciliation avec données API

**Observation** : L'event_persister enregistre les laps au fil du WS, mais ne récupère jamais
les données historiques depuis l'API HTTP (pit details, attribution pilotes).

À la fin d'une course (ou sur demande), on pourrait enrichir les stints existants avec :
- `relay_laps` précis depuis `.P`
- Attribution pilote confirmée depuis `.INF`

**Proposition** : un endpoint `POST /events/{id}/enrich` qui appelle l'API pour chaque équipe
et complète les stints manquants / confirme les attributions. Non prioritaire si le WS couvre déjà tout.

---

## Résumé priorités

| # | Priorité | Impact | Effort |
|---|---|---|---|
| 1.1 Port `-3` | **CRITIQUE** | `fetch_driver_laps` cassé sur Brignoles | 1 ligne |
| 1.2 30 tours seulement | Haute | historique incomplet | ~20 lignes |
| 2. Commentaires WS | Haute | pénalités invisibles | ~50 lignes |
| 1.3+1.4 Pit + attribution | Moyenne | enrichit stats pilotes | ~80 lignes |
| 3. Endpoint `/laps` | Moyenne | dépend de 1.2 | ~10 lignes |
| 4. Seuils configurables | Basse | confort | ~30 lignes |
| 5. Enrichissement post-course | Basse | redondant si WS OK | ~100 lignes |
| 6. Progress bar tour en cours | Backlog | UX live timing | ~40 lignes |
| 7. Météo live intégrée | Backlog | enrichit analyses post-course | ~60 lignes |
| 8. Analyse post-course Brignoles 2026 | Backlog | données capturées disponibles | à définir |

---

## 6. [BACKLOG] Reconstruction d'une course en cours sans enregistrement proxy

**Problème** : si le proxy n'a pas été démarré au début d'une course, il n'y a pas de JSONL à rejouer.
Mais la course est en cours — on peut quand même récupérer un état cohérent.

**Sources disponibles à tout moment** :

| Source | Données | Comment |
|---|---|---|
| WS live | Classement, tours, gap, statut pit | Connexion immédiate, état courant |
| `request.php` `.L` | Historique complet des tours depuis le début | Un appel par équipe |
| `request.php` `.P` + `.INF` | Historique complet des pit stops + pilotes | Un appel par équipe |

**Algorithme de reconstruction** :

1. Se connecter au WS → recevoir le snapshot grid (état instantané)
2. Pour chaque équipe (teamId = row_id sans `r`) :
   - Appeler `D#-999#D{id}.P#1#D{id}.INF` → pit stops + pilotes
   - Appeler `D#-{total+50}#D{id}.L` → tous les tours
3. Injecter les laps historiques dans `EventPersister` (déjà idempotent)
4. Recalculer les stints, niveaux, kart quality via `/events/{id}/reanalyze`

**Résultat** : base de données complète dès la connexion, comme si le proxy avait tout enregistré depuis le début.

**Endpoint suggéré** : `POST /events/{id}/backfill` — déclenche la reconstruction pour toutes les équipes actives.

**Effort estimé** : ~100 lignes (orchestration des appels API + injection dans event_persister).

---

## 7. [BACKLOG] Progress bar — position dans le tour en cours

**Inspiration** : Apex Timing affiche une petite barre de progression indiquant à quel pourcentage du tour se trouve chaque équipe en temps réel.

**Principe** : à chaque mise à jour WS, on connaît le temps du dernier tour et le temps écoulé depuis le début du tour actuel (`En piste` actualisé chaque seconde). En divisant `temps_depuis_dernier_passage / meilleur_tour_reference`, on obtient un pourcentage approximatif de progression dans le tour courant.

```python
# Pseudo-code
time_into_lap = now - last_lap_timestamp   # ms depuis le dernier tour
ref_lap = team.best_lap_ms or field_median_ms
progress = min(time_into_lap / ref_lap, 1.0)  # 0.0 → 1.0
```

**Limites** :
- C'est une estimation — le circuit n'a pas de GPS, on ne connaît pas la position réelle
- Les tours de pit faussent le calcul (durée >> meilleur tour)
- En cas de safety car / drapeau jaune, les temps de référence sont invalides

**Affichage suggéré** : barre horizontale fine sous chaque ligne de la grille, ou dans la colonne `En piste`. Largeur = `progress * 100%`, couleur = vert/jaune/rouge selon si l'équipe est rapide, dans les temps, ou lente par rapport au champ.

**Données disponibles** : tout est dans le flux WS — `last_lap_ms` et timestamp de réception suffisent. Aucun appel API supplémentaire nécessaire.

---

## 7. [BACKLOG] Météo live — polling Open-Meteo toutes les 15 min

**Principe** : pendant une course active, interroger Open-Meteo (gratuit, sans clé) toutes les 15 minutes et stocker le snapshot météo en base. Permet de corréler température / humidité avec les temps au tour en post-analyse.

**Endpoint** : `GET https://api.open-meteo.com/v1/forecast?current=temperature_2m,rain,windspeed_10m,...`

**Stockage** : nouvelle table `weather_snapshots` (event_id, captured_at, temp_c, rain_mm, wind_kmh, humidity_pct, cloudcover_pct).

**Refresh manuel** : bouton dans l'UI pour forcer un snapshot immédiat (utile si conditions changent rapidement).

**Intervalle** : 15 min en polling automatique. Réduire à 5 min si pluie détectée (rain_mm > 0).

**Usage post-course** : `normalized_lap_ms = lap_ms × (1 + α × (temp_at_lap - temp_ref))` pour neutraliser l'effet thermique dans les comparaisons de performance.

---

## 8. [BACKLOG] Analyse post-course — 24H Brignoles 2026

Les données de la course sont **déjà capturées** et disponibles localement.

### Fichiers disponibles

| Fichier | Taille | Contenu | Capturé à |
|---|---|---|---|
| `analysis/data/brignoles_2026_final.json` | 2.8 MB | Stats API complètes : 31 équipes, pilotes, pit stops, tous les tours, meilleur tour | 12h58 (fin de course) |
| `analysis/data/brignoles_2026_api.json` | 2.7 MB | Premier snapshot stats API | 12h03 |
| `analysis/data/brignoles_2026_weather.json` | 7.6 KB | Snapshots météo de la journée | — |
| `proxy/recordings/` | — | JSONL flux WS complet (grille, tours live, commentaires) | depuis le début |

### Structure `brignoles_2026_final.json`

```json
{
  "meta": {
    "event": "24H Brignoles 2026",
    "circuit": "brignoles-karting-loisir",
    "api_port": 8600,
    "captured_at": "2026-05-31T10:58:30Z",
    "teams_count": 31,
    "ok_count": 31
  },
  "grid": { ... },
  "teams": {
    "<team_id>": {
      "drivers": [...],
      "pits": [...],
      "laps": [...],
      "total_laps": N,
      "best_lap_ms": N
    }
  },
  "weather_at_capture": { ... }
}
```

### Découvertes sur la qualité des données (31/05/2026)

#### Structure JSONL — sessions dans le fichier

Le fichier `test-data/brignoles/24H_brignoles2026.jsonl` contient **une seule session continue** (204 876 messages, 26h30m) démarrant le 30/05 à 08:48 UTC :

| Session (title2) | Heure début UTC | Durée |
|---|---|---|
| ESSAIS LIBRES - 1H | 30/05 08:48 | 12 min |
| QUALIF - Q1 : 10 Minutes | 30/05 09:00 | 24 min |
| QUALIF - Q2 : Moy 5 tours | 30/05 09:24 | 17 min |
| QUALIF - Q3 : One shot | 30/05 09:41 | 23 min |
| **COURSE 24H** | **30/05 10:04** | **~25h** |
| Session 6 (post-course) | 31/05 11:03 | 13 min |
| Session 7 (post-course) | 31/05 11:16 | 6 min |

⚠️ La grille COURSE 24H a une structure différente des essais/qualifs — **pas de colonne `tlp` (tours)**. Mapping réel pendant la course : `c10=otr`, `c11=pit` (vs `c10=tlp`, `c11=otr` en essais).

#### Qualité des données API vs WS

Comparaison tour par tour sur STF BY KARTCUP (1341 tours) :

| Métrique | Valeur |
|---|---|
| Tours WS (`llp` updates) | 1 342 |
| `total_laps` API | 1 341 |
| Tours stockés dans `laps[]` | 1 333 |
| Tours avec valeur **identique** WS ↔ API | **1 329 / 1 333 = 99.7%** |
| Tours manquants dans API | laps 1–5, 880, 884 |

**`best_lap_ms` dans le JSON est faux** — ne pas utiliser. Utiliser `min(laps[].lap_ms)` ou le champ `blp` du WS.

```python
best = min(l['lap_ms'] for l in team['laps'] if l['lap_ms'] > 0)
```

Écart tours WS vs API sur l'ensemble des 31 équipes : **0 à −5 tours** (API légèrement en retard sur les derniers tours de course).

#### Source de vérité recommandée

| Donnée | Source |
|---|---|
| Classement final / positions | JSONL WS (`rk`, `sta`) |
| Meilleur tour réel | JSONL WS (`blp`) ou `min(laps[].lap_ms)` |
| Séquence complète des tours | JSONL WS (`llp` updates) |
| Numéros de tour | API `laps[].lap` |
| Pilotes + attribution relais | API `drivers` + `pits` |
| Durée des pit stops | API `pits[].pit_duration_ms` |

### Analyses possibles

- Comparaison pilotes intra-équipe (tours par pilote via attribution pit stops × laps)
- Évolution du rythme sur 24h par équipe (dégradation kart, fatigue pilote)
- Corrélation météo / temps au tour (température, vent)
- Classement des meilleurs pilotes toutes équipes confondues
- Nombre de tours / temps piste par pilote
- Détection des tours de pit (outliers) et calcul des durées de relais réelles

### Script de départ

```bash
python3 scripts/fetch_apex_stats.py --output analysis/data/brignoles_2026_final.json
# Les données sont déjà là — charger directement :
import json
data = json.load(open("analysis/data/brignoles_2026_final.json"))
teams = data["teams"]   # dict team_id → {drivers, pits, laps, ...}
```

**Effort estimé** : à définir selon l'analyse souhaitée — les données sont prêtes.
