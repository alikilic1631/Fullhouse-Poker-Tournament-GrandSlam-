#!/usr/bin/env python3
"""Where does a bot win and lose its chips?  python3 tools/profile.py v1/bot.py --rounds 20 [--only nit ...]"""
import argparse
import glob
import os
import random
import sys
from collections import defaultdict
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gauntlet import BB, KIT, ROOT, Seat, name_of  # noqa: E402
from engine import FixedHandsTable  # noqa: E402

POS8 = ["BTN", "SB", "BB", "UTG", "UTG1", "LJ", "HJ", "CO"]


def run(job):
    r, cand, field, seats, hands, seed = job
    rng = random.Random(seed * 1000003 + r)
    lineup = rng.sample(field, seats - 1) if len(field) >= seats - 1 else [rng.choice(field) for _ in range(seats - 1)]
    order = list(lineup)
    hero = r % seats
    order.insert(hero, cand)
    players = [Seat(p, False) for p in order]
    t = FixedHandsTable(players, hands=hands, seed=seed * 7919 + r, record=True)
    t.play()
    rows = []
    for rec in t.log:
        n = len(rec["stacks"])
        rel = (hero - rec["button"]) % n
        pos = POS8[rel] if rel < 3 else POS8[8 - (n - rel)]
        net = (rec["end"][hero] - rec["stacks"][hero]) / BB
        street = "preflop"
        raises = 0
        h_raise = h_call = h_fold = False
        first_raiser = None
        hero_first_in = True
        invested = 0
        saw_flop = False
        post = defaultdict(int)
        facing_bet = False
        for ev in rec["events"]:
            if ev[0] == "post" and ev[1] == hero:
                invested += ev[2]
            elif ev[0] == "board":
                street = ev[1]
                facing_bet = False
                if street == "flop" and not h_fold:
                    saw_flop = True
            elif ev[0] == "act":
                _, seat, a, amt = ev
                if street == "preflop":
                    if seat == hero:
                        if a == "raise":
                            h_raise = True
                            if first_raiser is None:
                                first_raiser = hero
                            raises += 1
                        elif a == "call":
                            h_call = True
                        elif a == "fold":
                            h_fold = True
                    else:
                        if a == "raise":
                            raises += 1
                            if first_raiser is None:
                                first_raiser = seat
                else:
                    if seat == hero:
                        if a == "fold":
                            h_fold = True
                            post["fold_to_bet"] += 1
                        if facing_bet:
                            post["faced_bet"] += 1
                            if a == "call":
                                post["call_bet"] += 1
                            elif a == "raise":
                                post["raise_bet"] += 1
                        else:
                            post["could_bet"] += 1
                            if a == "raise":
                                post["bet"] += 1
                        if a == "raise":
                            facing_bet = False
                    elif a == "raise":
                        facing_bet = True
        shown = "showdown" in rec and not h_fold
        allin_pre = False
        if not saw_flop and not h_fold and (h_raise or h_call):
            scen = "pre: won uncontested"
        elif h_fold and not saw_flop and street == "preflop" or (h_fold and not (h_raise or h_call) and not saw_flop):
            scen = "pre: folded" + (" (after putting chips in)" if (h_raise or h_call) else "")
        elif not (h_raise or h_call):
            scen = "post: checked BB" if saw_flop else "pre: walk/none"
        elif raises >= 2:
            scen = "post: 3-bet+ pot"
        elif h_raise and first_raiser == hero:
            scen = "post: we opened"
        elif h_raise:
            scen = "post: we raised"
        elif raises == 1:
            scen = "post: called a raise"
        else:
            scen = "post: limped"
        if not saw_flop and h_fold and (h_raise or h_call):
            scen = "pre: put chips in, folded"
        rows.append((pos, scen, net, h_raise or h_call, h_raise, saw_flop, shown, dict(post)))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bot")
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--seats", type=int, default=8)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    cand = os.path.abspath(a.bot)
    field = sorted(glob.glob(os.path.join(ROOT, "zoo", "*.py"))) + sorted(glob.glob(os.path.join(KIT, "examples", "*.py")))
    if a.only:
        field = [p for p in field if name_of(p) in a.only]
    with Pool(a.jobs) as pool:
        allrows = [x for rows in pool.map(run, [(r, cand, field, a.seats, 1000, a.seed) for r in range(a.rounds)], chunksize=1) for x in rows]
    N = len(allrows)
    tot = sum(x[2] for x in allrows)
    print("%s: %d hands, %+.1f bb/100" % (name_of(cand), N, tot / N * 100))
    print("VPIP %.1f%%  PFR %.1f%%  saw flop %.1f%%  showdown %.1f%%" % (
        100 * sum(x[3] for x in allrows) / N, 100 * sum(x[4] for x in allrows) / N,
        100 * sum(x[5] for x in allrows) / N, 100 * sum(x[6] for x in allrows) / N))
    print("\n%-6s %7s %7s %7s %10s" % ("pos", "hands", "VPIP%", "PFR%", "bb/100"))
    for p in POS8:
        xs = [x for x in allrows if x[0] == p]
        if xs:
            print("%-6s %7d %7.1f %7.1f %+10.1f" % (p, len(xs), 100 * sum(x[3] for x in xs) / len(xs),
                                                   100 * sum(x[4] for x in xs) / len(xs), sum(x[2] for x in xs) / len(xs) * 100))
    print("\n%-34s %7s %8s %12s %14s" % ("scenario", "hands", "% hands", "bb per hand", "bb/100 overall"))
    by = defaultdict(list)
    for x in allrows:
        by[x[1]].append(x[2])
    for k in sorted(by, key=lambda k: -abs(sum(by[k]))):
        v = by[k]
        print("%-34s %7d %8.1f %+12.2f %+14.1f" % (k, len(v), 100 * len(v) / N, sum(v) / len(v), sum(v) / N * 100))
    sd = [x[2] for x in allrows if x[6]]
    nsd = [x[2] for x in allrows if x[5] and not x[6]]
    if sd:
        print("\nshowdowns: %d, %+.2f bb each (%+.1f bb/100 overall); postflop without showdown: %d, %+.2f bb each (%+.1f bb/100)" % (
            len(sd), sum(sd) / len(sd), sum(sd) / N * 100, len(nsd), sum(nsd) / max(1, len(nsd)), sum(nsd) / N * 100))
    post = defaultdict(int)
    for x in allrows:
        for k, v in x[7].items():
            post[k] += v
    if post["could_bet"]:
        print("postflop: bets when checked to %.1f%% (%d spots); facing a bet: fold %.1f%% call %.1f%% raise %.1f%% (%d spots)" % (
            100 * post["bet"] / post["could_bet"], post["could_bet"], 100 * post["fold_to_bet"] / max(1, post["faced_bet"]),
            100 * post["call_bet"] / max(1, post["faced_bet"]), 100 * post["raise_bet"] / max(1, post["faced_bet"]), post["faced_bet"]))


if __name__ == "__main__":
    main()
