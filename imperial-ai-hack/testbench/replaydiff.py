#!/usr/bin/env python3
"""replaydiff - a candidate bot vs the LIVE bot on the REAL decision points of the real round logs.

    python3 replaydiff.py CAND.py                         # R19-R54 (the live bot's rounds), 6 processes
    python3 replaydiff.py CAND.py --base ../v10/bot.py    # + noise floor: (cand vs live) - (base vs live)
    python3 replaydiff.py CAND.py --rounds 30-33 --show R33:512 R31:7
    python3 replaydiff.py CAND.py --all                   # every log (practice + R1-R54)
    python3 replaydiff.py CAND.py --files ../../imperial-ai-hack-pokerbots-kit/hands/saturday_r041.json

How the replay works
  For every selected round log the tool rebuilds, event by event, the exact engine state that the live
  bot was sent at each of OUR decision points (same fields and values as engine/game.py builds them:
  pot, stacks, bets, folded, to_call, min/max_raise_to, legal_actions, raises_this_street, history ...),
  JSON round-trips it like engine/players.py SubprocessPlayer does, and asks the candidate.  A fresh
  module and a fresh Agent are made per round; the candidate gets on_table_start (FixedHandsTable info),
  every hand in order and on_hand_end with the engine's summary (board, shown cards of every showdown
  seat, winners, end stacks, full history), so its opponent model learns from exactly the same history
  as the live bot did.  Later decisions in a hand always follow the REAL trajectory.  The reply is turned
  into an action with the dealer's own rules (bot_runner.normalise + game.py: illegal raise -> call/check,
  call with nothing to call -> check, fold with nothing to call -> check, error/None -> check else fold).
  Sanity checks run on every hand (actor order, pot/to_call vs hh.py, end stacks vs results) and are
  reported; they should all be 0.

Classification of each decision point (raise amounts are raise-to totals for the street)
  same                     same action (raises: |cand - live| <= --size-tol x live raise-to)
  cand_fold_live_continue  cand folds, live called or raised
  cand_continue_live_fold  cand calls or raises, live folded
  cand_raise_live_call     facing a bet: cand raises, live called
  cand_call_live_raise     facing a bet: cand calls, live raised
  cand_bet_live_check      nothing to call: cand bets, live checked
  cand_check_live_bet      nothing to call: cand checks, live bet
  diff_raise_size          both raise, sizes differ by more than --size-tol

Valuation of the FIRST deviation in each hand (later decision points of that hand are moot)
  EXACT    cand_fold_live_continue: cand result = -(our chips invested before that decision);
           delta = cand - live, where live = the luck-adjusted live result (live - hh h.luck) when the
           live hand was an all-in with every showdown hand known, else the actual live result
           (the raw, unadjusted delta is reported too).
  APPROX   cand_continue_live_fold and the remaining players reached showdown (cards shown): passive
           call-down: our total commitment becomes the largest total commitment of any showdown
           player (i.e. we call our to_call and every later bet; capped by our stack), and we
           win/split/lose on the final board (evalx.eval7) against every shown hand.
           delta = cf result - live result (= -invested).  The others' actions are assumed unchanged.
  UNKNOWN  everything else: counted and listed with the live result of those hands (the stakes).
           A rough fold-equity estimate is given, SEPARATELY, for cand bets/raises where live
           checked/called: P(every opponent folds to a bet of that size, street and opponent count,
           measured on the selected logs over all players' bets) x (pot won now - live result).  It
           assumes nothing changes when the bet is called, so it is optimistic for bluffs; it is never
           added to the exact/approx numbers.  Likewise a rough river-call estimate for heads-up river
           calls where live folded (no cards are shown, so no APPROX): P(caller wins at showdown vs
           opponents' heads-up river bets of that size, measured on the selected logs) x (pot + call) - call;
           optimistic because the field's calling ranges are stronger than the hands we folded.

Noise floor (read every candidate number against it)
  The live bot itself (v10/bot.py) does not agree 100% with its own logged actions: its Monte Carlo is
  random and has a 2.1 ms deadline.  Measured over R19-R54 with seeds 1-5: 98.30% +- 0.04 same action
  type, 97.46% +- 0.03 incl. raise size; EXACT +9499 +- 3183 chips (+1.32 +- 0.44 bb/100), APPROX
  -688 +- 1376 chips, UNKNOWN 968 +- 15 hands.  So compare a candidate with --base ../v10/bot.py: the
  base is replayed on the same decision points with the SAME random seed per round (a candidate that
  is a patched copy of v10 then draws the same Monte Carlo samples as the base until their decisions
  differ) and the report shows (cand vs live) - (base vs live) per category plus a direct cand-vs-base
  comparison.  Residual cand-vs-base noise comes from the MC deadline under machine load (observed: at
  load average 67, v10_riverfold vs v10 had ~110 non-river differences with K=1, 2 with K=0.05); for
  patched copies of v10 add --time-scale 0.05 (the bot's clock runs 20x slower, its 2.1 ms deadline is
  never hit; the agreement with live is unchanged at 98.3%) to make the pairing essentially exact.

Output
  Per-round table (decisions, agreement %, exact / approx delta chips, unknown count, live chips, time),
  totals in chips and bb/100 over the hands replayed (bb/100 = chips / 20 / hands * 100), category
  tables (all decision points by street; first deviations with their values), cand-vs-base, the --top
  largest valued deviations with "R33 h512" references (hh.fmt_hand dumps in the .txt), the largest
  UNKNOWN ones, --show traces.  Saved to out/replaydiff_<name>.json (everything, incl. every first
  deviation) and out/replaydiff_<name>.txt.

Timing
  Bots run in-process: R19-R54 takes ~5-10 s with 6 processes on an idle machine (cand + base ~2x).
  act() time is measured and reported (think s per round, max ms, decisions over 25 ms); in-process it is
  ~10x below the live think_s (which includes the dealer's IPC and a slower sandbox core) and it rises
  when the machine is loaded.  --time-scale K makes the bot's clocks run K times faster: K > 1 emulates
  a K-times slower machine (times reported x K), K < 1 only removes deadline noise (times stay real).
  --enforce-time applies the dealer's 25 ms / 10 s bank rule to those times.  Use the kit's local_sim.py
  for a real timing gate.

Validation (testbench/out/validate_replaydiff.py, numbers observed on R19-R54)
  * reconstruction checks are 0 on all 55 logs (72,125 decision points);
  * out/check_fold_to_any_bet.py (deterministic): 7542/7542 first deviations identical in category and
    value to an independent computation from hh.py (7435 EXACT, -272,749 chips);
  * out/v10_riverfold.py (v10 that folds every river bet): every EXACT river value equals the
    independent hh value; tool + hands with an earlier (noise) deviation reconcile to the chip;
  * out/v10_no3betcall.py: 183/183 hands identical, incl. the lazily computed all-in luck.

Standard library only (python >= 3.9).  Never modifies bots, logs or the kit.
"""
import argparse
import contextlib
import gc
import glob
import importlib.util
import json
import os
import random
import re
import sys
import time
import traceback
import zlib
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import hh as H  # noqa: E402
import evalx as EV  # noqa: E402

_REAL = {nm: getattr(time, nm) for nm in ("perf_counter", "monotonic", "time", "process_time", "thread_time",
                                          "perf_counter_ns", "monotonic_ns", "time_ns", "process_time_ns",
                                          "thread_time_ns") if hasattr(time, nm)}
_real_pc = _REAL["perf_counter"]
_real_time = _REAL["time"]

