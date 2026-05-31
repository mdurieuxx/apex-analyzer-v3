#!/usr/bin/env python3
"""
Fetch stats from Apex Timing HTTP API for a live race.
Generates a markdown report with per-team and per-driver stats.

Usage:
    python fetch_race_stats.py --port 8600 --backend https://apex-analyzer.durdur.eu --output report.md
"""
import argparse
import re
import sys
import time
import statistics
from datetime import datetime
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


def fetch_team_data(port: int, team_id: str) -> dict | None:
    try:
        # Step 1: drivers + pit stops
        raw_pits = api_request(port, f"D#-999#D{team_id}.P#1#D{team_id}.INF")
        drivers, pits = parse_pits_and_inf(raw_pits, team_id)

        # Step 2: lap count + best lap
        raw_count = api_request(port, f"D#-1#D{team_id}.L")
        m = re.search(r'\.L(\d+)#\|\|\|(\d+)', raw_count)
        if not m:
            return None
        total_laps = int(m.group(1))
        best_lap_ms = int(m.group(2))

        # Step 3: all laps
        raw_laps = api_request(port, f"D#-{total_laps + 50}#D{team_id}.L")
        laps = parse_laps(raw_laps, team_id)

        # Step 4: laps per driver
        per_driver = get_laps_per_driver(pits, laps, drivers)

        return {
            "team_id": team_id,
            "drivers": drivers,
            "pits": pits,
            "laps": laps,
            "per_driver": per_driver,
            "total_laps": total_laps,
            "best_lap_ms": best_lap_ms,
        }
    except Exception as e:
        print(f"  [WARN] team {team_id}: {e}", file=sys.stderr)
        return None


def parse_pits_and_inf(raw: str, team_id: str) -> tuple[dict, list]:
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
                def toint(v): return int(v) if v.strip() else 0
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
    return drivers, pits


def parse_laps(raw: str, team_id: str) -> list[dict]:
    laps = []
    for line in raw.strip().split('\n'):
        m = re.match(rf'D{team_id}\.L(\d+)#\|\|\|(\d+)', line.strip())
        if m:
            laps.append({'lap': int(m.group(1)), 'lap_ms': int(m.group(2))})
    laps.sort(key=lambda x: x['lap'])
    return laps


def get_laps_per_driver(pits: list, laps: list, drivers: dict) -> dict:
    laps_dict = {l['lap']: l['lap_ms'] for l in laps}
    result: dict[str, list] = {}
    prev_lap = 0
    for pit in sorted(pits, key=lambda p: p['pit_n']):
        driver_id = pit['driver_id']
        stint_start = prev_lap + 1
        stint_end = pit['lap']
        driver_laps = result.setdefault(driver_id, [])
        for lap_n in range(stint_start, stint_end + 1):
            if lap_n in laps_dict:
                driver_laps.append({'lap': lap_n, 'lap_ms': laps_dict[lap_n]})
        prev_lap = stint_end
    # current stint
    current_driver_id = next((did for did, d in drivers.items() if d.get('current')), None)
    if current_driver_id and pits:
        current_laps = result.setdefault(current_driver_id, [])
        last_pit_lap = max(p['lap'] for p in pits)
        for lap_n in sorted(laps_dict):
            if lap_n > last_pit_lap:
                current_laps.append({'lap': lap_n, 'lap_ms': laps_dict[lap_n]})
    return result


def ms_to_str(ms: int) -> str:
    if ms <= 0:
        return "—"
    mins = ms // 60000
    secs = (ms % 60000) / 1000
    if mins > 60:
        h = mins // 60
        m = mins % 60
        return f"{h}h{m:02d}m{secs:05.2f}s"
    return f"{mins}:{secs:06.3f}"


def pit_ms_to_str(ms: int) -> str:
    secs = ms / 1000
    m = int(secs) // 60
    s = secs % 60
    if m:
        return f"{m}m{s:05.2f}s"
    return f"{s:.2f}s"


def compute_driver_stats(driver_laps: list[dict]) -> dict:
    times = [l['lap_ms'] for l in driver_laps if l['lap_ms'] > 30000]  # exclude outlaps <30s
    if not times:
        return {}
    best = min(times)
    med = statistics.median(times)
    cv = (statistics.stdev(times) / med * 100) if len(times) > 1 else 0
    return {'best': best, 'median': med, 'cv': cv, 'count': len(times)}


