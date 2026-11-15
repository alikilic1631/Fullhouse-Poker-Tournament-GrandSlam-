#!/usr/bin/env python3
"""profiles - behaviour profiles of the real teams, fitted to the real round logs (testbench).

    python3 profiles.py                      # all teams with >= 2000 hands, + pooled "field" and "donor"
    python3 profiles.py --min-hands 3000 --show Kojack "The Market Makers"
    python3 profiles.py --logs out/sim/iter2 --out /tmp/x   # profile simulated logs (calibrate.py does this)

Writes profiles/<slug>.json (slug = team name lowercased, every non-alphanumeric char -> '_'),
profiles/index.json (team -> {slug, hands, rounds_used, rule}) and out/profiles_summary.txt.
An existing "policy" section (written by calibrate.py) is preserved unless --reset-policy.

Data selection per team (teams changed bots during Saturday, so recent data wins):
  R30-R54 if the team has >= 2000 hands there, else R19-R54, else every round (practice included).
Pooled profiles: "field" = every profiled team's selected hands; "donor" = teams whose luck-adjusted
result at our tables is clearly negative (adj bb/100 < -10 and z < -2 over their selected hands).

The spot grammar and the decision classifier are shared with the clones (clone.Tracker), so a spot means
exactly the same thing in the logs, in the profiles and at the table. See DEFINITIONS below (also written
into every profile).
"""
import argparse
import glob
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hh as H  # noqa: E402
import clone as CL  # noqa: E402

HERO = "Durahim 1453"
OUT_DIR = os.path.join(HERE, "out")
PROF_DIR = os.path.join(HERE, "profiles")
M_CELL = 12.0       # pseudo-counts pulling a team cell toward its prior
M_COARSE = 20.0     # pseudo-counts pulling the team's coarse tendency toward the field's
M_FIELD = 5.0       # pseudo-counts pulling a field cell toward the built-in default
MIN_SIZES = 8       # size samples needed to use a cell's own size histogram

DEFINITIONS = {
    "spot_keys": {
        "preflop": "pf|<ctx>|<group>. group = position group of the actor (EP = UTG/UTG+1/UTG+2, MP = MP/HJ, CO, "
                   "BTN, SB, BB) for ctx unopened/limped/vs_open, jammer type tight/wild for vs_jam/vs_jam_inv, "
                   "'all' otherwise.",
        "pf ctx": {
            "unopened": "no voluntary money yet (only blinds): F fold, P limp/complete, R open-raise, J open-jam",
            "limped": "no raise yet, >= 1 limper (BB option included): F, P over-limp (BB: check), R iso-raise, J",
            "vs_open": "exactly one raise, actor has not put voluntary money in (blinds count as not): F, P call, "
                       "R 3-bet, J 3-bet all-in",
            "limper_vs_raise": "actor limped, now faces one raise: F, P, R, J",
            "opener_vs_3bet": "actor made the first raise and now faces exactly one re-raise: F, P, R 4-bet, J",
            "cold_vs_3bet": ">= 2 raises, actor has not acted voluntarily: F, P, R, J",
            "caller_vs_3bet": ">= 2 raises, actor limped/called before but never raised: F, P, R, J",
            "raiser_vs_4bet": "actor raised before and faces another raise (3-bettor vs 4-bet, opener vs 5-bet, "
                              "...): F, P, R, J",
            "vs_jam": "pf|vs_jam|<tight|wild>: facing a jam (current high bet >= 1000 = 50bb, overrides the "
                      "contexts above), actor has no voluntary money in: F, P call. tight/wild = the last jammer's "
                      "preflop jam rate (hands with a jam / hands) at the table is < / >= 5% (logs: over the whole "
                      "round; clone: running estimate (jams + 0.3) / (hands + 20))",
            "vs_jam_inv": "pf|vs_jam_inv|<tight|wild>: facing a jam after having limped/called/raised: F, P",
        },
        "jam": "J = a preflop raise that is all-in or to >= 1000 chips (50bb)",
        "postflop": "<street>|<ctx>|<hu|mw>[|<bucket>]; hu = exactly 2 players not folded at the decision",
        "post ctx (nothing to call)": {
            "agg": "actor was the aggressor of the previous street (flop: last preflop raiser) - c-bet/barrel",
            "donk": "previous-street aggressor still in and yet to act on this street - donk bet",
            "probe": "previous-street aggressor already checked this street",
            "noagg": "no previous-street aggressor (limped pot, street checked through, aggressor folded)",
            "actions": "X check, B bet",
        },
        "post ctx (facing)": {
            "vs_bet": "facing exactly one bet, first action on the street: F, C, R",
            "xr": "facing exactly one bet after having checked this street: F, C, R (R = check-raise)",
            "vs_raise_agg": "<street>|vs_raise_agg: facing a raise after having bet/raised this street",
            "vs_raise_cold": "<street>|vs_raise_cold: facing a bet and >= 1 raise without having bet this street",
        },
        "bucket": "size of the bet being faced = the bettor's bet / pot before the bet (pot includes all "
                  "earlier streets): b1 <= 0.35, b2 <= 0.55, b3 <= 0.8, b4 <= 1.1, b5 > 1.1",
    },
    "cell": "n = decisions, counts = raw action counts, p = smoothed probabilities used by the clone "
            "(p = (counts + 12*prior)/(n + 12); prior = field's p for the same spot, tilted by the team's own "
            "coarse tendency over groups/sizes/hu-mw), sizes = histogram used for raise/bet sizes",
    "sizes": "preflop unopened/limped: raise-to in bb (0.1bb bins); other preflop raises: raise-to / current "
             "high bet ('x', 0.1 bins); postflop: rfrac = (raise_to - high_bet) / (pot + to_call) in 0.05 bins, "
             "'allin' when the bet/raise left the stack at 0; preflop jams are excluded (they are action J)",
    "strength": "preflop: hand percentile in the clone's 169-class order (0 = aces, 1 = worst). postflop: s = "
                "percentile of the made hand among all two-card holdings on the board (ties half, 1 = nuts) plus a "
                "draw bonus on flop/turn (clone.strength)",
    "showdown": "for hands the team showed down: pf|<line> histogram of preflop percentile (deciles d0 best..d9), "
                "<street>|<act> histogram of strength deciles at the street where the act (last action of the "
                "street: bet/raise/call/check) was taken (d9 strongest); weak = s < 0.35",
    "summary": "vpip/pfr per hand excluding BB walks; three_bet = (R+J)/n over vs_open; fold_to_3bet = F/n over "
               "opener_vs_3bet; open_<grp> = (R+J)/n over unopened; cbet_flop = B/n over flop|agg; "
               "fold_vs_<street>_<bucket> = F/n over vs_bet+xr; agg_<street> = (B+R)/all decisions on the street; "
               "wtsd = showdowns / hands that saw the flop; wsd = showdowns won / showdowns; allin_pf / "
               "allin_post = hands with an all-in action on that phase / hands",
}


