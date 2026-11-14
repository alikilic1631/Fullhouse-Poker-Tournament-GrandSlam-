"""Evaluator check vs engine.cards.evaluate: identical ordering and ties."""
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "starter-kit", "imperial-ai-hack-pokerbots-kit")
sys.path.insert(0, KIT)
sys.path.insert(0, HERE)
from engine.cards import evaluate  # noqa: E402

t0 = time.perf_counter()
import bot  # noqa: E402
print("import %.3fs, NOFLUSH %d entries" % (time.perf_counter() - t0, len(bot.NOFLUSH)))


def pack(t):
    v = t[0] << 20
    s = 16
    for x in t[1:]:
        v |= x << s
        s -= 4
    return v


rng = random.Random(7)
deck = list(range(52))
N = int(sys.argv[1]) if len(sys.argv) > 1 else 300000
bad = 0
prev = None
for k in range(N):
    n = (5, 6, 7)[k % 3]
    h = rng.sample(deck, n)
    e = evaluate(h)
    m = bot.ev(h)
    if pack(e) != m:
        bad += 1
        if bad < 5:
            print("MISMATCH", h, e, hex(m))
    if prev is not None:
        pe, pm = prev
        if (e > pe) != (m > pm) or (e == pe) != (m == pm):
            bad += 1
    prev = (e, m)
print("checked %d hands, mismatches: %d" % (N, bad))
