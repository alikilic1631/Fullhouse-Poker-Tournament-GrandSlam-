"""Plays about 8% of hands (77+, AJs+, AQo+, KQs), raises them 3bb, bets top pair or better and gives up to any real pressure."""
ARCHETYPE = "nit"
TIER = "medium"
LEAK = "Folds 92% of hands and most flops: steal its blinds every time, c-bet small, and fold at once when it raises or keeps betting (it has it)."
#@KERNEL core


class Agent(Base):
    SALT = 101

    def pre(self, st):
        p = self.pct
        bb = st["big_blind"]
        r = st["raises_this_street"]
        if r == 0:
            if p <= 0.08:
                return raise_to(st, (3 + limpers(st)) * bb)
            return check_fold(st)
        if r == 1:
            if p <= 0.026:
                return raise_to(st, 3 * max(st["bets"]))
            if p <= 0.06 and st["to_call"] <= 4 * bb:
                return CALL
            return check_fold(st)
        if p <= 0.008:
            return raise_to(st, JAM)
        return check_fold(st)

    def post(self, st):
        tier, _ = self.tier(st)
        tc = st["to_call"]
        if tc == 0:
            if tier >= 3:
                return bet_frac(st, 0.6)
            return CHECK
        if tier >= 5:
            return bet_frac(st, 0.8)
        if tier == 4:
            return CALL
        if tier == 3 and st["raises_this_street"] == 1 and tc <= 0.7 * (st["pot"] - tc) \
                and st["street"] != "river":
            return CALL
        return FOLD
