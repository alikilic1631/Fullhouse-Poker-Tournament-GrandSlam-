# v15 = v14 + line-aware heads-up flop bluffing out of position (built Sun 15 Nov, 03:30) — NOT ADOPTED

> **Outcome (03:58): not adopted; the Desktop stays on v14.**
>
> v15 was picked out of six variants because it led on deal sets 201–701 (+0.54 ± 0.25). On **six fresh deal sets** (801–1301) that played no part in choosing it, it measured **−0.02 ± 0.25 vs v14** (FisherMen 0.00), and the static bench over 6 sets gave +0.01 ± 0.25. All 12 adaptive sets together: +0.26 ± 0.17 (z 1.5), which is inflated by the selection.
>
> **What this means:** the first-round lead was a winner's-curse effect. The real-log replay agrees: the reviewer's poker lens found the net effect of the out-of-position change on 46,342 real decisions to be about zero.
>
> **Is the file safe?** Yes: three-lens review says "ship", all upload checks pass (strict timing 0 timeouts, real limits 0, fuzz 0 errors). It is simply not better than v14.

**File:** `v15/bot.py`, SHA-256 `ed9f37225241273b…`, 96.2 KB.

**Built from:** `testbench/out/v15/v15c.py` (scratchpad `make_v15.py`, variant c). Only the first docstring line was changed.

**Base:** v14, see `../v14/CHANGES.md`.

## The change (`V15_FLOP_LINE`, `V15_CAP`, `V15_OOP_MIN`)

**Where it applies:** heads-up flop spots where nobody has bet yet. The bot now classifies the betting line, using the preflop aggressor `self.agg[0]` and whether the villain has already checked to us on this street.

| Line | v14 bluff cap | v15 bluff cap | Field fold-out to first bets of 0.6–0.85 / 0.85–1.1 pot (R1–R54, all teams) |
|---|---|---|---|
| c-bet in position (he checked to us, we raised preflop) | 0.55 | 0.55 (unchanged) | 69% / 75% |
| stab in position (he raised preflop and checked) | 0.55 | 0.55 (unchanged) | 55% / 74% |
| **c-bet out of position** (we raised preflop and act first) | 0.55 | **0.45** | 44% / 51% |
| **lead into the preflop raiser** (donk) | 0.55 | **0.30** | 37% / 45% |

**Extra rule:** out of position, pure-air bluffs (`eq_all < 0.30`) must be at least **0.85 pot**. Semi-bluffs and value bets are unaffected.

**Why:** v14 had allowed pot-size bluffs out of position on the flop. An independent reviewer flagged this: the field folds only 43–50% there, and v14's fold model over-predicts folds in these spots by 12–18 points (replay calibration). Its in-position spots are calibrated.

## Evidence

| Test | v15 vs v14 (bb/100, paired, all-in luck removed) |
|---|---|
| Adaptive Table C bench, deals 201 / 301 / 401 / 501 / 601 / 701 | +0.6 / +1.0 / +0.3 / +0.2 / +0.2 / +0.9; pooled over 1,440 pairs **+0.54 ± 0.25, z 2.2** |
| Per opponent (adaptive, 6 sets) | **FisherMen +0.31 ± 0.12 (z 2.6)**, Joca +0.15, Jump Street +0.13, 85p +0.02, The Market Makers 0.00, Claudebot −0.02, matcha −0.06 (none significantly negative) |
| Static bench (non-adaptive copies), deals 201 / 301 / 401 | +0.4 / −0.3 / +0.3; pooled **+0.15 ± 0.35** (Claudebot −0.15 ± 0.12, the only negative, not significant) |
| `simreal`: the 36 real Saturday line-ups, adaptive / static copies | +1.22 ± 0.84 / −0.79 ± 0.83 (neither significant) |
| Random 7-seat tables (whole field), adaptive, 2 runs | −0.8 ± 1.0 / +0.7 ± 0.9 (about 0) |
| Real logs | Neutral: removing or resizing these bluffs makes no detectable difference in realised results (randomised natural experiment, −0.02 ± 0.18 pot per bluff in R19–R54). No contradiction with the bench. |

**Reading:**
- The gain is specific to our Table C line-up against adaptive opponents: +0.54, positive in all 6 deal sets (sign test p ≈ 0.016), and it comes mainly from FisherMen.
- Everywhere else it is neutral; no test is significantly worse.
- **The mechanism is consistent with the evidence.** Out-of-position flop bluffs at about pot size are break-even against real opponents. Against opponents who call more versus frequent bettors they lose, and v14's fold model over-predicts folds in exactly these spots.
- **So v15 vs v14 is a small, low-risk improvement:** fewer bluffs, lower variance. Expect about +0 to +0.5 bb/100 in real play.

## Variants tested and not adopted (vs v14, adaptive bench, pooled)

| Variant | Result | Real logs |
|---|---|---|
| v15b: in-position caps up (c-bet 0.80, stab 0.70) | +0.06 ± 0.35 | c-bet part: moderate support (+0.74 pot per extra bluff) |
| v15f: v15c + in-position c-bet cap 0.80 + river in-position barrel cap 0.65 | adaptive +0.51 ± 0.26 over 6 sets, but **FisherMen 0.00** (v15c: +0.31); **static −0.76 ± 0.35 (z −2.1)** | FisherMen's fold rate to in-position c-bets fell to about 56% later on Saturday |
| v15d: in-position barrel cap 0.65 (turn and river) | −0.58 ± 0.35 | the turn part doesn't pay |
| v15e: no pot-size bluffs out of position on the flop (the reviewer's own fix) | −0.10 ± 0.37 | turns pot-size bluffs into ⅓-pot bluffs, the worst size |
| v14b0: fold blend off | +0.53 ± 0.45 | rejected: the model then predicts far too many folds (calibration) |
| v16a / v16b: fold model shifted by the measured line gap | +0.16 / +0.59 | — |
| v15g: v15c + v16's turn/river gap correction | +0.10 ± 0.27 over 6 sets | — |
