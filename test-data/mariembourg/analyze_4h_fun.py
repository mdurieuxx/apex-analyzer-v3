"""
Analyse Mariembourg 4h Fun — 17 mai 2026
Fichier mergé : mariembourg_4h_fun_20260517.jsonl (2 parties, 08:16 + 10:59)

Objectif : calibrer les algorithmes de l'application avec 3 niveaux de perf team,
3 niveaux pilote, 4 niveaux kart, et plusieurs niveaux de condition piste.
"""
import json, re, statistics
from collections import defaultdict
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional

FILE = "mariembourg_4h_fun_20260517.jsonl"

# Fenêtres et seuils
COMPARE_WINDOW    = 1200   # ±20 min (race courte → fenêtre réduite)
MIN_CONTEMP       = 3      # min équipes contemporaines (moins d'équipes qu'Agadir)
MIN_STINT_LAPS    = 4      # tours normaux minimum
TRACK_WINDOW      = 900    # 15-min pour les tranches de condition piste

# Seuils kart (espace best-lap, skill-adjusted) → 4 niveaux
ROCKET_THRESHOLD  = -0.015   # > 1.5% meilleur qu'attendu
GOOD_THRESHOLD    = -0.005   # 0.5–1.5% meilleur → GOOD
BAD_THRESHOLD     = +0.010   # 1.0–2.0% plus lent → BAD
CRITICAL_THRESHOLD= +0.020   # > 2.0% → CRITICAL (kart vraiment problématique)


# ── HTML parser grille initiale ───────────────────────────────────────────────
class GridParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.teams = {}
        self._row = None
        self._col = None
        self._col_map = {}   # data-type → col_id
        self._in_head = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        did = attrs.get("data-id", "")
        dt  = attrs.get("data-type", "")

        if tag == "tr" and did.startswith("r"):
            if did == "r0" or "head" in attrs.get("class",""):
                self._in_head = True
            else:
                self._in_head = False
                self._row = did
                if did not in self.teams:
                    self.teams[did] = {"kart": "", "team": "", "category": ""}
        if tag == "td":
            self._col = did
            if self._in_head and dt:
                self._col_map[dt] = did

        if tag == "div" and self._row:
            for c in attrs.get("class", "").split():
                if c.startswith("notc") or (c.startswith("no") and c[2:].isdigit()):
                    self.teams[self._row]["category"] = c

    def handle_data(self, data):
        data = data.strip()
        if not data or not self._row or not self._col:
            return
        # Mariembourg : kart=c4, team=c5
        if self._col.endswith("c4"):
            self.teams[self._row]["kart"] = data
        elif self._col.endswith("c5"):
            self.teams[self._row]["team"] = re.sub(r'\s*\[\d+:\d+\]$', '', data).strip()


# ── Modèle de données ────────────────────────────────────────────────────────
@dataclass
class Stint:
    team_id: str
    stint_num: int
    driver: str = ""
    laps: list = field(default_factory=list)   # (t_sec, lap_ms)
    pit_in_t: float = 0.0

    @property
    def normal_laps(self):
        """Passages 5+ après le pit (1=partiel, 2=out-lap, 3-4=chauffe)."""
        return self.laps[4:]

    @property
    def normal_ms(self):
        return [ms for _, ms in self.normal_laps]

    @property
    def out_lap(self):
        if len(self.laps) >= 2:
            return self.laps[1][1]
        return None

    @property
    def t_start(self):
        return self.laps[0][0] if self.laps else 0.0

    @property
    def t_end(self):
        return self.laps[-1][0] if self.laps else 0.0

    @property
    def t_mid(self):
        if not self.normal_laps:
            return (self.t_start + self.t_end) / 2 if self.laps else 0.0
        ts = [t for t, _ in self.normal_laps]
        return (ts[0] + ts[-1]) / 2

    @property
    def best(self):
        ms = self.normal_ms
        return min(ms) if ms else None

    @property
    def avg(self):
        ms = self.normal_ms
        return statistics.mean(ms) if ms else None

    @property
    def cv(self):
        ms = self.normal_ms
        return statistics.stdev(ms) / statistics.mean(ms) if len(ms) >= 3 else None


