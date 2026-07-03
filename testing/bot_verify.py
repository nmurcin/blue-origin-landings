"""
bot_verify.py — Verify the CURRENT game (index.html, deckX now 14000/17000) is
WINNABLE and characterize landing precision. Runs the robust active-steering
strategy N times per variant against the REAL game, sampling the game's spawn +
wind randomization, and reports:

  - per-run table: land_x, offset=|land_x - deckX|, on_deck?(padHalf), vx, vy,
    survived?(no burnup), fuel, result(WON/LOST)
  - offset distribution: min / median / max
  - on-deck HIT RATE at the shipped padHalf (44 ocean / 34 tower)
  - hit rate at a sweep of candidate padHalf values -> the padHalf that yields a
    ~60-80% hit rate (winnable-but-challenging)

The bot SEEKS the game's own deckX (14000/17000). Scoring uses the game's live
deckX() from each run's outcome, so this measures winnability of the shipped game.

Usage: py bot_verify.py <mode> <n>     e.g.  py bot_verify.py ocean 7
       py bot_verify.py both 7         runs both variants
"""
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot_sweep import run_strategy, DECKX, PADHALF, OKV  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# Robust strategy per variant (from the envelope study): entry decel burn to
# survive the hot entry + moderate low-band brake + terminal descent-rate + deck-seek.
STRAT = {
    "ocean": {"burnStartAlt": 7000, "bleedVx": 45, "glideLean": -2, "aNet": 10.5, "entryDecelSpd": 340},
    "tower": {"burnStartAlt": 7000, "bleedVx": 35, "glideLean": -2, "aNet": 9.5,  "entryDecelSpd": 200},
}


def verify(mode, n):
    deck = DECKX[mode]
    pad = PADHALF[mode]
    okvy, okvx = OKV[mode]
    strat = STRAT[mode]
    rows = []
    print(f"\n{'='*100}\n=== VERIFY {mode.upper()}  deckX={deck}  padHalf={pad}  "
          f"OK vy<={okvy} vx<={okvx}  ({n} runs) ===\n{'='*100}", flush=True)
    hdr = (f"{'#':>2} {'result':>6} {'land_x':>7} {'deckX':>6} {'offset':>7} {'on_deck':>7} "
           f"{'vx':>6} {'vy':>6} {'ang':>5} {'surv':>4} {'fuel':>6} {'dmg':>4}")
    print(hdr, flush=True)
    for i in range(n):
        row, out = run_strategy(mode, f"V{mode[:2]}{i}", strat, verbose=False)
        # use the GAME's live deckX from the outcome if present, else our constant
        gdeck = out.get("deckX") if out.get("deckX") is not None else deck
        lx = out.get("x")
        off = abs(lx - gdeck) if lx is not None else None
        surv = (out.get("result") in ("WON", "LOST") and (out.get("dmg", 100) or 0) < 100
                and out.get("y", 99) is not None and abs(out.get("y", 99)) < 5)
        soft = (out.get("vy") is not None and -out.get("vy") <= okvy
                and abs(out.get("vx", 99)) <= okvx
                and abs(out.get("ang", 99)) <= (10 if mode == "ocean" else 6))
        on = (off is not None and off <= pad and surv and soft)
        rec = {
            "i": i, "result": out.get("result"), "land_x": lx, "deckX": gdeck,
            "offset": off, "on_deck": on, "vx": out.get("vx"), "vy": out.get("vy"),
            "ang": out.get("ang"), "survived": surv, "soft": soft,
            "fuel": out.get("fuel"), "dmg": out.get("dmg"),
            "min_vx": row.get("min_vx"), "vx_never_neg": row.get("vx_never_neg"),
        }
        rows.append(rec)
        print(f"{i:>2} {str(rec['result']):>6} {str(lx):>7} {gdeck:>6} "
              f"{str(round(off) if off is not None else None):>7} {str(int(on)):>7} "
              f"{str(rec['vx']):>6} {str(rec['vy']):>6} {str(rec['ang']):>5} "
              f"{str(int(surv)):>4} {str(rec['fuel']):>6} {str(rec['dmg']):>4}", flush=True)

    # distribution over runs that at least reached the ground softly (a fair
    # "well-flown" population); also report over ALL runs.
    def dist(vals):
        vals = [v for v in vals if v is not None]
        if not vals:
            return None
        return (round(min(vals)), round(statistics.median(vals)), round(max(vals)))

    all_off = [r["offset"] for r in rows if r["offset"] is not None]
    soft_off = [r["offset"] for r in rows if r["offset"] is not None and r["soft"] and r["survived"]]
    print(f"\n  -- {mode} offset distribution (min/median/max) --", flush=True)
    print(f"     ALL runs      : {dist(all_off)}   n={len(all_off)}", flush=True)
    print(f"     survived+soft : {dist(soft_off)}   n={len(soft_off)}", flush=True)

    surv_soft = [r for r in rows if r["survived"] and r["soft"]]
    hit_ship = sum(1 for r in rows if r["on_deck"])
    print(f"\n  -- {mode} HIT RATE (survived + soft + within padHalf {pad}) --", flush=True)
    print(f"     {hit_ship}/{len(rows)} = {100*hit_ship/len(rows):.0f}%   "
          f"(survived+soft: {len(surv_soft)}/{len(rows)})", flush=True)

    # what padHalf yields ~60-80% hit rate (over survived+soft runs, since a burnup
    # can never be a landing regardless of pad size)
    print(f"\n  -- {mode} hit rate vs candidate padHalf (over survived+soft runs) --", flush=True)
    base = surv_soft if surv_soft else rows
    cand = [44, 34, 100, 150, 200, 300, 400, 500, 700, 1000, 1500]
    cand = sorted(set(cand))
    for ph in cand:
        hits = sum(1 for r in base if r["offset"] is not None and r["offset"] <= ph)
        frac = hits / len(rows) if rows else 0     # fraction of ALL runs (burnups count as miss)
        frac_soft = hits / len(base) if base else 0
        print(f"     padHalf={ph:>4}: {hits}/{len(rows)} all-runs={100*frac:>3.0f}%  "
              f"soft-runs={100*frac_soft:>3.0f}%", flush=True)

    # persist (suffix keeps batches from clobbering each other)
    suffix = os.environ.get("VERIFY_SUFFIX", "")
    with open(os.path.join(HERE, f"bot_verify_{mode}{suffix}.json"), "w", encoding="utf-8") as f:
        json.dump({"mode": mode, "deckX": deck, "padHalf": pad, "runs": rows}, f, indent=1)
    return rows


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "both"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    modes = ["ocean", "tower"] if mode == "both" else [mode]
    for m in modes:
        verify(m, n)