ROOT = os.path.dirname(HERE)                          # imperial-ai-hack/
LIVE_BOT = os.path.join(ROOT, "v10", "bot.py")        # = site version 17, played R19-R54
OUT_DIR = os.path.join(HERE, "out")
BB = 20
STREETS = H.STREETS
ST_IDX = H.ST_IDX
TIME_LIMIT_S = 0.025
BANK_S = 10.0
CATS = ["same", "cand_fold_live_continue", "cand_continue_live_fold", "cand_raise_live_call",
        "cand_call_live_raise", "cand_bet_live_check", "cand_check_live_bet", "diff_raise_size", "other"]
FE_CATS = ("cand_bet_live_check", "cand_raise_live_call")
SIZE_LABELS = ["<40%", "40-75%", "75-110%", ">110%"]


# ============================================================================ bot loading
_NLOAD = [0]


def _seed_rngs(ns, seed, salt):
    """Seed every random.Random instance found in a namespace (module globals or agent attributes)."""
    for k, v in list(ns.items()):
        if isinstance(v, random.Random) and not isinstance(v, random.SystemRandom):
            v.seed((seed * 1000003 + zlib.crc32((salt + str(k)).encode())) & 0xFFFFFFFFFFFF)


def load_bot_module(path, seed):
    """Fresh module per call (the sandbox starts a fresh process every round)."""
    _NLOAD[0] += 1
    random.seed(seed)
    spec = importlib.util.spec_from_file_location("replaydiff_bot_%d_%d" % (os.getpid(), _NLOAD[0]), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _seed_rngs(vars(mod), seed, "m:")
    return mod


@contextlib.contextmanager
def bot_clock(k):
    """While active, every clock in the time module runs k times faster, so a bot that budgets its own
    time (v10: 2.1 ms Monte Carlo deadline, time-bank thresholds) behaves as on a k-times slower machine.
    Must wrap the bot's import too (bots bind time.perf_counter at import).  Our own timing uses _REAL."""
    if not k or k == 1.0:
        yield
        return
    saved = {}
    for nm, real in _REAL.items():
        origin = real()
        if nm.endswith("_ns"):
            fn = (lambda real=real, origin=origin: origin + int((real() - origin) * k))
        else:
            fn = (lambda real=real, origin=origin: origin + (real() - origin) * k)
        saved[nm] = getattr(time, nm)
        setattr(time, nm, fn)
    try:
        yield
    finally:
        for nm, fn in saved.items():
            setattr(time, nm, fn)


# ============================================================================ dealer rules
def normalise(result):
    """engine/bot_runner.py normalise()."""
    if isinstance(result, dict):
        return {"action": result.get("action"), "amount": result.get("amount")}
    if isinstance(result, (tuple, list)):
        return {"action": result[0] if result else None, "amount": result[1] if len(result) > 1 else None}
    if isinstance(result, str):
        return {"action": result, "amount": None}
    return {"action": None, "amount": None}


def engine_action(decision, to_call, can_raise, min_to, max_to):
    """engine/game.py _betting_round: how the dealer turns a reply into the logged (action, amount)."""
    decision = decision or {}
    action = str(decision.get("action", "")).lower()
    amount = decision.get("amount")
    if action in ("raise", "bet", "all_in", "allin") and can_raise:
        if action in ("all_in", "allin"):
            amount = max_to
        try:
            target = int(amount)
        except (TypeError, ValueError, OverflowError):
            target = min_to
        return "raise", max(min_to, min(target, max_to))
    if action in ("call", "raise", "bet", "all_in", "allin") and to_call > 0:
        return "call", to_call
    if to_call == 0:
        return "check", 0
    return "fold", 0


def classify(la, lamt, ca, camt, tol):
    """Category of the candidate's (engine-normalised) action vs the live one."""
    if ca == la:
        if la == "raise" and abs(camt - lamt) > tol * max(lamt, 1):
            return "diff_raise_size"
        return "same"
    if ca == "fold":
        return "cand_fold_live_continue"
    if la == "fold":
        return "cand_continue_live_fold"
    if la == "call" and ca == "raise":
        return "cand_raise_live_call"
    if la == "check" and ca == "raise":
        return "cand_bet_live_check"
    if la == "raise":
        return "cand_call_live_raise" if ca == "call" else "cand_check_live_bet"
    return "other"


def _next_alive(stacks, seat, n):
    for k in range(1, n + 1):
        s = (seat + k) % n
        if stacks[s] > 0:
            return s
    return seat


def _jcopy(obj):
    return json.loads(json.dumps(obj))


# ============================================================================ replay of one round
def replay_round(bot_path, d, seed, tol, trace_hands=(), enforce_time=False, time_scale=1.0):
    """Feed one real round log through a bot. Returns decisions, traces and stats."""
    hero = int(d["seat"])
    n = len(d["players"])
    meta = d.get("round") or {}
    hands = d["hands"]
    h0 = hands[0]
    start0 = list(h0.get("start_stacks") or [2000] * n)
    st = {"errors": 0, "first_error": None, "think_s": 0.0, "max_ms": 0.0, "over25": 0, "timeouts": 0,
          "bank_out": 0, "order_mismatch": 0, "call_mismatch": 0, "stack_mismatch": 0, "dead": False,
          "load_s": 0.0, "think_real_s": 0.0}
    t_load = _real_pc()
    mod = load_bot_module(bot_path, seed)
    st["load_s"] = _real_pc() - t_load
    agent = None
    info = {"seat": hero, "num_players": n, "format": "fixed_hands", "hands": int(meta.get("hands") or len(hands)),
            "starting_stack": start0[hero], "stacks_reset_each_hand": True, "small_blind": h0["sb"],
            "big_blind": h0["bb"], "betting": "no_limit", "raise_cap": None}
    try:
        agent = mod.Agent()
        _seed_rngs(vars(agent), seed, "a:")
        if hasattr(agent, "on_table_start"):
            agent.on_table_start(_jcopy(info))
    except Exception:  # noqa: BLE001  (bot_runner: agent = None -> every decision auto-played)
        st["errors"] += 1
        st["first_error"] = traceback.format_exc(limit=6)
        st["dead"] = True
        agent = None
    bank = BANK_S
    decisions = []
    traces = {}
    for h in hands:
        hn = h["n"]
        start = list(h.get("start_stacks") or [2000] * n)
        stacks = list(start)
        bets = [0] * n
        contrib = [0] * n
        folded = [False] * n
        history = []
        board = []
        street = "preflop"
        si = 0
        button = h["button"]
        sbv, bbv = h["sb"], h["bb"]
        hole = list(h["hole"][str(hero)])
        npost = 0
        current = 0
        min_inc = bbv
        raises = 0
        pending = set()
        may_raise = {}
        ptr = 0
        winners = []
        k = 0
        tr = [] if hn in trace_hands else None
        for ei, e in enumerate(h["events"]):
            t = e[0]
            if t == "post":
                s, amt = e[1], min(e[2], stacks[e[1]])
                stacks[s] -= amt
                bets[s] += amt
                contrib[s] += amt
                history.append({"seat": s, "street": "preflop",
                                "action": "small_blind" if npost == 0 else "big_blind", "amount": bets[s]})
                npost += 1
                if npost == 2:     # preflop betting round starts left of the big blind
                    current, min_inc, raises = max(bets), bbv, 0
                    pending = {i for i in range(n) if not folded[i] and stacks[i] > 0}
                    may_raise = {i: True for i in pending}
                    ptr = _next_alive(stacks, s, n)
            elif t == "board":
                street = e[1]
                si = ST_IDX[street]
                board = list(e[2])
                bets = [0] * n
                current, min_inc, raises = 0, bbv, 0
                pending = {i for i in range(n) if not folded[i] and stacks[i] > 0}
                may_raise = {i: True for i in pending}
                ptr = _next_alive(stacks, button, n)
            elif t == "refund":
                s, amt = e[1], e[2]
                stacks[s] += amt
                contrib[s] -= amt
                bets[s] -= amt
            elif t == "win":
                stacks[e[1]] += e[2]
                winners.append({"seat": e[1], "amount": e[2], "hand": e[3] if len(e) > 3 else None})
            elif t == "act":
                s, a, amt = e[1], e[2], e[3]
                guard = 0
                while ptr not in pending and guard <= n:
                    ptr = (ptr + 1) % n
                    guard += 1
                if ptr != s:
                    st["order_mismatch"] += 1
                to_call = min(current - bets[s], stacks[s])
                others = any(not folded[j] and stacks[j] > 0 for j in range(n) if j != s)
                max_to = bets[s] + stacks[s]
                can_raise = bool(may_raise.get(s, True) and max_to > current and others)
                min_to = min(current + min_inc, max_to)
                if s == hero:
                    legal = (["fold", "call"] if to_call > 0 else ["check"]) + (["raise"] if can_raise else [])
                    state = {"type": "act", "hand_number": hn, "street": street, "seat": s, "button": button,
                             "hole_cards": list(hole), "board": list(board), "small_blind": sbv,
                             "big_blind": bbv, "blind_level": 0, "pot": sum(contrib), "stacks": list(stacks),
                             "bets": list(bets), "folded": list(folded), "to_call": to_call,
                             "min_raise_to": min_to if can_raise else None,
                             "max_raise_to": max_to if can_raise else None, "legal_actions": legal,
                             "betting": "no_limit", "raise_cap": None, "raises_this_street": raises,
                             "history": list(history)}
                    reply = None
                    raw = None
                    dt = 0.0
                    if agent is None:
                        pass
                    elif enforce_time and bank <= 0:
                        st["bank_out"] += 1
                    else:
                        sj = _jcopy(state)
                        t0 = _real_pc()
                        try:
                            raw = agent.act(sj)
                            reply = _jcopy(normalise(raw))
                        except Exception:  # noqa: BLE001
                            reply = None
                            st["errors"] += 1
                            if st["first_error"] is None:
                                st["first_error"] = traceback.format_exc(limit=6)
                        dt_real = _real_pc() - t0
                        # dealer view: real time, or K x real when emulating a K-times slower machine (K > 1)
                        dt = dt_real * max(1.0, time_scale)
                        st["think_s"] += dt
                        st["think_real_s"] += dt_real
                        st["max_ms"] = max(st["max_ms"], dt * 1000.0)
                        if dt > TIME_LIMIT_S:
                            st["over25"] += 1
                        if enforce_time:
                            limit = min(TIME_LIMIT_S, bank)
                            bank -= min(dt, limit)
                            if dt > limit:
                                reply = None
                                st["timeouts"] += 1
                    ca, camt = engine_action(reply, to_call, can_raise, min_to, max_to)
                    lamt = amt if a in ("raise", "call") else 0
                    cat = classify(a, lamt, ca, camt, tol)
                    nopp = sum(1 for j in range(n) if j != s and not folded[j])
                    decisions.append({"h": hn, "k": k, "i": ei, "st": si, "la": a, "lamt": lamt, "ca": ca,
                                      "camt": camt, "tc": to_call, "pot": sum(contrib), "inv": contrib[s],
                                      "hi": current, "bet": bets[s], "max_to": max_to, "nopp": nopp,
                                      "cat": cat, "ms": round(dt * 1000.0, 3)})
                    if tr is not None:
                        tr.append({"k": k, "street": street, "board": list(board), "pot": sum(contrib),
                                   "to_call": to_call, "legal": legal,
                                   "range": [min_to, max_to] if can_raise else None,
                                   "live": [a, lamt], "reply": repr(raw)[:120], "cand": [ca, camt],
                                   "cat": cat, "ms": round(dt * 1000.0, 2)})
                    k += 1
                # apply the LIVE action exactly as the dealer did
                if a == "raise":
                    add = amt - bets[s]
                    stacks[s] -= add
                    bets[s] += add
                    contrib[s] += add
                    raise_size = amt - current
                    full = raise_size >= min_inc
                    if full:
                        min_inc = raise_size
                    current = amt
                    raises += 1
                    pending = {j for j in range(n) if j != s and not folded[j] and stacks[j] > 0}
                    for j in pending:
                        if full:
                            may_raise[j] = True
                        else:
                            may_raise.setdefault(j, True)
                elif a == "call":
                    if amt != to_call:
                        st["call_mismatch"] += 1
                    stacks[s] -= amt
                    bets[s] += amt
                    contrib[s] += amt
                elif a == "fold":
                    folded[s] = True
                pending.discard(s)
                may_raise[s] = False
                history.append({"seat": s, "street": street, "action": a, "amount": amt})
                ptr = (s + 1) % n
        end = [start[i] + h["results"][i] for i in range(n)]
        if stacks != end:
            st["stack_mismatch"] += 1
        sd = sorted(int(x) for x in (h.get("showdown") or {}))
        shown = {str(i): list(h["hole"][str(i)]) for i in sd if str(i) in h["hole"]}
        summary = {"type": "hand_end", "hand_number": hn, "board": list(h.get("board") or []), "shown": shown,
                   "winners": winners, "stacks": end, "history": history}
        if agent is not None and hasattr(agent, "on_hand_end"):
            try:
                agent.on_hand_end(_jcopy(summary))
            except Exception:  # noqa: BLE001  (bot_runner ignores on_hand_end errors)
                pass
        if tr is not None:
            traces[hn] = tr
    del agent, mod
    return {"decisions": decisions, "traces": traces, "stats": st}


# ============================================================================ valuation
def size_bucket(fr):
    if fr is None:
        return 3
    if fr < 0.4:
        return 0
    if fr < 0.75:
        return 1
    if fr < 1.1:
        return 2
    return 3


def pop_allfold(r):
    """Population table: for every bet/raise by any seat, did every remaining opponent fold to it?
    key 'street,min(opponents,3),size bucket' -> [bets, all-fold]."""
    t = defaultdict(lambda: [0, 0])
    for Hd in r.hands:
        acts = Hd.acts
        for j, A in enumerate(acts):
            if A.a != "raise" or A.active < 2:
                continue
            later = acts[j + 1:]
            if not later:
                continue
            key = "%d,%d,%d" % (A.st, min(A.active - 1, 3), size_bucket(A.rfrac))
            t[key][0] += 1
            t[key][1] += all(B.a == "fold" for B in later)
    return dict(t)


def pop_rivercall(r):
    """Population table: heads-up river bets/raises by OPPONENTS that were called and shown down -> the
    caller's share (win 1, tie 0.5).  key = size bucket of the bet -> [bets, caller share]."""
    t = defaultdict(lambda: [0, 0.0])
    me = r.seat
    for Hd in r.hands:
        if len(Hd.went_sd) != 2 or len(Hd.board) != 5:
            continue
        bets = [A for A in Hd.acts if A.st == 3 and A.a == "raise"]
        if not bets:
            continue
        B = bets[-1]
        callers = [s for s in Hd.went_sd if s != B.seat]
        if B.seat == me or B.active != 2 or len(callers) != 1 or B.seat not in Hd.hole or callers[0] not in Hd.hole:
            continue
        b = [EV.card(c) for c in Hd.board]
        vb, vc = _eval(Hd.hole[B.seat], b), _eval(Hd.hole[callers[0]], b)
        key = str(size_bucket(B.rfrac))
        t[key][0] += 1
        t[key][1] += 1.0 if vc > vb else (0.5 if vc == vb else 0.0)
    return dict(t)


def _eval(cards, board):
    return EV.eval7([EV.card(c) for c in cards] + board)


def value_first(r, Hd, dec):
    """Value the first deviation of a hand (EXACT / APPROX / UNKNOWN)."""
    hero = r.seat
    live = Hd.results[hero]
    luck = Hd.luck[hero] if Hd.luck else 0.0
    rec = {"ref": "%s h%d" % (r.label, Hd.num), "label": r.label, "h": Hd.num, "i": dec["i"], "k": dec["k"],
           "st": dec["st"],
           "ctx": dec.get("ctx"), "cat": dec["cat"], "la": dec["la"], "lamt": dec["lamt"], "ca": dec["ca"],
           "camt": dec["camt"], "tc": dec["tc"], "pot": dec["pot"], "inv": dec["inv"], "nopp": dec["nopp"],
           "hi": dec["hi"], "live": live, "live_adj": round(live - luck, 1), "luck": round(luck, 1),
           "pos": Hd.pos[hero], "hole": "".join(Hd.hole.get(hero, ())), "kind": "unknown", "delta": None}
    cat = dec["cat"]
    if cat == "cand_fold_live_continue":
        cand = -dec["inv"]
        rec.update(kind="exact", cand=cand, delta=round(cand - (live - luck), 1), delta_raw=cand - live)
        return rec
    if cat == "cand_continue_live_fold":
        sd = sorted(Hd.went_sd)
        if len(sd) >= 2 and all(s in Hd.hole for s in sd) and len(Hd.board) == 5 and hero in Hd.hole:
            inv_final = [Hd.invested[s] - Hd.refunds.get(s, 0) for s in range(r.n)]
            top_sd = max(inv_final[s] for s in sd)
            stack0 = 2000
            cf_total = min(stack0, max(top_sd, dec["inv"] + dec["tc"]))
            pot_cf = sum(inv_final) - inv_final[hero] + cf_total
            board = [EV.card(c) for c in Hd.board]
            mine = _eval(Hd.hole[hero], board)
            opp = [_eval(Hd.hole[s], board) for s in sd]
            best = max(opp)
            if mine > best:
                share, res = float(pot_cf), "win"
            elif mine == best:
                share, res = pot_cf / (1.0 + sum(1 for v in opp if v == best)), "split"
            else:
                share, res = 0.0, "lose"
            cand = share - cf_total
            rec.update(kind="approx", cand=round(cand, 1), delta=round(cand - live, 1),
                       cost=cf_total - dec["inv"], sd=res, pot_cf=pot_cf)
            return rec
    if cat == "cand_continue_live_fold" and dec["st"] == 3 and dec["nopp"] == 1 and dec["ca"] == "call":
        rec["bet_frac"] = round(dec["tc"] / max(1, dec["pot"] - dec["tc"]), 3)   # villain's bet / pot before it
    if cat in FE_CATS:
        denom = dec["pot"] + dec["tc"]
        rec["rfrac"] = round((dec["camt"] - dec["hi"]) / denom, 3) if denom > 0 else None
        rec["win_now"] = dec["pot"] - dec["inv"]
    return rec


# ============================================================================ one job = one round x one bot
def run_job(job):
    path, role, bot_path, seed, tol, show, enforce, want_pop, top, tscale = job
    t0 = _real_time()
    d = json.load(open(path))
    r = H.load_round(path, with_luck=False)     # all-in luck is computed lazily, only where it is used
    raw_by_num = {h["n"]: h for h in d["hands"]}
    rseed = (seed * 7919 + zlib.crc32(r.ref.encode())) & 0x7FFFFFFF   # same for cand and base
    trace_hands = set(hn for (lab, hn) in show if lab == r.label)
    gc_was = gc.isenabled()
    with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), bot_clock(tscale):
        rep = replay_round(bot_path, d, rseed, tol, trace_hands, enforce, tscale)
    # the bot may have frozen/disabled the collector (v10 does): drop its module and clean up
    gc.unfreeze()
    gc.collect()
    if gc_was:
        gc.enable()
    hero = r.seat
    by_num = {Hd.num: Hd for Hd in r.hands}
    st = rep["stats"]
    st["state_mismatch"] = 0
    cat_st = defaultdict(lambda: [0, 0, 0, 0])
    size_same = []
    decs_by_hand = defaultdict(list)
    compact = []
    for dec in rep["decisions"]:
        Hd = by_num[dec["h"]]
        A = next((x for x in Hd.acts if x.i == dec["i"]), None)
        if A is None or A.seat != hero or A.pot != dec["pot"] or A.to_call != dec["tc"]:
            st["state_mismatch"] += 1
        dec["ctx"] = A.ctx if A is not None else None
        cat_st[dec["cat"]][dec["st"]] += 1
        if dec["la"] == "raise" and dec["ca"] == "raise":
            size_same.append(dec["camt"] - dec["lamt"])
        decs_by_hand[dec["h"]].append(dec)
        compact.append((dec["h"], dec["k"], dec["st"], dec["la"], dec["lamt"], dec["ca"], dec["camt"],
                        dec["tc"], dec["cat"], dec["ms"]))
    firsts = []
    for hn in sorted(decs_by_hand):
        for dec in decs_by_hand[hn]:
            if dec["cat"] != "same":
                Hd = by_num[hn]
                if dec["cat"] == "cand_fold_live_continue" and Hd.allin and len(Hd.went_sd) >= 2:
                    Hd.raw = raw_by_num[hn]          # hh.compute_luck needs the raw events
                    H.compute_luck(Hd)
                    Hd.raw = None
                firsts.append(value_first(r, Hd, dec))
                break
    valued = sorted((f for f in firsts if f["delta"] is not None), key=lambda f: -abs(f["delta"]))[:top]
    for f in valued:
        f["dump"] = H.fmt_hand(r, by_num[f["h"]])
    unk = sorted((f for f in firsts if f["kind"] == "unknown"), key=lambda f: -abs(f["live"]))[:10]
    for f in unk:
        f["dump"] = H.fmt_hand(r, by_num[f["h"]])
    shows = []
    for hn, tr in sorted(rep["traces"].items()):
        shows.append({"ref": "%s h%d" % (r.label, hn), "label": r.label, "h": hn, "trace": tr,
                      "dump": H.fmt_hand(r, by_num[hn])})
    nd = len(rep["decisions"])
    same_type = sum(1 for x in rep["decisions"] if x["la"] == x["ca"])
    ex = [f for f in firsts if f["kind"] == "exact"]
    ap = [f for f in firsts if f["kind"] == "approx"]
    un = [f for f in firsts if f["kind"] == "unknown"]
    row = {"label": r.label, "rnum": r.rnum, "practice": r.practice, "table": r.table, "seat": hero, "n": r.n,
           "version": r.version, "hands": len(r.hands), "decisions": nd,
           "agree_type": same_type, "agree_full": sum(1 for x in rep["decisions"] if x["cat"] == "same"),
           "raise_pairs": len(size_same), "raise_size_equal": sum(1 for x in size_same if x == 0),
           "exact": round(sum(f["delta"] for f in ex), 1), "exact_raw": sum(f["delta_raw"] for f in ex),
           "n_exact": len(ex), "approx": round(sum(f["delta"] for f in ap), 1), "n_approx": len(ap),
           "approx_raise": round(sum(f["delta"] for f in ap if f["ca"] == "raise"), 1),
           "n_approx_raise": sum(1 for f in ap if f["ca"] == "raise"),
           "unknown": len(un), "unknown_live": sum(f["live"] for f in un),
           "live_chips": sum(Hd.results[hero] for Hd in r.hands),
           "live_dev_hands": sum(f["live"] for f in firsts),
           "think_s": round(st["think_s"], 3), "think_real_s": round(st["think_real_s"], 3),
           "max_ms": round(st["max_ms"], 2), "over25": st["over25"],
           "timeouts": st["timeouts"], "bank_out": st["bank_out"], "errors": st["errors"],
           "first_error": st["first_error"], "order_mismatch": st["order_mismatch"],
           "call_mismatch": st["call_mismatch"], "state_mismatch": st["state_mismatch"],
           "stack_mismatch": st["stack_mismatch"], "load_s": round(st["load_s"], 3),
           "live_timeouts": r.timeouts, "live_think_s": r.think_s, "wall_s": round(_real_time() - t0, 2)}
    return {"role": role, "label": r.label, "row": row, "cat_st": {c: v for c, v in cat_st.items()},
            "size_diffs": size_same, "firsts": firsts, "top": valued, "unk_top": unk, "shows": shows,
            "decisions": compact, "pop": pop_allfold(r) if want_pop else None,
            "popcall": pop_rivercall(r) if want_pop else None}


