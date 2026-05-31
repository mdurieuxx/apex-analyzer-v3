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

**Réalité du karting moderne : les pilotes poussent à fond en permanence.**

En compétition aujourd'hui, les chronos sont quasi-qualificatifs tout au long de la course. La conséquence directe sur le modèle :

- **La variance de pace entre pilotes est compressée** — tout le monde est rapide, les écarts de temps pur sont faibles (quelques dixièmes)
- **La régularité devient le vrai différenciateur** : qui peut maintenir ce rythme qualif pendant 40 minutes sans faille ?
- Un pilote qui fait 1:00.2 / 1:00.1 / 1:00.3 pendant 40 tours EST meilleur qu'un pilote qui fait 0:59.8 / 1:01.5 / 1:00.0 / 1:02.0 — même si le second a un meilleur best lap

**Conséquence sur les poids :**

La vitesse reste le **plancher d'entrée** (sans pace compétitive, la régularité ne sert à rien). Mais puisque tout le monde pousse au même niveau, la régularité **pèse au moins autant que la vitesse** en endurance.

| Format | `WEIGHT_PACE` | `WEIGHT_REG` | Raisonnement |
|---|---|---|---|
| Endurance 6h+ | **30%** | **70%** | Pace compressée en karting moderne → régularité sur 1000+ tours = facteur décisif |
| Sprint / 1h | **50%** | **50%** | Équilibre — moins de tours mais la régularité reste clé |
| Qualification | **95%** | **5%** | Un seul tour, la régularité est anecdotique |

Note importante : le `pace_rank` doit toujours être calculé et affiché **séparément**. Un pilote à `pace_rank=30` (lent) avec `regularity_rank=95` ne doit pas être classé haut — la régularité ne compense jamais un pace non-compétitif. On peut envisager un **seuil minimum de pace** (`pace_rank >= 30`) en-dessous duquel le combined_rank est plafonné, quelle que soit la régularité.

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

## 5. Performance kart

### 5.1 Ce qu'on peut mesurer et ce qu'on ne peut pas

**Contrainte fondamentale** : on ne connaît pas l'identité physique du kart. Le numéro de kart affiché en timing est le numéro de dossard de l'équipe, pas le kart physique. On ne peut donc **jamais** comparer deux karts différents directement.

Ce qu'on peut mesurer :

| Situation | Ce qui change | Ce qui est constant | Mesure possible |
|---|---|---|---|
| Milieu de stint | — | Pilote + kart + conditions | Pace + régularité du duo pilote/kart |
| Pit court, **même pilote** ressort | Kart | Pilote + conditions (≈) | **Delta kart pur** ← cas idéal |
| Pit normal, **changement de pilote** | Pilote + kart | Conditions (≈) | Delta combiné pilote+kart — inséparable |
| Comparaison entre équipes | Tout | Conditions de piste | Relatif au champ via `ref_piste_T` |

### 5.2 Le cas en or : même pilote, kart changé au pit

Quand un pilote rentre et ressort sur un **kart différent** (fréquent en karting endurance — rotation de parc), on a une expérience contrôlée naturelle :

```
stint N   : pilote P, kart A → pace_P_A, regularity_P_A
pit stop
stint N+1 : pilote P, kart B → pace_P_B, regularity_P_B

kart_delta(A→B) = pace_P_B - pace_P_A   (normalisé vs ref_piste_T des deux périodes)
```

C'est la **seule mesure directe de la valeur d'un kart** disponible. Elle contrôle :
- Le pilote (identique)
- Les conditions (quasi identiques — quelques minutes d'écart)

Elle ne contrôle pas :
- L'usure des pneus au début du stint N+1 (out-lap froide) → exclure les 2-3 premiers tours
- La confiance du pilote sur le nouveau kart (stint N+1 tour 4+ est fiable)

**Condition de détection** : même `driver_id` sur le stint sortant et le stint entrant (données API `.P` + `.INF`).

### 5.3 Estimation kart par soustraction du skill connu — hiérarchie de confiance

Le pit swap same-driver est le cas idéal, mais on peut estimer la contribution du kart dès qu'on a une référence fiable du pilote ou de l'équipe. C'est une **hiérarchie de confiance** :

```
kart_contribution = duo_score - driver_expected_pace
```

| Niveau | Source du `driver_expected_pace` | Confiance | Quand disponible |
|---|---|---|---|
| **A — Gold** | Même pilote, stint précédent dans cette course, même kart → pit swap kart connu | 95% | Pit swap avec changement de kart identifié |
| **B — Silver** | Même pilote, stints précédents dans cette course (kart inconnu) | 75% | Dès le 2e relais du pilote |
| **C — Bronze** | Profil pilote cross-event depuis la DB | 60% | Si le pilote a couru des events précédents |
| **D — Faible** | Historique de l'équipe (tous pilotes confondus) dans cette course | 40% | Après 2-3 stints équipe |
| **E — Estimé** | Catégorie / niveau quartile sans historique individuel | 20% | Toujours disponible en fallback |

Plus le niveau est élevé, plus le badge kart affiché est fiable. Le `confidence` score affiché en LiveTiming reflète directement ce niveau.

**En pratique sur une 24H** : dès l'heure 2-3, la plupart des pilotes ont un relais complet dans la course (niveau B). Les pilotes récurrents ont un profil DB (niveau C). À partir de l'heure 6, les estimations kart sont fiables pour la grande majorité des équipes.

### 5.4 Le signal kart via écart au profil DB

C'est le raisonnement le plus puissant disponible dès la première lap si le pilote est connu en DB :

```
kart_signal = pace_actuel - pace_historique_DB
```

- **Pilote ELITE en DB qui tourne MEDIUM aujourd'hui** → kart sous-performant. Le pilote est connu pour être rapide, si il est lent c'est le kart.
- **Pilote SLOW en DB qui tourne FAST aujourd'hui** → kart surperformant. Le pilote est connu pour être lent, s'il est rapide c'est le kart qui l'aide.
- **Pilote FAST en DB qui tourne FAST aujourd'hui** → neutre, cohérent avec son niveau.

Ce signal est disponible **dès le premier tour** si le pilote est en DB — sans attendre des relais ou un pit swap. C'est la raison principale de persister les profils pilotes cross-event.

```python
kart_score_db = current_pace_rank - driver_db_pace_rank
# positif = kart meilleur que ce qu'on attendait du pilote
# négatif = kart moins bon que ce qu'on attendait
```

La confiance de ce signal = confiance du profil DB (nombre d'events, nombre de stints). Un pilote avec 5 events en DB donne un signal quasi-certain. Un pilote avec 1 event donne un signal indicatif.

### 5.4 Snapshot instantané multi-équipes

À chaque tour, calculer `kart_contribution` pour toutes les équipes simultanément, puis classer en **quartiles temps réel** :

```python
kart_score[team] = duo_score[team] - driver_expected_pace[team]

# Quartiles sur l'ensemble des kart_scores du champ
top_25    → ROCKET
25–50%    → FAST
50–75%    → MEDIUM
bottom_25 → BAD
```

Labels relatifs au champ du moment — pas de seuils absolus fixes.

### 5.5 Stabilité du label kart

Lissage pour éviter les flip-flop :

```python
# Changer de label uniquement si le score sort du quartile
# de manière persistante (2 tours consécutifs minimum)
kart_label[team] = new_label if stable_for >= 2 else previous_label
```

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
| Endurance 6h+ | 30% | 70% |
| Sprint / 1h | 50% | 50% |
| Qualification | 95% | 5% |

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
