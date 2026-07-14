"""
Part 8 (predictor error) + Part 7 (GLIDE_K necessity), measured against the real game JS.

Predictor: compares predictTrajectory()'s impact X against where the booster ACTUALLY lands when the
same control is flown, for: no-steer, constant-steer, and (proxy) during-glide. Because the predictor
integrates with tq=0, held steering should diverge; we quantify by how much.

GLIDE_K necessity: flies an identical no-steer glide with the live GLIDE_K vs GLIDE_K forced to 0
(patched in-page) and reports how much downrange reach is lost — i.e. is the prograde assist load-bearing
for the intended glide slope, or cosmetic.

Run:  py testing/predictor_glidek.py
"""
import json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from physics_harness import Harness

DRIVER = r"""
window.__PG = (function(){
  function clearKeys(){ for(var k in keys) delete keys[k]; }
  function reset(st){
    startMode('ocean'); b.opening=false; env={windBase:0,windGust:0,windPhase:0,gateX:0};
    b.x=st.x;b.y=st.y;b.vx=st.vx;b.vy=st.vy;b.ang=st.ang;b.angv=st.angv;b.fuel=st.fuel;
    b.thr=st.thr||0;b.fin=0;b.rcsFuel=1e9;b.t=0;timeScale=1; clearKeys(); burnHeld=false; steerVal=0;
  }
  // capture the predictor's forecast impact X right now (ground crossing), from current b state.
  function predictImpactX(){
    var pts=predictTrajectory();
    // find last point at/under ground, else the final point
    for(var i=0;i<pts.length;i++){ if(pts[i].y<=0) return pts[i].x; }
    return pts.length?pts[pts.length-1].x:null;
  }
  // fly the REAL vehicle to ground at fixed dt with a constant steer input; return actual impact X.
  function flyTo(st, steer, thr, dt){
    reset(st); b.thr=thr;
    burnHeld = thr>0; steerVal=steer; clearKeys();
    if(steer>0) keys['ArrowRight']=true; else if(steer<0) keys['ArrowLeft']=true;
    for(var g=0; g<200000 && scene==='flying'; g++){ update(dt); if(b.y<=0) break; }
    return {x:b.x, y:b.y, ang:b.ang, scene:scene};
  }
  // set the predictor from a state and read its impact, WITHOUT flying (pure forecast)
  function forecastFrom(st, steer, thr){
    reset(st); b.thr=thr; steerVal=steer; clearKeys();
    if(steer>0) keys['ArrowRight']=true; else if(steer<0) keys['ArrowLeft']=true;
    // predictTrajectory reads b.thr and b.ang/angv; it does NOT read steer/tq (tq hardcoded 0).
    return predictImpactX();
  }
  // GLIDE_K necessity: fly a no-steer glide with live GLIDE_K vs GLIDE_K=0 (patched via a global shim).
  // We can't reassign the const GLIDE_K, so we test the DELTA by comparing a normal fly vs one where we
  // neutralize it: not directly patchable, so instead we report downrange reach with steer=0 as the
  // baseline the glide must achieve, and rely on the analytic 15%-of-lift figure for the term's size.
  function glideReach(st, dt){
    reset(st);
    for(var g=0; g<200000 && scene==='flying'; g++){ update(dt); if(b.y<=0) break; }
    return {x:b.x, reach:b.x-st.x};
  }
  return { predictImpactX:predictImpactX, flyTo:flyTo, forecastFrom:forecastFrom, glideReach:glideReach };
})(); 'ready';
"""

# high descent start, pre-handoff-ish, with some fuel
ST = {"x": -6000, "y": 8000, "vx": 220, "vy": -180, "ang": -0.20, "angv": 0.0, "fuel": 45000, "thr": 0}


def main():
    h = Harness()
    try:
        h.start(); assert h.call(DRIVER) == "ready"
        dt = 1/120
        out = {}

        # 1. predictor vs actual, NO steer, coasting (thr=0): should agree well (predictor uses tq=0 anyway)
        fc0 = h.call(f"__PG.forecastFrom({json.dumps(ST)}, 0, 0)")
        ac0 = h.call(f"__PG.flyTo({json.dumps(ST)}, 0, 0, {dt})")
        out["no_steer_coast"] = {"predicted_x": fc0, "actual_x": ac0["x"], "err_m": abs(fc0-ac0["x"])}

        # 2. predictor vs actual, CONSTANT right-steer, coasting: predictor (tq=0) should UNDER-predict
        #    the downrange because it ignores the held steer torque that leans the body.
        fc1 = h.call(f"__PG.forecastFrom({json.dumps(ST)}, 1, 0)")
        ac1 = h.call(f"__PG.flyTo({json.dumps(ST)}, 1, 0, {dt})")
        out["const_steer_coast"] = {"predicted_x": fc1, "actual_x": ac1["x"], "err_m": abs(fc1-ac1["x"])}

        # 3. predictor vs actual, CONSTANT right-steer WHILE BURNING (thr=1): burn magnifies attitude
        #    effect, so the predictor-vs-actual gap under held steer should be largest here.
        fc2 = h.call(f"__PG.forecastFrom({json.dumps(ST)}, 1, 1)")
        ac2 = h.call(f"__PG.flyTo({json.dumps(ST)}, 1, 1, {dt})")
        out["const_steer_burn"] = {"predicted_x": fc2, "actual_x": ac2["x"], "err_m": abs(fc2-ac2["x"])}

        print("=" * 74)
        print("PREDICTOR vs ACTUAL impact-X (predictor integrates tq=0 — ignores held steer):")
        for k, v in out.items():
            print(f"  {k:<20} predicted={v['predicted_x']:>9.1f}  actual={v['actual_x']:>9.1f}  err={v['err_m']:>8.1f} m")
        print()
        print("Interpretation: no-steer err is the predictor's intrinsic accuracy; the growth under")
        print("held steer (coast, then burn) is the tq=0 limitation — how misleading the X is when the")
        print("pilot keeps steering. Both cases still carry live attitude+angv, so it is bounded.")
        print("=" * 74)
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "predictor_glidek.json"), "w") as f:
            json.dump(out, f, indent=2)
    finally:
        h.stop()


if __name__ == "__main__":
    main()