# ============================================================================ aggregation / report
def bb100(chips, hands):
    return chips / BB / hands * 100.0 if hands else 0.0


def parse_rounds(spec):
    out = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def select_files(a):
    files = sorted(glob.glob(os.path.join(H.HANDS_DIR, "*.json")))
    if a.files:
        return [os.path.abspath(f) for f in a.files]
    if a.all:
        return files
    want = parse_rounds(a.rounds)
    out = []
    for f in files:
        b = os.path.basename(f)
        m = re.search(r"r0*(\d+)\.json$", b)
        if "practice" not in b and m and int(m.group(1)) in want:
            out.append(f)
    return out


def parse_show(items):
    out = []
    for s in items:
        m = re.match(r"^\s*([RrPp]?)(\d+)\s*[:/ h]\s*h?(\d+)\s*$", s)
        if not m:
            sys.exit("--show expects R33:512, got %r" % s)
        out.append(("%s%d" % ((m.group(1) or "R").upper(), int(m.group(2))), int(m.group(3))))
    return out


def bot_name(path):
    base = os.path.basename(path)
    if base == "bot.py":
        return os.path.basename(os.path.dirname(os.path.abspath(path)))
    return os.path.splitext(base)[0]


def summarize(results):
    """Totals over a list of job results for one role."""
    tot = Counter()
    cats = Counter()
    cat_st = defaultdict(lambda: [0, 0, 0, 0])
    first = defaultdict(lambda: {"hands": 0, "exact": 0.0, "n_exact": 0, "approx": 0.0, "n_approx": 0,
                                 "unknown": 0, "live": 0})
    sizes = []
    for res in results:
        row = res["row"]
        for k in ("hands", "decisions", "agree_type", "agree_full", "raise_pairs", "raise_size_equal",
                  "n_exact", "n_approx", "n_approx_raise", "unknown", "unknown_live", "live_chips", "over25",
                  "timeouts",
                  "errors", "order_mismatch", "call_mismatch", "state_mismatch", "stack_mismatch"):
            tot[k] += row[k]
        for k in ("exact", "exact_raw", "approx", "approx_raise", "think_s", "think_real_s"):
            tot[k] += row[k]
        tot["max_ms"] = max(tot["max_ms"], row["max_ms"])
        tot["max_think_s"] = max(tot["max_think_s"], row["think_s"])
        for c, v in res["cat_st"].items():
            cats[c] += sum(v)
            for i in range(4):
                cat_st[c][i] += v[i]
        sizes.extend(res["size_diffs"])
        for f in res["firsts"]:
            g = first[f["cat"]]
            g["hands"] += 1
            g["live"] += f["live"]
            if f["kind"] == "exact":
                g["exact"] += f["delta"]
                g["n_exact"] += 1
            elif f["kind"] == "approx":
                g["approx"] += f["delta"]
                g["n_approx"] += 1
            else:
                g["unknown"] += 1
    return {"tot": dict(tot), "cats": dict(cats), "cat_st": {c: v for c, v in cat_st.items()},
            "first": {c: dict(v) for c, v in first.items()}, "sizes": sizes}


