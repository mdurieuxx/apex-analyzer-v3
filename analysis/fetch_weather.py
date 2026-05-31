#!/usr/bin/env python3
"""
Récupère les données météo pour une course depuis Open-Meteo (gratuit, sans clé API).
Génère un JSON brut et un rapport markdown.

Usage:
    python fetch_weather.py --lat 43.4067 --lon 6.0608 \
        --start "2026-05-30T13:00" --end "2026-05-31T14:00" \
        --timezone "Europe/Paris" \
        --output data/brignoles_2026_weather.json \
        --report data/brignoles_2026_weather.md
"""
import argparse
import json
import statistics
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    import urllib.request, urllib.parse
    class _requests:
        @staticmethod
        def get(url, timeout=20):
            with urllib.request.urlopen(url, timeout=timeout) as r:
                class _r:
                    text = r.read().decode()
                    def json(self): return json.loads(self.text)
                    def raise_for_status(self): pass
                return _r()
    requests = _requests()

API_URL = "https://api.open-meteo.com/v1/forecast"

VARIABLES = [
    "temperature_2m",
    "apparent_temperature",
    "dewpoint_2m",
    "precipitation",
    "rain",
    "windspeed_10m",
    "winddirection_10m",
    "relativehumidity_2m",
    "cloudcover",
    "surface_pressure",
    "visibility",
]


def fetch_weather(lat: float, lon: float, timezone: str) -> dict:
    params = {
        "latitude":     lat,
        "longitude":    lon,
        "hourly":       ",".join(VARIABLES),
        "past_days":    3,
        "forecast_days": 1,
        "timezone":     timezone,
    }
    url = API_URL + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()


def extract_window(data: dict, start: str, end: str) -> list[dict]:
    h = data["hourly"]
    rows = []
    for i, t in enumerate(h["time"]):
        if start <= t <= end:
            rows.append({
                "time":              t,
                "temp_c":            h["temperature_2m"][i],
                "apparent_temp_c":   h["apparent_temperature"][i],
                "dewpoint_c":        h["dewpoint_2m"][i],
                "precipitation_mm":  h["precipitation"][i],
                "rain_mm":           h["rain"][i],
                "wind_kmh":          h["windspeed_10m"][i],
                "wind_dir_deg":      h["winddirection_10m"][i],
                "humidity_pct":      h["relativehumidity_2m"][i],
                "cloudcover_pct":    h["cloudcover"][i],
                "pressure_hpa":      h["surface_pressure"][i],
            })
    return rows


def wind_direction(deg: float) -> str:
    dirs = ["N","NE","E","SE","S","SO","O","NO"]
    return dirs[round(deg / 45) % 8]


