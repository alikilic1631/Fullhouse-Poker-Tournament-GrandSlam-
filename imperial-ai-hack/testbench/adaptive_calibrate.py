#!/usr/bin/env python3
"""adaptive_calibrate - centre the adaptive shifts on the simulated population and calibrate the hero level.

    python3 adaptive_fit.py              # first: slopes etc. from the real logs -> adaptive/params.json
    python3 adaptive_calibrate.py        # then: 2 instrumented passes over v10's 36 real line-ups (seeds 101-106)

Pass 1 (centring).  The fold shifts are k * (feature - reference). adaptive_fit.py sets the references to the
feature's mean over the REAL decisions against other teams, but the clones' own bettors/3-bettors reach slightly
different running frequencies in simulation (e.g. clone 3-bettors have a lower running 3-bet frequency when they
3-bet), which would move every clone's pooled fold rate away from its profile. As calibrate.py does for the strength
CDFs, the references are re-set to the feature's mean over the SIMULATED decisions against non-hero seats, so the
average shift against other bettors is zero in the bench population (per street and size bucket; 3-bets).
Pass 2 (hero level).  With the centred references and no hero level, the clones' fold rate facing OUR single bet
(per street and size bucket) and facing OUR non-jam 3-bet is compared with the real rate on the same line-ups
(out/adaptive_real_records.json, R19-R54); the gap that the measured mechanisms leave is stored as
params["hero_level"], shrunk by the real sample size (gap * n / (n + 50); buckets with < 30 real decisions: 0).
It is a static calibrated correction: the logs show real teams fold more to OUR bets from the first hands of a
round, not explained by anything they could have learned (adaptive_fit.txt), so its cause is unknown.

Seeds 101-106 are used so that simreal.py's default seeds (1-6) stay out of sample for validation.
Writes adaptive/params.json (refs + hero_level) and out/adaptive_calibrate.txt.
"""
import argparse
import glob
import json
import os
import re
import statistics
import sys
import time
import zlib
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import clone as CL  # noqa: E402
import clone_adapt as CA  # noqa: E402

LIVE_BOT = os.path.join(os.path.dirname(HERE), "v10", "bot.py")
REC = os.path.join(HERE, "out", "adaptive_real_records.json")
OUT_TXT = os.path.join(HERE, "out", "adaptive_calibrate.txt")
N0 = 50.0
MIN_REAL = 30


class LoggingAgent(CA.AdaptiveCloneAgent):
    """Adaptive clone that logs, at every decision facing a single postflop bet and as opener facing one non-jam
    3-bet, the raw features (before the reference), whether the bettor is our seat, and whether it folded."""
    LOG = None

    def _post(self, state, key):
        out = super()._post(state, key)
        parts = key.split("|")
        if len(parts) == 4 and parts[1] in CL.POST_FACING:
            b = self.trk.agg_cur
            st = self.trk.st
            if 0 <= b < self.n and 1 <= st <= 3:
                m = self._mdl()
                ag = m.ag[b]
                f = (ag[2 * (st - 1) + 1] + self.m_bet * self.bet_prior[st - 1]) / (ag[2 * (st - 1)] + self.m_bet)
                sdev = m.dev(b, self.value_pi, self.m_shown)
                k = ("post", st, CL.BUCKETS.index(parts[3]), 1 if b == self.hero else 0)
                row = LoggingAgent.LOG[k]
                row[0] += 1
                row[1] += f
                row[2] += sdev
                row[3] += 1 if out.get("action") == "fold" else 0
        return out

    def _pre(self, state, key):
        rec = None
        if key == "pf|opener_vs_3bet|all" and 0 <= self.trk.pfa < self.n:
            t = self.trk.pfa
            n3, k3 = self._mdl().t3[t]
            rec = (("f3", 0, 0, 1 if t == self.hero else 0), (k3 + self.m3t * self.p3) / (n3 + self.m3t))
        out = super()._pre(state, key)
        if rec is not None:
            row = LoggingAgent.LOG[rec[0]]
            row[0] += 1
            row[1] += rec[1]
            row[3] += 1 if out.get("action") == "fold" else 0
        return out