def slugify(name):
    return re.sub(r"[^a-z0-9]", "_", name.lower())


# =============================================================================== tallies
def new_tally():
    return {"spots": defaultdict(Counter), "sizes": defaultdict(Counter), "stats": Counter(),
            "sd": defaultdict(Counter)}


def merge_tally(dst, src):
    for part in ("spots", "sizes", "sd"):
        for k, c in src[part].items():
            dst[part][k].update(c)
    dst["stats"].update(src["stats"])
    return dst


def tally_to_json(t):
    return {part: ({k: dict(v) for k, v in t[part].items()} if part != "stats" else dict(t[part]))
            for part in ("spots", "sizes", "stats", "sd")}


def tally_from_json(d):
    t = new_tally()
    for part in ("spots", "sizes", "sd"):
        for k, v in (d.get(part) or {}).items():
            t[part][k].update(v)
    t["stats"].update(d.get("stats") or {})
    return t


def _line_class(line):
    toks = line.split("-") if line else []
    if "J" in toks:
        return "jam"
    if "5" in toks or "4" in toks:
        return "4bet+"
    if "3" in toks:
        return "3bet"
    if "R" in toks:
        return "open"
    if "C" in toks:
        return "call"
    if "L" in toks:
        return "limp"
    return "check"


def tally_round(r, seats_team, tallies, showdown=True):
    """Add every decision of the given seats in round r. seats_team: {seat: team_name}; tallies: name -> tally."""
    n = r.n
    jams = [0] * n                       # per-seat preflop jam rate over the round (the jammer type of vs_jam)
    for Hd in r.hands:
        for s in {A.seat for A in Hd.acts if A.st == 0 and A.a == "raise" and (A.allin or A.to >= CL.JAM_TO)}:
            jams[s] += 1
    jam_rate = [j / float(max(1, len(r.hands))) for j in jams]
    for Hd in r.hands:
        trk = CL.Tracker(n, Hd.button)
        trk.jam_rate = jam_rate
        trk.post(Hd.sb, 10)
        trk.post(Hd.bb, 20)
        allin_pf = set()
        allin_post = set()
        pf_raise_info = {}
        for A in Hd.acts:
            if A.st > trk.st:
                trk.board(A.st)
            s = A.seat
            team = seats_team.get(s)
            if team is not None:
                T = tallies[team]
                key = trk.spot(s)
                a = A.a
                if A.st == 0:
                    if a == "raise":
                        lab = "J" if (A.allin or A.to >= CL.JAM_TO) else "R"
                    elif a == "fold":
                        lab = "F"
                    else:
                        lab = "P"
                    T["spots"][key][lab] += 1
                    if lab == "R":
                        ctx = key.split("|")[1]
                        if ctx in ("unopened", "limped"):
                            T["sizes"][key]["%.1f" % (round(A.to / 20.0 * 10) / 10.0)] += 1
                        elif A.hi > 0:
                            T["sizes"][key]["%.1f" % (round(A.to / float(A.hi) * 10) / 10.0)] += 1
                    if lab in ("R", "J") and key.startswith("pf|vs_open"):
                        pf_raise_info[s] = key.split("|")[2]
                else:
                    tc = A.to_call
                    if tc <= 0:
                        lab = "B" if a == "raise" else "X"
                    else:
                        lab = {"fold": "F", "call": "C", "raise": "R"}.get(a, "C")
                    T["spots"][key][lab] += 1
                    if a == "raise":
                        if A.allin:
                            T["sizes"][key]["allin"] += 1
                        else:
                            rf = A.rfrac if A.rfrac is not None else 0.0
                            T["sizes"][key]["%.2f" % (round(rf * 20) / 20.0)] += 1
                if A.allin:
                    (allin_pf if A.st == 0 else allin_post).add(s)
            trk.act(s, A.a, A.amt)
        # per-hand stats
        for s, team in seats_team.items():
            T = tallies[team]
            st = T["stats"]
            st["hands"] += 1
            pf = Hd.pf[s]
            if pf["walk"]:
                st["walks"] += 1
            if pf["vpip"]:
                st["vpip"] += 1
            if pf["pfr"]:
                st["pfr"] += 1
            res = Hd.results[s]
            adj = res - Hd.luck[s]
            st["chips"] += res
            st["luck"] += Hd.luck[s]
            st["adj_sq"] += adj * adj
            if Hd.reach[s] >= 1 and Hd.n_flop >= 2:
                st["saw_flop"] += 1
            if s in Hd.went_sd:
                st["went_sd"] += 1
                if Hd.wins.get(s, 0) > 0:
                    st["won_sd"] += 1
            # how the hand ended for this seat: f<k> folded on street k, w<k> won uncontested on street k,
            # sd showdown; chips per outcome show where a seat wins/loses
            if s in Hd.went_sd:
                oc = "sd"
            elif s in Hd.folded_st:
                oc = "f%d" % Hd.folded_st[s]
            else:
                oc = "w%d" % Hd.last_dec_st
            st["n_" + oc] += 1
            st["res_" + oc] += res
            if s in allin_pf:
                st["allin_pf"] += 1
            if s in allin_post:
                st["allin_post"] += 1
            if showdown and s in Hd.went_sd and s in Hd.hole:
                _tally_showdown(T, Hd, s, pf_raise_info.get(s))


