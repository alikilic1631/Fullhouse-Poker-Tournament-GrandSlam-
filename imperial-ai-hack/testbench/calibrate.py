#!/usr/bin/env python3
"""calibrate - make the clones reproduce the real teams' frequencies, and measure how well they do.

    python3 calibrate.py                         # 3 fitting passes + 1 validation pass, 120 tables each
    python3 calibrate.py --iters 0 --tables 60   # validation only (current policies), no profile changes
    python3 calibrate.py --teams Kojack Red --tables 40
    python3 calibrate.py --iters 0 --lineups real --tables 216 --no-write   # replay the live bot's 36 real
                                                 # tables with clones -> out/calibration_real_lineups.*

Each pass plays --tables tables of --seats seats with the kit engine in-process: the live bot
(../v10/bot.py by default, name "Durahim 1453") in one seat and clones of the profiled teams in the
others (every profile appears about equally often). The hands are written in exactly the real log format
(out/sim/<pass>/rNNN.json: hh.py and profiles.py parse them) and re-extracted with profiles.tally_round.

Fitting: the clone acts on u = F_spot(x) where x is its preflop range percentile q (0 = best) or its
postflop strength s. A fitting pass records x for every clone decision per (team, spot) and rewrites
profile["policy"]["cdf"] with the empirical quantiles of x (own spot if >= --min-samples, else pooled
over positions / hu-mw / size buckets, else the all-teams pool), so that the next pass hits the target
frequencies. Preflop this only corrects card removal (after folds/raises the hands left are not uniform);
postflop it maps the clone's strength scale onto its own range in each spot. The last pass validates.

Report (out/calibration.json/.txt; with --lineups real: out/calibration_real_lineups.json/.txt): per team,
target (real logs) vs achieved (simulation)
for the headline stats (VPIP, PFR, 3-bet, fold to 3-bet, opens by position, limp, c-bet, fold vs bet by
size per street, aggression per street, WTSD, W$SD, all-in frequency) with sample sizes, plus the
decision-weighted spot-level deviation, sim bb/100 vs real, the live bot's own stats real vs sim, where the
chips go (bb/100 by how hands ended, real vs sim) and the strength of shown hands per line (real vs sim).
"""
import argparse
import glob
import importlib.util
import json
import math
import os
import random
import shutil
import statistics
import sys
import time
import traceback
from collections import Counter, defaultdict
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
KIT = os.path.normpath(os.path.join(ROOT, "..", "imperial-ai-hack-pokerbots-kit"))
sys.path.insert(0, KIT)
from engine import FixedHandsTable  # noqa: E402
from engine.bot_runner import normalise  # noqa: E402

import clone as CL  # noqa: E402
import profiles as PR  # noqa: E402
import hh as H  # noqa: E402

PROF_DIR = os.path.join(HERE, "profiles")
OUT_DIR = os.path.join(HERE, "out")
LIVE_BOT = os.path.join(ROOT, "v10", "bot.py")
HERO = PR.HERO
QM = 20                    # quantile points per CDF: u = 0, 1/20, ..., 1

KEY_STATS = (["vpip", "pfr", "three_bet", "call_open", "fold_to_3bet", "limp", "iso_raise"]
             + ["open_" + g for g in ("EP", "MP", "CO", "BTN", "SB")]
             + ["cbet_flop", "cbet_turn", "donk_flop", "stab_flop"]
             + ["fold_vs_%s_%s" % (s, b) for s in ("flop", "turn", "river") for b in CL.BUCKETS]
             + ["raise_vs_bet_flop", "xr_flop", "fold_vs_raise_flop"]
             + ["agg_flop", "agg_turn", "agg_river", "wtsd", "wsd", "allin_pf", "allin_post"])


# =============================================================================== seats / workers
_BOT_CLS = {}


