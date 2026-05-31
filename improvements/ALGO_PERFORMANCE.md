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

## 2. Vitesse et régularité — deux dimensions indépendantes

### 2.0 Pourquoi ne pas les fusionner dans un seul score

Un `combined_score = pace × 0.6 + regularity × 0.4` est pratique mais **détruit de l'information** :

| Pilote | Pace | Régularité | Combined 60/40 |
|---|---|---|---|
| A | très rapide | irrégulier | bon |
| B | rapide | régulier | bon |
| C | moyen | très régulier | bon |

Les trois sont "bons" mais pour des raisons totalement différentes. En endurance, B et C sont souvent préférables à A. En qualification ou sprint, A est le meilleur. **Le contexte décide du poids** — pas l'algorithme.

**Proposition** : garder `pace_rank` et `regularity_rank` comme deux scores indépendants, normalisés de 0 à 100 chacun, et laisser l'utilisateur (ou la config de l'event) définir `WEIGHT_PACE` et `WEIGHT_REG` dont la somme = 100%.

```
combined_rank = WEIGHT_PACE × pace_rank + WEIGHT_REG × regularity_rank
```

Valeurs suggérées par défaut selon le format :
- **Course endurance (6h+)** : `WEIGHT_PACE=40, WEIGHT_REG=60`
- **Sprint / 1h** : `WEIGHT_PACE=65, WEIGHT_REG=35`
- **Qualification** : `WEIGHT_PACE=90, WEIGHT_REG=10`

Ces valeurs sont configurables dans `ConfigSchema` par event, pas des constantes.

### 2.1 Normalisation — même échelle pour comparer

Les deux métriques brutes ne sont pas sur la même échelle :
- `pace_score` : typiquement `-3%` à `+5%` (négatif = rapide)
- `regularity_score` (IQR normalisé) : typiquement `0.5%` à `3%` (bas = régulier)

Pour les rendre comparables, convertir chacun en **rang percentile dans le champ** :

```python
# pace_rank : 100 = le plus rapide du champ, 0 = le plus lent
pace_rank = (1 - percentile_rank(pace_score, all_pace_scores)) × 100

# regularity_rank : 100 = le plus régulier, 0 = le plus irrégulier
regularity_rank = (1 - percentile_rank(reg_score, all_reg_scores)) × 100
```

Avantage : les scores sont toujours relatifs au champ présent, pas à des seuils absolus. Si tous les pilotes sont irréguliers, le "moins irrégulier" est quand même à 100 en régularité — ce qui est correct pour la stratégie.

### 2.2 Les 4 profils pilote

La vraie valeur est dans la lecture 2D, pas dans le score combiné seul :

```
régularité
  100 │ SAFE FINISHER │ COMPLET    │
      │ (lent/régul.) │ (rapide+)  │
   50 ├───────────────┼────────────┤
      │ IMPRÉVISIBLE  │ NERVEUX    │
    0 │ (lent/irég.)  │ (rapide/-) │
      └───────────────┴────────────┘
      0               50          100  vitesse
```

- **COMPLET** (pace > 60, reg > 60) : idéal, à mettre aux heures de pointe
- **NERVEUX** (pace > 60, reg < 40) : rapide mais coûte des tours perdus + usure kart
- **SAFE FINISHER** (pace < 40, reg > 60) : idéal pour les heures creuses et la nuit
- **IMPRÉVISIBLE** (pace < 40, reg < 40) : à éviter en relais long

Le badge affiché en LiveTiming montre les deux dimensions séparément + le profil.

---

## 3. Régularité — calcul détaillé

### 3.1 Score de régularité pilote

Sur les tours filtrés (hors outliers, hors out-lap, hors warm-up) du relais courant :

```python
# IQR normalisé — robuste aux outliers résiduels
q75, q25 = percentile(laps_filtered, [75, 25])
regularity_score = (q75 - q25) / median(laps_filtered)
```

Ce score est ensuite converti en `regularity_rank` (0→100) par rang percentile dans le champ (§2.1).