# ── Parsing ──────────────────────────────────────────────────────────────────
def parse_file(path):
    teams   = {}
    stints  = defaultdict(list)
    active  = {}
    cur_drv = {}
    header  = None

    with open(path) as f:
        raw = [json.loads(l) for l in f if l.strip()]

    header = raw[0]
    t_start_abs = header.get("started_at", "")

    for entry in raw[1:]:
        if "msg" not in entry:
            continue
        t   = entry["t"]
        msg = entry["msg"]

        # Grid HTML initial
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

            # Catégorie CSS
            if sub.startswith("notc") or (sub.startswith("no") and sub[2:].isdigit()):
                base = row_id.replace("c5", "").replace("c4", "").replace("c3", "")
                if base in teams:
                    teams[base]["category"] = sub

            # Nom du pilote (colonne team, classe drteam)
            if "c5" in row_id and sub == "drteam":
                rid = row_id.replace("c5", "")
                name = re.sub(r'\s*\[\d+:\d+\]$', '', val).strip()
                if name:
                    cur_drv[rid] = name
                    if rid in active:
                        active[rid].driver = name

            # Numéro de kart
            if "c4" in row_id and val.strip():
                rid = row_id.replace("c4", "")
                if rid in teams and val.strip().isdigit():
                    teams[rid]["kart"] = val.strip()

            # Pit in → ferme stint, ouvre suivant
            if sub == "*in":
                if row_id in active and active[row_id].laps:
                    s = active[row_id]
                    s.pit_in_t = t
                    stints[row_id].append(s)
                n = len(stints[row_id]) + 1
                active[row_id] = Stint(team_id=row_id, stint_num=n,
                                       driver=cur_drv.get(row_id, ""))

            # Temps au tour
            if sub == "*" and val.isdigit():
                ms = int(val)
                if 30000 < ms < 200000:
                    if row_id not in active:
                        active[row_id] = Stint(team_id=row_id, stint_num=1,
                                               driver=cur_drv.get(row_id, ""))
                    active[row_id].laps.append((t, ms))
                    if not active[row_id].driver:
                        active[row_id].driver = cur_drv.get(row_id, "")

    for rid, s in active.items():
        if s.laps:
            stints[rid].append(s)

    return header, teams, stints


# ── Référence contemporaine ───────────────────────────────────────────────────
def contemp_best(target: Stint, all_stints_flat, exclude_id) -> Optional[float]:
    t_ref = target.t_mid
    peers = [
        s.best
        for (tid, s) in all_stints_flat
        if tid != exclude_id
        and s.best is not None
        and len(s.normal_laps) >= MIN_STINT_LAPS
        and abs(s.t_mid - t_ref) < COMPARE_WINDOW
    ]
    return statistics.median(peers) if len(peers) >= MIN_CONTEMP else None


