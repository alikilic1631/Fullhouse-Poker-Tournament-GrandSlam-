"""Limps 65% of hands from every seat, calls raises up to 4bb with the better 40%, never raises without aces or kings; after the flop it checks, calls up to three-quarter pot with any pair or draw and folds air."""
ARCHETYPE = "limp-caller (loose passive)"
TIER = "fish"
LEAK = "Limps then calls: isolate with 4-5bb raises in position, c-bet (it folds air on the flop), then value bet pairs relentlessly; when it bets it has two pair or better."
#@KERNEL core


class Agent(Base):
    SALT = 909

    def pre(self, st):
        p = self.pct
        tc = st["to_call"]
        bb = st["big_blind"]
        r = st["raises_this_street"]
        if p <= 0.01 and r <= 2:
            return raise_to(st, 0)
        if tc == 0:
            return CHECK
        if r == 0:
            return CALL if p <= 0.65 else FOLD
        if tc <= 4 * bb:
            return CALL if p <= 0.40 else FOLD
        if tc <= 12 * bb:
            return CALL if p <= 0.12 else FOLD
        return CALL if p <= 0.03 else FOLD

    def post(self, st):
        tier, outs = self.tier(st)
        tc = st["to_call"]
        if tc == 0:
            return bet_frac(st, 0.5) if tier >= 4 else CHECK
        f = tc / max(1, st["pot"] - tc)
        if tier >= 4:
            return CALL
        if tier >= 3:
            return CALL if f <= 1.2 else FOLD
        if (tier >= 1 or (outs >= 4 and st["street"] != "river")) and f <= 0.75:
            return CALL
        return FOLD
