#!/usr/bin/env python3
"""Compare candidate bots on identical tables (same opponents, seats and decks).

    python3 tools/gauntlet.py --bots candidates/A/bot.py candidates/B/bot.py --rounds 20
    python3 tools/gauntlet.py --bots ... --together          # all candidates at one table
    python3 tools/gauntlet.py --bots ... --field house       # zoo | house | mixed (default)

Solo mode (default): every candidate plays the same N tables on its own, so the
difference between two candidates is a paired comparison. Bots run in-process (no time
limit is enforced); act() time is measured and reported instead. Use the kit's
local_sim.py for the real 10 ms / 10 s gate.
"""
import argparse
import glob
import importlib.util
import os
import random
import statistics
import sys
import time
import traceback
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.join(ROOT, "starter-kit", "imperial-ai-hack-pokerbots-kit")
sys.path.insert(0, KIT)
from engine import FixedHandsTable  # noqa: E402
from engine.bot_runner import normalise  # noqa: E402

BB = 20
_CLS = {}


def agent_cls(path):
    if path not in _CLS:
        spec = importlib.util.spec_from_file_location("gbot_%d" % len(_CLS), path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _CLS[path] = mod.Agent
    return _CLS[path]


class Seat:
    def __init__(self, path, timed):
        self.path, self.timed = path, timed
        self.agent = None
        self.errors = 0
        self.first_tb = None
        self.times = []

    def start_table(self, seat, info):
        self.agent = agent_cls(self.path)()
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
        if self.timed:
            self.times.append(time.perf_counter() - t0)
        return out

    def hand_end(self, summary):
        if hasattr(self.agent, "on_hand_end"):
            t0 = time.perf_counter()
            try:
                self.agent.on_hand_end(summary)
            except Exception:
                self._err()
            if self.timed:
                self.times.append(time.perf_counter() - t0)


def name_of(path):
    base = os.path.basename(path)
    if base == "bot.py":
        return os.path.basename(os.path.dirname(path))
    return base[:-3]


def play(job):
    """job = (round, cands, field, seats, hands, seed). Returns per-candidate stats."""
    r, cands, field, seats, hands, seed = job
    rng = random.Random(seed * 1000003 + r)
    lineup = rng.sample(field, seats - len(cands)) if len(field) >= seats - len(cands) \
        else [rng.choice(field) for _ in range(seats - len(cands))]
    order = list(lineup)
    pos = [(r + 3 * k) % seats for k in range(len(cands))]
    for k, c in sorted(zip(pos, cands)):
        order.insert(min(k, len(order)), c)
    players = [Seat(p, p in cands) for p in order]
    res = FixedHandsTable(players, hands=hands, seed=seed * 7919 + r).play()
    assert sum(res["chips"]) == 0
    out = {}
    for i, p in enumerate(order):
        if p in cands:
            s = players[i]
            out[p] = {"chips": res["chips"][i], "errors": s.errors, "tb": s.first_tb,
                      "times": s.times}
    opp = {name_of(p): res["chips"][i] for i, p in enumerate(order) if p not in cands}
    return r, out, opp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bots", nargs="+", required=True)
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--hands", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--seats", type=int, default=8)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--field", choices=["zoo", "house", "mixed"], default="mixed")
    ap.add_argument("--only", nargs="*", help="restrict the field to these bot names")
    ap.add_argument("--together", action="store_true")
    a = ap.parse_args()

    cands = [os.path.abspath(b) for b in a.bots]
    zoo = sorted(glob.glob(os.path.join(ROOT, "zoo", "*.py")))
    house = sorted(glob.glob(os.path.join(KIT, "examples", "*.py")))
    field = {"zoo": zoo, "house": house, "mixed": zoo + house}[a.field]
    if a.only:
        field = [p for p in field if name_of(p) in a.only]
    if not field:
        sys.exit("empty field")

    if a.together:
        jobs = [(r, cands, field, a.seats, a.hands, a.seed) for r in range(a.rounds)]
    else:
        jobs = [(r, [c], field, a.seats, a.hands, a.seed) for r in range(a.rounds) for c in cands]
    t0 = time.time()
    with Pool(a.jobs) as pool:
        results = pool.map(play, jobs, chunksize=1)

    per = {c: {} for c in cands}        # cand -> round -> bb/100
    errs = {c: 0 for c in cands}
    tbs = {}
    times = {c: [] for c in cands}
    think = {c: [] for c in cands}
    vs = {c: {} for c in cands}         # cand -> archetype -> [bb/100 at tables with it]
    for r, out, opp in results:
        for c, st in out.items():
            bb100 = st["chips"] / BB / a.hands * 100
            per[c][r] = bb100
            errs[c] += st["errors"]
            if st["tb"] and c not in tbs:
                tbs[c] = st["tb"]
            times[c].extend(st["times"])
            think[c].append(sum(st["times"]) * 1000 / a.hands)
            for o in opp:
                vs[c].setdefault(o, []).append(bb100)

    def mean_se(xs):
        if len(xs) < 2:
            return (xs[0] if xs else 0.0), float("nan")
        return statistics.mean(xs), statistics.stdev(xs) / len(xs) ** 0.5

    print("\n%s mode, field=%s, %d rounds x %d hands, %d seats, seed %d (%.0fs)" % (
        "together" if a.together else "solo paired", a.field, a.rounds, a.hands, a.seats,
        a.seed, time.time() - t0))
    print("%-10s %9s %7s %7s %8s %8s %9s" % ("bot", "bb/100", "+-SE", "errors", "p99 ms", "max ms", "think s/rd"))
    for c in cands:
        xs = [per[c][r] for r in sorted(per[c])]
        m, se = mean_se(xs)
        ts = sorted(times[c])
        p99 = ts[int(len(ts) * 0.99)] * 1000 if ts else 0
        print("%-10s %+9.1f %7.1f %7d %8.2f %8.2f %9.2f" % (
            name_of(c), m, se, errs[c], p99, (ts[-1] * 1000 if ts else 0), max(think[c]) if think[c] else 0))
    if len(cands) > 1:
        print("\npaired difference (row minus column), bb/100 +- SE:")
        print("%-10s" % "" + "".join("%16s" % name_of(c) for c in cands))
        for c1 in cands:
            row = "%-10s" % name_of(c1)
            for c2 in cands:
                if c1 == c2:
                    row += "%16s" % "-"
                    continue
                d = [per[c1][r] - per[c2][r] for r in per[c1] if r in per[c2]]
                m, se = mean_se(d)
                row += "%+9.1f+-%-5.1f" % (m, se)
            print(row)
    names = sorted({o for c in cands for o in vs[c]})
    print("\nbb/100 at tables containing each opponent (n tables):")
    print("%-14s" % "opponent" + "".join("%14s" % name_of(c) for c in cands))
    for o in names:
        row = "%-14s" % o
        for c in cands:
            xs = vs[c].get(o, [])
            row += "%+9.0f (%2d)" % (statistics.mean(xs) if xs else 0, len(xs))
        print(row)
    for c, tb in tbs.items():
        print("\n--- first exception from %s ---\n%s" % (name_of(c), tb))


if __name__ == "__main__":
    main()
