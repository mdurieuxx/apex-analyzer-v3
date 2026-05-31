"""
Analyse 24h Agadir 20251116.
Kart quality : compare le best lap du stint aux best laps des autres équipes
               qui roulaient AU MÊME MOMENT (fenêtre ±COMPARE_WINDOW secondes).
Régularité   : CV des tours normaux → indicateur pilote uniquement.
"""
import json, re, statistics
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional
from html.parser import HTMLParser

FILE = "agadir_24h_20251116.jsonl"
COMPARE_WINDOW = 1800   # ±30 min pour la référence contemporaine
MIN_CONTEMPORANEOUS = 5  # min équipes simultanées pour avoir une référence valide
MIN_STINT_LAPS = 4       # tours normaux minimum pour noter un stint
BAD_THRESHOLD  =  0.010  # +1.0% → mauvais kart
FAST_THRESHOLD = -0.005  # -0.5% → bon kart


# ── HTML parser for initial grid ──────────────────────────────────────────────
class GridParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.teams = {}
        self._row = None
        self._col = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        did = attrs.get("data-id", "")
        if tag == "tr" and did.startswith("r") and did != "r0":
            self._row = did
            if did not in self.teams:
                self.teams[did] = {"kart": "", "team": "", "category": ""}
        if tag == "td":
            self._col = did
        if tag == "div" and self._row:
            for c in attrs.get("class", "").split():
                if c.startswith("notc") or (c.startswith("no") and c[2:].isdigit()):
                    self.teams[self._row]["category"] = c

    def handle_data(self, data):
        data = data.strip()
        if not data or not self._row or not self._col:
            return
        if self._col.endswith("c4"):
            self.teams[self._row]["kart"] = data
        elif self._col.endswith("c5"):
            self.teams[self._row]["team"] = re.sub(r'\s*\[\d+:\d+\]$', '', data).strip()


# ── Data model ─────────────────────────────────────────────────────────────────
@dataclass
class Stint:
    team_id: str
    stint_num: int
    driver: str = ""
    laps: list = field(default_factory=list)    # (t_seconds, lap_ms) for all passages
    pit_in_t: float = 0.0

    @property
    def normal_laps(self):
        """Passages 5+ (1=partial, 2=outlap, 3-4=warmup)."""
        return self.laps[4:]

    @property
    def normal_laps_ms(self):
        return [ms for _, ms in self.normal_laps]

    @property
    def t_mid(self):
        """Central timestamp of this stint (for contemporaneous comparison)."""
        if not self.normal_laps:
            return self.laps[-1][0] if self.laps else 0.0
        ts = [t for t, _ in self.normal_laps]
        return (ts[0] + ts[-1]) / 2

    @property
    def best(self):
        ms = self.normal_laps_ms
        return min(ms) if ms else None

    @property
    def avg(self):
        ms = self.normal_laps_ms
        return statistics.mean(ms) if ms else None

    @property
    def cv(self):
        ms = self.normal_laps_ms
        return statistics.stdev(ms) / statistics.mean(ms) if len(ms) >= 3 else None


# ── Parser ────────────────────────────────────────────────────────────────────
def parse_file(path):
    teams = {}
    stints = defaultdict(list)        # row_id -> [Stint]
    current_driver = {}
    active_stints = {}

    with open(path) as f:
        lines = [json.loads(l) for l in f if l.strip()]

    for entry in lines[1:]:
        if "msg" not in entry:
            continue
        t = entry.get("t", 0.0)
        msg = entry["msg"]

        # Grid HTML → team info
        if "grid||" in msg:
            m = re.search(r'grid\|\|(.+?)(?=\n[a-z]|\Z)', msg, re.DOTALL)
            if m:
                p = GridParser()
                p.feed(m.group(1))
                for rid, info in p.teams.items():
                    if rid not in teams:
                        teams[rid] = info
                    else:
                        for k, v in info.items():
                            if v:
                                teams[rid][k] = v

        for line in msg.split("\n"):
            parts = line.split("|")
            if len(parts) < 3:
                continue
            row_id, sub, val = parts[0], parts[1], parts[2]

            # Category from CSS class lines
            if sub in ("notc65535", "notc8388863") and row_id in teams:
                teams[row_id]["category"] = sub
            if sub.startswith("no") and sub[2:].isdigit() and row_id in teams:
                teams[row_id]["category"] = sub

            # Driver name
            if "c5" in row_id and sub == "drteam":
                rid = row_id.replace("c5", "")
                name = re.sub(r'\s*\[\d+:\d+\]$', '', val).strip()
                if name:
                    current_driver[rid] = name
                    if rid in active_stints:
                        active_stints[rid].driver = name

            # Kart number incremental update
            if "c4" in row_id and sub in ("notc65535", "notc8388863") or (sub == "no"):
                rid = row_id.replace("c4", "")
                if rid in teams and val.strip():
                    teams[rid]["kart"] = val.strip()

            # Pit in → close & open new stint
            if sub == "*in":
                if row_id in active_stints and active_stints[row_id].laps:
                    s = active_stints[row_id]
                    s.pit_in_t = t
                    stints[row_id].append(s)
                n = len(stints[row_id]) + 1
                active_stints[row_id] = Stint(team_id=row_id, stint_num=n,
                                               driver=current_driver.get(row_id, ""))

            # Lap time
            if sub == "*" and val.isdigit():
                lap_ms = int(val)
                if 30000 < lap_ms < 200000:
                    if row_id not in active_stints:
                        active_stints[row_id] = Stint(team_id=row_id, stint_num=1,
                                                       driver=current_driver.get(row_id, ""))
                    active_stints[row_id].laps.append((t, lap_ms))
                    if not active_stints[row_id].driver:
                        active_stints[row_id].driver = current_driver.get(row_id, "")

    for row_id, s in active_stints.items():
        if s.laps:
            stints[row_id].append(s)

    return teams, stints


