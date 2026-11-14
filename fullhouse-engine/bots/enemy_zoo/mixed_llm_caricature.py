"""Enemy zoo (held-out): mixed_llm_caricature — generic GPT-style bot.

Standard architecture the brief warns most competitors will build:
33%/66%/pot sizing, c-bet ~70%, pot-odds calling, linear value betting,
position-aware-ish, 169-hand preflop chart feel.
"""
import random
import eval7

BOT_NAME = "MixedLLMCaricature"
RANK_ORDER = "23456789TJQKA"

# Roughly "top 25%" GTO-flavoured opening chart.
OPEN_RANGE = {
    ('A', 'A'), ('K', 'K'), ('Q', 'Q'), ('J', 'J'), ('T', 'T'), ('9', '9'), ('8', '8'), ('7', '7'),
    ('A', 'K'), ('A', 'Q'), ('A', 'J'), ('A', 'T'), ('A', '9'), ('A', '8'), ('A', '5'),
    ('K', 'Q'), ('K', 'J'), ('K', 'T'), ('Q', 'J'), ('Q', 'T'), ('J', 'T'), ('T', '9'), ('9', '8'),
}
THREEBET_RANGE = {('A', 'A'), ('K', 'K'), ('Q', 'Q'), ('A', 'K'), ('A', 'Q')}
BIG_BLIND = 100


def _cat(hole, board):
    cats = ['High Card', 'Pair', 'Two Pair', 'Trips', 'Straight',
            'Flush', 'Full House', 'Quads', 'Straight Flush']
    ht = eval7.handtype(eval7.evaluate([eval7.Card(c) for c in hole + board]))
    try:
        return cats.index(ht)
    except ValueError:
        return 0


def _top_pair_plus(hole, board):
    if len(board) < 3:
        return False
    c = _cat(hole, board)
    if c >= 2:
        return True
    if c == 1:
        branks = [x[0] for x in board]
        top = max(branks, key=lambda r: RANK_ORDER.index(r))
        hranks = [x[0] for x in hole]
        if hranks[0] == hranks[1] and RANK_ORDER.index(hranks[0]) > RANK_ORDER.index(top):
            return True
        if top in hranks:
            return True
    return False


def decide(state):
    if state.get("type") == "warmup":
        return {"action": "check"}

    cards = state.get("your_cards", []) or []
    board = state.get("community_cards", []) or []
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
            if ranks in THREEBET_RANGE:
                return {"action": "raise", "amount": min(int(current_bet * 3), max_to)}
            if ranks in OPEN_RANGE and owed > 0 and pot / owed >= 2:
                return {"action": "call"}
            if state.get("can_check"):
                return {"action": "check"}
            return {"action": "fold"}
        if ranks in OPEN_RANGE:
            # Standard 2.5x open.
            return {"action": "raise", "amount": min(int(min_r * 2.5), max_to)}
        if state.get("can_check"):
            return {"action": "check"}
        return {"action": "fold"}

    # Postflop: linear value betting + 70% c-bet, standard sizes.
    strong = _top_pair_plus(cards, board)
    if state.get("can_check"):
        if strong:
            return {"action": "raise", "amount": min(int(pot * 0.66), max_to)}
        if random.random() < 0.70:
            return {"action": "raise", "amount": min(int(pot * 0.33), max_to)}
        return {"action": "check"}

    # Facing a bet: pot-odds call, raise strong hands.
    if strong and random.random() < 0.5:
        return {"action": "raise", "amount": min(int(pot * 1.0), max_to)}
    if owed > 0 and pot / owed >= 2.0:
        return {"action": "call"}
    return {"action": "fold"}
