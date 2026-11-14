"""In-process arena: hero bot vs archetype line-ups, fixed seeds, timing of act()."""
import os, sys, time, importlib, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "..", "..", "starter-kit", "imperial-ai-hack-pokerbots-kit")
sys.path.insert(0, KIT)
sys.path.insert(0, HERE)
from engine import FixedHandsTable
from engine.players import LocalPlayer
import arch


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m.Agent

TAG = load(os.path.join(KIT, "examples", "tight_aggressive.py"), "h_tag")
RND = load(os.path.join(KIT, "examples", "random_bot.py"), "h_rnd")
CS = load(os.path.join(KIT, "examples", "calling_station.py"), "h_cs")

TIMES = []


def timed(cls):
    class T(cls):
        def act(self, s):
            t = time.perf_counter(); o = cls.act(self, s); TIMES.append(time.perf_counter() - t); return o
    return T

LINEUPS = {
    "house": [TAG, CS, RND, TAG, CS, RND, TAG],
    "shove100": [arch.ShoveBot, TAG, arch.Nit, arch.EqBot, TAG, arch.Nit, arch.EqBot],
    "shove40": [arch.Shove40, TAG, arch.Nit, arch.EqBot, TAG, arch.Nit, arch.EqBot],
    "shove4": [arch.Shove4, TAG, arch.Nit, arch.EqBot, TAG, arch.Nit, arch.EqBot],
    "maniac": [arch.Maniac, TAG, arch.Nit, arch.EqBot, TAG, arch.Nit, arch.EqBot],
    "maniacs": [arch.Maniac, arch.Maniac, arch.Nit, arch.EqBot, TAG, arch.Nit, arch.EqBot],
    "nits": [arch.Nit] * 7,
    "stations": [arch.Station, arch.Station, arch.Nit, arch.EqBot, TAG, arch.Nit, arch.EqBot],
    "eqbots": [arch.EqBot] * 7,
    "lag": [arch.LAG, arch.LAG, arch.Nit, arch.EqBot, arch.LAG, arch.Nit, arch.EqBot],
    "mixed": [arch.ShoveBot, arch.Maniac, arch.Station, arch.EqBot, arch.LAG, arch.Nit, TAG],
    "mixed7": [arch.Shove40, arch.Maniac, arch.Station, arch.EqBot, arch.LAG, arch.Nit],
}


def run(hero_cls, names, rounds, hands, seed0=100, betting="no_limit", cap=0):
    out = {}
    for name in names:
        tot = 0; errs = 0; n = 0; per = []
        for r in range(rounds):
            classes = list(LINEUPS[name])
            pos = r % (len(classes) + 1)
            classes.insert(pos, timed(hero_cls))
            players = [LocalPlayer(c) for c in classes]
            res = FixedHandsTable(players, hands=hands, config={"betting": betting, "raise_cap": cap},
                                  seed=seed0 + r).play()
            tot += res["chips"][pos]; n += hands; errs += players[pos].stats.errors
            per.append(res["chips"][pos] / 20 / hands * 100)
            if players[pos].stats.error_samples:
                print(players[pos].stats.error_samples[0])
        out[name] = (tot / 20 / n * 100, errs, per)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", default=os.path.join(HERE, "bot.py"))
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--hands", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--betting", default="no_limit")
    ap.add_argument("--cap", type=int, default=0)
    ap.add_argument("names", nargs="*")
    a = ap.parse_args()
    hero = load(a.bot, "hero")
    names = a.names or list(LINEUPS)
    t0 = time.time()
    res = run(hero, names, a.rounds, a.hands, a.seed, a.betting, a.cap)
    for k, (bb, errs, per) in res.items():
        print("%-10s %+8.1f bb/100  errors %d   rounds: %s" % (k, bb, errs, " ".join("%+.0f" % x for x in per)))
    ts = sorted(TIMES)
    if ts:
        print("act(): n=%d mean %.3f ms  p50 %.3f  p99 %.3f  p99.9 %.3f  max %.3f ms; think/1000 hands %.2f s" % (
            len(ts), sum(ts) / len(ts) * 1e3, ts[len(ts) // 2] * 1e3, ts[int(len(ts) * .99)] * 1e3,
            ts[int(len(ts) * .999)] * 1e3, ts[-1] * 1e3, sum(ts) / (a.rounds * len(names) * a.hands) * 1000))
    print("%.1fs" % (time.time() - t0))
