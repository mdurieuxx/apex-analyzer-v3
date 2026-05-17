# Karting Live — Spécifications

Toutes les règles métier, contraintes techniques et comportements attendus définis au cours du projet.

---

## 1. Protocole Apex Timing WebSocket

### Connexion
- **CRITIQUE : ne jamais envoyer de message après la connexion** — même une chaîne vide provoque une déconnexion immédiate côté serveur Java.
- Tentative WSS en premier, fallback WS si échec.
- Schéma d'URL : `{wss|ws}://www.apex-timing.com:{port}/`
- Header `Origin` requis = URL du circuit sans slash final.

### Ports
- Port WS sécurisé : `displayPort + 3`
- Port WS non sécurisé : `displayPort + 2`
- Port HTTP data API : `wsPort - 3`
- Auto-découverte : fetcher la page HTML du circuit avec un User-Agent navigateur, extraire le port depuis le JS (patterns : `wsPort`, `ws_port`, `port =`).
- Override manuel possible via variable d'env `WS_PORT` ou config UI.

### Format des messages (newline-séparés)
```
ELEMENT_ID|CSS_CLASS|VALUE
```
- `title1|...|valeur` — titre ligne 1 de la session
- `title2|...|valeur` — titre ligne 2 / sous-titre
- `grid|html|<html>` — dump HTML complet de la grille (envoyé à la connexion)
- `dyn1|countdown|N` — compte à rebours en secondes
- `com|...|<html>` — commentaires de course
- `r{N}c{M}|css|valeur` — mise à jour incrémentale : ligne N, colonne M

### Mapping des colonnes (valeurs par défaut — Karting de Saintes)
| Colonne | Champ       |
|---------|-------------|
| c2      | position    |
| c3      | kart (bib)  |
| c4      | équipe      |
| c5      | gap         |
| c6      | interval    |
| c7      | S1          |
| c8      | S2          |
| c9      | S3          |
| c10     | dernier tour|
| c11     | meilleur tour|
| c12     | on_track    |
| c13     | stands      |
| c14     | pénalité    |

> **Les noms d'équipes et numéros de kart n'apparaissent que dans le dump HTML initial** — jamais dans les mises à jour incrémentales.

> **Les colonnes peuvent différer d'un circuit à l'autre et entre course/qualifications.** Le système doit détecter dynamiquement le mapping depuis la ligne d'en-tête de la grille HTML, avec fallback sur les valeurs ci-dessus.

### API HTTP Lap Detail
- Endpoint : `POST https://www.apex-timing.com/live-timing/commonv2/functions/request.php`
- Body : `port={dataPort}&request=D{id}.L#-999#D{id}.B#1#D{id}.INF`

---

## 2. Circuits connus

| Circuit | Pays | Ville | Long. | URL Live Timing | Port WS |
|---------|------|-------|-------|-----------------|---------|
| Karting de Saintes | France | Saintes | 0,9 km | `https://www.apex-timing.com/live-timing/karting-de-saintes/` | **8583** |
| Karting des Fagnes | Belgique | Mariembourg | 1,2 km | `https://www.apex-timing.com/live-timing/karting-mariembourg/` | **8313** |
| Karting de Genk | Belgique | Genk | 1,4 km | `https://www.apex-timing.com/live-timing/karting-genk/` | **8243** |
| Spa Francorchamps Karting | Belgique | Spa | 1,1 km | `https://live.apex-timing.com/spa-francorchamps-karting/` | **9723** |
| Karting Eupen | Belgique | Eupen | 1,0 km | `https://www.apex-timing.com/live-timing/karting-eupen/` | **8523** |
| MRK Agadir | Maroc | Agadir | 1,3 km | `https://www.apex-timing.com/live-timing/mrkagadir/` | **8023** |

> **Note Spa** : l'URL live timing utilise le sous-domaine `live.apex-timing.com` (pas `www`). Le header `Origin` de la connexion WebSocket doit correspondre.

> **Tous les ports sont désormais connus et fixés** — l'auto-découverte reste disponible en fallback mais n'est plus nécessaire pour ces circuits.

---

## 3. Gestion des karts et des stands

### Numéro de bib ≠ kart physique
- Le numéro visible (bib) est assigné à l'équipe, pas à la machine.
- Un kart physique est identifié par son propre label (ex. `K07`, `KA`).
- Quand une équipe rentre aux stands, son kart physique est retiré de la piste.
- Quand l'équipe repart, elle reçoit un autre kart physique — son bib reste inchangé.

### Files de réserve (FIFO)
- Les karts en réserve sont organisés en N files configurables.
- Quand un kart entre aux stands → il est ajouté à la file la moins chargée.
- Quand une équipe repart → elle prend le kart le plus ancien (premier entré, premier sorti) parmi ceux qui ont atteint le temps minimum de stand.
- Le bib de l'équipe est alors associé au nouveau kart physique.

### Paramètres configurables
| Paramètre | Description |
|-----------|-------------|
| `num_lanes` | Nombre de files de réserve |
| `karts_per_lane` | Karts de réserve par file |
| `min_pit_duration_s` | Durée minimum au stand (s) avant qu'un kart soit éligible |
| `min_relay_duration_s` | Durée minimum d'un relais (s) |
| `max_relay_duration_s` | Durée maximum d'un relais (s) |

