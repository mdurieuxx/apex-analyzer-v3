# Apex Timing — Interface live timing : comportement UX complet

Référence basée sur observation en direct de Brignoles (24H 2026).
Chaque interaction est documentée avec la fonction JS sous-jacente.

---

## 1. Structure générale

```
┌──────────────────────────────────────────────────────────┬──────────────────┐
│  ☰  LES 24H DE BRIGNOLES 2026   COURSE 24H   ●●●●   ⚙  │ CIRCUIT (987m)   │
├──────────────────────────────────────────────────────────┤ (logo)           │
│                                                          │                  │
│   [GRILLE DE CLASSEMENT]                                 │ Commentaires     │
│                                                          │ (live, défilant) │
├──────────────────────────────────────────────────────────┤                  │
│  CONNECTED ████░░░░░░░░                                  │                  │
└──────────────────────────────────────────────────────────┴──────────────────┘
```

| Zone | Description |
|---|---|
| `☰` | Menu historique sessions (voir §6) |
| Titre 1 / Titre 2 | Nom événement + type de course (`data-id="title1/title2"`) |
| `●●●●` 4 dots | Indicateurs de qualité de signal WebSocket |
| Chrono | Compte à rebours `HH:MM:SS` (source : `dyn1|countdown|N` ms) |
| `⚙` | Menu options (voir §7) |
| Barre statut bas | `CONNECTED` vert / `CONNECTING...` jaune |

---

## 2. Grille de classement — colonnes

| Col | `data-type` | Contenu |
|---|---|---|
| Clt | `sta` | Position actuelle |
| Kart | `rk` | Numéro kart, fond coloré = catégorie |
| Equipe | `dr` | Nom équipe (ou pilote en mode driver, voir §3) |
| Nation | `nat` | Drapeau |
| Dernier T. | `llp` | Dernier tour. **Rouge** = meilleur du peloton |
| Ecart | `in` | Gap au leader. `Tour X` si doublé |
| Interv. | `in` | Intervalle avec le rang précédent |
| Meilleur T. | `tb` | Meilleur tour. **Rouge** = record de course |
| En piste | `to` | Durée depuis dernier passage aux stands |
| Stands | `in` | Nombre d'arrêts stands |
| Péna. | (dernière col) | `1 Tr` / `3 Trs` = tours de pénalité actifs |