def lineups(rounds=(19, 54)):
    import hh as H
    sel = []
    for path in sorted(glob.glob(os.path.join(H.HANDS_DIR, "*.json"))):
        if "practice" in os.path.basename(path):
            continue
        m = re.search(r"r0*(\d+)\.json$", path)
        if not m or not rounds[0] <= int(m.group(1)) <= rounds[1]:
            continue
        with open(path) as fh:
            d = json.load(fh)
        if (d.get("round") or {}).get("version") != 17:
            continue
        sel.append(("R%d" % int(m.group(1)), d["players"], d["seat"]))
    return sel


def play_job(job):
    import duel as D
    from engine.game import FixedHandsTable
    LoggingAgent.LOG = defaultdict(lambda: [0, 0.0, 0.0, 0])
    params = job["params"]
    idx = job["index"]
    mod = D.load_module(job["bot"], "base")
    players = []
    for s, nm in enumerate(job["players"]):
        if s == job["seat"]:
            players.append(D.Seat(mod.Agent(), "<us>", hero=True))
        else:
            key = nm if (nm in idx and idx[nm].get("kind", "team") == "team") else "field"
            with open(os.path.join(HERE, "profiles", idx[key]["slug"] + ".json")) as fh:
                prof = json.load(fh)
            players.append(D.Seat(LoggingAgent(prof, job["clone_seed"], params, job["seat"]), nm))
    rng = D.DeckRecorder(job["engine_seed"])
    FixedHandsTable(players, hands=1000, record=False, rng=rng).play()
    D.drop_module(mod)
    return {"|".join(map(str, k)): v for k, v in LoggingAgent.LOG.items()}


def run_pass(params, seeds, procs, bot):
    import multiprocessing as mp
    with open(os.path.join(HERE, "profiles", "index.json")) as fh:
        idx = json.load(fh)
    jobs = []
    for i, (lab, pl, seat) in enumerate(lineups()):
        for sd in seeds:
            jobs.append({"players": pl, "seat": seat, "params": params, "index": idx, "bot": bot,
                         "clone_seed": sd * 7919 + i * 31, "engine_seed": (zlib.crc32(lab.encode()) & 0xFFFFFF) * 1009 + sd})
    agg = defaultdict(lambda: [0, 0.0, 0.0, 0])
    with mp.get_context("spawn").Pool(procs, maxtasksperchild=12) as pool:
        for res in pool.imap_unordered(play_job, jobs):
            for k, v in res.items():
                a = agg[k]
                for i in range(4):
                    a[i] += v[i]
    return agg, len(jobs)


