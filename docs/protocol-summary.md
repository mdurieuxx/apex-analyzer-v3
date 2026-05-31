# Apex Timing — Synthèse des sources de données

## Sources disponibles

| Donnée | Source | Fréquence | Doc détaillée |
|---|---|---|---|
| Position, gap, intervalles | WebSocket live | ~1s | `ws-protocol-analysis.md` §4 |
| Nombre de tours, meilleur tour | WebSocket live | par tour | `ws-protocol-analysis.md` §4 |
| Secteurs (S1/S2/S3) | WebSocket live | par tour | `ws-protocol-analysis.md` §4 |
| Statut pit (in/out) | WebSocket live | détection delta | `ws-protocol-analysis.md` §8 |
| Compte à rebours, titre session | WebSocket live | dyn1 frames | `ws-protocol-analysis.md` §3 |
| Commentaires de course / pénalités | WebSocket live | `com\|\|` / `comments\|\|` | `ws-protocol-analysis.md` §3, `stats-api-protocol.md` §4 |
| Historique tours complet (tous pilotes) | HTTP `request.php` | à la demande | `stats-api-protocol.md` §3.3 |
| Historique pit stops (ordre, durées, relayeurs) | HTTP `request.php` | à la demande | `stats-api-protocol.md` §3.1 |
| Tours par pilote | HTTP `request.php` | calculé | `stats-api-protocol.md` §5 |
| Infos équipe (pilotes, kart, club) | HTTP `request.php` | à la demande | `stats-api-protocol.md` §3.1 |

---

## WebSocket — Rappel connexion

```
ws://{circuit_url}:{configPort}/timing
```

- Ne jamais envoyer de message après connexion (= déconnexion serveur Java)
- `configPort` = port WS **et** port API (même valeur, ex: `8600` à Brignoles)
- `grid||<html>` — deux pipes (pas `grid|html|`)
- `dyn1|countdown|N` — N en millisecondes

→ Détails complets : `ws-protocol-analysis.md`

---

## HTTP API — request.php

```
POST https://live-data.apex-timing.com/live-timing/commonv2/functions/request.php
Content-Type: application/x-www-form-urlencoded

port={configPort}&request={query}
```

**teamId** : extraire le `row_id` WS (ex: `r44387`) → `44387` (strip `r`)

### Requêtes clés

| Objectif | Requête |
|---|---|
| Tours récents (N derniers) | `D#-{N}#D{teamId}.L` |
| Tous les tours | `D#-{totalLaps+50}#D{teamId}.L` |
| Historique pit stops + pilotes | `D#-999#D{teamId}.P#1#D{teamId}.INF` |
| Meilleur tour + infos pilotes | `D#-30#D{teamId}.L#-999#D{teamId}.BL#1#D{teamId}.INF` |

**Important** : `port` = `configPort` directement (pas de décalage `-3`)

→ Détails complets, format des réponses, attribution tours/pilotes : `stats-api-protocol.md`

---

## Attribution tours → pilotes

Calculé côté client à partir des pit stops :

```python
# pit = {lap, relay_laps, driver_id}
# tours du pilote P = [prev_end_lap+1 .. prev_end_lap+relay_laps]
```

→ Algorithme complet avec implémentation Python : `stats-api-protocol.md` §5-6
