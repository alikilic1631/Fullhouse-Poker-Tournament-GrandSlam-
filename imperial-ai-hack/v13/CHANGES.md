# v13.1: v11.1 plus data-checked exploits (the Desktop `bot.py` since 01:30 Sunday)

**File:** `v13/bot.py`, SHA-256 `26c933256cba8f0c…`, 92.9 KB.

**Based on:** v11.1 (`v11/bot.py`, `a635c437…`; see `../v11/CHANGES.md`).

**Ideas came from:** overnight web research (pokerbot competitions, pool-exploit literature, opponent modelling). Each idea was then checked against the 55 real round logs and a replay of the bot itself.

## Changes

| Switch | State | What it does | Real-log evidence |
|---|---|---|---|
| `V13_LINE_BLUFF` | **ON** | Heads-up turn/river bluff caps depend on the betting line: 0.70 when the villain gave up; 0.70 on the turn / 0.80 on the river after a checked-through street; 0.45 for an in-position barrel; 0.38 for out-of-position barrels and leads, which must also be at least 0.6 pot. Bluffs into capped ranges may be up to 1.05 pot. | Heads-up fold-out by line (turn / river): gave-up 65.5 / 67.6%; checked-through in position 68.2 / 80.1%; checked-through out of position 59.6 / 67.9%; barrel out of position 32.3 / 37.7%; our ≤0.45-pot out-of-position barrels 15%. Valued by the poker reviewer at +1.4 to +1.7 bb/100, and still +0.6 to +0.9 if every fold rate were 10 points lower. |
| `V13_4BET_WIDE` | **ON** | When **we** opened and the 3-bettor is a measured 4-bet folder (≥5 observations, folds ≥75%) who 3-bets our opens ≥15%: wider 4-bet bluff hands and u ≤ 0.75. | FisherMen folds 83% to 4-bets (n=125) and 89.5% to ours (n=38), never 5-bets, no in-round adaptation. It 3-bets our opens 29–38%, ramping 18% → 40% within a round. No other Table C team passes the gate. |
| `V13_WEAKPAIR` | **ON** | Heads-up river bet of at most 0.55 pot: call with a pair that uses a hole card if uh ≥ 0.57 and the call is under 30% of the stack (never when the board plays). | Field small river bets are 35% air. Review fix: Table C bets are more honest (18% air), so the uh ≥ 0.57 floor keeps only the profitable calls. |
| `V13_RIVER_BLSH` | off | River air share by bet size in the range model | No evidence at Table C (review). |
| `V13_IP_RAISE` | off | Raise a measured raise-folder's led flop/turn bet | The gate never fires against Table C (review). |

**Review fixes in v13.1** (3 independent reviewers: correctness, poker logic, robustness/timing):
- **Line label:** a previous street's checks no longer count. Checked-through out-of-position spots keep the benched caps and sizes, so there are 0 decision changes against benched v13.
- **Weak-pair calls:** strength floor, size cap and the board-plays check.
- **4-bet widening:** only when we opened.
- `RIVER_BLSH` and `IP_RAISE` switched off.

## Validation

All tests are paired against v11.1 on identical deals, in bb/100 with all-in luck removed.

| Test | v13.1 minus v11.1 |
|---|---|
| `duel.py` Sunday table, deals 201 / 301 / 401 (240 pairs each) | **+2.2 ±0.6** (z 3.7) / **+2.3 ±0.6** (z 3.1) / +1.2 ±0.7 (z 1.8); pooled about +1.9, z ≈ 5 |
| `duel.py --field 6`, random 7-seat tables | **+1.8 ±0.9** (z 2.0) |
| `simreal.py`, the 36 real line-ups (vs v10) | **+8.0 ±1.2** (v11.1: +5.7 to +7.5) |
| `replaydiff.py`, 46,342 real decisions | EXACT +0.20, APPROX +0.47 |
| Per opponent at Table C | All positive: FisherMen +0.5, 85p +0.5, Market Makers +0.4, … |
| Strict official engine, 10 ms / 5 s bank, 6 load processes, 4 rounds | **0 misses**; max 3.9 ms |
| Emulated slow server K = 6 / 10 | Same tail as v11.1 (paired, within noise) |
| Reviewer timing study (min of repeats, adversarial tables, K = 10) | v13 vs v11.1 max 11.16 vs 11.35 ms; no timing cost (+2 µs per postflop decision) |
| Fuzz, 34,531 decisions on mixed tables + about 117,000 in the review | 0 exceptions, 0 fallbacks, 0 invalid actions |

**Expectation:** the bench overstates absolute levels. Real gain over v11.1 is likely about +1 to +2 bb/100, plus the FisherMen 4-bet edge, which the static bench cannot value.

**Fallback:** `~/Desktop/bot_v11_backup.py` = v11.1.