def _tally_showdown(T, Hd, s, grp3):
    hole = Hd.hole[s]
    p = CL.pf_percentile_mid(hole)
    lc = _line_class(Hd.pf[s]["line"])
    c = T["sd"]["pf|" + lc]
    c["n"] += 1
    c["d%d" % min(9, int(p * 10))] += 1
    c["sum"] += p
    if lc == "3bet" and grp3:
        T["sd"]["pf|3bet_fine|" + grp3]["%02d" % min(49, int(p * 50))] += 1
    c1, c2 = CL.CI[hole[0]], CL.CI[hole[1]]
    board = [CL.CI[x] for x in Hd.board]
    last = {}
    for A in Hd.acts:
        if A.seat == s and A.st >= 1:
            if A.a == "raise":
                last[A.st] = "bet" if A.to_call <= 0 else "raise"
            else:
                last[A.st] = A.a
    for st_i, act in last.items():
        nb = 2 + st_i
        if len(board) < nb:
            continue
        x = CL.strength(c1, c2, board[:nb])
        k = "%s|%s" % (CL.STREETS[st_i], act)
        c = T["sd"][k]
        c["n"] += 1
        c["d%d" % min(9, int(x * 10))] += 1
        c["sum"] += x
        if x < 0.35:
            c["weak"] += 1
        c["cat%d" % CL.made_category(c1, c2, board[:nb])] += 1


