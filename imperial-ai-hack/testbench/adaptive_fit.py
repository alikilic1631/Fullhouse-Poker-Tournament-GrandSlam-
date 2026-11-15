#!/usr/bin/env python3
"""adaptive_fit - fit the ADAPTIVE clone parameters on the real logs (writes adaptive/params.json).

    python3 adaptive_measure.py --extract     # once (7 s): real logs -> out/adaptive_real_records.json
    python3 adaptive_fit.py                   # fit -> adaptive/params.json (keeps its hero_level block) + out/adaptive_fit.txt
    python3 adaptive_fit.py --no-write        # report only

What is measured (every number is from the real logs R1-R54; 'within' = within one seat in one round, i.e. how
the SAME observer reacts as the bettor's record changes during the round, which removes style differences
between bettors):
  postflop  fold rate facing a single bet, minus the observer's static clone probability for that spot (its
            profile cell), regressed on what the bettor has shown so far in the round:
              (a) its bet frequency when checked to on that street (shrunk to the population),
              (b) the value share of its big bets (> 0.55 pot) shown at showdown (top pair or better),
            fitted within (round, bettor) on bets by teams other than us.
  preflop   (c) per team: logit of its non-jam 3-bet rate facing a single open = logit(profile cell) + c_team +
                A_team * max(0, f - tau), f = the opener's shrunk fold-to-3-bet so far (m3, f0 shared; grid);
            (d) opener's fold to a 3-bet minus its static cell, regressed (within round and 3-bettor) on the
                3-bettor's shrunk 3-bet frequency so far.
The us-vs-others gaps that these mechanisms do NOT explain are reported; adaptive/params.json's hero_level
block (a static extra fold rate against our seat, calibrated on simulated replays of v10 by
adaptive_calibrate.py) is kept as it is when this script rewrites the file.
"""
import argparse
import json
import math
import os
import statistics
import sys
import time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import clone_adapt as CA  # noqa: E402

REC = os.path.join(HERE, "out", "adaptive_real_records.json")
PARAMS = CA.PARAMS_PATH
OUT_TXT = os.path.join(HERE, "out", "adaptive_fit.txt")
ST = ("flop", "turn", "river")


# =============================================================================== small numerics
def ols_within(groups):
    """groups: key -> list of (x tuple, y). Within-group (demeaned) OLS; returns (beta, se, n)."""
    X = []
    Y = []
    for v in groups.values():
        if len(v) < 2:
            continue
        k = len(v[0][0])
        mx = [sum(t[0][i] for t in v) / len(v) for i in range(k)]
        my = sum(t[1] for t in v) / len(v)
        for xs, y in v:
            X.append([xs[i] - mx[i] for i in range(k)])
            Y.append(y - my)
    return ols(X, Y, intercept=False)


def ols(X, Y, intercept=True):
    n = len(Y)
    if not n:
        return None, None, 0
    rows = [([1.0] if intercept else []) + list(x) for x in X]
    k = len(rows[0])
    A = [[0.0] * k for _ in range(k)]
    c = [0.0] * k
    for r, y in zip(rows, Y):
        for i in range(k):
            c[i] += r[i] * y
            for j in range(k):
                A[i][j] += r[i] * r[j]
    Ai = inv(A)
    if Ai is None:
        return None, None, n
    beta = [sum(Ai[i][j] * c[j] for j in range(k)) for i in range(k)]
    ss = 0.0
    for r, y in zip(rows, Y):
        e = y - sum(b * x for b, x in zip(beta, r))
        ss += e * e
    s2 = ss / max(1, n - k)
    se = [math.sqrt(max(0.0, s2 * Ai[i][i])) for i in range(k)]
    if intercept:
        return beta[1:], se[1:], n
    return beta, se, n


def inv(A):
    m = len(A)
    M = [list(row) + [1.0 if i == j else 0.0 for j in range(m)] for i, row in enumerate(A)]
    for i in range(m):
        piv = max(range(i, m), key=lambda r: abs(M[r][i]))
        if abs(M[piv][i]) < 1e-12:
            return None
        M[i], M[piv] = M[piv], M[i]
        pv = M[i][i]
        M[i] = [v / pv for v in M[i]]
        for r in range(m):
            if r != i and M[r][i] != 0.0:
                f = M[r][i]
                M[r] = [a - f * b for a, b in zip(M[r], M[i])]
    return [row[m:] for row in M]