def generate_report(rows: list[dict], meta: dict) -> str:
    temps = [r["temp_c"] for r in rows]
    humids = [r["humidity_pct"] for r in rows]
    total_rain = sum(r["rain_mm"] for r in rows)
    winds = [r["wind_kmh"] for r in rows]

    lines = []
    lines.append(f"# Météo 24H Brignoles 2026")
    lines.append("")
    lines.append(f"**Source** : Open-Meteo (archive ERA5 + modèle)  ")
    lines.append(f"**Station approx.** : Brignoles (43.41°N, 6.06°E, {meta.get('elevation','?')}m)  ")
    lines.append(f"**Fuseau** : {meta.get('timezone','?')}  ")
    lines.append(f"**Fenêtre** : {rows[0]['time']} → {rows[-1]['time']}  ")
    lines.append("")
    lines.append("## Résumé")
    lines.append("")
    lines.append(f"| Indicateur | Valeur |")
    lines.append(f"|------------|--------|")
    lines.append(f"| Temp. min | {min(temps):.1f}°C (nuit) |")
    lines.append(f"| Temp. max | {max(temps):.1f}°C |")
    lines.append(f"| Variation totale | {max(temps)-min(temps):.1f}°C |")
    lines.append(f"| Temp. moyenne | {statistics.mean(temps):.1f}°C |")
    lines.append(f"| Humidité moy | {statistics.mean(humids):.0f}% |")
    lines.append(f"| Précipitations | {total_rain:.1f} mm |")
    lines.append(f"| Vent max | {max(winds):.1f} km/h |")
    lines.append(f"| Vent moyen | {statistics.mean(winds):.1f} km/h |")
    lines.append("")
    lines.append("## Données horaires")
    lines.append("")
    lines.append("| Heure | Temp | Ressenti | Rosée | Humidité | Vent | Direction | Nuages | Pluie |")
    lines.append("|-------|------|----------|-------|----------|------|-----------|--------|-------|")

    for r in rows:
        rain_str = f"**{r['rain_mm']:.1f}mm**" if r["rain_mm"] > 0 else "—"
        lines.append(
            f"| {r['time'][11:]} "
            f"| {r['temp_c']:.1f}°C "
            f"| {r['apparent_temp_c']:.1f}°C "
            f"| {r['dewpoint_c']:.1f}°C "
            f"| {r['humidity_pct']:.0f}% "
            f"| {r['wind_kmh']:.1f} km/h "
            f"| {wind_direction(r['wind_dir_deg'])} "
            f"| {r['cloudcover_pct']:.0f}% "
            f"| {rain_str} |"
        )

    lines.append("")
    lines.append("## Analyse impact piste")
    lines.append("")

    temp_range = max(temps) - min(temps)
    if temp_range > 10:
        lines.append(f"- **Variation thermique élevée** : {temp_range:.1f}°C sur 24h → impact significatif sur l'adhérence du bitume.")
    if total_rain > 0:
        lines.append(f"- **Pluie détectée** : {total_rain:.1f}mm — les tours sous pluie sont à exclure ou flagguer dans l'analyse de performance.")
    else:
        lines.append("- **Pas de pluie** — les temps au tour reflètent uniquement la température et l'humidité.")

    # segment by phase
    phases = [
        ("Après-midi départ (13h-19h)", [r for r in rows if "T13" <= r["time"][11:] <= "T19" or r["time"][:10] == rows[0]["time"][:10] and r["time"][11:] >= "13:00"]),
        ("Nuit (20h-06h)", [r for r in rows if r["time"][11:] >= "20:00" or r["time"][11:] <= "06:00"]),
        ("Matin fin de course (07h-13h)", [r for r in rows if "07:00" <= r["time"][11:] <= "13:00" and r["time"][:10] == rows[-1]["time"][:10]]),
    ]
    # simpler
    d0 = rows[0]["time"][:10]
    d1 = rows[-1]["time"][:10]
    phases = [
        ("Après-midi départ",  [r for r in rows if r["time"][:10] == d0 and r["time"][11:] >= "13:00"]),
        ("Nuit",               [r for r in rows if (r["time"][:10] == d0 and r["time"][11:] >= "20:00") or (r["time"][:10] == d1 and r["time"][11:] < "07:00")]),
        ("Matin fin de course",[r for r in rows if r["time"][:10] == d1 and "07:00" <= r["time"][11:] <= "13:00"]),
    ]
    lines.append("")
    lines.append("### Phases thermiques")
    lines.append("")
    lines.append("| Phase | Temp moy | Humidité moy | Vent moy |")
    lines.append("|-------|----------|--------------|----------|")
    for name, phase_rows in phases:
        if not phase_rows:
            continue
        t_mean = statistics.mean(r["temp_c"] for r in phase_rows)
        h_mean = statistics.mean(r["humidity_pct"] for r in phase_rows)
        w_mean = statistics.mean(r["wind_kmh"] for r in phase_rows)
        lines.append(f"| {name} | {t_mean:.1f}°C | {h_mean:.0f}% | {w_mean:.1f} km/h |")

    lines.append("")
    lines.append("### Corrélation recommandée avec les temps au tour")
    lines.append("")
    lines.append("Utiliser la température comme variable de normalisation :")
    lines.append("```")
    lines.append("normalized_lap = lap_ms × (1 + α × (temp_at_lap - temp_reference))")
    lines.append("```")
    lines.append("où `α` est à calibrer empiriquement (~0.001–0.003 par °C selon le circuit).")
    lines.append("Référence suggérée : température médiane de la course = "
                 f"{statistics.median(temps):.1f}°C")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lat",      type=float, default=43.4067)
    parser.add_argument("--lon",      type=float, default=6.0608)
    now_local = datetime.now().strftime("%Y-%m-%dT%H:00")
    parser.add_argument("--start",    default="2026-05-30T13:00")
    parser.add_argument("--end",      default=now_local)
    parser.add_argument("--timezone", default="Europe/Paris")
    parser.add_argument("--output",   default="analysis/data/brignoles_2026_weather.json")
    parser.add_argument("--report",   default="analysis/data/brignoles_2026_weather.md")
    args = parser.parse_args()

    import os; os.makedirs(os.path.dirname(args.output), exist_ok=True)

    print(f"Fetching weather from Open-Meteo ({args.lat}, {args.lon})...")
    raw = fetch_weather(args.lat, args.lon, args.timezone)

    rows = extract_window(raw, args.start, args.end)
    print(f"  {len(rows)} hours in window {args.start} → {args.end}")

    snapshot = {
        "meta": {
            "source":       "open-meteo.com",
            "latitude":     raw["latitude"],
            "longitude":    raw["longitude"],
            "elevation":    raw.get("elevation"),
            "timezone":     raw["timezone"],
            "captured_at":  datetime.now(timezone.utc).isoformat(),
            "race_window":  {"start": args.start, "end": args.end},
        },
        "hourly": rows,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print(f"  JSON → {args.output}")

    report = generate_report(rows, {"elevation": raw.get("elevation"), "timezone": raw["timezone"]})
    with open(args.report, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  MD   → {args.report}")


if __name__ == "__main__":
    main()
