# V13_WEAKNESS_CATALOG.md — parametric weakness discovery (D1)

- Bot: bots/v13/bot.py · 80 LHS configs × 6 seeds × 400 hands
- Overall: median config delta = -10000, mean = +7046, configs where we LOSE (mean<0) = 16/80

## Worst-cluster parameter signature (worst 12 vs overall)
| dim | worst-12 mean | overall mean | range |
|---|---|---|---|
| fold_to_cbet | 0.69 | 0.53 | (0.1, 0.95) |
| threebet_freq | 0.20 | 0.16 | (0.02, 0.3) |
| cbet_freq | 0.71 | 0.62 | (0.3, 0.95) |
| vpip | 0.54 | 0.47 | (0.1, 0.85) |
| short_stack_jam_freq | 0.42 | 0.50 | (0.0, 1.0) |
| trap_freq | 0.17 | 0.15 | (0.0, 0.3) |
| river_bluff_freq | 0.21 | 0.20 | (0.0, 0.4) |
| donk_freq | 0.22 | 0.23 | (0.0, 0.45) |
| pfr | 0.29 | 0.29 | (0.05, 0.65) |
| aggression_factor | 2.65 | 2.65 | (0.3, 5.0) |

## Top 10 worst configs (patch-window targets)
| rank | mean Δ | median Δ | key params |
|---|---|---|---|
| 1 | -10000 | -10000 | vpip=0.44, aggression_factor=2.343, fold_to_cbet=0.876, trap_freq=0.24, donk_freq=0.056, short_stack_jam_freq=0.578, sizing_profile=min_raise |
| 2 | -10000 | -10000 | vpip=0.838, aggression_factor=1.352, fold_to_cbet=0.636, trap_freq=0.293, donk_freq=0.046, short_stack_jam_freq=0.195, sizing_profile=overbet |
| 3 | -10000 | -10000 | vpip=0.349, aggression_factor=0.724, fold_to_cbet=0.699, trap_freq=0.122, donk_freq=0.234, short_stack_jam_freq=0.021, sizing_profile=standard |
| 4 | -10000 | -10000 | vpip=0.517, aggression_factor=3.88, fold_to_cbet=0.37, trap_freq=0.025, donk_freq=0.428, short_stack_jam_freq=0.346, sizing_profile=standard |
| 5 | -10000 | -10000 | vpip=0.766, aggression_factor=4.614, fold_to_cbet=0.331, trap_freq=0.02, donk_freq=0.447, short_stack_jam_freq=0.684, sizing_profile=large |
| 6 | -10000 | -10000 | vpip=0.598, aggression_factor=0.454, fold_to_cbet=0.764, trap_freq=0.167, donk_freq=0.076, short_stack_jam_freq=0.691, sizing_profile=large |
| 7 | -9277 | -10000 | vpip=0.356, aggression_factor=4.246, fold_to_cbet=0.598, trap_freq=0.146, donk_freq=0.066, short_stack_jam_freq=0.211, sizing_profile=standard |
| 8 | -8365 | -10000 | vpip=0.183, aggression_factor=3.579, fold_to_cbet=0.643, trap_freq=0.216, donk_freq=0.444, short_stack_jam_freq=0.489, sizing_profile=min_raise |
| 9 | -6764 | -10000 | vpip=0.822, aggression_factor=3.364, fold_to_cbet=0.896, trap_freq=0.22, donk_freq=0.114, short_stack_jam_freq=0.601, sizing_profile=min_raise |
| 10 | -4883 | -10000 | vpip=0.746, aggression_factor=0.526, fold_to_cbet=0.758, trap_freq=0.135, donk_freq=0.316, short_stack_jam_freq=0.896, sizing_profile=standard |

## Notes
- Counter-strategies are NOT implemented here. On D2, match observed field
  profiles to these clusters; implement a counter ONLY IF the leak is large
  (>3000 mean), the fix is simple (<50 lines / one param), the profile is
  plausible in the real field, and it passes held-out + field-mix gates.
- Note: '5 copies of one config' mono-tables are a stress (5 maniacs/jammers
  at one table = high variance); read mean+median together, not raw worst.