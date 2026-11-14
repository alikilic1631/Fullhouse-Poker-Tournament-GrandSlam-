"""Enemy zoo (tuning): always_call — calls every bet, never folds, never raises."""

BOT_NAME = "AlwaysCall"


def decide(state):
    if state.get("type") == "warmup":
        return {"action": "check"}
    if state.get("can_check"):
        return {"action": "check"}
    return {"action": "call"}
