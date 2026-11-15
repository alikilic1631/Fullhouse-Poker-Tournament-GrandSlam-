"""Stand-alone stdlib hand evaluator (copied from pokerdash/analytics.py).

    card("As") -> (14, "s");  eval7(cards) -> comparable tuple, element 0 = category
    (0 high card, 1 pair, 2 two pair, 3 trips, 4 straight, 5 flush, 6 full house, 7 quads, 8 straight flush);
    equities(hands, board, samples=1500, seed=7) -> share of pot per hand (exact with <= 2 cards to come).
"""
import itertools
import random
from collections import Counter

# --------------------------------------------------------------------------- hand evaluator
_RANK = {r: i for i, r in enumerate("23456789TJQKA", start=2)}
DECK = [(r, s) for r in range(2, 15) for s in "cdhs"]


def card(c):
    return (_RANK[c[0]], c[1])


def _straight_high(rset):
    if 14 in rset:
        rset = rset | {1}
    for hi in range(14, 4, -1):
        if hi in rset and hi - 1 in rset and hi - 2 in rset and hi - 3 in rset and hi - 4 in rset:
            return hi
    return 0


def eval7(cards):
    """Comparable strength tuple of the best 5-card hand among 5-7 cards."""
    ranks = [r for r, _ in cards]
    suits = Counter(s for _, s in cards)
    fs = None
    for s, c in suits.items():
        if c >= 5:
            fs = s
    fr = None
    if fs:
        fr = sorted((r for r, s in cards if s == fs), reverse=True)
        sf = _straight_high(set(fr))
        if sf:
            return (8, sf)
    cnt = Counter(ranks)
    quads = [r for r, c in cnt.items() if c == 4]
    if quads:
        q = max(quads)
        return (7, q, max(r for r in ranks if r != q))
    trips = sorted((r for r, c in cnt.items() if c == 3), reverse=True)
    pairs = sorted((r for r, c in cnt.items() if c == 2), reverse=True)
    if trips and (len(trips) > 1 or pairs):
        return (6, trips[0], max(trips[1:] + pairs))
    if fr:
        return (5,) + tuple(fr[:5])
    st = _straight_high(set(ranks))
    if st:
        return (4, st)
    singles = sorted(set(ranks), reverse=True)
    if trips:
        t = trips[0]
        return (3, t) + tuple(r for r in singles if r != t)[:2]
    if len(pairs) >= 2:
        p1, p2 = pairs[0], pairs[1]
        return (2, p1, p2, max(r for r in singles if r != p1 and r != p2))
    if pairs:
        p = pairs[0]
        return (1, p) + tuple(r for r in singles if r != p)[:3]
    return (0,) + tuple(singles[:5])


def equities(hands, board, samples=1500, seed=7):
    """Share of the pot each hand wins over the remaining runouts (exact if <=2 cards to come)."""
    used = set(board)
    for h in hands:
        used.update(h)
    deck = [c for c in DECK if c not in used]
    need = 5 - len(board)
    if need <= 0:
        runs = [()]
    elif need <= 2:
        runs = itertools.combinations(deck, need)
    else:
        rng = random.Random(seed)
        runs = (tuple(rng.sample(deck, need)) for _ in range(samples))
    share = [0.0] * len(hands)
    tot = 0
    for run in runs:
        b = list(board) + list(run)
        vals = [eval7(h + b) for h in hands]
        best = max(vals)
        winners = [i for i, v in enumerate(vals) if v == best]
        for i in winners:
            share[i] += 1.0 / len(winners)
        tot += 1
    return [s / tot for s in share] if tot else [1.0 / len(hands)] * len(hands)