# =============================================================================== selection
def select_rows(rounds, min_hands=2000, exclude=(HERO,)):
    """team -> (rule, set of round refs used, hands)."""
    per = defaultdict(lambda: defaultdict(int))
    for r in rounds:
        for t in r.players:
            if t in exclude:
                continue
            per[t][(r.practice, r.rnum)] += len(r.hands)
    out = {}
    for t, d in per.items():
        r30 = sum(v for (pr, rn), v in d.items() if not pr and 30 <= rn <= 54)
        r19 = sum(v for (pr, rn), v in d.items() if not pr and 19 <= rn <= 54)
        tot = sum(d.values())
        if tot < min_hands:
            continue
        if r30 >= min_hands:
            rule, keys = "R30-R54", {k for k in d if not k[0] and 30 <= k[1] <= 54}
        elif r19 >= min_hands:
            rule, keys = "R19-R54", {k for k in d if not k[0] and 19 <= k[1] <= 54}
        else:
            rule, keys = "all", set(d)
        out[t] = (rule, keys, sum(d[k] for k in keys))
    return out


def extract(rounds, sel=None, include_hero=False, showdown=True, verbose=False):
    """Tally every selected team's decisions. sel: team -> (rule, keys, hands) or None = every seat, every round."""
    tallies = defaultdict(new_tally)
    t0 = time.time()
    for i, r in enumerate(rounds):
        seats = {}
        for s, t in enumerate(r.players):
            if t == HERO and not include_hero:
                continue
            if sel is not None:
                if t not in sel or (r.practice, r.rnum) not in sel[t][1]:
                    continue
            seats[s] = t
        if seats:
            tally_round(r, seats, tallies, showdown=showdown)
        if verbose and (i + 1) % 10 == 0:
            print("  tallied %d/%d rounds (%.0fs)" % (i + 1, len(rounds), time.time() - t0), flush=True)
    return tallies


# =============================================================================== smoothing / profile building
def _actions(key):
    parts = key.split("|")
    if parts[0] == "pf":
        return ("F", "P", "R", "J")
    if parts[1] in CL.POST_CHECKED:
        return ("X", "B")
    return ("F", "C", "R")


def coarse_key(key):
    parts = key.split("|")
    if parts[0] == "pf":
        return "pf|%s|*" % parts[1] if parts[2] != "all" else key
    if len(parts) == 4:
        return "%s|%s|*|*" % (parts[0], parts[1])
    if len(parts) == 3:
        return "%s|%s|*" % (parts[0], parts[1])
    return key


def _default_p(key):
    acts = _actions(key)
    parts = key.split("|")
    if parts[0] == "pf":
        d = CL._DEF_PF.get(parts[1], CL._DEF_PF["vs_open"])
        return {a: d.get(a, 0.0) for a in acts}
    if acts == ("X", "B"):
        return {"X": 0.6, "B": 0.4}
    return {"F": 0.5, "C": 0.4, "R": 0.1}


def _pdist(counts, acts, prior, m):
    n = sum(counts.get(a, 0) for a in acts)
    return {a: (counts.get(a, 0) + m * prior.get(a, 0.0)) / (n + m) for a in acts}


def _coarse_counts(spots):
    out = defaultdict(Counter)
    for k, c in spots.items():
        ck = coarse_key(k)
        if ck != k:
            out[ck].update(c)
    return out


def _all_keys(field_spots):
    keys = set(field_spots)
    # make sure every grouped preflop context / hu-mw / bucket combination exists
    for ctx in CL.PF_GROUPED:
        for g in CL.GROUPS:
            if not (ctx == "unopened" and g == "BB"):
                keys.add("pf|%s|%s" % (ctx, g))
    for ctx in CL.PF_POOLED:
        keys.add("pf|%s|all" % ctx)
    for ctx in CL.PF_JAM:
        for jt in CL.JAM_TYPES:
            keys.add("pf|%s|%s" % (ctx, jt))
    for st in CL.STREETS[1:]:
        for hm in ("hu", "mw"):
            for ctx in CL.POST_CHECKED:
                keys.add("%s|%s|%s" % (st, ctx, hm))
            for ctx in CL.POST_FACING:
                for b in CL.BUCKETS:
                    keys.add("%s|%s|%s|%s" % (st, ctx, hm, b))
        for ctx in CL.POST_RAISE:
            keys.add("%s|%s" % (st, ctx))
    return sorted(keys)


