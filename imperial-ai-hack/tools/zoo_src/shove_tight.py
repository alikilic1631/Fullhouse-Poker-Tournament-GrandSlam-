"""Push-or-fold bot: moves all in preflop with the top 12% of hands (44+, A5s+, ATo+, KTs+, QJs), folds everything else, and only continues after the flop with top pair or better (by shoving)."""
ARCHETYPE = "preflop shove-bot (top 12%)"
TIER = "medium"
LEAK = "Call its jams with exactly the hands that beat a 12% range (about 88+, AJs+, AKo) and fold the rest; its blinds are free to steal 88% of the time."
#@KERNEL core


class Agent(Base):
    SALT = 505
    RANGE = 0.12

    def pre(self, st):
        if self.pct <= self.RANGE:
            return raise_to(st, JAM)
        return check_fold(st)

    def post(self, st):
        tier, _ = self.tier(st)
        if tier >= 3:
            return raise_to(st, JAM)
        return check_fold(st)
