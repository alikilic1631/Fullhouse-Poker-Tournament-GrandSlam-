"""Slow-player: limps or flat-calls its premiums, checks and calls two pair or better on the flop, check-raises the turn and jams the river; with one pair it bets a third of the pot as a blocker."""
ARCHETYPE = "slow-playing trapper"
TIER = "medium"
LEAK = "Its small bets are weak one-pair hands (raise them), its checks hide monsters: do not barrel into a player who check-called the flop, and fold to its turn check-raise. Take the free cards it gives."
#@KERNEL core


class Agent(Base):
    SALT = 1212

    def pre(self, st):
        p = self.pct
        bb = st["big_blind"]
        r = st["raises_this_street"]
        tc = st["to_call"]
        if p <= 0.03:
            me = st["seat"]
            acted = any(h["seat"] == me and h["action"] in ("call", "raise") for h in st["history"])
            if r >= 2 or (r == 1 and acted):
                return raise_to(st, JAM)          # limp-reraise, or shove over a 3-bet
            return check_call(st)                 # trap: limp or flat-call the premium
        if r == 0:
            _, behind = self.spot(st)
            if p <= (0.30 if behind <= 2 else 0.16):
                return raise_to(st, (2.5 + limpers(st)) * bb)
            return check_fold(st)
        if r == 1 and p <= 0.14 and tc <= 4 * bb:
            return CALL
        return check_fold(st)

    def post(self, st):
        tier, outs = self.tier(st)
        tc = st["to_call"]
        street = st["street"]
        if tier >= 4:
            if tc == 0:
                if street == "river":
                    return bet_frac(st, 1.0)
                return CHECK
            if street == "flop":
                return CALL
            if street == "turn":
                return bet_frac(st, 1.0)
            return raise_to(st, JAM)
        if tc == 0:
            if tier >= 2:
                return bet_frac(st, 0.33)
            return CHECK
        f = tc / max(1, st["pot"] - tc)
        if tier >= 2:
            return CALL if f <= 0.6 else FOLD
        if (tier == 1 or outs >= 8) and street != "river" and f <= 0.4:
            return CALL
        return FOLD
