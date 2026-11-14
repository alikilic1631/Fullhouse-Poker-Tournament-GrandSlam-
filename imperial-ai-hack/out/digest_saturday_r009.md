# saturday/r009 — hero seat 7 (Durahim 1453), 1000 hands, **+25.7 bb/100**

| seat | player | bb/100 | VPIP | PFR | 3bet | postflop agg | SD% |
|---|---|---:|---:|---:|---:|---:|---:|
| 4 | Poké Bot | +26 | 24% | 18% | 1.2% | 1.4 | 24% |
| 7* | Durahim 1453 | +26 | 18% | 11% | 1.4% | 2.2 | 15% |
| 5 | Resonance Qt | +13 | 20% | 12% | 3.5% | 1.5 | 20% |
| 2 | Attention Is All In | +2 | 23% | 16% | 4.6% | 7.5 | 18% |
| 0 | aydine | -7 | 22% | 13% | 1.5% | 2.4 | 26% |
| 3 | Gherkers | -7 | 21% | 16% | 4.0% | 2.8 | 17% |
| 1 | SARS | -18 | 13% | 9% | 1.4% | 3.7 | 29% |
| 6 | pokermon | -34 | 32% | 17% | 3.0% | 4.7 | 15% |

**Hero by position (bb/100):** BB -48 (n=125), BTN -34 (n=125), SB -19 (n=125), EP1 -14 (n=125), CO +28 (n=125), EP3 +39 (n=125), HJ +108 (n=125), EP2 +145 (n=125)

**Biggest losses:**
- hand 977: 5h 5d | board 3h 5s 8s 9d 6s | -100.0 bb | vs aydine Three of a Kind
- hand 779: 6h 6c | board 2c Kc Tc 5h | -40.3 bb
- hand 755: Ts Td | board 9d Qd Js 6d | -25.5 bb
- hand 944: Kh Qh | board - | -24.1 bb
- hand 295: As Qd | board 6s 3s 9d Th | -19.0 bb
- hand 692: 4d 4h | board 2c 8d 6s 8s | -18.2 bb
- hand 595: 3h 3d | board Th Kh 9s 5h | -17.1 bb
- hand 242: Ah Th | board 7d Qc 4c 9s | -15.4 bb

**Biggest wins:**
- hand 830: Kc Ah | board Ac 8c 5s As 2c | +109.4 bb | vs Gherkers Three of a Kind
- hand 740: 6h 6c | board 8d 5d 7c 4s 2h | +101.5 bb | vs SARS Pair
- hand 475: Ks Ac | board Qd Js 2c Th Ad | +101.0 bb | vs SARS Three of a Kind
- hand 745: Qc 4c | board 3h 6c 9c Tc 9d | +100.2 bb | vs aydine Two Pair

**Chips hero lost into pots won by:** aydine 279 bb, pokermon 91 bb, Resonance Qt 90 bb, SARS 70 bb

**Replay through v3/bot.py:**
```
      9          9
  preflop  jam-3bet                        3          3
  preflop  jam-4bet+                       1          1
  preflop  4bet+                           1          1
  flop     check                          31         30
  flop     fold                           20         23
  flop     call                           20         17
  flop     bet-mid                        17         15
  flop     bet-small                       7         11
  flop     bet-overbet                     9          8
  flop     raise-small                     7          9
  flop     raise-overbet                   5          3
  turn     check                          23         24
  turn     fold                           23         22
  turn     bet-mid                        10         10
  turn     call                            7          7
  turn     bet-overbet                     3          2
  turn     raise-small                     1          2
  turn     raise-mid                       1          1
  river    check                          10         10
  river    fold                            5          5
  river    call                            2          2
  river    bet-mid                         1          1
  river    bet-overbet                     1          1
  river    bet-small                       1          1
counterfactual read (bb, over 1000 hands):
  same line as the live bot      :  976 hands, live result   +243.5
  this bot folds where live did not:    4 hands, live result    -55.8 -> this bot    -16.0  (+4.0 bb/100)
  other deviations (outcome unknown):   20 hands, live result    +68.9
      flop: live call -> this bot raise-small                 2 hands, live    -14.4
      flop: live check -> this bot bet-small                  3 hands, live    -12.6
      turn: live check -> this bot bet-mid                    2 hands, live     -7.6
      flop: live check -> this bot bet-overbet                1 hands, live     -3.0
      turn: live bet-mid -> this bot check                    3 hands, live     -2.6
      flop: live fold -> this bot call                        1 hands, live     -2.5
      turn: live fold -> this bot raise-small                 1 hands, live     -2.5
      flop: live raise-overbet -> this bot call               1 hands, live     +3.5
      flop: live check -> this bot bet-mid                    1 hands, live     +6.0
      flop: live raise-small -> this bot call                 1 hands, live    +17.1
```
