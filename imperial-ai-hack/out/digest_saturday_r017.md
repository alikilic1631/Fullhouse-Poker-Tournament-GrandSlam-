# saturday/r017 — hero seat 4 (Durahim 1453), 1000 hands, **+1.6 bb/100**

| seat | player | bb/100 | VPIP | PFR | 3bet | postflop agg | SD% |
|---|---|---:|---:|---:|---:|---:|---:|
| 1 | Chinese people can fly | +30 | 40% | 27% | 4.0% | 4.9 | 20% |
| 3 | SARS | +11 | 42% | 38% | 20.5% | 2.2 | 9% |
| 6 | gamblerlove | +6 | 18% | 15% | 2.5% | 1.9 | 17% |
| 4* | Durahim 1453 | +2 | 26% | 23% | 4.3% | 1.5 | 16% |
| 0 | Anker Batteries | -10 | 20% | 16% | 6.4% | 1.9 | 15% |
| 5 | test | -17 | 13% | 7% | 0.6% | 2.2 | 10% |
| 2 | Joca | -21 | 8% | 1% | 0.6% | 1.8 | 21% |

**Hero by position (bb/100):** EP2 -78 (n=142), BB -58 (n=143), SB -30 (n=143), HJ +2 (n=143), BTN +17 (n=143), CO +63 (n=143), EP1 +94 (n=143)

**Biggest losses:**
- hand 35: Ah Th | board 6c Ad 8s Ks 5h | -100.0 bb | vs Chinese people can fly Three of a Kind
- hand 438: Ks Ac | board Th Jd Ah 7s 8c | -100.0 bb | vs SARS Three of a Kind
- hand 492: Kd Kc | board 4d 9h Ts 7c 9d | -100.0 bb | vs Joca Full House
- hand 595: Jc Kd | board Kh Ah Ks 5c 7c | -100.0 bb | vs Chinese people can fly Three of a Kind
- hand 599: Ad As | board Qs Qh 6c 8c 2d | -100.0 bb | vs Chinese people can fly Two Pair, SARS Full House
- hand 826: Ks Ah | board 2d Jc Ad 8s 8h | -100.0 bb | vs Chinese people can fly Full House
- hand 637: Kc Kh | board 4c As 3d 8c | -61.2 bb
- hand 47: 9h 9c | board 3h 4c 4s | -34.5 bb

**Biggest wins:**
- hand 597: Kc Kh | board 5c 7s 4s 9h 5d | +120.7 bb | vs Chinese people can fly Two Pair
- hand 980: Kh As | board Ks 2s Jh 4s 2d | +101.0 bb | vs Chinese people can fly Two Pair
- hand 161: Ad Tc | board 2c 5h Ts 9c 7h | +84.5 bb | vs Joca Pair
- hand 372: Qh Ad | board Qc 4s Kh Ah | +71.3 bb

**Chips hero lost into pots won by:** Chinese people can fly 585 bb, SARS 387 bb, Joca 132 bb, gamblerlove 117 bb

**Replay through v6/bot.py:**
```
     19         19
  preflop  check                          11         11
  preflop  jam-3bet                        2          2
  preflop  jam-4bet+                       1          1
  flop     call                           38         45
  flop     bet-mid                        31         32
  flop     check                          28         26
  flop     fold                           20         20
  flop     bet-small                      19         19
  flop     raise-mid                      16          8
  flop     bet-overbet                     8          9
  flop     raise-overbet                   0          1
  turn     check                          25         28
  turn     fold                           23         23
  turn     call                           18         20
  turn     bet-mid                        15         12
  turn     raise-mid                       3          2
  turn     bet-overbet                     2          2
  turn     raise-small                     1          0
  river    fold                           12         11
  river    check                          11         11
  river    call                           10         11
  river    bet-mid                         4          5
  river    raise-overbet                   1          1
  river    bet-small                       1          0
counterfactual read (bb, over 1000 hands):
  same line as the live bot      :  971 hands, live result    -10.2
  this bot folds where live did not:    5 hands, live result    +13.1 -> this bot    -22.8  (-3.6 bb/100)
  other deviations (outcome unknown):   24 hands, live result    +13.3
      flop: live raise-mid -> this bot call                   8 hands, live    -24.7
      turn: live bet-mid -> this bot check                    3 hands, live    -16.7
      flop: live fold -> this bot call                        3 hands, live     -8.0
      turn: live fold -> this bot call                        1 hands, live     -8.0
      river: live fold -> this bot call                       1 hands, live     -7.5
      flop: live call -> this bot raise-mid                   1 hands, live     -4.3
      flop: live bet-mid -> this bot check                    2 hands, live     -2.1
      flop: live check -> this bot bet-overbet                1 hands, live     +5.0
      turn: live raise-mid -> this bot call                   1 hands, live     +8.7
      flop: live check -> this bot bet-small                  1 hands, live     +9.5
```
