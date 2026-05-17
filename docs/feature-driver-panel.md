# Feature : Panel détail équipe au clic

## Objectif

Clic sur une ligne dans LiveTiming ou Standings → panneau latéral coulissant avec le détail complet de l'équipe.

---

## Données disponibles

Endpoint existant : `GET /api/driver/{driver_id}/laps`

```typescript
{
  driver_info: {
    team: string
    kart: string
    club: string
    drivers: { id: string; num: string; name: string; current: boolean }[]
  }
  laps: {
    lap_number: number
    s1_ms: number; s1_best: boolean
    s2_ms: number; s2_best: boolean
    s3_ms: number; s3_best: boolean
    total_ms: number; total_best: boolean
    is_pit: boolean
  }[]
  best_lap:     { s1_ms: number; s2_ms: number; s3_ms: number; total_ms: number }
  best_sectors: { s1_ms: number; s2_ms: number; s3_ms: number }  // théorique
}
```

`api.driverLaps(driver_id)` existe déjà dans `frontend/src/api/client.ts`.

---

## UI — Panel latéral coulissant

- Overlay sombre derrière (clic dessus = ferme)
- Panel fixe à droite, largeur ~420px (full width mobile)
- Fermeture : bouton ✕ ou Escape
- Chargement spinner pendant le fetch

### Sections du panel

#### 1. Header
- Nom équipe + numéro de kart (#bib)
- Badge niveau équipe (ELITE/FAST/MEDIUM/SLOW) si disponible depuis `kart_rating`
- Badge kart quality (GOOD/NEUTRAL/BAD)
- Bouton favori ⭐

#### 2. Pilotes du relais
- Liste des drivers de `driver_info.drivers`
- Pilote actuel mis en évidence (badge "En piste")

#### 3. Graphique évolution des tours
- `recharts` LineChart (déjà dans le projet)
- X = numéro de tour, Y = total_ms converti en secondes
- Tours pit exclus du tracé (point gris à part)
- Référence horizontale = best lap de l'équipe
- Tooltip au survol avec temps formaté

#### 4. Meilleurs temps
| | S1 | S2 | S3 | Total |
|---|---|---|---|---|
| Meilleur tour | 18.4 | 22.1 | 19.5 | 1:00.0 |
| Théorique | 18.2 | 21.8 | 19.4 | 59.4 |

#### 5. Tableau historique des tours
- Colonnes : Tour / S1 / S2 / S3 / Total
- Tri décroissant (dernier tour en premier)
- Secteur violet si `s*_best = true`
- Ligne grisée + label "PIT" si `is_pit = true`
- Max ~50 derniers tours affichés

---

## Fichiers à créer / modifier

| Fichier | Action |
|---|---|
| `frontend/src/components/DriverPanel.tsx` | Nouveau — le panel complet |
| `frontend/src/pages/LiveTiming.tsx` | Ajouter `onClick` sur les lignes + state `selectedDriverId` |
| `frontend/src/pages/Standings.tsx` | Idem |
| `frontend/src/types.ts` | Ajouter `DriverLapDetail`, `LapRecord`, `DriverInfo` |

---

## État local à gérer

```typescript
const [selectedDriverId, setSelectedDriverId] = useState<string | null>(null)
// null = panel fermé
```

Le panel est monté dans le layout au-dessus du tableau, conditionnel sur `selectedDriverId !== null`.

---

## Notes d'implémentation

- Le fetch se fait à l'ouverture du panel (pas au hover)
- Pas de polling — données figées au moment du clic (snapshot historique)
- Si `laps` vide → message "Pas encore de données"
- `fmtMs(ms)` existe déjà dans `Standings.tsx`, à extraire dans un util partagé
- Sur mobile : panel full-screen avec back button
- Le graphique ne montre que les tours valides (`!is_pit && total_ms > 0`)
