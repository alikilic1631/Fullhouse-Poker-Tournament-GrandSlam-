# Phase 1 — v12 Failure-Mode Discovery

Method: `sandbox/loss_analyzer.py` — per-hand loss-by-spot classification, v12 (seat 0)
vs strong/value-style opponents, HU + 6-bot, 20 seeds × 400 hands each. Net chips and
counts per spot bucket; a strongly net-negative bucket = a real leak (not variance).

## Leak #1 (PRIMARY, high confidence): river over-calling as bluff-catcher
- `hu_caller` bucket (we faced a bet postflop and were NOT the aggressor) is net-negative
  in ALL 6 configs: −220 to −846 chips/hand.
- Losses are RIVER-concentrated (river = 40–50% of hu_caller losses).
- Drives punts: 6-bot vs solver_approximator = 11/20 punts, match median −10k.
- Mechanism: vs value-weighted river ranges (solver/chartbot under-bluff rivers) our
  marginal bluff-catchers call too often. Action-only/street-agnostic opponent stats
  can't distinguish a value-heavy river bettor from a balanced/bluffy one, so the
  default river-call frequency is too loose for the field's value-weighted river betting.
- CAVEAT: the same stat limitation means a blanket "fold more rivers" would also fold to
  genuine river bluffers (e.g. overbet_river_bluffer). Any fix must be validated to BEAT
  v12 on held-out enemy zoo + field-mix primary, not just vs solver.

## Not leaks (healthy)
- `hu_aggressor`: strongly POSITIVE (+213…+642/hand) — our betting/value/bluffing is +EV.
- `preflop_fold`: mildly negative (−41…−104/hand) — normal blind/limp surrender.
- `multiway_pot`: positive (+79…+1420/hand) — multiway tightening is working.
- `preflop_allin`: ~neutral.

## Decision
ONE real leak found -> proceed to Phase 2 (conditional tuning) on river bluff-catch
tightening, gated by opponent bluffiness, validated on held-out + field-mix. Keep only
if it beats v12 on held-out (not just tuning) and the mechanism generalizes.

---

## Phase 2 outcome — river/call-down over-pay fix (KEPT as v13)
- Narrow river-only fold-tightening was a no-op (we reach river *facing-bet decisions*
  only ~4×/300 hands; the leak's "river" was the showdown street, real leak is the
  multi-street call-down).
- Broadened to TURN+RIVER marginal call-downs, gated off vs flagged bluffers
  (bluff_propensity>0.45 or aggression>0.45), bet-size-scaled. Grid-swept magnitude:
  0.30 worse, 0.50 and 0.65 both robust +25008 (chose 0.50 — conservative).
- Validation (v12 -> v13, RIVER_FOLD=0.50):
  - field-mix primary robust +25008 vs v12 +24024; cumulative +748724 vs +722402; punts 11 vs 12
  - held-out field +2025 (w4/l0); reference field identical; tuning +134; bluffer +0 (no regression)
  - chartbot mono-table -1694 (median 0, w1/l2 = noise)
- Meets keep-criteria (beats v12 on held-out AND field-mix; mechanism generalizes;
  no significant regression) -> SHIPPED v13.
