# Apex Timing — Comportement de l'interface live timing

Référence UX basée sur l'observation en direct de Brignoles Karting Loisirs (24H, 2026).
Destinée à guider la conception d'une interface similaire dans l'application.

---

## 1. Structure globale de la page

```
┌─────────────────────────────────────────────────────────┬──────────────────┐
│  ☰  LES 24H DE BRIGNOLES 2026  COURSE 24H  ●●●●    ⚙   │                  │
├─────────────────────────────────────────────────────────┤  NOM CIRCUIT     │
│                                                         │  (logo)          │
│              GRILLE DE CLASSEMENT                       │                  │
│                                                         │  Commentaires    │
│                                                         │  [liste]         │
├─────────────────────────────────────────────────────────┤                  │
│  CONNECTED ██████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░   │                  │
└─────────────────────────────────────────────────────────┴──────────────────┘
```

### Barre de titre (rouge)
| Élément | Description |
|---|---|
| `☰` hamburger | Accès aux sessions précédentes ("No History" si session unique) |
| Titre 1 | Nom de l'événement (`data-id="title1"`) |
| Titre 2 | Type de course (`data-id="title2"`) |
| `●●●●` (4 dots verts) | Indicateurs de signal/qualité de connexion |
| Chrono | Compte à rebours HH:MM:SS (reçu via `dyn1|countdown|N` en ms) |
| `⚙` gear | Menu options (Ranking Effects, Share, Help) |

### Barre de statut (bas)
- `CONNECTED` en vert = WebSocket actif
- `CONNECTING...` en jaune/orange = reconnexion en cours

### Colonne droite (fixe)
- Nom du circuit + logo
- Journal des commentaires de course (live, défilant vers le bas)

---

## 2. Grille de classement

### Colonnes visibles

| Colonne | Donnée | Notes |
|---|---|---|
| **Clt** | Position | Mis à jour à chaque tour |
| **Kart** | Numéro de kart | Couleur de fond = catégorie |
| **Equipe** | Nom de l'équipe | Cliquable (bascule vers vue pilotes) |
| **Nation** | Drapeau pays | |
| **Dernier T.** | Temps du dernier tour | Rouge = meilleur du peloton |
| **Ecart** | Gap au leader | "Tour X" si doublé de X tours |
| **Interv.** | Intervalle avec le précédent | |
| **Meilleur T.** | Meilleur tour de l'équipe | Rouge = record de course |
| **En piste** | Durée depuis la dernière sortie des stands | |
| **Stands** | Nombre d'arrêts aux stands | |
| **Péna.** | Pénalités actives | "1 Tr", "3 Trs" = tours de pénalité |

### Comportement de la grille

**Clic sur une ligne** — bascule entre deux modes d'affichage :
- **Mode équipe** : affiche `Kart | Nom équipe | ...`
- **Mode pilote** : affiche `icône | NOM PILOTE [temps relais]` pour chaque ligne, avec le temps total en piste du relais actuel entre crochets

Ce toggle est global pour toutes les lignes simultanément.