**Couleurs de fond des lignes** : déterminées par la catégorie du kart (classes CSS `no1`, `no2`, `notc{decimal}` sur la cellule kart, ou préfixe `CATEGORIE - NOM` dans le nom d'équipe).

---

## 3. Clic sur une ligne — toggle mode pilotes

Handler JS : `tzflr(this, event)` sur chaque `<tr>`

**Premier clic** : ouvre le popup contextuel (voir §4).

**La colonne Equipe bascule** entre deux affichages globaux (toutes lignes en même temps) :

| Mode | Affichage colonne Equipe |
|---|---|
| **Équipe** | Nom de l'équipe |
| **Pilote** | `NOM PILOTE [MM:SS]` — pilote actuel + durée relais en cours entre `[]` |

Ce toggle est global : un clic bascule **toute** la grille, pas seulement la ligne cliquée.

---

## 4. Popup contextuel — clic sur une ligne

S'ouvre au clic sur n'importe quelle cellule de la ligne (`onclick="tzflr(this,event)"`).
Le popup se positionne à côté du curseur de la souris.

### Structure visuelle du popup

```
┌─────────────────────────────────────────┐
│  [📊 Statistics]  [🔴 On Board]  [♥]   │  ← barre de boutons
├─────────────────────────────────────────┤
│  [3]  STF BY KARTCUP                    │  ← badge kart + nom équipe
├─────────────────────────────────────────┤
│  ○  REMI LOTH          07:04:42         │  ← pilote inactif
│  ◉  MARVIN KLEIN       08:18:39         │  ← pilote actif (en piste)
│  ○  KILIAN SANCHEZ     06:28:37         │  ← pilote inactif
└─────────────────────────────────────────┘
```

### Boutons du popup

| Bouton | JS | Comportement |
|---|---|---|
| **Statistics** | `show_driver_laps_time(this)` | Ouvre la vue stats de l'équipe (voir §5) |
| **On Board** | `go_onboard()` | Ouvre la vue suivi mono-équipe (voir §8) |
| **♥** | `select_line()` | Toggle surlignage de la ligne dans la grille |

### Bouton ♥ (select_line)

- État **sélectionné** (`selected`) : la ligne est surlignée en permanence dans la grille
- État **désélectionné** : la ligne reprend son apparence normale
- Plusieurs lignes peuvent être sélectionnées simultanément
- La sélection est mémorisée pendant la navigation

### Section pilotes dans le popup

| Icône | Signification |
|---|---|
| `○` (cercle vide) | Pilote au repos |
| `◉` (cercle plein) | Pilote **actuellement en piste** (relais actif) |
| Temps | Durée totale cumulée en piste sur toute la course |

---

## 5. Vue Statistics (`show_driver_laps_time`)

Remplace la grille complète. Accessible via popup → Statistics.

### Layout

```
┌─ ← Back to Live Timing ──────────────────────────────────────────────────┐
│                                                                            │
│  [3] STF BY KARTCUP                                                  ♥    │
│                                                                            │
│  ○ REMI LOTH         07:04:42                                              │
│  ◉ MARVIN KLEIN      08:18:39  (+53min)   ← durée relais actuel           │
│  ○ KILIAN SANCHEZ    06:28:37                                              │
│                                                                            │
├──────────────────────────┬─────────────────────────────────────────────────┤
│  [ LAPS ]  [ PITS ]      │  [graphique courbe temps au tour]               │
│                          │                                          [−][+]  │
│  Best : 1:00.245         │  Laps →                                         │
│  1284  1:01.695  +1.450  │                                                  │
│  1283  1:01.906  +1.661  │  Compare: [▼ dropdown équipes]                  │
│  ...                     │                                                  │
└──────────────────────────┴─────────────────────────────────────────────────┘
```

### Panel pilotes (gauche)

| Élément | Signification |
|---|---|
| Badge `[3]` coloré | Numéro kart + couleur catégorie |
| `♥` (coin droit) | Ajouter/retirer des favoris |
| Icône `○` / `◉` | Inactif / En piste |
| Temps après le nom | Durée totale en piste sur la course |
| `(+Xmin)` | Durée du relais en cours (affiché uniquement pour le pilote actif) |

**Cliquer sur un pilote** : aucun effet sur les onglets — pas de filtre par pilote.

### Graphique

| Élément | Description |
|---|---|
| Courbe bleue | Temps au tour, tous tours, chronologiquement gauche→droite |
| Axe X | Numéros de tours (`Laps →`) |
| Axe Y | Temps (relatif, non gradué) |
| Pics | Tours de pit-stop ou incidents |
| `[−]` / `[+]` | Dézoom / zoom sur l'axe X (`show_less/more_graphic_laps_time()`) |
| **Compare** | Dropdown (`select#driver_select`) listant tous les pilotes de la course. Sélectionner superpose une 2e courbe pour comparaison visuelle |

### Onglet LAPS

| Colonne | Description |
|---|---|
| Lap | Numéro de tour |
| Time | Temps `M:SS.mmm`. **Or** = meilleur tour de l'équipe |
| Delta | `+X.XXX` vs meilleur tour. Tour de pit = delta très élevé ex: `+2:03.464` |

- Liste triée du plus récent au plus ancien
- `Best : M:SS.mmm` affiché en haut
- Bouton **Show More** : charge 30 tours supplémentaires par clic (pagination de 30)
- Tous les tours d'une équipe pour une course de 24h = ~1280 tours

### Onglet PITS

| Colonne | Description |
|---|---|
| Lap | Numéro du tour d'entrée aux stands |
| Hour | Heure horloge de l'arrêt `HH:MM:SS` |
| On track | Durée du relais effectué avant cet arrêt `HH:MM:SS` |
| Driver | Nom du pilote qui conduisait ce relais |
| Total | Temps total cumulé de ce pilote sur toute la course |
| Pit time | Durée de l'arrêt stands `M:SS.mmm` |

Trié du plus récent au plus ancien. Pas de filtre, pas de tri cliquable.

---

## 6. Menu hamburger `☰`

Fonction JS : `show_lives_list()`

Affiche la liste des **sessions précédentes** du même circuit.
- `No History` si aucune session précédente
- Sinon : liste de sessions passées cliquables pour accéder aux résultats archivés (lecture seule, sans WS live)

---

## 7. Menu options `⚙`

Fonction JS : `show_options_list()`

| Option | Comportement |
|---|---|
| **Ranking Effects** (toggle vert/gris) | Active/désactive les animations visuelles de changement de position dans la grille |
| **Share** | Génère et affiche un QR code pour partager l'URL de la session live |
| **Help** | Affiche l'aide intégrée |

---

## 8. Vue On Board (`go_onboard`)

Vue de **suivi mono-équipe**, optimisée pour afficher une seule équipe en grand.
Accessible via popup → On Board.

```
← Live Timing                  REMI LOTH [7:08]                   [Driver ▼]
┌──────────┐   ●                                              1:00.245  ← best
│    P1    │                                                  1:02.884  ← dernier (jaune)
└──────────┘
        En piste                                   Stands
        0:04                                       31
                              [3]
                        (badge kart, centré)
```

| Élément | Description |
|---|---|
| `P1` (grand, haut gauche) | Position actuelle, mise à jour live |
| `REMI LOTH [7:08]` (centre haut) | Pilote actuel + durée relais en cours |
| Dot vert (petit carré) | Indicateur de connexion/signal |
| `1:00.245` (blanc, haut droit) | Meilleur tour de l'équipe |
| `1:02.884` (jaune, haut droit) | Dernier tour |
| `En piste` | Durée depuis la dernière sortie des stands |
| `Stands` | Nombre d'arrêts stands |
| `[3]` (badge centré) | Numéro de kart |
| `← Live Timing` | Lien retour vers la grille principale (`show_live()`) |
| `[Driver ▼]` | Dropdown pour changer d'équipe suivie (voir ci-dessous) |

### Bouton Driver — changer d'équipe

Fonction : `show_list_driver()`

Ouvre un **panneau déroulant** listant tous les pilotes de la course :
```
1 - BASTIEN MEUNIER
2 - AXEL LENGRONNE
3 - REMI LOTH [7:08]   ← équipe actuellement suivie (surlignée)
4 - MALIK BOTREL [5:5...]
5 - GUILLAUME RADEN...
...
```
Chaque ligne correspond à un pilote d'une équipe avec le temps de relais actuel.
Cliquer sur une entrée bascule la vue On Board sur cette équipe (`tzfii('#driver_rXXXXX', this)`).

---

## 9. Journal des commentaires (colonne droite)

Flux live, mis à jour en temps réel via WS (`com||` et `comments||`).

### Format d'une entrée

```
10:49  [●rouge]  [6]   Blessure pilote constatée par le médecin. Remplacement autorisé
08:16  [ℹbleu]  [17]  Casque non attaché - passage aux stands 2 min non comptabilisé
06:46  [▶orange] [7]   Avertissement - Conduite anti-sportive sur retardataire
06:28  [●rouge]  [20]  Pénalité - Passage au stand en 01:57 (Tour 962) - 1 Tour
```

| Champ | Description |
|---|---|
| Heure | `HH:MM` heure horloge |
| Badge | Type d'événement (couleur + icône) |
| Numéro | Numéro de kart concerné |
| Texte | Description de l'événement |

### Types de badges (`data-flag`)

| Flag | Aspect | Quand |
|---|---|---|
| `green` | Vert | Reprise de course, green flag |
| `msg` | Bleu `ℹ` | Message informatif neutre |
| `warning` | Orange `▶` | Avertissement officiel |
| `penalty` | Rouge `●` | Pénalité infligée |

---

## 10. Navigation complète

```
GRILLE PRINCIPALE
│
├─ clic n'importe quelle cellule ──► POPUP CONTEXTUEL
│      │
│      ├─ [Statistics] ──────────────► VUE STATS ÉQUIPE
│      │      ├─ onglet LAPS ────────► liste tours + graphique + Compare
│      │      ├─ onglet PITS ────────► historique arrêts
│      │      └─ ← Back to Live Timing ──► GRILLE
│      │
│      ├─ [On Board] ───────────────► VUE ON BOARD
│      │      ├─ [Driver ▼] ────────► liste pilotes pour switcher
│      │      └─ ← Live Timing ─────► GRILLE
│      │
│      └─ [♥] ──────────────────────► toggle surlignage ligne (in-place)
│
├─ clic colonne Equipe ────────────► toggle mode TEAM ↔ PILOTE (in-place, global)
│
├─ ☰ ─────────────────────────────► liste sessions précédentes
│
└─ ⚙ ─────────────────────────────► menu options (Ranking Effects / Share / Help)
```

---

## 11. Ce que l'interface ne fait pas

- **Pas de filtre par pilote** dans LAPS/PITS — toujours les données de l'équipe entière
- **Pas de secteurs S1/S2/S3** affichés (disponibles en API)
- **Pas de tri** dans le tableau PITS
- **Pas d'alerte push** sur pénalité ou changement de position
- **Pagination bloquante** sur LAPS : clic obligatoire pour voir les anciens tours
- **Pas de comparaison multi-équipes** dans la grille (seulement dans le graphique)

---

## 12. Opportunités pour ton app

| Absent chez Apex | Valeur |
|---|---|
| Tours filtrés par pilote | Essentiel en endurance pour comparer les pilotes d'une équipe |
| Alerte pénalité en temps réel | Notification push quand une pénalité touche une équipe suivie |
| Secteurs S1/S2/S3 par tour | Disponibles via API, jamais affichés dans l'UI standard |
| Indicateur qualité kart | Absent chez Apex, ton app le fait déjà (ROCKET/FAST/BAD) |
| Calcul relais restants | Apex ne projette pas les stands futurs |
| Commentaires filtrés par équipe | Apex les affiche tous mélangés |
| Comparaison directe pilotes d'une équipe dans LAPS | Impossible aujourd'hui |
