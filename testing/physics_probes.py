"""
Targeted deep probes for BLUE ORIGIN LANDINGS physics — the subtle issues the A-K battery
doesn't isolate. Runs against the REAL game code in headless Chrome (reuses physics_harness.Harness).

Probes:
  P1  dead-fin           : does a nonzero `fin` arg change stepPhysics output? (grounding says NO — finD unused)
  P2  thr-smoothing-fr   : is b.thr smoothing (update(), NOT substepped) frame-rate dependent?
  P3  turbulence-fr      : is the turbulence kick (update(), NOT substepped, full dt) frame-rate dependent?
  P4  predictor-tq       : does the trajectory predictor ignore active steering (tq forced 0)?
  P5  full-frame-invar   : run the REAL update() loop at 30/60/120 Hz (game substep active) — outcome match?
  P6  com-pivot-drift    : does the CoM-pivot inject spurious translation when only rotating (no vel)?

Run:  py testing/physics_probes.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from physics_harness import Harness  # noqa: E402


PROBE_LIB = r"""
window.__P = (function(){
  function S(o){ return Object.assign({x:0,y:5000,vx:0,vy:0,ang:0,angv:0,fuel:50000}, o||{}); }

  // P1: run stepPhysics twice from identical state, differing ONLY in the fin arg.
  function finEffect(){
    mode='ocean'; applyModeParams('ocean'); SHIP_MODE=false; ASCENT_MODE=false;
    env={windBase:0,windGust:0,windPhase:0,gateX:0};
    var a=S({y:5000,vx:120,vy:-120,ang:0.2,angv:0,fuel:40000});
    var b=S({y:5000,vx:120,vy:-120,ang:0.2,angv:0,fuel:40000});
    stepPhysics(a, 1/120, 0, 0, 0.0);    // fin=0
    stepPhysics(b, 1/120, 0, 0, 1.0);    // fin=1 (max)
    return { dAng:(b.ang-a.ang), dAngv:(b.angv-a.angv), dVx:(b.vx-a.vx), dVy:(b.vy-a.vy),
             a:{ang:a.ang,angv:a.angv}, b:{ang:b.ang,angv:b.angv} };
  }

  // P6: pure rotation, zero velocity, zero thrust — does the CoM-pivot move x/y spuriously?
  // A booster with angv but no linear velocity should keep its CoM fixed; the tracked BASE
  // (s.x,s.y) is ALLOWED to move (it swings around the CoM), but the CoM must not translate.
  function comPivot(){
    mode='ocean'; applyModeParams('ocean'); SHIP_MODE=false; ASCENT_MODE=false;
    env={windBase:0,windGust:0,windPhase:0,gateX:0};
    var comH=62*0.42;
    var s=S({x:1000,y:5000,vx:0,vy:0,ang:0.0,angv:0.5,fuel:40000});
    var com0={x:s.x+Math.sin(s.ang)*comH, y:s.y+Math.cos(s.ang)*comH};
    // vacuum-ish high alt to kill aero: push y up
    s.y=60000; com0={x:s.x+Math.sin(s.ang)*comH, y:s.y+Math.cos(s.ang)*comH};
    for(var i=0;i<60;i++) stepPhysics(s,1/120,0,0,0);
    var com1={x:s.x+Math.sin(s.ang)*comH, y:s.y+Math.cos(s.ang)*comH};
    return { dComX:(com1.x-com0.x), dComY:(com1.y-com0.y), baseMoved:(Math.hypot(s.x-1000,s.y-60000)),
             ang:s.ang, angv:s.angv };
  }

  return { finEffect:finEffect, comPivot:comPivot };
})();
'ready';
"""


def run_real_update_loop(h, hz, seconds, control_js):
    """Drive the REAL game via update(dt) at a fixed dt=1/hz. control_js is a JS snippet that,
    given the elapsed time `T`, sets keys/burnHeld/steerVal. Returns final b state + scene/result."""
    dt = 1.0 / hz
    steps = int(round(seconds * hz))
    expr = f"""
    (function(){{
      // start a fresh ocean run through the real entry point
      startMode('ocean');
      // skip the locked opening so we control immediately: force opening done
      b.opening=false;
      // deterministic, no wind
      env={{windBase:0,windGust:0,windPhase:0,gateX:0}};
      // known start state (post-handoff descent), same for every hz
      b.x=-6000; b.y=9000; b.vx=250; b.vy=-250; b.ang=-0.3; b.angv=0; b.fuel=60000;
      b.thr=0; b.fin=0; b.rcsFuel=1e9;  // unlimited RCS so steering isn't gated
      for(var k in keys) delete keys[k]; burnHeld=false; steerVal=0; timeScale=1;
      var dt={dt};
      var n={steps};
      for(var i=0;i<n;i++){{
        var T=i*dt;
        {control_js}
        if(scene!=='flying') break;
        update(dt);
      }}
      return {{ x:b.x, y:b.y, vx:b.vx, vy:b.vy, ang:b.ang, angv:b.angv, fuel:b.fuel,
               scene:scene, ok:(result?result.ok:null), title:(result?result.title:null) }};
    }})()
    """
    return h.call(expr)


def main():
    h = Harness()
    out = {}
    try:
        h.start()
        ready = h.call(PROBE_LIB)
        assert ready == "ready", ready

        # P1 dead-fin
        fe = h.call("__P.finEffect()")
        out["P1_dead_fin"] = {
            "detail": fe,
            "fin_has_no_effect": abs(fe["dAng"]) < 1e-12 and abs(fe["dAngv"]) < 1e-12
                                 and abs(fe["dVx"]) < 1e-12 and abs(fe["dVy"]) < 1e-12,
        }

        # P6 com-pivot drift
        cp = h.call("__P.comPivot()")
        out["P6_com_pivot"] = {
            "detail": cp,
            "com_fixed": abs(cp["dComX"]) < 1.0 and abs(cp["dComY"]) < 1.0,
            "base_swings": cp["baseMoved"] > 1.0,
        }

        # P2 thr smoothing frame-rate: burn-key held, measure b.thr after 0.25 s at 30 vs 120 Hz
        # (isolate: no motion needed — just watch b.thr ramp). Use the real update loop.
        # thr isn't returned above; add a dedicated tiny loop reading b.thr.
        # Use 0.5 s so step counts are integers at all three rates (15/30/60) — identical total sim
        # time across frame rates, so any residual diff is genuine frame-rate sensitivity, not a
        # different simulated duration.
        def thr_after(hz):
            dt = 1.0/hz; n = int(round(0.5*hz))
            return h.call(f"""(function(){{ startMode('ocean'); b.opening=false; b.thr=0; b.fuel=60000;
              env={{windBase:0,windGust:0,windPhase:0,gateX:0}}; for(var k in keys)delete keys[k]; burnHeld=true; steerVal=0; timeScale=1;
              b.x=-6000;b.y=9000;b.vx=250;b.vy=-250;b.ang=-0.3;b.angv=0;b.rcsFuel=1e9;
              for(var i=0;i<{n};i++){{ if(scene!=='flying')break; update({dt}); }} return b.thr; }})()""")
        t30 = thr_after(30); t120 = thr_after(120)
        out["P2_thr_smoothing_framerate"] = {
            "thr_after_0.5s_30hz": t30, "thr_after_0.5s_120hz": t120,
            "diff": abs(t30 - t120),
            "frame_rate_dependent": abs(t30 - t120) > 0.02,
        }

        # P3 turbulence frame-rate: hold steady in the atmosphere (below entry, high qbar), no control,
        # measure angv spread at 30 vs 120 Hz over 1 s. Turbulence kick is once/frame at full dt (not substepped).
        def angv_after(hz):
            dt = 1.0/hz; n = int(round(1.0*hz))
            return h.call(f"""(function(){{ startMode('ocean'); b.opening=false;
              env={{windBase:0,windGust:0,windPhase:0,gateX:0}}; for(var k in keys)delete keys[k]; burnHeld=false; steerVal=0; timeScale=1;
              // low + fast for high qbar so turbulence is strong; no thrust/steer
              b.x=0;b.y=6000;b.vx=200;b.vy=-200;b.ang=0.0;b.angv=0;b.fuel=40000;b.rcsFuel=1e9;b.thr=0;
              for(var i=0;i<{n};i++){{ if(scene!=='flying')break; update({dt}); }}
              return {{angv:b.angv, ang:b.ang, y:b.y}}; }})()""")
        a30 = angv_after(30); a120 = angv_after(120)
        out["P3_turbulence_framerate"] = {
            "30hz": a30, "120hz": a120,
            "angv_diff": abs(a30["angv"] - a120["angv"]),
            "frame_rate_dependent": abs(a30["angv"] - a120["angv"]) > 0.05,
        }

        # P4 predictor ignores active steering: hold hard steer, compare predicted endpoint vs a
        # forecast that DID include the steer. We can only observe that predictTrajectory passes tq=0,
        # so its path won't bend with live tq. Measure: set b.angv big (as if steering), the predictor's
        # first-few-points curvature vs a manual step that applies tq.
        pr = h.call("""(function(){
          startMode('ocean'); b.opening=false;
          env={windBase:0,windGust:0,windPhase:0,gateX:0};
          b.x=0;b.y=6000;b.vx=150;b.vy=-120;b.ang=0.1;b.angv=0;b.fuel=40000;b.thr=1;b.fin=0;
          var pts=predictTrajectory();
          // compare endpoint if we instead manually integrate WITH tq=+1 (active steer)
          var s={x:b.x,y:b.y,vx:b.vx,vy:b.vy,ang:b.ang,angv:b.angv,fuel:b.fuel};
          for(var i=0;i<60;i++){ stepPhysics(s,0.3,1,1,0); if(s.y<=0)break; }
          var predEnd=pts.length?pts[pts.length-1]:null;
          return { predEndX: predEnd?predEnd.x:null, steerEndX: s.x, nPts: pts.length };
        })()""")
        out["P4_predictor_tq"] = {
            "detail": pr,
            "predictor_ignores_active_steer": True,  # structural: predictTrajectory hardcodes tq=0
            "note": "predictTrajectory passes tq=0; the X cannot bend with live ArrowLeft/Right torque, "
                    "only with body tilt already integrated into ang. steerEndX shows where active steer goes.",
        }

        # P5 full real-update-loop invariance at 30/60/120 with a fixed control script.
        # Coast 2 s, then burn full; steer right for a bounded 0.6 s pulse only (2.0-2.6 s) then release
        # so the booster makes a controlled attitude change instead of a runaway spin (a held steer
        # spins her to several rad/s, where ang is chaotically phase-sensitive and not a fair metric).
        ctrl = "burnHeld = (T>2.0); var st=(T>2.0 && T<2.6); steerVal = st?1:0; keys['ArrowRight'] = st;"
        f30 = run_real_update_loop(h, 30, 5.0, ctrl)
        f60 = run_real_update_loop(h, 60, 5.0, ctrl)
        f120 = run_real_update_loop(h, 120, 5.0, ctrl)
        import math
        def dp(a, b): return math.hypot(a["x"]-b["x"], a["y"]-b["y"])
        def dv(a, b): return math.hypot(a["vx"]-b["vx"], a["vy"]-b["vy"])
        out["P5_full_update_invariance"] = {
            "s30": {k: round(f30[k], 2) for k in ("x", "y", "vx", "vy", "ang", "angv", "fuel")},
            "s60": {k: round(f60[k], 2) for k in ("x", "y", "vx", "vy", "ang", "angv", "fuel")},
            "s120": {k: round(f120[k], 2) for k in ("x", "y", "vx", "vy", "ang", "angv", "fuel")},
            "pos_30_vs_120": round(dp(f30, f120), 2), "vel_30_vs_120": round(dv(f30, f120), 2),
            "angv_30_vs_120": round(abs(f30["angv"]-f120["angv"]), 4),
            "ang_30_vs_120": round(abs(f30["ang"]-f120["ang"]), 4),
        }

        # P7 NaN / end-to-end smoke: fly a full descent to touchdown at each rate; every state stays
        # finite and the run reaches a terminal scene ('done'). Catches any NaN the fixes might inject.
        def full_to_ground(hz):
            dt = 1.0/hz
            return h.call(f"""(function(){{
              startMode('ocean');
              for(var g=0; g<20000 && scene==='flying'; g++){{
                var T=g*{dt};
                burnHeld = (b.y < 4000 && b.vy < 0);   // simple auto: burn low & descending
                var st=(b.y<8000 && b.x < deckX()-200); steerVal = st?1:0; keys['ArrowRight']=st;
                update({dt});
              }}
              var fin = b ? [b.x,b.y,b.vx,b.vy,b.ang,b.angv,b.fuel] : [];
              var allFinite = fin.every(function(v){{return isFinite(v);}});
              return {{ scene:scene, ok:(result?result.ok:null), allFinite:allFinite, y:(b?b.y:null) }};
            }})()""")
        g30 = full_to_ground(30); g60 = full_to_ground(60); g120 = full_to_ground(120)
        out["P7_end_to_end_smoke"] = {
            "g30": g30, "g60": g60, "g120": g120,
            "all_finite": g30["allFinite"] and g60["allFinite"] and g120["allFinite"],
            "all_terminated": all(g["scene"] in ("done",) for g in (g30, g60, g120)),
        }

    finally:
        h.stop()

    print(json.dumps(out, indent=2))
    outname = "probes_" + (sys.argv[1] if len(sys.argv) > 1 else "baseline") + ".json"
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), outname), "w") as f:
        json.dump(out, f, indent=2)
    print("wrote " + outname)


if __name__ == "__main__":
    main()
