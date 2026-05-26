# Apex Timing WebSocket — Analyse exhaustive du protocole

Basé sur l'analyse empirique de 4 courses réelles :
- **Agadir 24h** (agadir_24h_20251116.jsonl, ws:8023, 185k msgs, 135 grids)
- **Mariembourg 8h** (mariembourg_8h_20251019.jsonl, ws:8313, 82k msgs, 2 grids)
- **Mariembourg 4h fun** (mariembourg_4h_fun_20260517.jsonl, ws:8313, 40k msgs, 15 grids)
- **Misanino 24h** (misanino_24h_20251018.jsonl, ws:8043, 226k msgs, 5 grids)

---

## 1. Structure générale du format proxy (fichiers .jsonl)

### Ligne 0 — header de fichier
```json
{"v": 1, "circuit_url": "https://...", "ws_port": 8313, "name": "session_name", "started_at": "2026-05-17T08:16:43.986993+00:00"}
```

### Lignes 1..N — messages WS
```json
{"t": 1.234, "msg": "ligne1\nligne2\nligne3"}
```
- `t` = secondes écoulées depuis `started_at`
- `msg` = contenu brut WS, plusieurs lignes séparées par `\n`
- Chaque ligne est un message indépendant au format pipe-delimited

---

## 2. Format général des messages pipe-delimited

```
SUBJECT|VERB|VALUE
SUBJECT|VERB|VALUE|EXTRA
```

- `SUBJECT` : identifiant de la cible (row, colonne, ou commande globale)
- `VERB` : type de mise à jour (CSS class, commande spéciale)
- `VALUE` : nouvelle valeur

### Deux familles de messages

| Type | SUBJECT format | Exemples |
|------|---------------|---------|
| **Row updates** | `rNNNN` ou `rNNNNcX` | `r19422`, `r19422c5` |
| **Global commands** | mot-clé | `init`, `title1`, `dyn1`, `css`, `grid`, `track` |

---

## 3. Messages globaux

### Session metadata (envoyés au démarrage et après init)
```
title1||24HEURES AGADIR 15 NOV 2025
title2||Finale
track||LEOPARD CIRCUIT VITERBO (1300m)
```

### Countdown (restant de course en **millisecondes**)
```
dyn1|countdown|74727615
```
- Valeur décroissante en ms (confirmé : delta ~30 000ms par 30s réelles)
- 74727615ms = 20.75h restantes

### CSS des catégories
```
css|no1|border-bottom-color:#FF8000 !important; color:#FFFFFF !important;
css|notc65535|border-bottom-color:#FFFF00 !important; color:#000000 !important;
```
Définit la couleur de chaque catégorie. À parser au démarrage pour le décodage des couleurs.

### Init (reset de la grille)
```
init|r|    ← race live / reset de course (grid actif, tours valides)
init|p|    ← session pausée / historique (ex: Chronos de la session précédente)
init|n|    ← vu à Mariembourg — sémantique similaire à init|r|
```
Toujours suivi d'un message `grid||<html>`. Déclenche la reconstruction du column map.

**Distinction `init|r|` vs `init|p|` :**
- `init|r|` (ex: Agadir 24h) → la course est live ou recommence ; les tours dans le grid sont valides
- `init|p|` (ex: Mariembourg 8h au démarrage) → snapshot d'une session terminée (Chronos) ; les tours affichés sont ceux de la session précédente → **les remettre à zéro**

**Démarrage de course dans la même connexion (sans nouveau `init|r|`)** :
Observé sur Mariembourg 8h : la connexion commence sur `init|p|` (Chronos), puis la course
démarre dans le même flux sans nouvelle commande `init`. Les signaux de départ sont :
```
light|lg|              ← feu vert
rNcM|in|0:00           ← reset de la colonne Tours (tlp) à 0:00 pour tous les drivers
rN|*||                 ← signal `*` vide pour chaque driver (départ, pas un temps au tour)
dyn1|countdown|NNN     ← countdown de course démarre
```

### Grid HTML
```
grid||<html>
```
Contient le tableau HTML complet de la grille. Peut arriver plusieurs fois dans une session
avec des **layouts de colonnes totalement différents** (voir § 5).

