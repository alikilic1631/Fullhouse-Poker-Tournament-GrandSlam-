#!/usr/bin/env python3
"""simreal - does the bench predict reality? Replays the live bot's REAL tables with clones and compares.

    python3 simreal.py                                   # R19-R54 (36 real v10 rounds) x 6 seeds, ~2-3 min
    python3 simreal.py --rounds 19-29 --seeds 8          # a subset
    python3 simreal.py --cand out/v10_riverfold.py --seeds 4 --name riverfold   # + paired candidate on real lineups
    python3 simreal.py --adaptive --name v10_adapt       # ADAPTIVE clones (clone_adapt.py, adaptive/params.json)

What it does
  For every selected real round played by the live bot (site version 17 = imperial-ai-hack/v10/bot.py,
  R19-R54) the real table is rebuilt: same teams in the same seats, our seat = the bot (--bot, default
  v10), every other seat = clone.make_agent(profile of that team). A team without a profile gets the
  pooled --fallback profile (default 'field'; the report lists every such case). Each lineup is played for
  --seeds deal seeds with the kit engine in-process (1,000 hands, chips reset every hand, like the real
  round). Workers never load the 55-round cache: the real side is computed once in one child process.

Compared, real (hh.py on the logs) vs sim (same lineups):
  * our bb/100 per round: real raw and all-in-luck adjusted (hh luck: all-in before the river with every
    showdown hand known -> equity share) vs the sim mean over seeds (the same adjustment, duel.analyse);
    bias = mean(sim - real) with its SE, correlation across rounds, and the same split R19-R29 vs R30-R54
    (most profiles use R30-R54 data only, so R19-R29 is closer to out-of-sample);
  * per-opponent chip flows: our adjusted chips from each team (zero-sum split per hand, duel.py's rule)
    per 100 hands with him, real vs sim, correlation across teams;
  * pooled opponent stats (all clones vs all real teams at the same tables): VPIP, PFR, 3-bet, fold to
    3-bet, c-bet, fold vs bet by street and size, WTSD, W$SD ..., plus the fold rate when facing OUR bet vs
    another opponent's bet, and 3-bets against OUR opens vs other opens (real teams adapt to us; clones are
    static frequency matchers);
  * our own stats (VPIP, fold vs bet, WTSD ...) and where our chips come from (outcome breakdown).
  * known exact real counterfactuals from the logs (always printed): 'fold every river bet we continued
    against' and 'never call a 3-bet after opening' (the out/v10_riverfold.py and out/v10_no3betcall.py
    copies). Run --cand with one of those copies to see whether the bench gets the size of a real
    difference right (the bench measures differences, so this is the check that matters for duel.py).
  With --cand the candidate is also played on every (lineup, seed) with the same deck and clone seeds
  (paired, like duel.py) and the paired difference is reported overall and per round.

With --adaptive [PARAMS] the clones are clone_adapt.make_agent(profile, seed, params, our seat) (see clone_adapt.py;
--no-hero-level drops the calibrated extra fold rate against our seat). With --adaptive (or --adaptive-checks on
static clones) an extra section compares, real vs sim on the same lineups: each team's 3-bet rate against our opens
and against others' (by quarter of the round), the fold rate of 3-bettors facing our 4-bets, and the fold rate
facing our bets by quarter of the round.

Output: a summary on stdout, out/simreal_<name>.txt and out/simreal_<name>.json.
Python 3.9+ standard library only.
"""
import argparse
import glob
import json
import math
import os
import re
import statistics
import sys
import time
import traceback
import zlib
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import duel as D  # noqa: E402  (engine glue, analysis; puts the kit on sys.path)
import hh as H  # noqa: E402
import clone as CL  # noqa: E402
import profiles as PR  # noqa: E402
import calibrate as CA  # noqa: E402  (write_round_json: sim logs in the real format)
import clone_adapt as CAD  # noqa: E402  (adaptive clones; used only with --adaptive)
from engine.game import FixedHandsTable  # noqa: E402

OUT_DIR = os.path.join(HERE, "out")
TMP_DIR = os.path.join(OUT_DIR, "sim", "_simreal_tmp")
PROF_DIR = os.path.join(HERE, "profiles")
LIVE_BOT = os.path.join(os.path.dirname(HERE), "v10", "bot.py")
HERO = "Durahim 1453"
BB = 20

STAT_ROWS = (["vpip", "pfr", "three_bet", "call_open", "fold_to_3bet", "four_bet", "call_jam", "limp", "iso_raise",
              "open_EP", "open_MP", "open_CO", "open_BTN", "open_SB", "cbet_flop", "cbet_turn", "donk_flop", "stab_flop"]
             + ["fold_vs_%s_%s" % (s, b) for s in ("flop", "turn", "river") for b in CL.BUCKETS]
             + ["raise_vs_bet_flop", "xr_flop", "fold_vs_raise_flop", "agg_flop", "agg_turn", "agg_river",
                "wtsd", "wsd", "allin_pf", "allin_post"])


def bb100(chips, hands):
    return chips / BB / hands * 100.0 if hands else 0.0


def mean_se(xs):
    xs = list(xs)
    if not xs:
        return float("nan"), float("nan")
    if len(xs) == 1:
        return xs[0], float("nan")
    return statistics.mean(xs), statistics.stdev(xs) / math.sqrt(len(xs))


def pearson(xs, ys, ws=None):
    n = len(xs)
    if n < 3:
        return float("nan")
    ws = ws or [1.0] * n
    W = sum(ws)
    mx = sum(w * x for w, x in zip(ws, xs)) / W
    my = sum(w * y for w, y in zip(ws, ys)) / W
    sxy = sum(w * (x - mx) * (y - my) for w, x, y in zip(ws, xs, ys))
    sxx = sum(w * (x - mx) ** 2 for w, x in zip(ws, xs))
    syy = sum(w * (y - my) ** 2 for w, y in zip(ws, ys))
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else float("nan")


def parse_rounds(spec):
    out = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


