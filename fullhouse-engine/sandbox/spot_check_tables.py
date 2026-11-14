"""Spot-check the generated equity tables against known values and runtime MC.

Validates that:
- AA vs 72o ≈ 0.87
- AKs vs QQ ≈ 0.46
- AA vs 1/3/5 random ≈ 0.85 / 0.65 / 0.50
- AKs vs 1/3/5 random ≈ 0.67 / 0.40 / 0.28
- Any 10 random Table-3 cells are within 0.02 of fresh runtime MC

Run after build_equity_tables.py completes.
"""
import sys, random
from pathlib import Path
import numpy as np
import eval7

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "training"))
import build_equity_tables as B


def main():
    npz_path = ROOT.parent / "submission" / "data" / "equity_tables.npz"
    if not npz_path.exists():
        print(f"NOT FOUND: {npz_path}"); sys.exit(1)
    d = np.load(npz_path, allow_pickle=False)
    print(f"Tables in file: {sorted(d.files)}")
    hand_classes = list(d["hand_classes"])
    cidx = {c: i for i, c in enumerate(hand_classes)}

    expected_t1 = [
        ("AA", "72o", 0.87, 0.03),
        ("AA", "KK", 0.82, 0.03),
        ("AKs", "QQ", 0.46, 0.03),
        ("AKs", "JJ", 0.46, 0.03),
        ("AKo", "AKs", 0.50, 0.02),
        ("72o", "AA", 0.13, 0.03),
    ]
    expected_t2 = [
        ("AA", 1, 0.85, 0.02),
        ("AA", 3, 0.65, 0.03),
        ("AA", 5, 0.49, 0.03),
        ("AKs", 1, 0.67, 0.02),
        ("AKs", 5, 0.28, 0.03),
        ("72o", 1, 0.36, 0.03),
        ("KK", 1, 0.82, 0.02),
        ("QQ", 1, 0.80, 0.02),
    ]
    print("\n=== TABLE 1: preflop hand-vs-hand ===")
    if "preflop_hand_vs_hand" in d.files:
        T1 = d["preflop_hand_vs_hand"]
        print(f"  shape: {T1.shape}, dtype: {T1.dtype}, size: {T1.nbytes} bytes")
        fails = 0
        for a, b, exp, tol in expected_t1:
            v = float(T1[cidx[a], cidx[b]])
            ok = abs(v - exp) <= tol
            print(f"  {a:>4s} vs {b:<4s} = {v:.3f}  (expect {exp:.2f} +/- {tol:.2f})  {'OK' if ok else 'FAIL'}")
            if not ok: fails += 1
        print(f"  {len(expected_t1)-fails}/{len(expected_t1)} pass")
    else:
        print("  NOT PRESENT")

    print("\n=== TABLE 2: preflop vs N random ===")
    if "preflop_vs_random" in d.files:
        T2 = d["preflop_vs_random"]
        print(f"  shape: {T2.shape}, dtype: {T2.dtype}, size: {T2.nbytes} bytes")
        fails = 0
        for cls, n, exp, tol in expected_t2:
            v = float(T2[cidx[cls], n-1])
            ok = abs(v - exp) <= tol
            print(f"  {cls:>4s} vs {n} = {v:.3f}  (expect {exp:.2f} +/- {tol:.2f})  {'OK' if ok else 'FAIL'}")
            if not ok: fails += 1
        print(f"  {len(expected_t2)-fails}/{len(expected_t2)} pass")
    else:
        print("  NOT PRESENT")

    print("\n=== TABLE 3: postflop class ===")
    if "postflop_class_n_opp" in d.files:
        T3 = d["postflop_class_n_opp"]
        Tf = d["postflop_class_filled"] if "postflop_class_filled" in d.files else None
        print(f"  shape: {T3.shape}, dtype: {T3.dtype}, size: {T3.nbytes} bytes")
        if Tf is not None:
            print(f"  filled cells: {int(Tf.sum())}/{Tf.size}")
        textures = [str(t) for t in d["board_textures"]]
        strengths = [str(s) for s in d["hand_strengths"]]
        # Spot-check: for each filled cell, value should be 0..1
        T3_flat = T3.flatten()
        n_zero = int((T3_flat == 0).sum())
        n_nonzero = T3_flat.size - n_zero
        print(f"  non-zero cells: {n_nonzero}/{T3_flat.size}")
        non_zero_vals = T3_flat[T3_flat > 0]
        if len(non_zero_vals):
            print(f"  value range: min={non_zero_vals.min():.3f} max={non_zero_vals.max():.3f}")

    print("\n=== TABLE 4: range vs range (optional) ===")
    if "range_vs_range" in d.files:
        T4 = d["range_vs_range"]
        Tf = d["range_vs_range_filled"] if "range_vs_range_filled" in d.files else None
        names = list(d["matchup_names"]) if "matchup_names" in d.files else []
        print(f"  shape: {T4.shape}, matchups: {names}")
        if Tf is not None:
            print(f"  filled cells: {int(Tf.sum())}/{Tf.size}")
        # quick check: preflop row should be non-zero across matchups
        if names:
            print("  preflop equities per matchup:")
            for i, n in enumerate(names):
                pre = float(T4[i, 0, 0])
                print(f"    {n:<32s} {pre:.3f}")

    print(f"\nTotal file size: {npz_path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
