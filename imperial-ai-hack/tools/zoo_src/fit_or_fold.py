"""Sees cheap flops with 45% of hands (raises only the top 5%), then continues only with top pair or better or a strong draw: bets three-quarter pot, calls anything, raises sets; otherwise check-folds."""
ARCHETYPE = "top-pair-or-better fit-or-fold"
TIER = "medium"
LEAK = "Misses two flops in three and gives up: c-bet every flop small and take it; when it calls or bets it has top pair or better, so stop bluffing and only continue with hands that beat top pair."
#@KERNEL core


class Agent(Base):
    SALT = 1414

    def pre(self, st):
        p = self.pct
        bb = st["big_blind"]
        r = st["raises_this_street"]
        tc = st["to_call"]
        if p <= 0.05 and r <= 1:
            return raise_to(st, 3.5 * max(st["bets"]) if r else (3.5 + limpers(st)) * bb)
        if p <= 0.012:
            return raise_to(st, JAM)
        if tc == 0:
            return CHECK
        if p <= 0.45 and tc <= 4 * bb:
            return CALL
        if p <= 0.06 and tc <= 20 * bb:
            return CALL
        return FOLD

    def post(self, st):
        tier, outs = self.tier(st)
        tc = st["to_call"]
        if tier >= 3:
            if tc == 0:
                return bet_frac(st, 0.75)
            if tier >= 5 and st["raises_this_street"] <= 2:
                return bet_frac(st, 1.0)
            return CALL
        if tc == 0:
            return CHECK
        f = tc / max(1, st["pot"] - tc)
        if outs >= 8 and st["street"] != "river" and f <= 0.5:
            return CALL
        return FOLD