def logit_fit(rows, sig_c=1.0, sig_a=15.0, a_free=True):
    """rows: (offset, h, y). Penalised MLE of P(y) = sigmoid(offset + c + A h), A >= 0.
    Returns (c, A, se_c, se_A, loglik)."""
    def solve(fit_a):
        c = 0.0
        a = 0.0
        for _ in range(60):
            gc = -c / sig_c ** 2
            ga = -a / sig_a ** 2 if fit_a else 0.0
            hcc = -1.0 / sig_c ** 2
            hca = 0.0
            haa = -1.0 / sig_a ** 2
            for off, h, y in rows:
                p = CA._sigmoid(off + c + a * h)
                w = p * (1.0 - p)
                gc += y - p
                hcc -= w
                if fit_a:
                    ga += (y - p) * h
                    hca -= w * h
                    haa -= w * h * h
            if fit_a:
                det = hcc * haa - hca * hca
                if abs(det) < 1e-12:
                    break
                dc = (haa * gc - hca * ga) / det
                da = (hcc * ga - hca * gc) / det
                c -= dc
                a -= da
                if abs(dc) < 1e-7 and abs(da) < 1e-6:
                    break
            else:
                dc = gc / hcc
                c -= dc
                if abs(dc) < 1e-7:
                    break
        ll = -0.5 * (c / sig_c) ** 2 - (0.5 * (a / sig_a) ** 2 if fit_a else 0.0)
        hcc = -1.0 / sig_c ** 2
        hca = 0.0
        haa = -1.0 / sig_a ** 2
        for off, h, y in rows:
            z = off + c + a * h
            p = CA._sigmoid(z)
            ll += y * math.log(max(1e-12, p)) + (1 - y) * math.log(max(1e-12, 1.0 - p))
            w = p * (1.0 - p)
            hcc -= w
            hca -= w * h
            haa -= w * h * h
        if fit_a:
            det = hcc * haa - hca * hca
            se_c = math.sqrt(max(0.0, -haa / det)) if det else float("nan")
            se_a = math.sqrt(max(0.0, -hcc / det)) if det else float("nan")
        else:
            se_c = math.sqrt(-1.0 / hcc)
            se_a = 0.0
        return c, a, se_c, se_a, ll
    if a_free:
        r = solve(True)
        if r[1] >= 0:
            return r
    return solve(False)


# =============================================================================== priors
def population(doc):
    rec = doc["records"]
    sh = [0] * 6
    ag = [0] * 6
    f3 = [0, 0]
    t3 = [0, 0]
    for row in rec["seat"]:
        if row[3]:
            continue
        for i in range(6):
            sh[i] += row[4][i]
            ag[i] += row[5][i]
        f3[0] += row[6][0]
        f3[1] += row[6][1]
        t3[0] += row[7][0]
        t3[1] += row[7][1]
    us_ag = [0] * 6
    us_t3 = [0, 0]
    us_f3 = [0, 0]
    us_sh = [0] * 6
    for row in rec["seat"]:
        if row[3] and row[0] >= 19 and row[1] == 17:
            for i in range(6):
                us_ag[i] += row[5][i]
                us_sh[i] += row[4][i]
            us_t3[0] += row[7][0]
            us_t3[1] += row[7][1]
            us_f3[0] += row[6][0]
            us_f3[1] += row[6][1]
    return {
        "value_pi": [sh[2 * k + 1] / max(1, sh[2 * k]) for k in range(3)],
        "value_n": [sh[2 * k] for k in range(3)],
        "bet_prior": [ag[2 * k + 1] / max(1, ag[2 * k]) for k in range(3)],
        "bet_n": [ag[2 * k] for k in range(3)],
        "f0": f3[1] / max(1, f3[0]), "f0_n": f3[0],
        "p3": t3[1] / max(1, t3[0]), "p3_n": t3[0],
        "us_v17": {"bet_freq": [us_ag[2 * k + 1] / max(1, us_ag[2 * k]) for k in range(3)],
                   "value_share": [us_sh[2 * k + 1] / max(1, us_sh[2 * k]) for k in range(3)],
                   "value_n": [us_sh[2 * k] for k in range(3)],
                   "threebet_freq": us_t3[1] / max(1, us_t3[0]), "fold_to_3bet": us_f3[1] / max(1, us_f3[0])},
    }