# ── Contemporaneous field reference ───────────────────────────────────────────
def contemporaneous_best_median(target_stint, all_stints_flat, exclude_id):
    """
    Median of other teams' best laps whose stints overlap in time with target_stint.
    'Overlap' = |t_mid_other - t_mid_target| < COMPARE_WINDOW and ≥ MIN_STINT_LAPS.
    """
    t_ref = target_stint.t_mid
    peers = [
        s.best
        for (team_id, s) in all_stints_flat
        if team_id != exclude_id
        and s.best is not None
        and len(s.normal_laps) >= MIN_STINT_LAPS
        and abs(s.t_mid - t_ref) < COMPARE_WINDOW
    ]
    if len(peers) < MIN_CONTEMPORANEOUS:
        return None
    return statistics.median(peers)


# ── Analysis ──────────────────────────────────────────────────────────────────
def analyze(teams, stints):
    # Keep only main category teams (notc8388863 and notc65535), exclude kids/no6
    main_cats = {"notc8388863", "notc65535", ""}
    main_teams = {rid for rid, info in teams.items()
                  if info.get("category", "") in main_cats}

    all_stints_flat = [
        (rid, s)
        for rid in main_teams
        for s in stints[rid]
        if len(s.normal_laps) >= MIN_STINT_LAPS
    ]

    # ── Global team stats ─────────────────────────────────────────────────────
    team_stats = {}
    for row_id in main_teams:
        info = teams.get(row_id, {})
        valid = [s for s in stints[row_id] if len(s.normal_laps) >= MIN_STINT_LAPS]
        if not valid:
            continue
        all_laps = [ms for s in valid for ms in s.normal_laps_ms]
        team_avg = statistics.mean(all_laps)
        # Global field avg for team level ranking (use full-race median of all teams)
        team_stats[row_id] = {
            "name": info.get("team", row_id),
            "kart": info.get("kart", "?"),
            "cat": info.get("category", ""),
            "avg": team_avg, "best": min(all_laps),
            "stints": valid,
        }

    # Field median (all laps, all main teams) → for team level classification
    all_laps_global = [ms for ts in team_stats.values() for ms in
                       [ms for s in ts["stints"] for ms in s.normal_laps_ms]]
    field_median = statistics.median(all_laps_global)

    for ts in team_stats.values():
        ts["delta"] = (ts["avg"] - field_median) / field_median

    # Quartile thresholds
    deltas = sorted(ts["delta"] for ts in team_stats.values())
    n = len(deltas)
    p25, p50, p75 = deltas[n//4], deltas[n//2], deltas[3*n//4]

    def team_level(delta):
        if delta <= p25: return "ELITE"
        if delta <= p50: return "FAST"
        if delta <= p75: return "MEDIUM"
        return "SLOW"

    # ── Print team ranking ────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"COURSE 24H AGADIR — médiane champ global: {field_median/1000:.3f}s")
    print(f"{'='*70}\n")
    print("── NIVEAUX ÉQUIPES ──────────────────────────────────────────────────")
    print(f"{'Kart':>4} {'Cat':>12} {'Niveau':>6} {'Avg':>8} {'Best':>8} {'Δ%':>7} {'Stints':>6}  Équipe")
    print("-"*80)
    for rid, ts in sorted(team_stats.items(), key=lambda x: x[1]["delta"]):
        lvl = team_level(ts["delta"])
        print(f"{ts['kart']:>4} {ts['cat']:>12} {lvl:>6} {ts['avg']/1000:>8.3f} "
              f"{ts['best']/1000:>8.3f} {ts['delta']*100:>+7.2f}% {len(ts['stints']):>6}  {ts['name']}")

    # ── Driver stats ──────────────────────────────────────────────────────────
    driver_stints = defaultdict(list)   # driver_name -> [stint_info]
    driver_laps   = defaultdict(list)   # driver_name -> [lap_ms]

    for row_id, ts in team_stats.items():
        for s in ts["stints"]:
            if not s.driver or len(s.normal_laps) < 5:
                continue
            driver_stints[s.driver].append({
                "team": ts["name"], "team_id": row_id,
                "stint": s, "best": s.best, "avg": s.avg, "cv": s.cv,
                "n": len(s.normal_laps),
            })
            driver_laps[s.driver].extend(s.normal_laps_ms)

    # Driver best-lap expected delta (vs contemporaneous field, median across stints)
    # We compute this AFTER we know all stints, using contemp reference for each
    driver_best_deltas = {}  # driver -> median of (raw_score per stint)
    for driver, d_stints in driver_stints.items():
        raw_scores = []
        for ds in d_stints:
            ref = contemporaneous_best_median(ds["stint"], all_stints_flat, ds["team_id"])
            if ref is not None and ds["best"] is not None:
                raw_scores.append((ds["best"] - ref) / ref)
        if len(raw_scores) >= 2:
            driver_best_deltas[driver] = statistics.median(raw_scores)

    # Team best-lap expected delta (fallback)
    team_best_deltas = {}
    for row_id, ts in team_stats.items():
        raw_scores = []
        for s in ts["stints"]:
            ref = contemporaneous_best_median(s, all_stints_flat, row_id)
            if ref is not None and s.best is not None:
                raw_scores.append((s.best - ref) / ref)
        if len(raw_scores) >= 2:
            team_best_deltas[row_id] = statistics.median(raw_scores)

    # ── Driver summary ────────────────────────────────────────────────────────
    driver_summary = []
    for driver, d_stints in driver_stints.items():
        if len(d_stints) < 2:
            continue
        laps = driver_laps[driver]
        avg  = statistics.mean(laps)
        delta_avg = (avg - field_median) / field_median
        cvs = [ds["cv"] for ds in d_stints if ds["cv"] is not None]
        cv_med = statistics.median(cvs) if cvs else None
        driver_summary.append({
            "name": driver, "delta_avg": delta_avg,
            "best_delta": driver_best_deltas.get(driver),
            "cv_stint": cv_med, "n_stints": len(d_stints),
            "n_laps": len(laps), "stints": d_stints,
        })

    driver_summary.sort(key=lambda x: x["delta_avg"])

    print(f"\n── PILOTES (≥2 stints, ≥5 tours/stint) ─────────────────────────────")
    print(f"{'Pilote':<30} {'Δavg%':>7} {'Δbest%':>7} {'CV/stint':>8} {'Stints':>6} {'Tours':>5}")
    print("-"*65)
    for d in driver_summary:
        bd = f"{d['best_delta']*100:>+7.2f}%" if d['best_delta'] is not None else "      -"
        cv = f"{d['cv_stint']*100:>8.2f}%" if d['cv_stint'] else "       -"
        print(f"{d['name']:<30} {d['delta_avg']*100:>+7.2f}% {bd} {cv} {d['n_stints']:>6} {d['n_laps']:>5}")

    # ── Kart quality per stint (contemporaneous best-lap comparison) ──────────
    print(f"\n── DÉTECTION KARTS — comparaison contemporaine (±{COMPARE_WINDOW//60}min) ────────")
    print(f"  score = (best_stint - médiane_best_contemporains) / ref  -  skill_expected")
    print(f"  skill = médiane des scores raw du pilote sur ses autres stints\n")

    bad_karts  = []
    good_karts = []

    for row_id, ts in team_stats.items():
        for s in ts["stints"]:
            if not s.best or len(s.normal_laps) < MIN_STINT_LAPS:
                continue
            ref = contemporaneous_best_median(s, all_stints_flat, row_id)
            if ref is None:
                continue
            raw = (s.best - ref) / ref

            # Skill: driver best-delta > team best-delta > 0
            skill = driver_best_deltas.get(s.driver) if s.driver else None
            if skill is None:
                skill = team_best_deltas.get(row_id, 0.0)

            score = raw - skill

            entry = {
                "team": ts["name"], "driver": s.driver or "-",
                "stint_num": s.stint_num, "best": s.best,
                "ref": ref, "raw": raw, "skill": skill, "score": score,
                "n": len(s.normal_laps), "cv": s.cv, "t_mid": s.t_mid,
            }
            if score > BAD_THRESHOLD:
                bad_karts.append(entry)
            elif score < FAST_THRESHOLD:
                good_karts.append(entry)

    header_line = (f"{'Équipe':<28} {'#':>3} {'Pilote':<24} {'Best':>8} "
                   f"{'Ref':>8} {'Raw':>7} {'Skill':>7} {'Score':>7} {'N':>4} {'h+':>4}")
    sep = "-"*105

    print(f"MAUVAIS KARTS ({len(bad_karts)} stints > +{BAD_THRESHOLD*100:.0f}%):")
    print(header_line); print(sep)
    for b in sorted(bad_karts, key=lambda x: -x["score"])[:25]:
        h = int(b["t_mid"] / 3600)
        real_h = (14 + h) % 24
        print(f"{b['team']:<28} #{b['stint_num']:>2} {b['driver']:<24} "
              f"{b['best']/1000:>8.3f} {b['ref']/1000:>8.3f} "
              f"{b['raw']*100:>+7.2f}% {b['skill']*100:>+7.2f}% "
              f"{b['score']*100:>+7.2f}% {b['n']:>4} {real_h:02d}h")

    print(f"\nBONS KARTS ({len(good_karts)} stints < {FAST_THRESHOLD*100:.0f}%):")
    print(header_line); print(sep)
    for b in sorted(good_karts, key=lambda x: x["score"])[:20]:
        h = int(b["t_mid"] / 3600)
        real_h = (14 + h) % 24
        print(f"{b['team']:<28} #{b['stint_num']:>2} {b['driver']:<24} "
              f"{b['best']/1000:>8.3f} {b['ref']/1000:>8.3f} "
              f"{b['raw']*100:>+7.2f}% {b['skill']*100:>+7.2f}% "
              f"{b['score']*100:>+7.2f}% {b['n']:>4} {real_h:02d}h")

    # ── Top regularity ────────────────────────────────────────────────────────
    print(f"\n── TOP PILOTES RÉGULIERS (≥3 stints, ≥15 tours) ────────────────────")
    regular = [d for d in driver_summary
               if d["n_stints"] >= 3 and d["n_laps"] >= 15 and d["cv_stint"] is not None]
    regular.sort(key=lambda x: x["cv_stint"])
    print(f"{'Pilote':<30} {'CV/stint':>8} {'Δavg%':>7} {'Δbest%':>7} {'Stints':>6} {'Tours':>5}")
    print("-"*63)
    for d in regular[:20]:
        bd = f"{d['best_delta']*100:>+7.2f}%" if d['best_delta'] else "      -"
        print(f"{d['name']:<30} {d['cv_stint']*100:>8.2f}% {d['delta_avg']*100:>+7.2f}% "
              f"{bd} {d['n_stints']:>6} {d['n_laps']:>5}")

    # ── Driver anomaly: stints where best lap > 1% above own expected ────────
    print(f"\n── STINTS ANORMALEMENT LENTS PAR PILOTE (best-lap, base contemporaine) ─")
    print("  score_stint > driver_expected_best_delta + 1%\n")
    for d in sorted(driver_summary, key=lambda x: x["delta_avg"]):
        if d["n_stints"] < 3 or d["n_laps"] < 15:
            continue
        exp = d["best_delta"]
        if exp is None:
            continue
        anomalies = []
        for ds in d["stints"]:
            s = ds["stint"]
            ref = contemporaneous_best_median(s, all_stints_flat, ds["team_id"])
            if ref is None or s.best is None:
                continue
            raw = (s.best - ref) / ref
            delta_vs_own = raw - exp
            if delta_vs_own > 0.010:
                anomalies.append((ds, raw, delta_vs_own))
        if anomalies:
            print(f"  {d['name']} (expected best Δ {exp*100:+.2f}%):")
            for ds, raw, dv in sorted(anomalies, key=lambda x: -x[2])[:4]:
                h = int(ds["stint"].t_mid / 3600)
                print(f"    Stint #{ds['stint'].stint_num:>2} {ds['team']:<28} "
                      f"best={ds['best']/1000:.3f}s raw={raw*100:+.2f}% "
                      f"Δ_own={dv*100:+.2f}% ({ds['n']}t  {(14+h)%24:02d}h)")


if __name__ == "__main__":
    import os
    os.chdir(os.path.dirname(__file__))
    print("Chargement...")
    teams, stints = parse_file(FILE)
    print(f"  {len(teams)} équipes, {sum(len(v) for v in stints.values())} stints")
    analyze(teams, stints)