---

## 4. Algorithme de ranking des karts

### Objectif
Déterminer si un kart est **bon** ou **mauvais** en isolation du niveau du pilote.

### Normalisation des conditions de piste
- Fenêtre glissante de 40 tours (tous pilotes confondus).
- Référence = moyenne des 25 % meilleurs temps dans la fenêtre.
- Chaque tour est normalisé : `ms / référence`.
- Cela élimine l'effet "gomme" (amélioration progressive des chronos au fil de la session).

### Baseline pilote
- Les tours réalisés avant le **premier arrêt aux stands** constituent la baseline de l'équipe.
- La baseline est **verrouillée définitivement** au moment où le premier pit stop est détecté.
- Baseline = médiane des tours normalisés sur le kart initial (≥ 5 tours requis).

### Delta kart
- `delta = moyenne(7 derniers tours normalisés sur kart actuel) - baseline`
- Valeur négative = kart plus rapide que la baseline du pilote.

### Niveaux de rating
| Niveau | Condition |
|--------|-----------|
| `GOOD` | delta < -1,2 % |
| `MEDIUM` | -1,2 % ≤ delta ≤ +1,5 % |
| `BAD` | delta > +1,5 % |
| `UNKNOWN` | confidence < 40 % (moins de 5 tours baseline OU moins de 3 tours sur le kart) |

### Confidence
- `confidence = min(nb_observations / 5, 1.0)` → 0–100 %
- Affiché à côté du badge de rating.

### Résumé réserve
- Pour les karts dans les files : pourcentage GOOD / MEDIUM / BAD / UNKNOWN affiché sous forme de barre colorée.

---

## 5. Type de session

| Type | Détection (titre) | Comportement |
|------|-------------------|--------------|
| `race` | "course", "race", "final", "finale", "heat", "endur" | Classement par position / nombre de tours |
| `qualifying` | "qualif", "qualify", "chrono", "essai" | Classement par meilleur temps (du plus rapide au plus lent) |
| `unknown` | aucun match | Fallback |

---

## 6. Gestion des événements

Chaque événement de course est configuré indépendamment et peut être activé pour écraser la config globale.

### Champs d'un événement
| Champ | Description |
|-------|-------------|
| `name` | Nom libre (ex. "24h Karting Saintes 2025") |
| `circuit_url` | URL Apex Timing du circuit |
| `ws_port_override` | Port WS forcé (0 = auto-découverte) |
| `event_date` | Date/heure de la course |
| `duration_hours` | Durée de la course (heures) |
| `min_pit_duration_s` | Temps minimum au stand |
| `min_relay_s` | Durée minimum d'un relais |
| `max_relay_s` | Durée maximum d'un relais |
| `num_lanes` | Nombre de files de réserve |
| `total_reserve_karts` | Nombre total de karts en réserve (répartis entre les files) |

### Activation d'un événement
- Copie les paramètres de l'événement dans la config active.
- `karts_per_lane = ceil(total_reserve_karts / num_lanes)`
- Arrête le client Apex actuel, remet l'état live à zéro, redémarre sur le nouveau circuit — **sans redémarrer le serveur**.
- Un seul événement peut être actif à la fois.

---

## 7. Multi-clients

- Plusieurs clients peuvent se connecter simultanément au backend via WebSocket `/ws`.
- Chaque client reçoit un snapshot complet à la connexion.
- Tous les événements (grid, pit_stop, connected, etc.) sont broadcastés à tous les clients connectés.
- Les connexions mortes sont nettoyées automatiquement.

---

## 8. Fonctionnalités UI

### Favoris
- Cliquer sur l'étoile d'une équipe (Live Timing ou Classement) la marque comme favori.
- Les équipes favorites apparaissent en surbrillance jaune et en tête du classement.
- Persisté dans `localStorage`.

### Classement (Standings)
- **Qualifications** : trié par meilleur tour, delta affiché par rapport au meilleur temps de la session (mis en violet).
- **Course** : trié par position.

### Classement des karts (Performance)
- Onglet dédié avec ranking GOOD → MEDIUM → BAD → UNKNOWN.
- Confiance et delta % affichés.

### Stands (Pit Lane)
- File d'attente FIFO par file, timer d'éligibilité visible.
- Badge de qualité sur chaque kart en réserve.
- Historique des arrêts aux stands.
- Résumé GOOD/MEDIUM/BAD/UNKNOWN de la réserve.

---

## 9. Déploiement

- Stack : **FastAPI** (Python) + **SQLite** + **React/TypeScript/Vite/Tailwind**.
- Proxy nginx devant le frontend (port 80/443), `/api` et `/ws` routés vers le backend.
- **Docker Compose** pour le dev/prod local.
- **K3s / Synology NAS** pour la cible de déploiement (fichier `stacks/synokrust/karting-live.yml`).
- Base de données persistée dans un volume Docker (`/data/karting.db`).