**Code couleur des lignes** :
- Fond coloré selon la catégorie (classe CSS `no1`, `no2`, `notc{decimal}` sur la cellule kart, ou préfixe dans le nom d'équipe)
- Certaines catégories ont un fond distinctif (orange, rouge, blanc, etc.)

**Colonne Péna.** : uniquement affichée quand une pénalité est active sur l'équipe ; disparaît après exécution.

---

## 3. Vue statistiques d'une équipe

Déclenchée via `show_driver_laps_time(teamId)` — remplace la grille complète.

```
┌─ Retour ─────────────────────────────────────────────────────────────────┐
│                                                                           │
│  [3] STF BY KARTCUP                                              ♥        │
│  ● REMI LOTH           07:04:42                                           │
│  ◉ MARVIN KLEIN        08:00:03  (+53min)    ← pilote actif               │
│  ● KILIAN SANCHEZ      06:28:37                                           │
│                                                                           │
├───────────────────────┬───────────────────────────────────────────────────┤
│                       │  ╭─────────────────────────────────────────────╮ │
│  LAPS    PITS         │  │  [graphique courbe temps au tour]           │ │
│                       │  │                                       [−][+]│ │
│  Lap     Time         │  │  Laps →                                     │ │
│  Best    1:00.245     │  ╰─────────────────────────────────────────────╯ │
│  1279    1:01.768  +1.523│                                               │
│  1278    1:01.819  +1.574│  Compare: [dropdown équipes]                  │
│  1277    1:01.966  +1.721│                                               │
│  ...                  │                                                   │
└───────────────────────┴───────────────────────────────────────────────────┘
```

### Panel gauche — pilotes

| Élément | Description |
|---|---|
| Badge numéro | Couleur de catégorie de l'équipe |
| Nom équipe | Titre de la section |
| `♥` | Ajout aux favoris |
| Icône `●` | Pilote en attente |
| Icône `◉` | Pilote **actuellement en piste** (relais actif) |
| Temps à côté du pilote | Durée totale en piste sur toute la course |
| `(+Xmin)` | Durée du relais en cours depuis la sortie des stands |

Les pilotes ne servent pas de filtre — cliquer dessus n'a pas d'effet sur les onglets LAPS/PITS.

### Graphique

- Courbe bleue : évolution du temps au tour sur l'ensemble de la course
- Axe X : numéros de tours (de gauche = début à droite = récent)
- Axe Y : temps (non gradué, relatif)
- Pics = tours de pit-stop ou incidents
- Boutons `[−][+]` : zoom (affichent moins/plus de tours sur l'axe X)
- **Compare** : dropdown listant tous les pilotes de la course (`driver_select`) — superpose une seconde courbe pour comparaison

---

## 4. Onglet LAPS

Tableau des tours de l'équipe, du plus récent au plus ancien.

| Colonne | Description |
|---|---|
| Lap | Numéro de tour |
| Time | Temps en `M:SS.mmm` |
| Delta | `+X.XXX` par rapport au meilleur tour de l'équipe |

**Couleurs** :
- Temps en **or/jaune** = meilleur tour absolu de l'équipe (`Best: M:SS.mmm`)
- Delta en **jaune** = écart positif normal
- Tour de pit-stop : temps anormalement long (ex: `3:03.709`) avec delta `+2:03.464`

**Pagination** : bouton "Show More" charge 30 tours supplémentaires par clic.
Le nombre de tours initial affiché est ~20, puis +30 à chaque "Show More".

---

## 5. Onglet PITS

Historique complet des arrêts aux stands de l'équipe, du plus récent au plus ancien.

| Colonne | Description |
|---|---|
| Lap | Numéro du tour lors de l'entrée aux stands |
| Hour | Heure horloge de l'arrêt (HH:MM:SS) |
| On track | Durée du relais effectué avant cet arrêt |
| Driver | Nom du pilote qui conduisait ce relais |
| Total | Temps total cumulé de ce pilote sur toute la course |
| Pit time | Durée de l'arrêt stands (format `M:SS.mmm`) |

Exemple de ligne :
```
30 | 1266 | 22:32:01 | 00:39:31 | MARVIN KLEIN | 08:00:03 | 2:01.476
```
→ Au tour 1266, MARVIN KLEIN est entré aux stands après 39min31 de relais, total cumulé 8h, arrêt de 2min01.

---

## 6. Journal des commentaires (colonne droite)

Flux live de messages officiels, mis à jour en temps réel.

### Format d'une entrée

```
10:49  [🔴]  [6]  Blessure pilote constatée par le médecin. Remplacement autorisé
08:16  [ℹ]  [17]  Casque non attaché - passage aux stands 2 min non comptabilisé
06:46  [⚠]  [7]   Avertissement - Conduite anti-sportive sur retardataire
06:28  [🔴]  [20]  Pénalité - Passage au stand en 01:57 (Tour 962) - 1 Tour
```

| Élément | Description |
|---|---|
| Heure | Heure horloge du message (HH:MM) |
| Badge couleur | Type d'événement (voir ci-dessous) |
| Numéro | Numéro de kart concerné |
| Texte | Description de l'événement |

### Types de badges (`data-flag`)

| Flag | Couleur | Signification |
|---|---|---|
| `green` | Vert | Green flag / reprise de course |
| `msg` | Bleu (ℹ) | Message informatif neutre |
| `warning` | Orange (▶) | Avertissement officiel |
| `penalty` | Rouge (●) | Pénalité infligée |

### Exemples de textes de pénalités
- `Pénalité - Passage au stand en 01:57 (Tour 962) - 1 Tour`
- `Pénalité - Temps de relai de 1:02:56 (Tour 772) - 1 Tour`
- `Pénalité stands retirée (erreur scan bracelet)`
- `Avertissement - Conduite anti-sportive sur retardataire`
- `Prochain arrêt en 1:44:00`
- `Équipement non conforme - passage aux stands non comptabilisé`

---

## 7. Menus

### Menu hamburger `☰` (haut gauche)
- Liste les **sessions précédentes** du même circuit
- Affiche "No History" si la session courante est la seule
- Permet de naviguer vers les résultats d'une session passée sans WS live

### Menu gear `⚙` (haut droit)

| Option | Description |
|---|---|
| Ranking Effects | Toggle ON/OFF — effets visuels de changement de position (animations) |
| Share | Génère un QR code pour partager l'URL de la session |
| Help | Aide intégrée |

---

## 8. Navigation entre vues

```
Grille principale
    │
    ├─── clic ligne ──────────► Toggle mode pilotes (in-place, même grille)
    │
    └─── show_driver_laps_time(id) ──► Vue stats équipe
              │
              ├─── onglet LAPS ──► Liste tours + graphique
              │         └─── Compare dropdown ──► Superposition courbe
              │
              ├─── onglet PITS ──► Historique arrêts
              │
              └─── Back to Live Timing ──► Retour grille
```

---

## 9. Ce que l'interface NE fait PAS

- **Pas de filtrage par pilote** : les onglets LAPS et PITS montrent toujours les données de l'**équipe entière**, pas d'un pilote spécifique. L'attribution tours/pilotes est calculable via les données API (voir `stats-api-protocol.md` §5).
- **Pas de secteurs** : les temps S1/S2/S3 sont disponibles dans l'API mais ne sont pas affichés dans l'interface standard.
- **Pas de tri/filtre** dans le tableau PITS.
- **Pagination bloquante** sur LAPS : il faut cliquer "Show More" pour voir les anciens tours.

---

## 10. Opportunités d'amélioration pour ton app

| Fonctionnalité absente chez Apex | Valeur |
|---|---|
| Tours filtrés par pilote | Très utile en endurance pour comparer les pilotes d'une équipe |
| Secteurs S1/S2/S3 par tour | Disponibles via API, non affichés |
| Delta par rapport au leader du moment | Apex montre uniquement le gap total |
| Indicateur visuel de kart (qualité) | Absent chez Apex, ton app le fait déjà |
| Historique pit avec relais restants à faire | Non calculé par Apex |
| Commentaires filtrables par équipe | Apex les affiche tous mélangés |
| Notification de pénalité en temps réel | Apex ne push pas d'alerte |
