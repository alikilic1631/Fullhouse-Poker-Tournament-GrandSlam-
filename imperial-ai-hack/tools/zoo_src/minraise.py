"""Min-raise spammer: min-raises preflop with 60% of hands (and re-min-raises), min-bets every time it is checked to, min-raises bets with any pair or draw, otherwise calls small bets."""
ARCHETYPE = "min-raise spammer"
TIER = "fish"
LEAK = "Bloats pots at a tiny price with weak ranges and then calls too much: re-raise big for value over its min-raises, call its min-bets with any equity, and value bet large; its raise sizes say nothing about strength."
#@KERNEL core


class Agent(Base):
    SALT = 1010

    def pre(self, st):
        p = self.pct
        tc = st["to_call"]
        bb = st["big_blind"]
        r = st["raises_this_street"]
        if p <= 0.60 and r <= 3 and tc <= 12 * bb:
            return raise_to(st, 0)
        if tc == 0:
            return CHECK
        if p <= 0.60 and tc <= 12 * bb:
            return CALL
        if p <= 0.05:
            return CALL
        return FOLD

    def post(self, st):
        tier, outs = self.tier(st)
        tc = st["to_call"]
        if tc == 0:
            return raise_to(st, 0)
        f = tc / max(1, st["pot"] - tc)
        rs = st["raises_this_street"]
        if tier >= 1 or outs >= 8:
            if rs <= 2 and (tier >= 2 or f <= 0.8):
                return raise_to(st, 0)
            if tier >= 3 or f <= 1.0:
                return CALL
            return FOLD
        return CALL if f <= 0.5 else FOLD
