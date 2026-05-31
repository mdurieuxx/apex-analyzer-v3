# Modèle de performance — proposition de refonte

Basé sur l'analyse des données Brignoles 2026 (JSONL WS + API stats).
À implémenter progressivement — ne pas tout toucher à la fois.

---

## Principe fondateur

Toute mesure de performance — pilote, kart, équipe — doit être exprimée **relativement aux conditions de piste du moment**, pas en millisecondes absolus. Un pilote qui fait 1:02 par temps froid avec du trafic peut être plus performant qu'un pilote qui fait 1:01 sur piste parfaite.

```
performance(x) = delta_pct(x) = (temps(x) - ref_piste_T) / ref_piste_T
```

`ref_piste_T` = médiane glissante des tours normaux du champ sur une fenêtre temporelle courte (~20-30 min) — pas par nombre de tours.

---

## 1. Filtrage des tours

### 1.1 Exclusion des tours aberrants

Avant tout calcul, filtrer les tours qui ne reflètent pas la vraie vitesse :

```
outlier si : lap_ms > median_pilote_courant × (1 + OUTLIER_PCT)
```

**`OUTLIER_PCT` recommandé : +12%**

Justification sur Brignoles : les tours de dépassement difficile ou d'incident coûtent typiquement 5-15% de plus que le temps normal. À 1:00 de référence, +12% = 1:07.2 — tout ce qui dépasse ça n'est pas représentatif.

Les tours exclus sont **conservés** dans les données brutes mais marqués `is_outlier=True`. Ils ne contribuent pas aux scores mais restent visibles dans l'historique.

### 1.2 Tours autour d'un pit stop

```
passage 1  : demi-tour (ignoré — existant)
passage 2  : out-lap   (séparé — existant, à enrichir)
passage 3-4: warm-up   (exclu des averages — existant)
```

**Nouvelle règle sur l'out-lap** :
- Garder l'out-lap mais l'indexer comme `"out"` dans son propre bucket
- Comparer les out-laps entre équipes → indicateur kart à froid
- Un out-lap < `ref_piste_T × 1.04` = "super out-lap" → signal fort sur l'état du kart
- Normaliser par durée du pit (`pit_duration_ms`) : un kart qui sort après 3 min de stop froid est désavantagé — appliquer un malus de référence de `+2%` si `pit_duration > 120s`

---

## 2. Régularité — métrique centrale

La régularité est **au moins aussi importante que la vitesse pure**. Un pilote rapide mais irrégulier coûte des tours perdus et fatigue le kart.

### 2.1 Score de régularité pilote

Sur les tours filtrés (hors outliers, hors out-lap, hors warm-up) du relais courant :

```python
# IQR normalisé — robuste aux outliers résiduels
q75, q25 = percentile(laps_filtered, [75, 25])
regularity_score = (q75 - q25) / median(laps_filtered)
```