def field_probs(field):
    """Smoothed p for every key of the pooled field (toward built-in defaults), incl. coarse keys."""
    spots = field["spots"]
    coarse = _coarse_counts(spots)
    out = {}
    for k in _all_keys(spots):
        acts = _actions(k)
        ck = coarse_key(k)
        prior = _default_p(k)
        if ck != k and sum(coarse[ck].values()) > 0:
            prior = _pdist(coarse[ck], acts, prior, M_FIELD)
        out[k] = _pdist(spots.get(k, {}), acts, prior, M_FIELD)
    for ck, c in coarse.items():
        out[ck] = _pdist(c, _actions(ck.replace("*", "x")), _default_p(ck.replace("*", "x")), M_FIELD)
    return out


def _sizes_for(key, t_sizes, t_csizes, f_sizes, f_csizes):
    own = t_sizes.get(key)
    if own and sum(own.values()) >= MIN_SIZES:
        return dict(own), "team"
    ck = coarse_key(key)
    tc = t_csizes.get(ck)
    if tc and sum(tc.values()) >= MIN_SIZES:
        return dict(tc), "team_coarse"
    fo = f_sizes.get(key)
    if fo and sum(fo.values()) >= MIN_SIZES:
        return dict(fo), "field"
    fc = f_csizes.get(ck)
    if fc and sum(fc.values()) > 0:
        return dict(fc), "field_coarse"
    return {}, "none"


def _coarse_sizes(sizes):
    out = defaultdict(Counter)
    for k, c in sizes.items():
        ck = coarse_key(k)
        out[ck].update(c)
    return out


def _r(x, d=4):
    return round(x, d) if isinstance(x, float) else x


def key_stats(t):
    """Headline stats (value, denominator) from a raw tally (used for target vs achieved)."""
    sp = t["spots"]
    st = t["stats"]
    out = {}

    def ratio(num, den):
        return (num / den if den else None, den)

    def agg(prefix_fn, acts_num):
        num = den = 0
        for k, c in sp.items():
            if prefix_fn(k):
                den += sum(c.values())
                num += sum(c.get(a, 0) for a in acts_num)
        return ratio(num, den)

    hands = st.get("hands", 0) - st.get("walks", 0)
    out["vpip"] = ratio(st.get("vpip", 0), hands)
    out["pfr"] = ratio(st.get("pfr", 0), hands)
    out["three_bet"] = agg(lambda k: k.startswith("pf|vs_open|"), ("R", "J"))
    out["call_open"] = agg(lambda k: k.startswith("pf|vs_open|"), ("P",))
    out["fold_to_3bet"] = agg(lambda k: k == "pf|opener_vs_3bet|all", ("F",))
    out["four_bet"] = agg(lambda k: k == "pf|opener_vs_3bet|all", ("R", "J"))
    out["call_jam"] = agg(lambda k: k.startswith("pf|vs_jam"), ("P",))
    out["limp"] = agg(lambda k: k.startswith("pf|unopened|"), ("P",))
    for g in CL.GROUPS[:-1]:
        out["open_" + g] = agg(lambda k, g=g: k == "pf|unopened|" + g, ("R", "J"))
    out["iso_raise"] = agg(lambda k: k.startswith("pf|limped|"), ("R", "J"))
    out["cbet_flop"] = agg(lambda k: k.startswith("flop|agg|"), ("B",))
    out["cbet_turn"] = agg(lambda k: k.startswith("turn|agg|"), ("B",))
    out["donk_flop"] = agg(lambda k: k.startswith("flop|donk|"), ("B",))
    out["stab_flop"] = agg(lambda k: k.startswith("flop|probe|") or k.startswith("flop|noagg|"), ("B",))
    for s in CL.STREETS[1:]:
        for b in CL.BUCKETS:
            out["fold_vs_%s_%s" % (s, b)] = agg(
                lambda k, s=s, b=b: k.startswith(s + "|") and k.split("|")[1] in CL.POST_FACING and k.endswith("|" + b),
                ("F",))
        out["raise_vs_bet_" + s] = agg(lambda k, s=s: k.startswith(s + "|vs_bet|"), ("R",))
        out["xr_" + s] = agg(lambda k, s=s: k.startswith(s + "|xr|"), ("R",))
        out["fold_vs_raise_" + s] = agg(lambda k, s=s: k.startswith(s + "|vs_raise"), ("F",))
        out["agg_" + s] = agg(lambda k, s=s: k.startswith(s + "|"), ("B", "R"))
    out["wtsd"] = ratio(st.get("went_sd", 0), st.get("saw_flop", 0))
    out["wsd"] = ratio(st.get("won_sd", 0), st.get("went_sd", 0))
    out["allin_pf"] = ratio(st.get("allin_pf", 0), st.get("hands", 0))
    out["allin_post"] = ratio(st.get("allin_post", 0), st.get("hands", 0))
    return out


