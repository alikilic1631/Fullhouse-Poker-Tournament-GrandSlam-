"""
Capture real game_state fixtures for use in tests / fuzzer seeding.

Drives PokerEngine directly (in-process), plays scripted hands across several
seeds and player counts, and saves a sample of distinct action_request states
(one per street, plus a short-stack and an all-in spot) to
sandbox/fixtures/game_states.json. The injected match_action_log mirrors what
match.py exposes to a live bot.

Usage:
    python3 sandbox/capture_fixtures.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.game import PokerEngine

OUT_DIR = Path(__file__).parent / "fixtures"
MATCH_LOG_MAX = 200


def _inject(state, match_log):
    if state.get("type") == "action_request":
        state = dict(state)
        state["match_action_log"] = match_log[-MATCH_LOG_MAX:]
    return state


def _scripted_action(state):
    """A simple driver that produces varied, legal states to sample from."""
    seat = state["seat_to_act"]
    # Mix it up so we reach flop/turn/river and create some raises.
    if state["street"] == "preflop" and seat % 3 == 0 and state["amount_owed"] <= 100:
        return {"action": "raise", "amount": state["min_raise_to"] * 2}
    if state["can_check"]:
        return {"action": "check"}
    pot, owed = state["pot"], state["amount_owed"]
    if owed > 0 and pot / owed >= 3:
        return {"action": "call"}
    return {"action": "call"} if owed <= 300 else {"action": "fold"}


def capture():
    samples = {}  # keyed by a label so we collect distinct kinds of spots
    for seed in range(0, 40):
        n = 6 if seed % 2 == 0 else 3
        bot_ids = [f"bot_{i}" for i in range(n)]
        eng = PokerEngine(f"fix_{seed}", bot_ids, dealer_seat=seed % n, seed=seed)
        match_log = []
        state = _inject(eng.start_hand(), match_log)
        steps = 0
        while state.get("type") == "action_request" and steps < 200:
            street = state["street"]
            label = f"{street}_{'check' if state['can_check'] else 'facing_bet'}"
            if label not in samples:
                samples[label] = state
            # short-stack spot
            if state["your_stack"] < 1500 and "short_stack" not in samples:
                samples["short_stack"] = state
            action = _scripted_action(state)
            seat = state["seat_to_act"]
            match_log.append({
                "hand_num": seed, "seat": seat, "bot_id": bot_ids[seat],
                "action": action.get("action"), "amount": action.get("amount"),
            })
            state = _inject(eng.apply_action(seat, action), match_log)
            steps += 1
        if len(samples) >= 10:
            break

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "game_states.json"
    fixtures = list(samples.values())
    out_path.write_text(json.dumps(fixtures, indent=2))
    print(f"Captured {len(fixtures)} fixture states -> {out_path}")
    for f in fixtures:
        print(f"  - {f['street']:8s} can_check={f['can_check']!s:5s} "
              f"owed={f['amount_owed']:5d} pot={f['pot']:6d} stack={f['your_stack']:6d}")


if __name__ == "__main__":
    capture()
