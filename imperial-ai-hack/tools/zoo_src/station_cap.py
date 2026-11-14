"""Calls unless the bet is huge: sees every flop for up to 15bb, calls bets up to pot size with any pair, draw or ace high, and folds to overbets and preflop all-ins without a strong hand."""
ARCHETYPE = "calling station (folds only to huge bets)"
TIER = "fish"
LEAK = "Pays off every bet up to pot size with weak pairs and ace high: value bet thin at 75-100% pot on all three streets, never bluff below an overbet; its bets (two pair+) are honest."
#@KERNEL core


class Agent(Base):
    SALT = 808

    def pre(self, st):
        p = self.pct
        tc = st["to_call"]
        bb = st["big_blind"]
        if tc == 0:
            return raise_to(st, 4 * bb) if p <= 0.03 else CHECK
        if tc <= 15 * bb:
            return CALL
        if p <= 0.10 or (p <= 0.20 and tc <= 40 * bb):
            return CALL
        return FOLD

    def post(self, st):
        tier, outs = self.tier(st)
        tc = st["to_call"]
        if tc == 0:
            return bet_frac(st, 0.5) if tier >= 4 else CHECK
        f = tc / max(1, st["pot"] - tc)
        if tier >= 3:
            return CALL
        ace = (self.c1 >> 2) == 12 or (self.c2 >> 2) == 12
        if f <= 1.05 and (tier >= 1 or outs >= 4 or ace or st["street"] == "flop"):
            return CALL
        return FOLD