# =============================================================================== postflop
def bet_freq(rec, st, m, prior):
    ag = rec[20]
    o = ag[2 * (st - 1)]
    b = ag[2 * (st - 1) + 1]
    return (b + m * prior[st - 1]) / (o + m)


def shown_dev(rec, m, pi):
    num = 0.0
    cnt = 0
    for k in range(3):
        n = rec[11 + 2 * k]
        num += rec[12 + 2 * k] - pi[k] * n
        cnt += n
    return num / (cnt + m)


def fit_postflop(doc, pop, L):
    F = doc["records"]["fold"]
    pi = pop["value_pi"]
    prior = pop["bet_prior"]
    best = None
    L.append("\n== POSTFLOP: fold facing a single bet, minus the observer's static clone probability (profile cell)")
    L.append("   within (round, bettor) OLS on bets by teams other than us; x_f = bettor's shrunk bet-when-checked-to"
             " frequency on that street, x_s = shrunk shown-value deviation (big bets only)")
    L.append("   hyper-parameter grid (sum over streets of within SSE reduction, big + small bets):")
    for m_b in (5, 10, 20, 40):
        for m_s in (3, 5, 10):
            gain = 0.0
            for st in (1, 2, 3):
                g = defaultdict(list)
                for r in F:
                    if r[9] or r[3] != st:
                        continue
                    xs = (bet_freq(r, st, m_b, prior), shown_dev(r, m_s, pi) if r[4] >= 2 else 0.0)
                    g[(r[0], r[10])].append((xs, (1.0 if r[17] == "F" else 0.0) - r[18]))
                beta, se, n = ols_within(g)
                # SSE reduction ~ sum (beta/se)^2 (likelihood-ratio style)
                gain += sum((b / s) ** 2 for b, s in zip(beta, se) if s and s > 0)
            L.append("     m_bet %2d m_shown %2d: sum z^2 %.1f" % (m_b, m_s, gain))
            if best is None or gain > best[0]:
                best = (gain, m_b, m_s)
    _, m_b, m_s = best
    L.append("   chosen m_bet %d, m_shown %d" % (m_b, m_s))
    out = {"m_bet": m_b, "m_shown": m_s, "bet_prior": prior, "value_pi": pi}
    rows = {}
    for st in (1, 2, 3):
        for grp, sel in (("all", lambda b: True), ("big", lambda b: b >= 2), ("small", lambda b: b <= 1)):
            g = defaultdict(list)
            gx = []
            gy = []
            for r in F:
                if r[9] or r[3] != st or not sel(r[4]):
                    continue
                big = r[4] >= 2
                xs = (bet_freq(r, st, m_b, prior), shown_dev(r, m_s, pi) if big else 0.0)
                y = (1.0 if r[17] == "F" else 0.0) - r[18]
                g[(r[0], r[10])].append((xs, y))
                gx.append(xs)
                gy.append(y)
            if grp == "small":
                g = {k: [((a[0],), y) for a, y in v] for k, v in g.items()}
                gx = [(a[0],) for a in gx]
            bw, sw, nw = ols_within(g)
            bc, sc, nc = ols(gx, gy)
            rows[(st, grp)] = (bw, sw, nw, bc, sc)
            L.append("   %-5s %-5s n %5d  within: k_bet %+.3f +- %.3f%s | cross-section: k_bet %+.3f +- %.3f%s" % (
                ST[st - 1], grp, nw, bw[0], sw[0],
                (" k_shown %+.3f +- %.3f" % (bw[1], sw[1])) if len(bw) > 1 else "", bc[0], sc[0],
                (" k_shown %+.3f +- %.3f" % (bc[1], sc[1])) if len(bc) > 1 else ""))
    # pooled within estimates (all streets): frequency on every size, shown value on big bets
    g = defaultdict(list)
    gs = defaultdict(list)
    for r in F:
        if r[9]:
            continue
        st = r[3]
        y = (1.0 if r[17] == "F" else 0.0) - r[18]
        f = bet_freq(r, st, m_b, prior)
        g[(r[0], r[10], st)].append(((f,), y))
        if r[4] >= 2:
            gs[(r[0], r[10], st)].append(((f, shown_dev(r, m_s, pi)), y))
    bf, sf, nf = ols_within(g)
    bs, ss_, ns = ols_within(gs)
    L.append("   pooled over streets, within: k_bet (all sizes) %+.3f +- %.3f (n %d) | big bets: k_bet %+.3f +- %.3f,"
             " k_shown %+.3f +- %.3f (n %d)" % (bf[0], sf[0], nf, bs[0], ss_[0], bs[1], ss_[1], ns))
    # final choice: frequency slope per street (all sizes) where |z| >= 2, else the pooled value;
    # shown-value slope per street (big bets) where |z| >= 2, else the pooled big-bet value if |z| >= 2, else 0
    k_bet = []
    k_shown = []
    for st in (1, 2, 3):
        bw, sw, _, _, _ = rows[(st, "all")]
        k_bet.append(round(bw[0], 4) if abs(bw[0]) >= 2 * sw[0] else round(bf[0], 4))
        bwb, swb, _, _, _ = rows[(st, "big")]
        if abs(bwb[1]) >= 2 * swb[1]:
            k_shown.append(round(bwb[1], 4))
        elif abs(bs[1]) >= 2 * ss_[1]:
            k_shown.append(round(bs[1], 4))
        else:
            k_shown.append(0.0)
    out["k_bet"] = k_bet
    out["k_shown"] = k_shown
    # references = mean feature over the real decisions facing bets by teams OTHER than us, R19-R54 (the line-ups
    # simreal.py replays; most profiles are fitted on R30-R54), per street AND size bucket. The profile cells already
    # match the real fold rate against other bettors (residual ~0), so the shift must average zero there; small
    # bets come mostly from frequent bettors, so a per-street reference would bias the fold rate per bucket.
    ref_b = []
    ref_s = []
    for st in (1, 2, 3):
        rb = []
        rs = []
        for b in range(5):
            sel = [r for r in F if r[3] == st and r[4] == b and not r[9] and r[0] >= 19]
            xs = [bet_freq(r, st, m_b, prior) for r in sel]
            rb.append(round(statistics.mean(xs), 5) if xs else round(prior[st - 1], 5))
            ys = [shown_dev(r, m_s, pi) for r in sel] if b >= 2 else []
            rs.append(round(statistics.mean(ys), 5) if ys else 0.0)
        ref_b.append(rb)
        ref_s.append(rs)
    out["ref_bet"] = ref_b
    out["ref_shown"] = ref_s
    L.append("   chosen: k_bet %s, k_shown (big bets) %s; references per street x bucket (mean over decisions facing other "
             "teams' bets, R19-R54) bet %s shown %s" % (
        k_bet, k_shown, ref_b, ref_s))
    # how much of the us-vs-others gap do these explain? (R19-R54, v17)
    L.append("   gap facing OUR bets vs others' (R19-R54), real fold minus static cell, and the part explained by"
             " the fitted shifts:")
    expl = {}
    for st in (1, 2, 3):
        for b in range(5):
            us = [r for r in F if r[0] >= 19 and r[1] == 17 and r[9] and r[3] == st and r[4] == b]
            ot = [r for r in F if r[0] >= 19 and r[1] == 17 and not r[9] and r[3] == st and r[4] == b]
            if len(us) < 15:
                continue

            def shift(r):
                v = k_bet[st - 1] * (bet_freq(r, st, m_b, prior) - ref_b[st - 1][r[4]])
                if r[4] >= 2:
                    v += k_shown[st - 1] * (shown_dev(r, m_s, pi) - ref_s[st - 1][r[4]])
                return v
            ru = statistics.mean((1.0 if r[17] == "F" else 0.0) - r[18] for r in us)
            ro = statistics.mean((1.0 if r[17] == "F" else 0.0) - r[18] for r in ot)
            su = statistics.mean(shift(r) for r in us)
            so = statistics.mean(shift(r) for r in ot)
            fu = statistics.mean(1.0 if r[17] == "F" else 0.0 for r in us)
            expl["%s|b%d" % (ST[st - 1], b + 1)] = {"real_fold_vs_us": fu, "n": len(us), "gap_us_minus_others": ru - ro,
                                                    "explained": su - so}
            L.append("     %-5s b%d: real fold vs us %5.1f%% (n %4d) | residual vs us %+5.1f, vs others %+5.1f | fitted "
                     "shift vs us %+5.1f, vs others %+5.1f" % (ST[st - 1], b + 1, 100 * fu, len(us), 100 * ru, 100 * ro,
                                                               100 * su, 100 * so))
    out["evidence"] = {"gap_explained": expl}
    return out


