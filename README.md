
# GrandSlam — Fullhouse Poker AI Tournament Bot

A multi-table no-limit hold'em poker bot built for the Fullhouse 2026 Tournament Finals.

GrandSlam is a layered decision engine combining adaptive Monte Carlo equity estimation, Bayesian opponent stat tracking, and a series of empirically-validated structural guards. Each layer addresses a specific leak identified through quantitative analysis of qualifier match data, and every shipped patch was validated against three independent test populations before integration.

---

## Overview

The bot is designed for a tournament environment with:

- 768 MB RAM limit per Docker container
- 0.5 CPU allocation
- 2-second wall-clock limit per decision (engine kills the bot on overrun)
- Read-only filesystem, no network access
- Python 3.10 + eval7 0.1.7, numpy, scipy, treys, scikit-learn

GrandSlam stays well within these limits in practice — the shipped version uses peak ~110 MB RAM and a p99 decision time around 700 ms, leaving substantial headroom for future work.

---

## Architecture

### Core engine

- **Adaptive Monte Carlo equity** with Wilson confidence interval early termination and per-decision time budgeting. Critical river decisions receive up to 1.5 s of compute; routine spots terminate within 200 ms. The budget allocation is K-aware: when downstream stack-off simulation is likely to fire, equity calculation reserves room for it rather than consuming the full wall.
- **Bayesian Beta(α,β) posteriors** for per-opponent statistics. Observation counts are smoothed toward population priors with explicit confidence weighting, preventing overfitting to the first few hands against any opponent.
- **Precomputed equity tables** (~90 KB total) covering 169×169 preflop matchups, vs-N-random equity grids, postflop hand-class vs board-texture lookups, and a 6-matchup deep-stack reference.
- **RIO_INDEX** (Reverse Implied Odds): a precomputed table of dominated-continuing-range fractions per (hand_class, board_texture, street, SPR), loaded at startup and consulted as an additive term in the nut_danger score.

### Decision pipeline (in order)

1. **Patches A through E** — Original v14 governors. Nut_danger scoring, worse-hands-that-call filter, street-specific commitment thresholds, trap-line dampener.
2. **RIO upstream of K** — The RIO table modifies nut_danger before the stack-off governor consumes it, allowing structural board-context information to influence whether Patch K fires at all.
3. **Patch K — Stack-off EV simulation** — On commit-fraction ≥ 0.40 decisions, enumerates candidate actions, runs MC rollouts against the opponent's observed-stat-weighted continuing range, and selects the max-EV action under a hard 500 ms budget.
4. **v15.10c — River-card-creates-pair transition guard** — Caps aggression when the river card pairs a previously unpaired board rank and hero lacks a full house or better.
5. **v15.10d — Multiway paired-river super-cap** — In 3+ player active pots on paired rivers, caps aggression when hero is below trips. Stricter protection than the heads-up version because multiway continuing ranges are structurally stronger.
6. **v15.12b — Preflop multi-raiser all-in guard** — Downgrades to fold when facing a 3-bet+ pot with all-in commitment and hero hand outside the premium set (JJ+, AK).

Each layer fires on a narrow conjunction of conditions and can be disabled independently for ablation studies.

---

## Performance

Cumulative gains across the shipped patch stack, measured on paired-seed bench against three independent populations:

- **Held-out enemy zoo**: net positive on every shipped patch, no regressions on median, mean, or catastrophic tail (p5)
- **Caricature regression suite**: net positive, no individual cluster regressions
- **solver_approximator HU**: neutral on every shipped patch, no regressions

The shipped bot has zero documented robustness regressions across 20,000+ fuzz states (no crashes, timeouts, or invalid actions returned).

---

## Repository layout

```
submission/
  bot.py                    # Final shipped bot (stripped, production-ready)
  submission_*.zip          # Versioned submission artifacts
  data/
    equity_tables.npz       # Precomputed equity lookups
    rio_index.npz           # Reverse-implied-odds table
fullhouse-engine/
  bots/v15_<n>/bot.py       # Canonical commented sources per version
training/                   # Offline table generation scripts
validation/                 # Paired-seed bench logs and validation matrices
prevmatches/                # Qualifier match JSON (analysis input)
SUBMISSION_REPORT.md        # Patch-by-patch validation history
V13_WEAKNESS_CATALOG.md     # Catalog of identified leaks
FAILURE_MODES.md            # Documented failure patterns and counter-mechanisms
PATCH_WINDOW.md             # Notes on patch-window discipline and scheduling
```

---

## Build and run

The bot is designed to run inside the Fullhouse tournament Docker sandbox. For local development:

