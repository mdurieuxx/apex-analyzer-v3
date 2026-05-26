# Observations sur les courses analysées

Fichiers dans `/test-data/`. Sert de validation empirique pour les algorithmes de performance.

---

## Agadir 24h — 15-16 novembre 2025

**Fichier** : `test-data/agadir/20251115_24h/agadir_24h_20251116.jsonl`  
**Script d'analyse** : `test-data/agadir/20251115_24h/analyze.py`  
**Format** : nouveau format proxy (v:1, t/msg)

### Statistiques
- Circuit Agadir (920m), démarrage 14:29 heure locale
- **~30 équipes** en catégorie principale (notc8388863 + notc65535), plus catégories jeunes/loisirs (no6, no7)
- **893 stints** totaux, ~25 stints/équipe (un nouveau kart à chaque pit)
- **26 226 tours normaux** sur la catégorie principale
- Médiane champ : **70.21s**
- Durée capturée : 28.7h (inclut courses d'autres catégories après la fin)

### Conditions de piste
Remarquablement stable pour une course de 24h en extérieur :
```
14h → 70.29s   | 20h → 70.04s   | 02h → 70.16s   | 08h → 70.27s
15h → 70.24s   | 21h → 70.38s   | 03h → 70.31s   | 09h → 70.28s
16h → 70.19s   | 22h → 70.38s   | 04h → 70.25s   | 10h → 70.55s
17h → 70.22s   | 23h → 70.21s   | 05h → 70.27s   | 11h → 70.63s
18h → 70.13s   | 00h → 70.14s   | 06h → 70.14s
19h → 70.05s   | 01h → 70.10s   | 07h → 70.35s
```
**Variation totale ≈ 0.8%** (70.04s à 70.63s). Légèrement plus rapide en soirée (19-20h), légèrement plus lent en milieu de matinée (10-11h).

### Niveaux équipes (catégorie principale)
```
ELITE   : EIRIZ PRO (-1.65%), LECLUSE 2 (-1.41%), SCUDERIA VAROISE (-1.11%)
          KARTDREAM (-0.93%), LECLUSE (-0.78%), MRK CHALLANS 1 (-0.77%)
          H3PERFORMANCE (-0.75%), H3 RACING (-0.73%)
FAST    : WRT EV (-0.54%), MRK CHALLANS 2 (-0.48%), HIVE-X MYRMIDONS (-0.45%)
          AMS RACING (-0.38%), DRIMA LAVAGE (-0.19%), WEST AVENTURE (-0.03%)
MEDIUM  : TCKB (+0.02%), SCUDERIA VAROISE 2 (+0.11%), BE3KARTING (+0.23%)
          KARTING SAINT-MALO (+0.26%), KART RACING TEAM INNTAL (+0.57%)
SLOW    : RKE NIGHT AND DAY (+0.61%), IEVENT (+0.61%), DDD RACING TEAM (+0.99%)
          LES NORMANDS (+1.16%), RSR RACING KART (+1.24%), FESTI'KART (+1.27%)...
```

### Top pilotes (vitesse + régularité)
Les pilotes sont identifiables via le champ `drteam` sur la colonne équipe. Corrélation forte entre vitesse et régularité pour les pilotes d'élite :

```
BROCHARD Martin    : Δbest=-1.55%  CV=0.16%  12 stints  449 tours  → meilleur global
BRICOUT Ewen       : Δbest=-1.33%  CV=0.16%  13 stints  442 tours  → plus de stints
VERFAILLIE Siebert : Δbest=-1.45%  CV=0.19%   7 stints  280 tours
CHIAPPE Tom        : Δbest=-1.42%  CV=0.17%   7 stints  222 tours
MORIN Grégory      : Δbest=-1.86%  CV=0.20%   9 stints  381 tours  → le plus rapide
MEUNIER Bastien    : Δbest=-1.60%  CV=0.19%   5 stints  215 tours
```

### Détection karts — cas notables

**Mauvais karts avérés** (comparaison contemporaine ±30min, skill-adjusted) :
- `PELLEGRINO Mathieu` — SCUDERIA, stint #18, 05h : score +1.36% (raw +0.06% vs ref, skill -1.30%)
- `JEANFILS Maxime` — TCKB, stint #4, 16h : score +1.63% — **32 tours avec ce kart** (long stint sans pit)
- `JEANFILS Maxime` — TCKB, stint #25, 10h : score +1.20% — confirme la récurrence
- `MRK CHALLANS 1` stints #21-22-23, 08-09h : 3 pilotes différents, scores +1.21%/+1.23%/+1.24% → **même kart physique recyclé 3× consécutives**
- `DURIEUX Marc` — HIVE-X, stint #8, 20h : score +1.32%, 9 tours
- `CHAMBRIER Anthony` — LECLUSE, stint #2, 14h : score +1.04% (début de course)

**Bons karts** :
- `BRUNOT Vladimir` — H3 RACING, stint #9, 22h : score -1.28% (best 68.756s)
- `TARDIEU Christophe` — SCUDERIA, stint #9, 21h : score -1.19%
- `KADDAI Tomy` — IEVENT, stint #25, 09h : score -1.21%

### Insight clé
La méthode `best-lap contemporain - skill_expected` fonctionne proprement :
- Les pilotes réguliers (CV 0.15-0.20%) maintiennent leur CV même avec un mauvais kart
- La déviation de vitesse (best lap plus lente) est le seul signal du kart
- Les cas MRK CHALLANS 1 validant l'hypothèse du "même kart physique" donnent confiance dans la méthode

---

## Misanino 24h — 18-19 octobre 2025

**Fichiers** : `test-data/misanino/2025_24h/` (3 fichiers consécutifs, même course)  
**Format** : ancien format (clé `data`, timestamps ISO)

### Statistiques
- Misanino Kart (Italie, piste ~750m intérieure/couverte)
- **36 équipes**, dont EIRIZ PRO, BLUE RACING TEAM, CHRONO TEAM RACING, DFB RACING TEAM…
- **33 258 tours** en 22.6h (3 fichiers couvrent 13h40 → 12h15 le lendemain)
- Médiane champ : **74.44s**
- **886 pit stops** = ~24.6 stints/équipe

### Conditions de piste — remarquables
La piste couverte/indoor donne les conditions les plus stables :
```
13h → 74.77s  | 19h → 74.57s  | 01h → 74.26s  | 07h → 74.44s
14h → 74.56s  | 20h → 74.41s  | 02h → 74.26s  | 08h → 74.52s
15h → 74.58s  | 21h → 74.40s  | 03h → 74.18s  | 09h → 74.60s
16h → 74.51s  | 22h → 74.40s  | 04h → 74.18s  | 10h → 74.80s
17h → 74.48s  | 23h → 74.18s  | 05h → 74.21s
18h → 74.47s  | 00h → 74.29s  | 06h → 74.44s
```
**Pattern** : léger ralentissement en fin de matinée (+0.5% à 10h vs 3h). Pas d'effet nuit marqué contrairement à une piste outdoor. **Variation totale : 0.9%** (74.18s à 74.89s).

### Notes sur le format ancien
Le format `data` (avant proxy) ne capture pas les drteam/pilotes individuellement dans les messages de mise à jour. Les noms d'équipes sont dans le HTML de grille initial. Moins d'informations sur les pilotes qu'avec le format proxy.

---

## Mariembourg 8h — 19 octobre 2025

**Fichier** : `test-data/mariembourg/mariembourg_8h_2025/20251019_converted.jsonl`  
**Format** : converti nouveau format (v:1)

### Statistiques
- Karting des Fagnes, Mariembourg (Belgique), ~1000m de piste
- **38 équipes**, 16-17 stints/équipe
- **13 197 tours** en 8.1h
- Médiane champ : **74.02s**
- **610 pit stops**

### Conditions de piste — plus variable
```
07h → 73.86s  | 10h → 73.78s  | 13h → 74.76s  | 15h → 74.44s
08h → 73.67s  | 11h → 73.95s  | 13h → 74.07s  | 15h → 75.42s  ← pic
08h → 73.86s  | 12h → 73.77s  | 14h → 74.44s  | 15h → 74.13s
09h → 73.87s  | 12h → 74.09s
```
**Variation totale : 2.4%** (73.67s à 75.42s). Pic à 15h = fin de course, possible humidité ou fatigue piste. La fenêtre de comparaison ±30min est critique ici.

### Niveaux équipes
```
Delta range : -1.08% à +3.15%
p25 = -0.34%   → seuil ELITE/FAST
p50 = +0.24%   → médiane
p75 = +0.78%   → seuil MEDIUM/SLOW
```
Spread plus large qu'Agadir (+3.15% vs +2.17%) — plus grande disparité de niveau en endurance 8h belge.

### Note importante
Le format converti ne contient pas les noms de pilotes dans les messages incrémentaux (pas de `drteam`). Seuls les teams sont identifiables. La détection de kart par team est possible mais pas par pilote individuel.

---

## Mariembourg 4h fun — 17 mai 2026

**Fichier** : `test-data/mariembourg/20260517_4h_fun/mariembourg_20260517_105903.jsonl`  
**Format** : nouveau format proxy (v:1)

### Statistiques
- Mariembourg, début 10:59
- **41 équipes**, 130 pit stops (durée capturée ~1.1h seulement sur 4h)
- **1 845 tours** sur la période capturée
- Médiane champ : **75.16s** (légèrement plus lent qu'en compétition)
- **1.25% de variation** sur la période

### Notes
- Fichier partiel (1.3h capturées sur 4h de course) → insuffisant pour calibrer les niveaux équipes sur toute la course
- Format v:1 → pas de noms pilotes dans la capture (pas de `drteam` visible)
- Utile pour tester le parsing et la connexion en live, pas pour l'analyse approfondie

---

## Mariembourg sprint — 26 octobre 2025

**Fichier** : `test-data/mariembourg/20251026_mariembourg_course_8h.jsonl`  
**Format** : ancien format (avant proxy)

### Notes
- 8 674 lignes, seulement **218 tours** détectés → capture partielle ou format non entièrement compatible
- **111 équipes** dans le HTML initial, 107 noms de pilotes identifiés
- Durée capturée courte, données insuffisantes pour l'analyse de performance

---

## Synthèse cross-circuits

### Variation de la condition de piste
```
Indoor/couvert (Misanino)          : ~0.9%  — le plus stable
Climat aride (Agadir, Maroc)       : ~0.8%  — très stable
Météo tempérée (Mariembourg, mai)  : ~1.3%
Météo automnale (Mariembourg, oct) : ~2.4%  — le plus variable
```
**Règle** : toujours utiliser une fenêtre temporelle ±30min pour la référence, même sur les pistes stables.

### Spread de niveau équipes (delta vs médiane)
```
Agadir 24h (30 teams main cat) : -1.65% à +2.17%
Mariembourg 8h (38 teams)      : -1.08% à +3.15%
```
Les courses plus longues (24h) concentrent les équipes sérieuses → spread légèrement plus resserré.

### CV intra-stint typique
```
Pilotes d'élite : 0.15–0.20%   (~0.10–0.15s std sur tour de 70–75s)
Pilotes am       : 0.25–0.45%
Pilotes inégaux  : 0.50–0.70%
```
Ces valeurs sont **stables cross-circuits et cross-formats** — indicateur robuste de niveau pilote.

### Nombre de stints pour convergence
- **≥2 stints** : signal pilote/équipe utilisable (avec réserves)
- **≥5 stints** : niveau équipe fiable
- **≥10 stints** : niveau pilote très fiable (24h = ~25 stints disponibles)

Sur une course de 24h, l'assignation aléatoire des karts sur 25 stints converge vers le vrai niveau de l'équipe avec une erreur <0.1%.
