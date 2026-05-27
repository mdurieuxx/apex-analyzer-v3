# Backlog — Karting Live (apex-analyzer-v3)

Fonctionnalités prévues post-release v1.0.0.

---

## ⚡ Priorité haute

### Source unique des circuits — SQLite partagée
Les circuits sont actuellement hardcodés en trois endroits indépendants :
- `proxy/app/main.py` → `KNOWN_CIRCUITS`
- `backend/app/models.py` → `CIRCUIT_PRESETS`
- Frontend : seulement via l'API `/api/circuits`

**Solution retenue : SQLite partagée.**
1. Déplacer les `CIRCUIT_PRESETS` du backend dans la table `Circuit` (seed au démarrage si vide)
2. Monter le même volume DB (`/data/karting.db`) dans les deux conteneurs
3. Le proxy lit la table `circuits` avec `sqlite3` (stdlib, zéro dep) au démarrage — lecture seule, pas de conflit avec le backend
4. Le frontend consomme `/api/circuits` comme maintenant

Le proxy reste autonome (lecture locale, pas de dépendance réseau vers le backend). L'édition se fait via la page Circuits du frontend.

---

## Proxy

### Multi-recording (mode mixte)
Permettre de faire simultanément :
1. Un relais **live diffusé** aux clients connectés (mode actuel)
2. **L'enregistrement** de ce même circuit live
3. **N enregistrements silencieux** d'autres circuits en arrière-plan (sans diffusion)

La base existe avec `bg_recordings` mais elle est séparée du mode live. Il faut unifier les deux : live broadcast + record du live + N bg records indépendants, tous pilotables indépendamment via l'UI.

### Circuits groupés par pays
Dans les dropdowns du proxy et de l'app, regrouper les circuits par pays (`<optgroup>`).  
Nécessite d'enrichir `KNOWN_CIRCUITS` (proxy) et `CIRCUIT_PRESETS` (backend) avec un champ `country` — la plupart des circuits découverts ne l'ont pas encore.  
Voir `docs/apex-circuits-inventory.md` pour la liste complète des circuits.

### Support multi-hôtes WS Apex
`client.py` hardcode `www.apex-timing.com`. Certains circuits sont sur `live-data.apex-timing.com` ou `live.apex-timing.com`.  
- Lire `configHost` depuis `javascript/config.js` dans `port_discovery.py`
- Tenter les deux hôtes en fallback dans `client.py`

---

### Fusion de fichiers d'enregistrement — événement fragmenté

Quand le proxy se déconnecte/reconnecte pendant un événement, plusieurs fichiers JSONL sont créés alors qu'il s'agit d'une seule course. Il faut pouvoir les fusionner en un seul fichier et traiter l'événement comme une unité cohérente dans le backend.

**Identification d'un événement** : exploiter un maximum de métadonnées extraites du flux Apex pour identifier à quelle course appartient chaque fichier :

*Métadonnées de fichier (proxy) :*
- Circuit URL / slug
- Timestamp premier et dernier message (début/fin réelle de capture)
- Durée totale couverte

*Métadonnées extraites du flux Apex :*
- `title1` / `title2` — nom de la session/épreuve (ex : "24h Karting Mariembourg", "Sprint Cat1") → comparaison textuelle
- `dyn1|countdown|N` — compte à rebours : permet de savoir si la course était déjà en cours à la reconnexion (même compteur = même course)
- Numéros de karts présents dans la grille (`grid|html|...`) — la composition de la grille doit être identique ou très proche entre deux fragments du même événement
- Noms d'équipes (`drteam`) — même ensemble d'équipes = fort signal de même événement
- Numéros de position/karts/tours : si le fragment B commence avec des données cohérentes avec la fin du fragment A (ex : même leaders, tours > ceux du fragment A), c'est le même événement
- Meilleur tour session (`tb`/`sb`/`best`) : le meilleur tour absolu ne peut que baisser ou rester stable — si le fragment B a un meilleur tour > fragment A, c'est une nouvelle session

*Critères de matching (ordre de priorité) :*
1. Même circuit URL
2. `title1` + `title2` identiques (ou très proches — distance Levenshtein)
3. Composition de grille compatible (≥ 80% de karts communs)
4. Continuité temporelle : gap entre fin A et début B < 30 min
5. Cohérence du compteur de tours (tours du fragment B ≥ tours fin fragment A)
6. Cohérence du meilleur tour (best_lap fragment B ≤ best_lap fragment A)

Un score de confiance peut être calculé : tous les critères → fusion automatique proposée ; critères partiels → fusion manuelle avec avertissement.

