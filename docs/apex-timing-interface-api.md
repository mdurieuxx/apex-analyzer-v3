# Apex Timing — Interface native & API disponible

> Analyse basée sur le reverse-engineering du protocole (lap_api.py, grid_parser.py, client.py)
> et la connaissance de l'interface native Apex Timing.
> Le site bloque les fetches automatiques — à compléter avec DevTools navigateur sur une session live.

---

## Interface native — clic sur une équipe

Clic sur une ligne du tableau → **modal centré** (ou panel selon la version) avec :

### 1. Header équipe
- Nom équipe
- Numéro de kart (bib)
- Catégorie / club
- Position actuelle

### 2. Graphique évolution des tours
- Line chart : numéro de tour (X) vs temps total en secondes (Y)
- Tours pit exclus ou affichés différemment (point gris)
- Ligne horizontale = meilleur tour de l'équipe
- Hover = tooltip avec temps formaté

### 3. Tableau historique des tours
| Tour | S1 | S2 | S3 | Total |
|------|----|----|----|----|
| 47 | 18.4 | 22.1 | 19.5 | 1:00.0 |
- Secteur en **violet** si meilleur personnel (`g` prefix dans le protocole)
- Tour marqué `PIT` si `p` prefix
- Trié du plus récent au plus ancien

### 4. Meilleurs temps
| | S1 | S2 | S3 | Total |
|---|---|---|---|---|
| Meilleur tour | 18.2 | 21.8 | 19.5 | 59.5 |
| **Théorique** | 18.2 | 21.7 | 19.4 | **59.3** |

> Le théorique = somme des meilleurs secteurs individuels (pas forcément sur le même tour).

### 5. Liste des pilotes du relais
- Nom + numéro transponder
- Badge "En piste" sur le pilote actuel (`current="1"` dans le XML INF)

### 6. Actions disponibles
- ⭐ Marquer comme favori (surbrillance dans le tableau principal)
- 📄 Export PDF (version compétition uniquement)
- ✕ Fermer le modal

---

## Fonctionnalités de l'interface principale (tableau)

### Colonnes standard
| Colonne | Contenu | Notes |
|---------|---------|-------|
| Position | Numéro de position | Bulle colorée (1er = or) |
| Kart / Bib | Numéro de départ | — |
| Équipe | Nom équipe | + pilote actuel si disponible |
| Catégorie | Badge couleur | `notc{decimal}` → RGB ou `no1`/`no2` |
| Gap | Écart au leader | — |
| Interval | Écart à l'équipe devant | — |
| S1 / S2 / S3 | Secteurs actuels | Violet = best session, vert = best perso |
| Dernier tour | Temps du dernier passage | Coloré selon classe CSS |
| Meilleur tour | Meilleur depuis le début | Toujours violet |
| Tours | Nombre de tours | — |
| Stands | Nombre d'arrêts | Orange si actuellement aux stands |

### Codes couleur CSS Apex
| Classe | Couleur affichée | Signification |
|--------|-----------------|---------------|
| `tb` / `sb` / `best` | Violet | Meilleur tour de la session |
| `ti` / `pb` / `improved` | Vert | Meilleur tour personnel |
| *(aucune)* | Blanc/gris | Tour normal |
| `p` prefix (données) | — | Tour de pit / out-lap |
| `g` prefix (données) | — | Meilleur secteur personnel |

### Favoris
- Clic étoile → équipe mise en surbrillance jaune dans le tableau
- Persisté en cookie/localStorage dans l'interface native

### Filtre par catégorie
- Boutons par catégorie (couleurs correspondantes)
- Filtre le tableau pour n'afficher qu'une catégorie

---

## API HTTP — `request.php`

**Endpoint :** `POST https://www.apex-timing.com/live-timing/commonv2/functions/request.php`

**Headers requis :**
```
Origin: https://www.apex-timing.com
Referer: <url_du_circuit>
User-Agent: Mozilla/5.0 ...
Content-Type: application/x-www-form-urlencoded
```

**Body :** `port={dataPort}&request={commandes}`

> `dataPort = wsPort - 3` (ex: wsPort 8313 → dataPort 8310)

### Commandes disponibles

