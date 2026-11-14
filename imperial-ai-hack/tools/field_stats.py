#!/usr/bin/env python3
"""Population tendencies of the real field from fetched rounds (hero's own actions excluded).
    python3 tools/field_stats.py hands/*.json"""
import json, sys
from collections import defaultdict
C = defaultdict(lambda: defaultdict(int))
def bucket(tc, pot_incl):
    rho = tc / pot_incl if pot_incl > 0 else 1.0
    return 0 if rho < 0.30 else (1 if rho < 0.45 else (2 if rho < 0.58 else 3))
def add(key, a): C[key]["n"] += 1; C[key][a] += 1
for path in sys.argv[1:]:
    d = json.load(open(path)); hero = d["seat"]; n = len(d["players"])
    for h in d["hands"]:
        street = "preflop"; si = 0; bets = defaultdict(int); lvl = 0; pot = 0; nr = 0
        raised = set(); limped = set(); acted = set(); last_raiser = None; pfr = None; bettor = None; nbets = 0
        stack = {i: 2000 for i in range(n)}
        for ev in h["events"]:
            if ev[0] == "post":
                bets[ev[1]] += ev[2]; pot += ev[2]; lvl = max(lvl, bets[ev[1]]); stack[ev[1]] -= ev[2]; continue
            if ev[0] == "board":
                street = ev[1]; si += 1; bets = defaultdict(int); lvl = 0; bettor = None; nbets = 0; acted = set(); continue
            if ev[0] != "act": continue
            _, seat, a, amt = ev
            tc = lvl - bets[seat]
            me = seat == hero
            if si == 0:
                shove_faced = tc >= 660
                if not me:
                    if shove_faced:
                        add("pre: facing shove, " + ("already raised" if seat in raised else ("already limped/called" if seat in acted else "cold")), a)
                    elif nr == 0:
                        nb = n - len(acted) - 1 - (0 if seat in (h["events"][0][1], h["events"][1][1]) else 0)
                        add("pre: unopened (any pos)", a)
                        if limped: add("pre: facing limpers only", a)
                    elif nr == 1:
                        if seat in limped: add("pre: limper facing raise", a)
                        else: add("pre: cold facing 1 raise" + (" (BB)" if seat == h["events"][1][1] else ""), a)
                    elif seat in raised:
                        add("pre: RAISER facing re-raise (nr=%s)" % ("2" if nr == 2 else "3+"), a)
                    else:
                        add("pre: cold facing 3-bet+", a)
                    if a == "raise": add("pre: raise is shove? (nr=%d)" % min(nr, 2), "shove" if amt >= 800 else "normal")
                if a == "raise":
                    if nr == 0 and not me: C["open size bb"]["n"] += 1; C["open size bb"]["sum"] += amt / 20
                    nr += 1; raised.add(seat); last_raiser = seat; pfr = seat
                elif a == "call" and nr == 0: limped.add(seat)
            else:
                if not me:
                    if tc <= 0:
                        role = "PFR" if seat == pfr else "non-PFR"
                        add("post %s: checked to, %s" % (street, role), a)
                        if a == "raise": C["bet size/pot %s" % street]["n"] += 1; C["bet size/pot %s" % street]["sum"] += amt / max(1, pot)
                    else:
                        b = bucket(tc, pot)
                        if nbets >= 2 and seat == prev_bettor: add("post: BETTOR facing a raise", a)
                        else:
                            add("post %s: facing bet, price bucket %d" % (street, b), a)
                            add("post all: facing bet, bucket %d" % b, a)
                            if nbets >= 2: add("post: non-bettor facing a raise (cold)", a)
                if a == "raise":
                    prev_bettor = bettor; bettor = seat; nbets += 1
            acted.add(seat)
            if a == "call": bets[seat] += amt; pot += amt
            elif a == "raise": pot += amt - bets[seat]; bets[seat] = amt; lvl = amt
print("%-46s %6s %7s %7s %7s %7s" % ("spot", "n", "fold%", "check%", "call%", "raise%"))
for k in sorted(C):
    c = C[k]; nn = c["n"]
    if "sum" in c: print("%-46s %6d   mean %.2f" % (k, nn, c["sum"] / nn)); continue
    if "shove" in c or "normal" in c: print("%-46s %6d   shove %.0f%%" % (k, nn, 100 * c["shove"] / nn)); continue
    print("%-46s %6d %7.0f %7.0f %7.0f %7.0f" % (k, nn, 100 * c["fold"] / nn, 100 * c["check"] / nn, 100 * c["call"] / nn, 100 * c["raise"] / nn))