# ── Conditions piste ─────────────────────────────────────────────────────────
def track_conditions(all_stints_flat, race_start_h=10):
    """Médiane du champ par tranche de TRACK_WINDOW secondes."""
    buckets = defaultdict(list)
    for tid, s in all_stints_flat:
        for t, ms in s.normal_laps:
            b = int(t // TRACK_WINDOW)
            buckets[b].append(ms)

    conds = {}
    for b, laps in sorted(buckets.items()):
        if len(laps) >= 10:
            conds[b] = statistics.median(laps)

    if not conds:
        return conds, None, None, None

    medians = list(conds.values())
    global_med  = statistics.median(medians)
    track_range = max(medians) - min(medians)
    track_var   = track_range / global_med

    print(f"\n── CONDITIONS PISTE (tranches {TRACK_WINDOW//60}min) ──────────────────────────────")
    print(f"  Race start ≈ {race_start_h}h00 (t=0 = {race_start_h:02d}h{0:02d})")
    print(f"  Médiane globale : {global_med/1000:.3f}s  |  Variation : {track_var*100:.2f}%\n")
    print(f"  {'Heure':>8} {'Médiane':>9} {'Δ%':>7} {'N':>5}")
    print(f"  {'-'*35}")
    for b, med in sorted(conds.items()):
        h_offset = b * TRACK_WINDOW / 3600
        h_real = int(race_start_h + h_offset) % 24
        m_real = int((h_offset % 1) * 60)
        delta = (med - global_med) / global_med
        mark = " ← pic lent" if delta > 0.015 else (" ← rapide" if delta < -0.010 else "")
        print(f"  {h_real:02d}h{m_real:02d}   {med/1000:>9.3f}s {delta*100:>+7.2f}%{mark}")

    # Niveaux condition (quintiles des tranches)
    sorted_meds = sorted(conds.values())
    n = len(sorted_meds)
    if n >= 5:
        q = [sorted_meds[int(n * i / 5)] for i in range(5)]
        print(f"\n  Seuils condition piste (quintiles) :")
        print(f"    TRÈS RAPIDE < {q[1]/1000:.3f}s")
        print(f"    RAPIDE      {q[1]/1000:.3f}s – {q[2]/1000:.3f}s")
        print(f"    NORMAL      {q[2]/1000:.3f}s – {q[3]/1000:.3f}s")
        print(f"    LENT        {q[3]/1000:.3f}s – {q[4]/1000:.3f}s")
        print(f"    TRÈS LENT   > {q[4]/1000:.3f}s")

    return conds, global_med, track_range, track_var


# ── Analyse principale ───────────────────────────────────────────────────────
def analyze(header, teams, stints):
    # Catégories : on prend tout (course fun → catégorie unique probable)
    all_cats = {v.get("category", "") for v in teams.values()}
    print(f"\n  Catégories détectées : {all_cats}")

    # Filtrer équipes avec au moins 1 stint valide
    valid_teams = {
        rid for rid in teams
        if any(len(s.normal_laps) >= MIN_STINT_LAPS for s in stints[rid])
    }

    all_stints_flat = [
        (rid, s)
        for rid in valid_teams
        for s in stints[rid]
        if len(s.normal_laps) >= MIN_STINT_LAPS
    ]

    # ── Conditions piste ──────────────────────────────────────────────────────
    conds, global_med, track_range, track_var = track_conditions(all_stints_flat, race_start_h=10)
    if global_med is None:
        print("Pas assez de données.")
        return

    # ── Stats équipes ─────────────────────────────────────────────────────────
    team_stats = {}
    for rid in valid_teams:
        info = teams.get(rid, {})
        valid = [s for s in stints[rid] if len(s.normal_laps) >= MIN_STINT_LAPS]
        all_ms = [ms for s in valid for ms in s.normal_ms]
        if not all_ms:
            continue
        team_stats[rid] = {
            "name": info.get("team", rid),
            "kart": info.get("kart", "?"),
            "cat":  info.get("category", ""),
            "avg":  statistics.mean(all_ms),
            "best": min(all_ms),
            "stints": valid,
            "n_laps": len(all_ms),
        }
        team_stats[rid]["delta"] = (team_stats[rid]["avg"] - global_med) / global_med

    # Tertiles → 3 niveaux team
    deltas = sorted(ts["delta"] for ts in team_stats.values())
    n = len(deltas)
    t33, t66 = deltas[n // 3], deltas[2 * n // 3]

    def team_level(delta):
        if delta <= t33: return "TOP"
        if delta <= t66: return "MEDIUM"
        return "SLOW"

    print(f"\n── ÉQUIPES — 3 NIVEAUX (tertiles) ──────────────────────────────────────")
    print(f"  Seuils : TOP ≤ {t33*100:+.2f}%  MEDIUM ≤ {t66*100:+.2f}%  SLOW > {t66*100:+.2f}%")
    print(f"  Médiane champ : {global_med/1000:.3f}s  |  Variation piste : {track_var*100:.2f}%\n")
    print(f"  {'Kart':>4} {'Niveau':>6} {'Avg':>8} {'Best':>8} {'Δ%':>7} {'Stints':>6} {'Tours':>5}  Équipe")
    print(f"  {'-'*80}")
    for rid, ts in sorted(team_stats.items(), key=lambda x: x[1]["delta"]):
        lvl = team_level(ts["delta"])
        cvs = [s.cv for s in ts["stints"] if s.cv is not None]
        cv_str = f"{statistics.median(cvs)*100:.2f}%" if cvs else "-"
        print(f"  {ts['kart']:>4} {lvl:>6} {ts['avg']/1000:>8.3f} {ts['best']/1000:>8.3f} "
              f"{ts['delta']*100:>+7.2f}% {len(ts['stints']):>6} {ts['n_laps']:>5}  {ts['name']}")

    # Spread équipes
    delta_vals = [ts["delta"] for ts in team_stats.values()]
    print(f"\n  Spread : {min(delta_vals)*100:+.2f}% à {max(delta_vals)*100:+.2f}%")
    print(f"  p33={t33*100:+.2f}%  p66={t66*100:+.2f}%")

    # ── Best-lap deltas team (contemporain) ───────────────────────────────────
    team_best_deltas = {}
    for rid, ts in team_stats.items():
        scores = []
        for s in ts["stints"]:
            ref = contemp_best(s, all_stints_flat, rid)
            if ref and s.best:
                scores.append((s.best - ref) / ref)
        if len(scores) >= 2:
            team_best_deltas[rid] = statistics.median(scores)

    # ── Pilotes ───────────────────────────────────────────────────────────────
    drv_stints = defaultdict(list)
    drv_laps   = defaultdict(list)

    for rid, ts in team_stats.items():
        for s in ts["stints"]:
            if not s.driver or len(s.normal_laps) < 5:
                continue
            drv_stints[s.driver].append({
                "team": ts["name"], "tid": rid, "stint": s,
                "best": s.best, "avg": s.avg, "cv": s.cv,
                "n": len(s.normal_laps),
            })
            drv_laps[s.driver].extend(s.normal_ms)

    # Best-delta pilote (espace best-lap, contemporain)
    drv_best_deltas = {}
    for drv, dstints in drv_stints.items():
        scores = []
        for ds in dstints:
            ref = contemp_best(ds["stint"], all_stints_flat, ds["tid"])
            if ref and ds["best"]:
                scores.append((ds["best"] - ref) / ref)
        if len(scores) >= 2:
            drv_best_deltas[drv] = statistics.median(scores)

    drv_summary = []
    for drv, dstints in drv_stints.items():
        if len(dstints) < 1:
            continue
        laps = drv_laps[drv]
        avg  = statistics.mean(laps)
        delta_avg = (avg - global_med) / global_med
        cvs = [ds["cv"] for ds in dstints if ds["cv"] is not None]
        drv_summary.append({
            "name": drv,
            "delta_avg":  delta_avg,
            "best_delta": drv_best_deltas.get(drv),
            "cv_median":  statistics.median(cvs) if cvs else None,
            "n_stints":   len(dstints),
            "n_laps":     len(laps),
            "stints":     dstints,
        })

    drv_summary.sort(key=lambda x: x["delta_avg"])

    # Tertiles pilotes → 3 niveaux
    d_deltas = sorted(d["delta_avg"] for d in drv_summary)
    nd = len(d_deltas)
    if nd >= 3:
        dp33 = d_deltas[nd // 3]
        dp66 = d_deltas[2 * nd // 3]
        def drv_level(delta):
            if delta <= dp33: return "TOP"
            if delta <= dp66: return "MEDIUM"
            return "SLOW"
    else:
        dp33 = dp66 = 0.0
        def drv_level(delta): return "MEDIUM"

    print(f"\n── PILOTES — 3 NIVEAUX ──────────────────────────────────────────────────")
    print(f"  Seuils : TOP ≤ {dp33*100:+.2f}%  MEDIUM ≤ {dp66*100:+.2f}%  SLOW > {dp66*100:+.2f}%\n")
    print(f"  {'Niveau':>6} {'Δavg%':>7} {'Δbest%':>7} {'CV/stint':>8} {'Stints':>6} {'Tours':>5}  Pilote")
    print(f"  {'-'*70}")
    for d in drv_summary:
        bd = f"{d['best_delta']*100:>+7.2f}%" if d['best_delta'] is not None else "      -"
        cv = f"{d['cv_median']*100:>8.2f}%" if d['cv_median'] else "       -"
        lvl = drv_level(d["delta_avg"])
        print(f"  {lvl:>6} {d['delta_avg']*100:>+7.2f}% {bd} {cv} "
              f"{d['n_stints']:>6} {d['n_laps']:>5}  {d['name']}")

    # ── Qualité kart — 4 niveaux ──────────────────────────────────────────────
    print(f"\n── QUALITÉ KART — 4 NIVEAUX ─────────────────────────────────────────────")
    print(f"  score = (best_stint - médiane_best_contemporains) / ref − skill_expected")
    print(f"  ROCKET < {ROCKET_THRESHOLD*100:.1f}%  |  GOOD {ROCKET_THRESHOLD*100:.1f}%–{GOOD_THRESHOLD*100:.1f}%"
          f"  |  NEUTRAL {GOOD_THRESHOLD*100:.1f}%–{BAD_THRESHOLD*100:.1f}%"
          f"  |  BAD {BAD_THRESHOLD*100:.1f}%–{CRITICAL_THRESHOLD*100:.1f}%"
          f"  |  CRITICAL > {CRITICAL_THRESHOLD*100:.1f}%\n")

    kart_results = []

    for rid, ts in team_stats.items():
        for s in ts["stints"]:
            if not s.best or len(s.normal_laps) < MIN_STINT_LAPS:
                continue
            ref = contemp_best(s, all_stints_flat, rid)
            if ref is None:
                continue
            raw = (s.best - ref) / ref

            skill = drv_best_deltas.get(s.driver) if s.driver else None
            if skill is None:
                skill = team_best_deltas.get(rid, 0.0)

            score = raw - skill

            if score < ROCKET_THRESHOLD:   quality = "ROCKET"
            elif score < GOOD_THRESHOLD:   quality = "GOOD"
            elif score <= BAD_THRESHOLD:   quality = "NEUTRAL"
            elif score <= CRITICAL_THRESHOLD: quality = "BAD"
            else:                          quality = "CRITICAL"

            kart_results.append({
                "team": ts["name"], "kart": ts["kart"], "tid": rid,
                "driver": s.driver or "-", "stint": s.stint_num,
                "best": s.best, "ref": ref, "raw": raw,
                "skill": skill, "score": score, "quality": quality,
                "n": len(s.normal_laps), "cv": s.cv, "t_mid": s.t_mid,
            })

    # Distribution des 4 niveaux
    from collections import Counter
    dist = Counter(r["quality"] for r in kart_results)
    total = len(kart_results)
    print(f"  Distribution sur {total} stints notés :")
    for lvl in ["ROCKET", "GOOD", "NEUTRAL", "BAD", "CRITICAL"]:
        n_lvl = dist.get(lvl, 0)
        print(f"    {lvl:>8} : {n_lvl:3} stints ({n_lvl/total*100:5.1f}%)")

    hdr = (f"  {'Équipe':<26} {'#':>3} {'Pilote':<22} {'Best':>8} "
           f"{'Ref':>8} {'Raw':>7} {'Skill':>7} {'Score':>7} {'N':>4} {'h':>4}")
    sep = "  " + "-"*100

    for quality, label in [("ROCKET","ROCKETS"), ("GOOD","BONS"), ("BAD","MAUVAIS"), ("CRITICAL","CRITIQUES")]:
        subset = [r for r in kart_results if r["quality"] == quality]
        if not subset:
            continue
        rev = quality in ("BAD", "CRITICAL")
        subset.sort(key=lambda x: (-x["score"] if rev else x["score"]))
        print(f"\n  {label} ({len(subset)}) :")
        print(hdr); print(sep)
        for r in subset[:15]:
            hm = int(r["t_mid"] / 3600) + 10
            print(f"  {r['team']:<26} #{r['stint']:>2} {r['driver']:<22} "
                  f"{r['best']/1000:>8.3f} {r['ref']/1000:>8.3f} "
                  f"{r['raw']*100:>+7.2f}% {r['skill']*100:>+7.2f}% "
                  f"{r['score']*100:>+7.2f}% {r['n']:>4} {hm%24:02d}h")

    # ── Régularité pilotes ────────────────────────────────────────────────────
    print(f"\n── RÉGULARITÉ PILOTES (CV intra-stint) ──────────────────────────────────")
    print(f"  CV = stdev(tours normaux) / mean — insensible aux conditions de piste\n")
    reg = [d for d in drv_summary if d["cv_median"] is not None and d["n_laps"] >= 8]
    reg.sort(key=lambda x: x["cv_median"])
    print(f"  {'CV/stint':>8} {'Δavg%':>7} {'Niveau':>6} {'Stints':>6} {'Tours':>5}  Pilote")
    print(f"  {'-'*60}")
    for d in reg:
        lvl = drv_level(d["delta_avg"])
        print(f"  {d['cv_median']*100:>8.2f}% {d['delta_avg']*100:>+7.2f}% "
              f"{lvl:>6} {d['n_stints']:>6} {d['n_laps']:>5}  {d['name']}")

    # Valeurs typiques de CV
    cvs_all = [d["cv_median"] for d in reg]
    if cvs_all:
        print(f"\n  CV médian tous pilotes : {statistics.median(cvs_all)*100:.2f}%")
        print(f"  CV range : {min(cvs_all)*100:.2f}% – {max(cvs_all)*100:.2f}%")

    # ── Stints aberrants par pilote (kart suspect) ────────────────────────────
    print(f"\n── STINTS ANORMALEMENT LENTS (kart suspect, pilotes ≥2 stints) ─────────")
    for d in sorted(drv_summary, key=lambda x: x["delta_avg"]):
        if d["n_stints"] < 2 or d["best_delta"] is None:
            continue
        exp = d["best_delta"]
        anomalies = []
        for ds in d["stints"]:
            ref = contemp_best(ds["stint"], all_stints_flat, ds["tid"])
            if ref is None or ds["best"] is None:
                continue
            raw = (ds["best"] - ref) / ref
            delta_vs_own = raw - exp
            if delta_vs_own > BAD_THRESHOLD:
                anomalies.append((ds, raw, delta_vs_own))
        if anomalies:
            print(f"\n  {d['name']} (Δbest attendu {exp*100:+.2f}%):")
            for ds, raw, dv in sorted(anomalies, key=lambda x: -x[2]):
                h = int(ds["stint"].t_mid / 3600) + 10
                print(f"    Stint #{ds['stint'].stint_num:>2} {ds['team']:<26} "
                      f"best={ds['best']/1000:.3f}s raw={raw*100:+.2f}% "
                      f"Δ_own={dv*100:+.2f}% ({ds['n']}t {h%24:02d}h)")

    # ── Résumé algorithmes ────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"RÉSUMÉ CALIBRATION ALGORITHMES")
    print(f"{'='*70}")
    print(f"  Médiane champ           : {global_med/1000:.3f}s")
    print(f"  Variation piste totale  : {track_var*100:.2f}%")
    print(f"  Niveaux équipes (tertiles): p33={t33*100:+.2f}%  p66={t66*100:+.2f}%")
    if nd >= 3:
        print(f"  Niveaux pilotes (tertiles): p33={dp33*100:+.2f}%  p66={dp66*100:+.2f}%")
    print(f"  Stints notés kart       : {total}")
    print(f"  Distribution karts      : " + "  ".join(
        f"{lvl}={dist.get(lvl,0)}" for lvl in ["ROCKET","GOOD","NEUTRAL","BAD","CRITICAL"]))
    if cvs_all:
        print(f"  CV pilotes : médiane={statistics.median(cvs_all)*100:.2f}%  "
              f"min={min(cvs_all)*100:.2f}%  max={max(cvs_all)*100:.2f}%")


if __name__ == "__main__":
    import os
    os.chdir(os.path.dirname(__file__))
    print(f"Chargement {FILE}...")
    header, teams, stints = parse_file(FILE)
    n_stints = sum(len(v) for v in stints.values())
    n_laps   = sum(len(s.laps) for v in stints.values() for s in v)
    print(f"  {len(teams)} équipes, {n_stints} stints, {n_laps} passages")
    analyze(header, teams, stints)
