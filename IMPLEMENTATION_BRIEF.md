# FullHouse Poker AI — Implementation Brief for Claude Code

> **For Claude Code (or any successor agent) executing this project from scratch.** This document is self-contained: it captures all design decisions, engine specifics, the validation methodology, the approved proposal set, and a 15-step implementation plan. You do not need any prior conversation history. Read this end-to-end before writing any code.

---

## 0. Project context

**The competition.** FullHouse Hackathon (sponsored by Quadrature Capital). 6-max No-Limit Texas Hold'em bots play in a Swiss-system online qualifier, top 64 advance to live finals.

**Timeline.**
- 31 May 2026 23:59 UTC — submission deadline
- 1 June 2026 — online qualifier (Swiss, multiple rounds, 400 hands per match, 6-bot tables, top 64 advance)
- 2 June 2026 — patch window: download hand histories as JSON, submit one updated bot
- 5 June 2026 — finals (single-elimination bracket)

**Goal.** Build a competitive bot that places top 64 in the qualifier and ideally wins the finals. Optimization target: cumulative chip delta across all qualifier matches (tiebreakers: fewer matches played, then best single-match delta).

**The single most important strategic insight.** Most competing bots will be LLM-generated, using similar standard architectures: 169-hand preflop charts, 33%/66%/pot bet sizing, pot-odds-based calling, GTO-flavored frequencies, weak multiway play. **The highest-leverage design move is orthogonal positioning** — pick approaches the modal LLM-built bot will not have anticipated. This is not about approximating GTO; it is about beating the modal LLM bot.

---

## 1. Engine specifications (must-read before writing code)

**Repo location.** Cloned at `/Users/ismailhakkikilic/Desktop/Fullhouse Poker AI/fullhouse-engine/`. Source of truth.

**File layout.**
```
fullhouse-engine/
├── engine/
│   ├── game.py            # PokerEngine class — game state, action validation, side pots
│   └── tournament.py      # Swiss pairing, standings, finalists
├── sandbox/
│   ├── match.py           # Match orchestrator — runs bots as subprocesses
│   ├── runner.py          # In-container runner — stdin/stdout protocol
│   ├── validator.py       # AST-based static checks + 4 runtime test states
│   └── Dockerfile         # python:3.10-slim + eval7 + numpy + scipy + treys + scikit-learn
├── bots/                  # Existing reference bots
│   ├── template/bot.py    # Premium pairs + basic pot odds
│   ├── aggressor/bot.py   # Raises constantly
│   ├── mathematician/bot.py  # Calls only when getting 3:1
│   ├── shark/bot.py       # Tight preflop, position-aware
│   └── ref_bot_2/bot.py   # Pot-odds caller
├── tests/test_engine.py
├── demo.py                # Local UI at http://localhost:5001
└── requirements.txt       # eval7, numpy, scipy, treys, scikit-learn, flask
```

**Submission format.** One file `bot.py` defining `def decide(game_state: dict) -> dict`. Optionally wrapped as `bot.zip` containing `bot.py` at root plus `data/` directory.
- `bot.py` max 5 MB
- `data/` max 200 MB total
- `data/` contains no `.py` files
- Total package max 250 MB

**The `decide(state)` contract.** Called once per action. Must return `dict` within 2 seconds. Return:
```python
{"action": "fold"}
{"action": "check"}                         # only when state["can_check"] == True
{"action": "call"}
{"action": "raise", "amount": 1200}         # amount = TOTAL bet, not raise-by
{"action": "all_in"}
```
Invalid/missing actions auto-fold. Raises below `state["min_raise_to"]` are snapped up. Crashes auto-fold for that hand (bot stays in tournament).

**Warmup call.** Before hand 1, the runner sends `{"type": "warmup"}` with a **30-second** budget. Use it to load blueprints / precompute tables. Bot must respond (the response is discarded). After warmup, the 2-second budget applies.

