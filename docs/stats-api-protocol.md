# Apex Timing — Protocole complet : API Statistics + Commentaires WS

Complément à `ws-protocol-analysis.md` qui documente le flux WebSocket temps réel.  
Ce document couvre :
1. L'API HTTP `request.php` (statistics, pilotes, historique tours/pits)
2. Le protocole WS pour les commentaires de course
3. La table de correspondance WS ↔ API (quelle source pour quoi)

Observé sur : Brignoles Karting Loisirs — LES 24H DE BRIGNOLES 2026 (port 8600).

---

## 1. Vue d'ensemble — WS vs API

| Information | WebSocket (temps réel) | API request.php (historique) |
|-------------|----------------------|------------------------------|
| Classement / positions | `rN\|#\|pos` | — |
| Temps au tour live | `rN\|*\|ms` | `D#-N#D{id}.L` (tous les tours) |
| Pit in / pit out live | `rN\|*in\|0` / `rN\|*out\|0` | `D#-999#D{id}.P#1#D{id}.INF` |
| Nom équipe | `rNcX\|dr\|nom` | `.INF` XML |
| **Pilote actuel** | `rNcX\|drteam\|NOM [M:SS]` | `.INF` `current="1"` |
| **Liste pilotes de l'équipe** | absent du flux WS | `.INF` XML uniquement |
| **Historique complet pits** | absent du flux WS | `.P` (API uniquement) |
| **Historique complet tours** | absent du flux WS | `.L` (API uniquement) |
| Commentaires / pénalités | `com\|\|<p>...</p>` (voir §4) | — |
| Tour total de l'équipe | `rNcX` colonne `tlp` (unreliable en course, voir §10 ws-protocol-analysis.md) | `D#-1#D{id}.L` (fiable) |
| Meilleur tour équipe | `rNcX` colonne `blp` | champ `best_lap_ms` de `.L` |
| Countdown | `dyn1\|countdown\|ms` | — |

**Règle générale** : le WS sert le temps réel (chaque tour, chaque pit à la seconde).
L'API sert à reconstituer l'historique complet après coup ou à l'initialisation.

---

## 2. API request.php — Endpoint

```
POST https://live-data.apex-timing.com/live-timing/commonv2/functions/request.php
Content-Type: application/x-www-form-urlencoded

port={configPort}&request={query}
```

- `configHost` : `live-data.apex-timing.com` (commun à tous les circuits Apex)
- `configPort` : varie par circuit — récupérable depuis :
  - `config.js` du circuit : variable `configPort`
  - Ligne 0 du fichier JSONL proxy : `{"v":1,"ws_port":8313,...}` → même valeur
  - Circuits connus : Brignoles=8600, Mariembourg=8313, Agadir=8023, Misanino=8043

### TeamId — mapping depuis le WS

Le **row ID WS** = le **teamId API**. Aucun mapping supplémentaire.

```
WS grid HTML :  <tr data-id="r44387" ...>
                              ↓
API teamId  :   44387   (strip le préfixe "r")
```

```python
team_id = row_id.lstrip('r')   # "r44387" → "44387"
```

Applicable à tous les row IDs WS, y compris les longs (`r900006322` → `900006322`).

---

## 3. API — Requêtes disponibles

### 3.1 Pilotes + Historique pit stops

**Request :**
```
request=D#-999#D{teamId}.P#1#D{teamId}.INF
```

**Response** — une ligne par pit stop en ordre **décroissant** (plus récent en premier), terminée par une ligne `.INF` :

```
D44387.P28#28|1180|75550412|75671959|121547|187831|3|44423|22525090
D44387.P27#27|1177|75240693|75362581|121888|3073663|50|44424|26432628
...
D44387.P01#1|58|3537104|3658781|121677|3537104|58|44423|3537104
D44387.INF#<driver id="44387" ... name="STF BY KARTCUP" color="#FFFF00">...</driver>
```

#### Format ligne pit stop

```
D{teamId}.P{N}#{N}|{lap}|{in_ms}|{out_ms}|{pit_ms}|{track_ms}|{relay_laps}|{driver_id}|{driver_total_ms}
```

