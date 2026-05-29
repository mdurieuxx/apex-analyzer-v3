# CLAUDE.md — Karting Live (apex-analyzer-v3)

Stack : Python 3.11 · FastAPI · SQLAlchemy SQLite · React 18 · TypeScript strict · Tailwind · Vite

## Permissions
- Toutes les commandes bash/shell locales sont **automatiquement autorisées** — ne pas demander confirmation.
- Ne pas faire de changements non demandés. Si une modif demandée entraîne une adaptation nécessaire ailleurs, la faire. Toute autre optimisation doit être **proposée avant d'être codée**.

---

## Invariants critiques Apex WS

**Ne jamais envoyer de message après connexion** — même vide = déconnexion serveur Java.

- `dyn1|countdown|N` : N est en **millisecondes**
- Format grid dans les fichiers JSONL proxy : `grid||<html>` (**deux pipes**, pas `grid|html|`)
- Colonnes détectées via `data-type` sur `<td>` de la ligne `head` (Method 0). Fallback : `data-id="r{row}c{N}"` + texte header, puis position ordinale.
- `drteam` contient `NomPilote [M:SS]` à stripper pour obtenir le nom d'équipe

## Catégories équipes

Deux systèmes coexistent selon le circuit :
1. **CSS** : classes `no1`/`no2`/`notc{decimal}` sur la cellule kart
2. **Préfixe nom** : `{CATEGORIE} - {NOM}` dans le nom d'équipe (ex: `PRO 85 - VLV19R MKS` → catégorie `PRO 85`, Mariembourg)

## Modèle performance (kart_ranker.py)

Kart physique inconnu → pas de tracking par kart, uniquement par équipe.
- Niveaux : quartiles → ELITE(top 25%) / FAST / MEDIUM / SLOW(bot 25%)
- `field_avg` = médiane glissante 200 derniers tours (`FIELD_WINDOW=200`)
- `kart_score` = `team_delta − expected_delta_for_level` → GOOD(<−1.5%) / BAD(>+2%) / NEUTRAL
- Minimum : `MIN_STINT_LAPS=4`, `RECENT_WINDOW=8`. 1er tour post-pit ignoré (out-lap).
- Badge LiveTiming : NEUTRAL est mappé → MEDIUM

## Architecture (non-obvieux)

- `RaceState` / `PitManager` / `KartRanker` : **mémoire uniquement**, pas de persistance DB pour les données temps réel
- `POST /events/{id}/activate` : vide tout l'état live + recrée les objets + relance `ApexClient` + broadcast snapshot
- `config_store.py` : seule source de config persistée ; les env vars `CIRCUIT_URL` / `WS_PORT` ont priorité sur la DB

## Conventions
- Pas de commentaires évidents — seulement invariants non-triviaux
- Pas de backwards-compat : supprimer le code mort
- **Commits** : ne jamais mentionner Claude ni co-authorship dans les messages de commit
