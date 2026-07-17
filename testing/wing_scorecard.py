"""
Wing-authority SCORECARD — the single apples-to-apples metric every glide-wing
candidate is judged by. Runs the REAL stepPhysics over a full glide at several
held lean angles and reports:
  - landing-X shift per lean (how far banking walks the touchdown point)
  - LEFT vs RIGHT spread and SYMMETRY (|left shift| vs |right shift|)
  - sign correctness (lean LEFT must land RIGHT)
  - residual descent-rate at floor (didn't secretly become a rocket)

Baseline (current main, measured 2026-07-17): lean -20 -> +264 m, +20 -> -481 m,
spread 746 m, ASYMMETRIC (right barely steers). Target: BIG + SYMMETRIC spread
(e.g. >1500 m, |L|/|R| within ~1.4x), sign preserved, still lands.

Run: py testing/wing_scorecard.py [port]
Prints a JSON blob on the last line for programmatic comparison.
"""
import os
import sys
import math
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from physics_harness import Harness  # noqa: E402


def full_glide(h, x0, y0, vx0, vy0, lean_deg, secs=20.0):
    ang = lean_deg * math.pi / 180.0
    js = """
    (function(){
      __H.setup('ocean'); env={windBase:0,windGust:0,windPhase:0,gateX:0}; SHIP_MODE=false; ASCENT_MODE=false;
      var s={x:%f,y:%f,vx:%f,vy:%f,ang:%f,angv:0,fuel:70000};
      var dt=1/120, n=%d, ang=%f, floor=(typeof GLIDE_FLOOR_Y!=='undefined'?GLIDE_FLOOR_Y:2100);
      for(var i=0;i<n;i++){ s.ang=ang; s.angv=0; stepPhysics(s,dt,0,0,0); if(s.y<=floor||s.y<=0)break; }
      return {x:s.x,y:s.y,vx:s.vx,vy:s.vy};
    })()
    """ % (x0, y0, vx0, vy0, ang, int(secs / (1 / 120)), ang)
    return h.chrome.eval(js)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9388
    h = Harness(port=port)
    h.start()
    try:
        c = h.chrome.eval("__H.setup('ocean')")
        top, floor, espd, deck = c["GLIDE_TOP_Y"], c["GLIDE_FLOOR_Y"], c["GLIDE_ENTRY_SPD"], c["deckX"]
        y0 = top - 400
        x0 = deck - 6000
        vx0, vy0 = 180.0, -150.0
        base = full_glide(h, x0, y0, vx0, vy0, 0)
        rows = {}
        for ld in (-30, -20, -10, 0, 10, 20, 30):
            r = full_glide(h, x0, y0, vx0, vy0, ld)
            rows[ld] = {"x": round(r["x"]), "dx": round(r["x"] - base["x"]), "y": round(r["y"]), "vy": round(r["vy"], 1)}
        L20, R20 = rows[-20]["dx"], rows[20]["dx"]
        L30, R30 = rows[-30]["dx"], rows[30]["dx"]
        spread20 = rows[-20]["x"] - rows[20]["x"]
        sign_ok = L20 > 0 and R20 < 0
        sym = (abs(L20) / abs(R20)) if R20 != 0 else 0.0
        print("=== WING SCORECARD (ocean glide, full descent to floor) ===")
        print("glide band %d-%d, entry_spd %d, deckX %d, GLIDE_LEAN %.1f deg"
              % (floor, top, espd, deck, c["GLIDE_LEAN"] * 180 / math.pi))
        print("consts: CL_K=%s BOOST=%s CLAMP_G=%s GLIDE_K=%s TRIM_K=%s"
              % (c["CL_K"],
                 h.chrome.eval("typeof GLIDE_LIFT_BOOST!=='undefined'?GLIDE_LIFT_BOOST:null"),
                 h.chrome.eval("typeof GLIDE_CLAMP_G!=='undefined'?GLIDE_CLAMP_G:null"),
                 h.chrome.eval("typeof GLIDE_K!=='undefined'?GLIDE_K:null"),
                 h.chrome.eval("typeof GLIDE_TRIM_K!=='undefined'?GLIDE_TRIM_K:null")))
        for ld in (-30, -20, -10, 0, 10, 20, 30):
            print("  lean %+4d -> land x=%d (%+d m)  floor y=%d  vy=%.1f"
                  % (ld, rows[ld]["x"], rows[ld]["dx"], rows[ld]["y"], rows[ld]["vy"]))
        print("  LEFT(-20)=%+d  RIGHT(+20)=%+d  spread=%d m  sign_ok=%s  symmetry(|L|/|R|)=%.2f"
              % (L20, R20, spread20, sign_ok, sym))
        print(json.dumps({"L20": L20, "R20": R20, "L30": L30, "R30": R30, "spread20": spread20,
                          "sign_ok": sign_ok, "symmetry": round(sym, 2),
                          "lands": all(rows[ld]["y"] <= floor + 50 for ld in rows)}))
    finally:
        h.chrome.close()


if __name__ == "__main__":
    main()
