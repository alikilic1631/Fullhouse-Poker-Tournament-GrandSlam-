"""
v0 baseline — "cannot die".

Goals (in priority order):
  1. Never crash, never time out, never return an illegal action.
  2. Play a coherent, tight-ish strategy that beats the loosest reference bots.

This is the floor every later version is measured against. Keep it simple.
"""
import os
import time

BOT_NAME = "OurBot v0"

DATA_DIR = os.environ.get("BOT_DATA_DIR",
                          os.path.join(os.path.dirname(__file__), "data"))

# === Module globals (persist across hands within a match) ===
HAND_COUNT = 0
LAST_LOG_INDEX = 0
OPPONENT_STATS = {}

# === Constants ===
PREMIUM_PAIRS = {('A', 'A'), ('K', 'K'), ('Q', 'Q'), ('J', 'J')}
STRONG_ACES = {('A', 'K'), ('A', 'Q')}


# === Helpers ===
def parse_state(state):
    cards = state.get('your_cards', []) or []
    ranks = tuple(sorted([c[0] for c in cards], reverse=True))
    suited = len(cards) == 2 and cards[0][1] == cards[1][1]
    return {
        'ranks': ranks,
        'suited': suited,
        'street': state.get('street', 'preflop'),
        'pot': state.get('pot', 0),
        'owed': state.get('amount_owed', 0),
        'stack': state.get('your_stack', 0),
        'can_check': state.get('can_check', False),
        'min_raise_to': state.get('min_raise_to', 100),
        'my_bet': state.get('your_bet_this_street', 0),
    }


def emergency_fallback(state):
    if state.get('can_check'):
        return {"action": "check"}
    return {"action": "fold"}


def map_to_legal_action(intended, state):
    """Ensure intended action is legal; coerce or fall back to a safe action."""
    a = intended.get('action')
    if a == 'check' and not state.get('can_check'):
        return {"action": "fold"}
    if a == 'raise':
        try:
            amt = int(intended.get('amount', 0))
        except (TypeError, ValueError):
            return emergency_fallback(state)
        min_r = state.get('min_raise_to', 0)
        max_r = state.get('your_stack', 0) + state.get('your_bet_this_street', 0)
        # If we can't even make a min raise, just call/check.
        if min_r > max_r:
            return {"action": "call"} if not state.get('can_check') else {"action": "check"}
        if amt >= max_r:
            return {"action": "all_in"}
        amt = max(amt, min_r)
        return {"action": "raise", "amount": amt}
    if a in ('fold', 'call', 'all_in'):
        return {"action": a}
    return emergency_fallback(state)


# === Main ===
def decide(state):
    if state.get('type') == 'warmup':
        return {"action": "check"}

    try:
        p = parse_state(state)

        # Preflop logic
        if p['street'] == 'preflop':
            if p['ranks'] in PREMIUM_PAIRS:
                return map_to_legal_action(
                    {"action": "raise", "amount": p['min_raise_to'] * 3}, state)
            if p['ranks'] in STRONG_ACES:
                # AKs gets value too; treat suited like the offsuit version here.
                if p['owed'] <= 100:  # first in / facing only the blind
                    return map_to_legal_action(
                        {"action": "raise", "amount": int(p['min_raise_to'] * 2.5)}, state)
                if p['owed'] <= p['pot'] * 0.5:
                    return {"action": "call"}
                return {"action": "fold"}
            if p['can_check']:
                return {"action": "check"}
            return {"action": "fold"}

        # Postflop logic: free check, else pot-odds call at 3:1 or better.
        if p['can_check']:
            return {"action": "check"}
        if p['owed'] > 0 and p['pot'] / p['owed'] >= 3:
            return {"action": "call"}
        return {"action": "fold"}

    except Exception:
        return emergency_fallback(state)
