"""TRAINING-ONLY opponent (Patch 17f) — uniform_betting_trainer.

NEVER submitted. Its only job is to decouple bet SIZE from hand STRENGTH when
generating LR training data. When it bets, it picks a size uniformly at random
from the full size space, regardless of its hand. Mixing ~30% of its data with
~70% normal selective-bet data lets the model identify the causal size->fold
effect instead of the "(strong range x scary board x big bet) -> fold" confound.

It still plays a reasonable preflop/continue game so hands reach showdown
realistically; only its bet SIZING is randomized.
"""
import random
import eval7

BOT_NAME = "UniformBettingTrainer"
RANK_VAL = {r: i for i, r in enumerate("23456789TJQKA")}
UNIFORM_SIZES = [0.25, 0.4, 0.55, 0.7, 0.9, 1.1, 1.4, 1.8]   # full size space

OPEN = {
    ('A', 'A'), ('K', 'K'), ('Q', 'Q'), ('J', 'J'), ('T', 'T'), ('9', '9'), ('8', '8'), ('7', '7'),
    ('A', 'K'), ('A', 'Q'), ('A', 'J'), ('A', 'T'), ('A', '9'), ('K', 'Q'), ('K', 'J'), ('K', 'T'),
    ('Q', 'J'), ('Q', 'T'), ('J', 'T'), ('T', '9'), ('9', '8'),
}


def _cat(hole, board):
    cats = ['High Card', 'Pair', 'Two Pair', 'Trips', 'Straight',
            'Flush', 'Full House', 'Quads', 'Straight Flush']
    ht = str(eval7.handtype(eval7.evaluate([eval7.Card(c) for c in hole + board])))
    return cats.index(ht) if ht in cats else 0


def _uniform_bet(pot, max_to, min_r):
    frac = random.choice(UNIFORM_SIZES)
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
        if state.get("current_bet", 100) > 100:
            if ranks in OPEN and owed <= pot:
                return {"action": "call"}
            return {"action": "check"} if state.get("can_check") else {"action": "fold"}
        if ranks in OPEN:
            return {"action": "raise", "amount": min(int(min_r * 2.3), max_to)}
        return {"action": "check"} if state.get("can_check") else {"action": "fold"}

    # Postflop: bet at a UNIFORM-RANDOM size with a fixed frequency that does NOT
    # depend on hand strength (the whole point — decouples size from strength).
    c = _cat(cards, board)
    if state.get("can_check"):
        if random.random() < 0.5:                  # bet half the time, size uniform-random
            return _uniform_bet(pot, max_to, min_r)
        return {"action": "check"}
    # facing a bet: continue with made hands / decent odds (so showdowns happen)
    if c >= 1:
        return {"action": "call"}
    if owed > 0 and pot / owed >= 3:
        return {"action": "call"}
    return {"action": "fold"}
