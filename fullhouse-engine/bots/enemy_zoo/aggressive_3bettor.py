"""Enemy zoo (tuning): aggressive_3bettor — 3-bets preflop ~25%, c-bets aggressively."""
import random

BOT_NAME = "Aggressive3Bettor"
BIG_BLIND = 100

OPEN_RANGE = {  # ~ top 35% of hands, by class
    ('A', 'A'), ('K', 'K'), ('Q', 'Q'), ('J', 'J'), ('T', 'T'), ('9', '9'),
    ('8', '8'), ('7', '7'), ('6', '6'), ('5', '5'),
    ('A', 'K'), ('A', 'Q'), ('A', 'J'), ('A', 'T'), ('A', '9'),
    ('K', 'Q'), ('K', 'J'), ('K', 'T'), ('Q', 'J'), ('Q', 'T'), ('J', 'T'),
}


def decide(state):
    if state.get("type") == "warmup":
        return {"action": "check"}

    cards = state.get("your_cards", []) or []
    stack = state.get("your_stack", 0)
    my_bet = state.get("your_bet_this_street", 0)
    min_r = state.get("min_raise_to", 100)
    current_bet = state.get("current_bet", 0)
    pot = state.get("pot", 0)
    owed = state.get("amount_owed", 0)
    max_to = stack + my_bet

    if state.get("street") == "preflop":
        ranks = tuple(sorted([c[0] for c in cards], reverse=True))
        facing_raise = current_bet > BIG_BLIND
        if facing_raise:
            # 3-bet ~25% of the time (more often with a real hand).
            p3 = 0.55 if ranks in OPEN_RANGE else 0.15
            if random.random() < p3:
                return {"action": "raise", "amount": min(int(current_bet * 3), max_to)}
            if ranks in OPEN_RANGE and owed <= pot:
                return {"action": "call"}
            if state.get("can_check"):
                return {"action": "check"}
            return {"action": "fold"}
        # First in: open ~ open range.
        if ranks in OPEN_RANGE:
            return {"action": "raise", "amount": min(int(min_r * 2.5), max_to)}
        if state.get("can_check"):
            return {"action": "check"}
        return {"action": "fold"}

    # Postflop: aggressive c-bet.
    if state.get("can_check"):
        if random.random() < 0.65:
            return {"action": "raise", "amount": min(int(pot * 0.66), max_to)}
        return {"action": "check"}
    if owed > 0 and pot / owed >= 2.5:
        return {"action": "call"}
    return {"action": "fold"}
