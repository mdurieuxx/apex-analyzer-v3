# Backlog — Karting Live (apex-analyzer-v3)

Fonctionnalités prévues post-release v1.0.0.

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

## Live Timing

### Classement virtuel — gap sur kart précédent
Le classement virtuel utilise actuellement le gap cumulatif depuis le leader.  
Il faudrait utiliser la colonne `gap` Apex (écart sur le kart directement devant) pour un calcul plus fidèle à la réalité piste — cela permet de simuler un dépassement kart par kart.

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
