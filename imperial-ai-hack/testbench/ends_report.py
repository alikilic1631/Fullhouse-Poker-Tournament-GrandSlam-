#!/usr/bin/env python3
"""ends_report.py - paired breakdowns of duel_ends.py results (added Sun 15 Nov, test runs).

    python3 ends_report.py out/duel_A.json [out/duel_B.json ...]      # several files = pairs pooled
    python3 ends_report.py --json summary.json out/duel_A.json ...     # also write the numbers as JSON

Prints, over all pairs of the given files (pairs of different deal sets are independent, so they pool):
  * the all-in adjusted difference (cand - base) +- SE over pairs and the seed-clustered SE, z = diff / larger SE;
  * per opponent: the zero-sum split of our adjusted result at his tables (as duel.py), diff +- SE over pairs;
  * how our hands end: raw chips per category (won uncontested by street, showdown won, showdown lost, folded
    by street), each as cand - base bb/100 of ALL hands +- SE over pairs (the rows add up to the raw diff);
  * preflop: opens, 3-bets against our opens per opponent (FisherMen first), our fold to 3-bets, our 3-bets and
    the opener's folds (pooled rates; counts in brackets);
  * postflop bets into no bet: per street / heads-up or multiway / top pair+ or not, bets per 100 hands and the
    share where everyone folded at once.
Needs the per-pair 'end' / 'x' fields of duel_ends.py for the last three parts (plain duel.py files: the first two).
"""
import argparse
import json
import math
import statistics
import sys
from collections import defaultdict

BB = 20


def mean_se(xs):
    if not xs:
        return float("nan"), float("nan")
    m = statistics.mean(xs)
    if len(xs) < 2:
        return m, float("nan")
    return m, statistics.stdev(xs) / math.sqrt(len(xs))


def bb100(chips, hands):
    return chips / BB / max(1, hands) * 100.0


def load(paths):
    pairs = []
    cfgs = []
    for p in paths:
        with open(p) as fh:
            d = json.load(fh)
        cfgs.append(d["config"])
        for r in d["pairs"]:
            if "failed" in r:
                continue
            r = dict(r)
            r["_file"] = p
            r["_seedkey"] = (p, r["seed"])
            pairs.append(r)
    return pairs, cfgs


def paired(pairs, f):
    """mean, SE over pairs and seed-clustered SE of f(pair) (a per-pair difference in bb/100)."""
    d = [f(r) for r in pairs]
    m, se = mean_se(d)
    by = defaultdict(list)
    for r, v in zip(pairs, d):
        by[r["_seedkey"]].append(v)
    _, se_cl = mean_se([statistics.mean(v) for v in by.values()])
    return m, se, se_cl


def fmt(m, se):
    return "%+6.2f +- %4.2f" % (m, se)


def rate(a, b):
    return (100.0 * a / b) if b else float("nan")


