"""
bot_gap.py — Given a saved trajectory JSON (from bot_sweep) and a candidate deckX,
print the gap-over-time table (gap = deckX - booster_x) to prove the deck stays
AHEAD (gap > 0) the whole descent and converges only near touchdown, and confirm
vx never reverses (vx >= ~0 throughout).

Trace columns: [t, x, y, vx, vy, ang_deg, thr, fuel, dmg, heatFrac, phase]

Usage: py bot_gap.py <run_json> <deckX>
"""
import json
import sys

path = sys.argv[1]
deckx = float(sys.argv[2])
with open(path, encoding="utf-8") as f:
    tr = json.load(f)

print(f"gap-over-time for {path}  deckX={deckx:.0f}")
print(f"{'t':>6} {'x':>7} {'y':>7} {'vx':>7} {'vy':>7} {'gap=deckX-x':>12} {'phase':>10}")
min_gap = 1e18
min_vx = 1e18
neg_gap_before_touchdown = False
# sample ~ every 2s of game time
last_t = -100
for pt in tr:
    if not isinstance(pt, list) or len(pt) < 11:
        continue
    t, x, y, vx, vy, ang, thr, fuel, dmg, hf, ph = pt
    gap = deckx - x
    min_vx = min(min_vx, vx)
    if y > 5:  # in-flight (not final touchdown sample)
        min_gap = min(min_gap, gap)
        if gap < 0:
            neg_gap_before_touchdown = True
    if t - last_t >= 2.0 or y < 300:
        print(f"{t:6.1f} {x:7.0f} {y:7.0f} {vx:7.1f} {vy:7.1f} {gap:12.0f} {ph:>10}")
        last_t = t

print(f"\n  min in-flight gap (deckX - x): {min_gap:.0f}  "
      f"({'DECK STAYED AHEAD' if min_gap > 0 else 'DECK WAS CROSSED (gap went negative)'})")
print(f"  min vx over flight: {min_vx:.1f}  "
      f"({'vx NEVER reversed' if min_vx >= -2 else 'vx REVERSED'})")