### Comments / Effects
```
comments||<html>
effects||Effets
com||<p>message de course...</p>
```

### Météo (Misanino)
```
wth1|ws|     ← météo slot 1
wth2||
wth3||
```

### Best / Light
```
best|hide|   ← cache la colonne meilleur temps
light|lg|    ← indicateur lumière (vert/rouge)
```

---

## 4. Messages row — format général

### Row ID
- Format `r\d+` : ex `r19422`, `r42118`, `r900006322`
- Row IDs longs (`r9000XXXXX`) : équipes normales avec IDs générés par le serveur
  - Ex : `r900006322` à Mariembourg = équipe normale avec beaucoup de mises à jour
- **Stable pendant toute la session**, mais différent d'une session à l'autre

### Messages sans suffixe colonne (`rN|VERB|VALUE`)
| VERB | Signification | Exemple |
|------|--------------|---------|
| `*` | Temps au tour (ms entier) | `r19422\|*\|70117` |
| `*i1` | Secteur 1 (ms) | `r12977\|*i1\|28291` |
| `*i2` | Secteur 2 (ms) | `r12977\|*i2\|23484` |
| `*in` | Pit in | `r39182\|*in\|0` |
| `*out` | Pit out | `r39182\|*out\|0` |
| `#` | Position (rank) | `r19422\|#\|3` |

> **Note** : `*` avec valeur vide (`rN|*||`) arrive parfois — ignorer (pas un temps valide).

### Messages avec suffixe colonne (`rNcX|VERB|VALUE`)
Le suffixe `cX` indique quelle colonne est mise à jour. La signification de cX dépend du
column map courant (voir § 5).

| VERB (CSS class) | Signification | Exemple valeur |
|-----------------|--------------|---------------|
| `dr` | Nom d'équipe (team name, stable) | `EIRIZ PRO`, `2 - GMTEAM` |
| `drteam` | Nom du **pilote actuel** + durée relais | `MORIN Grégory [0:35]` — change à chaque pit |
| `tn` | Dernier tour, couleur normale (blanc) | `1:10.322` |
| `ti` | Dernier tour, meilleur perso (vert) | `1:09.284` |
| `tb` | Meilleur tour session (violet) | `1:08.778` |
| `ib` | Écart/intervalle (display string) | `48.419`, `1:27.577` |
| `in` | Valeur générique neutre | gap, on-track, etc. |
| `to` | Chronomètre état courant : temps en piste si on track, temps au stand si en pit | `1:18.` (tronqué MM:SS.) |
| `notcXXXXX` | Kart number + catégorie notc | `32` (nouveau kart) |
| `noN` | Kart number + catégorie simple | `16` |

**Subs display-only (status column c1)** — aucune valeur utile :
`sr`, `su`, `sd`, `si`, `so`, `sf`, `ss`, `gs`, `gf`, `gl`, `gm` → ignorer.

**Position dupliquée** : La position est parfois envoyée dans deux formats simultanément :
```
r19305|#|25          ← sans colonne
r19305c2||25         ← avec colonne rk, sub vide
```
Les deux sont équivalents. Utiliser `#` sans colonne.

---

## 5. Grille HTML — Structure et column map

### RÈGLE FONDAMENTALE
> **Le numéro de colonne (c3, c4, c5...) n'est PAS stable entre les sessions, ni même entre
> les grid messages d'une même session.** Le même circuit peut avoir c4=kart dans un message
> et c4=team dans le suivant.

**Il faut TOUJOURS rebuilder le column map depuis le header row de chaque message grid.**

### Header row (r0)
```html
<tr data-id="r0" class="head">
  <td data-id="c1" data-type="sta"></td>
  <td data-id="c2" data-type="rk">Clt</td>
  <td data-id="c3" data-type="no">Kart</td>
  <td data-id="c4" data-type="dr" data-width="23">Equipe</td>
  <td data-id="c5" data-type="blp">Meilleur T.</td>
  ...
</tr>
```

Le `data-type` est le **seul identifiant fiable** de la colonne. Construire le map :
```python
col_map = {}  # col_id ("c3", "c4", ...) → data_type ("no", "dr", "blp", ...)
```

