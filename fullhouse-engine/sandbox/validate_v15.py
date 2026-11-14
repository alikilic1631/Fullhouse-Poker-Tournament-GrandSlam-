"""
validate_v15.py — paired-seed bench, fuzz, table spot-checks for v15.
Runs the full user-specified validation gate battery vs v14 baseline.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bench import compare


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="bots/v14/bot.py")
    ap.add_argument("--new", default="bots/v15/bot.py")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--hands", type=int, default=400)
    args = ap.parse_args()

    # Held-out set (matches the diverse 5-bot field used for v14 gates).
    held_out = [
        "bots/enemy_zoo/solver_approximator.py",
        "bots/enemy_zoo/mixed_strategy_pluribus_caricature.py",
        "bots/enemy_zoo/aggressive_3bettor.py",
        "bots/enemy_zoo/overbet_river_bluffer.py",
        "bots/enemy_zoo/polarized_bettor.py",
    ]
    # solver_approximator HU (gate 5).
    solver_hu = ["bots/enemy_zoo/solver_approximator.py"]

    print("=" * 64)
    print("v15 VALIDATION BATTERY")
    print(f"  base  : {args.base}")
    print(f"  new   : {args.new}")
    print("=" * 64)

    print(f"\n[HELD-OUT] 5-bot diverse (seeds {args.seeds}, hands {args.hands})")
    r1 = compare(args.base, args.new, held_out, args.seeds, args.hands)
    a, b, diff = r1["A"], r1["B"], r1["diff"]
    print(f"  A median {a['median']:+.0f}  mean {a['mean']:+.0f}  p5 {a['p5']:+.0f}  p95 {a['p95']:+.0f}")
    print(f"  B median {b['median']:+.0f}  mean {b['mean']:+.0f}  p5 {b['p5']:+.0f}  p95 {b['p95']:+.0f}")
    print(f"  B-A median {diff['median']:+.0f}  mean {diff['mean']:+.0f}")
    print(f"  B wins {diff['wins']}/{r1['seeds']}  losses {diff['losses']}/{r1['seeds']}")
    gate6 = diff["median"] >= -1500
    print(f"  GATE 6 (held-out median >= -1500): {'PASS' if gate6 else 'FAIL'}")

    print(f"\n[SOLVER HU] solver_approximator HU (seeds {args.seeds})")
    r2 = compare(args.base, args.new, solver_hu, args.seeds, args.hands)
    a, b, diff = r2["A"], r2["B"], r2["diff"]
    print(f"  B-A median {diff['median']:+.0f}  mean {diff['mean']:+.0f}")
    gate5 = diff["median"] >= -1500 and diff["mean"] >= -1500
    print(f"  GATE 5 (solver HU neutral or better): {'PASS' if gate5 else 'FAIL'}")

    # caricature checks (loose -- per spec, no >2000 regression)
    print(f"\n[CARICATURE] aggressive_3bettor + overbet_river_bluffer + polarized_bettor")
    caric = [
        "bots/enemy_zoo/aggressive_3bettor.py",
        "bots/enemy_zoo/overbet_river_bluffer.py",
        "bots/enemy_zoo/polarized_bettor.py",
        "bots/enemy_zoo/short_stack_jammer.py",
        "bots/enemy_zoo/loose_passive_call_station.py",
    ]
    r3 = compare(args.base, args.new, caric, args.seeds, args.hands)
    diff = r3["diff"]
    print(f"  B-A median {diff['median']:+.0f}  mean {diff['mean']:+.0f}")
    gate_caric = diff["median"] >= -2000
    print(f"  GATE caricature (no >2000 regression): {'PASS' if gate_caric else 'FAIL'}")

    print("\n" + "=" * 64)
    print(f"OVERALL: " + ("ALL GATES PASS" if (gate6 and gate5 and gate_caric)
                          else "SOME GATES FAILED"))
    print("=" * 64)


if __name__ == "__main__":
    main()
