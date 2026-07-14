"""
Prove the ramp-substep fix: (1) it collapses the 30-vs-120 Hz residual that 4ea7f03 still had, and
(2) quantify how much it moves the 60 Hz trajectory vs 4ea7f03 (the "does it change feel at 60fps"
question — should be small, since smoothK telescopes so the per-frame end value is unchanged; only the
intra-frame path shifts toward the continuous ideal).

Compares three builds on an identical timestamped maneuver:
  4ea7f03  (committed: per-frame ramp)  vs  WORKING (per-substep ramp)
Reports: 30-vs-120 Hz gap for each build (residual), and 60Hz WORKING-vs-4ea7f03 delta (feel drift).

Run:  py testing/verify_ramp_fix.py
"""
import json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from physics_harness import Harness

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PREV = os.path.join(HERE, "_baseline", "blue_origin_landings_4ea7f03.html")
WORK = os.path.join(REPO, "blue_origin_landings.html")

DRIVER = r"""
window.__V = (function(){
  function clearKeys(){ for(var k in keys) delete keys[k]; }
  function reset(st){
    startMode('ocean'); b.opening=false; env={windBase:0,windGust:0,windPhase:0,gateX:0};
    b.x=st.x;b.y=st.y;b.vx=st.vx;b.vy=st.vy;b.ang=st.ang;b.angv=st.angv;b.fuel=st.fuel;
    b.thr=0;b.fin=0;b.rcsFuel=1e9;b.t=0;timeScale=1; clearKeys(); burnHeld=false; steerVal=0;
  }
  function applyEvent(ev){ burnHeld=!!ev.burn; steerVal=ev.steer||0; clearKeys();
    if(ev.steer>0) keys['ArrowRight']=true; else if(ev.steer<0) keys['ArrowLeft']=true; }
  function snap(){ return {x:b.x,y:b.y,vx:b.vx,vy:b.vy,ang:b.ang,angv:b.angv,fuel:b.fuel}; }
  function run(st, hz, seconds, evs){
    reset(st); var dt=1/hz, ei=0;
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

ST = {"x": -6000, "y": 9000, "vx": 250, "vy": -250, "ang": -0.30, "angv": 0.0, "fuel": 60000}
EVS = [{"t":0,"burn":False,"steer":0},{"t":1.5,"burn":False,"steer":1},{"t":2.0,"burn":False,"steer":0},
       {"t":2.5,"burn":True,"steer":0},{"t":4.0,"burn":True,"steer":-1},{"t":4.4,"burn":True,"steer":0}]

def diff(a,b):
    return dict(dpos=math.hypot(a["x"]-b["x"],a["y"]-b["y"]), dvel=math.hypot(a["vx"]-b["vx"],a["vy"]-b["vy"]),
                dang_deg=abs(a["ang"]-b["ang"])*180/math.pi, dangv=abs(a["angv"]-b["angv"]), dfuel=abs(a["fuel"]-b["fuel"]))

def run_build(path, port):
    h = Harness(html_path=path, port=port)
    try:
        h.start(); assert h.call(DRIVER)=="ready"
        s30 = h.call(f"__V.run({json.dumps(ST)}, 30, 5.0, {json.dumps(EVS)})")
        s60 = h.call(f"__V.run({json.dumps(ST)}, 60, 5.0, {json.dumps(EVS)})")
        s120 = h.call(f"__V.run({json.dumps(ST)}, 120, 5.0, {json.dumps(EVS)})")
        return {"s30":s30,"s60":s60,"s120":s120}
    finally:
        h.stop()

def main():
    prev = run_build(PREV, 9461)
    work = run_build(WORK, 9462)
    gap_prev = diff(prev["s30"], prev["s120"])
    gap_work = diff(work["s30"], work["s120"])
    feel60 = diff(work["s60"], prev["s60"])
    print("="*80)
    print("30-vs-120 Hz RESIDUAL (lower = more frame-rate-invariant):")
    print(f"  4ea7f03 (per-frame ramp):  dpos={gap_prev['dpos']:.4f}m dvel={gap_prev['dvel']:.4f} "
          f"dang={gap_prev['dang_deg']:.5f}deg dfuel={gap_prev['dfuel']:.3f}kg")
    print(f"  WORKING (per-substep ramp):dpos={gap_work['dpos']:.4f}m dvel={gap_work['dvel']:.4f} "
          f"dang={gap_work['dang_deg']:.5f}deg dfuel={gap_work['dfuel']:.3f}kg")
    print()
    print("60 Hz FEEL DRIFT (WORKING vs 4ea7f03 at the common frame rate — should be small):")
    print(f"  dpos={feel60['dpos']:.4f}m dvel={feel60['dvel']:.4f} dang={feel60['dang_deg']:.5f}deg "
          f"dfuel={feel60['dfuel']:.3f}kg")
    print("="*80)
    # regression-guard verdict: WORKING residual must be materially below 4ea7f03's
    improved = gap_work["dfuel"] < gap_prev["dfuel"]*0.25 and gap_work["dpos"] < gap_prev["dpos"]*0.5
    print(f"RAMP FIX IMPROVES FRAME-RATE INVARIANCE: {improved}")
    print(f"  (dfuel {gap_prev['dfuel']:.1f} -> {gap_work['dfuel']:.3f} kg, dpos {gap_prev['dpos']:.2f} -> {gap_work['dpos']:.3f} m)")
    with open(os.path.join(HERE,"verify_ramp_fix.json"),"w") as f:
        json.dump({"gap_prev":gap_prev,"gap_work":gap_work,"feel60":feel60,"prev":prev,"work":work}, f, indent=2)
    sys.exit(0 if improved else 1)

if __name__ == "__main__":
    main()
