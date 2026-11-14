"""
fuzz.py — game-state fuzzer / robustness gate.

Generates 1000+ states (real engine states, mutated/malformed states, and
hand-crafted edge cases) and calls decide() on each, asserting:
  - decide() returns a dict with a valid "action"
  - the action is legal for the state (no check when can_check is False;
    raise carries an integer amount)
  - decide() never raises an exception (it must swallow its own errors)
  - decide() returns within 2 seconds

A bot that auto-folds gracefully on a garbage state PASSES — the bar is
"never crash, never stall, never return an illegal action", not "play well
on nonsense".

Usage:
  python3 sandbox/fuzz.py bots/v0/bot.py
  python3 sandbox/fuzz.py bots/v0/bot.py --n 5000
"""
import argparse
import importlib.util
import json
import random
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.game import PokerEngine

RANKS = "23456789TJQKA"
SUITS = "shdc"
VALID_ACTIONS = {"fold", "check", "call", "raise", "all_in"}
TIMEOUT_S = 2.0


# ---------------------------------------------------------------------------
# Timeout wrapper (cross-platform, mirrors runner.py)
# ---------------------------------------------------------------------------

class _Timeout(Exception):
    pass


def _call_with_timeout(fn, arg, timeout_s):
    box = {"value": None, "error": None}
    done = threading.Event()

    def _worker():
        try:
            box["value"] = fn(arg)
        except BaseException as e:
            box["error"] = e
        finally:
            done.set()

    threading.Thread(target=_worker, daemon=True).start()
    if not done.wait(timeout_s):
        raise _Timeout()
    if box["error"] is not None:
        raise box["error"]
    return box["value"]


# ---------------------------------------------------------------------------
# State generation
# ---------------------------------------------------------------------------

def _full_deck():
    return [r + s for r in RANKS for s in SUITS]


def real_states(n_target):
    """Collect genuine action_request states from real engine play."""
    out = []
    seed = 0
    while len(out) < n_target:
        nplayers = random.choice([2, 3, 4, 5, 6])
        ids = [f"b{i}" for i in range(nplayers)]
        eng = PokerEngine(f"fuzz_{seed}", ids, dealer_seat=seed % nplayers, seed=seed)
        match_log = []
        state = eng.start_hand()
        steps = 0
        while state.get("type") == "action_request" and steps < 120:
            state["match_action_log"] = match_log[-200:]
            out.append(json.loads(json.dumps(state)))  # deep copy
            seat = state["seat_to_act"]
            # random legal-ish action to keep the hand moving
            roll = random.random()
            if state["can_check"]:
                act = {"action": "check"} if roll < 0.6 else {
                    "action": "raise", "amount": state["min_raise_to"]}
            elif roll < 0.5:
                act = {"action": "call"}
            elif roll < 0.8:
                act = {"action": "fold"}
            else:
                act = {"action": "raise", "amount": state["min_raise_to"] * 2}
            match_log.append({"hand_num": seed, "seat": seat, "bot_id": ids[seat],
                              "action": act["action"], "amount": act.get("amount")})
            state = eng.apply_action(seat, act)
            steps += 1
        seed += 1
    return out[:n_target]


