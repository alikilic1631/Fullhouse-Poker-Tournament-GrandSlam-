"""Enemy zoo (HELD-OUT): mixed_strategy_pluribus_caricature.

Patch 16a Priority 1. Genuinely MIXES — 4 bet sizings at varying frequencies,
polarized triple-barrels, tight-ish 3bet/call/fold preflop (8/10/82). Designed
to be hard to exploit, so it tests whether our perturbation/LR layers over-adjust
to noise (they shouldn't gain much here).
"""
import random
import eval7

BOT_NAME = "PluribusCaricature"
RANK_VAL = {r: i for i, r in enumerate("23456789TJQKA")}
SIZES = [0.33, 0.5, 0.75, 1.25]          # mixes four sizings
SIZE_WEIGHTS = [0.35, 0.3, 0.2, 0.15]

OPEN = {
    ('A', 'A'), ('K', 'K'), ('Q', 'Q'), ('J', 'J'), ('T', 'T'), ('9', '9'), ('8', '8'), ('7', '7'),
    ('A', 'K'), ('A', 'Q'), ('A', 'J'), ('A', 'T'), ('A', '9'), ('A', '5'), ('A', '4'),
    ('K', 'Q'), ('K', 'J'), ('K', 'T'), ('Q', 'J'), ('Q', 'T'), ('J', 'T'), ('T', '9'), ('9', '8'),
}
THREEBET = {('A', 'A'), ('K', 'K'), ('Q', 'Q'), ('A', 'K'), ('A', '5')}  # ~8%: polar value+bluff


def _cat(hole, board):
    cats = ['High Card', 'Pair', 'Two Pair', 'Trips', 'Straight',
            'Flush', 'Full House', 'Quads', 'Straight Flush']
    ht = str(eval7.handtype(eval7.evaluate([eval7.Card(c) for c in hole + board])))
    return cats.index(ht) if ht in cats else 0


def _mix_size(pot, max_to, min_r):
    frac = random.choices(SIZES, weights=SIZE_WEIGHTS, k=1)[0]
    return {"action": "raise", "amount": min(max(int(frac * pot), min_r), max_to)}


def decide(state):
    if state.get("type") == "warmup":
        return {"action": "check"}
    cards = state.get("your_cards", []) or []
    board = state.get("community_cards", []) or []
    street = state.get("street")
    pot = state.get("pot", 0)
    owed = state.get("amount_owed", 0)
    stack = state.get("your_stack", 0)
    my_bet = state.get("your_bet_this_street", 0)
    min_r = state.get("min_raise_to", 100)
    max_to = stack + my_bet

    if street == "preflop":
        ranks = tuple(sorted([c[0] for c in cards], reverse=True))
        current = state.get("current_bet", 100)
        if current > 100:                       # facing a raise: 3bet 8 / call 10 / fold 82
            if ranks in THREEBET:
                return {"action": "raise", "amount": min(int(current * 3), max_to)}
            if ranks in OPEN and random.random() < 0.30:
                return {"action": "call"}
            return {"action": "check"} if state.get("can_check") else {"action": "fold"}
        if ranks in OPEN:
            return {"action": "raise", "amount": min(int(min_r * 2.5), max_to)}
        return {"action": "check"} if state.get("can_check") else {"action": "fold"}

    # Postflop: polarized. Bet strong (value) or pure air (bluff) with mixed sizes; check medium.
    c = _cat(cards, board)
    strong = c >= 2
    medium = c == 1
    if state.get("can_check"):
        if strong:
            return _mix_size(pot, max_to, min_r)
        if not medium and random.random() < 0.40:    # polar bluff
            return _mix_size(pot, max_to, min_r)
        return {"action": "check"}
    # facing a bet
    if strong:
        if random.random() < 0.45:
            return _mix_size(pot, max_to, min_r)
        return {"action": "call"}
    if medium and owed > 0 and pot / owed >= 3:
        return {"action": "call"}
    return {"action": "fold"}
