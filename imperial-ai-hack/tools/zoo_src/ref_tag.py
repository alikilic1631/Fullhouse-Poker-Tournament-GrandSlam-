"""Strong reference 1, a solid adaptive TAG: position opening ranges (10% early to 44% on the button), value-heavy 3-bets, calls shoves by the shover's measured frequency, steals more from tight blinds; after the flop it sizes by board texture and by how sticky the opponents are, and reads hands by action (folds one pair to raises and triple barrels from passive players, calls down wild ones)."""
ARCHETYPE = "strong reference: solid TAG with action-based hand reading"
TIER = "strong"
LEAK = "No easy money: it needs ~30 hands to adapt, its small c-bet on dry boards is often air (raise it occasionally), it over-folds one pair to turn/river raises from players it has tagged as passive, and it rarely bluffs rivers - fold bluff-catchers to its river bets. Stay near baseline against it."
#@KERNEL core tracker


class Agent(Base):
    SALT = 1717
    OPEN = {7: 0.10, 6: 0.12, 5: 0.15, 4: 0.19, 3: 0.27, 2: 0.44, 1: 0.36}

    def __init__(self):
        Base.__init__(self)
        self.tr = Tracker(10)

    def on_hand_end(self, summary):
        self.tr.update(summary)

    # ------------------------------------------------------------ preflop
    def pre(self, st):
        p = self.pct
        bb = st["big_blind"]
        tc = st["to_call"]
        bets = st["bets"]
        cur = max(bets)
        r = st["raises_this_street"]
        pos, behind = self.spot(st)
        tr = self.tr
        me = st["seat"]
        n = len(bets)
        premium = p <= 0.012 or (self.c1 >> 2) + (self.c2 >> 2) == 23      # QQ+ or AK
        if r == 0:
            limp = limpers(st)
            if pos == 2:
                return raise_to(st, (4 + limp) * bb) if p <= 0.10 else CHECK
            f = self.OPEN.get(behind, 0.10)
            left = [(me + k) % n for k in range(1, behind + 1)]
            if limp:
                f *= 0.85 if limp == 1 else 0.7
            elif behind <= 2 and max(tr.vpip_f(s) for s in left) < 0.20:
                f *= 1.4                                   # only tight players left: steal wider
            jb = max(tr.jam_f(s) for s in left)
            if jb > 0.20:                                  # a shove-bot behind: no raise-folding
                f = min(f, 0.5 * jb + 0.05)
            if p <= f:
                return raise_to(st, (2.5 + limp) * bb)
            return FOLD
        v = last_raiser(st, "preflop")
        if st["stacks"][v] == 0 or cur >= 1500:
            pj = tr.jam_f(v)
            lim = max(0.027, 0.45 * pj)
            if r >= 2 and pj < 0.08:
                lim = 0.012                                # a normal player's 4-bet jam: QQ+/AK only
            for i in range(n):
                if i != v and i != me and not st["folded"][i] and bets[i] >= cur:
                    lim *= 0.6                             # somebody already called the shove
            return CALL if (p <= lim or premium) else FOLD
        pv = tr.pfr_f(v)
        ip = (pos - 1) % n > ((v - st["button"]) - 1) % n
        if r == 1:
            callers = 0
            for i in range(n):
                if i != v and bets[i] >= cur:
                    callers += 1
            if premium or p <= max(0.028, 0.20 * pv):
                return raise_to(st, cur * (3.0 if ip else 3.6) + callers * cur)
            if ip and pv > 0.22 and 0.10 < p <= 0.17 and self.rng.random() < 0.25:
                return raise_to(st, cur * 3.0)
            if pos == 2:
                cf = 0.26 if cur <= 3 * bb else 0.16
            elif pos == 1:
                cf = 0.08
            else:
                cf = 0.13 if ip else 0.09
            x = (pv / 0.15) ** 0.5
            cf *= 0.75 if x < 0.75 else 1.8 if x > 1.8 else x
            if cur > 3.5 * bb:
                cf *= 3.5 * bb / cur
            return CALL if p <= cf else FOLD
        loose = pv > 0.30
        if premium or (loose and p <= 0.05):
            if cur >= 25 * bb or r >= 3:
                return raise_to(st, JAM)
            return raise_to(st, 2.3 * cur)
        if bets[me] > bb and tc <= 18 * bb and p <= (0.12 if loose else 0.055):
            return CALL
        return FOLD

    # ----------------------------------------------------------- postflop
    def post(self, st):
        me = st["seat"]
        board = [_CI[c] for c in st["board"]]
        tier, outs = classify(self.c1, self.c2, board)
        tc = st["to_call"]
        pot = st["pot"]
        street = st["street"]
        folded = st["folded"]
        n = len(folded)
        opps = [i for i in range(n) if not folded[i] and i != me]
        no = len(opps)
        pfa = agg_seat = -1
        prev_opp_aggr = my_prev_aggr = 0
        for h in st["history"]:
            if h["action"] == "raise":
                hs = h["street"]
                if hs == "preflop":
                    pfa = h["seat"]
                elif hs == street:
                    agg_seat = h["seat"]
                elif h["seat"] == me:
                    my_prev_aggr += 1
                else:
                    prev_opp_aggr += 1
        rs = st["raises_this_street"]
        wet = wetness(board)
        tr = self.tr
        rnd = self.rng.random
        btn = st["button"]
        myo = (me - btn - 1) % n
        ip = True
        for i in opps:
            if (i - btn - 1) % n > myo:
                ip = False
        river = street == "river"
        flop = street == "flop"

        if tc == 0:
            ff = min(tr.fold_f(i) for i in opps)           # the stickiest opponent decides
            if tier >= 4:
                if ff < 0.30:
                    return bet_frac(st, 1.0)
                return bet_frac(st, 0.75 if wet > 0.4 or ff < 0.38 else 0.6)
            if tier == 3:
                if river:
                    if no == 1 and (prev_opp_aggr == 0 or ff < 0.30):
                        return bet_frac(st, 0.75 if ff < 0.30 else 0.5)
                    return CHECK
                if no <= 2 or flop:
                    return bet_frac(st, 0.7 if wet > 0.4 or ff < 0.30 else 0.55)
                return CHECK
            if tier == 2:
                if flop and no <= 2:
                    return bet_frac(st, 0.5)
                if no == 1 and prev_opp_aggr == 0 and (ff < 0.35 or (ip and not river)):
                    return bet_frac(st, 0.45)
                return CHECK
            if outs >= 8 and not river and no <= 2 and ff > 0.30:
                return bet_frac(st, 0.6)
            if ff > 0.33:
                if flop and pfa == me:
                    pr = (0.7 if wet < 0.3 else 0.45) if no == 1 else 0.3 if no == 2 else 0.0
                    if rnd() < pr:
                        return bet_frac(st, 0.4 if wet < 0.3 else 0.55)
                elif flop and ip and no == 1 and ff > 0.5 and rnd() < 0.4:
                    return bet_frac(st, 0.5)
                elif street == "turn" and no == 1 and my_prev_aggr and ff > 0.5 and rnd() < 0.35:
                    return bet_frac(st, 0.66)
                elif river and no == 1 and my_prev_aggr >= 2 and tier == 0 and ff > 0.55 and rnd() < 0.3:
                    return bet_frac(st, 0.7)
            return CHECK

        v = agg_seat if agg_seat >= 0 and agg_seat != me else opps[0]
        f = tc / max(1, pot - tc)
        po = tc / (pot + tc)
        va = tr.agg_f(v)
        wild = va > 0.48
        passive = va < 0.22
        stack = st["stacks"][me]
        allin = tc >= stack
        multi = no >= 2
        can_raise = "raise" in st["legal_actions"]
        if tier >= 5:
            if can_raise and (tier >= 6 or rs <= 2 or wild):
                if stack <= 2.5 * pot or rs >= 2:
                    return raise_to(st, JAM)
                return bet_frac(st, 0.85)
            return CALL
        if tier == 4:
            if rs >= 3 and not wild:
                return FOLD if passive and f > 0.4 else CALL
            if rs == 2 and river and passive and f > 0.5:
                return FOLD
            if rs == 1 and not river and can_raise and (wet > 0.3 or wild):
                return bet_frac(st, 0.8)
            return CALL
        if tier == 3:
            if rs >= 2:
                return CALL if wild and f <= 1.2 else FOLD
            if multi and not flop and f > 0.6 and not wild:
                return FOLD
            if river and not wild and (f > 0.9 or (passive and f > 0.5) or (prev_opp_aggr >= 2 and f > 0.6)):
                return FOLD
            return CALL
        if tier == 2:
            lim = 0.8 if flop else 0.6 if street == "turn" else 0.45
            if wild:
                lim = 1.3
            elif passive:
                lim *= 0.6
            if multi:
                lim *= 0.7
            if (rs == 1 or wild) and f <= lim:
                return CALL
        elif tier == 1:
            if rs == 1 and ((flop and f <= 0.5 and not multi and not passive) or (wild and f <= 0.8)):
                return CALL
        if outs and not river:
            eq = outs * (0.040 if flop and allin else 0.022)
            if not allin:
                eq *= 1.3                                  # implied odds
            if eq >= po:
                if outs >= 12 and rs == 1 and can_raise and not multi and rnd() < 0.3:
                    return bet_frac(st, 0.8)
                return CALL
        return FOLD
