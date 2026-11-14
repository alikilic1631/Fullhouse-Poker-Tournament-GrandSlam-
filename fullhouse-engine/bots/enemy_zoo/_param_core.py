"""Shared ParametricOpponent core (Patch 19a). Imported by the thin
param_*.py bot files. NOT a bot itself (no module-level decide)."""
import random
import eval7

RANK_VAL = {r: i for i, r in enumerate("23456789TJQKA")}
_SIZING = {"standard": 0.66, "small": 0.4, "large": 0.9, "overbet": 1.3,
           "min_raise": 0.0, "tiny_block": 0.25}

# 169 hand classes ordered best->worst by a simple strength heuristic.
def _build_order():
    hands = []
    for a in range(13):
        for b in range(13):
            if a == b:
                hands.append("23456789TJQKA"[a] * 2)
            elif a > b:
                hands.append("23456789TJQKA"[a] + "23456789TJQKA"[b] + "s")
                hands.append("23456789TJQKA"[a] + "23456789TJQKA"[b] + "o")

    def score(c):
        if len(c) == 2:
            return 140 + RANK_VAL[c[0]] * 10
        hi, lo = RANK_VAL[c[0]], RANK_VAL[c[1]]
        s = hi * 5 + lo * 3 + (8 if c[2] == "s" else 0)
        g = hi - lo
        s += 6 if g == 1 else (3 if g == 2 else 0)
        if lo >= RANK_VAL["T"]:
            s += 6
        if c[0] == "A":
            s += 4
        return s
    return sorted(hands, key=score, reverse=True)

HAND_ORDER = _build_order()
RANK_PCT = {h: i / len(HAND_ORDER) for i, h in enumerate(HAND_ORDER)}


def _hand_class(cards):
    r0, r1 = cards[0][0], cards[1][0]
    if r0 == r1:
        return r0 + r1
    if RANK_VAL[r0] < RANK_VAL[r1]:
        r0, r1 = r1, r0
    return r0 + r1 + ("s" if cards[0][1] == cards[1][1] else "o")


def _cat(hole, board):
    cats = ['High Card', 'Pair', 'Two Pair', 'Trips', 'Straight',
            'Flush', 'Full House', 'Quads', 'Straight Flush']
    ht = str(eval7.handtype(eval7.evaluate([eval7.Card(c) for c in hole + board])))
    return cats.index(ht) if ht in cats else 0