**Game state schema (every `action_request` you'll receive).** Verified against `engine/game.py::_build_state()`:
```python
{
  "type": "action_request",
  "hand_id": str,                          # e.g. "match_x_h0042"
  "street": str,                            # "preflop" | "flop" | "turn" | "river"
  "seat_to_act": int,                       # your seat (0..n-1)
  "pot": int,                               # total chips in pot
  "community_cards": list[str],             # e.g. ["As", "Td", "7h"] (empty preflop)
  "current_bet": int,                       # highest bet this street
  "min_raise_to": int,                      # minimum legal raise total
  "amount_owed": int,                       # chips you owe to call (0 = free check)
  "can_check": bool,                        # True iff amount_owed == 0
  "your_cards": list[str],                  # ["As", "Kh"] (rank then suit; suits: s/h/d/c)
  "your_stack": int,                        # your remaining chips
  "your_bet_this_street": int,              # chips you've put in this street
  "players": list[dict],                    # see below
  "action_log": list[dict],                 # actions THIS HAND
  "match_action_log": list[dict]            # actions THIS MATCH (last 200 entries)
}
```
`players[i]` shape:
```python
{
  "seat": int, "bot_id": str, "stack": int,
  "state": str,           # "active" | "folded" | "all_in" | "busted"
  "is_folded": bool, "is_all_in": bool,
  "bet_this_street": int,
  "hole_cards": None      # ALWAYS None for opponents — never revealed during play
}
```
Action log entries (both `action_log` and `match_action_log`):
```python
# action_log entries:
{"seat": int, "action": str, "amount": int}
# action types: "small_blind", "big_blind", "fold", "check", "call", "raise", "all_in"
# match_action_log entries additionally include:
{"hand_num": int, "seat": int, "bot_id": str, "action": str, "amount": int}
```

**Critical engine facts (do not get these wrong).**

1. **Starting stack 10,000. Blinds 50/100.** So starting effective is 100bb. Deep enough that postflop matters.
2. **`match_action_log` is truncated to 200 entries** (see `match.py::MATCH_LOG_MAX_ENTRIES = 200`). With 6 bots and ~5 actions per hand, that's only 5–10 hands of rolling history. **You MUST maintain incremental stats in module globals** rather than reparse the log each call. Track `_last_seen_log_index` and only process new entries.
3. **Module globals persist across all 400 hands of a single match.** One `BotProcess` lives for the whole match. Opponent stats keyed by `bot_id` accumulate.
4. **Module globals do NOT persist across matches.** Each match is a fresh subprocess. There is **no cross-match memory** possible by design (read-only filesystem, no writes ever, fresh process).
5. **You never see opponent hole cards during play.** The engine reveals cards in the `hand_complete` payload, but that goes to the match orchestrator, not to your bot. Range estimation must be **action-only** — no showdown reveals are visible to `decide()`.
6. **stderr is captured but not exposed to the bot.** It can't be used as a back-channel.
7. **Heads-up rules differ.** When 2 active players: dealer is SB, SB acts first preflop, BB first postflop. Relevant when matches go short-handed.
8. **Action mapper forgiveness.** Engine snaps below-minimum raises up to `min_raise_to`, converts oversize raises to all_in. So we have some safety, but should produce clean actions.

**Tournament tiebreakers (`engine/tournament.py::compute_standings()`).** Sorted by:
1. cumulative_delta DESC (primary)
2. matches_played ASC (fewer matches with same delta = stronger)
3. best_match_delta DESC
4. bot_id ASC (alphabetic)

**Forbidden imports (`sandbox/validator.py::FORBIDDEN_MODULES`).** Hard rejection at submission:
```
socket, urllib, urllib2, urllib3, requests, httpx, aiohttp, http,
ftplib, smtplib, telnetlib, xmlrpc,
subprocess, multiprocessing,
pickle, shelve,
threading, asyncio,
ctypes,
runpy, importlib
```
**Implications:**
- Cannot use joblib for sklearn model loading (joblib uses pickle internally and sklearn ships with joblib). **Train sklearn models offline, manually extract numpy arrays, ship in `.npz`.** Write tiny pure-numpy inference functions.
- Cannot roll own timeout watchdog. Use `time.time()` checkpoints inside `decide()` to bail to fallback when budget exceeded.
- Cannot pickle blueprints. Use `.npz` / `.npy` / `.json` / plain bytes.

**Forbidden call patterns.** `eval(`, `exec(`, `compile(`, `__import__(`, `getattr(__builtins__`, `__builtins__[...]`, all `os.system/popen/exec*/spawn*/fork/kill/remove/unlink/rmdir/chmod/chown/rename/replace`, and `subprocess.*`. AST-checked.

**Available libraries.** `eval7`, `numpy`, `scipy`, `treys`, `scikit-learn`. eval7 is the same library MIT uses and is very fast for hand evaluation and Monte Carlo equity.

---

## 2. Strategic philosophy

These three principles override every implementation decision. When in doubt, re-read them.

**Principle 1 — Build the strongest simple mathematical bot, then make it adaptive.** Do not build a fragile research prototype. The bot must never crash, never timeout, never return an illegal action — these are non-negotiable. Strategic sophistication comes second.

**Principle 2 — Validate every addition with paired-seed differential testing.** The only honest way to know if a change helped is to compare two versions on identical seeds. Unpaired comparisons are noise. Without this discipline you will fall into the well of complexity and ship a bot worse than its predecessor.

**Principle 3 — Position orthogonally to the LLM-built field.** Most competitors will use predictable architectures. Deliberately pick design choices the modal LLM bot won't anticipate: irregular bet sizings, proper multiway tightening, anti-overfold exploitation, blocker-aware bluff-catching.

**Anti-patterns to refuse.**
- Building a deep enumerated archetype detector ("aggressive type A vs type B vs C") — use continuous stats with bounded perturbation
- Trying to "out-aggressive" aggressors — pick off bluffs at correct frequency instead
- Solving full multi-street CFR — infeasible in this timeframe
- Hand-coding special cases per opponent — use parametric adjustments
- Adding any feature that doesn't clearly pass paired-seed validation

---

## 3. Architecture overview

**Runtime flow:**
```
game_state arrives
    ↓
parse_state                          # extract structured fields
    ↓
update_opponent_memory               # incremental match_action_log consumer (P18)
    ↓
build_infoset                        # abstract state into bucket key
    ↓
lookup_blueprint(infoset)            # mixed strategy from precomputed table
    ↓
fallback_chain if missing            # exact → coarse → street → emergency
    ↓
opponent_perturbation                # bounded λ-blend (gated by Bayesian CI + entropy)
    ↓
optional: eval7_equity_verify        # for flagged uncertain spots (P19)
    ↓
optional: river_lp_solver            # HU large-pot rivers only (P25)
    ↓
sample_mixed_action                  # deterministic seed: hash(hand_id, bot_id, street) (P21)
    ↓
map_to_legal_action                  # adversarial sizing (P1), safety bounds
    ↓
safety_check
    ↓
return action
```

**Module-level state (persists per match):**
```python
# Loaded at import time:
BLUEPRINT_PREFLOP = ...   # numpy arrays from data/
BLUEPRINT_POSTFLOP = ...
EQUITY_VS_RANGE = ...     # P34 precomputed table
LR_W_GLOBAL = ...         # P26 logistic regression coefficients

# Persisted across hands:
OPPONENT_STATS = {}       # {bot_id: {stat_name: Beta(α,β), ...}}
LR_W_DELTA = {}           # {bot_id: numpy.ndarray of per-opponent corrections} (P30)
HAND_COUNTER = 0
LAST_LOG_INDEX = 0        # for incremental match_action_log consumption (P18)
```

**Layered exploit system.**
1. Blueprint (always): hand-crafted mixed strategies indexed by infoset
2. Multiway adjustment (when n_opp > 1): rule-based shrinkage tables + optional eval7 best-of-N equity
3. Opponent perturbation (when stats are confident): bounded λ-blend toward exploit distribution
4. LR-driven bet sizing (when applicable): EV-optimized size from fold predictor
5. River LP resolver (when conditions met): exact Nash for HU large-pot rivers
6. Safety net: emergency fallback that always returns a legal action

---

## 4. Approved proposals (the design backlog)

Each proposal is annotated **(version-N)** with the version it lands in, plus status.

| ID | Proposal | Status | Lands in |
|----|----------|--------|----------|
| P1 | Adversarial bet sizing (irregular percentages) | Accepted | v5 |
| P2 | Meta-classifier of LLM-built bots | **Rejected** (too expensive, low ROI) | — |
| P3 | Pre-built exploit library by archetype | Deferred | post-baseline if time |
| P4 | Limp-trap branches in preflop | End (conservative use) | v11+ if time |
| P5 | Donk-bet branches OOP | End (conservative use) | v11+ if time |
| P6 | Range-vs-range decisioning | Deferred | post-baseline if time |
| P7 | Showdown-based range learning | **Modified — not feasible** (no card reveals during play); action-only inference folds into P8 | v4 |
| P8 | Per-opponent bet-size frequency profile | Accepted | v4 |
| P9 | Multiway-specific blueprint | Accepted | v6 |
| P10 | Blocker-aware river decisions | Accepted | v7 |
| P11 | Game-state fuzzer | Accepted | Phase 1 tooling |
| P12 | Time-budget checkpoints (soft 800ms, not 200ms) | Accepted | v11 |
| P13 | Deterministic mixed-strategy sampling | Accepted | v11 (with P21) |
| P14 | stderr backchannel for hand history | **Rejected — not feasible** (stderr discarded by match runner) | — |
| P15 | Score-aware aggression (gentle) | Accepted | v11 |
| P16 | Stack-leader exploitation | Deferred | post-baseline if time |
| P17 | LLM-style enemy zoo (12 bots) | Accepted | Phase 1 tooling |
| P18 | Incremental match_action_log consumer | Accepted | v4 (core infrastructure) |
| P19 | Runtime eval7 Monte Carlo equity | Accepted | v3 |
| P20 | Heads-up branch | Accepted | v9 |
| P21 | Hash-seeded deterministic mixing | Accepted | v11 |
| P22 | Validator smoke test as pre-commit gate | Accepted | Phase 1 tooling |
| P23 | scipy.stats.beta Bayesian opponent stats | Accepted | v4 |
| P24 | scipy binomial CI adaptive Monte Carlo | Accepted | v3 |
| P25 | scipy.optimize.linprog river subgame solver | Accepted (conditional) | v10 |
| P26 | sklearn LogisticRegression fold predictor (offline) | Accepted | v8 |
| P27 | sklearn KMeans for board buckets | Optional | only if hand-crafted buckets leak |
| P28 | DecisionTree blueprint compressor | Optional | only if blueprint storage unwieldy |
| P29 | scipy.stats.entropy as exploitation gate | Accepted | v4 |
| P30 | Online per-opponent fold-predictor fine-tuning | Accepted | v8 |
| P31 | Online delta on Bayesian priors themselves | Deferred | post-baseline if time |
| P32 | Variance-adjusted calling buffer for high-variance all-ins | Accepted | v4 |
| P33 | Bluff-propensity stat (follow-through proxy) | Accepted | v4 |
| P34 | Precomputed equity-vs-range table | Accepted | v3 |

---

## 5. The 15-step implementation plan

Each step has: **build**, **validate**, **pass criteria**, **revert plan**. Steps progress strictly in order. Do not start step N+1 until step N has passed its gates.

### Phase 1 — Foundation (Day 1 morning, ~6 hours)

#### Step 1 — Environment, repo, smoke baseline
**Build:**
- Confirm repo at `fullhouse-engine/` is intact.
- Install dependencies on the user's machine per README:
  ```bash
  pip3 install "Cython<3"
  pip3 install --no-build-isolation eval7==0.1.7
  pip3 install flask numpy scipy treys scikit-learn
  ```
- Run engine tests: `python3 tests/test_engine.py` — all should pass.
- Run 1 reference match: `python3 sandbox/match.py bots/shark/bot.py bots/aggressor/bot.py --hands 50`. Should complete without errors.
- Capture 3–5 real `game_state` examples via a verbose match for use as fixtures.

**Validate:** Engine tests pass; reference match completes; fixtures saved.
**Pass:** Tournament infrastructure works locally.
**Revert plan:** Environment issues — fix incrementally, do not proceed without working env.

#### Step 2 — Validation infrastructure
Three deliverables, all in `fullhouse-engine/sandbox/` or `fullhouse-engine/bots/enemy_zoo/`:

**2a. `bench.py` (paired-seed comparison runner).** Takes (botA, botB, opponents, n_seeds). For each seed, runs (botA + opponents) and (botB + opponents) using `--seed`. Outputs per-seed deltas, paired t-test p-value, median/p5/p95 deltas, mean decision time, crash/timeout/invalid counts. Target: 30-seed comparison completes in <10 minutes.

**2b. `fuzz.py` (game-state fuzzer).** Generates 1000+ randomized and edge-case states: malformed fields (missing keys, wrong types), weird stacks (0, 1, 9_999_999), mid-betting (`amount_owed` close to `your_stack`), all-in spots, empty `community_cards` on river (invalid but should not crash bot), `players` lists of varying sizes (2..6). Calls `decide()` on each, asserts: result is dict with valid action, action is legal for that state, no exception raised, returns within 2s. Run as pre-commit gate.

**2c. Enemy zoo at `bots/enemy_zoo/`.** 12 caricature bots, ~50–100 lines each:

*Tuning half (looked at during development):*
- `always_call` — calls every bet, never folds, never raises
- `min_raise_spammer` — always min-raises preflop, calls postflop
- `nit_preflop` — only plays QQ+/AK preflop, plays straightforwardly postflop
- `overbet_river_bluffer` — checks/calls flop/turn, overbets river ~30% of the time as bluff
- `aggressive_3bettor` — 3-bets preflop ~25% of hands
- `fit_or_fold` — checks/folds postflop unless hits top pair or better

*Held-out half (only used for generalization check, never tuned against):*
- `tight_value_only` — only bets/raises with strong made hands
- `loose_passive_call_station` — VPIP 80%, never raises postflop
- `polarized_bettor` — bets pot with strong hands or pure bluffs, checks medium
- `short_stack_jammer` — limps preflop with everything, jams river
- `weird_sizing` — uses unusual bet sizes (37%, 88%, 113% pot)
- `mixed_llm_caricature` — deliberately designed to look like generic GPT-style bot (33%/66%/pot sizing, c-bet 70%, pot-odds calling, linear value betting)

**Validate:** `bench.py` produces sensible output with 2 reference bots. `fuzz.py` passes on `bots/template/bot.py`. Enemy zoo bots load and play a 6-bot match together without errors.
**Pass:** All three tools work end-to-end. Critical — everything downstream depends on these.
**Revert plan:** Cannot proceed without working tools. Fix immediately.

#### Step 3 — v0 baseline ("cannot die")
**Build:** `bots/v0/bot.py`, ~80 lines.

**Preflop logic:**
- Premium pairs (AA, KK, QQ, JJ): raise 3x `min_raise_to`
- Strong aces (AKs, AKo, AQs): raise 2.5x `min_raise_to` if first in, call if facing one bet, fold to 3-bet
- All other hands: check if free, fold otherwise

**Postflop logic:**
- Check if free
- Call if `pot / amount_owed >= 3` (pot odds 3:1 or better)
- Fold otherwise

**Safety layer (mandatory in EVERY version):**
```python
def emergency_fallback(state):
    if state.get("can_check"):
        return {"action": "check"}
    return {"action": "fold"}

def map_to_legal_action(intended, state):
    """Ensure intended action is legal; coerce or fallback."""
    a = intended.get("action")
    if a == "check" and not state.get("can_check"):
        return {"action": "fold"}
    if a == "raise":
        amt = intended.get("amount", 0)
        min_r = state["min_raise_to"]
        max_r = state["your_stack"] + state["your_bet_this_street"]
        if amt >= max_r:
            return {"action": "all_in"}
        amt = max(amt, min_r)
        return {"action": "raise", "amount": amt}
    if a in ("fold", "call", "all_in"):
        return {"action": a}
    return emergency_fallback(state)

def decide(state):
    if state.get("type") == "warmup":
        return {"action": "check"}
    try:
        # ... strategy logic returns `intended`
        return map_to_legal_action(intended, state)
    except Exception:
        return emergency_fallback(state)
```

**Validate:**
- `python3 sandbox/validator.py bots/v0/bot.py` — must pass
- `python3 fuzz.py bots/v0/bot.py` — zero crashes, zero invalid actions
- `bench.py bots/v0/bot.py bots/template/bot.py --opponents bots/template,bots/aggressor,bots/mathematician,bots/shark,bots/ref_bot_2 --seeds 30` — establish baseline numbers

**Pass:** Zero crashes, zero timeouts, zero invalid actions. Loses small to `shark`, roughly breaks even with `template`/`ref_bot_2`, beats `aggressor` and `mathematician`. These numbers become the floor every later version is measured against.

**Revert plan:** Edge case in action mapper — debug against specific failing fuzz state.

### Phase 2 — Strategic core (Day 1 afternoon + Day 2 morning, ~18 hours)

#### Step 4 — v1: hand-crafted preflop blueprint
**Build:** `bots/v1/bot.py` extends v0.

Add positional opening ranges for all 6 seats (UTG/HJ/CO/BTN/SB/BB), 3-bet ranges, 4-bet ranges, call-vs-3-bet, blind defense. Short-stack push/fold table for sub-15bb effective. Use the 169 canonical hand classes (AA…22, AKs…32s, AKo…32o).

The ranges should be **hand-crafted by an experienced poker player** (the user). The bot author scaffolds the lookup structure:

```python
PREFLOP_OPEN_RANGES = {
    'UTG': {'AA', 'KK', 'QQ', 'JJ', 'TT', '99', 'AKs', 'AKo', 'AQs', 'AQo', 'AJs', 'KQs'},
    'HJ':  {...},  # wider
    'CO':  {...},  # wider still
    'BTN': {...},  # widest
    'SB':  {...},
    'BB':  {...},
}

PREFLOP_3BET_RANGES = {
    ('BTN', 'UTG'): {'AA', 'KK', 'QQ', 'AKs', 'AKo'},   # tight against UTG
    ('BTN', 'CO'):  {...},  # wider
    # ... etc
}
```

Plus: short-stack jam/call/fold tables indexed by (hand_class, effective_stack_bb, position, n_to_act).

Postflop stays v0 logic for now.

**Validate:** `bench.py` paired-seed v1 vs v0 against each reference bot, 30 seeds each.
**Pass:** Beats v0 (p<0.05, positive median delta) AND positive median delta vs every reference bot AND beats `shark` for the first time.
**Revert plan:** Inspect specific lost hands → adjust ranges → re-test.

#### Step 5 — v2: postflop blueprint
**Build:** `bots/v2/bot.py` extends v1.

Add encoders:
- **Hand-strength bucket** (12 buckets): air, weak_showdown, third_pair_or_underpair, second_pair, weak_top_pair, strong_top_pair, overpair, two_pair, set_or_trips, straight, flush, full_house_or_better
- **Board-texture bucket** (~10 buckets): A_high_dry, K_high_dry, paired, monotone, two_tone, connected, low_connected, broadway_connected, disconnected_low, draw_completed
- **Draw bucket**: no_draw, backdoor, weak_draw, gutshot, OESD, flush_draw, combo_draw, nut_draw
- **SPR bucket** (5 buckets): <1, 1–3, 3–6, 6–10, ≥10
- **Position**: IP, OOP, sandwiched
- **Facing action**: checked_to, facing_small, facing_half, facing_pot, facing_overbet, facing_raise

Build infoset key as concatenation. Lookup tables map infoset → mixed strategy over abstract actions. Action abstraction:
- For betting: check/call, bet_33, bet_66, bet_100, bet_150, all_in
- For facing: fold, call, raise_2.5x, raise_pot, raise_all_in

**Nested fallback chain (critical for coverage):**
1. exact_infoset
2. drop facing_action (use most common)
3. drop SPR (use middle bucket)
4. drop board_texture (use generic)
5. street_default (street-wide default mix)
6. emergency_fallback

Track and log fallback-hit-rate during validation.

**Validate:** `bench.py` paired v2 vs v1. Monitor fallback hit rate — must be **<5%**.
**Pass:** Beats v1, fallback rate <5%, p99 decision time <300ms.
**Revert plan:** Fill in missing blueprint entries → re-test. Don't proceed with high fallback rate.

#### Step 6 — v3: eval7 equity layer + P34 equity-vs-range table
**Build:** `bots/v3/bot.py` extends v2.

At module import (warmup time), precompute equity-vs-range table:
- Dimensions: 169 hand classes × 5 opponent counts (1..5) × 6 range tightness buckets (100%, 80%, 60%, 40%, 25%, 15%)
- Store as numpy array, ~20KB
- Either compute at warmup (30s budget allows) or precompute offline and ship in `data/`

Runtime adaptive Monte Carlo using eval7 + scipy binomial CI for early stopping (P24):
- Batches of 200 rollouts
- Compute Wilson CI on win rate
- Stop when CI half-width <2 percentage points
- Hard cap: 5000 rollouts or 150ms, whichever first
- Fire only on "blueprint uncertain" spots: rivers facing bets, multiway flop value decisions, close turn calls

**Validate:** `bench.py` paired v3 vs v2. Watch decision time distribution carefully.
**Pass:** Beats v2 with no timeout regressions. p99 decision time stays under 600ms.
**Revert plan:** Restrict equity firing to fewer spots (only river facing bet, only very large pots). **High overfit risk** — if v3 vs v2 paired result is noisy, default to revert and keep v2.

#### Step 7 — v4: opponent modeling layer
**Build:** `bots/v4/bot.py` extends v3.

**Per-opponent tracker (module global, keyed by `bot_id`):**
```python
from scipy.stats import beta

OPPONENT_STATS = {}  # {bot_id: {stat_name: (alpha, beta), ...}}

PRIORS = {
    'vpip':            (25, 75),   # 25% prior
    'pfr':             (15, 85),   # 15% prior
    'fold_to_cbet':    (55, 45),   # 55% prior
    'fold_to_3bet':    (60, 40),
    'cbet_frequency':  (60, 40),
    'check_raise_freq':(8, 92),
    'shove_frequency': (2, 98),    # maniac detection
    'bluff_propensity':(30, 70),   # follow-through proxy (P33)
}

def update_stat(bot_id, stat, success):
    """Beta conjugate update."""
    if bot_id not in OPPONENT_STATS:
        OPPONENT_STATS[bot_id] = {k: list(v) for k, v in PRIORS.items()}
    a, b = OPPONENT_STATS[bot_id][stat]
    if success:
        OPPONENT_STATS[bot_id][stat][0] = a + 1
    else:
        OPPONENT_STATS[bot_id][stat][1] = b + 1

def stat_mean(bot_id, stat):
    if bot_id not in OPPONENT_STATS:
        a, b = PRIORS[stat]
    else:
        a, b = OPPONENT_STATS[bot_id][stat]
    return a / (a + b)

def stat_ci(bot_id, stat, conf=0.90):
    if bot_id not in OPPONENT_STATS:
        a, b = PRIORS[stat]
    else:
        a, b = OPPONENT_STATS[bot_id][stat]
    return beta.interval(conf, a, b)  # (lo, hi)
```

**Incremental match_action_log consumer (P18):**
```python
LAST_LOG_INDEX = 0
HAND_STATE = {}  # tracks per-hand context for stat updates

def update_opponent_memory(state):
    global LAST_LOG_INDEX
    log = state.get('match_action_log', [])
    for entry in log[LAST_LOG_INDEX:]:
        # update stats based on entry
        # increment appropriate (alpha, beta) for relevant bot_id
        ...
    LAST_LOG_INDEX = len(log)
```
Note: when `len(log)` resets (which it can if log was truncated), reset `LAST_LOG_INDEX = 0` and reprocess.

**Bluff-propensity stat (P33):** Track ratio of (aggressive action → subsequently folded to resistance) / (total aggressive actions). High ratio = bluffer; low = value-heavy. Use as predictor feature and as gate for "call lighter vs bluffers."

**Bounded λ-blend perturbation:**
```python
def perturb_strategy(blueprint_dist, opp_id):
    # Compute exploit_dist based on stats
    exploit_dist = build_exploit(opp_id)
    # Confidence factor: higher with tighter CI, higher entropy of opp action dist
    lam = compute_lambda(opp_id)  # bounded in [0, 0.3]
    return (1 - lam) * blueprint_dist + lam * exploit_dist
```

**Confidence gating via scipy.stats.entropy (P29) and CI tightness:**
- λ = 0 if fewer than 10 hands of data
- λ scales up with (1 - CI_width) and (1 - opp_entropy)
- Hard cap: λ ≤ 0.3

**Variance-adjusted calling buffer (P32):** When facing an all-in and equity is close to break-even AND bet covers >25% of remaining stack, require equity ≥ break_even + 3–5 percentage points. Premium scales down to zero as CI on opponent's range tightens and as pot odds get very favorable.

**Validate:** `bench.py` paired v4 vs v3 against the **tuning enemy zoo specifically** (reference bots are too few opponents for modeling gains to show in 400 hands).
**Pass:** Beats v3 against tuning enemy zoo; doesn't regress against reference bots.
**Revert plan:** Lower λ cap and CI threshold → re-test. If still no gain, perturbation logic broken — revert.

### Phase 3 — Tactical exploits (Day 2 afternoon, ~8 hours)

#### Step 8 — v5: adversarial bet sizing (P1)
**Build:** `bots/v5/bot.py` extends v4.

Bet-size translator. Where v4 blueprint outputs "bet_33" / "bet_66" / "bet_100", v5 substitutes irregular sizes:
```python
SIZE_MAP = {
    'bet_33':  0.29,   # was 0.33
    'bet_66':  0.71,   # was 0.66
    'bet_100': 1.13,   # was 1.00
    'bet_150': 1.87,   # was 1.50
}
```
Computed bet = `int(SIZE_MAP[abstract] * pot)` then clamped to legal range by `map_to_legal_action`. ~20 lines layered on top of action mapper.

**Validate:** `bench.py` paired v5 vs v4.
**Pass:** Beats v4 OR is statistically neutral with no robustness regressions. Acceptance is "doesn't lose" — gains show up against the real field, not our test bots.
**Revert plan:** If we lose to v4, irregular sizes are confusing our own subsequent logic — debug; otherwise keep.

#### Step 9 — v6: multiway blueprint (P9)
**Build:** `bots/v6/bot.py` extends v5.

**Layer 1 — Rule-based shrinkage (always on, cheap):**
```python
N_OPP_ADJUSTMENTS = {
    1: {'value_threshold': 0.50, 'bluff_freq_mult': 1.0, 'size_mult': 1.0, 'call_threshold': 0.40},
    2: {'value_threshold': 0.60, 'bluff_freq_mult': 0.3, 'size_mult': 0.85, 'call_threshold': 0.45},
    3: {'value_threshold': 0.70, 'bluff_freq_mult': 0.05, 'size_mult': 0.75, 'call_threshold': 0.50},
    4: {'value_threshold': 0.75, 'bluff_freq_mult': 0.02, 'size_mult': 0.70, 'call_threshold': 0.55},
    5: {'value_threshold': 0.80, 'bluff_freq_mult': 0.0, 'size_mult': 0.65, 'call_threshold': 0.60},
}
```
Applied as adjustments to v5 blueprint output when `n_active_opponents > 1`.

**Layer 2 — eval7 best-of-N equity (selective, P34):**
Use precomputed equity-vs-range table from Step 6. Fires on multiway value bets and calls when (pot > 1500 chips) AND (time budget remaining > 300ms). Verifies blueprint decision against actual equity-vs-best-of-N.

Layer 3 (multiway bluff probability via independent opponent fold rates) — only if Layers 1+2 pass cleanly.

**Validate:** `bench.py` paired v6 vs v5 in **6-bot mass simulations** (multiway pots only happen with full tables). 50 paired tournament-style sims.
**Pass:** Beats v5 in 6-bot sims, no regression in HU paired matches.
**Revert plan:** If v6 loses, drop Layer 2 (keep Layer 1) and re-test. Layer 1 alone is plausibly enough.

#### Step 10 — v7: blocker-aware river overrides (P10)
**Build:** `bots/v7/bot.py` extends v6.

River-only decision override. For (board, hero hand class, opponent action) tuple, small hand-crafted table indicating whether hero's specific blockers (e.g., having the Ace of spades on a 4-flush board) shift the decision toward bluff/call/fold. ~150 entries covering common river spots:
- Ace-blocker on board with flush completed → more bluff-suitable (blocks nut flush)
- Holding the straight-completing card → less bluff-suitable
- King-blocker vs polar 4-bet range → more bluff-catch worthy

**Validate:** `bench.py` paired v7 vs v6. Effect will be small (river spots rare).
**Pass:** Beats v6 by even small positive margin OR neutral with no robustness regressions.
**Revert plan:** If neutral, keep (safe addition). If lose, the lookup logic is wrong — debug.

### Phase 4 — Advanced features (Day 3 morning, ~6 hours)

#### Step 11 — v8: LR fold predictor + online per-opponent fine-tuning (P26 + P30)
**Build:** `bots/v8/bot.py` extends v7.

**Offline training:**
- Generate ~50,000 (state, action) tuples from running v7 vs the **tuning enemy zoo** under varied seeds
- Feature vector for each opponent decision point: `[street_onehot(4), pot_size_normalized, our_relative_bet_size, board_texture_onehot(10), our_position_onehot(6), action_history_hash_buckets(8)]` — ~30 features
- Target: did opponent fold? (binary)
- Train sklearn `LogisticRegression(C=1.0, solver='lbfgs', max_iter=1000)`
- **Extract `model.coef_` and `model.intercept_` as numpy arrays**, save to `data/lr_fold_predictor.npz`
- DO NOT use joblib (pickle forbidden). Manual extraction only.

**Runtime inference (pure numpy, no sklearn import):**
```python
import numpy as np

LR_DATA = np.load(os.path.join(BOT_DATA_DIR, 'lr_fold_predictor.npz'))
W_GLOBAL = LR_DATA['coef']        # shape (n_features,)
B_GLOBAL = LR_DATA['intercept']   # scalar
W_DELTA = {}                       # per-opponent online corrections

def predict_fold_prob(features, opp_id):
    delta = W_DELTA.get(opp_id, np.zeros_like(W_GLOBAL))
    logit = (W_GLOBAL + delta) @ features + B_GLOBAL
    return 1.0 / (1.0 + np.exp(-logit))

def online_update(opp_id, features, actual_fold):
    """Regularized SGD step on per-opponent delta only."""
    if opp_id not in W_DELTA:
        W_DELTA[opp_id] = np.zeros_like(W_GLOBAL)
    pred = predict_fold_prob(features, opp_id)
    grad = (pred - actual_fold) * features
    LR = 0.02
    LAMBDA = 0.01
    W_DELTA[opp_id] -= LR * (grad + LAMBDA * W_DELTA[opp_id])
```

**Filters for online updates (P30):** Only update when (bet size is within training distribution range) AND (opponent had a genuine choice — not pot-committed, not blind-posted).

**Bet sizing as EV optimization:**
For a list of candidate sizes (e.g., 25%, 50%, 75%, 100%, 150% pot), compute expected EV using:
```
EV(size) = P(fold | size) * (current_pot)
        + (1 - P(fold | size)) * (equity * (pot + size) - (1 - equity) * size)
```
Pick the size maximizing EV.

**Validate:**
1. `bench.py` paired v8 vs v7 against **tuning enemy zoo** — must win significantly
2. `bench.py` paired v8 vs v7 against **held-out enemy zoo** — must not regress
3. Doesn't regress against reference bots

**Pass:** All three conditions met. This is where overfitting risk is highest.
**Revert plan:** If beats tuning but loses held-out: overfit — reduce LR (0.02 → 0.005), increase λ (0.01 → 0.05), retrain offline weights with more synthetic opponents, retry. If loses tuning too: predictor broken; debug.

#### Step 12 — v9: heads-up branch (P20)
**Build:** `bots/v9/bot.py` extends v8.

Detect `len([p for p in state['players'] if p['state'] in ('active', 'all_in')]) == 2`.

When HU is active:
- HU-specific preflop ranges (much wider — dealer is SB; SB opens ~70%+ of hands, BB defends 60%+)
- HU position handling: dealer = SB, SB acts first preflop, BB first postflop
- Postflop adjustments: tighter c-betting on wet boards, wider call-down ranges, more aggressive donk-bets when checked to as BB

**Validate:** `bench.py` paired v9 vs v8. Construct synthetic short-handed scenarios (start matches with one bot already busted, or with very short stacks that bust early in match).
**Pass:** Beats v8 in HU/short-handed situations, neutral or better in 6-bot.
**Revert plan:** HU ranges miscalibrated → adjust → retry. Or simplify to "use v8 blueprint with HU position mapping."

### Phase 5 — Finalization (Day 3 afternoon, ~6 hours)

#### Step 13 — v10: river LP subgame solver (P25, conditional)
**Build:** `bots/v10/bot.py` extends v9.

`scipy.optimize.linprog`-based exact Nash solver for HU river spots.
- Inputs: hero range (estimated from action history), villain range, small action set (e.g., check/call, bet_33, bet_pot, all_in)
- Formulate as standard 2-player zero-sum LP, solve
- Output: mixed strategy for hero

Fires only when ALL conditions met:
- HU pot (n_active_opponents == 1)
- Street == 'river'
- Pot > 2000 chips
- Time budget remaining > 400ms
- Blueprint indicates non-trivial decision

**Validate:** `bench.py` paired v10 vs v9 in HU situations + stress-test with hand-crafted complex river spots.
**Pass:** Beats v9 in HU AND **zero timeout regressions** (critical).
**Revert plan:** If timeouts increase even slightly, revert. **Skip and move to step 14** if at any time v10 looks risky — v10 is a bonus, not required.

#### Step 14 — v11/v12: final hardening and freeze
**Build:** `bots/v11/bot.py` extends v10 (or v9 if v10 skipped). Three additions:

**Score-aware aggression (P15):** Mild adjustment based on `hands_remaining` and `our_stack / starting_stack`. Behind late in match → +5% aggression. Ahead late → -5% aggression. Bounded to ±10%.

**Time-budget checkpoints (P12):** Staged `decide()` with `time.time()` checks between stages:
```python
def decide(state):
    t0 = time.time()
    BUDGET = 0.8  # 800ms soft budget

    parsed = parse_state(state)
    if time.time() - t0 > BUDGET: return emergency_fallback(state)

    # ... blueprint lookup (cheap)

    if time.time() - t0 > BUDGET: return action_from_blueprint(...)

    # ... eval7 equity (expensive)
    # ... LP solver (expensive)

    return final_action
```

**Deterministic mix sampling (P21):**
```python
import hashlib

def sample_mixed(dist, hand_id, bot_id, street):
    seed_str = f"{hand_id}|{bot_id}|{street}"
    h = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)
    rng = np.random.default_rng(h)
    return rng.choice(len(dist), p=dist)
```

**Then v12 is the freeze:**
- Run full benchmark at scale: 100+ paired matches against every reference bot, full tuning enemy zoo, full held-out enemy zoo
- Compute robust score: `median - 0.25 * p5`
- Pick the version (v11 or earlier) with highest robust score
- Stress test with `fuzz.py` at 10x volume
- Run `validator.py` one final time
- Package submission as `bot.zip` with `bot.py` + `data/`
- Confirm submission size limits: bot.py ≤ 5MB, data/ ≤ 200MB, total ≤ 250MB

**Validate:** Final candidate has highest robust score, zero crashes, zero timeouts, zero invalid actions across all benchmark matches.
**Pass:** Submission package validated. Upload to portal.fullhousehackathon.com.
**Revert plan:** If hardening introduces regression, revert specific subcomponents.

#### Step 15 — Patch-window analytics pipeline
**Build:** Scripts at `analytics/` for parsing hand-history JSON from the D1 qualifier (downloadable on June 2):

- `analytics/loss_by_spot.py` — identify infoset buckets where we lost most chips
- `analytics/fallback_report.py` — which infosets triggered emergency fallback
- `analytics/opponent_sizing_histogram.py` — common bet sizes in actual field
- `analytics/big_pot_loss.py` — analyze largest losing hands in detail
- `analytics/multiway_analysis.py` — performance breakdown in multiway pots

Built **proactively before D1** so they're ready when histories drop. Validate by running against synthetic hand histories from our own local matches.

**Patch ideas to apply during D2:**
- Add common opponent bet sizes (from histograms) to action abstraction
- Fill in fallback-heavy infosets in the blueprint
- Re-tune λ perturbation based on field aggression
- Adjust short-stack jam thresholds

**Validate:** Scripts produce sensible output. Final submission package re-validated.
**Pass:** Patched bot uploaded before D5 finals.

---

## 6. Validation framework (use for EVERY version gate)

**Paired-seed differential testing** is the only honest way to measure improvement.

```bash
# Pattern for every version transition
python3 sandbox/bench.py \
    bots/vN/bot.py \
    bots/vN+1/bot.py \
    --opponents bots/template,bots/aggressor,bots/mathematician,bots/shark,bots/ref_bot_2 \
    --seeds 30 \
    --hands 400
```

**Three gates that EVERY version must clear:**

**Gate 1 — Robustness (hard, non-negotiable):**
- Zero crashes
- Zero timeouts
- Zero invalid actions
- p99 decision time ≤ 1.2s
- Mean decision time ≤ 500ms
- Validator still passes
- Fuzzer still passes

**Gate 2 — Paired EV (statistical):**
- Beats prior version on paired-seed runs
- Paired t-test p-value < 0.05
- Positive median per-seed delta
- 5th-percentile per-seed delta no worse than -1000 chips vs prior version

**Gate 3 — Held-out generalization (only checked at v4, v6, v8):**
- Doesn't regress against held-out enemy zoo (6 bots that were never used during tuning)
- This catches overfitting to the tuning enemy zoo

**Robust scoring function for final selection:**
```python
robust_score = median_delta - 0.25 * p5_delta
```
This penalizes variance — a feature that improves mean but blows up downside is penalized.

**If a version fails any gate:**
1. Archive the version directory as `vN_attempt_a/`
2. Revert trunk to vN-1
3. Either redesign and try again OR skip that feature
4. **No exceptions** for "but it should work."

---

## 7. Engineering discipline (anti-complexity)

These are hard constraints. Violating them = increased risk of failure.

**Line count budget.** v0 ≈ 80 lines. Each later version adds ≤150 lines of strategy code. By v12, ≤1,800 lines total. If a version needs more, split into two versions or simplify the design.

**No dead branches.** If a code path isn't exercised by some state in the validation suite, remove it. Untested code = risk without reward.

**Configuration over special cases.** When tempted to add `if opponent == 'aggressor': ...`, add a parameter instead. Special cases proliferate; parameters can be tuned.

**One thing at a time.** Each version changes exactly one mechanism. Don't add eval7 equity AND opponent modeling in the same step.

**Time-boxed implementation.** Each version gets max 4 hours including validation. If you hit the limit without a passing version, revert and either simplify or skip the feature.

**Always run validator and fuzzer before merging.** No exceptions.

---

## 8. Current state of the project (as of the start of Step 1)

**Done:**
- Repo cloned at `/Users/ismailhakkikilic/Desktop/Fullhouse Poker AI/fullhouse-engine/`
- This brief written
- Tasks 1–6 created in task tracker (Phase 1 only)

**Next actions in order:**
1. Confirm dependencies installed on the user's Mac (Cython<3, eval7==0.1.7, flask, numpy, scipy, treys, scikit-learn)
2. Run `python3 tests/test_engine.py` to verify engine
3. Run a smoke match: `python3 sandbox/match.py bots/shark/bot.py bots/aggressor/bot.py --hands 50 --verbose`
4. Capture 3–5 example game_states (modify a reference bot to print state to stderr, run match, parse)
5. Move on to Step 2 (build bench.py, fuzz.py, enemy zoo)

---

## 9. Reference material

### 9.1 Forbidden imports (full list)
`socket`, `urllib`, `urllib2`, `urllib3`, `requests`, `httpx`, `aiohttp`, `http`, `ftplib`, `smtplib`, `telnetlib`, `xmlrpc`, `subprocess`, `multiprocessing`, `pickle`, `shelve`, `threading`, `asyncio`, `ctypes`, `runpy`, `importlib`.

### 9.2 Forbidden call patterns (AST-checked)
`eval(`, `exec(`, `compile(`, `__import__(`, `getattr(__builtins__`, `__builtins__[...]`, `os.system`, `os.popen`, `os.exec*`, `os.spawn*`, `os.fork`, `os.kill`, `os.remove`, `os.unlink`, `os.rmdir`, `os.removedirs`, `os.chmod`, `os.chown`, `os.replace`, `os.rename`, `subprocess.*`.

### 9.3 Available libraries
- `eval7==0.1.7` — hand evaluation, Monte Carlo equity
- `numpy>=1.26.0` — arrays, math
- `scipy>=1.13.0` — stats, optimize (linprog), special functions
- `treys==0.1.8` — alternative hand evaluator
- `scikit-learn>=1.5.0` — offline training (extract numpy arrays, don't use joblib)

### 9.4 Example bot skeleton
```python
"""
v0 baseline — cannot die.
"""
import os
import time

BOT_NAME = "OurBot v0"

DATA_DIR = os.environ.get("BOT_DATA_DIR",
                          os.path.join(os.path.dirname(__file__), "data"))

# === Module globals (persist across hands within a match) ===
HAND_COUNT = 0
LAST_LOG_INDEX = 0
OPPONENT_STATS = {}

# === Constants ===
PREMIUM_PAIRS = {('A','A'), ('K','K'), ('Q','Q'), ('J','J')}
STRONG_ACES = {('A','K'), ('A','Q')}

# === Helpers ===
def parse_state(state):
    cards = state.get('your_cards', [])
    ranks = tuple(sorted([c[0] for c in cards], reverse=True))
    suited = len(cards) == 2 and cards[0][1] == cards[1][1]
    return {
        'ranks': ranks,
        'suited': suited,
        'street': state.get('street', 'preflop'),
        'pot': state.get('pot', 0),
        'owed': state.get('amount_owed', 0),
        'stack': state.get('your_stack', 0),
        'can_check': state.get('can_check', False),
        'min_raise_to': state.get('min_raise_to', 100),
        'my_bet': state.get('your_bet_this_street', 0),
    }

def emergency_fallback(state):
    if state.get('can_check'):
        return {"action": "check"}
    return {"action": "fold"}

def map_to_legal_action(intended, state):
    a = intended.get('action')
    if a == 'check' and not state.get('can_check'):
        return {"action": "fold"}
    if a == 'raise':
        amt = int(intended.get('amount', 0))
        min_r = state['min_raise_to']
        max_r = state['your_stack'] + state['your_bet_this_street']
        if amt >= max_r:
            return {"action": "all_in"}
        return {"action": "raise", "amount": max(amt, min_r)}
    if a in ('fold', 'call', 'all_in'):
        return {"action": a}
    return emergency_fallback(state)

# === Main ===
def decide(state):
    if state.get('type') == 'warmup':
        return {"action": "check"}

    t0 = time.time()
    try:
        p = parse_state(state)

        # Preflop logic
        if p['street'] == 'preflop':
            if p['ranks'] in PREMIUM_PAIRS:
                return map_to_legal_action(
                    {"action": "raise", "amount": p['min_raise_to'] * 3}, state)
            if p['ranks'] in STRONG_ACES:
                if p['owed'] <= 100:  # facing only blind
                    return map_to_legal_action(
                        {"action": "raise", "amount": int(p['min_raise_to'] * 2.5)}, state)
                if p['owed'] <= p['pot'] * 0.5:
                    return {"action": "call"}
                return {"action": "fold"}
            if p['can_check']:
                return {"action": "check"}
            return {"action": "fold"}

        # Postflop logic
        if p['can_check']:
            return {"action": "check"}
        if p['owed'] > 0 and p['pot'] / p['owed'] >= 3:
            return {"action": "call"}
        return {"action": "fold"}

    except Exception:
        return emergency_fallback(state)
```

### 9.5 The 169 canonical hand classes
- Pocket pairs: AA, KK, QQ, JJ, TT, 99, 88, 77, 66, 55, 44, 33, 22 (13 hands)
- Suited: AKs, AQs, ..., A2s, KQs, ..., K2s, ..., 32s (78 hands)
- Offsuit: AKo, AQo, ..., A2o, KQo, ..., K2o, ..., 32o (78 hands)
- Total: 169

### 9.6 Useful eval7 snippets
```python
import eval7
import random

def hand_equity_vs_random(hole_cards, community_cards, n_opponents=1, n_iter=2000):
    """Monte Carlo equity vs random opponents."""
    hero = [eval7.Card(c) for c in hole_cards]
    board = [eval7.Card(c) for c in community_cards]
    dead = set(hero + board)
    full_deck = [eval7.Card(r+s) for r in '23456789TJQKA' for s in 'shdc']
    available = [c for c in full_deck if c not in dead]

    wins = 0
    for _ in range(n_iter):
        deck = available[:]
        random.shuffle(deck)
        opps = [deck[i*2:(i+1)*2] for i in range(n_opponents)]
        idx = n_opponents * 2
        extra_board = deck[idx: idx + (5 - len(board))]
        full_board = board + extra_board
        hero_score = eval7.evaluate(hero + full_board)
        opp_scores = [eval7.evaluate(o + full_board) for o in opps]
        if hero_score > max(opp_scores):
            wins += 1
        elif hero_score == max(opp_scores):
            wins += 0.5
    return wins / n_iter
```

### 9.7 Useful scipy.stats.beta snippet
```python
from scipy.stats import beta

# Beta(alpha, beta) posterior for binary observations
def update_and_query(alpha, beta_param, successes, trials):
    new_alpha = alpha + successes
    new_beta = beta_param + (trials - successes)
    mean = new_alpha / (new_alpha + new_beta)
    lo, hi = beta.interval(0.90, new_alpha, new_beta)  # 90% CI
    return mean, lo, hi, new_alpha, new_beta
```

### 9.8 Useful scipy.optimize.linprog pattern for HU river LP
```python
from scipy.optimize import linprog
import numpy as np

def solve_river_lp(payoff_matrix):
    """
    payoff_matrix[i,j] = hero's EV when hero plays action i, villain plays j.
    Solves for hero's mixed strategy in zero-sum game.
    Returns (hero_mix, game_value).
    """
    m, n = payoff_matrix.shape
    # Standard form: maximize v subject to:
    #   sum_i x_i * payoff[i, j] >= v for all j
    #   sum_i x_i = 1, x_i >= 0
    # Variables: [v, x_0, x_1, ..., x_{m-1}]
    c = np.zeros(m + 1)
    c[0] = -1  # maximize v = minimize -v
    A_ub = np.hstack([np.ones((n, 1)), -payoff_matrix.T])
    b_ub = np.zeros(n)
    A_eq = np.zeros((1, m + 1))
    A_eq[0, 1:] = 1
    b_eq = np.array([1.0])
    bounds = [(None, None)] + [(0, 1)] * m
    res = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                  bounds=bounds, method='highs')
    if not res.success:
        return None, None
    hero_mix = res.x[1:]
    v = res.x[0]
    return hero_mix, v
```

---

## 10. The single most important reminder

**Validate every change with paired-seed differential testing. Never merge a version that fails its gates. The discipline IS the strategy.**

If you feel pressure to skip validation because "this change is obviously good," that's exactly when you must validate. Intuition about poker strategy is unreliable; the data is not.

End of brief.