### Data-types rencontrés sur tous les circuits

| data-type | Signification | Présent sur |
|-----------|--------------|------------|
| `sta` | Statut (indicateur de position) | tous |
| `rk` | Rang/Position | tous |
| `no` | Kart number + catégorie | tous |
| `dr` | Nom équipe / pilote | tous |
| `llp` | Dernier tour (last lap) | tous |
| `blp` | Meilleur tour (best lap) | tous |
| `gap` | Écart au leader | tous |
| `int` | Intervalle au précédent | tous |
| `otr` | Temps en piste (on track) | tous |
| `pit` | Nombre de pit stops | tous |
| `grp` | Groupe/catégorie indicator | agadir, mariembourg_8h, misanino |
| `tlp` | Nombre de tours | agadir, mariembourg_8h, misanino |

| `nat` | Nationalité | agadir, misanino |
| `s1` | Secteur 1 | misanino |
| `s2` | Secteur 2 | misanino |
| `s3` | Secteur 3 | misanino |
| `''` (vide) | Colonne custom (catégorie, pénalité, etc.) | tous |

> **Pour un parser futur** : ne considérer que les data-types connus (`no`, `dr`, `llp`, `blp`,
> `gap`, `tlp`, `pit`, `s1`, `s2`, `s3`). Ignorer les colonnes avec data-type vide ou inconnu.

### Structure des data rows

```html
<tr data-id="rNNNN" data-pos="3">
  <!-- Status (sta): data-id présent, valeur vide ou class de statut -->
  <td data-id="rNNNNc1" class="sr"></td>

  <!-- Rank (rk): td SANS data-id, div interne sans data-id -->
  <td class="rk"><div><p data-id="rNNNNc2" class="">3</p></div></td>

  <!-- Kart/Category (no): td SANS data-id, div AVEC data-id et class catégorie -->
  <td class="no"><div data-id="rNNNNc3" class="notc255">21</div></td>
  <!--                    ^^^ data-id = row + col correspondant au header "no"
                              class = catégorie (notcXXXXX ou noN)
                              texte = numéro de kart (string) -->

  <!-- Team name (dr): td AVEC data-id, texte direct -->
  <td data-id="rNNNNc4" class="dr">G - TRIPLE A</td>
  <!--                  ^^^ class="dr" dans la data row correspond au data-type "dr" du header -->

  <!-- Best lap (blp): td AVEC data-id -->
  <td data-id="rNNNNc5" class="in">1:14.831</td>
  <!--                  ^^^ class peut être "in" même si data-type est "blp" en header -->

  <!-- Last lap (llp): classe CSS peut être tn/ti/tb selon le statut -->
  <td data-id="rNNNNc6" class="tn">1:15.545</td>
</tr>
```

### Comment extraire kart et catégorie du HTML

La colonne `no` est spéciale : le td **n'a PAS de data-id**. La valeur est dans le div interne.

**Méthode pour identifier la colonne no dans les data rows :**

Option A — via inner div data-id :
- Le div interne a `data-id="rNNNNcX"` où `cX` est la colonne no du header
- Ex: header dit c3=no → inner div a data-id="rNNNNc3"

Option B — via outer td class :
- Le td a class="no" (même que data-type)
- Texte du div interne = kart number
- Class du div interne = catégorie

**Algorithme recommandé pour la grille :**
```
pour chaque td dans data row:
    col_id = td.data-id (peut être vide pour td class="no" ou "rk")
    dtype  = col_map.get(col_id, None)  # depuis le header

    si td.class == "no" (ou dtype == "no"):
        → chercher div enfant
        → div.class = catégorie (notcXXXXX ou noN)
        → div.texte = kart_number

    si dtype == "dr":
        → td.texte = nom équipe (peut contenir "[M:SS]" → stripper)

    si dtype in ("llp", "blp"):
        → td.texte = lap time string (format "M:SS.mmm" ou "SS.mmm")
```

---

## 6. Parsing des mises à jour incrémentielles

### Logique de routing par sub (CSS class)

