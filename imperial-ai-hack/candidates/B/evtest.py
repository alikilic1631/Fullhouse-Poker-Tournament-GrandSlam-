"""Verify the table evaluator against engine.cards.evaluate (ordering and ties)."""
import os, sys, random
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "starter-kit", "imperial-ai-hack-pokerbots-kit"))
sys.path.insert(0, HERE)
from engine.cards import evaluate
import bot
rng = random.Random(7)
N = int(sys.argv[1]) if len(sys.argv) > 1 else 300000
bad = 0
deck = list(range(52))
prev = None
for i in range(N):
    k = rng.choice((5, 6, 7))
    a = rng.sample(deck, k); b = rng.sample(deck, k)
    ea, eb = evaluate(a), evaluate(b)
    fa, fb = bot.ev7(a), bot.ev7(b)
    if (ea > eb) != (fa > fb) or (ea == eb) != (fa == fb) or (ea[0] != fa >> 20):
        bad += 1
        if bad < 5: print("MISMATCH", a, b, ea, eb, fa, fb)
print("hands compared: %d pairs (%d evaluations), mismatches: %d" % (N, 2 * N, bad))
