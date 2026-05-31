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

---

## 6. [BACKLOG] Progress bar — position dans le tour en cours

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