```
SUBJECT         | SUB          | ACTION
----------------|--------------|---------------------------------------
rN              | *            | Nouveau tour complet (val = ms entier string, peut être vide → ignorer)
rN              | *i1          | Secteur 1 (ms entier)
rN              | *i2          | Secteur 2 (ms entier)
rN              | *in          | Pit in (val = "0", ignorer val)
rN              | *out         | Pit out (val = "0", ignorer val)
rN              | #            | Nouvelle position (val = entier string)
rNcX            | dr           | Team name update (val = nom équipe brut)
rNcX            | drteam       | Driver name update (val = "NOM [M:SS]" → strip "[M:SS]")
rNcX            | notcXXXXX    | Kart change + catégorie notc (val = nouveau kart number)
rNcX            | noN          | Kart change + catégorie simple (val = nouveau kart number)
rNcX            | tn           | Dernier tour display update (format string "M:SS.mmm")
rNcX            | ti           | Dernier tour display, meilleur perso (format string)
rNcX            | tb           | Meilleur tour session update (format string)
rNcX            | ib           | Gap/interval display update (format string)
rNcX            | to           | Chronomètre état courant (en piste OU au stand selon l'état, format "MM:SS." tronqué, haute fréquence → redondant avec *in/*out)
rNcX            | in           | Valeur display générique (ignorer pour analyse)
rNcX            | *            | Position sub-variant (parfois = sub de position display)
rNc2            | (vide)       | Position update via colonne rk (val = entier) → doublon du #
```

### Extraction du row ID de base

Pour `rNcX|sub|val`, extraire le row base :
```python
base_rid = re.sub(r'c\d+$', '', row_id)  # "r42118c5" → "r42118"
```

Pour `rN|*|lap_ms`, le row_id est déjà le base (pas de suffixe colonne).

### Temps au tour (`*`)

```python
if sub == '*' and val.isdigit() and 30000 < int(val) < 300000:
    lap_ms = int(val)  # en millisecondes
```
- Plage valide observée : 60 000–200 000ms selon circuit
- Valeur vide possible → ignorer (ne pas crasher)
- `*i1`, `*i2` : secteurs en ms, même logique

### Driver name (drteam)

```python
if sub == 'drteam':
    # val = "MORIN Grégory [0:35]" ou "BRICOUT Ewen [1:09]"
    name = re.sub(r'\s*\[\d+:\d+\]$', '', val).strip()
    # name = "MORIN Grégory"
    # [M:SS] = durée du relais actuel (optionnel, ignorer pour le nom)
```

### Kart / Catégorie (notcXXXXX ou noN)

```python
if sub.startswith('notc') or (sub.startswith('no') and sub[2:].isdigit()):
    category = sub          # ex: "notc65535", "no1"
    kart_num  = val.strip() # ex: "32"
    # row_id contient le col_id = colonne "no" du header
```

---

## 7. Catégories

### Deux formats de catégorie

**Format `noN`** (Mariembourg, Misanino simple) :
- `no1`, `no2`, `no3`, ..., `no23`
- La couleur est définie par `css|no1|border-bottom-color:#FF8000 ...`
- Signification dépend du circuit (ex: no1=catégorie principale, no6=jeunes)

**Format `notcXXXXXX`** (Misanino, Agadir, Mariembourg avancé) :
- `notc8388863`, `notc65535`, `notc255`, `notc8454143`
- Encodage ARGB decimal → couleur CSS
- Décodage : `notc` + decimal → hex → `#RRGGBB`

```python
def decode_notc(cls: str) -> str:
    """notc8388863 → #7F00FF"""
    if not cls.startswith('notc'):
        return ''
    n = int(cls[4:]) & 0xFFFFFF  # ignorer l'alpha
    return f'#{n:06X}'
```

### Toujours présent sur deux éléments :
1. La class du `<div>` interne dans le td de type `no` (HTML initial)
2. Le sub du message incrémentiel `rNcX|notcXXX|kart_num`

---

## 8. Pit stops — détection fiable

```
rN|*in|0    ← équipe entre aux stands
... (temps dans les stands, pas de laps)
rN|*out|0   ← équipe quitte les stands
```

