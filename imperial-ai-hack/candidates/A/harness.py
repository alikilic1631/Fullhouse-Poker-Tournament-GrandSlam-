"""In-process strategy tests: our bot vs archetype tables, fixed seeds, act() timing.

    python3 harness.py <table> [rounds] [seed] [--bot path] [--dbg] [--seats 7]
tables: house mix shove40 shove100 shove8 maniac nit station eq tag random
"""
import importlib.util
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "starter-kit", "imperial-ai-hack-pokerbots-kit")
sys.path.insert(0, KIT)
from engine import FixedHandsTable  # noqa: E402
from engine.players import LocalPlayer  # noqa: E402


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


args = [a for a in sys.argv[1:] if not a.startswith("--")]
flags = sys.argv[1:]
botpath = os.path.join(HERE, "bot.py")
if "--bot" in flags:
    botpath = flags[flags.index("--bot") + 1]
    args.remove(botpath)
SEATS = 8
if "--seats" in flags:
    SEATS = int(flags[flags.index("--seats") + 1])
    args.remove(str(SEATS))
B = load(botpath, "cand_bot")
TAG = load(os.path.join(KIT, "examples", "tight_aggressive.py"), "h_tag").Agent
STN = load(os.path.join(KIT, "examples", "calling_station.py"), "h_stn").Agent
RND = load(os.path.join(KIT, "examples", "random_bot.py"), "h_rnd").Agent

CARD = B.CARD
PCT = B.PF_PCT


def pct(hole):
    return PCT[B._cls(CARD[hole[0]], CARD[hole[1]])]


def mk_shove(p):
    class Shove:
        def act(self, s):
            if s["street"] == "preflop" and pct(s["hole_cards"]) <= p:
                return {"action": "all_in"}
            return {"action": "check" if "check" in s["legal_actions"] else "fold"}
    return Shove


class Maniac:
    def __init__(self):
        self.r = random.Random(5)

    def act(self, s):
        x = self.r.random()
        if "raise" in s["legal_actions"] and x < 0.6:
            return {"action": "raise", "amount": s["min_raise_to"] + s["pot"]}
        if x < 0.92:
            return {"action": "call" if "call" in s["legal_actions"] else "check"}
        return {"action": "check" if "check" in s["legal_actions"] else "fold"}


class Nit:
    def act(self, s):
        legal = s["legal_actions"]
        hole = s["hole_cards"]
        if s["street"] == "preflop":
            p = pct(hole)
            if p <= 0.04 and "raise" in legal:
                return {"action": "raise", "amount": max(s["min_raise_to"], 3 * (s["to_call"] + 20))}
            if p <= 0.09:
                if s["to_call"] <= 60:
                    if "raise" in legal and s["raises_this_street"] == 0:
                        return {"action": "raise", "amount": 60}
                    return {"action": "call" if "call" in legal else "check"}
            return {"action": "check" if "check" in legal else "fold"}
        cards = [CARD[c] for c in hole + s["board"]]
        cat = B.ev(cards) >> 20
        bcat = B.ev([CARD[c] for c in s["board"]]) >> 20 if len(s["board"]) >= 5 else 0
        top = max(CARD[c] >> 2 for c in s["board"])
        haspair_top = any(CARD[c] >> 2 >= top for c in hole) and cat >= 1
        if cat >= 2 and cat > bcat:
            if "raise" in legal:
                return {"action": "raise", "amount": s["min_raise_to"] + int(0.7 * s["pot"])}
            return {"action": "call" if "call" in legal else "check"}
        if haspair_top:
            if s["to_call"] == 0 and "raise" in legal:
                return {"action": "raise", "amount": s["min_raise_to"] + int(0.5 * s["pot"])}
            if s["to_call"] <= 0.6 * s["pot"]:
                return {"action": "call" if "call" in legal else "check"}
        return {"action": "check" if "check" in legal else "fold"}


