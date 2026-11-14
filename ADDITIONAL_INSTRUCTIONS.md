# ADDITIONAL INSTRUCTIONS — FullHouse Poker AI

> **PRECEDENCE RULE — READ FIRST**
>
> This file is a companion to `IMPLEMENTATION_BRIEF.md`. **Where this file and the main brief disagree, this file wins.** When implementing any version (v0 through v12), check this file first. The brief remains the source of truth for everything not contradicted here.
>
> These patches address corrections surfaced by adversarial review after the brief was written. Several fix real bugs in the brief's design. None of them add complexity beyond what was already planned — they are sharper specifications or bug fixes, not new features.

---

## Patch 1 — Replace `LAST_LOG_INDEX` with hand-boundary processing

**Modifies:** Section 5 Step 7 of brief; Section 9.6 example snippet.

**Bug being fixed:** The brief proposes:
```python
LAST_LOG_INDEX = 0
def update_opponent_memory(state):
    log = state.get('match_action_log', [])
    for entry in log[LAST_LOG_INDEX:]:
        ...
    LAST_LOG_INDEX = len(log)
```
This is **broken**. `match_action_log` is a rolling window capped at 200 entries (see `match.py::MATCH_LOG_MAX_ENTRIES = 200`). Once it fills up, `len(log)` stays at 200 forever — new entries push old ones off. The index approach would silently stop learning after the first 200 logged actions.

**Required replacement:** Process completed hands at hand boundaries, plus track current-hand actions incrementally from `action_log` (which is per-hand and NOT truncated).

```python
import re

PROCESSED_HANDS = set()          # set of int hand_num
LAST_CURRENT_HAND_ACTIONS = 0    # actions seen in the current hand so far

def parse_hand_num(hand_id):
    """Extract trailing hNNNN from hand_id like 'match_x_h0042'.
    Returns int or None if format unrecognized."""
    if not hand_id:
        return None
    m = re.search(r'h(\d+)$', hand_id)
    return int(m.group(1)) if m else None

def update_opponent_memory(state):
    global LAST_CURRENT_HAND_ACTIONS

    current_hand = parse_hand_num(state.get('hand_id', ''))
    if current_hand is None:
        return  # graceful fail if hand_id format is unexpected

    match_log = state.get('match_action_log', [])

    # --- 1. Process completed hands we haven't seen yet ---
    by_hand = {}
    for entry in match_log:
        hn = entry.get('hand_num')
        if hn is None or hn == current_hand or hn in PROCESSED_HANDS:
            continue
        by_hand.setdefault(hn, []).append(entry)

    for hn in sorted(by_hand):
        # Process all actions from completed hand hn in order
        process_hand_actions(by_hand[hn])
        PROCESSED_HANDS.add(hn)

    # --- 2. Process new actions in the current hand from action_log ---
    # action_log is the per-hand log; complete and not truncated
    action_log = state.get('action_log', [])
    new_actions = action_log[LAST_CURRENT_HAND_ACTIONS:]
    for action in new_actions:
        process_current_hand_action(action, current_hand)
    LAST_CURRENT_HAND_ACTIONS = len(action_log)

    # --- 3. Detect hand transition for clean state reset ---
    # When current_hand differs from what action_log suggests, reset counter
    # Belt-and-suspenders: if action_log is shorter than expected, hand restarted
    if len(action_log) < LAST_CURRENT_HAND_ACTIONS:
        LAST_CURRENT_HAND_ACTIONS = len(action_log)
```

**Why this works:**
- Completed hands are captured at hand boundaries via the `PROCESSED_HANDS` set — survives any truncation in `match_action_log` as long as we see at least one entry from each hand before it's pushed off (in practice, fine: ~30 hands of buffer with 6 bots).
- Current-hand actions come from `action_log` which is **per-hand and not truncated**, so we never miss within-hand actions.
- `PROCESSED_HANDS` grows by ~1 per hand → ~400 entries by match end → trivial memory.

**Edge case to handle:** If we fold preflop and skip an entire hand, we still process that hand's actions on the next call to `decide()` (because the entries are in `match_action_log` for the next hand we play). The `PROCESSED_HANDS` check prevents double-counting.

---

## Patch 2 — Capture game states via match.py instrumentation, not stderr

**Modifies:** Section 5 Step 1; Section 8 of brief.

**Bug being fixed:** The brief suggests capturing fixture states by "modifying a reference bot to print state to stderr." This is wrong because `match.py` captures stderr but discards it via the empty `stderr_lines()` method — we can't reliably read it back.

**Required replacement:** Instrument `sandbox/match.py` directly for dev-only state capture. This is local tooling, not submission code, so file writes are fine.

In `sandbox/match.py`, modify `_play_hand` (around line 287):

```python
def _play_hand(engine, procs, active_bots, match_action_log, hand_num, verbose):
    import os, json
    dump_path = os.environ.get("DUMP_STATES")

    state = _inject_match_log(engine.start_hand(), match_action_log)
    steps = 0

    while state.get("type") == "action_request":
        seat   = state["seat_to_act"]
        bot_id = active_bots[seat]

        # DEV INSTRUMENTATION
        if dump_path:
            with open(dump_path, "a") as f:
                f.write(json.dumps(state) + "\n")

        action = procs[bot_id].act(state)
        # ... rest unchanged
```

Then capture states with:
```bash
DUMP_STATES=/tmp/states.jsonl python3 sandbox/match.py bots/shark/bot.py bots/aggressor/bot.py --hands 50
```

**Alternative (preferred for clean separation):** Write a standalone `dev/dump_states.py` that imports `PokerEngine` directly, simulates a hand with random actions, and serializes every `action_request` state. Doesn't touch `match.py` at all.

```python
# dev/dump_states.py
import json, random, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from engine.game import PokerEngine

random.seed(42)
out = []
for hand_idx in range(20):
    bot_ids = [f"bot_{i}" for i in range(6)]
    eng = PokerEngine(f"dev_h{hand_idx:04d}", bot_ids, dealer_seat=hand_idx % 6, seed=hand_idx)
    state = eng.start_hand()
    while state.get("type") == "action_request":
        out.append(state)
        # random legal action
        seat = state["seat_to_act"]
        choice = random.choice(["fold", "call", "check"])
        if choice == "check" and not state["can_check"]:
            choice = "call"
        state = eng.apply_action(seat, {"action": choice})

with open("dev/sample_states.jsonl", "w") as f:
    for s in out:
        f.write(json.dumps(s) + "\n")
print(f"Wrote {len(out)} states to dev/sample_states.jsonl")
```

---

## Patch 3 — Add fallback percentile preflop ranges (annotated)

**Modifies:** Section 5 Step 4 of brief.

**Bug being fixed:** Brief makes v1 dependent on hand-crafted ranges. If those are incomplete, v1 is blocked.

**Required addition:** Three range sources, with explicit annotation showing which is in use for each spot. Never silently use a fallback.

```python
# bots/v1/ranges.py

# 169 hand classes ordered by approximate hand strength (top of preflop chart)
HAND_RANK_ORDER = [
    'AA', 'KK', 'QQ', 'AKs', 'AKo', 'JJ', 'AQs', 'AQo', 'TT', 'KQs',
    'AJs', 'KJs', '99', 'KQo', 'ATs', 'AJo', 'QJs', '88', 'KTs',
    'QTs', 'JTs', 'ATo', 'KJo', '77', 'A9s', 'QJo', 'KTo', 'JTo',
    'A8s', 'T9s', 'QTo', '66', 'A7s', '98s', 'A5s', 'A6s', 'A4s',
    # ... extend to all 169
]

# Percentile fallback ranges (used if a spot has no handcrafted entry)
FALLBACK_OPEN_PERCENTILES = {
    'UTG': 0.12, 'HJ': 0.18, 'CO': 0.27, 'BTN': 0.45, 'SB': 0.40, 'BB': 0.0,  # BB never opens
}

def fallback_open_range(position):
    cutoff_pct = FALLBACK_OPEN_PERCENTILES[position]
    n = int(len(HAND_RANK_ORDER) * cutoff_pct)
    return set(HAND_RANK_ORDER[:n])

# Handcrafted ranges (user-authored). Each entry is annotated with source.
HANDCRAFTED_OPEN_RANGES = {
    'UTG': {  # source: handcrafted by Ali
        'hands': {'AA','KK','QQ','JJ','TT','99','AKs','AKo','AQs','AQo','AJs','KQs'},
        'source': 'handcrafted',
    },
    'BTN': {  # source: handcrafted by Ali
        'hands': {'AA','KK', ...},  # TODO fill in
        'source': 'handcrafted',
    },
    # spots NOT keyed here will use the fallback automatically
}

def get_open_range(position):
    """Returns (set_of_hands, source_string). source ∈ {'handcrafted', 'fallback'}."""
    if position in HANDCRAFTED_OPEN_RANGES:
        entry = HANDCRAFTED_OPEN_RANGES[position]
        return entry['hands'], entry['source']
    return fallback_open_range(position), 'fallback'
```

**Validation requirement:** During bench.py runs, log the count of times fallback fired per spot. If any spot fires fallback >10% of preflop decisions, flag it for handcrafting before moving to v2.

**Same pattern applies to 3-bet, 4-bet, blind-defend, push/fold ranges** — all need handcrafted + fallback versions.

---

## Patch 4 — Soften v1 pass criterion

