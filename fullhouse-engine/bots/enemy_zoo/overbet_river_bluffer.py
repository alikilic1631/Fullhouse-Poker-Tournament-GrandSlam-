"""Enemy zoo (tuning): overbet_river_bluffer — passive flop/turn, overbets river ~30% as a bluff."""
import random
import eval7

BOT_NAME = "OverbetRiverBluffer"


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

    street = state.get("street")
    cards = state.get("your_cards", []) or []
    board = state.get("community_cards", []) or []
    pot = state.get("pot", 0)
    stack = state.get("your_stack", 0)
    my_bet = state.get("your_bet_this_street", 0)
    owed = state.get("amount_owed", 0)

    if street == "preflop":
        # Loose-ish limper.
        if state.get("can_check"):
            return {"action": "check"}
        if owed <= 100:
            return {"action": "call"}
        return {"action": "fold"}

    if street in ("flop", "turn"):
        if state.get("can_check"):
            return {"action": "check"}
        return {"action": "call"}

    # River
    strong = _cat(cards, board) >= 2  # two pair or better
    if state.get("can_check"):
        if strong:
            return {"action": "raise", "amount": min(pot, stack + my_bet)}
        if random.random() < 0.30:
            # Overbet bluff ~1.5x pot.
            return {"action": "raise", "amount": min(int(pot * 1.5), stack + my_bet)}
        return {"action": "check"}
    if strong:
        return {"action": "call"}
    if owed > 0 and pot / owed >= 4:
        return {"action": "call"}
    return {"action": "fold"}