| Champ | Exemple | Signification |
|-------|---------|---------------|
| `N` | `28` | Numéro du pit stop (1 = premier de la course) |
| `lap` | `1180` | Tour auquel le kart est rentré aux stands |
| `in_ms` | `75550412` | Race time pit-in (ms depuis le départ) |
| `out_ms` | `75671959` | Race time pit-out (ms depuis le départ) |
| `pit_ms` | `121547` | Durée immobilisation stands (ms) |
| `track_ms` | `187831` | Durée du stint sur piste **se terminant** à ce pit (ms) |
| `relay_laps` | `3` | Nombre de tours effectués dans ce stint |
| `driver_id` | `44423` | ID interne du pilote ayant conduit ce stint |
| `driver_total_ms` | `22525090` | Temps cumulé total de ce pilote après ce stint (ms) |

> `driver_total_ms` du pit le plus récent d'un pilote = son temps total affiché dans le popup.  
> Vérification : 22 525 090 ms = 6:15:25 pour REMI LOTH ✓

#### Format ligne `.INF` (XML pilotes)

```xml
D44387.INF#<driver id="44387" member="0" center="145" num="3" name="STF BY KARTCUP" nat="" color="#FFFF00">
  <driver id="44423" member="0" num="1" name="REMI LOTH"      nat="" color="#000000" current="1"/>
  <driver id="44424" member="0" num="2" name="MARVIN KLEIN"   nat="" color="#000000"/>
  <driver id="44425" member="0" num="3" name="KILIAN SANCHEZ" nat="" color="#000000"/>
</driver>
```

