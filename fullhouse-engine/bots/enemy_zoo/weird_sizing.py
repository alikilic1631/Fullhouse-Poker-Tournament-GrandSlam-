"""Enemy zoo (held-out): weird_sizing — uses unusual bet sizes (37%, 88%, 113% pot)."""
import random
import eval7

BOT_NAME = "WeirdSizing"
SIZES = [0.37, 0.88, 1.13]

PLAYABLE = {
    ('A', 'A'), ('K', 'K'), ('Q', 'Q'), ('J', 'J'), ('T', 'T'), ('9', '9'), ('8', '8'), ('7', '7'),
    ('A', 'K'), ('A', 'Q'), ('A', 'J'), ('A', 'T'), ('A', '9'),
    ('K', 'Q'), ('K', 'J'), ('K', 'T'), ('Q', 'J'), ('Q', 'T'), ('J', 'T'), ('T', '9'),
}


def _cat(hole, board):
    cats = ['High Card', 'Pair', 'Two Pair', 'Trips', 'Straight',
            'Flush', 'Full House', 'Quads', 'Straight Flush']
    ht = eval7.handtype(eval7.evaluate([eval7.Card(c) for c in hole + board]))
    try:
        return cats.index(ht)
    except ValueError:
        return 0


def _weird_raise(pot, max_to, min_r):
    size = random.choice(SIZES)
    amt = int(pot * size)
    amt = max(amt, min_r)
    return {"action": "raise", "amount": min(amt, max_to)}


def decide(state):
    if state.get("type") == "warmup":
        return {"action": "check"}

    cards = state.get("your_cards", []) or []
    board = state.get("community_cards", []) or []
    stack = state.get("your_stack", 0)
    my_bet = state.get("your_bet_this_street", 0)
    min_r = state.get("min_raise_to", 100)
    pot = state.get("pot", 0)
    owed = state.get("amount_owed", 0)
    max_to = stack + my_bet

    if state.get("street") == "preflop":
        ranks = tuple(sorted([c[0] for c in cards], reverse=True))
        if ranks in PLAYABLE:
            return _weird_raise(pot, max_to, min_r)
        if state.get("can_check"):
            return {"action": "check"}
        return {"action": "fold"}

    made = _cat(cards, board) >= 1  # any pair or better
    if state.get("can_check"):
        if made and random.random() < 0.6:
            return _weird_raise(pot, max_to, min_r)
        if random.random() < 0.25:
            return _weird_raise(pot, max_to, min_r)  # occasional bluff
        return {"action": "check"}
    if made and owed > 0 and pot / owed >= 2:
        return {"action": "call"}
    if owed > 0 and pot / owed >= 4:
        return {"action": "call"}
    return {"action": "fold"}