```bash
# Install Python 3.10 and the required libraries
pip install eval7==0.1.7 numpy==1.26.4 scipy==1.13.0 treys==0.1.8 scikit-learn==1.5.2

# Run the bot against the engine's test harness
python submission/bot.py

# Build a submission zip
bash build_submission_zip.sh
```

The offline table-generation scripts in `training/` regenerate `equity_tables.npz` (~7 minutes) and `rio_index.npz` (~30-45 minutes) from scratch. They are not needed for normal use because the prebuilt tables ship in `submission/data/`.

---

## Methodology

GrandSlam was developed under strict revert-on-failure discipline. Every patch was implemented as an independent layer that could be sanity-tested in isolation and reverted without disturbing upstream baselines. The shipped versions represent the intersection of two conditions: evidence-backed in qualifier match data AND validated against the bench suite without regression. The intersection is substantially smaller than what was attempted.

### Validation framework

Every shipped layer was validated via paired-seed simulation against three independent test populations. Validation gates required:

- Zero robustness regressions (crashes, timeouts, invalid actions, p99 timing)
- Held-out median greater than or equal to baseline
- Catastrophic tail (p5) preserved within tolerance
- Caricature mean within tolerance and no individual cluster regression beyond threshold
- Mechanism-evidence diagnostics — action-category count reductions confirming the patch fires on the intended pattern

Ship decisions used the conjunction of these gates. Borderline cases were allowed to ship only if both held-out and caricature signals were within noise AND the mechanism diagnostic confirmed the patch was working as designed.

### Documented negative results

Eight attempted patches were implemented, validated, and reverted. Each is preserved in the source tree as a research checkpoint with its failure mode documented in `SUBMISSION_REPORT.md`:

- **v15.7** — K confidence gate. Premise (K's marginal calls were the caricature leak) turned out wrong on validation.
- **v15.8** — Range/nut advantage modulation. 42.8% fire rate was too broad; offline range priors didn't generalize to held-out opponents.
- **v15.9+** — Called stack-off sanity gate. Misclassified correct stack-offs as catastrophic; 0.54% fire rate but each fire was on the wrong spot.
- **v15.10a** — Paired-river hard commit cap. Broad trigger over-folded +EV continues despite passing sanity inspection.
- **v15.11a** — Backdoor flush completion guard. Capped straights too aggressively.
- **v15.11b** — Standard flush completion guard. Trigger too rare to fire in validation.
- **v15.11c** — Counterfeit guard. Caricature opponents bluff into trips/double-paired boards more than the patch assumed.
- **v15.11d** — Straight completion guard. Bench-noise neutral; failed strict gate but within paired W/L tolerance.
- **v15.12a** — Flop deep-stack all-in cap. Reverted before v15.12b shipped.

### Key lessons logged

1. **Narrow structural triggers outperform broad heuristic modulation.** v15.10a (any paired river) reverted; v15.10c (river card creates the pair) shipped on the same protected-hand condition.
2. **Transition-state triggers outperform static-state triggers.** Patches that detect a state change between streets (turn-to-river) catch traps that static patches miss.
3. **Action-type-specific caps outperform aggression-class caps.** Capping `all_in` specifically (v15.12b) preserves the bot's pressure engine; capping all aggression on a dangerous board (v15.10a) over-folds.
4. **Validation suite is insensitive to certain qualifier-data leaks.** When the held-out and caricature suites cannot detect a real leak, the only ship criterion is mechanism evidence (the patch fires on the intended pattern and reduces the targeted action category count).

---

## What did not get done

A backlog of high-potential patches was scoped, designed, and prompt-written but ran out of validation time before finals:

- **Pre-river deep-stack all-in discipline** beyond v15.12b. A 934k-chip leak across 40 hands was identified in qualifier data; only the preflop layer (v15.12b) shipped. The flop and turn layers remain as v16 work.
- **Called-branch strength model.** Per-opponent fold-rate-to-large-bet tracking with confidence weighting. The cleanest adaptive-modeling idea that fits within the validation framework.
- **Fold-equity pressure curves.** Per-opponent, per-bet-size-bucket fold-rate estimation feeding bet size selection. Highest theoretical upside, highest implementation risk.

The repository is structured so these can be picked up directly: the patch-window discipline, validation matrices, and revert-on-failure tooling are all in place.

---

## Constraints reminder

This bot is engineered for a specific tournament sandbox:

- Hard 2-second wall-clock per decision
- 768 MB RAM, 0.5 CPU
- Read-only filesystem
- Python 3.10, fixed library set
- No network access

The decision pipeline is designed to fail open on any exception path. Eval errors, missing tables, and unexpected state shapes all return the no-modification branch rather than raising. This makes the bot robust to environmental surprises at the cost of occasionally letting a problematic decision through to the next governor layer.
