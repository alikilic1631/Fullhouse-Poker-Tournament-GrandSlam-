#!/usr/bin/env python3
"""duel_ends.py - duel.py plus per-pair outcome and action counters in the JSON (added Sun 15 Nov, test runs).

    python3 duel_ends.py <exactly the duel.py arguments>      e.g.
    python3 duel_ends.py --cand X.py --base ../v11/bot.py --table-file tables/sunday.txt --seeds 30 --rotations 8 \
        --seed0 201 --adaptive --name tadapt_X
    python3 ends_report.py out/duel_tadapt_X.json [more.json ...]   # paired breakdowns with standard errors

It runs duel.main() unchanged: the same games, the same printed report and the same out/duel_<name>.json. The
only addition is bookkeeping: every pair record gets, for each side ('cand' / 'base'),
  end : duel.analyse's own outcome split {uncontested|sd_won|sd_lost|folded: [hands, chips]} (raw chips)
  x   : extra counters from the same hand records (extra_stats below):
        unc / fold   [hands, chips] per street where the hand ended (0 preflop .. 3 river)
        open         our preflop opens (first raise of the hand)
        o3           per opponent: [times he acted facing our open with no re-raise yet, times he 3-bet]
        f3           our answer to a single 3-bet of our open: [faced, fold, call, 4-bet]; f3by per 3-bettor
        our3         our 3-bets (raise over exactly one raise): [n, opener folds, calls, 4-bets]; our3by per opener
        bet          our postflop bets into no bet, key 'street|bucket|hu-or-mw|v-or-n' -> [n, everyone folded at
                     once]; bucket = clone.bucket(bet / pot), v = top pair or better with a hole card
                     (clone_adapt.value_hand), n = anything else (bluffs and draws)
The extra code never changes a decision (it reads the finished hand records) and any error in it is stored in
x['err'] instead of failing the pair. duel.py itself is not modified.
"""
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import duel  # noqa: E402

_CL = None
_CA = None


def _mods():
    global _CL, _CA
    if _CL is None:
        import clone as cl
        import clone_adapt as ca
        _CL, _CA = cl, ca
    return _CL, _CA


def extra_stats(log, hero, names):
    cl, ca = _mods()
    n = len(names)
    x = {"unc": [[0, 0] for _ in range(4)], "fold": [[0, 0] for _ in range(4)], "open": 0, "o3": {},
         "f3": [0, 0, 0, 0], "f3by": {}, "our3": [0, 0, 0, 0], "our3by": {}, "bet": {}}
    for rec in log:
        ev = rec["events"]
        start, end = rec["stacks"], rec["end"]
        r = end[hero] - start[hero]
        sd = rec.get("showdown") or {}
        hole = rec["hole"].get(str(hero))
        h1 = h2 = None
        if hole:
            h1, h2 = cl.CI[hole[0]], cl.CI[hole[1]]
        bets = [0] * n
        contrib = [0] * n
        folded = [False] * n
        street = 0
        board = []
        nr = 0                  # raises this street
        first_raiser = -1       # preflop
        hero_open = False
        three_bettor = -1       # first re-raiser of our open
        f3_done = False
        our3_opener = -1
        our3_done = False
        pend = None             # our open postflop bet waiting for answers: [key, others still to answer]
        fold_st = None
        for e in ev:
            t = e[0]
            if t == "post":
                bets[e[1]] += e[2]
                contrib[e[1]] += e[2]
            elif t == "board":
                street += 1
                board = [cl.CI[c] for c in e[2]]
                bets = [0] * n
                nr = 0
                pend = None
            elif t == "refund":
                bets[e[1]] -= e[2]
                contrib[e[1]] -= e[2]
            elif t == "act":
                i, a, amt = e[1], e[2], e[3]
                hi = max(bets)
                pot = sum(contrib)
                # ---- answers to our pending postflop bet
                if pend is not None and i != hero:
                    if a == "fold":
                        pend[1] -= 1
                        if pend[1] <= 0:
                            x["bet"][pend[0]][1] += 1
                            pend = None
                    else:
                        pend = None
                # ---- preflop bookkeeping
                if street == 0:
                    if hero_open and i != hero and nr == 1:
                        o = x["o3"].setdefault(names[i], [0, 0])
                        o[0] += 1
                        if a == "raise":
                            o[1] += 1
                            three_bettor = i
                    if i == hero and hero_open and not f3_done and nr >= 2:
                        f3_done = True
                        if nr == 2 and three_bettor >= 0:
                            k = {"fold": 1, "call": 2, "raise": 3}.get(a)
                            x["f3"][0] += 1
                            fb = x["f3by"].setdefault(names[three_bettor], [0, 0])
                            fb[0] += 1
                            if k:
                                x["f3"][k] += 1
                                if k == 1:
                                    fb[1] += 1
                    if our3_opener >= 0 and i == our3_opener and not our3_done:
                        our3_done = True
                        k = {"fold": 1, "call": 2, "raise": 3}.get(a)
                        ob = x["our3by"].setdefault(names[i], [0, 0])
                        if k:
                            x["our3"][k] += 1
                            if k == 1:
                                ob[1] += 1
                    if a == "raise":
                        if nr == 0:
                            first_raiser = i
                            if i == hero:
                                hero_open = True
                                x["open"] += 1
                        elif nr == 1 and i == hero and first_raiser >= 0 and first_raiser != hero:
                            our3_opener = first_raiser
                            x["our3"][0] += 1
                            x["our3by"].setdefault(names[first_raiser], [0, 0])[0] += 1
                # ---- our postflop bets into no bet
                if street >= 1 and i == hero and a == "raise" and hi == 0:
                    live = [j for j in range(n) if not folded[j]]
                    frac = amt / pot if pot > 0 else 1.0
                    vv = "v" if (h1 is not None and ca.value_hand(h1, h2, board)) else "n"
                    key = "%d|%s|%s|%s" % (street, cl.bucket(frac), "hu" if len(live) == 2 else "mw", vv)
                    x["bet"].setdefault(key, [0, 0])[0] += 1
                    pend = [key, len(live) - 1]
                # ---- apply the action
                if a == "raise":
                    add = amt - bets[i]
                    bets[i] = amt
                    contrib[i] += add
                    nr += 1
                elif a == "call":
                    bets[i] += amt
                    contrib[i] += amt
                elif a == "fold":
                    folded[i] = True
                    if i == hero:
                        fold_st = street
        if str(hero) in sd:
            continue
        if fold_st is not None:
            c = x["fold"][fold_st]
        else:
            c = x["unc"][min(street, 3)]
        c[0] += 1
        c[1] += r
    return x


_orig_analyse = duel.analyse


def analyse_plus(log, hero, names, st):
    st = _orig_analyse(log, hero, names, st)
    try:
        st["x"] = extra_stats(log, hero, names)
    except Exception:
        st["x"] = {"err": traceback.format_exc(limit=6)}
    return st


duel.analyse = analyse_plus
_orig_compact = duel.compact_pair


def compact_plus(r):
    o = _orig_compact(r)
    if "failed" not in r:
        for which in ("cand", "base"):
            s = r[which]["stats"]
            o[which]["end"] = {k: list(v) for k, v in s["end"].items()}
            o[which]["x"] = s.get("x")
            o[which]["vs_hands"] = dict(s.get("vs_hands", {}))
    return o


duel.compact_pair = compact_plus

if __name__ == "__main__":
    duel.main()
