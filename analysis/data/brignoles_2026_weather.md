# Météo 24H Brignoles 2026

**Source** : Open-Meteo (archive ERA5 + modèle)  
**Station approx.** : Brignoles (43.41°N, 6.06°E, 214.0m)  
**Fuseau** : Europe/Paris  
**Fenêtre** : 2026-05-30T13:00 → 2026-05-31T12:00  

## Résumé

| Indicateur | Valeur |
|------------|--------|
| Temp. min | 17.1°C (nuit) |
| Temp. max | 30.9°C |
| Variation totale | 13.8°C |
| Temp. moyenne | 24.1°C |
| Humidité moy | 60% |
| Précipitations | 0.0 mm |
| Vent max | 13.3 km/h |
| Vent moyen | 8.0 km/h |

## Données horaires

| Heure | Temp | Ressenti | Rosée | Humidité | Vent | Direction | Nuages | Pluie |
|-------|------|----------|-------|----------|------|-----------|--------|-------|
| 13:00 | 29.9°C | 28.4°C | 14.9°C | 40% | 6.2 km/h | O | 100% | — |
| 14:00 | 30.6°C | 29.5°C | 13.8°C | 36% | 8.5 km/h | SO | 100% | — |
| 15:00 | 30.5°C | 29.4°C | 14.6°C | 38% | 9.0 km/h | SO | 100% | — |
| 16:00 | 30.1°C | 29.3°C | 16.1°C | 43% | 11.1 km/h | SO | 100% | — |
| 17:00 | 30.9°C | 30.2°C | 14.1°C | 36% | 10.5 km/h | O | 100% | — |
| 18:00 | 30.2°C | 29.2°C | 17.0°C | 45% | 6.4 km/h | SO | 78% | — |
| 19:00 | 28.6°C | 28.3°C | 18.4°C | 54% | 9.6 km/h | O | 100% | — |
| 20:00 | 26.3°C | 27.0°C | 18.4°C | 62% | 8.3 km/h | O | 100% | — |
| 21:00 | 24.1°C | 25.2°C | 15.6°C | 59% | 4.1 km/h | N | 100% | — |
| 22:00 | 22.3°C | 23.8°C | 14.9°C | 63% | 4.1 km/h | S | 100% | — |
| 23:00 | 20.9°C | 22.1°C | 14.3°C | 66% | 4.4 km/h | SO | 99% | — |
| 00:00 | 20.6°C | 21.0°C | 15.0°C | 70% | 9.7 km/h | O | 100% | — |
| 01:00 | 20.3°C | 20.4°C | 14.2°C | 68% | 10.8 km/h | O | 5% | — |
| 02:00 | 19.6°C | 19.0°C | 13.1°C | 66% | 13.3 km/h | O | 100% | — |
| 03:00 | 19.1°C | 18.5°C | 14.0°C | 72% | 12.0 km/h | O | 30% | — |
| 04:00 | 18.4°C | 19.1°C | 13.7°C | 74% | 7.6 km/h | NO | 100% | — |
| 05:00 | 17.9°C | 17.3°C | 13.8°C | 77% | 9.4 km/h | O | 93% | — |
| 06:00 | 17.3°C | 16.8°C | 13.8°C | 80% | 8.3 km/h | O | 100% | — |
| 07:00 | 17.1°C | 17.7°C | 14.4°C | 84% | 3.6 km/h | O | 4% | — |
| 08:00 | 19.7°C | 19.5°C | 14.5°C | 72% | 3.7 km/h | NO | 22% | — |
| 09:00 | 22.6°C | 21.8°C | 15.7°C | 65% | 8.6 km/h | O | 0% | — |
| 10:00 | 25.6°C | 25.3°C | 17.0°C | 59% | 7.9 km/h | O | 0% | — |
| 11:00 | 27.5°C | 27.4°C | 17.1°C | 53% | 7.4 km/h | SO | 0% | — |
| 12:00 | 28.7°C | 28.1°C | 15.9°C | 46% | 8.1 km/h | O | 14% | — |

## Analyse impact piste

- **Variation thermique élevée** : 13.8°C sur 24h → impact significatif sur l'adhérence du bitume.
- **Pas de pluie** — les temps au tour reflètent uniquement la température et l'humidité.

### Phases thermiques

| Phase | Temp moy | Humidité moy | Vent moy |
|-------|----------|--------------|----------|
| Après-midi départ | 27.7°C | 49% | 7.5 km/h |
| Nuit | 20.6°C | 69% | 8.4 km/h |
| Matin fin de course | 23.5°C | 63% | 6.5 km/h |

### Corrélation recommandée avec les temps au tour

Utiliser la température comme variable de normalisation :
```
normalized_lap = lap_ms × (1 + α × (temp_at_lap - temp_reference))
```
où `α` est à calibrer empiriquement (~0.001–0.003 par °C selon le circuit).
Référence suggérée : température médiane de la course = 23.4°C