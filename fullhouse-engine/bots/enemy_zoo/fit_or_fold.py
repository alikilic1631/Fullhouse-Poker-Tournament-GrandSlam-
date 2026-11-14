"""Enemy zoo (tuning): fit_or_fold — checks/folds postflop unless top pair or better."""
import eval7

BOT_NAME = "FitOrFold"
RANK_ORDER = "23456789TJQKA"

PLAYABLE = {  # decent preflop range
    ('A', 'A'), ('K', 'K'), ('Q', 'Q'), ('J', 'J'), ('T', 'T'), ('9', '9'),
    ('8', '8'), ('7', '7'), ('6', '6'), ('5', '5'), ('4', '4'), ('3', '3'), ('2', '2'),
    ('A', 'K'), ('A', 'Q'), ('A', 'J'), ('A', 'T'), ('K', 'Q'), ('K', 'J'), ('Q', 'J'), ('J', 'T'),
}
PREMIUM = {('A', 'A'), ('K', 'K'), ('Q', 'Q'), ('A', 'K')}


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
    pot = state.get("pot", 0)
    owed = state.get("amount_owed", 0)
    max_to = stack + my_bet

    if state.get("street") == "preflop":
        ranks = tuple(sorted([c[0] for c in cards], reverse=True))
        if ranks in PREMIUM:
            return {"action": "raise", "amount": min(min_r * 3, max_to)}
        if ranks in PLAYABLE and owed <= pot * 0.4:
            return {"action": "call"}
        if state.get("can_check"):
            return {"action": "check"}
        return {"action": "fold"}

    # Postflop: fit (top pair+) or fold.
    if _top_pair_plus(cards, board):
        if state.get("can_check"):
            return {"action": "raise", "amount": min(int(pot * 0.66), max_to)}
        return {"action": "call"}
    if state.get("can_check"):
        return {"action": "check"}
    return {"action": "fold"}
