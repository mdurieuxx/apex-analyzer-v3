#!/usr/bin/env python3
"""
Récupère les stats depuis l'API Apex Timing pour toutes les équipes d'une course en cours.

Usage:
  python fetch_apex_stats.py                          # Brignoles par défaut
  python fetch_apex_stats.py --team 44387             # Une seule équipe
  python fetch_apex_stats.py --output stats.json      # Sauvegarder en JSON
  python fetch_apex_stats.py --url https://... --port 8313  # Autre circuit

Requête interceptée depuis le live Apex :
  D#-30#D{id}.L#-999#D{id}.P#2#D{id}.B#1#D{id}.INF
"""

import argparse
import json
import re
import sys
import urllib.request
import urllib.parse
from dataclasses import dataclass, asdict

# ── Config par défaut : Brignoles 24H ──────────────────────────────────────
DEFAULT_CIRCUIT_URL = "https://www.apex-timing.com/live-timing/brignoles-karting-loisir/"
DEFAULT_PORT        = 8600   # configPort = WS port direct (pas wsPort-3)

ENDPOINT = "https://live-data.apex-timing.com/live-timing/commonv2/functions/request.php"
HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://www.apex-timing.com",
    "User-Agent": "Mozilla/5.0",
}


# ── Appel API ───────────────────────────────────────────────────────────────

def api_call(port: int, request: str, referer: str) -> str:
    body = urllib.parse.urlencode({"port": str(port), "request": request}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={**HEADERS, "Referer": referer})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="replace")


# ── Parsers ──────────────────────────────────────────────────────────────────

def parse_laps(text: str, team_id: str) -> list[dict]:
    laps = []
    for line in text.splitlines():
        m = re.search(rf'D{team_id}\.L(\d+)#([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)', line)
        if not m or m.group(1) == '0':
            continue
        def dec(s):
            best = s.startswith("g")
            pit  = s.startswith("p")
            raw  = s.lstrip("gp")
            return int(raw) if raw.isdigit() else 0, best, pit
        lap_n = int(m.group(1))
        s1, s1b, _  = dec(m.group(2))
        s2, s2b, _  = dec(m.group(3))
        s3, s3b, _  = dec(m.group(4))
        tt, ttb, pip = dec(m.group(5))
        laps.append({"lap": lap_n, "s1": s1, "s2": s2, "s3": s3, "total": tt,
                     "is_best": ttb, "is_pit": pip or m.group(2).startswith("p")})
    return sorted(laps, key=lambda x: x["lap"])


def parse_pits(text: str, team_id: str) -> list[dict]:
    pits = []
    for line in text.splitlines():
        m = re.search(rf'D{team_id}\.P(\d+)#(.+)', line)
        if not m:
            continue
        f = m.group(2).split("|")
        if len(f) < 9:
            continue
        pits.append({
            "pit_n":           int(m.group(1)),
            "lap":             int(f[1]) if f[1].isdigit() else 0,
            "in_ms":           int(f[2]) if f[2].isdigit() else 0,
            "out_ms":          int(f[3]) if f[3].isdigit() else 0,
            "pit_dur_ms":      int(f[4]) if f[4].isdigit() else 0,
            "track_ms":        int(f[5]) if f[5].isdigit() else 0,
            "relay_laps":      int(f[6]) if f[6].isdigit() else 0,
            "driver_id":       f[7].strip(),
            "driver_total_ms": int(f[8]) if f[8].strip().isdigit() else 0,
        })
    return sorted(pits, key=lambda x: x["pit_n"])


def parse_best(text: str, team_id: str) -> dict:
    """
    .B avec prefix #2 — retourne le meilleur tour + meilleurs secteurs théoriques.
    Format observé : D{id}.BL#{s1}|{s2}|{s3}|{total}
                     D{id}.BS#{s1}|{s2}|{s3}
    """
    result = {}
    for line in text.splitlines():
        if f"D{team_id}.BL#" in line:
            p = line.split(".BL#", 1)[1].split("|")
            if len(p) >= 4:
                result["best_lap"] = {k: int(v) if v.isdigit() else 0
                                      for k, v in zip(("s1","s2","s3","total"), p)}
        elif f"D{team_id}.BS#" in line:
            p = line.split(".BS#", 1)[1].split("|")
            if len(p) >= 3:
                result["best_sectors"] = {k: int(v) if v.isdigit() else 0
                                          for k, v in zip(("s1","s2","s3"), p)}
    return result


def parse_inf(text: str, team_id: str) -> dict:
    result = {"team": "", "kart": "", "club": "", "color": "", "drivers": []}
    m = re.search(rf'D{team_id}\.INF#(.*)', text)
    if not m:
        return result
    xml = m.group(1)
    km = re.search(r'num="(\d+)"[^>]*name="([^"]+)"', xml)
    if km:
        result["kart"], result["team"] = km.group(1), km.group(2)
    col = re.search(r'color="([^"]+)"', xml)
    if col:
        result["color"] = col.group(1)
    club = re.search(r'type="club"[^>]*value="([^"]+)"', xml)
    if club:
        result["club"] = club.group(1)
    for d in re.finditer(r'<driver[^>]*id="(\d+)"[^>]*num="(\d+)"[^>]*name="([^"]+)"', xml):
        result["drivers"].append({
            "id": d.group(1), "num": d.group(2), "name": d.group(3),
            "current": 'current="1"' in d.group(0),
        })
    return result