class EqBot:
    """The typical quick bot: equity vs ONE random hand + thresholds."""
    def __init__(self):
        self.r = random.Random(11)

    def eq(self, hole, board, n=60):
        h = [CARD[c] for c in hole]
        b = [CARD[c] for c in board]
        deck = [c for c in range(52) if c not in h and c not in b]
        w = 0.0
        for _ in range(n):
            d = self.r.sample(deck, 2 + 5 - len(b))
            bb = b + d[2:]
            a = B.ev(h + bb)
            v = B.ev(d[:2] + bb)
            w += 1.0 if a > v else (0.5 if a == v else 0.0)
        return w / n

    def act(self, s):
        legal = s["legal_actions"]
        e = self.eq(s["hole_cards"], s["board"])
        tc = s["to_call"]
        pot = s["pot"]
        po = tc / (pot + tc) if tc else 0.0
        if s["street"] == "preflop":
            if e > 0.66 and "raise" in legal:
                return {"action": "raise", "amount": max(s["min_raise_to"], 3 * max(tc, 20) + 20)}
            if e > 0.55 and tc <= 200 or e > po + 0.12 and tc <= 80:
                return {"action": "call" if "call" in legal else "check"}
            return {"action": "check" if "check" in legal else "fold"}
        if e > 0.75 and "raise" in legal:
            return {"action": "raise", "amount": s["min_raise_to"] + int(0.7 * pot)}
        if tc == 0 and e > 0.6 and "raise" in legal:
            return {"action": "raise", "amount": s["min_raise_to"] + int(0.4 * pot)}
        if tc and e > po + 0.08:
            return {"action": "call"}
        return {"action": "check" if "check" in legal else "fold"}


ZOO = {}
_zd = os.path.join(os.path.dirname(os.path.dirname(HERE)), "zoo")
if os.path.isdir(_zd):
    for _f in sorted(os.listdir(_zd)):
        if _f.endswith(".py"):
            try:
                _c = load(os.path.join(_zd, _f), "zoo_" + _f[:-3]).Agent
                ZOO[_f[:-3]] = type(_f[:-3], (_c,), {})
            except Exception as _e:
                print("zoo load failed", _f, _e)
ZFISH = ["limp_caller", "maniac", "minraise", "pot_odds", "shove_loose", "station_any", "station_cap"]
ZMED = ["barreler", "cbet_fold", "fit_or_fold", "lag", "mc_threshold", "nit", "shove_tight", "tag_charts", "trapper"]
ZSTR = ["ref_lag", "ref_tag"]


def zpick(rng, table):
    if table == "zmix":
        return [ZOO[k] for k in rng.sample(sorted(ZOO), 7)]
    if table == "zfield":
        return [ZOO[k] for k in rng.sample(ZFISH, 2) + rng.sample(ZMED, 3) + ZSTR]
    if table == "zfish":
        return [ZOO[k] for k in ZFISH]
    if table == "zmed":
        return [ZOO[k] for k in rng.sample(ZMED, 7)]
    if table == "zstrong":
        return [ZOO[k] for k in ["ref_lag", "ref_tag", "tag_charts", "lag", "mc_threshold", "barreler", "trapper"]]
    if table == "ztough":
        return [ZOO["ref_lag"], ZOO["ref_tag"]] * 3 + [ZOO["tag_charts"]]
    names = table[2:].split(",")
    return [ZOO[names[i % len(names)]] for i in range(7)]


TABLES = {
    "house": None,
    "mix": [mk_shove(0.4), Maniac, Nit, STN, EqBot, TAG, RND],
    "shove40": [mk_shove(0.4)] * 2 + [TAG, Nit, EqBot, EqBot, STN],
    "shove100": [mk_shove(1.0)] * 2 + [TAG, Nit, EqBot, EqBot, STN],
    "shove8": [mk_shove(0.08)] * 2 + [TAG, Nit, EqBot, EqBot, STN],
    "maniac": [Maniac] * 3 + [TAG, Nit, EqBot, EqBot],
    "nit": [Nit] * 7,
    "station": [STN] * 4 + [TAG, Nit, EqBot],
    "eq": [EqBot] * 7,
    "tag": [TAG] * 7,
    "random": [RND] * 4 + [TAG, Nit, EqBot],
}

times = []
ATTR = {}


class Timed(B.Agent):
    def act(self, state):
        t = time.perf_counter()
        r = B.Agent.act(self, state)
        times.append(time.perf_counter() - t)
        return r