Valeurs observées sur Brignoles (estimation) :
- Pilote excellent : `regularity_score < 0.008` (< 0.8% d'écart IQR)
- Pilote correct : `0.008 – 0.015`
- Pilote irrégulier : `> 0.020`

### 3.2 Tendance intra-relais (slope)

Information complémentaire à la régularité — pas un sous-score, mais un indicateur directionnel :

```python
slope_ms_per_lap = linregress(range(N), recent_laps_ms).slope
```

- `slope < -50 ms/tour` → `IMPROVING` (pilote qui monte en régime)
- `-50 < slope < +50` → `STABLE`
- `slope > +50 ms/tour` → `DEGRADING` (fatigue ou kart qui souffre)

Un pilote `DEGRADING` avec haute régularité est différent d'un pilote `DEGRADING` avec faible régularité — le premier se fatigue de manière ordonnée, le second part dans tous les sens.

---

## 4. Conditions de piste

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

## 5. Performance kart — comparaison simultanée

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

## 6. Pilotes inter-événements (DB)

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

## 7. Récapitulatif des métriques exposées

**Pilote — 2 dimensions indépendantes + score combiné configurable**

| Métrique | Calcul | Nouveauté |
|---|---|---|
| `pace_score` | `delta_pct` vs `ref_piste_T` | Ref améliorée (temporelle) |
| `pace_rank` | Rang percentile dans le champ (0→100) | **NOUVEAU** |
| `regularity_score` | IQR normalisé sur tours filtrés | **NOUVEAU** |
| `regularity_rank` | Rang percentile dans le champ (0→100) | **NOUVEAU** |
| `driver_profile` | `COMPLET / NERVEUX / SAFE FINISHER / IMPRÉVISIBLE` | **NOUVEAU** |
| `combined_rank` | `WEIGHT_PACE × pace_rank + WEIGHT_REG × regularity_rank` | **NOUVEAU** |
| `stint_trend` | Slope régression linéaire `IMPROVING/STABLE/DEGRADING` | **NOUVEAU** |
| `outlier_count` | Nb tours exclus / relais | **NOUVEAU** |

**Config pondération (par event)**

| Format | `WEIGHT_PACE` | `WEIGHT_REG` |
|---|---|---|
| Endurance 6h+ | 40% | 60% |
| Sprint / 1h | 65% | 35% |
| Qualification | 90% | 10% |

**Conditions & kart**

| Métrique | Calcul | Nouveauté |
|---|---|---|
| `ref_piste_T` | Médiane rolling 30 min champ | Remplace rolling 200 tours |
| `kart_score` | `kart_raw - skill_expected` (snapshot multi-teams) | Amélioré |
| `kart_label` | Quartile temps réel + lissage 2 tours | Amélioré |
| `out_lap_quality` | Out-lap vs ref + normalisation `pit_duration` | Amélioré |
| `driver_combined_score` | Cross-event depuis DB `driver_profiles` | Amélioré |

---

## 8. Ordre d'implémentation recommandé

1. **Filtrage outliers** (`OUTLIER_PCT=12%`) — fondation de tout le reste, ~1h
2. **`regularity_score` IQR + `regularity_rank`** — s'appuie sur tours filtrés, ~2h
3. **`pace_rank`** — percentile dans le champ, ~30 min
4. **`driver_profile` 2D** (COMPLET/NERVEUX/SAFE FINISHER/IMPRÉVISIBLE) — ~1h
5. **`WEIGHT_PACE / WEIGHT_REG`** configurables dans `ConfigSchema` — ~1h
6. **`ref_piste_T` temporel** — remplace rolling 200 tours, ~2h
7. **Classement kart par quartile temps réel** — remplace seuils fixes, ~2h
8. **`stint_trend` slope** — régression linéaire, ~1h
9. **`driver_profiles` DB** — persistance cross-event, ~4h

Total estimé : ~2 jours (items 1-8), +1 jour pour le 9.