def _base_state():
    deck = _full_deck()
    random.shuffle(deck)
    n_board = random.choice([0, 3, 4, 5])
    nplayers = random.choice([2, 3, 4, 5, 6])
    pot = random.choice([150, 300, 800, 2000, 5000, 19999])
    current_bet = random.choice([0, 100, 350, 1200])
    owed = random.choice([0, 50, current_bet, current_bet // 2 if current_bet else 0])
    stack = random.choice([0, 1, 50, 800, 9900, 9_999_999])
    players = []
    for i in range(nplayers):
        players.append({
            "seat": i, "bot_id": f"b{i}",
            "stack": random.choice([0, 100, 5000, 10000]),
            "state": random.choice(["active", "folded", "all_in", "busted"]),
            "is_folded": random.random() < 0.3,
            "is_all_in": random.random() < 0.2,
            "bet_this_street": random.choice([0, 100, 500]),
            "hole_cards": None,
        })
    return {
        "type": "action_request",
        "hand_id": "fuzz_x",
        "street": random.choice(["preflop", "flop", "turn", "river"]),
        "seat_to_act": 0,
        "pot": pot,
        "community_cards": deck[:n_board],
        "current_bet": current_bet,
        "min_raise_to": current_bet + 100,
        "amount_owed": owed,
        "can_check": owed == 0,
        "your_cards": deck[n_board:n_board + 2],
        "your_stack": stack,
        "your_bet_this_street": random.choice([0, 100, 500]),
        "players": players,
        "action_log": [],
        "match_action_log": [],
    }


def mutate(state):
    """Corrupt a state to test crash-resistance."""
    s = json.loads(json.dumps(state))
    mutation = random.choice([
        "drop_key", "wrong_type", "extreme_num", "bad_cards",
        "owed_gt_stack", "negative", "empty_lists", "none_values",
    ])
    if mutation == "drop_key" and s:
        k = random.choice(list(s.keys()))
        s.pop(k, None)
    elif mutation == "wrong_type":
        k = random.choice(["pot", "amount_owed", "your_stack", "street", "can_check", "your_cards"])
        s[k] = random.choice(["???", None, [], {}, 3.5, -1])
    elif mutation == "extreme_num":
        s[random.choice(["pot", "your_stack", "amount_owed", "min_raise_to"])] = random.choice(
            [0, -5, 10**12, 9_999_999])
    elif mutation == "bad_cards":
        s["your_cards"] = random.choice([[], ["Zz", "Xx"], ["As"], ["As", "As"], None])
    elif mutation == "owed_gt_stack":
        s["your_stack"] = 200
        s["amount_owed"] = 5000
        s["can_check"] = False
    elif mutation == "negative":
        s["pot"] = -100
        s["amount_owed"] = -50
    elif mutation == "empty_lists":
        s["players"] = []
        s["community_cards"] = []
    elif mutation == "none_values":
        s["min_raise_to"] = None
        s["current_bet"] = None
    return s


def edge_cases():
    """Hand-crafted nasty-but-specific spots."""
    cases = []
    # river with empty community (invalid but must not crash)
    cases.append({
        "type": "action_request", "hand_id": "e1", "street": "river",
        "seat_to_act": 0, "pot": 1000, "community_cards": [], "current_bet": 500,
        "min_raise_to": 1000, "amount_owed": 500, "can_check": False,
        "your_cards": ["As", "Kd"], "your_stack": 4000, "your_bet_this_street": 0,
        "players": [], "action_log": [], "match_action_log": [],
    })
    # amount_owed exactly equals stack (call = all-in)
    cases.append({
        "type": "action_request", "hand_id": "e2", "street": "turn",
        "seat_to_act": 0, "pot": 6000, "community_cards": ["2h", "7d", "Tc", "Ks"],
        "current_bet": 3000, "min_raise_to": 6000, "amount_owed": 3000, "can_check": False,
        "your_cards": ["Ah", "Ad"], "your_stack": 3000, "your_bet_this_street": 0,
        "players": [{"seat": 0, "bot_id": "b0", "stack": 3000, "state": "active",
                     "is_folded": False, "is_all_in": False, "bet_this_street": 0,
                     "hole_cards": None}],
        "action_log": [], "match_action_log": [],
    })
    # zero stack
    cases.append({
        "type": "action_request", "hand_id": "e3", "street": "preflop",
        "seat_to_act": 0, "pot": 300, "community_cards": [], "current_bet": 100,
        "min_raise_to": 200, "amount_owed": 100, "can_check": False,
        "your_cards": ["7c", "2d"], "your_stack": 0, "your_bet_this_street": 0,
        "players": [], "action_log": [], "match_action_log": [],
    })
    # empty everything
    cases.append({"type": "action_request"})
    cases.append({})
    # min_raise_to greater than stack
    cases.append({
        "type": "action_request", "hand_id": "e6", "street": "flop",
        "seat_to_act": 0, "pot": 400, "community_cards": ["As", "Kd", "Qc"],
        "current_bet": 100, "min_raise_to": 99999, "amount_owed": 100, "can_check": False,
        "your_cards": ["Js", "Ts"], "your_stack": 500, "your_bet_this_street": 0,
        "players": [], "action_log": [], "match_action_log": [],
    })
    return cases


def load_fixtures():
    fp = Path(__file__).parent / "fixtures" / "game_states.json"
    if fp.exists():
        try:
            return json.loads(fp.read_text())
        except Exception:
            return []
    return []


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------

def check_result(action, state):
    """Return an error string if the action is illegal, else None."""
    if not isinstance(action, dict):
        return f"not a dict: {type(action).__name__}"
    a = action.get("action")
    if a not in VALID_ACTIONS:
        return f"invalid action: {a!r}"
    if a == "check" and state.get("can_check") is False:
        return "checked when can_check is False"
    if a == "raise":
        if "amount" not in action:
            return "raise without amount"
        try:
            int(action["amount"])
        except (TypeError, ValueError):
            return f"raise amount not int: {action.get('amount')!r}"
    return None


def build_corpus(n):
    n_real = max(1, n // 3)
    real = real_states(n_real)
    mutated = [mutate(random.choice(real)) for _ in range(n // 3)]
    randoms = [_base_state() for _ in range(n - n_real - len(mutated))]
    corpus = real + mutated + randoms + edge_cases() * 5 + load_fixtures()
    random.shuffle(corpus)
    return corpus


def main():
    ap = argparse.ArgumentParser(description="Fuzz a bot's decide() for robustness")
    ap.add_argument("bot_path")
    ap.add_argument("--n", type=int, default=1200, help="approx number of states")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    random.seed(args.seed)

    spec = importlib.util.spec_from_file_location("fuzz_bot", args.bot_path)
    bot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bot)
    if not hasattr(bot, "decide"):
        print("FAIL: no decide()", file=sys.stderr)
        sys.exit(1)

    corpus = build_corpus(args.n)
    failures = []
    max_ms = 0.0
    n_timeout = 0

    for i, state in enumerate(corpus):
        t0 = time.perf_counter()
        try:
            action = _call_with_timeout(bot.decide, state, TIMEOUT_S)
        except _Timeout:
            n_timeout += 1
            failures.append((i, "TIMEOUT (>2s)", state))
            continue
        except Exception as e:
            failures.append((i, f"EXCEPTION: {type(e).__name__}: {e}", state))
            continue
        dt_ms = (time.perf_counter() - t0) * 1000
        max_ms = max(max_ms, dt_ms)
        err = check_result(action, state)
        if err:
            failures.append((i, f"ILLEGAL: {err} (returned {action})", state))

    total = len(corpus)
    passed = total - len(failures)
    print(f"\nFUZZ  {args.bot_path}")
    print(f"  states tested : {total}")
    print(f"  passed        : {passed}")
    print(f"  failed        : {len(failures)}  (timeouts: {n_timeout})")
    print(f"  max decide time: {max_ms:.2f} ms")

    if failures:
        print("\n  FAILURES (first 10):")
        for i, why, state in failures[:10]:
            snippet = {k: state.get(k) for k in ("street", "can_check", "amount_owed",
                                                 "your_stack", "your_cards") if k in state}
            print(f"   #{i}: {why}\n        state={snippet}")
        sys.exit(1)

    print("  ✅ no crashes, no timeouts, no illegal actions")
    sys.exit(0)


if __name__ == "__main__":
    main()