**Ce qu'il faut implémenter :**
1. **Outil de détection** : scanner un dossier de fichiers JSONL et regrouper automatiquement ceux qui appartiennent au même événement (même circuit, même plage horaire)
2. **Outil de fusion** : merger N fichiers JSONL triés chronologiquement en un seul, en dédupliquant les messages redondants à la jonction (ex : le `grid|html|...` de reconnexion remplace l'état précédent — à gérer proprement)
3. **UI dans le proxy** : afficher les groupes détectés, proposer la fusion, nommer le fichier résultant
4. **Backend** : importer un fichier fusionné comme un seul événement (déjà possible via replay, mais à vérifier que les jonctions ne cassent pas l'état RaceState)

---

## Live Timing

### Catégories depuis le préfixe du nom d'équipe

Certains circuits (ex : Mariembourg) encodent la catégorie directement dans le nom d'équipe sous la forme `{CATEGORIE} - {NOM}` :
- `PRO 85 - VLV19R MKS` → catégorie `PRO 85`
- `AM 75 - A.D.S_BY_FASTCAR` → catégorie `AM 75`
- `AM 85 - GKD COMPETIZIONE` → catégorie `AM 85`

Ce préfixe (tout ce qui précède le premier ` - `) est la catégorie réelle de l'équipe. Il faut :

1. **Extraction** : détecter ce pattern dans `grid_parser.py` — si le nom d'équipe contient ` - `, extraire le préfixe comme `category` et le reste comme `team_name` affiché
2. **Filtres** : utiliser ces catégories extraites dans `CategoryFilter` au même titre que les catégories CSS (`no1`/`no2`/`notc`) — elles peuvent coexister selon le circuit
3. **Affichage** : le badge catégorie (`CategoryBadge.tsx`) doit afficher le libellé texte (`PRO 85`, `AM 75`…) en plus ou à la place de la couleur CSS quand le préfixe est disponible
4. **Classement** : les classements et le live timing doivent pouvoir filtrer/grouper par catégorie préfixe

Note : la couleur CSS et le préfixe texte peuvent tous deux être présents (ex : Mariembourg a des `notc{n}` ET des préfixes). Priorité d'affichage à définir.

---

### Classement virtuel — gap sur kart précédent
Le classement virtuel utilise actuellement le gap cumulatif depuis le leader.  
Il faudrait utiliser la colonne `gap` Apex (écart sur le kart directement devant) pour un calcul plus fidèle à la réalité piste — cela permet de simuler un dépassement kart par kart.

---

## Intégrations externes

### Sodiworld Series
Intégrer des données depuis https://www.sodiwseries.com/ — récupérer les événements, calendriers et autres infos pertinentes du site.
À investiguer : quelles données sont disponibles (API, scraping, RSS ?), ce qui est utile pour l'app (events, circuits, résultats...).

---

## Circuits à ajouter

Découverts lors de l'investigation du 2026-05-26 (voir `docs/apex-circuits-inventory.md`).  
À intégrer dans `CIRCUIT_PRESETS` (backend) et `KNOWN_CIRCUITS` (proxy) :

| Slug | Nom | URL | WS port |
|------|-----|-----|---------|
| lemans-karting2 | ACO Le Mans Karting 2 | https://www.apex-timing.com/live-timing/lemans-karting2/ | 8013 |
| circuit-europe | Circuit de l'Europe | https://www.apex-timing.com/live-timing/circuit-europe/ | 8203 |
| cornwall-karting | Cornwall Karting | https://www.apex-timing.com/live-timing/cornwall-karting/ | 8593 |
| karting-45 | Karting 45 | https://www.apex-timing.com/live-timing/karting-45/ | 8373 |
| wik | Wavre Indoor Karting | https://www.apex-timing.com/live-timing/wik/ | 8553 |
| paris-kart | Paris Kart Indoor | https://www.apex-timing.com/live-timing/paris-kart/ | 8213 |
| circuitpaulricardkarting | Circuit Paul Ricard Karting | https://www.apex-timing.com/live-timing/circuitpaulricardkarting/ | 7923 |
| rkc | Racing Kart Cormeilles | https://www.apex-timing.com/live-timing/rkc/ | 7913 |
| capkarting | Circuit de Bresse | https://www.apex-timing.com/live-timing/capkarting/ | 7953 |
| ckbesancon | CKB Besançon | https://live.apex-timing.com/ckbesancon/ | 9643 |
| onlykart | Onlykart | https://live.apex-timing.com/onlykart/ | 9323 |
| kartplanet | Kart Planet | https://live.apex-timing.com/kartplanet/ | 10223 |
| karting-sevilla | Karting Sevilla | https://live.apex-timing.com/karting-sevilla/ | 9863 |
