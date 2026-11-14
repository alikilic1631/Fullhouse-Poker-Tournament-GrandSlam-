"""Enemy zoo (tuning): min_raise_spammer — always min-raises preflop, calls postflop."""

BOT_NAME = "MinRaiseSpammer"


def decide(state):
    if state.get("type") == "warmup":
        return {"action": "check"}

    stack = state.get("your_stack", 0)
    my_bet = state.get("your_bet_this_street", 0)
    min_r = state.get("min_raise_to", 100)

    if state.get("street") == "preflop":
        max_to = stack + my_bet
        if min_r >= max_to:
            return {"action": "all_in"}
        return {"action": "raise", "amount": min_r}

    # Postflop: passive caller.
    if state.get("can_check"):
        return {"action": "check"}
    return {"action": "call"}
