"""Calls any bet of any size on any street with any two cards, never folds; bets a third of the pot with two pair or better and min-raises only with a straight or better."""
ARCHETYPE = "calling station (calls anything)"
TIER = "fish"
LEAK = "Never folds: zero bluffs, value bet three streets as big as possible with top pair or better (it even calls all-ins), isolate it preflop with big raises; believe its rare raise."
#@KERNEL core


class Agent(Base):
    SALT = 707

    def pre(self, st):
        return check_call(st)

    def post(self, st):
        tier, _ = self.tier(st)
        if st["to_call"] == 0:
            return bet_frac(st, 0.33) if tier >= 4 else CHECK
        if tier >= 6 and st["raises_this_street"] == 1:
            return raise_to(st, 0)
        return CALL
