# D2 Patch-Window Playbook (FullHouse)

Shipped bot: **v13** (`submission/bot.py`). One re-submission allowed before D5.
Goal on D2: from D1 hand histories, profile the actual field, re-tune, and ship the
best-validated patch (or keep v13 if nothing clearly wins).

## Step 0 — Ingest D1 hand histories
1. Download the D1 JSON. Inspect ONE record's schema.
2. Edit `analytics/field_analysis.py::normalize_record()` to map the portal schema to
   our action list `{bot_id, action, amount, pot}`. (It currently reads the engine's
   `events` format — the reference; the portal format may differ in field names only.)
3. Run: `python3 analytics/field_analysis.py --input d1_hands.jsonl`
   Rehearsed working via `--selftest`.

## Step 1 — Read the field flags
`field_analysis` outputs per-opponent {fold_to_bet, aggression, shove_rate, round_bet%}
and field flags: `pct_using_round_sizing`, `mean_fold_to_bet`, `mean_aggression`,
`high_shove_share`. Also run `analytics/loss_analyzer`-style loss-by-spot on OUR D1
hands to see where we actually leaked vs the real field.

## Step 2 — Decision tree (which patch to deploy)
Apply the FIRST matching rule; then validate (Step 4) before shipping.

| Observed D1 signal | Patch |
|---|---|
| `pct_using_round_sizing > 0.50` AND `mean_fold_to_bet > 0.55` (modal-LLM-heavy, fold-y) | **Adj-A "solver/LLM-heavy"** + consider re-deploying **v10 LR** (`bots/v10/` + `data/lr_fold_predictor.npz`) — the LR sizes bets by predicted fold and is most valuable vs a round-sizing fold-y field |
| `mean_aggression > 0.45` OR many opponents with `shove_rate > 0.08` / frequent overbets-as-bluffs | **Adj-B "bluff-heavy"** (loosen call-downs, bluff-catch more) |
| Many opponents lead/donk OOP (high non-PFR-aggressor flop bets) | **Adj-C "donk-heavy"** (don't over-respect donks) |
| Loss-by-spot shows a NEW specific leak | Targeted tune via the Phase-2 method (find param, 3-grid sweep, validate on held-out + re-tuned field-mix) |
| No clear signal / nothing beats v13 in validation | **Keep v13** |

## Step 3 — Pre-built adjustment recipes (apply to a copy of v13)
All are small, reversible parameter/branch changes. Make `bots/v14/bot.py = v13` and edit.

**Adj-A — solver/LLM-heavy field (tighter value, fewer bluffs):**
- `RIVER_FOLD = 0.65` (was 0.50) — fold marginal call-downs more vs the value-heavy field.
- In `perturb_postflop`, raise the over-folder bluff threshold `f > 0.55` -> `f > 0.62` and
  cut the bluff `move` factor (bluff less into a fold-y-but-trappy field).
- Rationale: a round-sizing fold-y field is value-heavy when it DOES bet; pay off less.

**Adj-B — bluff-heavy field (more bluff-catching):**
- `RIVER_FOLD = 0.0` (disable the value-respect tightening — they bluff, so call down).
- In `perturb_postflop` facing-bet branch, raise the bluff-catch cap (e.g. `g` ceiling
  0.8 -> 0.9) and lower the trigger `agg > 0.40` -> `agg > 0.32`.
- Rationale: vs frequent bluffers, calling lighter is +EV; our action-only stats
  under-detect them, so bias the default toward calling.

**Adj-C — donk-heavy field (better donk response):**
- Add to `postflop_decision` (facing a flop/turn bet where the bettor was NOT the
  preflop aggressor — a donk lead): shift some fold->call and add a small raise, since
  donk ranges are weak/capped. Snippet:
  ```python
  if facing != "checked_to" and street in ("flop","turn") and not _we_were_pf_aggressor(state):
      d = dict(dist); mv = 0.2*d.get("fold",0)
      d["fold"] -= mv; d["call"] = d.get("call",0)+mv*0.6; d["raise_pot"]=d.get("raise_pot",0)+mv*0.4
      dist = _norm(d)
  ```

## Step 4 — Re-tune field_sim + validate (REQUIRED before shipping any patch)
1. Re-weight `sandbox/field_sim.py::FIELD_DISTRIBUTION` from D1 observed archetype
   frequencies (map each D1 opponent to its nearest archetype via its field_analysis
   profile: fold_to_bet/aggression/round_bet% -> nit/tag/lag/station/solver/etc).
2. Paired-seed the patch vs v13 on held-out enemy zoo + the re-tuned field-mix:
   `python3 sandbox/bench.py bots/v13/bot.py bots/v14/bot.py --opponents <held-out> --seeds 20`
   `python3 sandbox/field_sim.py bots/v14/bot.py --tables 40`
3. Run `python3 sandbox/final_validation.py` (A=v14, B=v13) for the full shootout +
   field-mix + round-robin + decision matrix.
4. **Ship the patch ONLY if it beats v13 on the re-tuned field-mix robust_score AND
   doesn't regress on held-out.** Otherwise keep v13. (Same discipline as Phase 2.)
5. Re-run validator + fuzz (10k) + Patch-15 safety audit on the shipped file.

## Step 5 — Ship
Update `submission/bot.py`, re-validate (`validator.py`), upload at portal. Update
`SUBMISSION_REPORT.md` with what was changed and why.

## Tooling ready for D2
- `analytics/field_analysis.py` — field profiler (selftest-verified).
- `sandbox/loss_analyzer.py` — loss-by-spot leak finder.
- `sandbox/field_sim.py` — field-mix metric (re-tune FIELD_DISTRIBUTION here).
- `sandbox/final_validation.py` — multi-version shootout + decision matrix.
- `training/train_lr.py` + `bots/v10/` — v10 LR ready to re-deploy if the field warrants it.
