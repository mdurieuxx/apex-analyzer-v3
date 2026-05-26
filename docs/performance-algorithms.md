# Algorithmes de performance karting endurance

Validé sur 4 courses réelles (Agadir 24h, Misanino 24h, Mariembourg 8h, Mariembourg 4h).

---

## 1. Conditions de piste

### Problème
Les temps au tour varient naturellement au cours d'une course indépendamment de la qualité des karts :
- Température (jour/nuit, météo)
- Rubber progressif sur la piste
- Usure des pneumatiques selon humidité

Comparer un stint à la médiane globale de la course est faux si les conditions ont changé.

### Mesure de la variation observée

| Circuit | Format | Variation max | Cause principale |
|---------|--------|--------------|-----------------|
| Agadir (Maroc) | 24h | **0.5–0.6%** | Climat saharien, très stable |
| Misanino (Italie) | 24h | **0.9%** | Nuit légèrement plus rapide |
| Mariembourg (Belgique) | 8h | **2.4%** | Température variable, pluie possible |
| Mariembourg (Belgique) | 4h | **1.3%** | — |

Même 0.5% de variation peut inverser un signal kart si le seuil de détection est à 1%. La normalisation est **toujours nécessaire**.

### Algorithme

**En live** : fenêtre glissante des N derniers tours normaux du champ.
```
field_avg(t) = médiane des FIELD_WINDOW=200 derniers tours (tous teams)
```
- Utilisé pour normaliser `track_monitor.normalize(lap_ms)`
- Utilisé pour calibrer les niveaux équipes/pilotes (`_close_stint`)

**En analyse statique** : fenêtre temporelle centrée sur chaque stint.
```
ref_contemporain(stint) = médiane(best_laps des autres teams | |t_mid_other - t_mid_stint| < 1800s)
```
- Fenêtre ±30 min = ~1 500–2 000 tours de référence sur une course de 30 teams
- Minimum : 5 équipes contemporaines, sinon `UNKNOWN`

### Pattern nuit vs jour (Misanino 24h)
```
13h-18h : 74.5–74.8s  (début de course, piste froide)
22h-04h : 74.1–74.3s  (nuit, rubber maximal → piste plus rapide !)
08h-10h : 74.6–74.9s  (matin, température basse mais rubber usé)
```
→ La nuit est souvent plus rapide — **ne jamais comparer à la médiane globale**.

---

## 2. Performance équipe

### Vitesse

**Objectif** : mesurer à quel point une équipe est structurellement rapide ou lente, indépendamment des karts reçus. Sur une course de 24h avec ~25 stints, la distribution des karts est aléatoire → la moyenne des deltas converge vers le niveau réel de l'équipe.

```
field_avg = médiane glissante (FIELD_WINDOW=200 tours normaux, tous teams)
stint_delta = (stint_avg_laps - field_avg) / field_avg

team_weighted_delta = Σ(stint_delta_i × lap_count_i) / Σ(lap_count_i)
```

**Niveaux** (quartile sur tous les teams de la course) :
```
ELITE  : team_delta ≤ p25   → top 25% les plus rapides
FAST   : p25 < delta ≤ p50
MEDIUM : p50 < delta ≤ p75
SLOW   : delta > p75
```

**Données observées — Agadir 24h (main category, 30 teams) :**
```
ELITE  [≤-0.77%] : EIRIZ PRO (-1.65%), LECLUSE 2 (-1.41%), SCUDERIA VAROISE (-1.11%)...
FAST   [-0.77% à -0.19%] : WRT (-0.54%), MRK CHALLANS 2 (-0.48%), HIVE-X (-0.45%)...
MEDIUM [-0.19% à +0.27%] : WEST AVENTURE, TCKB, SCUDERIA VAROISE 2, BE3KARTING...
SLOW   [>+0.27%] : KART RACING TEAM INNTAL, RKE NIGHT AND DAY, DDD RACING TEAM...
```

**Mariembourg 8h (38 teams) :**
```
p25=-0.34%  p50=+0.24%  p75=+0.78%  range: -1.08% à +3.15%
```

### Régularité

**Objectif** : mesurer la consistance d'une équipe, utile pour prévoir son comportement futur et détecter les passages difficiles.

```
CV_stint = stdev(normal_laps_du_stint) / mean(normal_laps_du_stint)
team_regularity = médiane(CV_stint sur tous les stints valides)
```

**Valeurs typiques observées :**
```
Teams pro compétitifs  : CV 0.15–0.25%  → ~0.1–0.2s std sur tour de 70s
Teams am expérimentés  : CV 0.25–0.40%
Teams am occasionnels  : CV 0.40–0.70%
Teams inégaux          : CV > 0.70%
```