def generate_report(grid: list[dict], stats: dict[str, dict], port: int) -> str:
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    lines = []
    lines.append(f"# 24H Brignoles 2026 — Stats en direct")
    lines.append(f"")
    lines.append(f"**Généré le** : {now}  ")
    lines.append(f"**Circuit** : Brignoles Karting Loisir  ")
    lines.append(f"**API port** : {port}  ")
    lines.append(f"**Équipes** : {len(grid)}  ")
    lines.append(f"")

    # global field median
    all_laps = []
    for s in stats.values():
        if s:
            all_laps.extend([l['lap_ms'] for l in s['laps'] if l['lap_ms'] > 30000])
    field_median = statistics.median(all_laps) if all_laps else 0
    lines.append(f"**Médiane champ** : {ms_to_str(int(field_median))}  ")
    lines.append(f"**Tours champ total** : {len(all_laps):,}  ")
    lines.append(f"")

    lines.append("---")
    lines.append("")
    lines.append("## Classement par équipe")
    lines.append("")
    lines.append("| Pos | Kart | Équipe | Tours | Meilleur tour | Médiane | Δ champ | Pits | Pilote actuel |")
    lines.append("|-----|------|--------|-------|---------------|---------|---------|------|---------------|")

    for g in grid:
        tid = g['driver_id']
        s = stats.get(tid)
        pos = g.get('position', '?')
        kart = g.get('kart_label') or g.get('kart', '?')
        team = g.get('team', '?')
        cat = g.get('category', '')
        cat_str = f" `{cat}`" if cat else ""

        if s:
            total = s['total_laps']
            best = ms_to_str(s['best_lap_ms'])
            laps_filtered = [l['lap_ms'] for l in s['laps'] if l['lap_ms'] > 30000]
            med = statistics.median(laps_filtered) if laps_filtered else 0
            delta = ((med - field_median) / field_median * 100) if field_median else 0
            delta_str = f"{delta:+.2f}%"
            pits = len(s['pits'])
            current = next((d['name'] for d in s['drivers'].values() if d.get('current')), '—')
            lines.append(f"| {pos} | {kart} | {team}{cat_str} | {total:,} | {best} | {ms_to_str(int(med))} | {delta_str} | {pits} | {current} |")
        else:
            lines.append(f"| {pos} | {kart} | {team}{cat_str} | — | — | — | — | — | — |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Détail par équipe")
    lines.append("")

    for g in grid:
        tid = g['driver_id']
        s = stats.get(tid)
        if not s:
            continue

        team = g.get('team', '?')
        kart = g.get('kart_label') or g.get('kart', '?')
        pos = g.get('position', '?')
        lines.append(f"### #{pos} — {team} (Kart {kart})")
        lines.append("")

        laps_filtered = [l['lap_ms'] for l in s['laps'] if l['lap_ms'] > 30000]
        if laps_filtered:
            med = statistics.median(laps_filtered)
            delta = (med - field_median) / field_median * 100
            lines.append(f"- **Tours** : {s['total_laps']:,}  |  **Meilleur** : {ms_to_str(s['best_lap_ms'])}  |  **Médiane** : {ms_to_str(int(med))}  |  **Δ champ** : {delta:+.2f}%")

        if s['pits']:
            pit_durations = [p['pit_duration_ms'] for p in s['pits']]
            avg_pit = statistics.mean(pit_durations)
            lines.append(f"- **Pits** : {len(s['pits'])}  |  **Durée moy** : {pit_ms_to_str(int(avg_pit))}  |  **Min** : {pit_ms_to_str(min(pit_durations))}  |  **Max** : {pit_ms_to_str(max(pit_durations))}")

        if s['drivers']:
            lines.append("")
            lines.append("**Pilotes :**")
            lines.append("")
            lines.append("| Pilote | Stints | Tours | Meilleur | Médiane | CV% | Temps total |")
            lines.append("|--------|--------|-------|----------|---------|-----|-------------|")
            for did, driver in s['drivers'].items():
                dlaps = s['per_driver'].get(did, [])
                dstats = compute_driver_stats(dlaps)
                stints = sum(1 for p in s['pits'] if p['driver_id'] == did)
                # add current stint if applicable
                if driver.get('current'):
                    stints += 1
                total_ms = max((p['driver_total_ms'] for p in s['pits'] if p['driver_id'] == did), default=0)
                current_mark = " ◀" if driver.get('current') else ""
                if dstats:
                    lines.append(
                        f"| {driver['name']}{current_mark} | {stints} | {dstats['count']} | "
                        f"{ms_to_str(dstats['best'])} | {ms_to_str(int(dstats['median']))} | "
                        f"{dstats['cv']:.2f}% | {ms_to_str(total_ms)} |"
                    )
                else:
                    lines.append(f"| {driver['name']}{current_mark} | {stints} | 0 | — | — | — | {ms_to_str(total_ms)} |")

        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8600)
    parser.add_argument('--backend', default='https://apex-analyzer.durdur.eu')
    parser.add_argument('--output', default='analysis/brignoles_2026_stats.md')
    args = parser.parse_args()

    print(f"Fetching grid from {args.backend}...")
    grid = get_grid(args.backend)
    print(f"  {len(grid)} teams found")

    stats = {}
    for i, g in enumerate(grid):
        tid = g['driver_id']
        team = g.get('team', '?')
        print(f"  [{i+1}/{len(grid)}] {team} ({tid})...", end=' ', flush=True)
        data = fetch_team_data(args.port, tid)
        stats[tid] = data
        if data:
            print(f"{data['total_laps']} laps, {len(data['pits'])} pits, {len(data['drivers'])} drivers")
        else:
            print("FAILED")
        time.sleep(0.1)  # polite rate limiting

    print(f"\nGenerating report → {args.output}")
    report = generate_report(grid, stats, args.port)
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(report)
    print("Done.")


if __name__ == '__main__':
    main()