# =============================================================================== shared metrics on hh rounds
def facing_counts(r, hero):
    """Fold/call/raise counts when facing exactly one postflop bet, by street, size bucket of the bet and who
    bet: 'opp_vs_us' (an opponent facing OUR bet), 'opp_vs_opp', 'us_vs_opp'. Plus preflop: opponents'
    3-bets against our opens vs other opens, and openers' folds to our 3-bets vs other 3-bets."""
    c = Counter()
    for Hd in r.hands:
        st = -1
        bettor = None
        bfrac = None
        raisers = []                   # preflop raisers in order
        for A in Hd.acts:
            if A.st != st:
                st = A.st
                bettor = None
                bfrac = None
            if A.st == 0:
                if A.seat != hero and A.ctx == "vs_open" and A.first and raisers:
                    who = "us" if raisers[0] == hero else "other"
                    c["pf|3bet_vs_%s_open|n" % who] += 1
                    if A.a == "raise":
                        c["pf|3bet_vs_%s_open|R" % who] += 1
                if A.ctx == "vs_3bet" and len(raisers) == 2 and A.seat == raisers[0]:
                    if A.seat == hero:
                        who = "us_vs_opp"
                    else:
                        who = "opp_vs_us" if raisers[1] == hero else "opp_vs_opp"
                    c["pf|fold_to_3bet|%s|n" % who] += 1
                    if A.a == "fold":
                        c["pf|fold_to_3bet|%s|F" % who] += 1
                if A.a == "raise":
                    raisers.append(A.seat)
                continue
            if A.ctx == "vs_bet" and bettor is not None:
                if A.seat == hero:
                    who = "us_vs_opp"
                elif bettor == hero:
                    who = "opp_vs_us"
                else:
                    who = "opp_vs_opp"
                key = "%s|%s|%s" % (H.STREETS[A.st], who, CL.bucket(bfrac))
                c[key + "|n"] += 1
                c[key + "|" + A.a[0].upper()] += 1
            if A.a == "raise":
                if bettor is None:
                    bfrac = A.rfrac
                bettor = A.seat
    return c