> **Note** : le CV est insensible aux conditions de piste (c'est une mesure relative intra-stint).

---

## 3. Performance pilote

### Vitesse

**Objectif** : isoler la contribution du pilote, indépendamment du kart reçu et des conditions du moment.

**En live** (via noms de pilotes dans `drteam`) :
```
driver_delta = médiane(stint_deltas du pilote sur ses stints nommés)
Fiable si : total_laps ≥ 15 ET stints_count ≥ 2
```

**En analyse statique** (meilleurs tours, base contemporaine) :
```
raw_score_stint = (best_lap_stint - ref_contemporain) / ref_contemporain
driver_best_delta = médiane(raw_score sur tous les stints du pilote)
Fiable si : stints_nommés ≥ 2
```

**Données observées — Agadir 24h (pilotes avec ≥3 stints, ≥15 tours) :**
```
Pilote               Δbest%    CV/stint  Stints
MORIN Grégory        -1.86%    0.20%      9
BROCHARD Martin      -1.55%    0.16%     12
MEUNIER Bastien      -1.60%    0.19%      5
VERFAILLIE Siebert   -1.45%    0.19%      7
CHIAPPE Tom          -1.42%    0.17%      7
BRICOUT Ewen         -1.33%    0.16%     13
...
DURIEUX Marc         -0.44%    0.27%      6
...
COLIN Paul           +1.34%    0.23%      7
JAOUAD Ziyad         +1.67%    0.42%      7
```

**Hiérarchie des sources pour le skill expected delta :**
1. `driver_best_delta` si fiable (≥15 tours, ≥2 stints nommés)
2. `team_best_delta` (médiane des raw scores de l'équipe sur ses stints) si ≥2 stints
3. Expected delta du niveau de l'équipe (midpoint du quartile)
4. `0.0` (pas d'ajustement)

### Régularité

**Objectif** : distinguer un pilote régulier et rapide d'un pilote rapide mais irrégulier.

```
CV_per_stint  = stdev(normal_laps) / mean(normal_laps)  [intra-stint]
regularity    = médiane(CV_per_stint sur tous les stints du pilote)
```

**Insight clé** : un bon pilote maintient un CV de 0.15–0.20% **quel que soit le kart reçu**. Un mauvais kart se voit dans la vitesse (best lap plus lente), pas dans la régularité.

```
Signal kart → déviation de VITESSE avec régularité maintenue
Signal pilote fatigué / erreurs → déviation de RÉGULARITÉ
```

**Top pilotes réguliers — Agadir 24h :**
```
DELFOSSE Tom      CV=0.15%  Δ=-1.02%  → rapide ET machine
BRICOUT Ewen      CV=0.16%  Δ=-1.33%  → rapide ET machine (13 stints, 442 tours)
BROCHARD Martin   CV=0.16%  Δ=-1.55%  → le plus rapide ET très régulier
HERMIER Carl      CV=0.16%  Δ=-0.93%  → idem
Nelson Desplat    CV=0.16%  Δ=-1.05%  → idem
CHIAPPE Tom       CV=0.17%  Δ=-1.42%  → top 5 vitesse + régularité
```

---

## 4. Performance kart

### Principe

Le kart physique est assigné **aléatoirement** à chaque pit stop — l'équipe ne choisit pas. Il est donc impossible de tracer un kart spécifique dans le temps. Le modèle est **stint-based** : on évalue la qualité du kart reçu pour chaque stint.

**Formule centrale :**
```
score = (best_lap_stint - ref_contemporain) / ref_contemporain - skill_expected_delta
```

- `best_lap_stint` : meilleur tour normal (passage ≥5 post-pit) du stint en cours
- `ref_contemporain` : médiane des best laps des autres teams qui roulaient au même moment (±30min)
- `skill_expected_delta` : delta attendu pour ce pilote/équipe (voir § 3)

### Pourquoi les meilleurs tours ?

Les tours moyens incluent trafic, erreurs, trajectoires expérimentales → bruit. Le **meilleur tour d'un stint** représente le **plafond de performance** du kart dans des conditions optimales. C'est le seul signal propre pour isoler le matériel.

Comparaison best laps vs average laps sur les données observées :
```
Spread inter-team (average laps) : ±2.5–4%   → seuils anciens : ROCKET -3.5%, BAD +2.5%
Spread inter-team (best laps)    : ±1.0–2%   → seuils recalibrés : ROCKET -1.5%, BAD +1.0%
```

### Séquence des tours post-pit

```
n=1  : tour partiel (sortie des stands → ligne de chronométrage)  → IGNORÉ
n=2  : out-lap (premier tour complet, pneus froids, prudent)       → comparé aux autres out-laps
n=3-4: tours de chauffe (montée en température)                    → EXCLUS
n≥5  : tours normaux → contribuent au scoring
```

**Out-lap comme signal précoce** : si n_normal < MIN_STINT_LAPS (4), utiliser l'out-lap comparé à la médiane des out-laps du champ comme signal d'alerte précoce (moins fiable).

### Thresholds (calibrés sur best laps)

```python
ROCKET_THRESHOLD = -0.015   # 1.5% meilleur qu'attendu → kart exceptionnel
FAST_THRESHOLD   = -0.005   # 0.5% meilleur → bon kart
BAD_THRESHOLD    = +0.010   # 1.0% plus lent → mauvais kart
```

### Niveau de confiance

```
n_normal = 0-3 : UNKNOWN (out-lap signal seulement, basse confiance)
n_normal = 4-7 : confiance modérée (~50-75%)
n_normal ≥ 8   : confiance élevée (≥100%)
confidence = min(n_normal / MIN_STINT_LAPS * 100, 100)
```

### Preuves empiriques — Agadir 24h

**Mauvais karts clairement identifiés :**
```
PELLEGRINO Mathieu (SCUDERIA, Δbest habituel -1.30%)
  Stint #18, 05h : best=70.315s vs ref=70.273s → raw=+0.06%, skill=-1.30% → score=+1.36%
  → son kart était dans la norme du champ alors qu'il est normalement 1.3% devant

JEANFILS Maxime (TCKB, Δbest habituel -0.62%)
  Stint #4, 16h : best=70.714s vs ref=70.007s → raw=+1.01%, skill=-0.62% → score=+1.63%
  → 32 TOURS avec ce kart sans pit → grosse perte de temps

MRK CHALLANS 1, stints #21-22-23 consécutifs (08-09h)
  3 pilotes différents : Mathieu Biteau (+1.21%), Nelson Desplat (+1.23%), S. Kermandi (+1.24%)
  → Même score, 3 pilotes différents → MÊME KART PHYSIQUE recyclé 3 fois de suite
```

**Bons karts identifiés :**
```
BRUNOT Vladimir (H3 RACING) Stint #9, 22h
  best=68.756s vs ref=70.001s → raw=-1.78%, skill=-0.50% → score=-1.28%
  → kart exceptionnel, 1.3% meilleur qu'attendu pour ce pilote

TARDIEU Christophe (SCUDERIA) Stint #9, 21h
  score=-1.19%  → bon kart en début de nuit
```

**Validation de la méthode — signal propre :**
- Un pilote avec mauvais kart maintient son CV habituel (0.15-0.20%) → régularité non impactée
- Seul le NIVEAU absolu des temps baisse → signal kart clairement isolé
- La méthode contemporaine absorbe les variations de conditions : les stints de nuit (plus rapides à Misanino) sont comparés à d'autres stints de nuit → pas de biais

---

## 5. Implémentation live vs analyse statique

| Aspect | Live (kart_ranker.py) | Analyse statique (analyze.py) |
|--------|----------------------|-------------------------------|
| Référence contemporaine | `_field_avg()` rolling 200 tours | médiane best laps ±30min |
| Skill delta | `weighted_historical_delta()` (avg laps) | `driver_best_delta` (best laps) |
| Normalisation | `track_monitor.normalize()` | fenêtre temporelle explicite |
| Out-lap | stocké séparément dans `_field_outlaps` | non utilisé (assez de stints) |
| Seuils | identiques : ROCKET -1.5%, BAD +1.0% | identiques |

**Différence clé** : en live, le skill delta est calibré en *average laps* (via `_close_stint`) mais appliqué à un score en *best laps*. L'approximation est acceptable car le ratio est proche de 1 pour des pilotes réguliers (CV faible → best ≈ avg - constante).

---

## 6. Données de référence par circuit

| Circuit | Longueur | Médiane typique | Variation piste | Teams/course |
|---------|----------|-----------------|-----------------|--------------|
| Agadir (Maroc) | 920m | ~70s | **0.5%** | 30 (endurance) |
| Misanino (Italie) | ~750m | ~74s | **0.9%** | 36 |
| Mariembourg (Belgique) | ~1000m | ~74s | **2.4%** | 38 |
| Mariembourg fun | ~1000m | ~75s | **1.3%** | 41 |

**Spread inter-pilotes typique (best-lap delta après skill adj) :**
- Kart exceptionnel : -1.2 à -1.5%
- Bon kart : -0.5 à -0.8%
- Kart neutre : -0.3 à +0.3%
- Mauvais kart : +0.8 à +1.5%
- Kart très mauvais : > +1.5%