OUTCOMES = ("f0", "w0", "f1", "w1", "f2", "w2", "f3", "w3", "sd")
OUTCOME_NAMES = {"f0": "folded preflop", "w0": "won preflop uncontested", "f1": "folded flop",
                 "w1": "won flop uncontested", "f2": "folded turn", "w2": "won turn uncontested",
                 "f3": "folded river", "w3": "won river uncontested", "sd": "showdown"}


def outcome_breakdown(st):
    """bb/100 contributed by each way a hand ended for the seat (sums to the seat's bb/100)."""
    n = st.get("hands", 0)
    if not n:
        return {}
    return {oc: {"share": round(st.get("n_" + oc, 0) / float(n), 4),
                 "bb100": round(st.get("res_" + oc, 0) / 20.0 / n * 100.0, 2)} for oc in OUTCOMES}


def _results(st):
    n = st.get("hands", 0)
    if not n:
        return {}
    chips = st.get("chips", 0)
    luck = st.get("luck", 0.0)
    adj = chips - luck
    mean = adj / n
    var = max(0.0, st.get("adj_sq", 0.0) / n - mean * mean)
    se = math.sqrt(var / n) / 20.0 * 100.0
    return {"hands": n, "chips": chips, "bb100": round(chips / 20.0 / n * 100.0, 2),
            "adj_bb100": round(adj / 20.0 / n * 100.0, 2), "se_bb100": round(se, 2),
            "z": round((adj / 20.0 / n * 100.0) / se, 2) if se > 0 else 0.0,
            "by_outcome": outcome_breakdown(st)}


def _sd_summary(sd):
    out = {}
    for k, c in sorted(sd.items()):
        if "|3bet_fine|" in k:
            continue
        n = c.get("n", 0)
        if not n:
            continue
        e = {"n": n, "mean": round(c.get("sum", 0.0) / n, 3),
             "deciles": [c.get("d%d" % i, 0) for i in range(10)]}
        if not k.startswith("pf|"):
            e["weak_share"] = round(c.get("weak", 0) / n, 3)
            e["made_cat"] = {str(i): c.get("cat%d" % i, 0) for i in range(9) if c.get("cat%d" % i, 0)}
        out[k] = e
    return out


def _bluff(t, f_tally, cells):
    """Bluff shares: preflop 3-bets from shown 3-bet hands outside the team's 3-bet range; postflop from the
    share of weak (s < 0.35) hands among shown bets/raises, shrunk toward the field's share."""
    sd = t["sd"]
    fsd = f_tally["sd"] if f_tally is not None else sd
    out_pf = {}
    num = den = 0.0
    for g in CL.GROUPS:
        fine = sd.get("pf|3bet_fine|" + g)
        cell = cells.get("pf|vs_open|" + g)
        if not fine or not cell:
            continue
        # a shown 3-bet is a bluff when the hand is outside the whole continue range (3-bet + call): the
        # clone takes its 3-bet bluffs from just below its calling range
        x = cell["p"].get("R", 0.0) + cell["p"].get("J", 0.0) + cell["p"].get("P", 0.0)
        for b, v in fine.items():
            den += v
            if (int(b) + 0.5) / 50.0 > x:
                num += v
    out_pf["vs_open"] = round(min(0.5, (num + 0.15 * 6) / (den + 6)), 3)
    out_post = {}
    for st in CL.STREETS[1:]:
        for a, k2 in (("bet", "bet"), ("raise", "raise")):
            c = sd.get("%s|%s" % (st, k2), {})
            fc = fsd.get("%s|%s" % (st, k2), {})
            fprior = (fc.get("weak", 0) + 0.15 * 5) / (fc.get("n", 0) + 5)
            share = (c.get("weak", 0) + fprior * 10) / (c.get("n", 0) + 10)
            out_post["%s|%s" % (st, a)] = round(min(0.5, share), 3)
    return {"preflop": out_pf, "postflop": out_post,
            "note": "bluff share = part of the bet/raise frequency taken from the bottom of the strength range "
                    "(postflop) or from just below the calling range (preflop 3-bets); estimated from showdowns, "
                    "so biased low (bluffs that get folds are never shown)"}