def bot_class(path):
    if path not in _BOT_CLS:
        spec = importlib.util.spec_from_file_location("calbot_%d" % len(_BOT_CLS), path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _BOT_CLS[path] = mod.Agent
    return _BOT_CLS[path]


class Seat:
    """Engine seat around an in-process agent; measures act() time, never lets an exception through."""

    def __init__(self, agent):
        self.agent = agent
        self.t = 0.0
        self.nd = 0
        self.mx = 0.0
        self.errors = 0
        self.first_tb = None

    def start_table(self, seat, info):
        if hasattr(self.agent, "on_table_start"):
            try:
                self.agent.on_table_start(info)
            except Exception:
                self._err()

    def _err(self):
        self.errors += 1
        if self.first_tb is None:
            self.first_tb = traceback.format_exc(limit=5)

    def act(self, state):
        t0 = time.perf_counter()
        try:
            out = normalise(self.agent.act(state))
        except Exception:
            self._err()
            out = None
        dt = time.perf_counter() - t0
        self.t += dt
        self.nd += 1
        if dt > self.mx:
            self.mx = dt
        return out

    def hand_end(self, summary):
        if hasattr(self.agent, "on_hand_end"):
            try:
                self.agent.on_hand_end(summary)
            except Exception:
                self._err()


def rec_to_hand(rec, hero, n):
    start = list(rec["stacks"])
    end = list(rec["end"])
    results = [end[i] - start[i] for i in range(n)]
    sd = dict(rec.get("showdown") or {})
    hole = {str(hero): list(rec["hole"][str(hero)])}
    for k in sd:
        hole[k] = list(rec["hole"][k])
    return {"n": rec["n"], "button": rec["button"], "sb": rec["sb"], "bb": rec["bb"], "start_stacks": start,
            "hole": hole, "showdown": sd, "board": list(rec["board"]), "events": rec["events"],
            "results": results, "result": results[hero]}


def write_round_json(path, ref, names, hero, log, chips, think_s, hands):
    n = len(names)
    d = {"ref": ref, "seat": hero, "players": list(names),
         "format": "events: [post|act|board|refund|win, ...]; results: chips won per seat",
         "hands": [rec_to_hand(rec, hero, n) for rec in log],
         "round": {"ref": ref, "slot": None, "table": 0, "seat": hero, "chips": chips, "hands": hands,
                   "version": "sim", "bb100": round(chips / 20.0 / hands * 100, 2), "timeouts": 0, "errors": 0,
                   "bank_out": 0, "think_s": round(think_s, 2), "violations": [], "error_sample": None}}
    with open(path, "w") as fh:
        json.dump(d, fh, separators=(",", ":"))


def play_table(job):
    """job: dict(idx, names, profiles (list of dict|None for the live bot), seeds, deck_seed, hands, bot,
    log_path, ref). Returns tally (json), strength traces, chips, timings."""
    names = job["names"]
    hero = names.index(HERO)
    agents = []
    clones = {}
    for i, (nm, prof) in enumerate(zip(names, job["profiles"])):
        if prof is None:
            agents.append(Seat(bot_class(job["bot"])()))
        else:
            ag = CL.make_agent(prof, job["seeds"][i])
            ag.trace = []
            clones[i] = ag
            agents.append(Seat(ag))
    t0 = time.time()
    table = FixedHandsTable(agents, hands=job["hands"], seed=job["deck_seed"], record=True)
    res = table.play()
    wall = time.time() - t0
    chips = res["chips"]
    write_round_json(job["log_path"], job["ref"], names, hero, table.log, chips[hero], agents[hero].t, job["hands"])
    table.log = None
    r = H.load_round(job["log_path"], with_luck=False)     # all-in luck is not needed for sim logs (and is slow)
    seats_team = {i: nm for i, nm in enumerate(names)}
    tallies = defaultdict(PR.new_tally)
    PR.tally_round(r, seats_team, tallies, showdown=True)
    traces = {}
    for i, ag in clones.items():
        d = defaultdict(list)
        for key, x, u, act in ag.trace:
            d[key].append(round(x, 6))
        traces[names[i]] = dict(d)
    if not job.get("keep_log"):
        try:
            os.remove(job["log_path"])
        except OSError:
            pass
    timing = {nm: {"decisions": agents[i].nd, "total_s": agents[i].t, "max_ms": agents[i].mx * 1000,
                   "errors": agents[i].errors, "tb": agents[i].first_tb} for i, nm in enumerate(names)}
    return {"idx": job["idx"], "names": names, "chips": chips, "tallies": {k: PR.tally_to_json(v) for k, v in tallies.items()},
            "traces": traces, "timing": timing, "wall": wall}


# =============================================================================== lineups
def real_lineups(teams, versions=(17,)):
    """The real tables our live bot played (site versions given): (ref, players with HERO at its real seat).
    Rounds with a team that has no profile are skipped."""
    out = []
    for path in sorted(glob.glob(os.path.join(H.HANDS_DIR, "*.json"))):
        with open(path) as fh:
            d = json.load(fh)
        meta = d.get("round") or {}
        if "practice" in d.get("ref", "") or meta.get("version") not in versions:
            continue
        names = list(d["players"])
        names[d["seat"]] = HERO
        if all(nm == HERO or nm in teams for nm in names):
            out.append((d["ref"], names))
    return out


def make_lineups(teams, tables, seats, rng):
    """Every table: the live bot + (seats-1) distinct clones, teams used about equally often."""
    count = Counter({t: 0 for t in teams})
    out = []
    k = seats - 1
    for _ in range(tables):
        order = sorted(teams, key=lambda t: (count[t], rng.random()))
        pick = order[:k]
        for t in pick:
            count[t] += 1
        names = list(pick)
        rng.shuffle(names)
        names.insert(rng.randrange(seats), HERO)
        out.append(names)
    return out


# =============================================================================== CDF fitting
def quantiles(xs, m=QM):
    xs = sorted(xs)
    n = len(xs)
    out = []
    for k in range(m + 1):
        pos = k / float(m) * (n - 1)
        i = int(math.floor(pos))
        f = pos - i
        if i + 1 < n and f > 0 and xs[i + 1] != xs[i]:
            out.append(round(xs[i] + f * (xs[i + 1] - xs[i]), 6))
        else:
            out.append(round(xs[i], 6))
    for k in range(1, len(out)):              # numerical safety: non-decreasing
        if out[k] < out[k - 1]:
            out[k] = out[k - 1]
    return out


def fit_cdfs(traces, min_samples):
    """traces: team -> key -> [x]. Returns team -> {key: {"n", "q", "from"}} incl. pooled parent keys.
    A spot's own CDF needs min_samples decisions; pooled parent keys (fallbacks) need half of that; the
    coarsest key of a chain falls back to the all-teams pool."""
    min_parent = max(30, min_samples // 2)
    pool = defaultdict(list)                    # all teams, per key and per parent key
    for team, d in traces.items():
        for key, xs in d.items():
            for pk in CL.parent_keys(key):
                pool[pk].extend(xs)
    out = {}
    for team, d in traces.items():
        own = defaultdict(list)
        for key, xs in d.items():
            for pk in CL.parent_keys(key):
                own[pk].extend(xs)
        cdf = {}
        keys = set(own) | set(pool)
        for k in keys:
            xs = own.get(k, [])
            is_parent = k not in d
            if len(xs) >= (min_parent if is_parent else min_samples):
                cdf[k] = {"n": len(xs), "q": quantiles(xs), "from": "team"}
            elif len(pool.get(k, [])) >= min_parent and CL.parent_keys(k) == [k]:
                # only the coarsest keys fall back to the all-teams pool (the clone tries its own parents first)
                cdf[k] = {"n": len(pool[k]), "q": quantiles(pool[k]), "from": "pool"}
        out[team] = cdf
    return out


# =============================================================================== comparison
def zdiff(p1, n1, p2, n2):
    if p1 is None or p2 is None or not n1 or not n2:
        return None
    p = (p1 * n1 + p2 * n2) / float(n1 + n2)
    v = p * (1 - p) * (1.0 / n1 + 1.0 / n2)
    return (p2 - p1) / math.sqrt(v) if v > 0 else 0.0


def compare(target_summary, achieved_tally, min_n=40):
    ach = PR.key_stats(achieved_tally)
    rows = []
    for k in KEY_STATS:
        t = target_summary.get(k) or {}
        tv, tn = t.get("value"), t.get("n", 0)
        av, an = ach.get(k, (None, 0))
        d = (av - tv) * 100 if (tv is not None and av is not None) else None
        z = zdiff(tv, tn, av, an)
        enough = (tn or 0) >= min_n and (an or 0) >= min_n
        ok = None
        if d is not None and enough:
            ok = abs(d) <= 3.0 or (z is not None and abs(z) < 2.0)
        rows.append({"stat": k, "target": tv, "n_real": tn, "achieved": av, "n_sim": an,
                     "diff_pp": round(d, 2) if d is not None else None, "z": round(z, 2) if z is not None else None,
                     "within_3pp": (abs(d) <= 3.0) if (d is not None and enough) else None, "ok": ok})
    return rows


def spot_fidelity(profile, achieved_tally, min_n=30):
    """Decision-weighted mean |achieved - target| (pp) over spots with >= min_n decisions in both."""
    num = den = 0.0
    worst = []
    for key, cell in profile["spots"].items():
        if "*" in key:
            continue
        tn = cell.get("n", 0)
        sim = achieved_tally["spots"].get(key)
        if not sim or tn < min_n:
            continue
        an = sum(sim.values())
        if an < min_n:
            continue
        acts = PR._actions(key)
        dev = 0.0
        for a in acts:
            tp = cell["counts"].get(a, 0) / float(tn)
            ap = sim.get(a, 0) / float(an)
            dev = max(dev, abs(ap - tp))
        w = min(tn, an)
        num += dev * w
        den += w
        worst.append((dev * 100, key, tn, an))
    worst.sort(reverse=True)
    return (num / den * 100 if den else None), worst[:5]


# =============================================================================== main
def load_profiles(teams):
    idx = json.load(open(os.path.join(PROF_DIR, "index.json")))
    out = {}
    for t in teams or sorted(idx):
        if t not in idx:
            sys.exit("no profile for %r (see profiles/index.json)" % t)
        out[t] = json.load(open(os.path.join(PROF_DIR, idx[t]["slug"] + ".json")))
    return out, idx


def hero_real_tally():
    """The live bot's real tally over its site-version-17 rounds (cached in out/hero_real_tally.json).
    Computed in a child process so the ~1 GB of parsed logs never lives in this (forking) process."""
    path = os.path.join(OUT_DIR, "hero_real_tally.json")
    if not os.path.exists(path):
        print("computing the live bot's real stats (site version 17 rounds) ...", flush=True)
        with Pool(1) as pool:
            pool.apply(_hero_real_job, (path,))
    return PR.tally_from_json(json.load(open(path)))


def _hero_real_job(path):
    rounds = H.select(H.load_all(), versions={17})
    tallies = defaultdict(PR.new_tally)
    for r in rounds:
        PR.tally_round(r, {r.seat: HERO}, tallies, showdown=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(path, "w") as fh:
        json.dump(PR.tally_to_json(tallies[HERO]), fh)
    return True


def pearson(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    sxx = sum((a - mx) ** 2 for a in xs)
    syy = sum((b - my) ** 2 for b in ys)
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else float("nan")


def run_pass(name, profiles, teams, args, rng, keep_logs):
    if args.lineups == "real":
        base = real_lineups(set(teams))
        if not base:
            sys.exit("no real lineup can be rebuilt from the selected profiles")
        lineups = [list(base[j % len(base)][1]) for j in range(args.tables)]
    else:
        lineups = make_lineups(teams, args.tables, args.seats, rng)
    log_dir = os.path.join(OUT_DIR, "sim", ("%s_%s" % (args.name, name)) if args.name else name)
    if os.path.isdir(log_dir):
        shutil.rmtree(log_dir)
    os.makedirs(log_dir, exist_ok=True)
    jobs = []
    for j, names in enumerate(lineups):
        jobs.append({"idx": j, "names": names,
                     "profiles": [None if nm == HERO else profiles[nm] for nm in names],
                     "seeds": [args.seed * 7919 + j * 31 + i for i in range(len(names))],
                     "deck_seed": args.seed * 1000003 + j, "hands": args.hands, "bot": args.bot,
                     "log_path": os.path.join(log_dir, "r%03d.json" % (j + 1)),
                     "ref": "sim/%s/r%03d" % (name, j + 1), "keep_log": keep_logs})
    t0 = time.time()
    with Pool(args.jobs, maxtasksperchild=20) as pool:
        results = pool.map(play_table, jobs, chunksize=1)
    tallies = defaultdict(PR.new_tally)
    traces = defaultdict(lambda: defaultdict(list))
    chips = defaultdict(int)
    hands = Counter()
    timing = defaultdict(lambda: {"decisions": 0, "total_s": 0.0, "max_ms": 0.0, "errors": 0, "tb": None})
    for res in results:
        for team, tj in res["tallies"].items():
            PR.merge_tally(tallies[team], PR.tally_from_json(tj))
        for team, d in res["traces"].items():
            for k, xs in d.items():
                traces[team][k].extend(xs)
        for i, nm in enumerate(res["names"]):
            chips[nm] += res["chips"][i]
            hands[nm] += args.hands
            tm = res["timing"][nm]
            T = timing[nm]
            T["decisions"] += tm["decisions"]
            T["total_s"] += tm["total_s"]
            T["max_ms"] = max(T["max_ms"], tm["max_ms"])
            T["errors"] += tm["errors"]
            if tm["tb"] and not T["tb"]:
                T["tb"] = tm["tb"]
    if not keep_logs:
        shutil.rmtree(log_dir, ignore_errors=True)
    print("  pass %s: %d tables in %.0fs" % (name, len(jobs), time.time() - t0), flush=True)
    return tallies, traces, chips, hands, timing


def fmt_pct(v):
    return "   -" if v is None else "%5.1f" % (100 * v)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iters", type=int, default=3, help="fitting passes before the validation pass")
    ap.add_argument("--tables", type=int, default=120, help="tables per pass")
    ap.add_argument("--hands", type=int, default=1000)
    ap.add_argument("--seats", type=int, default=7)
    ap.add_argument("--lineups", choices=["uniform", "real"], default="uniform",
                    help="uniform: every profile equally often at --seats tables; real: replay the real tables "
                         "(teams and seats) of the live bot's site-v17 rounds R19-R54, cycling through them, so "
                         "the live bot's sim result is comparable with its real result")
    ap.add_argument("--jobs", type=int, default=6, help="worker processes (max 6 on the shared machine)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--teams", nargs="*", help="profiles to calibrate (default: every profile in the index)")
    ap.add_argument("--bot", default=LIVE_BOT, help="bot in the hero seat (default: live v10/bot.py)")
    ap.add_argument("--min-samples", type=int, default=120, help="decisions needed to fit a spot's own CDF "
                    "(pooled fallback keys need half)")
    ap.add_argument("--pool-passes", type=int, default=2, help="fit on the traces of the last N fitting passes")
    ap.add_argument("--no-write", action="store_true", help="do not update profiles/*.json")
    ap.add_argument("--keep-logs", action="store_true", help="keep the logs of every pass (default: validation only)")
    ap.add_argument("--name", help="write the report to out/<name>.txt/.json and the logs to out/sim/<name>_<pass>/ "
                                   "(default: out/calibration[_real_lineups].* and out/sim/<pass>/, which the reference "
                                   "run uses: give --name for test runs so they do not overwrite it)")
    ap.add_argument("--reset", action="store_true", help="start from identity CDFs (drop existing policies)")
    args = ap.parse_args()
    args.jobs = max(1, min(6, args.jobs))
    args.bot = os.path.abspath(args.bot)
    t_start = time.time()
    profiles, idx = load_profiles(args.teams)
    teams = sorted(profiles)
    if args.seats - 1 > len(teams):
        sys.exit("need at least %d profiles for %d seats" % (args.seats - 1, args.seats))
    if args.reset:
        for p in profiles.values():
            p.pop("policy", None)
    rng = random.Random(args.seed)
    history = []
    hero_real = hero_real_tally()
    passes = ["fit%d" % k for k in range(args.iters)] + ["validate"]
    final = None
    recent = []                               # traces of the last --pool-passes fitting passes
    for pi, pname in enumerate(passes):
        tallies, traces, chips, hands, timing = run_pass(pname, profiles, teams, args, rng,
                                                         keep_logs=(args.keep_logs or pname == "validate"))
        # quick progress line: share of headline stats within 3pp (enough samples)
        oks = tot = 0
        for t in teams:
            for row in compare(profiles[t]["summary"], tallies[t]):
                if row["within_3pp"] is not None:
                    tot += 1
                    oks += 1 if row["within_3pp"] else 0
        fid = [spot_fidelity(profiles[t], tallies[t])[0] for t in teams]
        fid = [f for f in fid if f is not None]
        print("  pass %s: %d/%d headline stats within 3pp (%.0f%%), mean spot deviation %.2f pp" % (
            pname, oks, tot, 100.0 * oks / max(1, tot), statistics.mean(fid) if fid else float("nan")), flush=True)
        history.append({"pass": pname, "within_3pp": oks, "comparable": tot,
                        "mean_spot_dev_pp": round(statistics.mean(fid), 3) if fid else None})
        if pname != "validate":
            recent = (recent + [traces])[-max(1, args.pool_passes):]
            merged = defaultdict(lambda: defaultdict(list))
            for tr in recent:
                for team, d in tr.items():
                    for k, xs in d.items():
                        merged[team][k].extend(xs)
            cdfs = fit_cdfs(merged, args.min_samples)
            for t in teams:
                pol = profiles[t].get("policy") or {}
                pol["cdf"] = {k: v for k, v in sorted(cdfs.get(t, {}).items())}
                pol["fitted"] = {"pass": pname, "tables": args.tables, "seats": args.seats, "seed": args.seed,
                                 "bot": os.path.relpath(args.bot, HERE), "date": time.strftime("%Y-%m-%d %H:%M"),
                                 "note": "cdf[key].q = strength quantiles at u = 0, 1/20, ..., 1 of the clone's own "
                                         "decisions in that spot under the previous policy (calibrate.py)"}
                profiles[t]["policy"] = pol
        else:
            final = (tallies, traces, chips, hands, timing)
    tallies, traces, chips, hands, timing = final
    if not args.no_write:
        for t in teams:
            path = os.path.join(PROF_DIR, idx[t]["slug"] + ".json")
            with open(path, "w") as fh:
                json.dump(profiles[t], fh, indent=1)

    # ---------------------------------------------------------------- report
    report = {"args": {k: v for k, v in vars(args).items()}, "passes": history, "teams": {}, "hero": {}}
    lines = []
    lines.append("CALIBRATION  %d fitting passes + validation, %d tables x %d hands per pass, %d seats (live bot + %d clones)"
                 % (args.iters, args.tables, args.hands, args.seats, args.seats - 1))
    lines.append("bot in hero seat: %s" % os.path.relpath(args.bot, HERE))
    lines.append("pass history: " + "; ".join("%s %d/%d within 3pp, spot dev %.2fpp" % (
        h["pass"], h["within_3pp"], h["comparable"], h["mean_spot_dev_pp"] or float("nan")) for h in history))
    lines.append("")
    lines.append("Per team (validation pass). 'within' = headline stats with >= 40 decisions on both sides that are")
    lines.append("within 3pp; 'ok' also accepts |z| < 2 (difference explained by sampling noise); spot dev =")
    lines.append("decision-weighted mean of the largest action-frequency gap per spot (spots with >= 30 decisions).")
    lines.append("%-26s %6s %6s %7s %5s %7s %8s %8s %9s %8s" % ("team", "hands", "within", "ok", "of", "spotdev",
                                                                "sim bb100", "real adj", "ms/dec", "max ms"))
    sim_vs_real = []
    for t in teams:
        rows = compare(profiles[t]["summary"], tallies[t])
        comp = [r for r in rows if r["within_3pp"] is not None]
        within = sum(1 for r in comp if r["within_3pp"])
        ok = sum(1 for r in comp if r["ok"])
        fid, worst = spot_fidelity(profiles[t], tallies[t])
        tm = timing[t]
        ms = tm["total_s"] / max(1, tm["decisions"]) * 1000
        simbb = chips[t] / 20.0 / max(1, hands[t]) * 100
        realbb = profiles[t].get("results", {}).get("adj_bb100")
        if realbb is not None and profiles[t]["kind"] == "team":
            sim_vs_real.append((simbb, realbb))
        report["teams"][t] = {"kind": profiles[t]["kind"], "hands_sim": hands[t],
                              "hands_real": profiles[t]["data"]["hands"], "rule": profiles[t]["data"]["rule"],
                              "within_3pp": within, "ok": ok, "comparable": len(comp),
                              "spot_dev_pp": round(fid, 3) if fid is not None else None,
                              "worst_spots": [{"key": k, "dev_pp": round(d, 1), "n_real": a, "n_sim": b} for d, k, a, b in worst],
                              "sim_bb100": round(simbb, 1), "real_adj_bb100": realbb,
                              "ms_per_decision": round(ms, 4), "max_ms": round(tm["max_ms"], 2),
                              "errors": tm["errors"], "stats": rows}
        lines.append("%-26s %6d %6d %7d %5d %7s %+8.1f %8s %9.3f %8.2f" % (
            t[:26], hands[t], within, ok, len(comp), ("%.2f" % fid) if fid is not None else "-",
            simbb, ("%+.1f" % realbb) if realbb is not None else "-", ms, tm["max_ms"]))
    if len(sim_vs_real) >= 3:
        xs = [a for a, _ in sim_vs_real]
        ys = [b for _, b in sim_vs_real]
        corr = pearson(xs, ys)
        report["sim_vs_real_bb100_correlation"] = round(corr, 3)
        lines.append("\ncorrelation across teams of clone sim bb/100 vs the team's real luck-adjusted bb/100: %.2f" % corr)
    # stat-level overview across teams
    lines.append("\nHeadline stats across teams (validation): within 3pp / comparable, mean |diff| pp")
    agg = defaultdict(lambda: [0, 0, []])
    for t in teams:
        for r in report["teams"][t]["stats"]:
            if r["within_3pp"] is None:
                continue
            a = agg[r["stat"]]
            a[0] += 1 if r["within_3pp"] else 0
            a[1] += 1
            a[2].append(abs(r["diff_pp"]))
    for k in KEY_STATS:
        if k in agg:
            a = agg[k]
            lines.append("  %-20s %3d/%-3d  mean |diff| %5.2f  max %5.1f" % (k, a[0], a[1], statistics.mean(a[2]), max(a[2])))
    # per team detail
    lines.append("\nPer-team detail (target real -> achieved sim, n real/n sim; * = off by > 3pp and |z| >= 2):")
    for t in teams:
        rows = report["teams"][t]["stats"]
        parts = []
        for r in rows:
            if r["target"] is None and r["achieved"] is None:
                continue
            flag = "*" if (r["ok"] is False) else ""
            parts.append("%s %s->%s (%s/%s)%s" % (r["stat"], fmt_pct(r["target"]).strip(), fmt_pct(r["achieved"]).strip(),
                                                  r["n_real"], r["n_sim"], flag))
        lines.append("\n%s [%s, %d real hands]" % (t, profiles[t]["data"]["rule"], profiles[t]["data"]["hands"]))
        for i in range(0, len(parts), 4):
            lines.append("   " + "; ".join(parts[i:i + 4]))
        ws = report["teams"][t]["worst_spots"]
        if ws:
            lines.append("   largest spot gaps: " + ", ".join("%s %.1fpp (%d/%d)" % (w["key"], w["dev_pp"], w["n_real"], w["n_sim"]) for w in ws[:3]))
    # hero
    hrows = compare({k: {"value": v[0], "n": v[1]} for k, v in PR.key_stats(hero_real).items()}, tallies[HERO])
    hst = hero_real["stats"]
    real_bb = hst.get("chips", 0) / 20.0 / max(1, hst.get("hands", 1)) * 100
    real_adj = (hst.get("chips", 0) - hst.get("luck", 0)) / 20.0 / max(1, hst.get("hands", 1)) * 100
    simbb = chips[HERO] / 20.0 / max(1, hands[HERO]) * 100
    tm = timing[HERO]
    report["hero"] = {"bot": os.path.relpath(args.bot, HERE), "real_bb100_v17": round(real_bb, 1),
                      "real_adj_bb100_v17": round(real_adj, 1), "real_hands": hst.get("hands", 0),
                      "sim_bb100": round(simbb, 1), "sim_hands": hands[HERO], "stats": hrows,
                      "ms_per_decision": round(tm["total_s"] / max(1, tm["decisions"]) * 1000, 3),
                      "errors": tm["errors"]}
    lines.append("\nLIVE BOT (%s) real (site v17, %d hands: %+.1f bb/100, %+.1f luck-adjusted) vs vs-clones sim (%d hands: %+.1f bb/100)"
                 % (os.path.relpath(args.bot, HERE), hst.get("hands", 0), real_bb, real_adj, hands[HERO], simbb))
    parts = ["%s %s->%s" % (r["stat"], fmt_pct(r["target"]).strip(), fmt_pct(r["achieved"]).strip()) for r in hrows
             if r["target"] is not None or r["achieved"] is not None]
    for i in range(0, len(parts), 6):
        lines.append("   " + "; ".join(parts[i:i + 6]))
    # where the chips go: outcome breakdown (bb/100 per way a hand ended), real vs sim
    clone_sim = PR.new_tally()
    for t in teams:
        if profiles[t]["kind"] == "team":
            PR.merge_tally(clone_sim, tallies[t])
    field_real = profiles.get("field") or json.load(open(os.path.join(PROF_DIR, "field.json")))
    hb_real = PR.outcome_breakdown(hero_real["stats"])
    hb_sim = PR.outcome_breakdown(tallies[HERO]["stats"])
    cb_real = (field_real.get("results") or {}).get("by_outcome") or {}
    cb_sim = PR.outcome_breakdown(clone_sim["stats"])
    report["outcomes"] = {"hero_real": hb_real, "hero_sim": hb_sim, "clones_real": cb_real, "clones_sim": cb_sim}
    lines.append("\nWHERE THE CHIPS GO: bb/100 by how the hand ended for the seat (share of hands in brackets)")
    lines.append("%-24s %18s %18s | %18s %18s" % ("outcome", "live bot real", "live bot sim", "teams real (field)", "clones sim"))
    for oc in PR.OUTCOMES:
        def cell(d):
            e = d.get(oc)
            return "%+7.1f (%5.1f%%)" % (e["bb100"], 100 * e["share"]) if e else "-"
        lines.append("%-24s %18s %18s | %18s %18s" % (PR.OUTCOME_NAMES[oc], cell(hb_real), cell(hb_sim), cell(cb_real), cell(cb_sim)))
    # showdown strength of the clones' lines vs the real teams'
    lines.append("\nSHOWN HANDS: strength when the line was taken (mean s, share weak s < 0.35), real field vs clones sim")
    sd_sim = PR._sd_summary(clone_sim["sd"])
    sd_real = field_real.get("showdown") or {}
    report["showdown_compare"] = {}
    for k in ("pf|open", "pf|call", "pf|3bet", "pf|jam", "flop|bet", "flop|call", "turn|bet", "turn|call",
              "river|bet", "river|call", "river|raise"):
        a = sd_real.get(k)
        b = sd_sim.get(k)
        if not a or not b:
            continue
        report["showdown_compare"][k] = {"real": a, "sim": b}
        if k.startswith("pf|"):
            lines.append("  %-12s real mean pct %.3f (n %5d)   sim mean pct %.3f (n %5d)   (preflop percentile, 0 = best)"
                         % (k, a["mean"], a["n"], b["mean"], b["n"]))
        else:
            lines.append("  %-12s real mean s %.3f weak %4.1f%% (n %5d)   sim mean s %.3f weak %4.1f%% (n %5d)"
                         % (k, a["mean"], 100 * a.get("weak_share", 0), a["n"], b["mean"], 100 * b.get("weak_share", 0), b["n"]))
    clone_ms = [report["teams"][t]["ms_per_decision"] for t in teams]
    lines.append("\nclone speed: mean %.3f ms/decision (worst team %.3f), worst single decision %.2f ms; errors %d" % (
        statistics.mean(clone_ms), max(clone_ms), max(report["teams"][t]["max_ms"] for t in teams),
        sum(report["teams"][t]["errors"] for t in teams)))
    lines.append("total time %.0fs; validation logs in out/sim/%s/" % (
        time.time() - t_start, ("%s_validate" % args.name) if args.name else "validate"))
    txt = "\n".join(lines)
    os.makedirs(OUT_DIR, exist_ok=True)
    base = args.name or ("calibration" if args.lineups == "uniform" else "calibration_real_lineups")
    with open(os.path.join(OUT_DIR, base + ".json"), "w") as fh:
        json.dump(report, fh, indent=1)
    with open(os.path.join(OUT_DIR, base + ".txt"), "w") as fh:
        fh.write(txt + "\n")
    head = txt.split("\nPer-team detail")[0]
    print(head)
    print("\nfull report: out/%s.txt, out/%s.json" % (base, base))


if __name__ == "__main__":
    main()