- `rN` = row ID **sans suffixe colonne** (toujours)
- `val` = toujours `"0"` (ignorer)
- La séquence `*in` → `*out` marque un pit stop complet
- Un nouveau `*` après `*out` = premier tour (out-lap) du nouveau stint

### Particularité : stint numero 1
Les équipes n'ont pas forcément de `*in` au début de la session.
Le premier `*` reçu pour une équipe démarre le stint 1 sans `*in` préalable.

---

## 9. Fréquence et structure des messages

### Messages haute fréquence (par tour, ~30–75s)
- `*` (lap time) : 1 par tour
- `tn`/`ti` (display last lap) : 1 par tour
- `#` / position : 1 par tour
- `drteam` : 1 par tour (relay timer [M:SS] mis à jour)
- `ib` (gap) : 1 par tour

### Messages haute fréquence (live timer, chaque ~1s)
- `to` (chronomètre état courant, en piste ou au stand) : très fréquent → redondant avec `*in`/`*out`, **ignorer dans l'analyse**

### Messages rares
- `*in` / `*out` : quelques centaines par course
- `notcXXX` / `noN` (kart change) : quelques centaines par course
- `dr` (team name refresh) : quelques milliers
- `tb` (session best) : dizaines par course
- `dyn1|countdown` : toutes les 30s

### Taille typique des msg fields
- La majorité des messages contiennent 1–5 lignes
- Les messages `grid||` peuvent contenir des dizaines de KB de HTML
- Les messages à `t=0` contiennent le dump initial complet (grid + css + metadata)

---

## 10. Scénarios complexes à gérer

### Changement de session dans la même connexion
- Nouveau `init|r|` reçu → le grid qui suit peut avoir un layout totalement différent
- **Rebuilder le col_map et réinitialiser l'état si init|r|**
- `init|p|` et `init|n|` : reset partiel dont la sémantique exacte n'est pas entièrement documentée
  - `init|p|` vu à Agadir et Misanino (partial reset ?)
  - `init|n|` vu à Mariembourg (new session ?)
  - **Traiter tous les init comme un reset et attendre le grid suivant**

### Changement de sémantique des colonnes en mode Course (Mariembourg)

**Observation critique** : à Mariembourg, le header `grid||` identifie les colonnes par `data-type`.
Ces types restent valides structurellement, mais le **contenu** change radicalement entre mode Chronos
et mode Course — sans qu'un nouveau grid soit envoyé.

| Colonne | data-type header | Contenu Chronos | Contenu Course (endurance) |
|---------|-----------------|-----------------|--------------------------|
| c6 | `llp` (Dernier T.) | Temps au tour `1:13.857` | Leader : `Tour N` · Voitures proches : gap `0.085` (secondes) · Voitures doublées : `N Tour(s)` |
| c8 | `gap` (Ecart) | Gap en secondes `0.799` | **Temps au tour** `1:13.090` |
| c9 | `tlp` (Tours) | Nombre de tours `13` | **Minutes écoulées** depuis le départ `0:07` |

**Conséquences pour le parser :**

1. **La colonne `tlp` (c9) en mode Course ≠ tours.** Les valeurs `0:01`, `0:07`… sont des minutes
   écoulées, pas des compteurs de tours. Seuls les signaux `*` sont la source fiable de tours.

2. **La colonne `llp` (c6) en mode Course = affichage de gap.** Elle contient :
   - `Tour N` pour le leader courant → correspond au numéro de tour actuel de la course (source Apex authoritative)
   - `N.NNN` (ex: `0.085`) pour les voitures proches → gap en secondes, **pas un temps au tour**
   - `N Tour(s)` pour les doublés → nombre de tours de retard

3. **Ne jamais parser les valeurs < 30 000ms comme des tours** depuis la colonne `llp` : les gaps
   en secondes (`0.085` → 85ms) seraient faussement interprétés comme des temps au tour.

4. **Extraction du tour depuis `Tour N`** : quand `llp` contient `Tour N`, le leader est au tour N.
   Cette valeur peut être utilisée pour synchroniser le compteur de tours.