def build_profile(name, kind, t, field_t, fprobs, data_info, old_policy=None):
    sp = t["spots"]
    coarse = _coarse_counts(sp)
    fsp = field_t["spots"]
    fcoarse = _coarse_counts(fsp)
    t_csizes = _coarse_sizes(t["sizes"])
    f_csizes = _coarse_sizes(field_t["sizes"])
    cells = {}
    is_field = t is field_t
    for k in _all_keys(fsp):
        acts = _actions(k)
        cnt = sp.get(k, Counter())
        n = sum(cnt.get(a, 0) for a in acts)
        fp = fprobs.get(k) or _default_p(k)
        if is_field:
            p = fp
        else:
            ck = coarse_key(k)
            prior = dict(fp)
            if ck != k:
                fcp = fprobs.get(ck) or fp
                tcn = sum(coarse[ck].get(a, 0) for a in acts)
                tilt = {}
                for a in acts:
                    tcp = (coarse[ck].get(a, 0) + M_COARSE * fcp.get(a, 0.0)) / (tcn + M_COARSE)
                    tilt[a] = tcp / fcp[a] if fcp.get(a, 0.0) > 1e-9 else 1.0
                z = sum(prior[a] * tilt[a] for a in acts)
                if z > 0:
                    prior = {a: prior[a] * tilt[a] / z for a in acts}
            p = _pdist(cnt, acts, prior, M_CELL)
        sizes, src = _sizes_for(k, t["sizes"], t_csizes, field_t["sizes"], f_csizes)
        cell = {"n": n, "counts": {a: cnt.get(a, 0) for a in acts if cnt.get(a, 0)},
                "p": {a: _r(p[a]) for a in acts}}
        if any(a in acts for a in ("R", "B")):
            cell["sizes"] = sizes
            cell["sizes_from"] = src
            cell["n_sizes"] = sum(t["sizes"].get(k, {}).values())
        cells[k] = cell
    for ck, c in coarse.items():          # coarse cells (fallbacks + readability)
        acts = _actions(ck.replace("*", "x"))
        n = sum(c.get(a, 0) for a in acts)
        fp = fprobs.get(ck) or _default_p(ck.replace("*", "x"))
        p = fp if is_field else _pdist(c, acts, fp, M_CELL)
        cells[ck] = {"n": n, "counts": {a: c.get(a, 0) for a in acts if c.get(a, 0)},
                     "p": {a: _r(p[a]) for a in acts}}
    stats = key_stats(t)
    prof = {
        "format": "testbench-clone-profile/1",
        "team": name,
        "slug": slugify(name),
        "kind": kind,
        "data": data_info,
        "results": _results(t["stats"]),
        "summary": {k: {"value": _r(v[0]) if v[0] is not None else None, "n": v[1]} for k, v in stats.items()},
        "spots": cells,
        "bluff": _bluff(t, field_t, cells),
        "showdown": _sd_summary(t["sd"]),
        "definitions": DEFINITIONS,
    }
    if old_policy:
        prof["policy"] = old_policy
    return prof


def build_all(rounds, min_hands=2000, out_dir=PROF_DIR, reset_policy=False, verbose=True, write=True):
    sel = select_rows(rounds, min_hands=min_hands)
    t0 = time.time()
    tallies = extract(rounds, sel, verbose=verbose)
    if verbose:
        print("extracted %d teams in %.1fs" % (len(tallies), time.time() - t0))
    field = new_tally()
    for t in tallies.values():
        merge_tally(field, t)
    fprobs = field_probs(field)
    res = {t: _results(tallies[t]["stats"]) for t in tallies}
    donors = sorted(t for t, r in res.items() if r.get("adj_bb100", 0) < -10 and r.get("z", 0) < -2)
    donor = new_tally()
    for t in donors:
        merge_tally(donor, tallies[t])
    profiles = {}

    def old_pol(slug):
        if reset_policy:
            return None
        path = os.path.join(out_dir, slug + ".json")
        if os.path.exists(path):
            try:
                return json.load(open(path)).get("policy")
            except Exception:
                return None
        return None

    for t in sorted(tallies):
        rule, keys, hands = sel[t]
        info = {"rule": rule, "rounds": sorted(("P%d" % k[1]) if k[0] else ("R%d" % k[1]) for k in keys),
                "rounds_used": len(keys), "hands": hands}
        profiles[t] = build_profile(t, "team", tallies[t], field, fprobs, info, old_pol(slugify(t)))
    finfo = {"rule": "pooled: every profiled team's selected hands", "members": sorted(tallies),
             "rounds_used": len({k for t in sel for k in sel[t][1]}), "hands": field["stats"]["hands"]}
    profiles["field"] = build_profile("field", "pool", field, field, fprobs, finfo, old_pol("field"))
    dinfo = {"rule": "pooled: teams with adj bb/100 < -10 and z < -2 over their selected hands",
             "members": donors, "rounds_used": len({k for t in donors for k in sel[t][1]}),
             "hands": donor["stats"]["hands"]}
    profiles["donor"] = build_profile("donor", "pool", donor, field, fprobs, dinfo, old_pol("donor"))
    if write:
        os.makedirs(out_dir, exist_ok=True)
        index = {}
        for name, prof in profiles.items():
            with open(os.path.join(out_dir, prof["slug"] + ".json"), "w") as fh:
                json.dump(prof, fh, indent=1, sort_keys=False)
            index[name] = {"slug": prof["slug"], "hands": prof["data"]["hands"],
                           "rounds_used": prof["data"]["rounds_used"], "rule": prof["data"]["rule"],
                           "kind": prof["kind"]}
        with open(os.path.join(out_dir, "index.json"), "w") as fh:
            json.dump(index, fh, indent=1)
    return profiles, tallies, field, donors