**Modifies:** Section 5 Step 4 of brief.

**Old criterion:** "Beats v0 (p<0.05, positive median delta) AND positive median delta vs every reference bot AND beats `shark` for the first time."

**New criterion:**
- Beats v0 paired-seed overall (p<0.05, positive median delta)
- **Improves materially vs shark vs v0 baseline** (median delta gain > +2000 chips per 400-hand match relative to v0)
- Does not regress materially against `template`, `aggressor`, `mathematician`, `ref_bot_2` (median delta no worse than -1000 chips relative to v0)

**Rationale:** Without postflop, v1 may not actually beat shark in absolute terms, but should improve directionally vs v0. The "actually beats shark" goalpost moves to v2.

---

## Patch 5 — v2 is explicitly hand-authored postflop strategy table

**Modifies:** Section 5 Step 5 of brief; Section 4 proposal table.

**Clarification:** v2's postflop "blueprint" is a **hand-authored mixed-strategy table** in a CFR-compatible format. It is NOT generated by running CFR. The format is `infoset_key → action_probability_vector` so that a future CFR-generated table could drop in to replace it, but for v2 the values are authored from poker theory + judgment.

Rename in code and comments from "blueprint" (ambiguous) to **`POSTFLOP_STRATEGY_TABLE`** to remove the implication of solver origin.

**Storage format:** plain Python dict or numpy `.npz`. Each value is a length-K probability vector over abstract actions (K = number of actions in the abstract action set at that node).

---

## Patch 6 — Use normal-approximation CI for runtime opponent-stat gating

**Modifies:** Section 5 Step 7 of brief; Section 9.7 snippet.

**Bug being fixed:** Brief uses `scipy.stats.beta.interval(0.90, a, b)` in the runtime gating path. This is computationally expensive (regularized incomplete beta function) and unnecessary for our gating purposes.

**Required replacement:** Wilson / normal approximation for the hot path. Reserve `scipy.stats.beta.interval` for offline analysis only.

```python
import math

def stat_mean_and_ci(alpha, beta_param):
    """Cheap Wilson-style CI for Beta(alpha, beta) posterior.
    Good enough for opponent-modeling gating; ~50x faster than
    scipy.stats.beta.interval and accurate to within ~1pp for n>20."""
    n = alpha + beta_param
    if n == 0:
        return 0.5, 0.0, 1.0
    mean = alpha / n
    # Wilson half-width for 90% CI (z = 1.645)
    se = math.sqrt(mean * (1.0 - mean) / n) if n > 0 else 0.5
    half = 1.645 * se
    return mean, max(0.0, mean - half), min(1.0, mean + half)
```

Use exact `scipy.stats.beta.interval` ONLY in offline analytics scripts (Step 15 patch-window tools), never inside `decide()`.

---

## Patch 7 — LR-driven sizing is confidence-gated, not full EV-optimizer

**Modifies:** Section 5 Step 11 of brief.

**Bug being fixed:** The brief's "pick the size maximizing EV using LR fold predictor" is too aggressive. When the LR's prediction has high uncertainty (limited per-opponent data, out-of-distribution features), it can produce wild bet sizes that the blueprint would never recommend.

**Required replacement:** Gate the LR's influence by its own confidence. Three-tier behavior:

```python
def lr_assisted_bet_size(blueprint_dist, features, opp_id):
    """
    blueprint_dist: dict like {0.33: 0.4, 0.66: 0.3, 1.0: 0.3} (size_frac: prob)
    Returns the actual bet fraction to use.
    """
    # Predict P(fold) for each candidate size
    candidate_sizes = sorted(blueprint_dist.keys())
    fold_preds = [predict_fold_prob(features_for_size(features, s), opp_id)
                  for s in candidate_sizes]

    # Estimate prediction confidence from data we have on this opponent
    n_obs = opponent_observation_count(opp_id)

    if n_obs < 20:
        # Insufficient data — sample from blueprint as-is
        return sample_from_dist(blueprint_dist)
    elif n_obs < 100:
        # Some data — let LR perturb blueprint probabilities, but don't override
        # Compute expected EV per size, but only shift probabilities, don't pick max
        ev_per_size = compute_ev_per_size(candidate_sizes, fold_preds, ...)
        weights = blueprint_dist_values * np.exp(0.3 * normalize(ev_per_size))
        return sample_from_weights(candidate_sizes, weights)
    else:
        # Lots of data — let LR drive within blueprint's support
        ev_per_size = compute_ev_per_size(candidate_sizes, fold_preds, ...)
        # Pick highest-EV size, but ONLY among blueprint-approved sizes
        best_idx = argmax(ev_per_size)
        return candidate_sizes[best_idx]
```

**Key constraint:** LR can only redistribute probability among **blueprint-approved sizes**. It cannot invent new sizes outside the blueprint's distribution. This bounds the downside if the LR is wrong.

---

## Patch 8 — Hard rule: no sklearn import in submitted bot.py

**Modifies:** Section 1 forbidden-imports; Section 7 engineering discipline.

**New rule:** `bot.py` (the submission file) MUST NOT import scikit-learn. Even though `import sklearn` would pass the AST validator, sklearn pulls in joblib (which uses pickle internally) and has high import-time cost.

**Allowed imports in submission `bot.py`:**
- `os`, `time`, `math`, `random`, `hashlib`, `json`, `re`, `collections`, `itertools`, `functools` (stdlib)
- `numpy`
- `eval7`
- `scipy.stats` (limited — use sparingly, prefer numpy where possible)
- `scipy.optimize` (only in v11 LP solver path)
- `scipy.special` (for logsumexp etc, if needed)

**Banned at runtime even though pip-installable:**
- `sklearn` / `scikit-learn` — train offline, extract numpy arrays, ship in `data/`
- `treys` — eval7 is enough
- `flask` — server library, no purpose here

**Training pattern:** Offline trainer script (e.g., `training/train_lr.py`) uses sklearn, then extracts:
```python
np.savez(
    'data/lr_fold_predictor.npz',
    coef=model.coef_.astype(np.float32),
    intercept=model.intercept_.astype(np.float32),
    feature_means=scaler.mean_.astype(np.float32),  # if using StandardScaler
    feature_stds=scaler.scale_.astype(np.float32),
)
```
Runtime loads these arrays at module import and does inference with pure numpy.

---

## Patch 9 — Strengthen deterministic mix-sampling seed

**Modifies:** Section 5 Step 14 of brief; Section 9 sampling snippet.

**Bug being fixed:** The brief's seed `f"{hand_id}|{bot_id}|{street}"` is not unique per decision. We may act multiple times on the same street (e.g., facing a raise after our c-bet). Same seed → same quantile → unwanted correlation across our own decisions.

**Required replacement:** Include enough state to uniquely identify each decision point.

```python
import hashlib

def sample_mixed_action(dist_dict, state):
    """
    dist_dict: {action_name: probability}
    state: full game state dict
    Returns: chosen action name (deterministic per decision point).
    """
    if not dist_dict:
        return None

    actions = sorted(dist_dict.keys())
    probs = [dist_dict[a] for a in actions]
    total = sum(probs)
    if total <= 0:
        return actions[0]
    probs = [p / total for p in probs]

    # Seed includes everything that uniquely identifies this decision point
    seed_parts = [
        state.get('hand_id', ''),
        str(state.get('seat_to_act', '')),
        state.get('street', ''),
        str(len(state.get('action_log', []))),    # action position within hand
        str(state.get('pot', '')),
        str(state.get('current_bet', '')),
        str(state.get('amount_owed', '')),
        str(state.get('your_bet_this_street', '')),
    ]
    seed_str = '|'.join(seed_parts)
    h = int(hashlib.md5(seed_str.encode()).hexdigest()[:16], 16)
    rng_value = (h % 10**9) / 10**9   # uniform [0, 1)

    cumulative = 0.0
    for action, p in zip(actions, probs):
        cumulative += p
        if rng_value < cumulative:
            return action
    return actions[-1]  # numerical safety
```

**Why this works:** Every distinct decision point produces a distinct seed. Within a single decision, sampling is reproducible from the seed. Across decisions, the distribution mixing is proper.

---

## Patch 10 — Consistent bucketing for irregular bet sizes (Patch interacts with v7 irregular sizing)

**Modifies:** Section 5 Step 5/8 of brief.

**Bug being fixed:** v7 introduces irregular sizes (29%, 71%, 113%) but our own action-history encoder (used to build infoset keys) sees these in our own match log. If the encoder uses exact sizes, it bucketsour 29% bet as "small" while the blueprint expects "bet_33" bucket — mismatch.

