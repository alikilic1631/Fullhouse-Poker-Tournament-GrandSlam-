"""Enemy zoo (held-out): polarized_bettor — bets pot with strong hands or pure bluffs, checks medium."""
import random
import eval7

BOT_NAME = "PolarizedBettor"
RANK_ORDER = "23456789TJQKA"

PLAYABLE = {
    ('A', 'A'), ('K', 'K'), ('Q', 'Q'), ('J', 'J'), ('T', 'T'), ('9', '9'), ('8', '8'),
    ('A', 'K'), ('A', 'Q'), ('A', 'J'), ('A', 'T'), ('K', 'Q'), ('K', 'J'), ('Q', 'J'), ('J', 'T'),
}


def _cat(hole, board):
    cats = ['High Card', 'Pair', 'Two Pair', 'Trips', 'Straight',
            'Flush', 'Full House', 'Quads', 'Straight Flush']
    ht = eval7.handtype(eval7.evaluate([eval7.Card(c) for c in hole + board]))
    try:
        return cats.index(ht)
    except ValueError:
        return 0


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
            return {"action": "raise", "amount": min(int(min_r * 2.5), max_to)}
        if state.get("can_check"):
            return {"action": "check"}
        return {"action": "fold"}

    c = _cat(cards, board)
    strong = c >= 2          # two pair or better
    medium = c == 1          # one pair
    pot_bet = min(pot, max_to)

    if state.get("can_check"):
        if strong:
            return {"action": "raise", "amount": pot_bet}
        if not medium and random.random() < 0.45:
            # Pure bluff with air.
            return {"action": "raise", "amount": pot_bet}
        return {"action": "check"}

    # Facing a bet: call with strong, fold the rest (polarized = no medium bluff-catch).
    if strong:
        return {"action": "call"}
    if medium and owed > 0 and pot / owed >= 4:
        return {"action": "call"}
    return {"action": "fold"}