# =============================================================================== preflop
def fit_threebet(doc, pop, L, prof_rounds):
    T = doc["teams"]
    TB = doc["records"]["tb"]
    f0 = pop["f0"]
    by_team = defaultdict(list)
    for r in TB:
        t = T[r[3]]
        if r[10] is None:
            continue
        if prof_rounds.get(t) and r[0] not in prof_rounds[t]:
            continue
        by_team[t].append(r)
    L.append("\n== PREFLOP 3-BETS: logit(non-jam 3-bet) = logit(profile cell) + c_team + A_team * max(0, f - tau), f = opener's"
             " shrunk fold-to-3-bet so far ((folds + m3 f0) / (n + m3), f0 %.3f); records in each team's profile rounds" % f0)
    grid = []
    for m3 in (2, 4, 8, 15, 30):
        for tau in (0.50, 0.55, 0.60, 0.64, 0.68):
            tot = 0.0
            for t, rows in by_team.items():
                data = [(CA._logit(r[10][2]), max(0.0, (r[9] + m3 * f0) / (r[8] + m3) - tau), 1 if r[7] == "R" else 0)
                        for r in rows]
                tot += logit_fit(data)[4]
            grid.append((tot, m3, tau))
    grid.sort(reverse=True)
    L.append("   grid (penalised log-lik summed over %d teams), best first: %s" % (
        len(by_team), "; ".join("m3 %d tau %.2f: %.1f" % (m, t, ll) for ll, m, t in grid[:6])))
    _, m3, tau = grid[0]
    teams = {}
    L.append("   chosen m3 %d, tau %.2f. Per team (n = its vs-open decisions in profile rounds): c, A (SE); 3-bet %% vs our opens"
             " real/model, vs others real/model; by quarter vs us real | model" % (m3, tau))
    rows_out = []
    for t, rows in sorted(by_team.items()):
        data = [(CA._logit(r[10][2]), max(0.0, (r[9] + m3 * f0) / (r[8] + m3) - tau), 1 if r[7] == "R" else 0) for r in rows]
        c, a, sc, sa, ll = logit_fit(data)
        pred = [CA._sigmoid(o + c + a * h) for o, h, _ in data]
        us = [i for i, r in enumerate(rows) if r[4]]
        ot = [i for i, r in enumerate(rows) if not r[4]]

        def rate(idx, real=True):
            if not idx:
                return float("nan")
            if real:
                return sum(1 for i in idx if rows[i][7] in ("R", "J")) / len(idx)
            return sum(pred[i] + rows[i][10][3] for i in idx) / len(idx)
        q_real = []
        q_mod = []
        for q in range(4):
            idx = [i for i in us if (rows[i][2] - 1) // 250 == q]
            q_real.append(rate(idx))
            q_mod.append(rate(idx, False))
        teams[t] = {"c": round(c, 4), "A": round(a, 3), "se_c": round(sc, 4), "se_A": round(sa, 3), "n": len(rows),
                    "n_vs_us": len(us), "real_vs_us": rate(us), "model_vs_us": rate(us, False),
                    "real_vs_others": rate(ot), "model_vs_others": rate(ot, False),
                    "real_vs_us_by_quarter": q_real, "model_vs_us_by_quarter": q_mod}
        rows_out.append((a, t))
    for a, t in sorted(rows_out, reverse=True):
        d = teams[t]
        if d["n_vs_us"] < 30 and d["A"] == 0:
            continue
        L.append("   %-24s n %5d c %+.2f (%.2f) A %5.1f (%4.1f) | vs us %5.1f/%5.1f (n %4d) | vs others %5.1f/%5.1f | Q %s | %s" % (
            t[:24], d["n"], d["c"], d["se_c"], d["A"], d["se_A"], 100 * d["real_vs_us"], 100 * d["model_vs_us"], d["n_vs_us"],
            100 * d["real_vs_others"], 100 * d["model_vs_others"],
            " ".join("%2.0f" % (100 * x) if x == x else " -" for x in d["real_vs_us_by_quarter"]),
            " ".join("%2.0f" % (100 * x) if x == x else " -" for x in d["model_vs_us_by_quarter"])))
    # share of the extra 3-bets that come from calls (teams with A > 0): residual call change / residual 3-bet change
    num = den = 0.0
    for t, rows in by_team.items():
        if teams[t]["A"] <= 0:
            continue
        for r in rows:
            h = max(0.0, (r[9] + m3 * f0) / (r[8] + m3) - tau)
            if h <= 0:
                continue
            p = r[10]
            den += (1.0 if r[7] == "R" else 0.0) - p[2]
            num += (1.0 if r[7] == "P" else 0.0) - p[1]
    s_call = min(1.0, max(0.0, -num / den)) if den > 0 else 0.0
    L.append("   extra 3-bets taken from calls: s_call = %.3f (residual call change %+.1f vs residual 3-bet change %+.1f"
             " over decisions with f > tau, adaptive teams)" % (s_call, num, den))
    # adaptive teams: A clearly above 0 (A >= 3 SE) AND the fitted model reproduces the team's real 3-bet rate against
    # OUR opens within 2.5 binomial SE (the hinge form fits a few teams' other openers but not us, e.g. a team that
    # 3-bets us LESS than others); every other team keeps its static profile (c = A = 0)
    keep = {}
    L.append("   adaptive teams kept (A >= 3 SE and model vs our opens within 2.5 SE of real):")
    for t, d in sorted(teams.items(), key=lambda kv: -kv[1]["A"]):
        if d["A"] <= 0 or d["se_A"] <= 0 or d["A"] < 3 * d["se_A"]:
            continue
        p = d["real_vs_us"]
        n = d["n_vs_us"]
        se = math.sqrt(max(p * (1 - p), 0.01 * 0.99) / max(1, n))
        ok = n >= 30 and abs(d["model_vs_us"] - p) <= 2.5 * se
        L.append("     %-24s A %5.1f (z %4.1f) model vs us %5.1f%% real %5.1f%% (SE %.1f) -> %s" % (
            t[:24], d["A"], d["A"] / d["se_A"], 100 * d["model_vs_us"], 100 * p, 100 * se, "KEEP" if ok else "static"))
        if ok:
            keep[t] = {"c": d["c"], "A": d["A"], "n": d["n"], "se_A": d["se_A"], "real_vs_us": round(p, 4),
                       "model_vs_us": round(d["model_vs_us"], 4), "real_vs_others": round(d["real_vs_others"], 4)}
    return {"f0": round(f0, 5), "m3": m3, "tau": tau, "s_call": round(s_call, 4), "teams": keep}, teams


def fit_fold3(doc, pop, L):
    F3 = doc["records"]["f3"]
    p3 = pop["p3"]
    L.append("\n== PREFLOP FOLD TO A 3-BET: opener's fold minus its static cell (spot pf|opener_vs_3bet|all), regressed within"
             " (round, 3-bettor) on the 3-bettor's shrunk 3-bet frequency so far ((3-bets + m p3) / (n + m), p3 %.4f)" % p3)
    best = None
    for m in (10, 20, 30, 50, 80):
        g = defaultdict(list)
        for r in F3:
            if r[4] or r[9] is None or not r[10] or r[5]:
                continue
            t = (r[8][1] + m * p3) / (r[8][0] + m)
            g[(r[0], r[6])].append(((t,), (1.0 if r[7] == "F" else 0.0) - r[9][0]))
        b, s, n = ols_within(g)
        L.append("   m %2d: within k %+.3f +- %.3f (n %d)" % (m, b[0], s[0], n))
        if best is None or abs(b[0] / s[0]) > best[0]:
            best = (abs(b[0] / s[0]), m, b[0], s[0])
    _, m, k, se = best
    # reference: mean over real 3-bets by teams other than us faced by other openers, R19-R54 (see fit_postflop)
    xs = [((r[8][1] + m * p3) / (r[8][0] + m)) for r in F3 if not r[4] and r[9] is not None and r[10] and not r[5]
          and r[0] >= 19]
    ref = statistics.mean(xs)
    us = [r for r in F3 if not r[4] and r[9] is not None and r[10] and r[5] and r[0] >= 19 and r[1] == 17]
    ot = [r for r in F3 if not r[4] and r[9] is not None and r[10] and not r[5] and r[0] >= 19 and r[1] == 17]
    def res(rs):
        return statistics.mean((1.0 if r[7] == "F" else 0.0) - r[9][0] for r in rs)
    def sh(rs):
        return statistics.mean(k * ((r[8][1] + m * p3) / (r[8][0] + m) - ref) for r in rs)
    L.append("   chosen m %d, k %+.3f +- %.3f, reference (mean over other teams' 3-bets faced, R19-R54) %.4f" % (m, k, se, ref))
    L.append("   vs OUR 3-bets (R19-R54): real fold %.1f%% (n %d), residual vs static cell %+.1f, fitted shift %+.1f | vs"
             " others' residual %+.1f, shift %+.1f" % (100 * statistics.mean(1.0 if r[7] == "F" else 0.0 for r in us), len(us),
                                                      100 * res(us), 100 * sh(us), 100 * res(ot), 100 * sh(ot)))
    return {"p3": round(p3, 5), "m": m, "k": round(k, 4), "se_k": round(se, 4), "ref": round(ref, 5)}


def evidence_report(doc, pop, L):
    """Report-only evidence behind the design (no parameters are fitted here)."""
    T = doc["teams"]
    R = doc["records"]
    S = [x for x in R["shown"] if x[0] >= 19 and x[1] == 17]
    L.append("\n== EVIDENCE 1: big bets (> 0.55 pot) shown at showdown, R19-R54: share that was top pair or better (value_hand)"
             " and mean clone strength, us vs other teams")
    for st in (1, 2, 3):
        parts = []
        for b in (2, 3, 4):
            row = []
            for who in (1, 0):
                xs = [x for x in S if x[5] == st and x[6] == b and x[4] == who]
                if xs:
                    row.append("%s %.2f/%.2f (n %d)" % ("us" if who else "others", sum(x[7] for x in xs) / len(xs),
                                                        sum(x[8] for x in xs) / len(xs), len(xs)))
            parts.append("b%d: %s" % (b + 1, ", ".join(row)))
        L.append("   %-5s %s" % (ST[st - 1], " | ".join(parts)))
    us = [x for x in S if x[4]]
    ot = [x for x in S if not x[4]]
    L.append("   all streets and sizes: us %.3f (n %d), others %.3f (n %d)" % (
        sum(x[7] for x in us) / max(1, len(us)), len(us), sum(x[7] for x in ot) / max(1, len(ot)), len(ot)))
    F = [x for x in R["fold"] if x[0] >= 19 and x[1] == 17]
    L.append("\n== EVIDENCE 2: fold facing a single postflop bet minus the observer's static clone probability, by hand number"
             " in the round (R19-R54). A learned reaction to us would grow during the round.")
    for lo, hi in ((1, 50), (51, 125), (126, 250), (251, 500), (501, 1000)):
        row = []
        for who in (1, 0):
            for lab, sel in (("big", lambda b: b >= 2), ("small", lambda b: b <= 1)):
                xs = [x for x in F if x[9] == who and sel(x[4]) and lo <= x[2] <= hi]
                row.append("%s %s %+5.1f (n %4d)" % ("vs us" if who else "vs others", lab, 100 * sum(
                    (1.0 if x[17] == "F" else 0.0) - x[18] for x in xs) / max(1, len(xs)), len(xs)))
        L.append("   hands %4d-%4d: %s" % (lo, hi, " | ".join(row)))
    f0 = pop["f0"]
    L.append("\n== EVIDENCE 3: 3-bet rate facing OTHER teams' opens, by the opener's shrunk fold-to-3-bet so far (m 10, f0 %.3f)"
             % f0)
    for team in ("FisherMen", "Attention Is All In", "Resonance Qt", "AAST", "Anton", "Anker Batteries", "85p", "Claudebot"):
        if team not in T:
            continue
        ti = T.index(team)
        bins = defaultdict(lambda: [0, 0])
        for x in R["tb"]:
            if x[3] != ti or x[4]:
                continue
            f = (x[9] + 10 * f0) / (x[8] + 10)
            b = min(4, max(0, int((f - 0.45) / 0.06)))
            bins[b][0] += 1
            bins[b][1] += 1 if x[7] in ("R", "J") else 0
        L.append("   %-22s %s" % (team[:22], " | ".join("f~%.2f %4.1f%% (n %d)" % (0.48 + 0.06 * b, 100.0 * v[1] / v[0], v[0])
                                                         for b, v in sorted(bins.items()))))


def fold4_report(doc, L):
    T = doc["teams"]
    F4 = doc["records"]["f4"]
    rows = defaultdict(lambda: [[0, 0], [0, 0]])
    for r in F4:
        if r[4]:
            continue
        rows[T[r[3]]][r[5]][0] += 1
        rows[T[r[3]]][r[5]][1] += 1 if r[7] == "F" else 0
    L.append("\n== 3-BETTOR FACING A 4-BET (real, all rounds): fold %% vs our 4-bets | vs others' (profile cell"
             " pf|raiser_vs_4bet|all is what the clones use)")
    for t in ("FisherMen", "Attention Is All In", "AAST", "Resonance Qt", "Anton", "Anker Batteries"):
        o, u = rows.get(t, [[0, 0], [0, 0]])
        L.append("   %-24s vs us %5.1f%% (n %3d) | vs others %5.1f%% (n %3d)" % (
            t, 100 * u[1] / max(1, u[0]), u[0], 100 * o[1] / max(1, o[0]), o[0]))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--records", default=REC)
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    with open(a.records) as fh:
        doc = json.load(fh)
    pop = population(doc)
    L = ["ADAPTIVE FIT on %s (created %s)" % (os.path.relpath(a.records, HERE), doc.get("created")),
         "population (other teams, R1-R54): value share of shown big bets by street %s (n %s); bet-when-checked-to "
         "frequency %s; opener fold to a 3-bet %.3f (n %d); 3-bet rate facing a single open %.4f (n %d)" % (
             [round(x, 3) for x in pop["value_pi"]], pop["value_n"], [round(x, 3) for x in pop["bet_prior"]], pop["f0"],
             pop["f0_n"], pop["p3"], pop["p3_n"]),
         "our live bot (v17 rounds R19-R54): bet-when-checked-to %s, shown big-bet value share %s (n %s), 3-bet %.4f,"
         " fold to 3-bet %.3f" % ([round(x, 3) for x in pop["us_v17"]["bet_freq"]],
                                   [round(x, 3) for x in pop["us_v17"]["value_share"]], pop["us_v17"]["value_n"],
                                   pop["us_v17"]["threebet_freq"], pop["us_v17"]["fold_to_3bet"])]
    idx = json.load(open(os.path.join(HERE, "profiles", "index.json")))
    prof_rounds = {}
    for nm, v in idx.items():
        p = json.load(open(os.path.join(HERE, "profiles", v["slug"] + ".json")))
        prof_rounds[nm] = set(int(x[1:]) for x in ((p.get("data") or {}).get("rounds") or []) if x.startswith("R"))
    post = fit_postflop(doc, pop, L)
    tb, tb_detail = fit_threebet(doc, pop, L, prof_rounds)
    f3 = fit_fold3(doc, pop, L)
    fold4_report(doc, L)
    evidence_report(doc, pop, L)
    old = {}
    if os.path.exists(PARAMS):
        try:
            old = CA.load_params()
        except Exception:
            old = {}
    params = {
        "format": "testbench-adaptive-params/1",
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "adaptive_fit.py on out/adaptive_real_records.json (real logs R1-R54)",
        "fold": {"big_frac": CA.BIG_FRAC, "clamp": [0.02, 0.98],
                 "bet_prior": [round(x, 5) for x in post["bet_prior"]], "m_bet": post["m_bet"], "ref_bet": post["ref_bet"],
                 "k_bet": post["k_bet"],
                 "value_pi": [round(x, 5) for x in post["value_pi"]], "m_shown": post["m_shown"],
                 "ref_shown": post["ref_shown"], "k_shown": post["k_shown"]},
        "threebet": tb,
        "fold3": f3,
        "union_3bet_range": True,
        "light_3bet_fold": True,
        "hero_level": (old.get("hero_level") or {"note": "not calibrated yet (adaptive_calibrate.py)", "flop": {},
                                                 "turn": {}, "river": {}, "fold_to_3bet": 0.0}),
        "evidence": {"population": pop, "postflop_gap": post["evidence"],
                     "threebet_teams": {t: d for t, d in tb_detail.items() if d["n_vs_us"] >= 30 or d["A"] > 0}},
    }
    txt = "\n".join(L)
    print(txt)
    os.makedirs(os.path.dirname(OUT_TXT), exist_ok=True)
    with open(OUT_TXT, "w") as fh:
        fh.write(txt + "\n")
    if not a.no_write:
        os.makedirs(os.path.dirname(PARAMS), exist_ok=True)
        with open(PARAMS, "w") as fh:
            json.dump(params, fh, indent=1)
        print("\nwrote %s (%.0fs)" % (PARAMS, time.time() - t0))


if __name__ == "__main__":
    main()
