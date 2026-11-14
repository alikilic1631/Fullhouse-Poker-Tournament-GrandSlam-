# saturday/r010 — hero seat 3 (Durahim 1453), 1000 hands, **-4.3 bb/100**

| seat | player | bb/100 | VPIP | PFR | 3bet | postflop agg | SD% |
|---|---|---:|---:|---:|---:|---:|---:|
| 4 | Kojack | +68 | 22% | 17% | 4.1% | 2.0 | 32% |
| 1 | Chinese people can fly | +12 | 37% | 22% | 2.7% | 3.3 | 34% |
| 0 | supernut | +3 | 16% | 11% | 1.2% | 1.2 | 20% |
| 5 | Red | +3 | 30% | 22% | 2.7% | 3.3 | 30% |
| 3* | Durahim 1453 | -4 | 25% | 19% | 3.8% | 1.5 | 16% |
| 2 | Poké Bot | -82 | 30% | 20% | 2.6% | 0.6 | 33% |

**Hero by position (bb/100):** BTN -127 (n=167), HJ -86 (n=167), BB -2 (n=166), SB +1 (n=167), EP1 +77 (n=166), CO +112 (n=167)

**Biggest losses:**
- hand 272: 8h 9d | board 8c 9c 4c Th Td | -100.0 bb | vs Red Two Pair
- hand 430: Qd Ks | board Qh Jd Td Qs 8c | -100.0 bb | vs Chinese people can fly Straight
- hand 704: Kc As | board Ts Js Jh 8h 5h | -100.0 bb | vs Red Two Pair
- hand 949: Jc Js | board Tc 4h Kh Qc 6d | -29.6 bb
- hand 983: As 7d | board Ah 9d 8c 2h 9h | -26.5 bb
- hand 638: 8s 6s | board Ah Tc 6d Ts | -23.9 bb
- hand 898: Kd 6d | board Jh 8s Ks Jd | -23.0 bb
- hand 678: 2d As | board 7s 9h Td Ac Ks | -22.2 bb

**Biggest wins:**
- hand 657: 8s 8c | board 7d 8h 4h 2d 3d | +107.5 bb | vs Chinese people can fly Pair
- hand 209: 9d Jd | board Ac Qh Ts 8s Ks | +101.5 bb | vs Red Three of a Kind
- hand 720: Ah Td | board 5c Th 9h Ts 4c | +100.5 bb | vs Red Two Pair
- hand 914: 4s Ad | board 4d 6s 5s 4h Jh | +62.2 bb | vs Red Pair

**Chips hero lost into pots won by:** Red 380 bb, Chinese people can fly 322 bb, Kojack 223 bb, Poké Bot 162 bb

**Replay through v4/bot.py:**
```
      4          4
  preflop  jam-3bet                        4          4
  preflop  call-shove                      1          1
  flop     call                           39         38
  flop     bet-mid                        35         36
  flop     fold                           27         33
  flop     check                          29         30
  flop     bet-small                       7         11
  flop     bet-overbet                    11          5
  flop     raise-overbet                   6          5
  flop     raise-small                     6          2
  turn     check                          30         30
  turn     fold                           27         27
  turn     call                           17         19
  turn     bet-mid                         9         10
  turn     bet-overbet                     5          4
  turn     bet-small                       4          4
  turn     raise-small                     3          1
  turn     raise-overbet                   2          2
  turn     raise-mid                       2          2
  river    check                          19         19
  river    fold                           16         16
  river    call                            5          5
  river    bet-mid                         2          2
  river    bet-small                       1          1
counterfactual read (bb, over 1000 hands):
  same line as the live bot      :  967 hands, live result   +257.7
  this bot folds where live did not:    8 hands, live result    -80.0 -> this bot    -39.0  (+4.1 bb/100)
  other deviations (outcome unknown):   25 hands, live result   -220.8
      turn: live raise-small -> this bot call                 2 hands, live   -113.1
      turn: live raise-mid -> this bot call                   1 hands, live   -100.0
      flop: live bet-mid -> this bot check                    5 hands, live    -38.7
      flop: live check -> this bot bet-mid                    3 hands, live    -14.6
      flop: live raise-small -> this bot call                 5 hands, live    -14.5
      turn: live bet-mid -> this bot check                    1 hands, live    -10.5
      turn: live fold -> this bot call                        1 hands, live    -10.1
      flop: live fold -> this bot call                        1 hands, live     -9.0
      turn: live check -> this bot bet-small                  1 hands, live     -4.3
      turn: live bet-small -> this bot check                  1 hands, live     +3.5
```
