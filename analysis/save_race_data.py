#!/usr/bin/env python3
"""
Sauvegarde les données hors-WebSocket depuis l'API Apex Timing :
  - Pilotes par équipe (.INF) — non disponibles dans le flux WS
  - Pit stops avec durées exactes et attribution pilote (.P) — complémente le WS

Le flux WS complet (tours, positions, temps réel) est capturé séparément par le proxy JSONL.

Usage:
    python save_race_data.py --port 8600 --backend https://apex-analyzer.durdur.eu --output data/brignoles_2026_api.json
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import requests

BASE_URL = "https://live-data.apex-timing.com/live-timing/commonv2/functions/request.php"


def api_request(port: int, query: str) -> str:
    r = requests.post(BASE_URL, data={"port": port, "request": query}, timeout=20)
    r.raise_for_status()
    return r.text


def get_grid(backend_url: str) -> list[dict]:
    r = requests.get(f"{backend_url}/api/grid", timeout=10)
    r.raise_for_status()
    return r.json()["drivers"]


def toint(v: str) -> int:
    return int(v) if v and v.strip() else 0


def fetch_team(port: int, team_id: str) -> dict | None:
    """Pilotes + pit stops (1 appel) + tous les tours (2 appels)."""
    try:
        # pilotes + pits
        raw = api_request(port, f"D#-999#D{team_id}.P#1#D{team_id}.INF")
        pits = []
        drivers = {}
        for line in raw.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            if re.match(rf'D{team_id}\.P\d+#', line):
                after = line.split('#', 1)[1]
                p = after.split('|')
                if len(p) >= 9:
                    pits.append({
                        'pit_n':           toint(p[0]),
                        'lap':             toint(p[1]),
                        'in_ms':           toint(p[2]),
                        'out_ms':          toint(p[3]),
                        'pit_duration_ms': toint(p[4]),
                        'track_ms':        toint(p[5]),
                        'relay_laps':      toint(p[6]),
                        'driver_id':       p[7].strip(),
                        'driver_total_ms': toint(p[8]),
                    })
            elif f'D{team_id}.INF#' in line:
                xml_str = line.split('.INF#', 1)[1]
                try:
                    root = ET.fromstring(xml_str)
                    for d in root.findall('driver'):
                        drivers[d.get('id')] = {
                            'id':      d.get('id'),
                            'num':     d.get('num'),
                            'name':    d.get('name', '?'),
                            'color':   d.get('color', ''),
                            'current': d.get('current') == '1',
                        }
                except ET.ParseError:
                    pass
        pits.sort(key=lambda x: x['pit_n'])

        # total tours + meilleur
        raw_count = api_request(port, f"D#-1#D{team_id}.L")
        m = re.search(r'\.L(\d+)#\|\|\|(\d+)', raw_count)
        total_laps = int(m.group(1)) if m else 0
        best_lap_ms = int(m.group(2)) if m else 0

        # tous les tours
        laps = []
        if total_laps > 0:
            raw_laps = api_request(port, f"D#-{total_laps + 50}#D{team_id}.L")
            for line in raw_laps.strip().split('\n'):
                lm = re.match(rf'D{team_id}\.L(\d+)#\|\|\|(\d+)', line.strip())
                if lm:
                    laps.append({'lap': int(lm.group(1)), 'lap_ms': int(lm.group(2))})
            laps.sort(key=lambda x: x['lap'])

        return {'drivers': drivers, 'pits': pits, 'laps': laps,
                'total_laps': total_laps, 'best_lap_ms': best_lap_ms}

    except Exception as e:
        print(f"  [WARN] team {team_id}: {e}", file=sys.stderr)
        return None


WEATHER_API = "https://api.open-meteo.com/v1/forecast"
WEATHER_VARS = "temperature_2m,apparent_temperature,precipitation,rain,windspeed_10m,relativehumidity_2m,cloudcover"


def fetch_weather_now(lat: float, lon: float, tz: str = "Europe/Paris") -> dict | None:
    try:
        url = (f"{WEATHER_API}?latitude={lat}&longitude={lon}"
               f"&current={WEATHER_VARS}&timezone={tz}")
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json().get("current", {})
    except Exception as e:
        print(f"  [WARN] weather: {e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',       type=int, default=8600)
    parser.add_argument('--backend',    default='https://apex-analyzer.durdur.eu')
    parser.add_argument('--output',     default='analysis/data/brignoles_2026_api.json')
    parser.add_argument('--event',      default='24H Brignoles 2026')
    parser.add_argument('--lat',        type=float, default=43.4067)
    parser.add_argument('--lon',        type=float, default=6.0608)
    args = parser.parse_args()

    import os; os.makedirs(os.path.dirname(args.output), exist_ok=True)

    print(f"Fetching grid from {args.backend}...")
    grid = get_grid(args.backend)
    print(f"  {len(grid)} teams")

    teams_data = {}
    for i, g in enumerate(grid):
        tid = g['driver_id']
        print(f"  [{i+1}/{len(grid)}] {g.get('team','?')} ({tid})...", end=' ', flush=True)
        data = fetch_team(args.port, tid)
        if data:
            teams_data[tid] = data
            print(f"{data['total_laps']} laps, {len(data['pits'])} pits, {len(data['drivers'])} drivers")
        else:
            print("FAILED")
        time.sleep(0.1)

    snapshot = {
        'meta': {
            'event':       args.event,
            'circuit':     'brignoles-karting-loisir',
            'api_port':    args.port,
            'captured_at': datetime.now(timezone.utc).isoformat(),
            'note':        'Snapshot API complet : pilotes, pit stops, et tous les tours. Complément nominatif au JSONL proxy.',
            'teams_count': len(grid),
            'ok_count':    len(teams_data),
        },
        'grid': grid,
        'teams': teams_data,
    }

    print(f"\nFetching current weather ({args.lat}, {args.lon})...")
    weather = fetch_weather_now(args.lat, args.lon)
    if weather:
        print(f"  {weather.get('temperature_2m')}°C  humidity={weather.get('relativehumidity_2m')}%  rain={weather.get('rain')}mm  wind={weather.get('windspeed_10m')}km/h")
    snapshot['weather_at_capture'] = weather

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    total_laps = sum(v['total_laps'] for v in teams_data.values())
    total_pits = sum(len(v['pits']) for v in teams_data.values())
    total_drivers = sum(len(v['drivers']) for v in teams_data.values())
    print(f"\nSaved → {args.output}")
    print(f"  {len(teams_data)}/{len(grid)} teams  |  {total_laps:,} laps  |  {total_pits} pits  |  {total_drivers} drivers")
    print(f"  Captured at: {snapshot['meta']['captured_at']}")


if __name__ == '__main__':
    main()
