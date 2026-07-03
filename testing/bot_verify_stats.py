"""Merge verify batches and print final per-run table + offset distribution +
hit-rate-vs-padHalf, per variant. Reads bot_verify_<mode>_batch1.json and
bot_verify_<mode>_batch2.json (whichever exist)."""
import json
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
PAD = {"ocean": 44, "tower": 34}


def load(mode):
    runs = []
    meta = None
    for suf in ("_batch1", "_batch2", ""):
        p = os.path.join(HERE, f"bot_verify_{mode}{suf}.json")
        if os.path.exists(p):
            d = json.load(open(p, encoding="utf-8"))
            meta = d
            runs.extend(d["runs"])
    return meta, runs


for mode in ("ocean", "tower"):
    meta, runs = load(mode)
    if not runs:
        continue
    deck = meta["deckX"]
    pad = PAD[mode]
    n = len(runs)
    soft = [r for r in runs if r.get("survived") and r.get("soft")]
    offs = sorted(r["offset"] for r in soft if r["offset"] is not None)
    print(f"\n{'='*80}\n{mode.upper()}  deckX={deck}  padHalf={pad}  "
          f"N={n} runs  (survived+soft={len(soft)})\n{'='*80}")
    print(f"{'#':>2} {'land_x':>7} {'offset':>7} {'vx':>6} {'vy':>6} {'ang':>5} "
          f"{'surv':>4} {'soft':>4} {'fuel':>6} {'dmg':>4}")
    for i, r in enumerate(runs):
        print(f"{i:>2} {str(r['land_x']):>7} {str(round(r['offset']) if r['offset'] is not None else None):>7} "
              f"{str(r['vx']):>6} {str(r['vy']):>6} {str(r['ang']):>5} "
              f"{int(bool(r['survived'])):>4} {int(bool(r['soft'])):>4} "
              f"{str(r['fuel']):>6} {str(r['dmg']):>4}")
    if offs:
        print(f"\n  survived+soft rate: {len(soft)}/{n} = {100*len(soft)/n:.0f}%")
        print(f"  offset (soft) min={min(offs)} median={round(statistics.median(offs))} "
              f"mean={round(statistics.mean(offs))} max={max(offs)} "
              f"stdev={round(statistics.pstdev(offs))}")
        print(f"  hit rate @ shipped padHalf {pad}: "
              f"{sum(1 for o in offs if o<=pad)}/{n} = {100*sum(1 for o in offs if o<=pad)/n:.0f}%")
        print("  hit rate vs padHalf (fraction of ALL runs; burnups=miss):")
        for ph in [50, 100, 150, 200, 300, 400, 500, 600, 700, 800, 1000, 1200, 1500, 2000]:
            h = sum(1 for o in offs if o <= ph)
            print(f"     padHalf={ph:>4}: {h}/{n} = {100*h/n:>3.0f}%")
        # padHalf needed for target hit rates
        print("  padHalf needed for target hit rate (over all runs):")
        for tgt in (0.5, 0.6, 0.7, 0.8):
            need = max(1, round(tgt * n))
            ph = offs[need - 1] if need <= len(offs) else None
            print(f"     ~{int(tgt*100)}% ({need}/{n}) -> padHalf >= "
                  f"{ph if ph is not None else 'N/A (burnups cap it)'} m")