| Commande | Description | Exemple |
|----------|-------------|---------|
| `D{id}.L#-999` | Tous les tours du driver (999 derniers) | `Dr5.L#-999` |
| `D{id}.B#1` | Meilleur tour (flag = inclure secteurs) | `Dr5.B#1` |
| `D{id}.BS` | Meilleurs secteurs théoriques | `Dr5.BS` |
| `D{id}.BL` | Best lap avec S1/S2/S3 détaillés | `Dr5.BL` |
| `D{id}.INF` | Infos équipe (XML) | `Dr5.INF` |
| `D#-30` | Données globales session (30 dernières entrées) | — |

> Plusieurs commandes peuvent être concaténées avec `#` dans le même body.

### Format de réponse — Tours (`D{id}.L{N}`)

```
Dr5.L47#18400|22100|19500|60000
Dr5.L46#g18200|22300|19800|60300
Dr5.L45#p19000|23000|20000|62000
```

| Préfixe valeur | Signification |
|----------------|--------------|
| *(aucun)* | Temps normal |
| `g` | Meilleur secteur/tour personnel |
| `p` | Tour de pit / out-lap lent |

**Structure par tour :** `S1_ms | S2_ms | S3_ms | Total_ms`

### Format de réponse — Best lap (`D{id}.BL`)

```
Dr5.BL#18200|21800|19500|59500
```

`S1_ms | S2_ms | S3_ms | Total_ms`

### Format de réponse — Best secteurs théoriques (`D{id}.BS`)

```
Dr5.BS#18200|21700|19400
```

`S1_ms | S2_ms | S3_ms` (somme = meilleur théorique possible)

### Format de réponse — Infos équipe (`D{id}.INF`)

```xml
<item num="12" name="Team Rouge">
  <info type="club" value="Club Nord"/>
  <driver id="1" num="5" name="Pierre Dupont" current="1"/>
  <driver id="2" num="6" name="Marc Martin"/>
</item>
```

---

## API WebSocket — données live

**URL :** `{wss|ws}://www.apex-timing.com:{wsPort}/`

**Header requis :** `Origin: <url_circuit_sans_slash_final>`

**CRITIQUE : ne jamais envoyer de message après connexion.**

### Messages reçus

| Format | Données | Notes |
|--------|---------|-------|
| `grid\|html\|<html>` | Dump HTML complet | Envoyé à la connexion uniquement |
| `rNcM\|css\|value` | Mise à jour cellule | Ligne N, colonne M |
| `rN\|*in\|0` | Pit in | Équipe N entre aux stands |
| `rN\|*out\|0` | Pit out | Équipe N quitte les stands |
| `rN\|*\|lap_ms\|` | Nouveau tour | Sans secteurs |
| `rN\|*\|lap_ms\|s1_ms` | Nouveau tour | Avec secteur 1 |
| `title1\|...\|val` | Titre session | — |
| `title2\|...\|val` | Sous-titre | — |
| `dyn1\|countdown\|N` | Compte à rebours (s) | — |
| `com\|...\|<html>` | Commentaires | — |

### Données disponibles via la grille HTML initiale

Colonnes détectées via `data-type` attribute sur les `<th>` :
`pos`, `krt`, `nam` (team), `drv` (driver), `llp` (last_lap), `blp` (best_lap),
`gap`, `int`, `s1`, `s2`, `s3`, `tlp` (laps), `otr` (on_track), `pit`, `pen`

---

## Données disponibles pour un événement donné

> Un "événement" chez Apex Timing = une **session en cours** identifiée par son port WS.
> Il n'existe pas de notion d'événement nommé ou d'ID d'événement dans l'API publique.

### Vue d'ensemble par driver (session en cours)

Pour chaque équipe présente dans la grille (`driver_id` = `r{N}`) :