def run(table, rounds, seed):
    rng = random.Random(seed)
    tot = {}
    hands = 0
    last = None
    errs = 0
    for r in range(rounds):
        if table.startswith("z"):
            opp = zpick(rng, table)[:SEATS - 1]
        elif TABLES[table] is None:
            opp = [rng.choice([TAG, STN, RND]) for _ in range(SEATS - 1)]
        else:
            opp = list(TABLES[table])[:SEATS - 1]
        seats = [Timed] + opp
        rng.shuffle(seats)
        players = [LocalPlayer(c) for c in seats]
        res = FixedHandsTable(players, hands=1000, seed=rng.random(), record="--attr" in flags).play()
        hands += res["hands"]
        if "--attr" in flags:
            me = seats.index(Timed)
            for rec in res["log"]:
                d = [e - 2000 for e in rec["end"]]
                our = d[me]
                if not our:
                    continue
                flop = any(ev[0] == "board" for ev in rec["events"])
                side = [j for j in range(len(d)) if j != me and (d[j] < 0 if our > 0 else d[j] > 0)]
                tot_side = sum(abs(d[j]) for j in side) or 1
                for j in side:
                    key = (seats[j].__name__, "post" if flop else "pre")
                    ATTR[key] = ATTR.get(key, 0.0) + our * abs(d[j]) / tot_side
        for i, c in enumerate(seats):
            nm = "US" if c is Timed else c.__name__
            tot.setdefault(nm, [0, 0])
            tot[nm][0] += res["chips"][i]
            tot[nm][1] += res["hands"]
            if c is Timed:
                last = (players[i].agent, seats)
                errs += players[i].stats.errors
    print("== %s: %d rounds, seed %s" % (table, rounds, seed))
    for nm, (ch, h) in sorted(tot.items(), key=lambda kv: -kv[1][0] / kv[1][1]):
        print("  %-10s %+9.1f bb/100  (%d seat-hands)" % (nm, ch / 20.0 / h * 100, h))
    ts = sorted(times)
    if ts:
        print("  act(): n=%d mean=%.3fms p50=%.3f p99=%.3f max=%.3f  total/round=%.2fs errors=%d" % (
            len(ts), 1000 * sum(ts) / len(ts), 1000 * ts[len(ts) // 2], 1000 * ts[int(len(ts) * 0.99)],
            1000 * ts[-1], sum(ts) / rounds, errs))
    if ATTR:
        names = sorted(set(k[0] for k in ATTR))
        print("  our P&L by opponent (bb/100 of OUR hands): name pre / post / total")
        for nm in sorted(names, key=lambda x: ATTR.get((x, "pre"), 0) + ATTR.get((x, "post"), 0)):
            a, b = ATTR.get((nm, "pre"), 0.0), ATTR.get((nm, "post"), 0.0)
            print("    %-13s %+8.1f %+8.1f %+8.1f" % (nm, a / 20 / hands * 100, b / 20 / hands * 100,
                                                    (a + b) / 20 / hands * 100))
    if "--dbg" in flags and last:
        ag, seats = last
        for s, c in enumerate(seats):
            if c is Timed:
                continue
            o = ag.opp[s]
            P = ag._prof(s)
            top = sorted(range(7), key=lambda k: -P.A[k])[:2]
            print("  seat %d %-8s act=%d vpip=%.2f pfr=%.2f shv=%.2f g=%.2f ratio=%.2f psh=%.2f ab=%.2f cq=%.2f "
                  "fold=%s arch=%s" % (s, c.__name__, o.n_act, o.vpip / max(1, o.hands), o.pfr / max(1, o.hands),
                                       o.shv / max(1, o.hands), P.g, P.ratio, P.psh, P.ab, P.cq,
                                       ["%.2f" % f for f in P.fold],
                                       ", ".join("%s %.2f" % (B.ARCH[k], P.A[k]) for k in top)))


if __name__ == "__main__":
    table = args[0] if args else "house"
    rounds = int(args[1]) if len(args) > 1 else 3
    seed = int(args[2]) if len(args) > 2 else 1
    run(table, rounds, seed)