| Attribut (tag racine) | Signification |
|-----------------------|---------------|
| `id` | teamId (= row_id WS sans "r") |
| `num` | Numéro de kart |
| `name` | Nom d'équipe |
| `color` | Couleur kart (#RRGGBB) — même que `notc` / `noN` dans le WS |
| `center` | ID du circuit/center Apex |

| Attribut (tag pilote enfant) | Signification |
|------------------------------|---------------|
| `id` | driver_id (clé de jointure avec les pit stops) |
| `num` | Numéro d'ordre du pilote dans l'équipe (1, 2, 3...) |
| `name` | Nom complet du pilote |
| `color` | Couleur casque dans l'UI |
| `current="1"` | Pilote actuellement sur piste (attribut absent = false) |

> **Lien WS** : le nom du pilote actuel arrive aussi via `rNcX|drteam|NOM [M:SS]` dans le flux WS.
> L'API `.INF` est la seule source pour la **liste complète** des pilotes d'une équipe.

---

### 3.2 Compteur de tours + meilleur tour (poll live)

**Request :**
```
request=D#-1#D{teamId}.L
```

**Response :**
```
D44387.L1216#|||61644
```

Format : `D{teamId}.L{totalLaps}#|||{best_lap_ms}`

| Champ | Exemple | Signification |
|-------|---------|---------------|
| `totalLaps` | `1216` | Total tours de l'équipe à l'instant t |
| `best_lap_ms` | `61644` | Meilleur tour en ms (61644ms = 1:01.644 ✓) |

Usage : récupérer `totalLaps` avant de demander tout l'historique (§3.3).

---

### 3.3 Historique complet des tours (laps)

**Request — tout récupérer en un appel :**
```
request=D#-{totalLaps+buffer}#D{teamId}.L
```

Le `-N` signifie « les N derniers tours ». Utiliser `totalLaps + 50` comme buffer contre les tours
arrivés entre les deux appels.

```python
# Étape 1 : récupérer le total
r = api_request(port, f"D#-1#D{team_id}.L")
total = int(re.search(r'\.L(\d+)#', r).group(1))

# Étape 2 : tout d'un coup
r = api_request(port, f"D#-{total + 50}#D{team_id}.L")
# Testé : D#-1300#D44387.L → 1226 tours (tours 6–1226), 27 008 octets ✓
```

**Pagination UI (équivalent du "+ Show More") :**
```
D#-30#D{teamId}.L    ← 30 premiers (chargement initial)
D#-60#D{teamId}.L    ← 60 (1er Show More)
D#-90#D{teamId}.L    ← 90 (2ème Show More)
```
→ Incrément de 30 à chaque clic. Pour l'application, utiliser directement le grand N.

**Response :**
```
D44387.L1224#|||62019
D44387.L1223#|||61460
D44387.L1222#|||61641
...
D44387.L6#|||61234
```

Format : `D{teamId}.L{lapN}#|||{lap_time_ms}`

| Champ | Signification |
|-------|---------------|
| `lapN` | Numéro du tour |
| `lap_time_ms` | Temps au tour en ms (62019ms = 1:02.019 ✓) |

> Les tours de stand (in-lap et out-lap) sont inclus avec leur temps réel.
> Pour les identifier : le tour d'entrée pit = `pits[N].lap`, le tour de sortie = `pits[N].lap + 1`.

---

## 4. Protocole WS — Commentaires de course

Les commentaires de la colonne droite ("Commentaires") arrivent exclusivement via le WebSocket.

### 4.1 Message initial (chargement)

```
comments||<p>...</p><p>...</p>...
```

Envoyé une fois en début de connexion (ou après `init|*|`). Contient tous les commentaires existants sous forme de bloc HTML.

### 4.2 Nouveaux commentaires (live)

```
com||<p><b>HH:MM</b><span data-flag="TYPE"></span><span class="com_no noN">KART</span>TEXTE</p>
```

### 4.3 Structure HTML d'un commentaire

```html
<!-- Commentaire avec kart concerné -->
<p>
  <b>06:28</b>
  <span data-flag="penalty"></span>
  <span class="com_no no8">20</span>
  Pénalité - Passage au stand en 01:57 (Tour 962) - 1 Tour
</p>

<!-- Commentaire global (sans kart) -->
<p>
  <b>13:00</b>
  <span data-flag="green"></span>
  Départ
</p>
```

| Élément | Contenu | Signification |
|---------|---------|---------------|
| `<b>` | `08:16` | Temps de course **restant** au format HH:MM |
| `data-flag` | voir tableau | Type d'événement |
| `<span class="com_no noN">` | `17` | Numéro de kart concerné (absent si événement global) |
| `noN` | `no7`, `no8`... | Classe CSS de catégorie (même système `noN` que le WS grid) |
| texte | — | Message complet |

### 4.4 Types de `data-flag`

| `data-flag` | Icône UI | Signification |
|-------------|----------|---------------|
| `green` | Drapeau vert | Événement global course (Départ, Safety Car, fin de neutralisation...) |
| `msg` | Info (i) | Message opérationnel, équipement, incident hors pénalité |
| `warning` | Triangle | Avertissement officiel infligé à un kart |
| `penalty` | P rouge | Pénalité infligée **ou retirée** à un kart |

> Les pénalités retirées (`retirée`) restent de type `penalty` — c'est le texte qui différencie.

### 4.5 Parser Python

```python
from bs4 import BeautifulSoup

def parse_comment(html_fragment: str) -> dict | None:
    """
    html_fragment : contenu du message WS après 'com||' ou une ligne du bloc 'comments||'
    Exemple input : '<p><b>06:28</b><span data-flag="penalty"></span><span class="com_no no8">20</span>Pénalité...</p>'
    """
    p = BeautifulSoup(html_fragment, 'html.parser').find('p')
    if not p:
        return None

    time_tag  = p.find('b')
    flag_span = p.find(attrs={'data-flag': True})
    kart_span = p.find(class_=lambda c: c and 'com_no' in c)

    time_str  = time_tag.get_text(strip=True) if time_tag else ''
    flag      = flag_span.get('data-flag', '') if flag_span else ''
    kart_num  = kart_span.get_text(strip=True) if kart_span else None
    kart_cat  = kart_span['class'][1] if kart_span else None  # ex: "no8"

    # Texte = tout sauf les tags structurels
    for el in p.find_all(['b', 'span']):
        el.decompose()
    message = p.get_text(strip=True)

    return {
        'time':     time_str,   # "06:28" (temps restant HH:MM)
        'flag':     flag,       # "penalty" | "warning" | "msg" | "green"
        'kart':     kart_num,   # "20" ou None
        'category': kart_cat,   # "no8" ou None
        'message':  message,    # "Pénalité - Passage au stand en 01:57 (Tour 962) - 1 Tour"
    }

def parse_comments_block(html_block: str) -> list[dict]:
    """Parse le message initial 'comments||<html>' contenant tous les commentaires."""
    soup = BeautifulSoup(html_block, 'html.parser')
    return [c for p in soup.find_all('p') if (c := parse_comment(str(p)))]
```

---

## 5. Tours par pilote — attribution côté client

**L'API ne filtre pas par pilote.** L'UI ne le fait pas non plus (aucune requête générée au clic
sur un pilote, liste de tours inchangée). Le calcul est 100% client-side.

### Principe

`relay_laps` de chaque pit stop = tours effectués dans le stint **se terminant** à ce pit.
Les stints se chaînent sans trou :

```
Pit  1 : driver=44423 (REMI LOTH),      lap=58,   relay_laps=58  → tours   1–58
Pit  2 : driver=44425 (KILIAN SANCHEZ), lap=106,  relay_laps=48  → tours  59–106  (58+48=106 ✓)
Pit  3 : driver=44423 (REMI LOTH),      lap=163,  relay_laps=57  → tours 107–163
...
Pit 28 : driver=44423 (REMI LOTH),      lap=1180, relay_laps=3   → tours 1178–1180
Actuel : driver=44423 (current="1" INF)                          → tours 1181+
```

Formule : `premier_tour_du_stint = pit_précédent.lap + 1`  
Cas initial : `premier_tour_stint_1 = 1` (pas de pit précédent, `prev_lap = 0`).

### Algorithme Python

```python
def get_laps_per_driver(
    pits: list[dict],      # résultat parse_pits_and_inf(), trié par pit_n ASC
    laps: list[dict],      # résultat parse_laps(), trié par lap ASC
    drivers: dict,         # résultat parse_pits_and_inf(), {driver_id: {..., 'current': bool}}
) -> dict[str, list[dict]]:
    """Retourne {driver_id: [{lap, lap_ms}, ...]}"""

    laps_dict = {l['lap']: l['lap_ms'] for l in laps}
    result: dict[str, list] = {}
    prev_lap = 0

    for pit in sorted(pits, key=lambda p: p['pit_n']):
        driver_id   = pit['driver_id']
        stint_start = prev_lap + 1
        stint_end   = pit['lap']

        driver_laps = result.setdefault(driver_id, [])
        for lap_n in range(stint_start, stint_end + 1):
            if lap_n in laps_dict:
                driver_laps.append({'lap': lap_n, 'lap_ms': laps_dict[lap_n]})

        prev_lap = stint_end

    # Stint en cours — source authoritative : current="1" dans INF
    current_driver_id = next(
        (did for did, d in drivers.items() if d['current']), None
    )
    if current_driver_id and pits:
        current_laps = result.setdefault(current_driver_id, [])
        last_pit_lap = max(p['lap'] for p in pits)
        for lap_n in sorted(laps_dict):
            if lap_n > last_pit_lap:
                current_laps.append({'lap': lap_n, 'lap_ms': laps_dict[lap_n]})

    return result
```

### Notes

- `relay_laps` inclut l'out-lap (premier tour après la sortie du stand). Pas de correction nécessaire.
- Si `laps` ne commence pas à 1 (tours 1–5 absents à Brignoles), les premiers tours du premier pilote n'ont pas de temps enregistré — ne pas crasher.
- Utiliser `drivers[id]['current']` (XML INF) plutôt que `pits[-1]['driver_id']` pour le stint en cours : un relais récent peut avoir changé le pilote sans que le pit soit encore clôturé.

---

## 6. Flux complet — implémentation sans browser

```python
import re
import requests
from xml.etree import ElementTree as ET
from bs4 import BeautifulSoup

BASE_URL = "https://live-data.apex-timing.com/live-timing/commonv2/functions/request.php"

def api_request(config_port: int, query: str) -> str:
    r = requests.post(BASE_URL, data={"port": config_port, "request": query}, timeout=15)
    r.raise_for_status()
    return r.text


def get_team_stats(config_port: int, team_id: str) -> dict:
    """Récupère pilotes + historique pits + tous les tours pour une équipe."""

    # Étape 1 : pilotes + pit stops
    raw_pits = api_request(config_port, f"D#-999#D{team_id}.P#1#D{team_id}.INF")
    drivers, pits = parse_pits_and_inf(raw_pits)

    # Étape 2 : total tours + meilleur tour
    raw_count = api_request(config_port, f"D#-1#D{team_id}.L")
    m = re.search(r'\.L(\d+)#\|\|\|(\d+)', raw_count)
    total_laps  = int(m.group(1))
    best_lap_ms = int(m.group(2))

    # Étape 3 : tous les tours d'un coup
    raw_laps = api_request(config_port, f"D#-{total_laps + 50}#D{team_id}.L")
    laps = parse_laps(raw_laps, team_id)

    # Étape 4 : attribution tours → pilotes
    per_driver = get_laps_per_driver(pits, laps, drivers)

    return {
        "team_id":      team_id,
        "drivers":      drivers,       # {driver_id: {id, num, name, color, current}}
        "pits":         pits,          # [{pit_n, lap, in_ms, out_ms, pit_ms, track_ms, relay_laps, driver_id, driver_total_ms}]
        "laps":         laps,          # [{lap, lap_ms}] trié ASC
        "per_driver":   per_driver,    # {driver_id: [{lap, lap_ms}]}
        "total_laps":   total_laps,
        "best_lap_ms":  best_lap_ms,
    }


def parse_pits_and_inf(raw: str) -> tuple[dict, list]:
    pits    = []
    drivers = {}
    for line in raw.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        if re.match(r'D\d+\.P\d+#', line):
            after = line.split('#', 1)[1]
            p = after.split('|')
            pits.append({
                'pit_n':           int(p[0]),
                'lap':             int(p[1]),
                'in_ms':           int(p[2]),
                'out_ms':          int(p[3]),
                'pit_duration_ms': int(p[4]),
                'track_ms':        int(p[5]),
                'relay_laps':      int(p[6]),
                'driver_id':       p[7],
                'driver_total_ms': int(p[8]),
            })
        elif '.INF#' in line:
            xml_str = line.split('.INF#', 1)[1]
            root = ET.fromstring(xml_str)
            for d in root.findall('driver'):
                drivers[d.get('id')] = {
                    'id':      d.get('id'),
                    'num':     d.get('num'),
                    'name':    d.get('name'),
                    'color':   d.get('color'),
                    'current': d.get('current') == '1',
                }
    pits.sort(key=lambda x: x['pit_n'])
    return drivers, pits


def parse_laps(raw: str, team_id: str) -> list[dict]:
    laps = []
    for line in raw.strip().split('\n'):
        m = re.match(rf'D{team_id}\.L(\d+)#\|\|\|(\d+)', line.strip())
        if m:
            laps.append({'lap': int(m.group(1)), 'lap_ms': int(m.group(2))})
    laps.sort(key=lambda x: x['lap'])
    return laps
```

---

## 7. Ce qu'on peut calculer avec ces données

| Information | Source | Calcul |
|-------------|--------|--------|
| Temps total par pilote | API `.P` | `driver_total_ms` du pit le plus récent par `driver_id` |
| Nombre de stints par pilote | API `.P` | `count(pits where driver_id == X)` |
| Durée moyenne pit stop | API `.P` | `mean(pit_duration_ms)` |
| Stint le plus long / court | API `.P` | `max/min(track_ms)` ou `max/min(relay_laps)` |
| Tours par stint | API `.P` | `relay_laps` de chaque pit |
| Meilleur tour équipe | API `.L` | `best_lap_ms` ou `min(laps[].lap_ms)` |
| Distribution temps au tour | API `.L` | histogramme sur `laps[].lap_ms` |
| Tours de pit | API `.P` + `.L` | in-lap = `pits[N].lap`, out-lap = `pits[N].lap + 1` |
| Pilote actuel | API `.INF` | `current="1"` dans XML |
| Meilleur tour par pilote | API `.P` + `.L` | `min(per_driver[id][].lap_ms)` |
| Distribution tours par pilote | API `.P` + `.L` | `per_driver[id]` (cf. §5) |
| Évolution du rythme d'un pilote | API `.P` + `.L` | courbe `lap_ms` sur `per_driver[id]` |
| Pénalités / commentaires live | WS `com\|\|` | cf. §4 |
| Tour actuel de course | WS `rNcX\|tn\|` ou `\|*\|` | signal `*` = nouveau tour |

---

## 8. Notes et contraintes

- **CORS** : pas de restriction depuis Python/serveur. Proxy nécessaire depuis un browser cross-origin.
- **Pas d'authentification** : API publique, seul `configPort` identifie le circuit.
- **Tours manquants en début de course** : la réponse `.L` peut commencer au tour 6 (tours 1–5 absents à Brignoles). Gérer le cas `min(laps[].lap) > 1` sans crasher.
- **Race en cours** : `total_laps` augmente pendant la course. Le buffer de +50 dans `D#-{total+50}#D{id}.L` évite de manquer les tours arrivés entre les deux appels.
- **Pits API vs WS** : `*in`/`*out` WS = détection temps réel. API `.P` = source authoritative pour l'historique complet avec durées exactes.
- **Pilotes absents du WS** : `drteam` WS donne le pilote actuel mais pas la liste complète. `.INF` est la seule source exhaustive.
- **Ordre réponse `.P`** : lignes en ordre décroissant (pit le plus récent en premier), `.INF` toujours en dernière ligne.
- **`D#-999` préfixe** : sémantique inconnue, toujours présent tel quel dans les requêtes pits/inf. Ne pas modifier.