| Donnée | Source | Disponible |
|--------|--------|-----------|
| Position actuelle | WebSocket grille | ✅ temps réel |
| Numéro kart (bib) | WebSocket grille | ✅ temps réel |
| Nom équipe | WebSocket grille | ✅ (dump HTML initial) |
| Pilote actuel | WebSocket grille (`drteam` class) | ✅ si exposé par le circuit |
| Liste tous les pilotes de l'équipe | `request.php` → `.INF` | ✅ pull |
| Dernier tour (S1/S2/S3/Total) | WebSocket grille | ✅ temps réel |
| Meilleur tour (S1/S2/S3/Total) | WebSocket grille + `.BL` | ✅ temps réel |
| Meilleurs secteurs théoriques | `request.php` → `.BS` | ✅ pull |
| Historique de tous les tours | `request.php` → `.L#-999` | ✅ pull, jusqu'à 999 tours |
| Gap au leader | WebSocket grille | ✅ temps réel |
| Interval (écart devant) | WebSocket grille | ✅ temps réel |
| Nombre de tours | WebSocket grille | ✅ temps réel |
| Nombre de stands | WebSocket grille | ✅ temps réel |
| Statut pit in / pit out | WebSocket (`*in` / `*out`) | ✅ événement push |
| Catégorie | WebSocket grille (CSS class) | ✅ si circuit la gère |
| Club | `request.php` → `.INF` | ✅ pull |
| Pénalité | WebSocket grille | ✅ si exposé |

### Données de session (globales)

| Donnée | Source | Disponible |
|--------|--------|-----------|
| Titre session (nom événement) | WebSocket `title1` / `title2` | ✅ push |
| Compte à rebours / temps restant | WebSocket `countdown` | ✅ push |
| Type de session (course/qualifs) | Déduit du titre | ✅ (heuristique) |
| Nombre d'équipes | Grille HTML initiale | ✅ |
| Commentaires de course | WebSocket `com` | ✅ push |
| Meilleur tour de la session | CSS class `tb`/`sb`/`best` | ✅ (marquage dans grille) |

### Ce qu'on peut dériver / calculer côté serveur

| Donnée calculée | Comment |
|-----------------|---------|
| Niveau équipe (ELITE/FAST/...) | Quartile delta vs field_avg — `kart_ranker.py` |
| Qualité kart actuel (GOOD/NEUTRAL/BAD) | Delta stint vs attendu pour le niveau |
| Niveau pilote | Agrégat stints nommés |
| Durée des stands | `exited_at - entered_at` — `pit_manager.py` |
| File de réserve optimale | FIFO + min_pit_duration — `pit_manager.py` |
| Meilleur théorique | Somme best S1+S2+S3 tous tours — `lap_api.py` |
| Tendance temps de tour | Fenêtre glissante — `track_condition.py` |

### Ce qu'on ne peut PAS obtenir (même pendant un événement)

| Donnée | Raison |
|--------|--------|
| Historique des sessions passées | API limitée à la session en cours |
| Nom de l'événement structuré | Seulement titre libre dans `title1`/`title2` |
| Heure de départ officielle | Non exposée (déduite du countdown) |
| Nombre de karts total engagés | Non exposé avant la connexion |
| Résultats officiels / classement final | Disparaît à la fin de session |
| Données météo / conditions piste | Aucune API |
| Position GPS des karts | Système GoTracking séparé, non accessible |
| Télémétrie moteur | Non disponible |

---

## Ce qu'on ne peut PAS obtenir via API

| Donnée | Disponibilité |
|--------|--------------|
| Position GPS / tracking kart | ❌ Non exposé (GoTracking = système séparé) |
| Temperatures / météo | ❌ Aucune API |
| Données moteur / télémétrie | ❌ Non disponible |
| Historique sessions passées | ❌ Seulement session en cours |
| Export PDF programmatique | ❌ Généré côté serveur Apex, pas d'API |
| Identification transponder RFID | ❌ Interne au système |

---

## À explorer avec DevTools sur une session live

Pour compléter cette analyse, ouvrir `https://www.apex-timing.com/live-timing/karting-mariembourg/index.html`
pendant une session active et inspecter :

1. **Network → WS** : voir tous les messages WebSocket reçus
2. **Network → Fetch/XHR** : voir les requêtes vers `request.php` déclenchées au clic
3. **Sources → JS** : chercher les fonctions `showDetail`, `openPopup`, `loadLaps`
4. **Elements** : structure du modal qui apparaît au clic (classes CSS, data-attributes)