def summary_table(profiles):
    cols = ["vpip", "pfr", "three_bet", "fold_to_3bet", "limp", "cbet_flop", "fold_vs_flop_b3", "agg_flop",
            "wtsd", "wsd", "allin_pf"]
    lines = ["%-26s %-8s %6s %6s %8s %8s | %s" % ("team", "rule", "hands", "rds", "adjbb100", "z",
                                                 " ".join("%7s" % c[:7] for c in cols))]
    for name in sorted(profiles, key=lambda t: (profiles[t]["kind"] != "team", t.lower())):
        p = profiles[name]
        r = p.get("results", {})
        vals = []
        for c in cols:
            v = p["summary"].get(c, {}).get("value")
            vals.append("%7s" % ("-" if v is None else "%.1f" % (100 * v)))
        lines.append("%-26s %-8s %6d %6d %+8.1f %+8.1f | %s" % (
            name[:26], p["data"]["rule"][:8], p["data"]["hands"], p["data"]["rounds_used"],
            r.get("adj_bb100", 0.0), r.get("z", 0.0), " ".join(vals)))
    return "\n".join(lines)


def load_rounds_from(paths):
    out = []
    for p in paths:
        out.append(H.load_round(p, with_luck=True))
    out.sort(key=lambda r: (0 if r.practice else 1, r.rnum))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", nargs="*", help="log files or folders (default: the real logs via hh.load_all)")
    ap.add_argument("--out", default=PROF_DIR, help="profile folder (default: profiles/)")
    ap.add_argument("--min-hands", type=int, default=2000)
    ap.add_argument("--reset-policy", action="store_true", help="drop calibrated policy sections")
    ap.add_argument("--show", nargs="*", default=[], help="print the full spot table of these teams")
    a = ap.parse_args()
    t0 = time.time()
    if a.logs:
        paths = []
        for x in a.logs:
            paths += sorted(glob.glob(os.path.join(x, "*.json"))) if os.path.isdir(x) else [x]
        rounds = load_rounds_from(paths)
    else:
        rounds = H.load_all()
    print("loaded %d rounds (%.1fs)" % (len(rounds), time.time() - t0))
    profiles, tallies, field, donors = build_all(rounds, a.min_hands, a.out, a.reset_policy)
    txt = summary_table(profiles)
    print(txt)
    print("\ndonor pool: %s" % ", ".join(donors))
    os.makedirs(OUT_DIR, exist_ok=True)
    if not a.logs:
        with open(os.path.join(OUT_DIR, "profiles_summary.txt"), "w") as fh:
            fh.write(txt + "\n\ndonor pool: %s\n" % ", ".join(donors))
    for name in a.show:
        p = profiles.get(name)
        if not p:
            print("no profile for", name)
            continue
        print("\n=== %s (%s, %d hands)" % (name, p["data"]["rule"], p["data"]["hands"]))
        for k, c in sorted(p["spots"].items()):
            if "*" in k:
                continue
            print("  %-28s n=%5d  %s  %s" % (k, c["n"], " ".join("%s=%.2f" % (x, y) for x, y in c["p"].items()),
                                             " ".join("%s:%d" % kv for kv in sorted(c.get("sizes", {}).items(),
                                                                                   key=lambda kv: -kv[1])[:4])))
    print("\nwrote %d profiles to %s (%.1fs)" % (len(profiles), a.out, time.time() - t0))


if __name__ == "__main__":
    main()