def real_targets():
    with open(REC) as fh:
        doc = json.load(fh)
    post = defaultdict(lambda: [0, 0])
    for r in doc["records"]["fold"]:
        if r[9] and r[0] >= 19 and r[1] == 17:
            p = post[(r[3], r[4])]
            p[0] += 1
            p[1] += 1 if r[17] == "F" else 0
    f3 = [0, 0]
    for r in doc["records"]["f3"]:
        if r[5] and not r[4] and r[10] and r[0] >= 19 and r[1] == 17:
            f3[0] += 1
            f3[1] += 1 if r[7] == "F" else 0
    return post, f3


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seeds", default="101-106", help="deal seeds per line-up (default 101-106; simreal uses 1-6)")
    ap.add_argument("--procs", type=int, default=6)
    ap.add_argument("--bot", default=LIVE_BOT)
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    lo, hi = (int(x) for x in a.seeds.split("-"))
    seeds = list(range(lo, hi + 1))
    procs = max(1, min(6, a.procs))
    t0 = time.time()
    params = CA.load_params()
    L = ["ADAPTIVE CALIBRATION (v10 on its 36 real line-ups R19-R54, seeds %s, adaptive clones)" % a.seeds]
    # ---------------------------------------------------------------- pass 1: centring
    p1 = json.loads(json.dumps(params))
    p1["hero_level"] = {}
    agg, nt = run_pass(p1, seeds, procs, a.bot)
    fp = params["fold"]
    fp.setdefault("ref_bet_real", fp.get("ref_bet"))
    fp.setdefault("ref_shown_real", fp.get("ref_shown"))
    new_rb = [[None] * 5 for _ in range(3)]
    new_rs = [[0.0] * 5 for _ in range(3)]
    L.append("\npass 1 (%d tables, %.0fs): mean feature against NON-hero bettors, sim vs real reference" % (nt, time.time() - t0))
    for st in (1, 2, 3):
        for b in range(5):
            v = agg.get("post|%d|%d|0" % (st, b))
            if v and v[0] >= 50:
                new_rb[st - 1][b] = round(v[1] / v[0], 5)
                if b >= 2:
                    new_rs[st - 1][b] = round(v[2] / v[0], 5)
            else:
                new_rb[st - 1][b] = fp["ref_bet_real"][st - 1][b]
                new_rs[st - 1][b] = fp["ref_shown_real"][st - 1][b]
            L.append("  %-5s b%d n %6d bet freq sim %.4f real %.4f | shown dev sim %+.4f real %+.4f" % (
                CA.STREET_NAMES[st - 1], b + 1, v[0] if v else 0, new_rb[st - 1][b], fp["ref_bet_real"][st - 1][b],
                new_rs[st - 1][b], fp["ref_shown_real"][st - 1][b]))
    f3p = params["fold3"]
    f3p.setdefault("ref_real", f3p.get("ref"))
    v = agg.get("f3|0|0|0")
    new_ref3 = round(v[1] / v[0], 5) if v and v[0] >= 50 else f3p["ref_real"]
    L.append("  3-bettor's 3-bet frequency at non-jam 3-bets by non-hero seats: sim %.4f (n %d) real %.4f" % (
        new_ref3, v[0] if v else 0, f3p["ref_real"]))
    fp["ref_bet"] = new_rb
    fp["ref_shown"] = new_rs
    f3p["ref"] = new_ref3
    # ---------------------------------------------------------------- pass 2: hero level
    p2 = json.loads(json.dumps(params))
    p2["hero_level"] = {}
    t1 = time.time()
    agg2, nt = run_pass(p2, seeds, procs, a.bot)
    real_post, real_f3 = real_targets()
    hl = {"note": "static extra fold probability when the bettor / 3-bettor is OUR seat: real minus adaptive-sim fold "
                  "rate (v10, 36 real line-ups, seeds %s), times n_real / (n_real + %d); 0 where n_real < %d" % (
                      a.seeds, int(N0), MIN_REAL), "flop": {}, "turn": {}, "river": {}}
    L.append("\npass 2 (%d tables, %.0fs): fold facing OUR bets, real vs sim (centred references, no hero level)" % (
        nt, time.time() - t1))
    for st in (1, 2, 3):
        for b in range(5):
            rn, rf = real_post.get((st, b), (0, 0))
            v = agg2.get("post|%d|%d|1" % (st, b))
            sn = v[0] if v else 0
            sf = v[3] / sn if sn else None
            rr = rf / rn if rn else None
            if rn >= MIN_REAL and sf is not None:
                gap = rr - sf
                lev = gap * rn / (rn + N0)
            else:
                gap = None
                lev = 0.0
            hl[CA.STREET_NAMES[st - 1]][CL.BUCKETS[b]] = round(lev, 4)
            L.append("  %-5s b%d real %s (n %4d) sim %s (n %5d) gap %s -> hero level %+.1fpp" % (
                CA.STREET_NAMES[st - 1], b + 1, "%5.1f" % (100 * rr) if rr is not None else "    -", rn,
                "%5.1f" % (100 * sf) if sf is not None else "    -", sn, "%+5.1f" % (100 * gap) if gap is not None else "    -",
                100 * lev))
    v = agg2.get("f3|0|0|1")
    sn = v[0] if v else 0
    sf = v[3] / sn if sn else None
    rr = real_f3[1] / real_f3[0] if real_f3[0] else None
    lev = (rr - sf) * real_f3[0] / (real_f3[0] + N0) if (sf is not None and rr is not None and real_f3[0] >= MIN_REAL) else 0.0
    hl["fold_to_3bet"] = round(lev, 4)
    L.append("  opener facing OUR non-jam 3-bet: real %.1f%% (n %d) sim %.1f%% (n %d) -> hero level %+.1fpp" % (
        100 * rr, real_f3[0], 100 * sf if sf is not None else float("nan"), sn, 100 * lev))
    params["hero_level"] = hl
    params["calibrated"] = {"date": time.strftime("%Y-%m-%d %H:%M:%S"), "seeds": a.seeds, "bot": os.path.relpath(a.bot, HERE),
                            "tables_per_pass": nt}
    txt = "\n".join(L)
    print(txt)
    with open(OUT_TXT, "w") as fh:
        fh.write(txt + "\n")
    if not a.no_write:
        with open(CA.PARAMS_PATH, "w") as fh:
            json.dump(params, fh, indent=1)
        print("\nwrote %s (%.0fs)" % (CA.PARAMS_PATH, time.time() - t0))


if __name__ == "__main__":
    main()
