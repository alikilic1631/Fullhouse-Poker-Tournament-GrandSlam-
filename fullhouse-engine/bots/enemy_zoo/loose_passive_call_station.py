"""Enemy zoo (held-out): loose_passive_call_station — VPIP ~80%, never raises postflop."""
import random

BOT_NAME = "LoosePassiveCallStation"

# Worst ~20% of hands it will fold preflop to a raise (offsuit disconnected low).
FOLD_PREFLOP = {
    ('7', '2'), ('8', '2'), ('9', '2'), ('7', '3'), ('8', '3'), ('9', '3'),
    ('6', '2'), ('5', '2'), ('4', '2'), ('3', '2'), ('6', '3'), ('5', '3'),
    ('4', '3'), ('7', '4'), ('8', '4'), ('9', '4'), ('6', '4'), ('5', '4'),
}


def decide(state):
    if state.get("type") == "warmup":
        return {"action": "check"}

    cards = state.get("your_cards", []) or []
    owed = state.get("amount_owed", 0)
    pot = state.get("pot", 0)

    if state.get("street") == "preflop":
        if state.get("can_check"):
            return {"action": "check"}
        ranks = tuple(sorted([c[0] for c in cards], reverse=True))
        suited = len(cards) == 2 and cards[0][1] == cards[1][1]
        # VPIP ~80%: fold only the trashiest offsuit hands to a raise.
        if (not suited) and ranks in FOLD_PREFLOP and owed > 200:
            return {"action": "fold"}
        return {"action": "call"}

    # Postflop: pure call station — never raises.
    if state.get("can_check"):
        return {"action": "check"}
    # Calls almost anything; folds only to enormous bets sometimes.
    if owed > pot * 1.5 and random.random() < 0.4:
        return {"action": "fold"}
    return {"action": "call"}