def adapt_counts(r, hero):
    """Per-team checks for the adaptive mode (same code on real and sim logs): 3-bets facing OUR open vs other
    opens (first decision facing a single open, as facing_counts), by quarter of the round vs us; 3-bettors facing
    OUR 4-bet; folds facing OUR single postflop bet by quarter (big = > 0.55 pot)."""
    c = Counter()
    for Hd in r.hands:
        q = min(3, max(0, (Hd.num - 1) // 250))
        st = -1
        bettor = None
        bfrac = None
        raisers = []
        for A in Hd.acts:
            if A.st != st:
                st = A.st
                bettor = None
                bfrac = None
            if A.st == 0:
                if A.seat != hero and A.ctx == "vs_open" and A.first and raisers:
                    t = r.players[A.seat]
                    who = "us" if raisers[0] == hero else "oth"
                    c["tb|%s|%s|n" % (t, who)] += 1
                    c["tb|ALL|%s|n" % who] += 1
                    if A.a == "raise":
                        c["tb|%s|%s|R" % (t, who)] += 1
                        c["tb|ALL|%s|R" % who] += 1
                    if who == "us":
                        c["tbq|%s|%d|n" % (t, q)] += 1
                        c["tbq|ALL|%d|n" % q] += 1
                        if A.a == "raise":
                            c["tbq|%s|%d|R" % (t, q)] += 1
                            c["tbq|ALL|%d|R" % q] += 1
                if A.ctx == "vs_4bet+" and len(raisers) == 3 and A.seat == raisers[1] and raisers[2] == hero \
                        and A.seat != hero:
                    t = r.players[A.seat]
                    c["f4|%s|n" % t] += 1
                    c["f4|ALL|n"] += 1
                    if A.a == "fold":
                        c["f4|%s|F" % t] += 1
                        c["f4|ALL|F"] += 1
                if A.a == "raise":
                    raisers.append(A.seat)
                continue
            if A.ctx == "vs_bet" and bettor == hero and A.seat != hero:
                k = "fq|%s|%d" % ("big" if (bfrac or 0) > CAD.BIG_FRAC else "small", q)
                c[k + "|n"] += 1
                if A.a == "fold":
                    c[k + "|F"] += 1
            if A.a == "raise":
                if bettor is None:
                    bfrac = A.rfrac
                bettor = A.seat
    return dict(c)


def tally_and_facing(r, hero):
    tallies = defaultdict(PR.new_tally)
    seats = {s: ("hero" if s == hero else "opp") for s in range(r.n)}
    PR.tally_round(r, seats, tallies, showdown=False)
    return {k: PR.tally_to_json(v) for k, v in tallies.items()}, dict(facing_counts(r, hero))


def real_round_metrics(r):
    """Real side of one round (hh Round with luck): our raw/adjusted chips, per-opponent zero-sum flows
    (duel.analyse's rule: only hands where we reached an all-in showdown are equity-adjusted), tallies."""
    hero = r.seat
    n = r.n
    names = list(r.players)
    names[hero] = "<us>"
    chips = 0
    adj = 0.0
    sq = 0.0
    vs_adj = defaultdict(float)
    vs_raw = defaultdict(float)
    vs_sq = defaultdict(float)
    vs_hands = Counter()
    opp_chips = Counter()
    cf_river = [0, 0.0, 0.0]  # hands changed, chip delta, sum of squared deltas: fold at our first river decision
    cf_3bet = [0, 0.0, 0.0]   # facing a bet / fold instead of calling a 3-bet after opening
    for Hd in r.hands:
        res = Hd.results
        luck = Hd.luck
        a = res[hero] - luck[hero]
        chips += res[hero]
        adj += a
        sq += a * a
        ares = [res[s] - luck[s] for s in range(n)] if hero in Hd.went_sd else list(res)
        acc = defaultdict(float)
        D._split(acc, ares, hero, names, a)
        accr = defaultdict(float)
        D._split(accr, res, hero, names, res[hero])
        for j in range(n):
            if j == hero:
                continue
            nm = names[j]
            v = acc.get(nm, 0.0)
            vs_hands[nm] += 1
            vs_adj[nm] += v
            vs_sq[nm] += v * v
            vs_raw[nm] += accr.get(nm, 0.0)
            opp_chips[nm] += res[j]
        # exact counterfactuals (the hand ends for us at that decision; nothing else changes)
        raisers = []
        river_done = False
        for A in Hd.acts:
            if A.seat == hero:
                if (A.st == 0 and A.a == "call" and A.to_call > 0 and len(raisers) == 2 and raisers[0] == hero
                        and raisers[1] != hero):
                    dlt = -(2000 - A.stack) - a
                    cf_3bet[0] += 1
                    cf_3bet[1] += dlt
                    cf_3bet[2] += dlt * dlt
                if A.st == 3 and A.to_call > 0 and not river_done:
                    river_done = True
                    if A.a in ("call", "raise"):
                        dlt = -(2000 - A.stack) - a
                        cf_river[0] += 1
                        cf_river[1] += dlt
                        cf_river[2] += dlt * dlt
            if A.st == 0 and A.a == "raise":
                raisers.append(A.seat)
    tallies, facing = tally_and_facing(r, hero)
    return {"label": r.label, "rnum": r.rnum, "n": n, "players": list(r.players), "seat": hero, "hands": len(r.hands),
            "chips": chips, "adj": adj, "adj_sq": sq, "vs_adj": dict(vs_adj), "vs_raw": dict(vs_raw),
            "vs_sq": dict(vs_sq), "vs_hands": dict(vs_hands), "opp_chips": dict(opp_chips),
            "cf_river": cf_river, "cf_3bet": cf_3bet, "tallies": tallies, "facing": facing,
            "adapt": adapt_counts(r, hero)}


def real_side_job(labels):
    """Runs in a child process: load the cached logs once (~1 GB), return compact per-round metrics."""
    rounds = H.load_all()
    out = {}
    for r in rounds:
        if not r.practice and r.label in labels:
            out[r.label] = real_round_metrics(r)
    return out


# =============================================================================== sim side (workers)
_PROF_TXT = {}
_PROF = {}
_ADAPT = {}


def _init_worker(prof_txt, bot_code, adapt_params=None):
    _PROF_TXT.update(prof_txt)
    D._BOT_CODE.update(bot_code)
    if adapt_params is not None:
        _ADAPT["params"] = adapt_params


def _profile(key):
    p = _PROF.get(key)
    if p is None:
        p = _PROF[key] = json.loads(_PROF_TXT[key])
    return p


def play(job, which):
    path = job[which]
    mod = D.load_module(path, which)
    hero_seat = job["seat"]
    players = []
    for s, (nm, pk) in enumerate(zip(job["names"], job["prof_keys"])):
        if s == hero_seat:
            players.append(D.Seat(mod.Agent(), "<us>", hero=True))
        elif _ADAPT.get("params") is not None:
            players.append(D.Seat(CAD.make_agent(_profile(pk), job["clone_seed"], _ADAPT["params"], hero_seat), nm))
        else:
            players.append(D.Seat(CL.make_agent(_profile(pk), job["clone_seed"]), nm))
    names = [p.name for p in players]
    rng = D.DeckRecorder(job["engine_seed"])
    t0 = time.perf_counter()
    res = FixedHandsTable(players, hands=job["hands"], record=True, rng=rng).play()
    wall = time.perf_counter() - t0
    log = res["log"]
    st = D.analyse(log, hero_seat, names, D.new_stats())
    if st["chips"] != res["chips"][hero_seat] or sum(res["chips"]) != 0:
        raise RuntimeError("chip accounting mismatch")
    hero = players[hero_seat]
    meta = {"wall_s": round(wall, 3), "think_s": round(hero.think, 3), "errors": hero.errors,
            "first_error": hero.first_error, "opp_errors": sum(p.errors for p in players if not p.hero),
            "deck": rng.digest.hexdigest()[:16]}
    D.drop_module(mod)
    return st, log, meta, res["chips"]


def tally_sim(log, job, chips, think_s):
    os.makedirs(TMP_DIR, exist_ok=True)
    path = os.path.join(TMP_DIR, "%d_%s_s%d.json" % (os.getpid(), re.sub(r"\W", "_", job["label"]), job["seed"]))
    names = list(job["names"])
    names[job["seat"]] = HERO
    CA.write_round_json(path, "simreal/%s/s%d" % (job["label"], job["seed"]), names, job["seat"], log,
                        chips[job["seat"]], think_s, job["hands"])
    try:
        r = H.load_round(path, with_luck=False)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    t, f = tally_and_facing(r, job["seat"])
    return t, f, adapt_counts(r, job["seat"])


def run_job(job):
    try:
        out = {"label": job["label"], "seed": job["seed"]}
        whiches = ["base"] + (["cand"] if job.get("cand") else [])
        if job["idx"] % 2 and len(whiches) == 2:
            whiches.reverse()
        logs = {}
        for which in whiches:
            st, log, meta, chips = play(job, which)
            rec = {"chips": st["chips"], "adj": st["adj"], "hands": st["hands"], "vs": dict(st["vs"]),
                   "vs_adj": dict(st["vs_adj"]), "vs_hands": dict(st["vs_hands"]), "opp_chips": dict(st["opp_chips"]),
                   "end": st["end"], "allin_hands": st["allin_hands"], "meta": meta}
            if which == "base" and job["tally"]:
                rec["tallies"], rec["facing"], rec["adapt"] = tally_sim(log, job, chips, meta["think_s"])
            out[which] = rec
            logs[which] = log
        if len(logs) == 2:
            out["deck_same"] = out["base"]["meta"]["deck"] == out["cand"]["meta"]["deck"]
            out["divergence"] = D.first_divergence(logs["cand"], logs["base"], job["seat"])
        return out
    except Exception:
        return {"label": job["label"], "seed": job["seed"], "failed": traceback.format_exc(limit=8)}


# =============================================================================== aggregation / report
def merge_tallies(dst, src_json):
    for k, tj in src_json.items():
        PR.merge_tally(dst[k], PR.tally_from_json(tj))


def stat_table(real_t, sim_t):
    rk = PR.key_stats(real_t)
    sk = PR.key_stats(sim_t)
    rows = []
    for k in STAT_ROWS:
        rv, rn = rk.get(k, (None, 0))
        sv, sn = sk.get(k, (None, 0))
        z = CA.zdiff(rv, rn, sv, sn)
        rows.append({"stat": k, "real": rv, "n_real": rn, "sim": sv, "n_sim": sn,
                     "diff_pp": (sv - rv) * 100 if (rv is not None and sv is not None) else None, "z": z})
    return rows


def facing_table(real_c, sim_c):
    keys = sorted({k.rsplit("|", 1)[0] for k in list(real_c) + list(sim_c) if k.endswith("|n")})
    rows = []
    for k in keys:
        act = "R" if "3bet_vs" in k else "F"
        rn, sn = real_c.get(k + "|n", 0), sim_c.get(k + "|n", 0)
        rv = real_c.get(k + "|" + act, 0) / rn if rn else None
        sv = sim_c.get(k + "|" + act, 0) / sn if sn else None
        rows.append({"spot": k, "act": act, "real": rv, "n_real": rn, "sim": sv, "n_sim": sn,
                     "diff_pp": (sv - rv) * 100 if (rv is not None and sv is not None) else None,
                     "z": CA.zdiff(rv, rn, sv, sn)})
    return rows


def pct(v):
    return "    -" if v is None else "%5.1f" % (100 * v)


def adaptive_section(L, ra, sa):
    """Real vs sim per-team checks for the adaptive mode (counters from adapt_counts)."""
    def r_(c, k, a):
        n = c.get(k + "|n", 0)
        return (c.get(k + "|" + a, 0) / n if n else None), n
    out = {"threebet": {}, "threebet_quarters": {}, "fold_to_our_4bet": {}, "fold_vs_our_bets_quarters": {}}
    L.append("\nADAPTIVE CHECKS (real logs vs sim on the same lineups; 3-bet = raise at the first decision facing a single"
             " open, jams included)")
    L.append("%-26s %20s %20s | %20s %20s | %s" % ("3-bet % vs OUR opens", "real", "sim", "vs others real", "sim",
                                                 "by quarter vs us: real | sim"))
    teams = sorted({k.split("|")[1] for k in list(ra) + list(sa) if k.startswith("tb|")},
                   key=lambda t: (t != "ALL", -(ra.get("tb|%s|us|n" % t, 0))))
    for t in teams:
        ru, nu = r_(ra, "tb|%s|us" % t, "R")
        su, snu = r_(sa, "tb|%s|us" % t, "R")
        ro, no = r_(ra, "tb|%s|oth" % t, "R")
        so, sno = r_(sa, "tb|%s|oth" % t, "R")
        if (nu or 0) < 40 and t != "ALL":
            continue
        qr = [r_(ra, "tbq|%s|%d" % (t, q), "R")[0] for q in range(4)]
        qs = [r_(sa, "tbq|%s|%d" % (t, q), "R")[0] for q in range(4)]
        out["threebet"][t] = {"real_vs_us": ru, "n_real_vs_us": nu, "sim_vs_us": su, "n_sim_vs_us": snu,
                              "real_vs_others": ro, "sim_vs_others": so}
        out["threebet_quarters"][t] = {"real": qr, "sim": qs}
        L.append("%-26s %20s %20s | %20s %20s | %s | %s" % (
            t[:26], "%s (%5d)" % (pct(ru), nu), "%s (%6d)" % (pct(su), snu), "%s (%5d)" % (pct(ro), no),
            "%s (%6d)" % (pct(so), sno), " ".join(pct(x) for x in qr), " ".join(pct(x) for x in qs)))
    L.append("%-26s %20s %20s" % ("3-bettor folds to OUR 4-bet", "real", "sim"))
    f4 = sorted({k.split("|")[1] for k in list(ra) + list(sa) if k.startswith("f4|")},
                key=lambda t: (t != "ALL", -(ra.get("f4|%s|n" % t, 0))))
    for t in f4:
        rv, rn = r_(ra, "f4|%s" % t, "F")
        sv, sn = r_(sa, "f4|%s" % t, "F")
        if (rn or 0) < 8 and t != "ALL":
            continue
        out["fold_to_our_4bet"][t] = {"real": rv, "n_real": rn, "sim": sv, "n_sim": sn}
        L.append("%-26s %20s %20s" % (t[:26], "%s (%5d)" % (pct(rv), rn), "%s (%6d)" % (pct(sv), sn)))
    L.append("fold facing OUR single postflop bet, by quarter of the round (real | sim)")
    for sz in ("big", "small"):
        row_r = [r_(ra, "fq|%s|%d" % (sz, q), "F") for q in range(4)]
        row_s = [r_(sa, "fq|%s|%d" % (sz, q), "F") for q in range(4)]
        out["fold_vs_our_bets_quarters"][sz] = {"real": [x[0] for x in row_r], "sim": [x[0] for x in row_s]}
        L.append("  %-5s (%s pot) real %s | sim %s" % (sz, "> 0.55" if sz == "big" else "<= 0.55",
                                                     " ".join("%s (%d)" % (pct(v), n) for v, n in row_r),
                                                     " ".join("%s (%d)" % (pct(v), n) for v, n in row_s)))
    return out


def build_report(args, real, rounds, jobs, results, fallback_used, insample, elapsed):
    ok = [r for r in results if "failed" not in r]
    failed = [r for r in results if "failed" in r]
    by_round = defaultdict(list)
    for r in ok:
        by_round[r["label"]].append(r)
    L = []
    rep = {"config": {k: v for k, v in vars(args).items()}, "fallback_used": fallback_used, "failed": len(failed),
           "elapsed_s": round(elapsed, 1)}
    L.append("SIM-TO-REAL: %s in our seat, %sclones of the real teams in their real seats, %d real rounds x %d seeds "
             "x %d hands (%d tables%s), %.0fs" % (D.label_of(args.bot),
                                                  ("ADAPTIVE (%s%s%s) " % (os.path.relpath(args.adaptive, HERE),
                                                                           ", no hero level" if args.no_hero_level else "",
                                                                           (", off: " + args.adaptive_off)
                                                                           if args.adaptive_off else ""))
                                                  if args.adaptive else "", len(rounds), args.seeds, args.hands, len(ok),
                                                  (", %d FAILED" % len(failed)) if failed else "", elapsed))
    if fallback_used:
        L.append("teams without a profile -> '%s' profile: %s" % (args.fallback, ", ".join(
            "%s (%s)" % (t, ",".join(sorted(v))) for t, v in sorted(fallback_used.items()))))
    else:
        L.append("every opponent in these rounds has its own profile (no '%s' fallback needed)" % args.fallback)
    # ---------------------------------------------------------------- per round
    L.append("\nPER ROUND (bb/100; real adj = luck-adjusted; sim = mean over seeds of the adjusted result; in-sample ="
             " opponents whose profile data includes this round)")
    L.append("%-5s %2s %9s %9s %16s %9s %6s %9s" % ("round", "n", "real raw", "real adj", "sim adj +-SE", "sim-real",
                                                  "z", "in-sample"))
    rows = []
    for lab in rounds:
        rr = real[lab]
        sims = by_round.get(lab, [])
        if not sims:
            continue
        s_adj = [bb100(x["base"]["adj"], x["base"]["hands"]) for x in sims]
        s_raw = [bb100(x["base"]["chips"], x["base"]["hands"]) for x in sims]
        sm, sse = mean_se(s_adj)
        real_adj = bb100(rr["adj"], rr["hands"])
        real_raw = bb100(rr["chips"], rr["hands"])
        var_h = max(0.0, rr["adj_sq"] / rr["hands"] - (rr["adj"] / rr["hands"]) ** 2)
        rse = math.sqrt(var_h / rr["hands"]) / BB * 100
        z = (sm - real_adj) / math.sqrt(rse ** 2 + (sse if sse == sse else 0) ** 2)
        row = {"round": lab, "rnum": rr["rnum"], "n": rr["n"], "real_raw": real_raw, "real_adj": real_adj,
               "real_se": rse, "sim_adj": sm, "sim_se": sse, "sim_raw": statistics.mean(s_raw), "diff": sm - real_adj,
               "z": z, "in_sample": insample[lab], "seeds": len(sims)}
        rows.append(row)
        L.append("%-5s %2d %+9.1f %+9.1f %+9.1f +-%4.1f %+9.1f %+6.2f %5d/%d" % (
            lab, rr["n"], real_raw, real_adj, sm, sse if sse == sse else 0, sm - real_adj, z, insample[lab], rr["n"] - 1))
    rep["rounds"] = rows

    def block(sel, title):
        if not sel:
            return None
        ra = [x["real_adj"] for x in sel]
        rr_ = [x["real_raw"] for x in sel]
        sa = [x["sim_adj"] for x in sel]
        # SE of the mean real result: per-hand variance pooled over the rounds
        n_h = sum(real[x["round"]]["hands"] for x in sel)
        s1 = sum(real[x["round"]]["adj"] for x in sel)
        s2 = sum(real[x["round"]]["adj_sq"] for x in sel)
        real_mean = bb100(s1, n_h)
        real_se = math.sqrt(max(0.0, s2 / n_h - (s1 / n_h) ** 2) / n_h) / BB * 100
        tabs = [bb100(t["base"]["adj"], t["base"]["hands"]) for x in sel for t in by_round[x["round"]]]
        sim_mean, sim_se = mean_se(tabs)
        bias = sim_mean - real_mean
        bse = math.sqrt(real_se ** 2 + sim_se ** 2)
        corr = pearson(sa, ra)
        # noise ceiling: the best correlation a perfect simulator could reach given the real per-round noise
        var_sim = statistics.pvariance(sa) if len(sa) > 1 else 0.0
        sig = max(0.0, var_sim - statistics.mean([(x["sim_se"] if x["sim_se"] == x["sim_se"] else 0) ** 2 for x in sel]))
        noise = statistics.mean([x["real_se"] ** 2 for x in sel])
        ceiling = math.sqrt(sig / (sig + noise)) if sig + noise > 0 else float("nan")
        d = {"rounds": len(sel), "real_raw_mean": statistics.mean(rr_), "real_adj_mean": real_mean,
             "real_adj_se": real_se, "sim_adj_mean": sim_mean, "sim_adj_se": sim_se, "bias": bias, "bias_se": bse,
             "bias_z": bias / bse if bse > 0 else None, "ratio_sim_over_real": sim_mean / real_mean if real_mean else None,
             "corr_rounds": corr, "corr_ceiling": ceiling, "sd_sim_round_means": math.sqrt(var_sim),
             "real_round_noise_se": math.sqrt(noise)}
        L.append("  %-10s %2d rounds: real adj %+6.1f +-%4.1f (raw %+6.1f) | sim %+6.1f +-%4.1f | bias sim-real %+6.1f "
                 "+-%4.1f (z %+.1f) | corr across rounds %+.2f (ceiling ~%.2f: real per-round noise SE %.0f, sim spread of"
                 " round means SD %.1f)" % (title, len(sel), real_mean, real_se, d["real_raw_mean"], sim_mean, sim_se,
                                            bias, bse, d["bias_z"] or 0, corr, ceiling, d["real_round_noise_se"],
                                            d["sd_sim_round_means"]))
        return d

    L.append("\nTOTALS (bb/100)")
    rep["totals"] = {"all": block(rows, "all"),
                     "R19-R29": block([x for x in rows if x["rnum"] <= 29], "R19-R29"),
                     "R30-R54": block([x for x in rows if x["rnum"] >= 30], "R30-R54")}
    # ---------------------------------------------------------------- per opponent
    opp = defaultdict(lambda: {"real_chips": 0.0, "real_sq": 0.0, "real_hands": 0, "real_his": 0, "sim_chips": 0.0,
                               "sim_hands": 0, "sim_his": 0, "sim_tables": [], "rounds": 0})
    for lab in rounds:
        rr = real[lab]
        if lab not in by_round:
            continue
        for nm, hnd in rr["vs_hands"].items():
            o = opp[nm]
            o["rounds"] += 1
            o["real_chips"] += rr["vs_adj"].get(nm, 0.0)
            o["real_sq"] += rr["vs_sq"].get(nm, 0.0)
            o["real_hands"] += hnd
            o["real_his"] += rr["opp_chips"].get(nm, 0)
        for t in by_round[lab]:
            b = t["base"]
            for nm, hnd in b["vs_hands"].items():
                o = opp[nm]
                o["sim_chips"] += b["vs_adj"].get(nm, 0.0)
                o["sim_hands"] += hnd
                o["sim_his"] += b["opp_chips"].get(nm, 0)
                o["sim_tables"].append(bb100(b["vs_adj"].get(nm, 0.0), hnd))
    orows = []
    for nm, o in opp.items():
        if not o["real_hands"] or not o["sim_hands"]:
            continue
        rv = bb100(o["real_chips"], o["real_hands"])
        var_h = max(0.0, o["real_sq"] / o["real_hands"] - (o["real_chips"] / o["real_hands"]) ** 2)
        rse = math.sqrt(var_h / o["real_hands"]) / BB * 100
        sv = bb100(o["sim_chips"], o["sim_hands"])
        sse = mean_se(o["sim_tables"])[1]
        sse = sse if sse == sse else 0.0
        orows.append({"team": nm, "rounds": o["rounds"], "real_hands": o["real_hands"], "real_flow": rv, "real_se": rse,
                      "sim_flow": sv, "sim_se": sse, "diff": sv - rv, "z": (sv - rv) / math.sqrt(rse ** 2 + sse ** 2),
                      "real_his_bb100": bb100(o["real_his"], o["real_hands"]),
                      "sim_his_bb100": bb100(o["sim_his"], o["sim_hands"]), "fallback": nm in fallback_used})
    orows.sort(key=lambda x: -x["real_hands"])
    rep["per_opponent"] = orows
    L.append("\nPER OPPONENT: our all-in adjusted chips from him (zero-sum split) per 100 hands with him, real vs sim; his"
             " own raw bb/100 at those tables")
    L.append("%-26s %3s %6s %15s %15s %8s %6s | %8s %8s" % ("team", "rds", "hands", "real flow +-SE", "sim flow +-SE",
                                                         "sim-real", "z", "his real", "his sim"))
    for x in orows:
        L.append("%-26s %3d %6d %+8.1f +-%4.1f %+8.1f +-%4.1f %+8.1f %+6.2f | %+8.1f %+8.1f%s" % (
            x["team"][:26], x["rounds"], x["real_hands"], x["real_flow"], x["real_se"], x["sim_flow"], x["sim_se"],
            x["diff"], x["z"], x["real_his_bb100"], x["sim_his_bb100"], "  (fallback profile)" if x["fallback"] else ""))
    big = [x for x in orows if x["real_hands"] >= 2000]
    if len(big) >= 3:
        w = [x["real_hands"] for x in big]
        c_all = pearson([x["sim_flow"] for x in big], [x["real_flow"] for x in big], w)
        mid = [x for x in big if abs(x["real_his_bb100"]) < 100]
        c_mid = pearson([x["sim_flow"] for x in mid], [x["real_flow"] for x in mid], [x["real_hands"] for x in mid])
        c_his = pearson([x["sim_his_bb100"] for x in big], [x["real_his_bb100"] for x in big], w)
        c_his_mid = pearson([x["sim_his_bb100"] for x in mid], [x["real_his_bb100"] for x in mid],
                            [x["real_hands"] for x in mid])
        chi = sum(x["z"] ** 2 for x in big)
        rep["per_opponent_summary"] = {"teams": len(big), "corr_our_flow": c_all, "corr_our_flow_excl_megadonors": c_mid,
                                       "corr_his_result": c_his, "corr_his_result_excl_megadonors": c_his_mid,
                                       "teams_excl": len(mid), "sum_z2": chi,
                                       "teams_abs_z_gt2": sum(1 for x in big if abs(x["z"]) > 2)}
        L.append("teams with >= 2000 hands: %d | hand-weighted correlation sim vs real of OUR flow %.2f (%.2f without the "
                 "%d teams whose own result is beyond +-100 bb/100) | of HIS own result %.2f (%.2f without them) | |z| > 2 for %d teams "
                 "(sum z^2 %.0f on %d)" % (len(big), c_all, c_mid, len(big) - len(mid), c_his, c_his_mid,
                                           rep["per_opponent_summary"]["teams_abs_z_gt2"], chi, len(big)))
    # ---------------------------------------------------------------- stats
    if args.tally:
        real_t = defaultdict(PR.new_tally)
        sim_t = defaultdict(PR.new_tally)
        real_f = Counter()
        sim_f = Counter()
        for lab in rounds:
            if lab not in by_round:
                continue
            merge_tallies(real_t, real[lab]["tallies"])
            real_f.update(real[lab]["facing"])
            for t in by_round[lab]:
                merge_tallies(sim_t, t["base"]["tallies"])
                sim_f.update(t["base"]["facing"])
        orow = stat_table(real_t["opp"], sim_t["opp"])
        hrow = stat_table(real_t["hero"], sim_t["hero"])
        frow = facing_table(real_f, sim_f)
        rep["opp_stats"] = orow
        rep["hero_stats"] = hrow
        rep["facing"] = frow
        rep["hero_outcomes"] = {"real": PR.outcome_breakdown(real_t["hero"]["stats"]),
                                "sim": PR.outcome_breakdown(sim_t["hero"]["stats"])}
        L.append("\nPOOLED STATS, opponents (real teams vs their clones at the same tables) and us; % (n real / n sim);"
                 " * = off by > 3pp and |z| >= 2")
        L.append("%-20s %22s %22s | %22s %22s" % ("stat", "opponents real", "clones sim", "us real", "us sim"))
        for a, b in zip(orow, hrow):
            def cell(v, n):
                return "%s (%6d)" % (pct(v), n)
            fa = "*" if (a["diff_pp"] is not None and abs(a["diff_pp"]) > 3 and a["z"] is not None and abs(a["z"]) >= 2) else " "
            fb = "*" if (b["diff_pp"] is not None and abs(b["diff_pp"]) > 3 and b["z"] is not None and abs(b["z"]) >= 2) else " "
            L.append("%-20s %22s %21s%s | %22s %21s%s" % (a["stat"], cell(a["real"], a["n_real"]), cell(a["sim"], a["n_sim"]), fa,
                                                       cell(b["real"], b["n_real"]), cell(b["sim"], b["n_sim"]), fb))
        okc = [a for a in orow if a["n_real"] >= 100 and a["n_sim"] >= 100 and a["diff_pp"] is not None]
        if okc:
            within = sum(1 for a in okc if abs(a["diff_pp"]) <= 3)
            L.append("opponent stats with n >= 100: %d/%d within 3pp, mean |diff| %.1fpp" % (
                within, len(okc), statistics.mean(abs(a["diff_pp"]) for a in okc)))
            rep["opp_stats_within_3pp"] = [within, len(okc)]
        L.append("\nFACING A BET, by who bet (opp_vs_us = an opponent facing OUR bet). Fold % (n); preflop: 3-bet % vs"
                 " opens and fold % of the opener vs a 3-bet")
        L.append("%-34s %18s %18s %8s %6s" % ("spot", "real", "sim", "sim-real", "z"))
        for x in frow:
            if x["n_real"] < 30 and x["n_sim"] < 30:
                continue
            L.append("%-34s %8s (%7d) %8s (%7d) %+8.1f %+6.1f" % (
                x["spot"] + " " + x["act"], pct(x["real"]), x["n_real"], pct(x["sim"]), x["n_sim"],
                x["diff_pp"] if x["diff_pp"] is not None else float("nan"), x["z"] if x["z"] is not None else float("nan")))
        L.append("\nWHERE OUR CHIPS GO (bb/100 by how the hand ended for us; share of hands)")
        hr, hs = rep["hero_outcomes"]["real"], rep["hero_outcomes"]["sim"]
        for oc in PR.OUTCOMES:
            a, b = hr.get(oc), hs.get(oc)
            if a and b:
                L.append("  %-26s real %+7.1f (%5.1f%%)   sim %+7.1f (%5.1f%%)   sim-real %+6.1f" % (
                    PR.OUTCOME_NAMES[oc], a["bb100"], 100 * a["share"], b["bb100"], 100 * b["share"], b["bb100"] - a["bb100"]))
        if args.adaptive or args.adaptive_checks:
            ra = Counter()
            sa = Counter()
            for lab in rounds:
                if lab not in by_round:
                    continue
                ra.update(real[lab].get("adapt") or {})
                for t in by_round[lab]:
                    sa.update(t["base"].get("adapt") or {})
            rep["adaptive_checks"] = adaptive_section(L, ra, sa)
    # ---------------------------------------------------------------- exact real counterfactuals
    n_h = sum(real[lab]["hands"] for lab in rounds if lab in by_round)

    def cf_total(key):
        k = sum(real[lab][key][0] for lab in rounds if lab in by_round)
        s1 = sum(real[lab][key][1] for lab in rounds if lab in by_round)
        s2 = sum(real[lab][key][2] for lab in rounds if lab in by_round)
        se = math.sqrt(max(0.0, s2 - s1 * s1 / n_h)) if n_h else 0.0      # SE of the total over n_h hands
        return {"hands": k, "chips": s1, "chips_se": se, "bb100": bb100(s1, n_h), "bb100_se": bb100(se, n_h)}
    cfr = cf_total("cf_river")
    cf3 = cf_total("cf_3bet")
    rep["real_counterfactuals"] = {"fold_every_river_bet_we_continued_against": cfr, "never_call_3bet_after_opening": cf3,
                                   "hands": n_h}
    L.append("\nEXACT REAL COUNTERFACTUALS on these rounds (hh.py, luck-adjusted; the hand ends for us at that decision;"
             " +- = sampling SE of which hands came up)")
    L.append("  fold at our first river decision facing a bet (= out/v10_riverfold.py): %d hands changed, %+.0f chips = "
             "%+.2f +- %.2f bb/100" % (cfr["hands"], cfr["chips"], cfr["bb100"], cfr["bb100_se"]))
    L.append("  fold instead of calling a 3-bet after opening (= out/v10_no3betcall.py): %d hands changed, %+.0f chips = "
             "%+.2f +- %.2f bb/100" % (cf3["hands"], cf3["chips"], cf3["bb100"], cf3["bb100_se"]))
    # ---------------------------------------------------------------- candidate
    if args.cand:
        pairs = [r for r in ok if "cand" in r]
        d_adj = [bb100(r["cand"]["adj"], r["cand"]["hands"]) - bb100(r["base"]["adj"], r["base"]["hands"]) for r in pairs]
        d_raw = [bb100(r["cand"]["chips"], r["cand"]["hands"]) - bb100(r["base"]["chips"], r["base"]["hands"]) for r in pairs]
        am, ase = mean_se(d_adj)
        rm, rse_ = mean_se(d_raw)
        per_r = defaultdict(list)
        for r, x in zip(pairs, d_adj):
            per_r[r["label"]].append(x)
        _, cse = mean_se([statistics.mean(v) for v in per_r.values()])
        viol = sum(1 for r in pairs if r.get("divergence") and not r["divergence"]["ok"])
        decks = all(r.get("deck_same") for r in pairs)
        rep["candidate"] = {"cand": args.cand, "pairs": len(pairs), "diff_adj": am, "diff_adj_se": ase,
                            "diff_adj_se_round_clustered": cse, "diff_raw": rm, "diff_raw_se": rse_,
                            "cand_adj": statistics.mean(bb100(r["cand"]["adj"], r["cand"]["hands"]) for r in pairs),
                            "base_adj": statistics.mean(bb100(r["base"]["adj"], r["base"]["hands"]) for r in pairs),
                            "decks_identical": decks, "determinism_violations": viol,
                            "per_round": {k: statistics.mean(v) for k, v in per_r.items()}}
        L.append("\nCANDIDATE %s vs %s on the real lineups (paired, same decks and clone seeds): adj diff %+.2f +- %.2f "
                 "bb/100 (round-clustered SE %.2f), raw %+.2f +- %.2f | %d pairs, decks identical %s, determinism "
                 "violations %d" % (D.label_of(args.cand), D.label_of(args.bot), am, ase, cse, rm, rse_, len(pairs),
                                    decks, viol))
    if failed:
        L.append("\nFAILED jobs: %d; first:\n%s" % (len(failed), failed[0]["failed"]))
    return L, rep


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], epilog="Details: the module docstring.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bot", default=LIVE_BOT, help="bot in our seat (default: the live bot v10/bot.py, the bot that "
                                                    "played these rounds)")
    ap.add_argument("--cand", help="optional candidate, played paired against --bot on every lineup and seed")
    ap.add_argument("--rounds", default="19-54", help="real rounds to rebuild, e.g. 19-54 or 19-25,33 (default 19-54)")
    ap.add_argument("--versions", default="17", help="site versions whose rounds are used (default 17 = v10/bot.py)")
    ap.add_argument("--seeds", type=int, default=6, help="deal seeds per round (default 6)")
    ap.add_argument("--seed0", type=int, default=1)
    ap.add_argument("--hands", type=int, default=1000, help="hands per table (default 1000 = the real round)")
    ap.add_argument("--fallback", default="field", choices=["field", "donor"],
                    help="profile for teams without their own profile (default field)")
    ap.add_argument("--no-tally", dest="tally", action="store_false", help="skip the pooled-stats part (faster)")
    ap.add_argument("--procs", type=int, default=6, help="worker processes (max 6)")
    ap.add_argument("--name", help="output name: out/simreal_<name>.json/.txt (default from the bot names)")
    ap.add_argument("--adaptive", nargs="?", const=os.path.join(HERE, "adaptive", "params.json"), default=None,
                    metavar="PARAMS", help="ADAPTIVE clones (clone_adapt.py) with these parameters (default "
                                           "adaptive/params.json); default off = the static clones")
    ap.add_argument("--no-hero-level", action="store_true",
                    help="with --adaptive: switch off the calibrated static extra fold rate against our seat")
    ap.add_argument("--adaptive-checks", action="store_true",
                    help="print the ADAPTIVE CHECKS section also for static clones (needs the tally)")
    ap.add_argument("--adaptive-off", default="", metavar="LIST",
                    help="with --adaptive: comma list of components to switch off: postflop, shown, hero, exploit3, "
                         "fold3, union, light4 (clone_adapt.COMPONENTS)")
    args = ap.parse_args()
    if (args.no_hero_level or args.adaptive_off) and not args.adaptive:
        ap.error("--no-hero-level / --adaptive-off need --adaptive")
    adapt_params = None
    if args.adaptive:
        args.adaptive = os.path.abspath(args.adaptive)
        with open(args.adaptive) as fh:
            adapt_params = json.load(fh)
        if args.no_hero_level:
            adapt_params["hero_level"] = {"note": "switched off (--no-hero-level)"}
        off = [x.strip() for x in args.adaptive_off.split(",") if x.strip()]
        if off:
            adapt_params = CAD.variant(adapt_params, off)
    args.bot = os.path.abspath(args.bot)
    args.cand = os.path.abspath(args.cand) if args.cand else None
    for p in [args.bot] + ([args.cand] if args.cand else []):
        if not os.path.isfile(p):
            sys.exit("no such bot file: %s" % p)
    procs = max(1, min(6, args.procs))
    rnums = parse_rounds(args.rounds)
    versions = {int(v) for v in args.versions.split(",") if v.strip()}
    # rounds to rebuild: read only the small metadata of each log
    sel = []
    for path in sorted(glob.glob(os.path.join(H.HANDS_DIR, "*.json"))):
        if "practice" in os.path.basename(path):
            continue
        m = re.search(r"r0*(\d+)\.json$", path)
        if not m or int(m.group(1)) not in rnums:
            continue
        with open(path) as fh:
            d = json.load(fh)
        if (d.get("round") or {}).get("version") not in versions:
            continue
        sel.append(("R%d" % int(m.group(1)), d["players"], d["seat"], len(d["hands"])))
    if not sel:
        sys.exit("no real rounds selected (rounds %s, versions %s)" % (args.rounds, sorted(versions)))
    with open(os.path.join(PROF_DIR, "index.json")) as fh:
        index = json.load(fh)
    need = {}
    fallback_used = defaultdict(set)
    insample = {}
    prof_rounds = {}
    for lab, players, seat, _ in sel:
        cnt = 0
        for s, nm in enumerate(players):
            if s == seat:
                continue
            if nm in index and index[nm].get("kind", "team") == "team":
                key = nm
            else:
                key = args.fallback
                fallback_used[nm].add(lab)
            if key not in need:
                with open(os.path.join(PROF_DIR, index[key]["slug"] + ".json")) as fh:
                    need[key] = fh.read()
                prof_rounds[key] = set((json.loads(need[key]).get("data") or {}).get("rounds") or [])
            if lab in prof_rounds.get(key, ()):
                cnt += 1
        insample[lab] = cnt
    bot_code = {}
    for p in [args.bot] + ([args.cand] if args.cand else []):
        with open(p) as fh:
            bot_code[p] = fh.read()
    jobs = []
    for i, (lab, players, seat, nh) in enumerate(sel):
        keys = [None if s == seat else (nm if (nm in index and index[nm].get("kind", "team") == "team") else args.fallback)
                for s, nm in enumerate(players)]
        for k in range(args.seeds):
            sd = args.seed0 + k
            jobs.append({"idx": len(jobs), "label": lab, "seed": sd, "names": list(players), "prof_keys": keys,
                         "seat": seat, "hands": args.hands, "base": args.bot, "cand": args.cand,
                         "engine_seed": (zlib.crc32(lab.encode()) & 0xFFFFFF) * 1009 + sd,
                         "clone_seed": sd * 7919 + i * 31, "tally": args.tally})
    labels = [s[0] for s in sel]
    print("simreal: %d real rounds (%s..%s) x %d seeds = %d tables%s, %d procs; computing the real side first ..." % (
        len(sel), labels[0], labels[-1], args.seeds, len(jobs) * (2 if args.cand else 1),
        " (base + cand)" if args.cand else "", procs), flush=True)
    t0 = time.time()
    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    with ctx.Pool(1) as p1:                     # the ~1 GB cache lives only in this short-lived child
        real = p1.apply(real_side_job, (set(labels),))
    print("  real side done (%.0fs); playing %d tables ..." % (time.time() - t0, len(jobs) * (2 if args.cand else 1)),
          flush=True)
    results = []
    last = time.time()
    pool = ctx.Pool(min(procs, len(jobs)), maxtasksperchild=12, initializer=_init_worker,
                    initargs=(need, bot_code, adapt_params))
    try:
        for res in pool.imap_unordered(run_job, jobs):
            results.append(res)
            if time.time() - last > 15:
                last = time.time()
                print("  %d/%d jobs, %.0fs" % (len(results), len(jobs), time.time() - t0), flush=True)
        pool.close()
    except BaseException:
        pool.terminate()
        raise
    finally:
        pool.join()
    try:
        os.rmdir(TMP_DIR)
    except OSError:
        pass
    elapsed = time.time() - t0
    L, rep = build_report(args, real, labels, jobs, results, {k: sorted(v) for k, v in fallback_used.items()}, insample,
                          elapsed)
    txt = "\n".join(L)
    print(txt)
    name = args.name or (D.label_of(args.bot) if not args.cand else "%s_vs_%s" % (D.label_of(args.cand), D.label_of(args.bot)))
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "simreal_%s.txt" % name), "w") as fh:
        fh.write(txt + "\n")
    rep["tables"] = [{"round": r["label"], "seed": r["seed"],
                      "base_adj_bb100": bb100(r["base"]["adj"], r["base"]["hands"]) if "base" in r else None,
                      "cand_adj_bb100": bb100(r["cand"]["adj"], r["cand"]["hands"]) if "cand" in r else None,
                      "failed": r.get("failed")} for r in sorted(results, key=lambda r: (r["label"], r["seed"]))]
    with open(os.path.join(OUT_DIR, "simreal_%s.json" % name), "w") as fh:
        json.dump(rep, fh, indent=1, default=lambda o: sorted(o) if isinstance(o, set) else float(o))
    print("\nsaved out/simreal_%s.txt and .json" % name)


if __name__ == "__main__":
    main()