### Plusieurs grid messages dans la même session
- 135 grids à Agadir (multiples sessions sur 28.7h capturées)
- 15 grids dans les 2 fichiers Mariembourg 4h
- Chaque `init|*|` + `grid||` peut changer le layout complet
- Toujours mettre à jour le col_map

### Teams sans nom (team name vide ou "1 -")
- Certains rows ont une team name = `"1 -"` ou vide dans le HTML initial
- Peut être complété plus tard par un message `dr`
- Row IDs très longs (`r9000XXXXX`) = teams normales, pas de cas spécial

### Kart changes en cours de course
- Reçu comme `rNcX|notcXXX|new_kart_num`
- La catégorie peut aussi changer (nouveau kart d'une autre catégorie)
- Le row ID reste le même (c'est l'équipe qui change de kart)

### Duplication de données positionnelles
- Position envoyée en 2 formats : `rN|#|pos` ET `rNc2||pos`
- Ne pas compter deux fois

---

## 11. Algorithme de parsing recommandé pour le live

```python
state = {
    'col_map': {},        # col_id → data_type (rebuilt à chaque grid)
    'teams': {},          # row_id → {kart, team, category, driver, laps, ...}
    'stints': {},         # row_id → current_stint
    'session': {},        # title1, title2, countdown, track
}

def process_message(msg: str, t: float):
    for line in msg.split('\n'):
        parts = line.split('|')
        if len(parts) < 2:
            continue
        subject, verb = parts[0], parts[1]
        val = parts[2] if len(parts) > 2 else ''

        # === Commandes globales ===
        if subject == 'init':
            # Prochain grid va rebuilder col_map
            state['pending_reset'] = True

        elif subject == 'grid':
            # Parser le HTML, rebuilder col_map depuis header row
            col_map = parse_grid_header(val)
            state['col_map'] = col_map
            parse_grid_data_rows(val, col_map)

        elif subject == 'title1':
            state['session']['title1'] = val

        elif subject == 'title2':
            state['session']['title2'] = val

        elif subject == 'track':
            state['session']['track'] = val

        elif subject == 'dyn1' and verb == 'countdown':
            state['session']['countdown_ms'] = int(val) if val.isdigit() else None

        elif subject == 'css':
            state['session']['css'][verb] = val  # verb = class name

        # === Row updates ===
        elif subject.startswith('r') and subject[1:2].isdigit():
            base_rid = re.sub(r'c\d+$', '', subject)

            if verb == '*':
                # Lap time
                if val.isdigit():
                    ms = int(val)
                    if 30000 < ms < 300000:
                        on_lap(base_rid, ms, t)

            elif verb in ('*i1', '*i2'):
                # Sector time
                if val.isdigit():
                    on_sector(base_rid, verb, int(val), t)

            elif verb == '*in':
                on_pit_in(base_rid, t)

            elif verb == '*out':
                on_pit_out(base_rid, t)

            elif verb == '#':
                if val.isdigit():
                    state['teams'][base_rid]['position'] = int(val)

            elif verb == 'dr':
                # Team name (pas drteam)
                if val.strip():
                    state['teams'][base_rid]['team'] = val.strip()

            elif verb == 'drteam':
                # Driver name avec relay time
                name = re.sub(r'\s*\[\d+:\d+\]$', '', val).strip()
                if name:
                    state['teams'][base_rid]['driver'] = name

            elif verb.startswith('notc') or (verb.startswith('no') and verb[2:].isdigit()):
                # Kart + category change
                state['teams'][base_rid]['category'] = verb
                if val.strip():
                    state['teams'][base_rid]['kart'] = val.strip()

            # Ignorer: to, in, ib, tn, ti, tb, sr, su, sd, si, so, sf, ss, gm, gl, gf, gs
```

---

## 12. Informations disponibles par circuit — récapitulatif

| Information | data-type (grid) | sub (incrémentiel) | Circuits |
|-------------|-----------------|-------------------|---------|
| **Kart number** | `no` (div interne) | `notcXXX` / `noN` | tous |
| **Catégorie** | `no` (class div) | `notcXXX` / `noN` | tous |
| **Nom équipe** | `dr` | `dr` | tous |
| **Nom pilote actuel** | — (pas dans grid initial) | `drteam` | quand tracking pilote actif |
| **Durée relais pilote** | — | `drteam` (suffix `[M:SS]`) | quand tracking pilote actif |
| **Dernier tour (display)** | `llp` | `tn` / `ti` / `tb` | tous |
| **Meilleur tour (display)** | `blp` | `tb` | tous |
| **Temps au tour (ms)** | — | `*` | tous |
| **Secteur 1 (ms)** | `s1` | `*i1` | misanino |
| **Secteur 2 (ms)** | `s2` | `*i2` | misanino |
| **Secteur 3 (ms)** | `s3` | — | misanino (display only) |
| **Écart leader** | `gap` | `ib` | tous |
| **Intervalle** | `int` | `ib` | tous |
| **Nombre de tours** | `tlp` | `*` (fiable) · `tlp` en Chronos seulement | agadir, mariembourg_8h, misanino |
| **Nombre de pits** | `pit` | — | tous |
| **Temps en piste** | `otr` | `to` | tous (display, ignorer) |
| **Position** | `rk` | `#` / `rNc2||` | tous |
| **Groupe** | `grp` | — | agadir, mariembourg_8h, misanino |
| **Nationalité** | `nat` | — | agadir, misanino |
| **Countdown** | — | `dyn1|countdown|ms` | tous |
| **Pit in/out** | — | `*in` / `*out` | tous |
| **Titre session** | — | `title1` / `title2` | tous |
| **Circuit (piste)** | — | `track` | misanino |

---

## 13. Points critiques pour un parser robuste

1. **Jamais de colonne fixe** : toujours parser le header row et builder le col_map avant tout.

2. **La colonne `no` est la seule sans data-id sur le td** : identifier via `class="no"` sur le td ou via `data-id` du div enfant.

3. **Le sub des updates ne correspond pas toujours au data-type** : `tn`, `ti`, `tb` pour `llp`/`blp`, `in` pour n'importe quelle valeur neutre.

4. **Les laps `*` arrivent toujours sans suffixe de colonne** (ex: `r42118|*|70117`).

5. **Les pit in/out `*in`/`*out` arrivent toujours sans suffixe de colonne**.

6. **Toujours filtrer les laps** : `val.isdigit()` ET dans la plage 30 000–300 000ms.
   Même contrainte pour les valeurs issues de la colonne `llp` en mode Course : les gaps en secondes
   (`"0.085"` → 85 ms) doivent être rejetés (< 30 000 ms = pas un temps au tour).

7. **Gérer les teams sans `*in` initial** : le premier `*` démarre un stint sans pit préalable.

8. **Gérer `init|*|` avant chaque grid** : plusieurs variants (`r`, `p`, `n`) → tous traitent pareil.

9. **drteam peut arriver sur n'importe quel circuit** mais pas toujours (dépend de la config du circuit).

10. **Les row IDs très longs (r900006XXX)** sont des équipes normales.

11. **`rNc2||val`** = doublon de position via colonne rk, sub vide → ignorer ou déduplication.

12. **Secteurs `*i1`/`*i2`** uniquement à Misanino — prévoir l'extensibilité.

13. **Ne jamais envoyer de message après connexion** — même un ping = déconnexion serveur.

---

## 14. Fréquences observées (volumes)

| Event | Agadir 24h | Mariembourg 8h | Misanino 24h |
|-------|-----------|----------------|-------------|
| Total messages | 185 464 | 82 253 | 226 369 |
| Laps (`*`) | 29 920 | 13 197 | 33 258 |
| drteam updates | 87 840 | 0 | 103 372 |
| dr updates | 74 491 | 0 | 88 026 |
| on-track `to` | 137 166 | 86 568 | 164 354 |
| Pit in | 772 | 610 | 886 |
| Pit out | 751 | 573 | 881 |
| Grid messages | 135 | 2 | 5 |

> `to` représente ~60% du volume total → toujours ignorer pour l'analyse.
> `drteam` absent à Mariembourg 8h dans cet échantillon → ne pas supposer sa présence.
