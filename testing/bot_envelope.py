"""
bot_envelope.py — Run a SWEEP of control strategies per variant against the REAL
game and print the reachable landing-x envelope table. Each strategy is a
(burnStartAlt, bleedVx, glideLean, aNet) tuple fed to bot_sweep.run_strategy.

The sweep spans from aggressive brake (high burnStartAlt, low bleedVx floor -> land
SHORT) to minimal brake (low burnStartAlt so BLEED never triggers, retrograde coast
-> land FAR). Results are written to bot_sweep_<mode>.csv and printed as a table.
"""
import csv
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot_sweep import run_strategy, DECKX, PADHALF, OKV  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# aNet defaults per vehicle (tower heavier -> slightly lower net decel).
ANET = {"ocean": 10.5, "tower": 9.5}

# Strategy grid: vary the brake. burnStartAlt = altitude below which the retrograde
# BLEED burn may fire; bleedVx = floor it brakes down to (keeps vx>0). Higher
# burnStartAlt + lower bleedVx = more braking = shorter landing.
def strat_of(mode, label, bsa, bvx, eds):
    return {"burnStartAlt": bsa, "bleedVx": bvx, "glideLean": -2,
            "aNet": ANET[mode], "entryDecelSpd": eds}


def grid(mode):
    # Each entry: (label, burnStartAlt, bleedVx, entryDecelSpd)
    # entryDecelSpd = the mandatory reentry decel-burn target speed (bleed total
    # speed to this before the heat band). Ocean survives with a light/no entry burn;
    # tower REQUIRES an aggressive one (hot entry) or it burns up. Vary the entry burn
    # + the low-band bleed to sweep the reachable landing-x range.
    if mode == "tower":
        return [
            ("EDECEL_180",  7000,  30, 180),   # hard entry brake -> shortest
            ("EDECEL_240",  7000,  40, 240),
            ("EDECEL_300",  7000,  40, 300),
            ("EDECEL_360",  6000,  60, 360),
            ("EDECEL_430",  5000, 110, 430),   # light entry brake -> farther
            ("EDECEL_520",  4200, 170, 520),   # minimal survivable entry brake -> farthest
        ]
    # ocean: it survives without a forced entry burn; vary the low-band brake.
    return [
        ("BRAKE_HARD",   8000,  25,   0),
        ("BRAKE_MED",    7000,  40,   0),
        ("BRAKE_SOFT",   6000,  70,   0),
        ("BRAKE_LIGHT",  5000, 110,   0),
        ("BRAKE_MIN",    4200, 170,   0),
        ("EDECEL_260",   6500,  40, 260),   # add a mild entry brake to pull it shorter
    ]


def main():
    modes = [m for m in sys.argv[1:] if m in ("ocean", "tower")] or ["ocean", "tower"]
    for mode in modes:
        rows = []
        csv_path = os.path.join(HERE, f"bot_sweep_{mode}.csv")
        header_written = False
        print(f"\n{'='*96}\n=== SWEEP {mode.upper()}  (deckX baseline {DECKX[mode]}, padHalf {PADHALF[mode]}, "
              f"OK vy<={OKV[mode][0]} vx<={OKV[mode][1]}) ===\n{'='*96}", flush=True)
        for label, bsa, bvx, eds in grid(mode):
            strat = {"burnStartAlt": bsa, "bleedVx": bvx, "glideLean": -2,
                     "aNet": ANET[mode], "entryDecelSpd": eds}
            t0 = time.time()
            row, out = run_strategy(mode, label, strat, verbose=False)
            dt = time.time() - t0
            rows.append(row)
            print(f"  {label:11} bStart={bsa:>5} bleedVx={bvx:>4} eDecel={eds:>4} | "
                  f"land_x={str(row['land_x']):>7} vx={str(row['vx']):>7} vy={str(row['vy']):>7} "
                  f"ang={str(row['ang']):>6} dmg={str(row['dmg']):>4} fuel={str(row['fuel']):>6} "
                  f"| soft={int(bool(row['soft_touchdown']))} vx+={int(bool(row['vx_never_neg']))} "
                  f"min_vx={row.get('min_vx')} res={row['result']} ({dt:.0f}s)", flush=True)
            # append to CSV immediately (live progress)
            mode_a = "w" if not header_written else "a"
            with open(csv_path, mode_a, newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(row.keys()))
                if not header_written:
                    w.writeheader(); header_written = True
                w.writerow(row)
        # envelope summary: survivable + soft + vx-never-negative landings
        good = [r for r in rows if r["soft_touchdown"] and r["vx_never_neg"] and (r["dmg"] or 100) < 100]
        print(f"\n  -- {mode} reachable envelope (soft + vx>=0 + survived) --")
        if good:
            xs = sorted(r["land_x"] for r in good)
            print(f"     landing-x range: {xs[0]} .. {xs[-1]}   (n={len(good)} clean strategies)")
        else:
            print("     NONE clean — see table for tradeoffs")
        print(f"  wrote {csv_path}")


if __name__ == "__main__":
    main()
