"""
Neutral WING JUDGE — scores ANY build's index.html against ONE fixed scorecard so
the 3 judge-panel candidates are compared apples-to-apples (each authored its own
scorecard in its worktree; this ignores those and re-measures every build identically).

Runs the REAL stepPhysics of the given build over a full ocean glide at held lean
angles and reports landing-X shift, LEFT/RIGHT spread, symmetry, monotonicity, sign.

Usage: py testing/wing_judge.py <label>=<path-to-index.html> [<label>=<path> ...] [--port N]
Example:
  py testing/wing_judge.py baseline=index.html c1=.claude/worktrees/agent-XXX/index.html
Prints a per-build table + a final JSON summary. Uses ONE Chrome, one build at a time.
"""
import os
import sys
import math
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from physics_harness import Harness  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


def score_build(label, path, port):
    ap = path if os.path.isabs(path) else os.path.join(REPO, path)
    if not os.path.exists(ap):
        return {"label": label, "error": "missing: " + ap}
    h = Harness(html_path=ap, port=port)
    h.start()
    try:
        c = h.chrome.eval("__H.setup('ocean')")
        top, floor, deck = c["GLIDE_TOP_Y"], c["GLIDE_FLOOR_Y"], c["deckX"]
        y0, x0, vx0, vy0 = top - 400, deck - 6000, 180.0, -150.0
        base = full_glide(h, x0, y0, vx0, vy0, 0)
        shift = {}
        yfloor = {}
        for ld in (-30, -20, -10, 0, 10, 20, 30):
            r = full_glide(h, x0, y0, vx0, vy0, ld)
            shift[ld] = round(r["x"] - base["x"])
            yfloor[ld] = round(r["y"])
        L20, R20, L30, R30 = shift[-20], shift[20], shift[-30], shift[30]
        spread20 = shift[-20] - shift[20]
        sign_ok = L20 > 0 and R20 < 0
        symmetry = round(abs(L20) / abs(R20), 2) if R20 != 0 else 0.0
        mono_left = abs(shift[-30]) >= abs(shift[-20]) >= abs(shift[-10])
        mono_right = abs(shift[30]) >= abs(shift[20]) >= abs(shift[10])
        return {"label": label, "path": ap, "shift": shift, "yfloor": yfloor,
                "L20": L20, "R20": R20, "L30": L30, "R30": R30, "spread20": spread20,
                "sign_ok": sign_ok, "symmetry": symmetry,
                "monotonic_left": mono_left, "monotonic_right": mono_right,
                "consts": {"CL_K": c["CL_K"],
                           "BOOST": h.chrome.eval("typeof GLIDE_LIFT_BOOST!=='undefined'?GLIDE_LIFT_BOOST:null"),
                           "GLIDE_K": h.chrome.eval("typeof GLIDE_K!=='undefined'?GLIDE_K:null")}}
    finally:
        h.chrome.close()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    port = 9420
    for a in sys.argv[1:]:
        if a.startswith("--port"):
            port = int(a.split("=")[1]) if "=" in a else 9420
    builds = []
    for a in args:
        if "=" in a:
            lbl, p = a.split("=", 1)
            builds.append((lbl, p))
    if not builds:
        print("usage: py testing/wing_judge.py baseline=index.html c1=<path> c2=<path> c3=<path>")
        sys.exit(2)
    results = []
    for i, (lbl, p) in enumerate(builds):
        r = score_build(lbl, p, port + i)
        results.append(r)
        if "error" in r:
            print("[%s] ERROR %s" % (lbl, r["error"]))
            continue
        print("=== %s ===" % lbl)
        for ld in (-30, -20, -10, 0, 10, 20, 30):
            print("  lean %+4d -> %+6d m (floor y=%d)" % (ld, r["shift"][ld], r["yfloor"][ld]))
        print("  spread20=%d  sign_ok=%s  symmetry=%.2f  mono_L=%s  mono_R=%s"
              % (r["spread20"], r["sign_ok"], r["symmetry"], r["monotonic_left"], r["monotonic_right"]))
    print("\nJSON " + json.dumps([{k: v for k, v in r.items() if k != "path"} for r in results]))


if __name__ == "__main__":
    main()
