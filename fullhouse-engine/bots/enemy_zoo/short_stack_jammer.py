"""Enemy zoo (held-out): short_stack_jammer — limps preflop with everything, jams the river."""

BOT_NAME = "ShortStackJammer"


def decide(state):
    if state.get("type") == "warmup":
        return {"action": "check"}

    street = state.get("street")
    owed = state.get("amount_owed", 0)
    pot = state.get("pot", 0)

    if street == "preflop":
        # Limp with everything; just call the blind, fold to big raises.
        if state.get("can_check"):
            return {"action": "check"}
        if owed <= 100:
            return {"action": "call"}
        return {"action": "fold"}

    if street in ("flop", "turn"):
        if state.get("can_check"):
            return {"action": "check"}
        if owed > 0 and pot / owed >= 3:
            return {"action": "call"}
        return {"action": "fold"}

    # River: jam.
    return {"action": "all_in"}