class ParametricOpponent:
    def __init__(self, **p):
        self.p = {
            "vpip": 0.25, "pfr": 0.18, "threebet_freq": 0.06, "fold_to_3bet": 0.6,
            "cbet_freq": 0.6, "fold_to_cbet": 0.55, "aggression_factor": 2.0,
            "sizing_profile": "standard", "river_bluff_freq": 0.1, "trap_freq": 0.0,
            "donk_freq": 0.0, "short_stack_jam_freq": 0.0,
        }
        self.p.update(p)

    def _bet(self, pot, max_to, min_r):
        frac = _SIZING.get(self.p["sizing_profile"], 0.66)
        amt = min_r if frac == 0.0 else max(int(frac * pot), min_r)
        return {"action": "raise", "amount": min(amt, max_to)}

    def decide(self, state):
        if state.get("type") == "warmup":
            return {"action": "check"}
        try:
            cards = state.get("your_cards", []) or []
            board = state.get("community_cards", []) or []
            street = state.get("street")
            pot = state.get("pot", 0)
            owed = state.get("amount_owed", 0)
            stack = state.get("your_stack", 0)
            my_bet = state.get("your_bet_this_street", 0)
            min_r = state.get("min_raise_to", 100)
            can_check = state.get("can_check", False)
            max_to = stack + my_bet
            P = self.p

            if len(cards) == 2 and stack <= 1500 and P["short_stack_jam_freq"] > 0:
                pct = RANK_PCT.get(_hand_class(cards), 1.0)
                if pct <= P["short_stack_jam_freq"]:
                    return {"action": "all_in"}

            if street == "preflop":
                pct = RANK_PCT.get(_hand_class(cards), 1.0)
                facing = state.get("current_bet", 100) > 100
                if facing:
                    if pct <= P["threebet_freq"]:
                        return {"action": "raise", "amount": min(int(state["current_bet"] * 3), max_to)}
                    if pct <= P["vpip"] and owed <= pot:
                        return {"action": "call"}
                    return {"action": "check"} if can_check else {"action": "fold"}
                if pct <= P["pfr"]:
                    return {"action": "raise", "amount": min(int(min_r * 2.4), max_to)}
                if pct <= P["vpip"] and can_check:
                    return {"action": "check"}
                if pct <= P["vpip"] and owed <= 100:
                    return {"action": "call"}
                return {"action": "check"} if can_check else {"action": "fold"}

            # Postflop
            c = _cat(cards, board)
            strong = c >= 2
            medium = c == 1
            if can_check:
                if strong and P["trap_freq"] > 0 and random.random() < P["trap_freq"]:
                    return {"action": "check"}                     # trap
                if strong:
                    return self._bet(pot, max_to, min_r)
                if random.random() < P["cbet_freq"] * (0.6 if not medium else 0.8):
                    return self._bet(pot, max_to, min_r)
                if street == "river" and not medium and random.random() < P["river_bluff_freq"]:
                    return self._bet(pot, max_to, min_r)
                return {"action": "check"}
            # facing a bet
            if strong:
                if random.random() < min(0.5, P["aggression_factor"] / 8.0):
                    return self._bet(pot, max_to, min_r)
                return {"action": "call"}
            if medium:
                return {"action": "call"} if random.random() > P["fold_to_cbet"] else {"action": "fold"}
            # weak
            if random.random() > P["fold_to_cbet"] and owed > 0 and pot / owed >= 2:
                return {"action": "call"}
            return {"action": "fold"}
        except Exception:
            return {"action": "check"} if state.get("can_check") else {"action": "fold"}


GRID = {
    "param_nit_overfolder": dict(vpip=0.12, pfr=0.10, threebet_freq=0.03, fold_to_cbet=0.80,
                                 aggression_factor=0.6, sizing_profile="standard"),
    "param_tag_reg": dict(vpip=0.22, pfr=0.18, threebet_freq=0.08, cbet_freq=0.70,
                          fold_to_cbet=0.55, aggression_factor=2.5, sizing_profile="standard"),
    "param_lag_maniac": dict(vpip=0.65, pfr=0.45, threebet_freq=0.18, cbet_freq=0.85,
                             fold_to_cbet=0.25, aggression_factor=4.0, sizing_profile="overbet",
                             river_bluff_freq=0.30),
    "param_loose_passive_station": dict(vpip=0.60, pfr=0.05, cbet_freq=0.20, fold_to_cbet=0.15,
                                        aggression_factor=0.3, sizing_profile="small"),
    "param_modal_llm_chartbot": dict(vpip=0.25, pfr=0.20, threebet_freq=0.07, cbet_freq=0.70,
                                     fold_to_cbet=0.55, aggression_factor=2.0, sizing_profile="standard"),
    "param_pot_odds_overfolder": dict(vpip=0.18, pfr=0.12, fold_to_cbet=0.70,
                                      aggression_factor=0.8, sizing_profile="standard"),
    "param_weird_sizing_polar": dict(vpip=0.22, pfr=0.18, cbet_freq=0.6, fold_to_cbet=0.55,
                                     aggression_factor=2.8, sizing_profile="overbet", river_bluff_freq=0.30),
    "param_multiway_limper_station": dict(vpip=0.55, pfr=0.08, cbet_freq=0.25, fold_to_cbet=0.30,
                                          aggression_factor=0.6, sizing_profile="small"),
}
