# Sunday bot: what to upload (written overnight, Sun 15 Nov)

## TL;DR

- **Upload `~/Desktop/bot.py` at 09:00.** It is **v14**: SHA-256 `3ec3640e274a2247…`, 94,826 bytes, standard library only.
- A new upload plays from the next round, so uploading at 09:00 means it plays from about 09:05.
- Backups on the Desktop, newest first:
  - `bot_v13_backup.py` = v13.1, the Desktop bot from 01:30 to 03:05.
  - `bot_v11_backup.py` = v11.1, Saturday evening's version.
- v14 beats both on every pooled benchmark, including a re-check on fresh deals, and it has **0 timeouts** in every timing test (details below).
- I did not upload, log in, commit or push anything.

## Version history

| Version | What it is |
|---|---|
| v10 | The live site v17 from Saturday. |
| v11.1 | Fixes from the 36-round diagnosis: river over-folding, monster-hand guards, jam ranges, 3-bet defence, time budgets. |
| v13.1 | v11.1 + three exploits checked on the real logs: line-aware turn/river bluffing, wider 4-bet bluffs against FisherMen, small-river bluff-catching with pairs. |
| **v14** | v13.1 + four aggression switches: calibrated fold model, pot-size heads-up bluffs, value overbets, light 3-bets against measured folders. |

## How much better is it?

Paired duplicate tests: the same cards for both bots. Opponents are copies of the 7 Table C teams built from their real Saturday hands. All-in luck is removed. Units are bb/100.

| Test | v14 vs v13.1 | v13.1 vs v11.1 |
|---|---|---|
| Adaptive Table C bench (copies adapt to how often we bet and 3-bet us exploitatively), 720 tables | **+1.14 ± 0.46** (z 2.5) | **+2.75 ± 0.39** (z 6.8) |
| Static Table C bench, 720 tables | **+1.30 ± 0.49** (z 2.6) | about +1.9 (z ≈ 5) |
| Random 7-seat tables drawn from the whole field | **+4.0 ± 1.2** (z 3.4) | +1.8 ± 0.9 |
| The 36 real Saturday line-ups, replayed (adaptive / static) | +1.7 ± 1.1 / +0.4 ± 1.2 | |
| Per Table C opponent (adaptive) | none negative | all positive (FisherMen +1.1) |
| **Fresh-deal re-check at 04:10** (deals never used to build or choose it): adaptive, 6 sets | **+0.82 ± 0.36** (z 2.3) | |
| All deals pooled: adaptive 9 sets / static 6 sets | **+0.93 ± 0.28** (z 3.3) / **+0.96 ± 0.36** (z 2.7) | |

**Overall:** v14 is about **+3.7 bb/100 over v11.1** on the adaptive bench, and roughly **+10 or more over Saturday's live bot**. The bench overstates absolute levels, so expect less in real play. The ranking has held on every pooled test.

**Where v14 wins:**
- It takes more pots without a showdown, mainly with heads-up flop bluffs of about pot size. Part of that is given back on turns when those bluffs are called, and in slightly bigger showdown losses.
- It also has v13's 4-bet edge against FisherMen, our main rival for 2nd. On top of the same aggression switches, that edge alone is worth +0.85 bb/100 against them.

## Misses and timeouts

| Check | Result |
|---|---|
| Official engine, real transport, 6 extra busy processes, strict limits 10 ms / 5 s bank (real limits: 25 ms / 10 s) | **0 timeouts** in 14,852 decisions over 12 rounds; slowest 4.2 ms |
| Same, at the real limits 25 ms / 10 s | **0 timeouts** in 13,454 decisions over 11 rounds; slowest 6.2 ms |
| Projected thinking time on the (slower) server | about 3.0 s per round on average, 4.1 s at worst, of the 10 s bank |
| Emulated slow server (bot clock 6× and 10× slower), paired with v13.1 | Slowest decision 5–10 ms of compute, the same as v13.1. The bot's own 8 ms cap bounds its thinking; even with about 2 ms transport that leaves at least 13 ms of the 25 ms limit spare. |
| Fuzz: random/odd tables, 2–8 seats, 40× slow clock | 25,947 decisions; 0 crashes, 0 fallbacks, 0 illegal actions |
| Final format (if we reach it): one 5,000-hand table, 50 s bank, official `local_sim.py` and the timing tool with load | 0 timeouts / errors / bank-outs; 6,172 decisions, slowest 3.7 ms, 2.9 s of the 50 s bank used |
| Python 3.11 and 3.13 (the server runs 3.12) | clean |
| Independent code review | "ship": no crash, legality or timing defects |

Zero misses can't be *guaranteed*, because a server-side stall can hit any bot; every team had a few on Saturday, at negligible cost. v14's own thinking time sits far below the limit.

## What I tried overnight and did not adopt (data-driven: real logs + bench)

| Idea | Result | Decision |
|---|---|---|
| Higher in-position flop c-bet bluff cap (v15b) | Bench +0.06 ± 0.35. Real logs: moderate support (+0.74 pot per extra bluff in a randomised natural experiment), but it loses against FisherMen, whose fold rate fell later on Saturday. | rejected |
| Higher in-position turn+river barrel cap (v15d) | Bench −0.58 ± 0.35. Real logs: the turn part doesn't pay. | rejected |
| Fewer out-of-position flop bluffs (v15, `imperial-ai-hack/v15/`) | Led on the deal sets used to pick it (+0.54 ± 0.25 over 6 sets). On **6 fresh deal sets: −0.02 ± 0.25**; static +0.01. Real logs: no difference. The first lead was a winner's-curse effect (best of 6 variants). It passed every safety check, but it isn't better than v14. | **not adopted** |
| Same, plus a higher in-position c-bet cap and river barrel cap (v15f) | Adaptive +0.51; static −0.76 ± 0.35 | rejected |
| No pot-size out-of-position flop bluffs (v15e, a reviewer's suggestion) | Bench −0.10. Real logs: pushes bluffs to ⅓ pot, the worst size. | rejected |
| Fold blend off (v14b0) | Bench +0.53 ± 0.45. Real logs: the model then predicts far too many folds. | rejected |
| Fold model corrected by betting line (v16a/b, v15g) | +0.16 / +0.59 / +0.10, not significant | rejected |
| In-position bluff-raises against an out-of-position lead (v17) | Raising every lead loses money in the real logs (−0.07 pot per spot). Only raises against small leads (≤ ⅓ pot) pay: about 61–77% folds, mostly from FisherMen and matcha. That is about one spot per round, worth about +0.15–0.35 bb/100, too small to confirm before 09:00. Bench (broad version): +0.13 ± 0.36. | not adopted (an idea for a later upload) |
| More multiway c-bets | Real logs: 3-way pot-size c-bets after everyone checks get 70% folds, but the spot is rare (about +0.2–0.4 bb/100) | not built |

**Lesson I applied:** one variant (v15) looked significantly better on the deals used to choose it, and it vanished on fresh deals. So v14 was re-checked on fresh deals too, and it held: +0.82 ± 0.36.

## Morning checklist

1. At 09:00 upload `~/Desktop/bot.py` on the AI Poker Bots page.
2. After the first round it plays, check its row: timeouts and errors should be 0. One or two server stalls per several rounds is normal.
3. If it shows errors (it should not), upload `bot_v13_backup.py`, the previous validated version.

Full details:
- `imperial-ai-hack/v14/CHANGES.md` and `../v13`, `../v11` in the project folder;
- the run log `imperial-ai-hack/testbench/out/test_adapt/summary.out`.