**Required fix:** All size encoding (ours AND opponents') uses generous buckets, not exact sizes.

```python
def bucket_bet_size(bet_amount, pot_at_time):
    """Map any bet to a size bucket. Used both when encoding our own
    actions and when reading opponent actions from match_action_log."""
    if pot_at_time <= 0:
        return 'min_bet'
    ratio = bet_amount / pot_at_time
    if ratio < 0.20:
        return 'tiny_bet'        # min-raise, weird small
    elif ratio < 0.45:
        return 'small_bet'       # 25%-45% pot (handles 33%, 29%)
    elif ratio < 0.80:
        return 'medium_bet'      # 50%-75% pot (handles 66%, 71%)
    elif ratio < 1.20:
        return 'pot_bet'         # 80%-120% pot (handles 100%, 113%)
    elif ratio < 2.00:
        return 'overbet'         # 1.2x-2x pot (handles 150%, 187%)
    else:
        return 'huge_overbet'    # 2x+ pot
```

Use `bucket_bet_size` everywhere — both when **we** translate abstract → concrete in `map_to_legal_action`, and when we **read** prior actions from `action_log` / `match_action_log` for opponent modeling.

---

## Patch 11 — Revised version sequence

**Modifies:** Section 5 of brief (entire structure).

**Reason:** Multiway tightening is one of the highest-leverage moves against an LLM-built field. It should land earlier than adversarial sizing. Deterministic sampling should be promoted from "hardening" to a foundational layer. LR comes later (higher risk).

**New canonical sequence (use this, ignore brief's ordering):**

| Version | Content | Approx LOC delta | Validation gate |
|---------|---------|------------------|-----------------|
| v0 | "Cannot die" baseline | 80 | Validator + fuzzer + 30 paired seeds vs reference bots |
| v1 | Hand-crafted preflop blueprint + fallback ranges (Patch 3) | +150 | Patch 4 criterion vs v0 |
| v2 | Hand-authored postflop strategy table + nested fallback (Patch 5) | +200 | Beats v1 paired-seed, fallback rate <5% |
| **v3** | **Multiway tightening Layer 1 (rules-only)** | +60 | Beats v2 in 6-bot mass sims, no HU regression |
| **v4** | **Opponent memory: Bayesian Beta stats with hand-boundary processing (Patch 1) + normal-approx CI (Patch 6) + bounded perturbation + variance buffer + bluff-propensity stat** | +200 | Beats v3 vs tuning enemy zoo specifically |
| **v5** | **eval7 equity layer + precomputed equity-vs-range table + multiway Layer 2 (best-of-N equity verification)** | +150 | Beats v4 with no timeout regressions, p99 decision time <600ms |
| **v6** | **Deterministic mixed-strategy sampling (Patch 9) + bet-size bucketing (Patch 10)** | +80 | Neutral or better than v5; sampling is reproducible from logs |
| **v7** | **Irregular adversarial bet sizing** | +30 | Neutral or better than v6 |
| v8 | Blocker-aware river overrides | +120 | Beats v7 by even small margin |
| v9 | Heads-up branch (short-handed strategy + dealer=SB handling) | +120 | Beats v8 in synthetic HU situations |
| **v10** | **LR fold predictor + confidence-gated EV sizing (Patch 7) — no sklearn import (Patch 8)** | +200 | Beats v9 vs tuning AND held-out enemy zoo |
| v11 | (Optional) River LP subgame solver — only if all gates clean | +150 | Zero timeout regressions, beats v10 in HU |
| v12 | Final hardening: score-aware aggression (Patch 12), time-budget checkpoints, safety audit (Patch 15) | +80 | Highest robust score across full benchmark; zero failures across 100+ matches |

**Why this reorder:**
- Multiway at v3 captures EV gap from "LLM bots treat multiway as heads-up" as early as possible — this is where we expect our biggest field edge.
- Opponent stats at v4 immediately exploits multiway's tightening; together they cover most of the +EV potential.
- Equity at v5 unlocks multiway Layer 2 (best-of-N verification) and powers later layers.
- Deterministic sampling at v6 is treated as foundational (it affects every decision and is needed for reproducible debugging) rather than v11-hardening.
- LR at v10 stays late because it's the highest-overfit-risk component.
- River LP at v11 stays optional — skip if anything earlier is shaky.

---

## Patch 12 — Score-aware aggression: smaller deltas, parse hand_num explicitly

**Modifies:** Section 5 Step 14 of brief (now v12 under Patch 11 reorder).

**Bug being fixed:** Brief's ±10% modifier is too aggressive for a cash format. And it assumes hand_num is available without showing parsing.

**Required replacement:**

```python
def aggression_modifier(state):
    """Returns a multiplier in [0.97, 1.05] to apply to bluff/raise frequencies.
    Very mild; only fires near end of match."""
    hand_num = parse_hand_num(state.get('hand_id', ''))
    if hand_num is None:
        return 1.0  # graceful fail — no adjustment if we can't determine

    HANDS_PER_MATCH = 400
    hands_remaining = HANDS_PER_MATCH - hand_num

    # Only apply in last ~50 hands
    if hands_remaining > 50:
        return 1.0

    our_stack = state.get('your_stack', 0)
    STARTING_STACK = 10_000
    delta_ratio = our_stack / STARTING_STACK  # >1 if ahead, <1 if behind

    # Mild adjustment:
    # If far behind, slight aggression boost (need to gamble for chips)
    # If far ahead, slight passivity (preserve)
    # Bounded to ±3-5%
    if delta_ratio < 0.5:
        return 1.05    # +5% aggression when way behind, late in match
    elif delta_ratio < 0.8:
        return 1.02
    elif delta_ratio > 2.0:
        return 0.97    # -3% aggression when way ahead, late in match
    elif delta_ratio > 1.5:
        return 0.99
    return 1.0
```

**Pushback on GPT's intuition:** This is cash format with fixed 400-hand budget, not ICM. The asymmetry is "running out of hands" not "preserving stack." Weighting primarily by `hands_remaining` (not `stack_ratio`) is more correct.

---

## Patch 13 — bench.py must standardize seat and bot identity

**Modifies:** Section 5 Step 2a of brief; Section 6.

**Bug being fixed:** When comparing v_N vs v_{N+1}, if they have different `bot_id`s or sit in different seats, the comparison is biased — positional dynamics differ, and our own deterministic sampling (which keys on hand_id + seat) gives different mixings for what should be the same decision point.

**Required behavior in `bench.py`:**

1. **Stable bot_id.** Both versions are renamed to the same `bot_id` for the comparison run (e.g., both run as `"bot_under_test"`). Achieved by copying the bot.py to a tempdir with a fixed name before invoking `match.py`.

2. **Stable seat index.** The bot under test is always at seat 0; opponents fill seats 1..n-1 in the same order.

3. **Identical opponent set and ordering.** The opponents list is passed in the same order for both runs.

4. **Identical seed.** `match.py --seed S` is used for both runs.

Skeleton:

```python
# sandbox/bench.py
import subprocess, json, tempfile, shutil, os, sys
import numpy as np
from scipy import stats

def run_match(bot_under_test_path, opponent_paths, seed, hands=400):
    """Run a single match with bot at seat 0, opponents at 1..n-1."""
    with tempfile.TemporaryDirectory(prefix='bench_') as td:
        # Standardize bot identity
        canonical_bot = os.path.join(td, 'bot_under_test')
        os.makedirs(canonical_bot)
        shutil.copy(bot_under_test_path, os.path.join(canonical_bot, 'bot.py'))
        # If bot has data/, copy that too
        bot_dir = os.path.dirname(bot_under_test_path)
        data_dir = os.path.join(bot_dir, 'data')
        if os.path.isdir(data_dir):
            shutil.copytree(data_dir, os.path.join(canonical_bot, 'data'))

        cmd = [
            sys.executable, 'sandbox/match.py',
            canonical_bot,             # always seat 0
            *opponent_paths,           # seats 1..n-1
            '--seed', str(seed),
            '--hands', str(hands),
            '--json',
        ]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return json.loads(out.stdout)

def paired_bench(bot_a, bot_b, opponents, n_seeds=30, hands=400, base_seed=1000):
    """Paired-seed comparison. Returns per-seed deltas and stats."""
    deltas_a, deltas_b = [], []
    for i in range(n_seeds):
        seed = base_seed + i
        ra = run_match(bot_a, opponents, seed, hands)
        rb = run_match(bot_b, opponents, seed, hands)
        # Bot is "bot_under_test" by construction
        deltas_a.append(ra['chip_delta']['bot_under_test'])
        deltas_b.append(rb['chip_delta']['bot_under_test'])
    paired_diffs = np.array(deltas_b) - np.array(deltas_a)
    t_stat, p_val = stats.ttest_rel(deltas_b, deltas_a)
    return {
        'mean_diff': float(np.mean(paired_diffs)),
        'median_diff': float(np.median(paired_diffs)),
        'p5_diff': float(np.percentile(paired_diffs, 5)),
        'p95_diff': float(np.percentile(paired_diffs, 95)),
        't_stat': float(t_stat),
        'p_value': float(p_val),
        'a_mean': float(np.mean(deltas_a)),
        'b_mean': float(np.mean(deltas_b)),
        'per_seed_a': deltas_a,
        'per_seed_b': deltas_b,
    }
```

---

## Patch 14 — Three-tier fuzzer legality classification

**Modifies:** Section 5 Step 2b of brief.

**Bug being fixed:** "Legal action" is ambiguous because the engine snaps below-min raises and converts oversize raises to all_in. The fuzzer should distinguish strict-clean from engine-accepted-but-coerced from truly invalid.

**Required behavior in `fuzz.py`:**

```python
def classify_action(action, state):
    """Returns one of: 'clean', 'coerced', 'invalid', 'crash'."""
    if not isinstance(action, dict) or 'action' not in action:
        return 'invalid'
    a = action['action']
    if a not in ('fold', 'check', 'call', 'raise', 'all_in'):
        return 'invalid'
    if a == 'check' and not state.get('can_check'):
        return 'invalid'
    if a == 'raise':
        amt = action.get('amount')
        if not isinstance(amt, int) or amt <= 0:
            return 'invalid'
        min_r = state.get('min_raise_to', 0)
        max_r = state.get('your_stack', 0) + state.get('your_bet_this_street', 0)
        if amt < min_r:
            return 'coerced'  # engine will snap up
        if amt > max_r:
            return 'coerced'  # engine will convert to all_in
        return 'clean'
    return 'clean'

# In fuzz run:
counts = {'clean': 0, 'coerced': 0, 'invalid': 0, 'crash': 0}
for state in fuzz_states:
    try:
        action = bot.decide(state)
        counts[classify_action(action, state)] += 1
    except Exception:
        counts['crash'] += 1
```

**Fail criteria:**
- `crash > 0` → hard fail (must fix)
- `invalid > 0` → hard fail (must fix)
- `coerced` is acceptable but logged — too many `coerced` suggests sloppy action mapping

---

## Patch 15 — Pre-submission safety audit checklist

**Modifies:** Section 5 Step 14 of brief (now v12 under Patch 11 reorder).

**New step:** Before packaging the final `bot.zip`, run through this checklist explicitly. Block submission until every item is checked.

```
[ ] sandbox/validator.py passes on submission package
[ ] fuzz.py: 0 crashes, 0 invalid actions across 10,000+ states
[ ] No forbidden imports in bot.py (grep: socket, urllib, requests, httpx,
    subprocess, multiprocessing, pickle, shelve, threading, asyncio,
    ctypes, runpy, importlib, sklearn, joblib, flask, treys)
[ ] No forbidden call patterns (grep: eval(, exec(, compile(, __import__(,
    getattr(__builtins__, os.system, os.popen, os.exec, subprocess.)
[ ] No file writes anywhere in bot.py (grep: open(, with open, .write()
    — verify each is reading from data/ at import time only)
[ ] No runtime file reads (all loads at module level, none in decide())
[ ] bot.py size <= 5MB
[ ] data/ total size <= 200MB
[ ] data/ contains no .py files
[ ] Total submission package <= 250MB
[ ] Handles state.get("type") == "warmup" correctly
[ ] Handles missing BOT_DATA_DIR gracefully (uses default path)
[ ] Handles malformed game states (verified by fuzz.py)
[ ] Handles 2-player to 6-player tables (verified by varying len(players))
[ ] Handles zero stack / all-in / busted players in players list
[ ] No absolute paths hardcoded (no /Users/, no C:\)
[ ] No stderr output in normal play (only on caught exceptions — and even
    then, just a brief tag, not full state dumps)
[ ] No network or DNS calls (visual inspection — should be obvious)
[ ] Deterministic mix-sampling produces same action for same state
    (run decide() twice on same state, verify same result)
[ ] Mean decision time <= 500ms across 1000+ fuzzed states
[ ] p99 decision time <= 1.2s across 1000+ fuzzed states
[ ] PROCESSED_HANDS set is cleared between matches (verified by
    inspecting test that runs 2 matches in sequence)
[ ] All assertions removed (assert statements may be optimized out
    under -O; don't rely on them)
[ ] All TODO/FIXME comments addressed or explicitly accepted as known
    limitations
```

If any item fails, fix or document acceptance before submitting.

---

## Patch 16 — Expanded enemy zoo and field-mix simulation methodology

**Modifies:** Section 5 Step 2c of brief; Section 6 validation framework.

**Reason:** Original 12-bot zoo skews toward easily-exploitable weak bots. Missing coverage of (a) strong "solver-flavored" opponents we'll face deep in the bracket, (b) bots that test our perturbation safety, (c) common blueprint-coverage holes (donking, trapping, slowplay). Also missing a **field-mix simulation methodology** — a much better predictor of tournament performance than head-to-head paired-seed against any single bot type.

### Patch 16a — Zoo additions (priority-grouped)

Add the following to `bots/enemy_zoo/`. Implement Priority 1 definitely; Priority 2 if time before v3; Priority 3 only if everything else is shipped.

**Priority 1 (covers our biggest blind spots — must add):**

`solver_approximator/bot.py` (~200 lines, **held-out zoo**)
- Standard 6-max preflop charts (tight UTG → wide BTN)
- Postflop: eval7-based equity, c-bet ~70% IP / 60% OOP, half-pot default sizing
- Calls down with top-pair-good-kicker or better
- Folds to large bets without strong made hand
- Represents the modal LLM-built bot. If we can't beat this, we won't make finals.

`mixed_strategy_pluribus_caricature/bot.py` (~150 lines, **held-out zoo**)
- Genuinely mixes: 4 different bet sizings at varying frequencies
- Polarized triple-barrel ranges
- 3-bet 8% / call 10% / fold 82% preflop
- Hard to exploit by design — tests whether our perturbation layer over-adjusts to noise

**Priority 2 (add if time before v3):**

`adaptive_basic/bot.py` (~100 lines, **held-out zoo**)
- Plays standard tight-aggressive for hands 1–50
- After hand 50: if observed our aggression > threshold, switches to call-station mode
- Tests anti-counter-exploit resilience; with Patch 9 deterministic sampling our behavior is reproducible from `hand_id`, but we verify it doesn't create exploitable patterns

`donking_specialist/bot.py` (~80 lines, **tuning zoo**)
- Donk-bets ~40% of flops from OOP with mixed-strength range
- Tests infoset coverage for donk lines (most blueprints lack this)

`slowplay_trapper/bot.py` (~80 lines, **tuning zoo**)
- Checks strong hands (sets, two pair, sometimes top pair) hoping to induce
- Check-raises after our c-bet
- Bets only marginal value
- Tests whether we correctly handle "checked to me" not implying weakness

`position_blind_bot/bot.py` (~50 lines, **tuning zoo**)
- Plays identical ranges regardless of position
- Tests whether our positional exploits pay off (they should)

**Priority 3 (skip unless everything else stable):**

`glitchy_bot` (occasional invalid actions/near-timeouts), `min_call_only` (folds anything > 1bb), `range_protector` (c-bets / barrels every street balanced), `tight_aggressive_reg` (standard online-regular profile).

**Total target zoo size:** 16–18 bots (was 12). Do not exceed 20 — diminishing returns on benchmark coverage and rising compute cost.

### Patch 16b — Field-mix simulation harness (M2 — highest-value new methodology)

Build `sandbox/field_sim.py`. Simulates a realistic tournament field with weighted opponent distribution. Becomes the **single best predictive metric for actual qualifier finish** because it tests the bot against the kind of mix it will actually face, not against any single bot type.

```python
# sandbox/field_sim.py
"""
Simulate realistic tournament-field 6-bot tables. Best predictor of
actual qualifier performance — much more informative than paired-seed
head-to-head against a single bot type.
"""
import random, json
import numpy as np
from pathlib import Path

# Pre-tournament best-guess distribution. Re-tune from D1 hand histories
# during the patch window.
FIELD_DISTRIBUTION = {
    'bots/enemy_zoo/solver_approximator/bot.py':              0.25,
    'bots/enemy_zoo/mixed_strategy_pluribus_caricature/bot.py': 0.10,
    'bots/enemy_zoo/mixed_llm_caricature/bot.py':             0.15,
    'bots/enemy_zoo/tight_value_only/bot.py':                 0.08,
    'bots/enemy_zoo/loose_passive_call_station/bot.py':       0.08,
    'bots/enemy_zoo/aggressive_3bettor/bot.py':               0.05,
    'bots/enemy_zoo/polarized_bettor/bot.py':                 0.05,
    'bots/enemy_zoo/short_stack_jammer/bot.py':               0.04,
    'bots/enemy_zoo/weird_sizing/bot.py':                     0.04,
    'bots/enemy_zoo/donking_specialist/bot.py':               0.04,
    'bots/enemy_zoo/nit_preflop/bot.py':                      0.03,
    'bots/enemy_zoo/overbet_river_bluffer/bot.py':            0.03,
    'bots/shark/bot.py':                                      0.03,
    'bots/template/bot.py':                                   0.02,
    'bots/aggressor/bot.py':                                  0.01,
}

def sample_table(distribution, n_opponents=5, rng=None):
    """Draw n_opponents bot paths from the field distribution (with replacement)."""
    if rng is None:
        rng = random.Random()
    bots, weights = zip(*distribution.items())
    return rng.choices(bots, weights=weights, k=n_opponents)

def run_field_simulation(bot_under_test, n_tables=100, hands=400, base_seed=2000):
    """Run n_tables 6-bot tables drawing opponents from the field distribution."""
    from bench import run_match    # uses canonical 'bot_under_test' identity (Patch 13)
    deltas = []
    for i in range(n_tables):
        rng = random.Random(base_seed + i)
        opponents = sample_table(FIELD_DISTRIBUTION, n_opponents=5, rng=rng)
        result = run_match(bot_under_test, opponents,
                           seed=base_seed + i, hands=hands)
        deltas.append(result['chip_delta'].get('bot_under_test', 0))

    deltas = np.array(deltas)
    return {
        'n_tables':                 n_tables,
        'cumulative_delta':         int(deltas.sum()),
        'mean_per_table':           float(deltas.mean()),
        'median_per_table':         float(np.median(deltas)),
        'p5_per_table':             float(np.percentile(deltas, 5)),
        'p95_per_table':            float(np.percentile(deltas, 95)),
        'std_per_table':            float(deltas.std()),
        'robust_score':             float(np.median(deltas) - 0.25 * np.percentile(deltas, 5)),
        'tables_with_positive_delta': int((deltas > 0).sum()),
        'per_table_deltas':         deltas.tolist(),
    }

if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('bot_path')
    ap.add_argument('--tables', type=int, default=100)
    ap.add_argument('--hands', type=int, default=400)
    ap.add_argument('--seed', type=int, default=2000)
    args = ap.parse_args()
    result = run_field_simulation(args.bot_path,
                                   n_tables=args.tables,
                                   hands=args.hands,
                                   base_seed=args.seed)
    print(json.dumps(result, indent=2))
```

**Validation use:** Run after every version that clears Gate 1 + Gate 2:
```bash
python3 sandbox/field_sim.py bots/v5/bot.py --tables 100
```
Track `cumulative_delta` and `robust_score` over versions.

**New Gate 4 — Field-mix non-regression.** A version that beats prior-version paired-seed BUT has a worse field-mix `robust_score` is suspicious — likely overfitting to specific opponents at expense of field-wide performance. **Treat as a soft gate**: investigate before merging.

**Patch-window update:** After D1 qualifier, re-tune `FIELD_DISTRIBUTION` weights from observed actual-field opponent types. The pre-tournament weights are best-guess; post-D1 we have ground truth.

### Patch 16c — Cross-version round-robin (M1, lighter-weight)

Build `sandbox/cross_version.py`. Verifies the **monotonic improvement curve** — each version should beat all earlier versions when seated at the same table.

```python
# sandbox/cross_version.py
"""
Multi-version round-robin. Seats v0, v1, ..., v_current at a single
6-bot table (filling remaining seats with reference bots) and runs
the table over n_seeds. Catches silent regressions where v_N
unexpectedly loses to v_{N-2} despite beating v_{N-1} pairwise.
"""
import json
from pathlib import Path
from bench import run_match_multiway  # see bench.py extension below

def cross_version_round_robin(version_paths, filler_paths, n_seeds=20, hands=400):
    """
    version_paths: ['bots/v0/bot.py', 'bots/v1/bot.py', ..., 'bots/v_current/bot.py']
    filler_paths: reference bots used to fill to 6 seats
        e.g. ['bots/shark/bot.py', 'bots/template/bot.py']
    Returns per-version cumulative chip delta across all seeds.
    """
    seats = version_paths + filler_paths
    assert 2 <= len(seats) <= 9
    cumulative = {p: 0 for p in seats}
    for i in range(n_seeds):
        result = run_match_multiway(seats, seed=1000 + i, hands=hands)
        for bot_id, delta in result['chip_delta'].items():
            cumulative[bot_id_to_path(bot_id, seats)] += delta
    return cumulative
```

**Validation use:** Run every 2–3 versions. If v_5 doesn't have a strictly higher cumulative delta than v_4 in this round-robin (despite winning paired-seed at the v_4→v_5 transition), something regressed silently.

### Patch 16d — Adversarial-weakness search (M3) — DEFERRED to patch window

Programmatic search for opponent parameters that maximally exploit us is academically clean but premature pre-qualifier. The right time is D2 patch window when we have real hand histories to identify actual weaknesses, not synthetic ones.

Implementation sketch for patch-window use: parameterize a `parametric_opponent` with sliders for `(open_freq, cbet_freq, fold_to_3bet, bluff_freq, agg_factor, ...)`, grid-search the slider space, find the parameter combination that v_current loses to the most. Add that bot to held-out zoo as a sparring partner. Iterate.

---

## Patch 17 — Logistic regression refinements (LR is bounded helper, not engine)

**Modifies:** Section 5 Step 11 of brief; the LR-related parts of v10 (post-Patch 11 reorder).

**Reason:** Plain logistic regression with thin features and unconstrained EV optimization is fragile in poker because (a) linearity-in-log-odds misses non-monotonic and interaction effects, (b) training labels are partially unobservable and selection-biased toward our betting policy, (c) the EV formula uses equity-vs-random when it needs equity-vs-calling-range, (d) opponents are heterogeneous and non-stationary, and (e) errors in bet-size ranking are asymmetrically expensive. Patch 7 partially addressed safety by constraining LR to blueprint-approved sizes. Patch 17 adds feature engineering, training corrections, equity correction, and a stricter support constraint to make the LR component robust.

### Patch 17a — Expanded feature families

Organize features into six explicit groups. Total ~30–35 features before crosses and buckets.

**A. Street and action context:** street one-hot (4), is_preflop_aggressor, is_last_aggressor, facing_cbet, facing_double_barrel, raise_count_this_street (normalized), bet_count_this_hand (normalized)

**B. Pot geometry:** bet_size_fraction_of_pot, amount_to_call_over_pot, effective_stack_over_pot (SPR), bet_size_over_opp_stack, opp_stack_after_call_over_pot, is_all_in

**C. Board texture:** paired_board, monotone_board, two_tone_board, straight_connected_board, A_high_board, K_high_board, draw_completed_turn_or_river

**D. Multiway context:** n_active_opponents, n_players_left_to_act, is_multiway

**E. Position:** in_position, out_of_position, blind_vs_button, is_heads_up

**F. Opponent profile (from Patch 17b):** opponent_vpip, opponent_pfr, opponent_fold_to_cbet, opponent_fold_to_3bet, opponent_aggression_factor, opponent_bluff_propensity, opponent_call_station_score

### Patch 17b — Opponent Bayesian stats as direct LR features

Instead of relying solely on per-opponent `W_DELTA`, pass the current opponent Bayesian stat estimates (means, not CIs) as input features to the global LR. This lets the global model learn population-wide effects ("high-VPIP opponents fold less to large bets") once, applied to every new opponent immediately from their first ~10 hands of stats.

Features are queried from the existing opponent tracker (Patch 1 hand-boundary processing), normalized to `[0,1]`. New opponents with no observation data use the prior means as feature values — safe default.

### Patch 17c — `W_DELTA` as residual correction only

`W_DELTA` is retained but reframed: it's the **residual** per-opponent correction on top of the opponent-stat-aware global model from 17b. With opponent stats already in the features, the residual is much smaller and converges faster on the limited data we have per opponent (~80 hands per match).

```python
def predict_fold_prob(features, opp_id):
    delta = W_DELTA.get(opp_id, np.zeros_like(W_GLOBAL))
    logit = (W_GLOBAL + delta) @ features + B_GLOBAL
    return 1.0 / (1.0 + np.exp(-logit))
```

### Patch 17d — Hand-designed interaction crosses

Add explicit crosses at feature-construction time. The known important interactions:

- `bet_size × street_one_hot` — fold elasticity differs by street (75% pot on flop ≠ 75% pot on river)
- `bet_size × board_wetness_score` — same size means different things on dry vs wet boards (where wetness = monotone + connected + paired flags summed)
- `bet_size × opponent_bluff_propensity` — size pressure matters more vs bluff-catchers
- `bet_size × stack_depth_normalized` — overbets are different at low SPR
- `opponent_vpip × position` — LAGs and nits play position differently
- `position × is_multiway` — positional advantage scales with player count
- `opponent_fold_to_cbet × is_facing_cbet` — direct relevance signal

Adds ~10 features. Captures the most important known interactions without going to full polynomial expansion.

### Patch 17e — Bucket key continuous features for non-monotonic effects

For features with known non-linear or non-monotonic effects, replace the continuous feature with one-hot bucketed features. Each bucket gets its own coefficient, allowing U-curves and other non-monotone shapes while keeping the LR linear in (engineered) features.

- **bet_size buckets:** `{tiny <20%, small 20–45%, medium 45–80%, large 80–120%, overbet >120%}` (5 binary)
- **SPR buckets:** `{<1, 1–3, 3–6, 6–10, ≥10}` (5 binary)
- **opponent_vpip buckets:** `{<15%, 15–25%, 25–40%, 40–60%, >60%}` (5 binary)
- **effective_stack_bb buckets:** `{<10bb, 10–30bb, 30–60bb, 60–100bb, ≥100bb}` (5 binary)
- **pot_size_bb buckets:** `{<5bb, 5–15bb, 15–40bb, ≥40bb}` (4 binary)

Adds ~25 binary features. Default behavior: **replace** the corresponding continuous feature (don't keep both — avoids collinearity).

### Patch 17f — Selection-bias correction in training data

The training data is selection-biased: both we and most enemy-zoo bots bet selectively (mostly with strong hands or in good spots). So the model learns "large bet → fold" when the causal structure is "(strong range × scary board × large bet) → fold." Using this model to evaluate a *bluff* in a new spot overestimates fold equity.

**Required addition to training pipeline:** Build `bots/training_only/uniform_betting_trainer/bot.py` — when it bets, picks bet size uniformly at random from the full size space, decoupling bet size from hand strength. When generating offline training data, mix:

- ~70% normal selective-bet data (from regular enemy-zoo opponents)
- ~30% uniform-bet data (from `uniform_betting_trainer` in the field)

The mixture lets the model:
- Learn typical opponent behavior from the 70% selective data
- Identify the causal size→fold effect independent of range confound from the 30% randomized data

Without this correction, LR-driven bluffing in v10 is dangerous because the model has no data to identify size→fold causally.

### Patch 17g — Equity-vs-calling-range in EV formula

The EV formula:
```
EV(size) = P(fold) * pot + (1 - P(fold)) * [equity * (pot + size) - (1 - equity) * size]
```
requires equity against the **calling range**, not random. When opponent doesn't fold, their range is the strong subset of their pre-call range. Using `equity_vs_random` in this formula systematically overestimates our equity in called scenarios — a bias that compounds with overestimated fold probabilities, making us bet too big and too often.

**Required correction** (start simple, tune by validation):
```python
def equity_vs_calling_range(hero_cards, board, n_opp, fold_prob):
    """
    Approximate equity against the subset of opponent's range that doesn't fold.
    Opponents who fold are weaker; opponents who call are stronger.
    Linear pessimistic correction tuned by validation; default 10pp haircut at 100% fold_prob.
    """
    raw_equity = mc_equity_vs_random(hero_cards, board, n_opp)
    correction = 0.10 * fold_prob
    return max(0.0, raw_equity - correction)
```

More accurate alternative (defer unless v10 validation requires it): sample only from the top `(1 - fold_prob)` percentile of opponent's hand-strength distribution. Requires hand-rank ordering and is more complex; the simple correction above captures most of the benefit at lower cost.

### Patch 17h — Mode 2 only, with support constraint (stricter than Patch 7)

LR is restricted to **Mode 2: redistribute probability among blueprint-approved sizes only**. Patch 7 already constrained LR to blueprint-approved sizes; Patch 17h adds a **support threshold** so LR cannot promote a size from "blueprint barely considers this" to "the chosen action."

The reason: bet-sizing EV is asymmetrically sensitive to ranking errors. If LR mis-ranks a 150% pot bluff above a 50% pot bet because of model misspecification, the cost of that single error can be huge. The support constraint bounds the downside by refusing to consider sizes the blueprint barely supports.

```python
def lr_assisted_bet_size(blueprint_dist, features, opp_id, current_pot,
                         fold_prob_fn, equity_fn):
    """
    blueprint_dist: {size_frac_of_pot: probability} from the blueprint
    Returns chosen bet size as fraction of pot.
    LR may only choose among sizes the blueprint already gives meaningful weight.
    """
    SUPPORT_THRESHOLD = 0.10
    candidate_sizes = [s for s, p in blueprint_dist.items() if p >= SUPPORT_THRESHOLD]

    if len(candidate_sizes) <= 1:
        return sample_from_dist(blueprint_dist)

    n_obs = opponent_observation_count(opp_id)
    if n_obs < 20:
        return sample_from_dist(blueprint_dist)   # insufficient data, defer to blueprint

    # Compute EV for each candidate using 17g calling-range equity
    ev_per_size = {}
    for s in candidate_sizes:
        feat = features_for_size(features, s)
        p_fold = fold_prob_fn(feat, opp_id)
        eq = equity_fn(p_fold)
        bet_chips = s * current_pot
        ev_per_size[s] = (p_fold * current_pot
                          + (1 - p_fold) * (eq * (current_pot + bet_chips)
                                            - (1 - eq) * bet_chips))

    if n_obs < 100:
        # Some data: nudge blueprint probabilities by EV, don't override
        ev_arr = np.array([ev_per_size[s] for s in candidate_sizes])
        ev_norm = (ev_arr - ev_arr.mean()) / (ev_arr.std() + 1e-9)
        weights = np.array([blueprint_dist[s] for s in candidate_sizes]) * np.exp(0.3 * ev_norm)
        weights = weights / weights.sum()
        idx = np.random.choice(len(candidate_sizes), p=weights)
        return candidate_sizes[idx]
    else:
        # Sufficient data: pick max EV, but only among candidate_sizes
        return max(candidate_sizes, key=lambda s: ev_per_size[s])
```

**Hard rule:** LR never picks a size with blueprint probability below `SUPPORT_THRESHOLD`, regardless of predicted EV. This is the strongest safety guarantee in the LR pipeline — it prevents LR from inventing bluff lines or unusual sizings that the blueprint didn't authorize.

### Patch 17i — GBM as conditional fallback only

If LR with 17a–17h fails to achieve required validation accuracy on the held-out enemy zoo, swap LR for a small gradient-boosted tree ensemble (`GradientBoostingClassifier(max_depth=3, n_estimators=50, learning_rate=0.1)`). Trees natively capture non-linearity and interactions, making 17d (crosses) and 17e (buckets) redundant. Cost: more complex extraction to numpy.

**Extraction (offline):** Per tree, store `feature`, `threshold`, `children_left`, `children_right`, `value` arrays in an `.npz`. Inference is a ~20-line pure-numpy tree-walking loop, microseconds per inference. Same support-constraint and Mode-2 boundary as LR — only the predictor inside changes.

**Decision criterion:** Prefer LR with full 17a–17h IF its validation accuracy is within 3 percentage points of GBM's. If GBM beats LR by more than 5pp, switch. **Do not pre-commit to GBM** — it's optionality, not the plan.

### Patch 17 — Summary

LR is a **bounded helper for bet sizing inside Mode 2**, not a decision engine. The decision hierarchy:

1. **Blueprint** decides strategic action family (bet vs check, approximate frequencies)
2. **Opponent stats + entropy gate** control how much LR is trusted (Patch 7 confidence tiers)
3. **LR ranks/nudges sizes** within blueprint-approved support only (17h support constraint)
4. **EV formula** uses calling-range-corrected equity (17g)
5. **Validation** decides whether the feature survives (paired-seed + field-mix gates)

If any layer fails its check (insufficient opponent data, low blueprint support, equity calc timeout, validation regression), LR contribution is silently suppressed and the blueprint distribution is sampled directly. Safe default behavior under all uncertainty conditions.

---

## Patch summary table

| Patch | Bug class | Severity | Brief section affected |
|-------|-----------|----------|------------------------|
| 1 | Silently broken opponent memory after 200 actions | **Critical** | §5 Step 7, §9.6 |
| 2 | Wrong tool for state capture | Medium | §5 Step 1, §8 |
| 3 | Single-source-of-truth blocking | Medium | §5 Step 4 |
| 4 | Over-strict pass criterion | Low | §5 Step 4 |
| 5 | Ambiguous specification | Low | §5 Step 5, §4 |
| 6 | Runtime performance | Medium | §5 Step 7, §9.7 |
| 7 | Overfitting risk in LR sizing | High | §5 Step 11 |
| 8 | Submission risk (sklearn import) | High | §1, §7 |
| 9 | Determinism collision across decisions | **High** | §5 Step 14, §9 |
| 10 | Encoder mismatch with adversarial sizing | Medium | §5 Step 5/8 |
| 11 | Suboptimal priority ordering | Medium | §5 throughout |
| 12 | Format mismatch (ICM vs cash) | Low | §5 Step 14 |
| 13 | Hidden bias in paired comparisons | **High** | §5 Step 2a, §6 |
| 14 | False positives in fuzzer | Medium | §5 Step 2b |
| 15 | Submission-day mistake risk | High | §5 Step 14 |
| 16 | Zoo coverage gaps and missing field-mix metric | **High** | §5 Step 2c, §6 |
| 17 | LR brittleness: linearity, selection bias, calling-range equity, scope creep | **High** | §5 Step 11; v10 |
| 19 | Final pre-submission rigorous multi-version validation (trimmed ~5h, dynamic candidates, punt audit, emergency rule) | **High** | §5 Step 14; post-v12 |

End of additional instructions.

---

## Patch 19 — Final pre-submission rigorous validation phase

**Modifies:** Section 5 Step 14 of brief; extends the v12 hardening phase with a dedicated multi-version + parametric-grid evaluation that DECIDES what we submit.

**Reason:** Per-version paired-seed validation tells us "v_N+1 beats v_N." It does NOT tell us "v_N is the right version to submit." Late versions sometimes regress in subtle ways against opponent profiles we never benchmarked. Before submission, we need a comprehensive evaluation that compares multiple candidate versions against a much broader opponent space than our hand-built zoo and a single field distribution. This is the **submission-decision phase**, not just a hardening checkpoint.

**When this fires:** After v12 hardening is complete and validator/fuzzer pass. Replaces the "pick the version with highest robust score" line in v12 with a structured multi-version comparison.

### Patch 19a — Build the ParametricOpponent class

`bots/enemy_zoo/parametric_opponent.py` (~200 lines). Single configurable class:

```python
class ParametricOpponent:
    """
    Configurable opponent. All behaviors driven by parameters.
    Used both for adversarial-weakness search and for grid-sweep validation.
    """
    PARAMETERS = {
        # Preflop
        'vpip': float,                  # 0.0 to 1.0
        'pfr': float,                   # 0.0 to 1.0 (must be <= vpip)
        'threebet_freq': float,         # 0.0 to 0.5
        'fold_to_3bet': float,          # 0.0 to 1.0
        # Postflop aggression
        'cbet_freq': float,             # 0.0 to 1.0
        'fold_to_cbet': float,          # 0.0 to 1.0
        'aggression_factor': float,     # 0.0 to 5.0 (bets+raises / calls)
        # Sizing
        'sizing_profile': str,          # 'standard' | 'small' | 'large' | 'overbet' | 'min_raise' | 'tiny_block'
        # River
        'river_bluff_freq': float,      # 0.0 to 0.5
        'river_call_freq': float,       # 0.0 to 1.0
        # Special behaviors
        'trap_freq': float,             # 0.0 to 0.3 (check-raise frequency)
        'donk_freq': float,             # 0.0 to 0.4
        'short_stack_jam_freq': float,  # 0.0 to 1.0 when effective < 15bb
    }

    def __init__(self, **params): ...
    def decide(self, state): ...
```

The `decide()` method implements a strategy whose every behavioral knob is set by parameters. Postflop logic uses simple equity buckets (low/mid/high) crossed with the parameter set to produce mixed strategies. ~200 lines total.

### Patch 19b — Define the comprehensive test opponent set

Three sources of opponents for the final phase:

**Source 1: Existing zoo + reference bots (17 opponents).** All 12 enemy zoo bots from Patch 16 + the 5 reference bots.

**Source 2: Parametric grid (30 opponents).** Defined by a fixed grid of parameter combinations covering key axes:

```python
PARAMETRIC_GRID = [
    # Format: (name, params dict)
    ('grid_nit',              {'vpip': 0.12, 'pfr': 0.10, 'fold_to_cbet': 0.75, 'aggression_factor': 0.5,  'sizing_profile': 'standard'}),
    ('grid_tag',              {'vpip': 0.22, 'pfr': 0.18, 'fold_to_cbet': 0.55, 'aggression_factor': 2.5,  'sizing_profile': 'standard'}),
    ('grid_lag',              {'vpip': 0.35, 'pfr': 0.28, 'fold_to_cbet': 0.45, 'aggression_factor': 3.5,  'sizing_profile': 'large'}),
    ('grid_maniac',           {'vpip': 0.80, 'pfr': 0.60, 'fold_to_cbet': 0.20, 'aggression_factor': 4.5,  'sizing_profile': 'overbet'}),
    ('grid_station',          {'vpip': 0.70, 'pfr': 0.05, 'fold_to_cbet': 0.15, 'aggression_factor': 0.3,  'sizing_profile': 'standard'}),
    ('grid_overfolder',       {'vpip': 0.18, 'pfr': 0.15, 'fold_to_cbet': 0.90, 'aggression_factor': 1.5,  'sizing_profile': 'standard'}),
    ('grid_passive_caller',   {'vpip': 0.40, 'pfr': 0.10, 'fold_to_cbet': 0.30, 'aggression_factor': 0.6,  'sizing_profile': 'small'}),
    ('grid_aggro_3bettor',    {'vpip': 0.25, 'pfr': 0.22, 'threebet_freq': 0.25, 'fold_to_cbet': 0.50, 'aggression_factor': 3.0, 'sizing_profile': 'standard'}),
    ('grid_trapper',          {'vpip': 0.20, 'pfr': 0.15, 'trap_freq': 0.25, 'fold_to_cbet': 0.40, 'aggression_factor': 1.2, 'sizing_profile': 'standard'}),
    ('grid_donker',           {'vpip': 0.30, 'pfr': 0.20, 'donk_freq': 0.30, 'fold_to_cbet': 0.55, 'aggression_factor': 1.8, 'sizing_profile': 'standard'}),
    ('grid_min_raiser',       {'vpip': 0.45, 'pfr': 0.40, 'sizing_profile': 'min_raise', 'aggression_factor': 2.5, 'fold_to_cbet': 0.40}),
    ('grid_tiny_blocker',     {'vpip': 0.30, 'pfr': 0.22, 'sizing_profile': 'tiny_block', 'aggression_factor': 1.5, 'fold_to_cbet': 0.50}),
    ('grid_polarized',        {'vpip': 0.20, 'pfr': 0.18, 'sizing_profile': 'large', 'aggression_factor': 2.8, 'fold_to_cbet': 0.55, 'river_bluff_freq': 0.30}),
    ('grid_short_jammer',     {'vpip': 0.50, 'pfr': 0.40, 'short_stack_jam_freq': 0.90, 'aggression_factor': 2.0}),
    ('grid_modal_llm_a',      {'vpip': 0.25, 'pfr': 0.20, 'cbet_freq': 0.70, 'fold_to_cbet': 0.55, 'sizing_profile': 'standard', 'aggression_factor': 2.0}),
    ('grid_modal_llm_b',      {'vpip': 0.28, 'pfr': 0.22, 'cbet_freq': 0.75, 'fold_to_cbet': 0.50, 'sizing_profile': 'standard', 'aggression_factor': 2.2}),
    ('grid_modal_llm_c',      {'vpip': 0.20, 'pfr': 0.16, 'cbet_freq': 0.65, 'fold_to_cbet': 0.60, 'sizing_profile': 'standard', 'aggression_factor': 1.8}),
    # ... extend to 30 covering important corners
]
```

Pick 30 combinations to cover: nit/tag/lag/maniac/station axis, overfolder/sticky-caller axis, sizing-profile axis, special-behavior axis (trapping/donking/short-jamming), modal-LLM cluster (multiple variants).

**Source 3: Adversarial-search winners (3-5 opponents).** After the grid sweep on the candidate versions is done, identify the 3-5 parametric profiles that hurt our top candidate the most. Re-run with those specific opponents at higher seed count to get tight confidence intervals on the worst-case performance.

**Total test opponent count:** 17 + 30 + ~5 = ~52 opponents.

### Patch 19c — Multi-version evaluation (trimmed)

Pick **2 candidate versions** for the final shootout. Selection is **dynamic**, not fixed:

- **Candidate A** = the final shipped version (whatever v12 ended up as)
- **Candidate B** = the strongest simpler stable version BEFORE the highest-risk feature in Candidate A

The reason for dynamic selection: if v12 = v10 plus the LR layer and v11 LP solver was implemented but didn't make the final cut, then v12 might effectively be v10 with the LR layer bolted on. The comparison should isolate "did the risky feature actually help?" not "did v10 vs v12 differ at all."

Worked examples:
- If Candidate A contains LR (the highest-risk feature), **Candidate B = v9** (last pre-LR version)
- If Candidate A contains LP solver but not LR, **Candidate B = v10** (last pre-LP version)
- If Candidate A reverted both LR and LP, **Candidate B = v8** (last pre-blocker-aware version)

(v8 sanity baseline is verified separately via 19e cross-version round-robin at much lower cost — no need to run it through the full grid unless it IS Candidate B.)

**Test opponent count (trimmed):** 25 opponents total
- 12 enemy zoo bots (all from Patch 16)
- 5 reference bots
- 8 most-orthogonal parametric grid instances (instead of 30):
  - `nit_overfolder` (extreme tight passive)
  - `tight_aggressive_reg` (standard online-pro profile)
  - `loose_aggressive_maniac` (extreme aggro/wide opening)
  - `loose_passive_station` (calls everything, never raises)
  - `modal_llm_chartbot` (standard 33/66/pot LLM-template)
  - `pot_odds_overfolder` (folds tight, calls only on great pot odds)
  - `weird_sizing_polar` (extreme bet sizes, polarized range)
  - `multiway_limper_station` (limps wide, multiway weakness exploiter)

These 8 are chosen for orthogonal coverage — each tests a distinct mechanism rather than overlapping categories.

For each candidate version, run:
- **15 paired seeds** against each test opponent (instead of 30 — accepts wider CIs in exchange for time)
- **400 hands per match** (full qualifier length)
- **Standardized seat and bot_id** per Patch 13

Per-version reports:
- Per-opponent mean/median/p5/p95 chip delta
- Overall: median, p5, robust_score, farm_score (per Patch 18f weak-field def)
- Crashes/timeouts/invalid-actions (must all be zero)
- p99 decision time (must be ≤1200ms)

**Compute budget:** 2 versions × 25 opponents × 15 seeds × ~15 sec/match ≈ **3.1 hours wall-clock**. After picking the finalist, optionally run an additional 15 seeds (so finalist has 30 total) against the 17 fixed opponents for tighter confidence (~1 hour). Default budget: **~3-4 hours.**

### Patch 19d — Cross-distribution field-mix shootout (trimmed)

Run field-mix simulation (Patch 16b / 18g) against TWO distributions, both candidate versions:

```python
FIELD_DISTRIBUTIONS = {
    'primary':       # the main Patch 16b weighting — best-guess realistic field
    'llm_heavy':     # 50% modal_llm variants, 20% pot-odds, 15% chartbot, 10% standard, 5% other
                     # represents the failure mode where field is more LLM-template-heavy than expected
}
```

The `conservative` distribution is dropped — primary already includes solver_approximator at 25% weight, and the marginal info from running it separately doesn't justify the compute cost.

For each candidate version × each distribution:
- **40 tables × 400 hands** (instead of 100 — gives reasonable cumulative-delta confidence)
- Report: cumulative_delta, mean_per_table, median, p5, robust_score, farm_score, tables_with_positive_delta

**Compute budget:** 2 versions × 2 distributions × 40 tables × ~30 sec/table ≈ **1.3 hours**.

### Patch 19e — Cross-version round-robin sanity check

Run `sandbox/cross_version.py` (Patch 16c) once with v0, v2, v5, v8, v10, v12 seated at the same 6-bot table with the 30-seed table sweep. Verify:

- Each later version has **strictly higher cumulative delta** than each earlier version
- No "leapfrog regressions" (e.g., v8 unexpectedly losing to v5)

If any monotonicity violation, **investigate before submitting** — likely indicates a silent regression that paired-seed benches missed.

**Compute budget:** 1 round-robin × 30 seeds × ~30 sec ≈ 15 minutes.

### Patch 19f — The decision matrix

After 19c, 19d, 19e complete, evaluate candidates on these criteria in priority order:

**Tier 1 — Hard gates (any failure disqualifies the candidate):**
- Zero crashes / zero timeouts / zero invalid actions across ALL test runs
- p99 decision time ≤ 1200ms across all runs
- Cross-version round-robin shows no monotonicity violation
- Pre-submission safety audit (Patch 15) checklist 100% complete

**Tier 2 — Performance ranking:**
For each candidate version, compute:
```
composite_score = 0.50 * robust_score_primary_field
                + 0.20 * robust_score_llm_heavy_field
                + 0.15 * farm_score
                - 0.15 * normalized_punt_penalty
```
Where `normalized_punt_penalty = (number of matches where chip_delta < -7000) / (total_matches * 0.1)` — scales so a 10%-punt-rate is "1.0 of penalty" magnitude.

Higher composite_score is better.

**Tier 3 — Worst-case constraint (median-based, not raw minimum):**
Reject any candidate where ANY of the following are true:
- **Median delta against any opponent type < -3000 chips** (consistent loser pattern, not single-seed noise)
- **p5 against any common field opponent (the 17 zoo+reference set) < -6000 chips** (catastrophic 1-in-20 outcomes)
- **Punt count materially higher than Candidate B** (catastrophic-loss rate worse than the simpler stable version, by more than 1.5×)

Using median instead of raw minimum prevents one unlucky 400-hand run from triggering false-positive rejection. With only 15 seeds per opponent, raw minimum is too noisy to trust.

**Final pick:** Highest composite_score among Tier-1-passing, Tier-3-passing candidates.

### Patch 19g — Output a submission readiness report

At the end of the validation phase, produce a single file `SUBMISSION_REPORT.md` summarizing:
- Which version was picked and why
- Per-version composite scores
- Worst-case opponent for each candidate (for awareness during qualifier)
- Any opponent type where chip delta is consistently negative (so we know our blind spots before D1)
- All Tier-1 hard-gate checks (each marked pass/fail)
- Total compute hours spent in validation
- Final fuzzer + validator status

This report goes into the working folder and stays as a paper trail. Useful during the patch window — when D1 hand histories arrive, we know what we expected to be weak against and can verify whether those weaknesses materialized.

### Patch 19h — Time discipline (trimmed default ~5 hours)

The trimmed phase is **budgeted at ~4-5 hours of wall-clock benchmark time** — fits a half-day or single overnight window:

| Component | Trimmed time |
|-----------|--------------|
| 19a — Build ParametricOpponent class | ~1 hour (parallel with 19c launch) |
| 19b — Define 8-opponent parametric grid | ~30 min |
| 19c — Multi-version evaluation (2 versions × 25 opponents × 15 seeds) | **~3.5 hours** |
| 19d — Field-mix shootout (2 versions × 2 distributions × 40 tables) | **~1.3 hours** |
| 19e — Cross-version round-robin | ~15 min |
| 19g — Generate SUBMISSION_REPORT.md | ~10 min |
| **Total wall-clock** | **~5 hours** (compute happens in parallel where possible) |

**Recommended schedule:**
- v11/v12 implementation completes morning of Day 3
- Afternoon Day 3: build 19a + 19b (~1.5 hours), then launch 19c+19d in background (~4 hours total) — can run unattended
- Evening Day 3: review SUBMISSION_REPORT.md, run 19e + safety audit (~30 min), finalize pick, submit

**Further truncation if pressed (in order — field-mix is preserved as long as possible):**
1. First cut: drop the post-finalist 15-seed extra pass (saves ~1 hour) → ~4 hours
2. Second cut: reduce parametric opponents 8 → 5 (saves ~30 min) → ~3.5 hours
3. Third cut: reduce field-mix tables 40 → 25 (saves ~30 min) → ~3 hours
4. Fourth cut: reduce paired seeds 15 → 10 (saves ~1 hour) → ~2 hours
5. Fifth cut: drop second field distribution (llm_heavy), keep primary only (saves ~40 min) → ~1.3 hours
6. **DO NOT drop primary field-mix unless truly emergency** (<1 hour total)

**Rationale for this order:** field-mix is the closest proxy for actual qualifier conditions. Per-opponent paired tests are more about isolating mechanisms than predicting field performance. When time-constrained, preserve realism (field-mix) over mechanistic isolation (paired-seed). The original truncation order allowed cutting field-mix too aggressively; this revised order protects it.

**DO NOT skip under any circumstances:**
- Cross-version round-robin (19e) — 15 minutes, catches silent regressions
- Pre-submission safety audit (Patch 15) — minutes, catches submission-blocker bugs
- Final validator + fuzzer runs — minutes, validates the submitted bot

**Compute-saving notes for Claude Code:**
- 19c batches across opponents — can launch as separate background processes if hardware allows parallel matches (cuts wall-clock further)
- The bot is single-threaded, so multiple matches can run in parallel up to core count
- Use `--seed` deterministically so failed/restarted runs don't waste seeds

**If we genuinely have <1 hour for validation:**
Run only: 19e (round-robin, 15 min) + 19d primary distribution only (~40 min) + safety audit (~5 min). This is the bare-minimum trustworthy pre-submission check. Skip 19c entirely. Pick whichever candidate version (Candidate A or B) has better field-mix score.

### Patch 19i — Large-pot punt audit

Add to `sandbox/bench.py` a per-match catastrophic-loss tracker. Extend the result dict to include:

```python
# In bench.py result aggregation, alongside existing per-seed deltas:
punt_matches = sum(1 for d in per_seed_deltas if d < -7000)
near_punt_matches = sum(1 for d in per_seed_deltas if -7000 <= d < -4000)
worst_match_delta = min(per_seed_deltas)
```

Report in 19c output per candidate version:
- Total matches with `chip_delta < -7000` (true punts — catastrophic single-match losses)
- Total matches with `chip_delta` in `(-7000, -4000)` (near-punts)
- Worst single-match delta
- Per-opponent breakdown of punt counts (which opponents cause the worst losses)

**Why it matters:** In a 400-hand chip-delta tournament, a single catastrophic match can erase many small wins. A candidate with better mean EV but more punts may finish worse than a less-flashy candidate. This audit surfaces the variance profile that aggregate stats hide. Patch 17h's confidence-gating and Patch 32's variance buffer should keep punts rare, but we verify empirically.

**Soft gate:** Already folded into Tier 2 composite_score via the `normalized_punt_penalty` term and into Tier 3 as "punt count materially higher than Candidate B." Patch 19i just ensures the metric is actually computed and reported, not silently dropped.

**Implementation cost:** ~5 lines in `bench.py` result aggregation. No new infrastructure. The data is already available; we just count it differently.

### Patch 19j — Emergency submission decision rule (paralysis prevention)

When validation results are ambiguous or time is too short for full analysis, apply this deterministic if-then to pick the submission:

```
if Candidate_A has any Tier-1 hard-gate failure (crash / timeout / invalid action / p99 > 1200ms):
    submit Candidate B
elif Candidate_A composite_score - Candidate_B composite_score > 0.5:
    submit Candidate A  (clear winner)
elif Candidate_A field_mix_robust_score > Candidate_B by >5%:
    submit Candidate A
elif Candidate_A has worse p5 delta OR materially more punts than Candidate_B:
    submit Candidate B  (simpler stable version, safer choice)
elif Candidate_A farm_score > Candidate_B by any margin:
    submit Candidate A
else:
    submit Candidate B  (default to simpler/safer when results are a wash)
```

**Why this exists:** When data is ambiguous and time is short, decision paralysis is a real failure mode — Ali staring at p-values at 11pm on submission day is not where we want to be. This rule provides a deterministic fallback that biases toward safety (Candidate B, the simpler stable version) when there's no clear winner. It's not provably optimal in expectation, but it's robust to "we ran out of time" scenarios and removes judgment-call burden.

**When to use this rule:**
- Composite scores are within 0.3 of each other (ambiguous ranking)
- Less than 30 minutes remain before submission deadline
- Field-mix results are inconsistent across distributions (A wins primary, B wins llm_heavy or vice versa)

**When NOT to use:**
- Composite score gap > 0.5 (clear winner, just pick higher — don't overthink)
- Plenty of time to investigate further (do that instead — rerun marginal benches with more seeds)
- Both candidates fail Tier 1 hard gates (don't pick either; debug and submit older known-good version like v8)

### Patch 19 — Summary

The final validation phase is a **submission-decision tool**, not just another benchmark. Per-version paired-seed comparisons during development can hide:
- Subtle regressions only visible against the broader opponent space
- Catastrophic blind spots against opponent profiles we never tested
- Monotonicity violations where later versions are actually worse
- Field-distribution sensitivity (a version that wins primary distribution but loses LLM-heavy distribution is fragile)

This phase exposes those issues by combining: parametric grid sweep (broader opponent coverage), cross-distribution field-mix (multiple field weightings), cross-version round-robin (monotonicity), and adversarial worst-case (downside bound). The composite scoring + Tier-3 worst-case constraint chooses the version that's both strong on average AND robust to adversarial corners.

If we have the validation rigor to do this right, the submitted bot is much more likely to be the genuine best choice rather than the latest implemented version.
