"""
Decompose the residual 30-vs-120 Hz ATTITUDE difference into its contributors, to confirm (not assume)
the "input-timing quantization" diagnosis.

Method: run the SAME timestamped control schedule at 30 Hz and 120 Hz, applying events at EXACT sim
time by splitting the physics interval at each event boundary. Then progressively remove each candidate
confound and measure how much of the attitude gap disappears:

  S0  baseline maneuver          — full maneuver, events split at exact time. (the residual we're explaining)
  S1  no turbulence              — start above the buffet band (y0=15000) so turb=0 the whole run.
  S2  no steering (burn only)    — remove the ArrowLeft/Right torque pulses (keep the burn).
  S3  no burn (steer only)       — remove thrust (keep the steer pulses).
  S4  coast only                 — no burn, no steer, no turbulence: pure gravity+drag+lift+weathercock.
  S5  frame-ALIGNED events       — snap event times to a common 8.33ms grid (the shared sdt) so the
                                    interval-split fractional-dt substep misalignment is removed.

Contribution of a factor ≈ (gap_with_factor − gap_without_factor). We report each gap and the drops.

Determinism: wind off; turbulence pure fn of b.t. So the only 30-vs-120 differences are: (a) the
fractional-dt substep from event-splitting changes ceil(dt*120) alignment, (b) any per-frame term.
After the 4ea7f03 fix there are NO per-frame physics terms, so (a) should dominate — S5 tests that.

Run:  py testing/decompose_attitude.py
"""
import json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from physics_harness import Harness

DRIVER = r"""
window.__DC = (function(){
  function clearKeys(){ for(var k in keys) delete keys[k]; }
  function reset(st){
    startMode('ocean'); b.opening=false; env={windBase:0,windGust:0,windPhase:0,gateX:0};
    b.x=st.x;b.y=st.y;b.vx=st.vx;b.vy=st.vy;b.ang=st.ang;b.angv=st.angv;b.fuel=st.fuel;
    b.thr=0;b.fin=0;b.rcsFuel=1e9;b.t=0;timeScale=1; clearKeys(); burnHeld=false; steerVal=0;
  }
  function applyEvent(ev){ burnHeld=!!ev.burn; steerVal=ev.steer||0; clearKeys();
    if(ev.steer>0) keys['ArrowRight']=true; else if(ev.steer<0) keys['ArrowLeft']=true; }
  function snap(){ return {x:b.x,y:b.y,vx:b.vx,vy:b.vy,ang:b.ang,angv:b.angv,fuel:b.fuel,t:b.t}; }
  // events applied at EXACT sim time by splitting the frame; optional grid snaps event times.
  // run with an optional pre-saturated throttle (thr0) so there is NO throttle ramp — tests whether
  // the once-per-frame smoother ramp is the residual's cause.
  function run(st, hz, seconds, evs, thr0){
    reset(st); if(thr0!==undefined){ b.thr=thr0; }
    var dt=1/hz, ei=0;
    while(ei<evs.length && evs[ei].t<=1e-9){ applyEvent(evs[ei]); ei++; }
    var t=0;
    while(t<seconds-1e-9){
      var end=Math.min(t+dt,seconds), cursor=t;
      while(ei<evs.length && evs[ei].t<end-1e-9){
        var et=evs[ei].t;
        if(et>cursor+1e-9){ update(et-cursor); cursor=et; }
        if(scene!=='flying') return snap();
        applyEvent(evs[ei]); ei++;
      }
      if(end>cursor+1e-9) update(end-cursor);
      if(scene!=='flying') return snap();
      t=end;
    }
    return snap();
  }
  return { run:run };
})(); 'ready';
"""

BUFFET = {"x": -6000, "y": 9000, "vx": 250, "vy": -250, "ang": -0.30, "angv": 0.0, "fuel": 60000}
ABOVE  = {"x": -6000, "y": 15000, "vx": 250, "vy": -250, "ang": -0.30, "angv": 0.0, "fuel": 60000}

FULL = [{"t":0,"burn":False,"steer":0},{"t":1.5,"burn":False,"steer":1},{"t":2.0,"burn":False,"steer":0},
        {"t":2.5,"burn":True,"steer":0},{"t":4.0,"burn":True,"steer":-1},{"t":4.4,"burn":True,"steer":0}]
