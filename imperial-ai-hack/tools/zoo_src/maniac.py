"""Raises about 80% of hands preflop to 4-6bb, re-raises with almost half of them, pots it on every street and raises bets at random."""
ARCHETYPE = "maniac"
TIER = "fish"
LEAK = "Its bets and raises carry almost no information: 3-bet/4-bet for value much wider, call down with any decent pair, check strong hands to it and let it barrel; never bluff it."
#@KERNEL core


class Agent(Base):
    SALT = 404

    def pre(self, st):
        p = self.pct
        bb = st["big_blind"]
        r = st["raises_this_street"]
        rnd = self.rng.random
        cur = max(st["bets"])
        if r == 0:
            if p <= 0.80:
                return raise_to(st, (4 + int(rnd() * 3) + limpers(st)) * bb)
            return check_call(st)
        if r == 1:
            if p <= 0.45:
                return raise_to(st, 3.5 * cur)
            return CALL if p <= 0.85 else FOLD
        if p <= 0.20 or rnd() < 0.12:
            return raise_to(st, JAM)
        return CALL if p <= 0.50 else FOLD

    def post(self, st):
        tier, outs = self.tier(st)
        tc = st["to_call"]
        rnd = self.rng.random
        if tc == 0:
            if rnd() < 0.85:
                return bet_frac(st, 0.8 + 0.4 * rnd())
            return CHECK
        rs = st["raises_this_street"]
        x = rnd()
        if tier >= 4:
            return raise_to(st, JAM) if rs >= 2 else bet_frac(st, 1.0)
        if x < 0.33 and rs <= 2:
            return bet_frac(st, 1.0)
        if tier >= 1 or outs >= 4 or x < 0.75:
            return CALL
        return FOLD
