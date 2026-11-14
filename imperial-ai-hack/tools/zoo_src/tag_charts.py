"""Textbook rule-based TAG: opening chart by position (9% under the gun to 32% on the button), 3-bets JJ+/AK, c-bets when it connects or heads-up, then plays fit-or-fold."""
ARCHETYPE = "rule-based TAG (position charts)"
TIER = "medium"
LEAK = "Static and honest: folds to 3-bets without a premium, gives up the turn without top pair, never bluff-catches a raise. Float or raise its c-bets, 3-bet its late opens, fold to its turn and river bets."
#@KERNEL core


class Agent(Base):
    SALT = 202
    OPEN = {7: 0.09, 6: 0.11, 5: 0.13, 4: 0.16, 3: 0.22, 2: 0.32, 1: 0.25}

    def pre(self, st):
        p = self.pct
        bb = st["big_blind"]
        r = st["raises_this_street"]
        pos, behind = self.spot(st)
        tc = st["to_call"]
        if r == 0:
            limp = limpers(st)
            if pos == 2:
                return raise_to(st, (4 + limp) * bb) if p <= 0.06 else CHECK
            f = self.OPEN.get(behind, 0.09) * (0.8 if limp else 1.0)
            if p <= f:
                return raise_to(st, (3 + limp) * bb)
            return FOLD
        if r == 1:
            if p <= 0.03:
                return raise_to(st, 3 * max(st["bets"]))
            lim = 0.16 if pos == 2 else 0.10 if pos == 0 else 0.07
            if p <= lim and tc <= 3.5 * bb:
                return CALL
            return FOLD
        if p <= 0.012:
            return raise_to(st, JAM)
        if p <= 0.03 and tc <= 25 * bb:
            return CALL
        return FOLD

    def post(self, st):
        tier, outs = self.tier(st)
        tc = st["to_call"]
        street = st["street"]
        nopp = st["folded"].count(False) - 1
        if tc == 0:
            if street == "flop" and last_raiser(st, "preflop") == st["seat"]:
                if tier >= 2 or outs >= 8 or (nopp == 1 and self.rng.random() < 0.5):
                    return bet_frac(st, 0.66)
                return CHECK
            if tier >= 3:
                return bet_frac(st, 0.66)
            return CHECK
        f = tc / max(1, st["pot"] - tc)
        rs = st["raises_this_street"]
        if tier >= 5:
            return bet_frac(st, 1.0)
        if tier == 4:
            return CALL
        if tier == 3:
            if rs >= 2 and street != "flop":
                return FOLD
            return CALL if f <= 1.0 else FOLD
        if tier == 2 and street == "flop" and f <= 0.6 and rs == 1:
            return CALL
        if outs >= 8 and street != "river" and f <= 0.55:
            return CALL
        return FOLD