def ms_to_str(ms: int) -> str:
    if ms <= 0:
        return "-"
    s = ms / 1000
    m = int(s // 60)
    return f"{m}:{s % 60:06.3f}"


# ── Fetch complet pour une équipe ────────────────────────────────────────────

def fetch_team(team_id: str, port: int, circuit_url: str, all_laps: bool = False) -> dict:
    # Requête exacte capturée depuis l'UI Apex Timing
    # D#-30#D{id}.L  : 30 derniers tours
    # D#-999#D{id}.P : tous les pit stops
    # D#2#D{id}.B    : meilleur tour + meilleurs secteurs
    # D#1#D{id}.INF  : infos équipe + pilotes

    if all_laps:
        # Étape 1 : total de tours
        count_raw = api_call(port, f"D#-1#D{team_id}.L", circuit_url)
        m = re.search(rf'D{team_id}\.L(\d+)#', count_raw)
        total = int(m.group(1)) if m else 50
        req = f"D#-{total + 50}#D{team_id}.L#-999#D{team_id}.P#2#D{team_id}.B#1#D{team_id}.INF"
    else:
        req = f"D#-30#D{team_id}.L#-999#D{team_id}.P#2#D{team_id}.B#1#D{team_id}.INF"

    raw = api_call(port, req, circuit_url)

    laps = parse_laps(raw, team_id)
    pits = parse_pits(raw, team_id)
    info = parse_inf(raw, team_id)
    best = parse_best(raw, team_id)

    # Attribution tours → pilotes via pit stops
    laps_per_driver = {}
    if pits:
        laps_by_n = {l["lap"]: l for l in laps}
        prev = 0
        for pit in pits:
            did = pit["driver_id"]
            start, end = prev + 1, prev + pit["relay_laps"]
            driver_laps = [laps_by_n[n] for n in range(start, end + 1) if n in laps_by_n]
            laps_per_driver.setdefault(did, []).extend(driver_laps)
            prev = end

    return {
        "team_id": team_id,
        "info": info,
        "best": best,
        "pit_count": len(pits),
        "pits": pits,
        "lap_count": max((l["lap"] for l in laps), default=0),
        "laps": laps,
        "laps_per_driver": laps_per_driver,
    }


# ── Affichage résumé ─────────────────────────────────────────────────────────

def print_summary(team: dict):
    info = team["info"]
    best = team.get("best", {})
    bl = best.get("best_lap", {})
    print(f"\n{'='*60}")
    print(f"  Kart {info['kart']}  {info['team']}  [{info['color']}]")
    print(f"  Club : {info['club'] or '—'}")
    print(f"  Tours : {team['lap_count']}  |  Stands : {team['pit_count']}")
    if bl:
        print(f"  Meilleur tour : {ms_to_str(bl.get('total',0))}  "
              f"(S1={ms_to_str(bl.get('s1',0))} S2={ms_to_str(bl.get('s2',0))} S3={ms_to_str(bl.get('s3',0))})")

    print(f"\n  Pilotes :")
    for d in info["drivers"]:
        cur = " ← EN PISTE" if d["current"] else ""
        print(f"    [{d['num']}] {d['name']}{cur}")

    print(f"\n  Derniers stands :")
    for pit in team["pits"][-5:]:
        print(f"    Stand {pit['pit_n']:3d} | Tour {pit['lap']:4d} | "
              f"Relais {ms_to_str(pit['track_ms'])} | "
              f"Pit {ms_to_str(pit['pit_dur_ms'])} | "
              f"Driver #{pit['driver_id']}")

    print(f"\n  Derniers tours :")
    for lap in team["laps"][-10:]:
        flag = " ★" if lap["is_best"] else ("  P" if lap["is_pit"] else "  ")
        print(f"    Tour {lap['lap']:4d} : {ms_to_str(lap['total'])}{flag}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Fetch Apex Timing stats")
    p.add_argument("--url",    default=DEFAULT_CIRCUIT_URL, help="URL circuit Apex")
    p.add_argument("--port",   type=int, default=DEFAULT_PORT, help="configPort (WS port)")
    p.add_argument("--team",   help="Team ID (ex: 44387). Défaut: STF BY KARTCUP")
    p.add_argument("--all-laps", action="store_true", help="Récupérer tous les tours (2 appels)")
    p.add_argument("--output", help="Sauvegarder en JSON")
    p.add_argument("--raw",    action="store_true", help="Afficher la réponse brute")
    args = p.parse_args()

    team_id = args.team or "44387"  # STF BY KARTCUP par défaut

    print(f"Fetching team {team_id} from port {args.port}...")
    if args.raw:
        req = f"D#-30#D{team_id}.L#-999#D{team_id}.P#2#D{team_id}.B#1#D{team_id}.INF"
        print(api_call(args.port, req, args.url))
        return

    team = fetch_team(team_id, args.port, args.url, all_laps=args.all_laps)
    print_summary(team)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(team, f, indent=2, ensure_ascii=False)
        print(f"\nSauvegardé dans {args.output}")


if __name__ == "__main__":
    main()