def report(paths, out_json=None):
    pairs, cfgs = load(paths)
    if not pairs:
        sys.exit("no pairs")
    res = {"files": paths, "pairs": len(pairs)}
    c0 = cfgs[0]
    print("== %s vs %s | %d pairs from %d file(s) | adaptive: %s" % (
        c0["cand"].split("imperial-ai-hack/")[-1], c0["base"].split("imperial-ai-hack/")[-1], len(pairs), len(paths),
        "no" if not c0.get("adaptive") else ("yes" + (" (no hero level)" if c0["adaptive"].get("no_hero_level") else "")
                                             + ((" off " + ",".join(c0["adaptive"]["components_off"]))
                                                if c0["adaptive"].get("components_off") else ""))))
    for c in cfgs:
        print("   seeds %d-%d x %d rotations, created %s" % (c["seed0"], c["seed0"] + c["seeds"] - 1, c["rotations"],
                                                             c.get("created")))
    hands = pairs[0]["cand"]["hands"]
    # ---- headline
    for key, lab in (("adj", "adj"), ("chips", "raw")):
        m, se, se_cl = paired(pairs, lambda r: bb100(r["cand"][key] - r["base"][key], r["cand"]["hands"]))
        cm = statistics.mean(bb100(r["cand"][key], r["cand"]["hands"]) for r in pairs)
        bm = statistics.mean(bb100(r["base"][key], r["base"]["hands"]) for r in pairs)
        z = m / max(se, se_cl)
        print("%-4s cand %+6.1f  base %+6.1f  diff %s (clustered %.2f)  z %+.2f" % (lab, cm, bm, fmt(m, se), se_cl, z))
        res[lab] = {"cand": cm, "base": bm, "diff": m, "se": se, "se_cl": se_cl, "z": z}
    # ---- per opponent
    opps = sorted({o for r in pairs for o in r["cand"]["vs_adj"]})
    print("\nper opponent (our adj bb/100 per hand with him, zero-sum split; diff +- SE over pairs)")
    res["per_opponent"] = {}
    rows = []
    for o in opps:
        def f(r, o=o):
            h = (r["cand"].get("vs_hands") or {}).get(o, r["cand"]["hands"])
            return bb100(r["cand"]["vs_adj"].get(o, 0.0) - r["base"]["vs_adj"].get(o, 0.0), h)
        m, se, se_cl = paired(pairs, f)
        rows.append((o, m, se, se_cl))
        res["per_opponent"][o] = {"diff": m, "se": se, "se_cl": se_cl}
    rows.sort(key=lambda t: (t[0] != "FisherMen", -t[1]))
    for o, m, se, se_cl in rows:
        print("  %-26s %s  z %+5.2f" % (o, fmt(m, se), m / max(se, se_cl) if max(se, se_cl) > 0 else 0.0))
    have_x = all(r["cand"].get("x") and r["base"].get("x") and "err" not in r["cand"]["x"]
                 and "err" not in r["base"]["x"] for r in pairs)
    if not have_x:
        errs = [r["cand"]["x"]["err"] for r in pairs if r["cand"].get("x") and "err" in r["cand"]["x"]]
        print("\n(no complete duel_ends counters in these files%s)" % ("; first error:\n" + errs[0] if errs else ""))
        if out_json:
            with open(out_json, "w") as fh:
                json.dump(res, fh, indent=1)
        return res
    # ---- outcomes
    print("\nhow our hands end: raw chips, cand - base, bb/100 of all hands +- SE over pairs | hands per 100: cand / base")
    res["ends"] = {}
    cats = ([("unc", s, "won uncontested " + nm) for s, nm in enumerate(("preflop", "flop", "turn", "river"))]
            + [("sd_won", None, "showdown won/chop"), ("sd_lost", None, "showdown lost")]
            + [("fold", s, "folded " + nm) for s, nm in enumerate(("preflop", "flop", "turn", "river"))])

    def cat_val(side, c, s):
        if s is None:
            return side["end"][c]
        return side["x"][c][s]

    tot = 0.0
    for c, s, lab in cats:
        m, se, se_cl = paired(pairs, lambda r: bb100(cat_val(r["cand"], c, s)[1] - cat_val(r["base"], c, s)[1],
                                                     r["cand"]["hands"]))
        nc = sum(cat_val(r["cand"], c, s)[0] for r in pairs) / (len(pairs) * hands) * 100
        nb = sum(cat_val(r["base"], c, s)[0] for r in pairs) / (len(pairs) * hands) * 100
        tot += m
        print("  %-26s %s  z %+5.2f | %6.2f / %6.2f" % (lab, fmt(m, se), m / max(se, se_cl) if se > 0 else 0, nc, nb))
        res["ends"][lab] = {"diff": m, "se": se, "se_cl": se_cl, "per100_cand": nc, "per100_base": nb}
    # grouped rows
    groups = (("ALL won uncontested", [("unc", s) for s in range(4)]),
              ("ALL showdown (won + lost)", [("sd_won", None), ("sd_lost", None)]),
              ("ALL folded", [("fold", s) for s in range(4)]),
              ("postflop uncontested (flop-river)", [("unc", s) for s in (1, 2, 3)]))
    for lab, keys in groups:
        def g(r, keys=keys):
            return bb100(sum(cat_val(r["cand"], c, s)[1] - cat_val(r["base"], c, s)[1] for c, s in keys),
                         r["cand"]["hands"])
        m, se, se_cl = paired(pairs, g)
        print("  %-34s %s  z %+5.2f" % (lab, fmt(m, se), m / max(se, se_cl) if se > 0 else 0))
        res["ends"][lab] = {"diff": m, "se": se, "se_cl": se_cl}
    print("  (rows sum to the raw diff: %+.2f)" % tot)
    # ---- preflop
    agg = {}
    for which in ("cand", "base"):
        a = {"open": 0, "o3": defaultdict(lambda: [0, 0]), "f3": [0, 0, 0, 0], "f3by": defaultdict(lambda: [0, 0]),
             "our3": [0, 0, 0, 0], "our3by": defaultdict(lambda: [0, 0]), "bet": defaultdict(lambda: [0, 0])}
        for r in pairs:
            x = r[which]["x"]
            a["open"] += x["open"]
            for k in ("f3", "our3"):
                for i in range(4):
                    a[k][i] += x[k][i]
            for k in ("o3", "f3by", "our3by", "bet"):
                for o, v in x[k].items():
                    a[k][o][0] += v[0]
                    a[k][o][1] += v[1]
        agg[which] = a
    H = len(pairs) * hands
    print("\npreflop (pooled rates)                      cand                 base")
    print("  our opens per 100 hands          %8.2f            %8.2f" % (100.0 * agg["cand"]["open"] / H,
                                                                           100.0 * agg["base"]["open"] / H))
    res["preflop"] = {"opens_per100": [100.0 * agg["cand"]["open"] / H, 100.0 * agg["base"]["open"] / H]}
    tot3 = [sum(v[1] for v in agg[w]["o3"].values()) for w in ("cand", "base")]
    totop = [sum(v[0] for v in agg[w]["o3"].values()) for w in ("cand", "base")]
    print("  3-bets vs our open, all opps     %6.1f%% (%5d/%6d) %6.1f%% (%5d/%6d)" % (
        rate(tot3[0], totop[0]), tot3[0], totop[0], rate(tot3[1], totop[1]), tot3[1], totop[1]))
    res["preflop"]["3bet_vs_open"] = {}
    for o in sorted(agg["cand"]["o3"], key=lambda o: (o != "FisherMen", o)):
        c, b = agg["cand"]["o3"][o], agg["base"]["o3"][o]
        print("    %-30s %6.1f%% (%5d/%6d) %6.1f%% (%5d/%6d)" % (o, rate(c[1], c[0]), c[1], c[0],
                                                               rate(b[1], b[0]), b[1], b[0]))
        res["preflop"]["3bet_vs_open"][o] = [rate(c[1], c[0]), rate(b[1], b[0])]
    for w in ("cand", "base"):
        pass
    fc, fb = agg["cand"]["f3"], agg["base"]["f3"]
    print("  3-bets faced per 100 hands       %8.2f            %8.2f" % (100.0 * fc[0] / H, 100.0 * fb[0] / H))
    print("  we fold / call / 4-bet           %4.1f/%4.1f/%4.1f%%      %4.1f/%4.1f/%4.1f%%" % (
        rate(fc[1], fc[0]), rate(fc[2], fc[0]), rate(fc[3], fc[0]), rate(fb[1], fb[0]), rate(fb[2], fb[0]),
        rate(fb[3], fb[0])))
    for o in ("FisherMen",):
        c, b = agg["cand"]["f3by"].get(o, [0, 0]), agg["base"]["f3by"].get(o, [0, 0])
        print("    we fold to %-19s %6.1f%% (%5d/%6d) %6.1f%% (%5d/%6d)" % (o + "'s 3-bets", rate(c[1], c[0]), c[1], c[0],
                                                                       rate(b[1], b[0]), b[1], b[0]))
    res["preflop"]["fold_to_3bet"] = [rate(fc[1], fc[0]), rate(fb[1], fb[0])]
    oc, ob = agg["cand"]["our3"], agg["base"]["our3"]
    print("  our 3-bets per 100 hands         %8.2f            %8.2f" % (100.0 * oc[0] / H, 100.0 * ob[0] / H))
    print("  opener folds / calls / 4-bets    %4.1f/%4.1f/%4.1f%%      %4.1f/%4.1f/%4.1f%%" % (
        rate(oc[1], oc[0]), rate(oc[2], oc[0]), rate(oc[3], oc[0]), rate(ob[1], ob[0]), rate(ob[2], ob[0]),
        rate(ob[3], ob[0])))
    res["preflop"]["our3_per100"] = [100.0 * oc[0] / H, 100.0 * ob[0] / H]
    res["preflop"]["opener_fold_to_our3"] = [rate(oc[1], oc[0]), rate(ob[1], ob[0])]
    for o in sorted(agg["cand"]["our3by"], key=lambda o: (o != "FisherMen", o)):
        c, b = agg["cand"]["our3by"][o], agg["base"]["our3by"].get(o, [0, 0])
        print("    our 3-bets vs %-17s %5d (fold %5.1f%%)      %5d (fold %5.1f%%)" % (
            o, c[0], rate(c[1], c[0]), b[0], rate(b[1], b[0])))
    # ---- postflop bets
    print("\npostflop bets into no bet: bets per 100 hands (share everyone folded at once)")
    print("  %-26s %-24s %-24s" % ("street|size|hu/mw|v/n", "cand", "base"))
    res["bets"] = {}
    keys = sorted(set(agg["cand"]["bet"]) | set(agg["base"]["bet"]))
    # condensed: per street x hu/mw x v/n over all sizes, then the big sizes heads-up
    cond = defaultdict(lambda: {"cand": [0, 0], "base": [0, 0]})
    for k in keys:
        st, bk, hm, vv = k.split("|")
        for w in ("cand", "base"):
            v = agg[w]["bet"].get(k, [0, 0])
            for kk in ("%s|all|%s|%s" % (st, hm, vv), "%s|%s|%s|%s" % (st, ("b4+" if bk in ("b4", "b5") else "<=b3"),
                                                                          hm, vv)):
                cond[kk][w][0] += v[0]
                cond[kk][w][1] += v[1]
    for k in sorted(cond):
        c, b = cond[k]["cand"], cond[k]["base"]
        if c[0] + b[0] < 20:
            continue
        print("  %-26s %6.2f (%5.1f%%, n %6d)   %6.2f (%5.1f%%, n %6d)" % (
            k, 100.0 * c[0] / H, rate(c[1], c[0]), c[0], 100.0 * b[0] / H, rate(b[1], b[0]), b[0]))
        res["bets"][k] = {"cand_per100": 100.0 * c[0] / H, "cand_foldthrough": rate(c[1], c[0]),
                          "base_per100": 100.0 * b[0] / H, "base_foldthrough": rate(b[1], b[0]), "n": [c[0], b[0]]}
    if out_json:
        with open(out_json, "w") as fh:
            json.dump(res, fh, indent=1)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", help="also write the numbers to this JSON file")
    a = ap.parse_args()
    report(a.files, a.json)


if __name__ == "__main__":
    main()