def fe_estimates(results, pop):
    """Rough fold-equity estimate for the UNKNOWN bet/raise deviations (kept separate)."""
    out = []
    for res in results:
        for f in res["firsts"]:
            if f["kind"] != "unknown" or f["cat"] not in FE_CATS:
                continue
            key = "%d,%d,%d" % (f["st"], min(max(f["nopp"], 1), 3), size_bucket(f.get("rfrac")))
            nb, nf = pop.get(key, [0, 0])
            p = (nf + 1.0) / (nb + 2.0)
            est = p * (f["win_now"] - f["live_adj"])
            f["fe_p"] = round(p, 3)
            f["fe_est"] = round(est, 1)
            out.append(est)
    return out


def rc_estimates(results, popcall):
    """Rough estimate for UNKNOWN heads-up river calls where live folded (no showdown to value them):
    P(caller wins | opponents' HU river bets of that size, called and shown down) x (pot + call) - call."""
    out = []
    for res in results:
        for f in res["firsts"]:
            if f["kind"] != "unknown" or "bet_frac" not in f:
                continue
            nb, share = popcall.get(str(size_bucket(f["bet_frac"])), [0, 0.0])
            w = (share + 1.0) / (nb + 2.0)
            est = w * (f["pot"] + f["tc"]) - f["tc"]
            f["rc_w"] = round(w, 3)
            f["rc_est"] = round(est, 1)
            out.append(est)
    return out