Valeurs observées sur Brignoles (estimation) :
- Pilote excellent : `regularity_score < 0.008` (< 0.8% d'écart IQR)
- Pilote correct : `0.008 – 0.015`
- Pilote irrégulier : `> 0.020`

### 2.2 Score combiné pilote

```python
pace_score      = delta_pct vs ref_piste_T   # vitesse relative (négatif = rapide)
regularity_cost = regularity_score × REGULARITY_WEIGHT   # REGULARITY_WEIGHT = 0.5
combined_score  = pace_score + regularity_cost
```

`REGULARITY_WEIGHT = 0.5` signifie que 1% d'écart IQR supplémentaire coûte 0.5% sur le score final.

Un pilote à `-1.5%` de pace mais `regularity=0.020` aura :
`combined = -1.5% + 0.020 × 0.5 = -0.5%`

Vs un pilote à `-1.0%` de pace mais `regularity=0.007` :
`combined = -1.0% + 0.007 × 0.5 = -0.65%` → **meilleur score malgré moins de vitesse brute**

### 2.3 Tendance intra-relais (slope)

Régression linéaire sur les N derniers tours filtrés :

```python
slope_ms_per_lap = linregress(range(N), recent_laps_ms).slope
```

Exposer : `stint_trend = "IMPROVING" | "STABLE" | "DEGRADING"`

- `slope < -50 ms/tour` → IMPROVING (pilote qui monte en régime)
- `-50 < slope < +50` → STABLE
- `slope > +50 ms/tour` → DEGRADING (fatigue ou kart qui souffre)

Affiché dans la LiveTiming et dans la vue stats équipe.

---

## 3. Conditions de piste

### 3.1 Référence temporelle (non par nombre de tours)

Remplacer `_field_laps: deque(maxlen=200)` par une fenêtre temporelle :

```python
FIELD_WINDOW_SECONDS = 1800  # 30 minutes
_field_laps: list[tuple[timestamp_ms, lap_ms]]
ref_piste_T = median([l for t, l in _field_laps if now - t < FIELD_WINDOW_SECONDS × 1000])
```

La fenêtre de 30 min capture ~1800 tours (31 équipes × ~2 tours/min) — statistiquement très solide. Elle reflète les conditions actuelles sans mémoire des conditions de 3h avant.

### 3.2 Application universelle

**Toutes** les comparaisons doivent utiliser `ref_piste_T` :
- Team level
- Kart quality
- Driver combined_score
- Out-lap comparison

Un pilote n'est jamais lent "en absolu" — il est lent par rapport au champ dans les mêmes conditions.

---

## 4. Performance kart — comparaison simultanée

### 4.1 Le problème actuel

`kart_quality` compare le stint courant vs `field_avg` puis soustrait le skill attendu du pilote/équipe. Mais ce calcul est fait **équipe par équipe** sans vision globale.

### 4.2 Snapshot instantané multi-équipes

À chaque tour (ou toutes les 60s), calculer pour **toutes les équipes simultanément** :

```python
kart_raw[team] = delta_pct(team, ref_piste_T)        # médiane RECENT_WINDOW tours filtrés
skill_expected[team] = driver_combined_score ou team_hist_delta
kart_score[team] = kart_raw[team] - skill_expected[team]
```

Puis classer tous les `kart_score` en **quartiles en temps réel** :
- Top 25% → ROCKET
- 25-50% → FAST
- 50-75% → MEDIUM
- Bottom 25% → BAD

L'avantage : les labels sont relatifs au champ **du moment**, pas à des seuils fixes ±1.5%. Si tous les karts sont mauvais, le "meilleur des mauvais" est quand même ROCKET relativement.

### 4.3 Stabilité du classement kart

Le classement kart doit être **lissé** pour éviter les flip-flop toutes les 30s :

```python
kart_label[team] = weighted_vote(
    current_score = kart_score[team],       # poids 0.6
    previous_label_score = last_score[team], # poids 0.4
)
```

Changer de label uniquement si le score franchit le seuil de ±0.5% de manière persistante (2 tours consécutifs).

---

## 5. Pilotes inter-événements (DB)

### 5.1 Ce qui existe

`seed_from_previous_event()` charge les `stint_deltas` d'une équipe depuis un event précédent. Le pilote spécifique est perdu si son nom change légèrement ou si l'équipe change.

### 5.2 Améliorations

**Identification robuste du pilote** : normaliser les noms (strip, upper, strip accents) dans une table `drivers` dédiée, avec un `driver_key` stable.

**Profil pilote persistant** :
```sql
driver_profiles (
  driver_key TEXT,          -- normalized name
  event_id INT,
  avg_pace_pct FLOAT,       -- delta vs field moyen sur l'event
  regularity_score FLOAT,   -- IQR moyen sur l'event
  combined_score FLOAT,
  total_laps INT,
  total_stints INT
)
```

**Au démarrage d'un nouvel event** : charger le `combined_score` historique des pilotes connus → seed direct du `_skill_expected` sans attendre 15 tours.

**Ce que ça donne** : un pilote connu avec `combined_score = -1.2%` aura dès son premier tour une estimation de skill réaliste, améliorant immédiatement la précision du kart_quality.

---

## 6. Récapitulatif des métriques exposées

| Métrique | Calcul | Nouveauté |
|---|---|---|
| `ref_piste_T` | Médiane rolling 30 min champ | Remplace rolling 200 tours |
| `pace_score` | `delta_pct` vs `ref_piste_T` | Identique mais ref améliorée |
| `regularity_score` | IQR normalisé tours filtrés | **NOUVEAU** |
| `combined_score` | `pace + regularity × 0.5` | **NOUVEAU** |
| `stint_trend` | Slope régression linéaire | **NOUVEAU** |
| `outlier_count` | Nb tours exclus / relais | **NOUVEAU** |
| `kart_score` | `kart_raw - skill_expected` (multi-teams) | Amélioré |
| `kart_label` | Quartile temps réel + lissage | Amélioré |
| `out_lap_quality` | Out-lap vs ref + pit_duration | Amélioré |
| `driver_combined_score` | Cross-event depuis DB | Amélioré |

---

## 7. Ordre d'implémentation recommandé

1. **Filtrage outliers** (`OUTLIER_PCT=12%`) — fondation de tout le reste, 1 heure
2. **`regularity_score` IQR** — s'appuie sur les tours filtrés, 1-2h
3. **`combined_score`** — combine pace + regularity, 30 min
4. **`ref_piste_T` temporel** — remplace le rolling 200 tours, 1-2h
5. **Classement kart par quartile temps réel** — remplace seuils fixes, 2-3h
6. **`stint_trend` slope** — régression linéaire, 1h
7. **`driver_profiles` DB** — persistance cross-event, 3-4h

Total estimé : ~2 jours de dev pour les items 1-6, 1 jour supplémentaire pour le 7.
