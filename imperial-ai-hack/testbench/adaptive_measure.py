#!/usr/bin/env python3
"""adaptive_measure - decision records for the ADAPTIVE clone model, from real logs or simulated logs.

    python3 adaptive_measure.py --extract            # real logs -> out/adaptive_real_records.json (~30 s, ~1 GB RAM)

Every hand of a round is replayed in order through clone_adapt.TableModel (exactly what an adaptive clone
learns from hand_end summaries), and these decisions are recorded with what the deciding seat could know
at that moment:

  fold   every non-hero decision facing exactly ONE postflop bet (spots vs_bet / xr): street, size bucket and
         size of the bet, hu/mw, observer, bettor (us or not), the bettor's shown big bets so far in the round
         (TableModel.sh row), the action, and the observer's static clone fold probability for that spot
         (its profile cell, clone.py's lookup).
  tb     every non-hero first decision facing a single open (spot pf|vs_open|<group>): opener (us or not),
         the opener's fold-to-3-bet record so far (TableModel.f3 row), action F/P/R/J, the profile cell.
  f3     every opener facing exactly one 3-bet (fold or not; who 3-bet).
  f4     every 3-bettor facing a 4-bet (raisers = opener, 3-bettor, 4-bettor): action, who 4-bet, who opened.
  shown  every big bet (> 0.55 pot) shown at showdown: seat, street, bucket, value_hand, clone strength.

The same extraction runs on simulated logs (simreal.py --adaptive-metrics) so real and bench are measured
with identical code.  adaptive_fit.py reads the real records and fits adaptive/params.json.
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import clone as CL  # noqa: E402
import clone_adapt as CA  # noqa: E402

HERO = "Durahim 1453"
OUT_DIR = os.path.join(HERE, "out")
PROF_DIR = os.path.join(HERE, "profiles")
REAL_RECORDS = os.path.join(OUT_DIR, "adaptive_real_records.json")
BI = {b: i for i, b in enumerate(CL.BUCKETS)}
GI = {g: i for i, g in enumerate(CL.GROUPS)}


class CellLookup:
    """Static clone action probabilities for (team, spot key): the profile cell with clone.py's fallback chain;
    teams without a profile use the pooled 'field' profile (as simreal.py does)."""

    def __init__(self, prof_dir=PROF_DIR):
        with open(os.path.join(prof_dir, "index.json")) as fh:
            self.index = json.load(fh)
        self.cells = {}
        self.cache = {}
        for name, v in self.index.items():
            with open(os.path.join(prof_dir, v["slug"] + ".json")) as fh:
                self.cells[name] = json.load(fh)["spots"]

    def p(self, team, key, acts):
        ck = (team, key)
        r = self.cache.get(ck)
        if r is not None:
            return r
        cells = self.cells.get(team) if (team in self.index and self.index[team].get("kind", "team") == "team") \
            else self.cells["field"]
        r = None
        for k in CL.parent_keys(key):
            c = cells.get(k)
            if c and c.get("p"):
                r = CL._norm(c["p"], acts)
                break
        if r is None:
            r = [1.0 / len(acts)] * len(acts)
        r = [round(x, 5) for x in r]
        self.cache[ck] = r
        return r


def extract_round(r, hero, look, teams):
    """Records of one hh.Round (real or simulated). hero = our seat. teams: name -> index (extended here)."""
    n = r.n
    tid = []
    for nm in r.players:
        if nm not in teams:
            teams[nm] = len(teams)
        tid.append(teams[nm])
    names = list(r.players)
    jams = [0] * n
    for Hd in r.hands:
        for s in {A.seat for A in Hd.acts if A.st == 0 and A.a == "raise" and (A.allin or A.to >= CL.JAM_TO)}:
            jams[s] += 1
    jam_rate = [j / float(max(1, len(r.hands))) for j in jams]
    model = CA.TableModel(n)
    rnum = r.rnum
    ver = r.version
    out = {"fold": [], "tb": [], "f3": [], "f4": [], "shown": [], "seat": []}
    for Hd in r.hands:
        hn = Hd.num
        trk = CL.Tracker(n, Hd.button)
        trk.jam_rate = jam_rate
        trk.post(Hd.sb, 10)
        trk.post(Hd.bb, 20)
        raisers = []
        first_pf = set()
        bigbets = []
        for A in Hd.acts:
            if A.st > trk.st:
                trk.board(A.st)
            s = A.seat
            a = A.a
            if A.st == 0:
                if s != hero and s not in first_pf and trk.nr == 1 and not trk.limped[s] and not trk.raised[s] \
                        and not trk.called[s]:
                    key = trk.spot(s)
                    if key.startswith("pf|vs_open|"):
                        o = trk.opener
                        if a == "raise":
                            lab = "J" if (A.allin or A.to >= CL.JAM_TO) else "R"
                        else:
                            lab = {"fold": "F", "call": "P"}.get(a, "P")
                        out["tb"].append([rnum, ver, hn, tid[s], 1 if o == hero else 0, tid[o], GI[key.split("|")[2]],
                                          lab, model.f3[o][0], model.f3[o][1],
                                          look.p(names[s], key, ("F", "P", "R", "J")) if s != hero else None])
                if trk.nr == 2 and trk.opener == s and len(raisers) == 2:
                    k3 = trk.spot(s)
                    out["f3"].append([rnum, ver, hn, tid[s], 1 if s == hero else 0, 1 if raisers[1] == hero else 0,
                                      tid[raisers[1]], a[0].upper(), list(model.t3[raisers[1]]),
                                      look.p(names[s], k3, ("F", "P", "R", "J")) if s != hero else None,
                                      1 if k3 == "pf|opener_vs_3bet|all" else 0])
                if trk.nr == 3 and len(raisers) == 3 and s == raisers[1]:
                    out["f4"].append([rnum, ver, hn, tid[s], 1 if s == hero else 0, 1 if raisers[2] == hero else 0,
                                      1 if raisers[0] == hero else 0, a[0].upper(), 1 if raisers[2] == raisers[0] else 0])
                first_pf.add(s)
                if a == "raise":
                    raisers.append(s)
            else:
                tc = trk.to_call(s)
                if s != hero and tc > 0 and trk.nr == 1:
                    key = trk.spot(s)
                    parts = key.split("|")
                    b = trk.agg_cur
                    out["fold"].append([rnum, ver, hn, A.st, BI[parts[3]], round(trk.bet_rfrac or 0.0, 4),
                                        1 if parts[2] == "hu" else 0, 1 if parts[1] == "xr" else 0, tid[s],
                                        1 if b == hero else 0, tid[b]] + list(model.sh[b])
                                       + [a[0].upper(), look.p(names[s], key, ("F", "C", "R"))[0],
                                          1 if trk.agg_prev == b else 0, list(model.ag[b]), list(model.vp[b]),
                                          list(model.sd[b]), list(model.bw[b])])
                if a == "raise" and trk.nr == 0:
                    bigbets.append((s, A.st, A.rfrac))
            trk.act(s, a, A.amt)
        # shown big bets of this hand (records), then the model learns the hand (exactly as a clone would)
        for s, st, rf in bigbets:
            if rf is None or rf <= CA.BIG_FRAC or s not in Hd.went_sd or s not in Hd.hole:
                continue
            c1, c2 = CL.CI[Hd.hole[s][0]], CL.CI[Hd.hole[s][1]]
            bc = [CL.CI[x] for x in Hd.board[:2 + st]]
            out["shown"].append([rnum, ver, hn, tid[s], 1 if s == hero else 0, st, BI[CL.bucket(rf)],
                                 1 if CA.value_hand(c1, c2, bc) else 0, round(CL.strength(c1, c2, bc), 4)])
        hist, shown, board, winners = CA.summary_from_hand(Hd)
        model.learn(hist, shown, board, n, winners)
    # end-of-round totals per seat (population priors): team, is_us, sh, ag, f3, t3, vp, sd
    out["seat"] = [[rnum, ver, tid[s], 1 if s == hero else 0, model.sh[s], model.ag[s], model.f3[s], model.t3[s],
                    model.vp[s], model.sd[s]] for s in range(n)]
    return out


def extract_rounds(rounds, look=None, hero_name=HERO):
    look = look or CellLookup()
    teams = {}
    recs = {"fold": [], "tb": [], "f3": [], "f4": [], "shown": [], "seat": []}
    meta = []
    for r in rounds:
        o = extract_round(r, r.seat, look, teams)
        for k in recs:
            recs[k].extend(o[k])
        meta.append({"label": r.label, "rnum": r.rnum, "version": r.version, "players": list(r.players),
                     "seat": r.seat, "hands": len(r.hands)})
    names = [None] * len(teams)
    for nm, i in teams.items():
        names[i] = nm
    return {"teams": names, "rounds": meta, "records": recs,
            "columns": {"fold": "rnum ver hand street bucket_idx rfrac hu xr obs_team bettor_is_us bettor_team "
                                "sh_n1 sh_v1 sh_n2 sh_v2 sh_n3 sh_v3 action pF_static bettor_prev_street_aggressor "
                                "bettor_ag[opp,bets x flop/turn/river] bettor_vp[hands,vpip] bettor_sd[showdowns,won] "
                                "bettor_bw[shown big-bet hands,won]",
                        "tb": "rnum ver hand obs_team opener_is_us opener_team group_idx action opener_f3_n "
                              "opener_f3_folds p_static[F,P,R,J]",
                        "f3": "rnum ver hand opener_team opener_is_us threebettor_is_us threebettor_team action "
                              "threebettor_t3[vs-open decisions,3-bets] p_static[F,P,R,J] (opener's spot) spot_is_opener_vs_3bet",
                        "f4": "rnum ver hand threebettor_team threebettor_is_us fourbettor_is_us opener_is_us action "
                              "fourbettor_is_opener",
                        "shown": "rnum ver hand team is_us street bucket_idx value strength",
                        "seat": "rnum ver team is_us sh ag f3 t3 vp sd (end-of-round TableModel rows)"},
            "groups": list(CL.GROUPS), "buckets": list(CL.BUCKETS)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--extract", action="store_true", help="extract the real records (R1-R54, practice excluded)")
    ap.add_argument("--out", default=REAL_RECORDS)
    a = ap.parse_args()
    if not a.extract:
        ap.error("nothing to do (use --extract; analysis lives in adaptive_fit.py)")
    import hh as H
    t0 = time.time()
    rounds = [r for r in H.load_all() if not r.practice]
    print("loaded %d rounds (%.1fs)" % (len(rounds), time.time() - t0), flush=True)
    doc = extract_rounds(rounds)
    doc["created"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(a.out, "w") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    print("records: " + ", ".join("%s %d" % (k, len(v)) for k, v in doc["records"].items()))
    print("saved %s (%.1fs)" % (a.out, time.time() - t0))


if __name__ == "__main__":
    main()