def _size_stats(diffs):
    """cand - live raise-to differences (chips) where both raised."""
    if not diffs:
        return None
    ds = sorted(abs(x) for x in diffs)
    return {"pairs": len(ds), "equal": sum(1 for x in ds if x == 0), "mean_abs": round(sum(ds) / len(ds), 2),
            "median_abs": ds[len(ds) // 2], "p90_abs": ds[int(len(ds) * 0.9)], "max_abs": ds[-1],
            "mean_signed": round(sum(diffs) / len(diffs), 2)}


def _nodump(f):
    return {k: v for k, v in f.items() if k != "dump"}


def fmt_dev(f):
    la = "%s%s" % (f["la"], (" %d" % f["lamt"]) if f["la"] in ("raise", "call") else "")
    ca = "%s%s" % (f["ca"], (" %d" % f["camt"]) if f["ca"] in ("raise", "call") else "")
    val = ("%+8.0f" % f["delta"]) if f["delta"] is not None else "       ?"
    extra = ""
    if f["kind"] == "exact":
        extra = "live %+6d adj %+7.0f -> cand %+6d" % (f["live"], f["live_adj"], f["cand"])
    elif f["kind"] == "approx":
        extra = "live %+6d -> cand %+7.0f (call-down %d, %s)" % (f["live"], f["cand"], f["cost"], f["sd"])
    else:
        extra = "live %+6d" % f["live"]
    return "%-10s %-7s %-7s %-9s %-4s %-5s %-15s -> %-15s %s  %s" % (
        f["ref"], f["kind"], STREETS[f["st"]], f.get("ctx") or "", f["pos"], f["hole"], la, ca, val, extra)


def build_report(a, cand_path, base_path, files, results, wall):
    L = []
    cres = sorted([r for r in results if r["role"] == "cand"], key=lambda r: (r["row"]["practice"] is False, r["row"]["rnum"]))
    bres = sorted([r for r in results if r["role"] == "base"], key=lambda r: (r["row"]["practice"] is False, r["row"]["rnum"]))
    C = summarize(cres)
    B = summarize(bres) if bres else None
    pop = defaultdict(lambda: [0, 0])
    for res in cres:
        for k, v in (res["pop"] or {}).items():
            pop[k][0] += v[0]
            pop[k][1] += v[1]
    pop = dict(pop)
    fe_c = fe_estimates(cres, pop)
    fe_b = fe_estimates(bres, pop) if bres else []
    popcall = defaultdict(lambda: [0, 0.0])
    for res in cres:
        for k, v in (res.get("popcall") or {}).items():
            popcall[k][0] += v[0]
            popcall[k][1] += v[1]
    popcall = dict(popcall)
    rc_c = rc_estimates(cres, popcall)
    rc_b = rc_estimates(bres, popcall) if bres else []
    ct = C["tot"]
    hands = ct["hands"]
    labels = [r["row"]["label"] for r in cres]
    L.append("replaydiff  cand = %s  (%s)" % (a.name, os.path.relpath(cand_path, HERE)))
    if base_path:
        L.append("            base = %s  (%s)" % (bot_name(base_path), os.path.relpath(base_path, HERE)))
    L.append("rounds %s .. %s: %d logs, %d hands, %d of our decision points; seed %d, size-tol %.2f, time-scale %g%s; "
             "%.0f s with %d procs"
             % (labels[0] if labels else "-", labels[-1] if labels else "-", len(cres), hands, ct["decisions"],
                a.seed, a.size_tol, a.time_scale, ", time limits ENFORCED" if a.enforce_time else "", wall, a.procs))
    chk = (ct["order_mismatch"], ct["call_mismatch"], ct["state_mismatch"], ct["stack_mismatch"])
    L.append("reconstruction checks (should all be 0): actor order %d, call amount %d, pot/to_call vs hh %d, end stacks %d"
             % chk)
    L.append("")
    # ---------------------------------------------------------------- per round
    bmap = {r["row"]["label"]: r["row"] for r in bres}
    hdr = "%-5s %3s %4s %5s %6s  %8s %4s %8s %4s %4s" % ("round", "tbl", "seat", "dec", "agree%", "exactD", "n", "approxD", "n", "unk")
    if bres:
        hdr += " | %6s %8s %8s %4s" % ("base%", "exactD", "approxD", "unk")
    hdr += " | %8s %6s %6s %5s %3s" % ("live", "thinks", "maxms", ">25ms", "err")
    L.append("per round (exactD/approxD = candidate minus live, chips; agree% = same action type)")
    L.append(hdr)
    for res in cres:
        w = res["row"]
        line = "%-5s %3s %4d %5d %6.1f  %+8.0f %4d %+8.0f %4d %4d" % (
            w["label"], w["table"], w["seat"], w["decisions"], 100.0 * w["agree_type"] / max(1, w["decisions"]),
            w["exact"], w["n_exact"], w["approx"], w["n_approx"], w["unknown"])
        if bres:
            b = bmap.get(w["label"])
            if b:
                line += " | %6.1f %+8.0f %+8.0f %4d" % (100.0 * b["agree_type"] / max(1, b["decisions"]), b["exact"],
                                                       b["approx"], b["unknown"])
            else:
                line += " | %6s %8s %8s %4s" % ("-", "-", "-", "-")
        line += " | %+8d %6.2f %6.1f %5d %3d" % (w["live_chips"], w["think_s"], w["max_ms"], w["over25"], w["errors"])
        L.append(line)
    line = "%-5s %3s %4s %5d %6.1f  %+8.0f %4d %+8.0f %4d %4d" % (
        "total", "", "", ct["decisions"], 100.0 * ct["agree_type"] / max(1, ct["decisions"]), ct["exact"],
        ct["n_exact"], ct["approx"], ct["n_approx"], ct["unknown"])
    if B:
        bt = B["tot"]
        line += " | %6.1f %+8.0f %+8.0f %4d" % (100.0 * bt["agree_type"] / max(1, bt["decisions"]), bt["exact"],
                                               bt["approx"], bt["unknown"])
    line += " | %+8d %6.2f %6.1f %5d %3d" % (ct["live_chips"], ct["think_s"] / max(1, len(cres)), ct["max_ms"],
                                              ct["over25"], ct["errors"])
    L.append(line + "   (think s = mean per round)")
    L.append("")

    # ---------------------------------------------------------------- totals
    def totals_block(S, fe, rc, who):
        t = S["tot"]
        hn = t["hands"]
        out = []
        out.append("%s totals over %d hands (bb/100 = chips / 20 / hands * 100):" % (who, hn))
        out.append("  agreement with live: %.2f%% same action type, %.2f%% same incl. raise size (tol %.0f%%); "
                   "both-raise pairs %d, exactly equal size %.1f%%"
                   % (100.0 * t["agree_type"] / max(1, t["decisions"]), 100.0 * t["agree_full"] / max(1, t["decisions"]),
                      100 * a.size_tol, t["raise_pairs"], 100.0 * t["raise_size_equal"] / max(1, t["raise_pairs"])))
        out.append("  EXACT  cand folds where live continued : %5d hands  delta %+9.0f chips = %+7.2f bb/100"
                   "   (raw, no luck adj.: %+.0f = %+.2f bb/100)"
                   % (t["n_exact"], t["exact"], bb100(t["exact"], hn), t["exact_raw"], bb100(t["exact_raw"], hn)))
        out.append("  APPROX cand continues where live folded: %5d hands  delta %+9.0f chips = %+7.2f bb/100"
                   "   (passive call-down to a known showdown; of which cand RAISED: %d hands %+.0f chips)"
                   % (t["n_approx"], t["approx"], bb100(t["approx"], hn), t["n_approx_raise"], t["approx_raise"]))
        out.append("  UNKNOWN first deviations              : %5d hands  (live result in those hands %+.0f chips)"
                   % (t["unknown"], t["unknown_live"]))
        if fe:
            out.append("    rough fold-equity estimate for %d of them (cand bets/raises where live checked/called): "
                       "%+.0f chips = %+.2f bb/100  [optimistic: assumes no change when called; NOT added]"
                       % (len(fe), sum(fe), bb100(sum(fe), hn)))
        if rc:
            out.append("    rough river-call estimate for %d of them (cand calls a heads-up river bet live folded): "
                       "%+.0f chips = %+.2f bb/100  [optimistic: population caller win rate vs bets of that size; "
                       "NOT added]" % (len(rc), sum(rc), bb100(sum(rc), hn)))
        out.append("  live bot's actual result over these rounds: %+d chips = %+.2f bb/100" % (
            t["live_chips"], bb100(t["live_chips"], hn)))
        out.append("  in-process act() time: %.2f s/round (max %.2f), max %.1f ms, %d decisions > 25 ms%s, %d errors%s"
                   % (t["think_s"] / max(1, len(cres)), t["max_think_s"], t["max_ms"], t["over25"],
                      (" [x%g slower-machine emulation; real %.2f s/round]"
                       % (a.time_scale, t["think_real_s"] / max(1, len(cres)))) if a.time_scale > 1.0 else "",
                      t["errors"],
                      (", %d auto-played by --enforce-time" % t["timeouts"]) if a.enforce_time else ""))
        return out

    L.extend(totals_block(C, fe_c, rc_c, "CANDIDATE " + a.name))
    if B:
        L.extend(totals_block(B, fe_b, rc_b, "BASE " + bot_name(base_path)))
        bt = B["tot"]
        L.append("CANDIDATE minus BASE (each vs the same live actions; noise cancels in expectation):")
        L.append("  EXACT  %+9.0f chips = %+7.2f bb/100   APPROX %+9.0f chips = %+7.2f bb/100   UNKNOWN hands %+d"
                 % (ct["exact"] - bt["exact"], bb100(ct["exact"] - bt["exact"], hands), ct["approx"] - bt["approx"],
                    bb100(ct["approx"] - bt["approx"], hands), ct["unknown"] - bt["unknown"]))
    L.append("")
    # ---------------------------------------------------------------- categories, all decision points
    L.append("all decision points by category (every point is compared on the real trajectory)")
    h2 = "%-26s %7s %6s" % ("category", "cand", "%")
    if B:
        h2 += " %7s %6s %8s" % ("base", "%", "cand-base")
    h2 += "   cand by street: preflop   flop   turn  river"
    L.append(h2)
    for c in CATS:
        cc = C["cats"].get(c, 0)
        bc = B["cats"].get(c, 0) if B else 0
        if not cc and not bc:
            continue
        line = "%-26s %7d %6.2f" % (c, cc, 100.0 * cc / max(1, ct["decisions"]))
        if B:
            line += " %7d %6.2f %+8d" % (bc, 100.0 * bc / max(1, B["tot"]["decisions"]), cc - bc)
        v = C["cat_st"].get(c, [0, 0, 0, 0])
        line += "   %22d %6d %6d %6d" % tuple(v)
        L.append(line)
    if C["sizes"]:
        ds = sorted(abs(x) for x in C["sizes"])
        L.append("raise sizes when both raised: %d pairs, |cand - live| median %d, p90 %d chips"
                 % (len(ds), ds[len(ds) // 2], ds[int(len(ds) * 0.9)]))
    L.append("")
    # ---------------------------------------------------------------- first deviation per hand
    L.append("first deviation per hand (the only one valued)")
    h3 = "%-26s %6s %9s %5s %9s %5s %5s %9s" % ("category", "hands", "exactD", "n", "approxD", "n", "unk", "live")
    if B:
        h3 += " | %6s %9s %9s %5s | %9s %9s" % ("base", "exactD", "approxD", "unk", "c-b exact", "c-b apprx")
    L.append(h3)
    for c in CATS[1:]:
        g = C["first"].get(c)
        gb = B["first"].get(c) if B else None
        if not g and not gb:
            continue
        g = g or {"hands": 0, "exact": 0, "n_exact": 0, "approx": 0, "n_approx": 0, "unknown": 0, "live": 0}
        line = "%-26s %6d %+9.0f %5d %+9.0f %5d %5d %+9d" % (c, g["hands"], g["exact"], g["n_exact"], g["approx"],
                                                              g["n_approx"], g["unknown"], g["live"])
        if B:
            gb = gb or {"hands": 0, "exact": 0, "n_exact": 0, "approx": 0, "n_approx": 0, "unknown": 0, "live": 0}
            line += " | %6d %+9.0f %+9.0f %5d | %+9.0f %+9.0f" % (gb["hands"], gb["exact"], gb["approx"], gb["unknown"],
                                                                g["exact"] - gb["exact"], g["approx"] - gb["approx"])
        L.append(line)
    L.append("")
    # ---------------------------------------------------------------- cand vs base directly
    cvb = None
    if bres:
        bdec = {}
        for res in bres:
            for x in res["decisions"]:
                bdec[(res["label"], x[0], x[1])] = x
        same = tot = 0
        cc = Counter()
        cc_st = defaultdict(lambda: [0, 0, 0, 0])
        for res in cres:
            for x in res["decisions"]:
                y = bdec.get((res["label"], x[0], x[1]))
                if y is None:
                    continue
                tot += 1
                same += x[5] == y[5]
                c = classify(y[5], y[6], x[5], x[6], a.size_tol)
                cc[c] += 1
                cc_st[c][x[2]] += 1
        cvb = {"decisions": tot, "agree_type": same, "cats": dict(cc), "cat_st": {c: v for c, v in cc_st.items()}}
        L.append("candidate vs base directly on the same %d decision points: %.2f%% same action type"
                 % (tot, 100.0 * same / max(1, tot)))
        for c in CATS[1:]:
            if cc.get(c):
                L.append("  %-26s %6d   by street %s" % (c.replace("live", "base"), cc[c], cc_st[c]))
        L.append("")
    # ---------------------------------------------------------------- top deviations
    tops = sorted([f for res in cres for f in res["top"]], key=lambda f: -abs(f["delta"]))[:a.top]
    L.append("%d largest valued deviations (|delta|, chips; exact uses the luck-adjusted live result):" % len(tops))
    L.append("%-3s %-10s %-7s %-7s %-9s %-4s %-5s %-15s    %-15s %8s" % ("#", "ref", "kind", "street", "ctx", "pos",
                                                                         "hole", "live", "cand", "delta"))
    for i, f in enumerate(tops, 1):
        L.append("%-3d %s" % (i, fmt_dev(f)))
    L.append("")
    unks = sorted([f for res in cres for f in res["unk_top"]], key=lambda f: -abs(f["live"]))[:10]
    if unks:
        L.append("largest UNKNOWN deviations by |live result| (no value assigned):")
        for f in unks:
            L.append("    %s" % fmt_dev(f))
        L.append("")
    console_cut = len(L)
    L.append("hand dumps of the %d largest valued deviations" % len(tops))
    for i, f in enumerate(tops, 1):
        L.append("#%d %s" % (i, fmt_dev(f)))
        L.append(f.get("dump", ""))
        L.append("")
    if unks:
        L.append("hand dumps of the largest UNKNOWN deviations")
        for f in unks:
            L.append(fmt_dev(f))
            L.append(f.get("dump", ""))
            L.append("")
    # ---------------------------------------------------------------- traces
    shows = [s for res in cres for s in res["shows"]]
    bshow = {(s["label"], s["h"]): s for res in bres for s in res["shows"]}
    show_lines = []
    for s in shows:
        show_lines.append("trace %s (cand = %s%s)" % (s["ref"], a.name, (", base = %s" % bot_name(base_path)) if base_path else ""))
        show_lines.append(s["dump"])
        bs = bshow.get((s["label"], s["h"]))
        btr = {t["k"]: t for t in bs["trace"]} if bs else {}
        for t in s["trace"]:
            rng = ("[%d..%d]" % tuple(t["range"])) if t["range"] else ""
            line = "  %-7s %-14s pot %5d to_call %5d %s%s  live %-11s cand %-11s %-24s %5.1f ms  reply %s" % (
                t["street"], " ".join(t["board"]), t["pot"], t["to_call"], "/".join(t["legal"]), rng,
                "%s %d" % tuple(t["live"]), "%s %d" % tuple(t["cand"]), t["cat"], t["ms"], t["reply"])
            if t["k"] in btr:
                line += "   base %s %d (%s)" % (btr[t["k"]]["cand"][0], btr[t["k"]]["cand"][1], btr[t["k"]]["cat"])
            show_lines.append(line)
        show_lines.append("")
    missing = set(parse_show(a.show)) - set((s["label"], s["h"]) for s in shows)
    for lab, hn in sorted(missing):
        show_lines.append("trace %s h%d: not in the selected rounds (or no such hand)" % (lab, hn))
    errs = [(r["row"]["label"], r["role"], r["row"]["first_error"]) for r in results if r["row"]["first_error"]]
    err_lines = []
    for lab, role, tb in errs[:3]:
        err_lines.append("first error (%s, %s):\n%s" % (role, lab, tb))
    report = {
        "tool": "replaydiff", "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "args": {k: v for k, v in vars(a).items()}, "cand": {"name": a.name, "path": cand_path},
        "base": {"name": bot_name(base_path), "path": base_path} if base_path else None,
        "files": files, "rounds": labels, "hands": hands, "decisions": ct["decisions"], "wall_s": round(wall, 1),
        "per_round": {"cand": [r["row"] for r in cres], "base": [r["row"] for r in bres]},
        "totals": {"cand": C["tot"], "base": B["tot"] if B else None,
                   "cand_bb100": {"exact": bb100(ct["exact"], hands), "exact_raw": bb100(ct["exact_raw"], hands),
                                  "approx": bb100(ct["approx"], hands), "fe_est": bb100(sum(fe_c), hands),
                                  "live": bb100(ct["live_chips"], hands)},
                   "fe_est": {"cand": [len(fe_c), sum(fe_c)], "base": [len(fe_b), sum(fe_b)]},
                   "rc_est": {"cand": [len(rc_c), sum(rc_c)], "base": [len(rc_b), sum(rc_b)]}},
        "categories": {"cand": C["cats"], "cand_by_street": C["cat_st"], "base": B["cats"] if B else None,
                       "base_by_street": B["cat_st"] if B else None},
        "first_deviation": {"cand": C["first"], "base": B["first"] if B else None},
        "raise_size": {"cand": _size_stats(C["sizes"]), "base": _size_stats(B["sizes"]) if B else None},
        "cand_vs_base": cvb, "population_allfold": pop, "population_rivercall": popcall,
        "top": tops, "unknown_top": unks,
        "deviations": {"cand": [_nodump(f) for res in cres for f in res["firsts"]],
                       "base": [_nodump(f) for res in bres for f in res["firsts"]]},
        "shows": shows,
    }
    return L, console_cut, show_lines, err_lines, report


def main():
    ap = argparse.ArgumentParser(
        description="Candidate bot vs the LIVE bot on the real decision points of the real round logs "
                    "(see the module docstring for the method).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n"
               "  python3 replaydiff.py ../v10/bot.py --name v10_self          # noise floor of the live bot\n"
               "  python3 replaydiff.py ../v9/bot.py --base ../v10/bot.py\n"
               "  python3 replaydiff.py my_cand.py --base ../v10/bot.py --rounds 30-40 --show R33:512\n")
    ap.add_argument("cand", help="candidate bot file (defines class Agent)")
    ap.add_argument("--name", help="report name (default: folder name for bot.py, else the file stem)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--rounds", default="19-54",
                   help="counted rounds, e.g. 19-54 or 19-25,33 (default 19-54 = the rounds played by the live bot)")
    g.add_argument("--all", action="store_true", help="every log: practice + R1-R54")
    g.add_argument("--files", nargs="+", help="explicit round log files")
    ap.add_argument("--base", help="also replay this baseline bot (e.g. ../v10/bot.py, the live bot) "
                                   "and report (cand vs live) - (base vs live) per category")
    ap.add_argument("--procs", type=int, default=6, help="worker processes, parallel by round (max 6)")
    ap.add_argument("--show", nargs="*", default=[], metavar="R33:512",
                    help="print the candidate's decision trace for these hands")
    ap.add_argument("--seed", type=int, default=1,
                    help="seeds every random.Random of the bot module/agent per round (same for cand and base)")
    ap.add_argument("--size-tol", type=float, default=0.15,
                    help="raises count as the same if |cand - live| <= tol x live raise-to (default 0.15)")
    ap.add_argument("--top", type=int, default=25, help="largest deviations to list (default 25)")
    ap.add_argument("--dumps", type=int, default=0,
                    help="also print this many hand dumps on the console (all --top dumps go to the .txt)")
    ap.add_argument("--time-scale", type=float, default=1.0,
                    help="the bot's clocks run K times faster. K > 1 emulates a K-times slower sandbox (times are "
                         "then reported x K); K < 1 removes Monte Carlo deadline noise for exact cand/base "
                         "pairing (0.05 recommended for v10-derived candidates; do not use it with bots that "
                         "loop until a time budget is spent). Default 1")
    ap.add_argument("--enforce-time", action="store_true",
                    help="auto check/fold decisions over 25 ms or after a 10 s bank, as the dealer does")
    ap.add_argument("--out", default=OUT_DIR, help="output folder (default testbench/out)")
    a = ap.parse_args()

    cand = os.path.abspath(a.cand)
    base = os.path.abspath(a.base) if a.base else None
    for p in [cand] + ([base] if base else []):
        if not os.path.isfile(p):
            sys.exit("no such bot file: %s" % p)
    a.name = a.name or bot_name(cand)
    if a.procs > 6:
        print("note: --procs capped at 6 (shared machine)")
    a.procs = max(1, min(6, a.procs))
    files = select_files(a)
    if not files:
        sys.exit("no round logs selected")
    show = parse_show(a.show)
    jobs = []
    for f in files:
        jobs.append((f, "cand", cand, a.seed, a.size_tol, show, a.enforce_time, True, a.top, a.time_scale))
        if base:
            jobs.append((f, "base", base, a.seed, a.size_tol, show, a.enforce_time, False, a.top, a.time_scale))
    t0 = _real_time()
    results = []
    if a.procs == 1:
        for j in jobs:
            results.append(run_job(j))
            print("\r  %d/%d jobs  %.0fs" % (len(results), len(jobs), _real_time() - t0), end="", file=sys.stderr, flush=True)
    else:
        import multiprocessing as mp
        ctx = mp.get_context("spawn")
        with ctx.Pool(a.procs, maxtasksperchild=8) as pool:
            for res in pool.imap_unordered(run_job, jobs, chunksize=1):
                results.append(res)
                print("\r  %d/%d jobs  %.0fs" % (len(results), len(jobs), _real_time() - t0), end="", file=sys.stderr,
                      flush=True)
    print("", file=sys.stderr)
    wall = _real_time() - t0
    L, cut, show_lines, err_lines, report = build_report(a, cand, base, files, results, wall)
    console = L[:cut]
    if a.dumps:
        tops = report["top"][:a.dumps]
        console.append("hand dumps of the %d largest valued deviations" % len(tops))
        for i, f in enumerate(tops, 1):
            console += ["#%d %s" % (i, fmt_dev(f)), f.get("dump", ""), ""]
    if not a.dumps:
        console.append("(hand dumps of these deviations are in the .txt report; --dumps N prints N of them here)")
    print("\n".join(console + show_lines + err_lines))
    os.makedirs(a.out, exist_ok=True)
    stem = os.path.join(a.out, "replaydiff_%s" % re.sub(r"[^A-Za-z0-9_.-]+", "_", a.name))
    with open(stem + ".txt", "w") as fh:
        fh.write("\n".join(L + show_lines + err_lines) + "\n")
    with open(stem + ".json", "w") as fh:
        json.dump(report, fh, indent=1, default=str)
    print("saved %s.txt and %s.json" % (os.path.relpath(stem, HERE), os.path.relpath(stem, HERE)))


if __name__ == "__main__":
    main()