BURN_ONLY  = [{"t":0,"burn":False,"steer":0},{"t":2.5,"burn":True,"steer":0}]
STEER_ONLY = [{"t":0,"burn":False,"steer":0},{"t":1.5,"burn":False,"steer":1},{"t":2.0,"burn":False,"steer":0},
              {"t":4.0,"burn":False,"steer":-1},{"t":4.4,"burn":False,"steer":0}]
COAST = [{"t":0,"burn":False,"steer":0}]

# grid-snapped FULL: event times rounded to the shared 8.33ms substep grid
G = 1.0/120.0
FULL_GRID = [{**e, "t": round(e["t"]/G)*G} for e in FULL]

SEC = 5.0

def gap(h, st, evs, thr0=None):
    ta = "" if thr0 is None else f", {thr0}"
    a = h.call(f"__DC.run({json.dumps(st)}, 30, {SEC}, {json.dumps(evs)}{ta})")
    b = h.call(f"__DC.run({json.dumps(st)}, 120, {SEC}, {json.dumps(evs)}{ta})")
    return {"dang_deg": abs(a["ang"]-b["ang"])*180/math.pi,
            "dangv": abs(a["angv"]-b["angv"]),
            "dpos": math.hypot(a["x"]-b["x"], a["y"]-b["y"]),
            "dfuel": abs(a["fuel"]-b["fuel"])}

def main():
    h = Harness(port=9421, profile=os.path.join(os.path.dirname(os.path.abspath(__file__)), "_prof_decomp"))
    try:
        h.start(); assert h.call(DRIVER)=="ready"
        S = {}
        S["S0_full_buffet"]      = gap(h, BUFFET, FULL)
        S["S1_no_turbulence"]    = gap(h, ABOVE,  FULL)
        S["S2_burn_only_buffet"] = gap(h, BUFFET, BURN_ONLY)
        S["S3_steer_only_buffet"]= gap(h, BUFFET, STEER_ONLY)
        S["S4_coast_buffet"]     = gap(h, BUFFET, COAST)
        S["S5_full_gridsnapped"] = gap(h, BUFFET, FULL_GRID)
        S["S6_full_above_grid"]  = gap(h, ABOVE,  FULL_GRID)
        # S7: burn the WHOLE run, throttle PRE-SATURATED (thr0=1) so there is no smoother ramp at all.
        # If the once-per-frame throttle/fin ramp is the residual's cause, this gap collapses toward S4.
        BURN_ALL = [{"t":0,"burn":True,"steer":0}]
        S["S7_presat_burn_above"] = gap(h, ABOVE, BURN_ALL, thr0=1.0)
        # S8: same but WITH the from-zero ramp (thr0=0) — isolates the ramp's contribution vs S7.
        S["S8_ramp_burn_above"]   = gap(h, ABOVE, BURN_ALL, thr0=0.0)
    finally:
        h.stop()

    print("="*76)
    print("30-vs-120 Hz gap under progressive confound removal (events at exact sim time):")
    print(f"  {'scenario':<22} {'dang(deg)':>10} {'dangv':>9} {'dpos(m)':>9} {'dfuel(kg)':>10}")
    for k,v in S.items():
        print(f"  {k:<22} {v['dang_deg']:>10.5f} {v['dangv']:>9.5f} {v['dpos']:>9.4f} {v['dfuel']:>10.4f}")
    print("="*76)
    d = lambda k: S[k]["dang_deg"]
    print("Attribution of the attitude gap (deg):")
    print(f"  S0 full maneuver, buffet band ............ {d('S0_full_buffet'):.5f}")
    print(f"  - turbulence contribution (S0 - S1) ...... {d('S0_full_buffet')-d('S1_no_turbulence'):+.5f}")
    print(f"  - event-timing/substep (S5 grid-snapped) . {d('S5_full_gridsnapped'):.5f}  (gap left after aligning events)")
    print(f"  - integrator+turb w/ aligned events (S6) . {d('S6_full_above_grid'):.5f}  (grid events, no turbulence)")
    print(f"  coast-only floor (integrator truncation) . {d('S4_coast_buffet'):.5f}")
    print("="*76)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"decompose_attitude.json"),"w") as f:
        json.dump(S, f, indent=2)

if __name__ == "__main__":
    main()
