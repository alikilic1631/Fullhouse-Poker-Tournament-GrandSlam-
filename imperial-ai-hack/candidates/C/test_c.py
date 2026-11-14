"""Test harness for candidate C: evaluator check, in-process matches vs archetypes, timing."""
import importlib.util
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "starter-kit", "imperial-ai-hack-pokerbots-kit")
sys.path.insert(0, KIT)
sys.path.insert(0, HERE)
from engine import FixedHandsTable  # noqa: E402
from engine.cards import evaluate  # noqa: E402
from engine.players import LocalPlayer  # noqa: E402


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def check_eval(bot, n=240000, seed=5):
    rng = random.Random(seed)
    deck = list(range(52))
    bad = 0
    for k in range(n // 2):
        m = rng.choice((5, 6, 7))
        cs = rng.sample(deck, m * 2)
        a, b = cs[:m], cs[m:]
        if m == 7 and k % 3 == 0:      # shared board, like a real showdown
            b = a[:5] + b[:2]
        ea, eb = evaluate(a), evaluate(b)
        ma, mb = bot.ev(a), bot.ev(b)
        if (ea > eb) != (ma > mb) or (ea == eb) != (ma == mb) or (ea[0] != ma >> 20):
            bad += 1
    print("evaluator: %d hands compared, %d mismatches" % (n, bad))
    return bad


# ------------------------------------------------------------ archetypes
RK = "23456789TJQKA"


def pf_strength(hole):
    a, b = sorted((RK.index(c[0]) for c in hole), reverse=True)
    if a == b:
        return 0.5 + a / 24
    return (a + b) / 24 + (0.06 if hole[0][1] == hole[1][1] else 0) - (0.04 if a - b > 4 else 0)


class ShoveBot:
    FREQ = 0.30

    def __init__(self):
        self.rng = random.Random(11)

    def act(self, s):
        if s["street"] == "preflop":
            if pf_strength(s["hole_cards"]) >= self.THR:
                return {"action": "all_in"}
            return {"action": "check"} if "check" in s["legal_actions"] else {"action": "fold"}
        return {"action": "check"} if "check" in s["legal_actions"] else {"action": "call"}


class Shove30(ShoveBot):
    THR = 0.62


class Shove5(ShoveBot):
    THR = 0.86


class Maniac:
    def __init__(self):
        self.rng = random.Random(12)

    def act(self, s):
        legal = s["legal_actions"]
        r = self.rng.random()
        if "raise" in legal and r < 0.6:
            lo, hi = s["min_raise_to"], s["max_raise_to"]
            return {"action": "raise", "amount": min(hi, max(lo, s["pot"] + s["to_call"]))}
        if "call" in legal and r < 0.92:
            return {"action": "call"}
        return {"action": "check"} if "check" in legal else {"action": "fold"}


class Nit:
    def act(self, s):
        legal = s["legal_actions"]
        st = pf_strength(s["hole_cards"])
        if s["street"] == "preflop":
            if st >= 0.9 and "raise" in legal:
                return {"action": "raise", "amount": min(s["max_raise_to"], max(s["min_raise_to"], 3 * s["to_call"] + 60))}
            if st >= 0.8 and s["to_call"] <= 80:
                return {"action": "call"} if "call" in legal else {"action": "check"}
            return {"action": "check"} if "check" in legal else {"action": "fold"}
        ranks = [c[0] for c in s["hole_cards"] + s["board"]]
        top = max(RK.index(c[0]) for c in s["board"])
        good = any(ranks.count(r) >= 2 and RK.index(r) >= top for r in set(c[0] for c in s["hole_cards"]))
        if good:
            if "raise" in legal and s["to_call"] == 0:
                return {"action": "raise", "amount": min(s["max_raise_to"], max(s["min_raise_to"], int(0.6 * s["pot"])))}
            return {"action": "call"} if "call" in legal else {"action": "check"}
        return {"action": "check"} if "check" in legal else {"action": "fold"}


class Station:
    def act(self, s):
        return {"action": "check" if "check" in s["legal_actions"] else "call"}


class EqBot:
    """Equity vs random hands + thresholds (the typical quickly written bot)."""
    def __init__(self):
        self.rng = random.Random(13)
        import bot as B
        self.B = B

    def act(self, s):
        B = self.B
        legal = s["legal_actions"]
        h = [B.CARD[c] for c in s["hole_cards"]]
        bd = [B.CARD[c] for c in s["board"]]
        nopp = max(1, sum(1 for f in s["folded"] if not f) - 1)
        if not bd:
            eq = B.PF_VS_RANDOM[B.CCLS[B.CIDX[h[0] * 52 + h[1]]]]
        else:
            deck = [c for c in range(52) if c not in h and c not in bd]
            w = 0.0
            N = 60
            for _ in range(N):
                x = self.rng.sample(deck, 2 + 5 - len(bd))
                full = bd + x[2:]
                a, b = B.ev(h + full), B.ev(x[:2] + full)
                w += 1 if a > b else 0.5 if a == b else 0
            eq = w / N
        eq = eq ** nopp
        pot, tc = s["pot"], s["to_call"]
        if eq > 0.7 and "raise" in legal:
            return {"action": "raise", "amount": min(s["max_raise_to"], max(s["min_raise_to"], int(tc + 0.7 * (pot + tc))))}
        if tc == 0:
            if eq > 0.5 and "raise" in legal:
                return {"action": "raise", "amount": min(s["max_raise_to"], max(s["min_raise_to"], int(0.5 * pot)))}
            return {"action": "check"}
        if eq > tc / float(pot + tc) + 0.05:
            return {"action": "call"}
        return {"action": "fold"}


class Timed(LocalPlayer):
    def __init__(self, cls):
        LocalPlayer.__init__(self, cls)
        self.times = []

    def act(self, state):
        t0 = time.perf_counter()
        out = LocalPlayer.act(self, state)
        self.times.append((time.perf_counter() - t0) * 1000)
        return out


def match(hero_cls, opp_classes, rounds=3, hands=1000, seed=1, config=None, verbose=True):
    """Hero + the given opponents (cycled to fill 8 seats, or exact list). Returns bb/100 and timings."""
    rng = random.Random(seed)
    tot = 0
    times = []
    errs = 0
    think = []
    for r in range(rounds):
        seats = [("H", hero_cls)] + [("O", c) for c in opp_classes]
        rng.shuffle(seats)
        players = [Timed(c) if k == "H" else LocalPlayer(c) for k, c in seats]
        res = FixedHandsTable(players, hands=hands, config=config, seed=rng.random()).play()
        for i, (k, c) in enumerate(seats):
            if k == "H":
                tot += res["chips"][i]
                times += players[i].times
                errs += players[i].stats.errors + getattr(players[i].agent, "errs", 0)
                think.append(sum(players[i].times) / 1000.0)
                if players[i].stats.error_samples:
                    print(players[i].stats.error_samples[0])
    times.sort()
    bb100 = tot / 20.0 / (rounds * hands) * 100
    p99 = times[int(len(times) * 0.99)] if times else 0
    out = dict(bb100=bb100, p50=times[len(times) // 2] if times else 0, p99=p99, mx=times[-1] if times else 0,
               errs=errs, think=max(think) if think else 0, n=len(times))
    if verbose:
        print("  bb/100 %+8.1f | act ms p50 %.3f p99 %.3f max %.3f | think/rd %.2fs | errors %d | decisions %d"
              % (out["bb100"], out["p50"], out["p99"], out["mx"], out["think"], errs, out["n"]))
    return out


if __name__ == "__main__":
    bot = load(os.path.join(HERE, sys.argv[2] if len(sys.argv) > 2 else "bot.py"), "bot")
    sys.modules["bot"] = bot
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    if what in ("eval", "all"):
        check_eval(bot)
    ex = os.path.join(KIT, "examples")
    TA = load(os.path.join(ex, "tight_aggressive.py"), "ta").Agent
    CS = load(os.path.join(ex, "calling_station.py"), "cs").Agent
    RB = load(os.path.join(ex, "random_bot.py"), "rb").Agent
    tables = {
        "house": [TA, CS, RB, TA, CS, RB, TA],
        "shove30": [Shove30, Shove30, TA, TA, Nit, Nit, TA],
        "shove5": [Shove5, Shove5, TA, TA, Nit, Nit, TA],
        "maniac": [Maniac, Maniac, TA, TA, Nit, Nit, TA],
        "nit": [Nit] * 7,
        "station": [Station, Station, Station, TA, TA, Nit, Nit],
        "eqbot": [EqBot] * 7,
        "mixed": [EqBot, Maniac, Shove30, Station, Nit, TA, EqBot],
        "self": [bot.Agent] * 3 + [EqBot, TA, Nit, Station],
    }
    for name, opps in tables.items():
        if what in ("all", "tables", name):
            print(name)
            match(bot.Agent, opps, rounds=rounds, seed=7)
