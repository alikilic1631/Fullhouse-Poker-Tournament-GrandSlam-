"""Over-bluffing barreler: opens 30%, then fires 75% pot on the flop, 80% on the turn and pot on the river almost regardless of its cards whenever it is checked to; folds to raises without top pair."""
ARCHETYPE = "over-bluffing barreler"
TIER = "medium"
LEAK = "Three barrels with air far too often: check to it and call down with any reasonable pair, or raise the turn (it folds everything below top pair). Do not lead into it, let it bet."
#@KERNEL core


class Agent(Base):
    SALT = 1313

    def pre(self, st):
        p = self.pct
        bb = st["big_blind"]
        r = st["raises_this_street"]
        tc = st["to_call"]
        if r == 0:
            if p <= 0.30:
                return raise_to(st, (3 + limpers(st)) * bb)
            return check_fold(st)
        if r == 1:
            if p <= 0.04:
                return raise_to(st, 3 * max(st["bets"]))
            if p <= 0.18 and tc <= 5 * bb:
                return CALL
            return check_fold(st)
        if p <= 0.015:
            return raise_to(st, JAM)
        return CALL if p <= 0.05 and tc <= 25 * bb else check_fold(st)

    def post(self, st):
        tier, outs = self.tier(st)
        tc = st["to_call"]
        street = st["street"]
        rnd = self.rng.random
        if tc == 0:
            if street == "flop":
                return bet_frac(st, 0.75) if rnd() < 0.90 else CHECK
            if street == "turn":
                return bet_frac(st, 0.80) if rnd() < 0.80 else CHECK
            return bet_frac(st, 1.0) if (tier >= 3 or rnd() < 0.70) else CHECK
        f = tc / max(1, st["pot"] - tc)
        if tier >= 5:
            return bet_frac(st, 1.0)
        if tier >= 3:
            return CALL if (tier >= 4 or f <= 1.2) else FOLD
        if outs >= 8 and street != "river" and f <= 0.8:
            return CALL
        if tier == 2 and st["raises_this_street"] == 1 and f <= 0.5:
            return CALL
        return FOLD
