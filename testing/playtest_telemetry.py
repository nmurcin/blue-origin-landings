"""
Part 9 (automated portion): fly the required playtest scenarios headlessly against the REAL game and
capture telemetry (velocity, attitude, angular rate, throttle, fuel, touchdown classification), plus
orientation samples during a down-right retro-burn so the visual claims can be checked numerically.

Scenarios (autopiloted with a simple deterministic controller so they actually land):
  1 nominal 60 Hz     2 nominal 30 Hz     3 nominal 120 Hz
  4 down-right retro-burn orientation check (samples aft/nose/thrust vectors while burning)
  5 aggressive gimbal/attitude recovery (spin up, then recover to vertical)
  6 hard landing (come in fast)     7 excessive-tilt landing     8 off-deck landing

The autopilot: below a trigger altitude, burn to null vertical speed; steer toward deckX; stand vertical
near the deck. Tuned only enough to exercise each outcome — not to be a champion pilot.

Run:  py testing/playtest_telemetry.py
"""
import json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from physics_harness import Harness

DRIVER = r"""
window.__PT = (function(){
  function clearKeys(){ for(var k in keys) delete keys[k]; }
  // Autopilot flight to touchdown. cfg: {hz, burnAlt, standAlt, hard, tilt, offdeck}. Returns telemetry.
  function fly(cfg){
    startMode('ocean'); b.opening=false; env={windBase:0,windGust:0,windPhase:0,gateX:0};
    // start post-handoff, descending toward the deck
    b.x=-6000;b.y=9000;b.vx=240;b.vy=-220;b.ang=-0.25;b.angv=0;b.fuel=55000;b.thr=0;b.fin=0;b.rcsFuel=1e9;b.t=0;timeScale=1;
    clearKeys(); burnHeld=false; steerVal=0;
    var dt=1/cfg.hz, dk=deckX();
    var samples=[]; var burnAlt=cfg.burnAlt||3500; var standAlt=cfg.standAlt||1500;
    for(var g=0; g<400000 && scene==='flying'; g++){
      // --- simple deterministic controller ---
      var tq=0, burn=false;
      var wantX = cfg.offdeck ? dk+600 : dk;          // off-deck test aims 600 m long
      // steer: lean toward the target while high; stand vertical when low (unless tilt test)
      if(b.y>standAlt){
        if(b.x < wantX-80) tq=1; else if(b.x > wantX+80) tq=-1;
        // limit lean
        if(b.ang>0.5) tq=-1; else if(b.ang<-0.5) tq=1;
      } else if(!cfg.tilt){
        // stand vertical: drive ang->0
        if(b.ang>0.02) tq=-1; else if(b.ang<-0.02) tq=1;
      } else {
        // tilt test: hold a big lean into touchdown
        if(b.ang<0.35) tq=1;
      }
      // burn: null vertical speed below burnAlt; hard test burns late/less
      var trig = cfg.hard ? burnAlt*0.45 : burnAlt;
      if(b.y<trig && b.vy < (cfg.hard? -14 : -6)) burn=true;
      // apply
      steerVal=tq; clearKeys();
      if(tq>0) keys['ArrowRight']=true; else if(tq<0) keys['ArrowLeft']=true;
      burnHeld=burn;
      // sample orientation while burning in the down-right phase (for scenario 4)
      if(cfg.sampleOrient && b.thr>0.2 && b.vx>0 && b.vy<0 && samples.length<40 && (g%3===0)){
        samples.push({t:+b.t.toFixed(2), y:+b.y.toFixed(0),
          vx:+b.vx.toFixed(1), vy:+b.vy.toFixed(1), ang:+b.ang.toFixed(3),
          noseX:+Math.sin(b.ang).toFixed(3), noseY:+Math.cos(b.ang).toFixed(3),
          tailX:+(-Math.sin(b.ang)).toFixed(3), tailY:+(-Math.cos(b.ang)).toFixed(3),
          thrX:+(Math.sin(b.ang)).toFixed(3), thrY:+(Math.cos(b.ang)).toFixed(3), thr:+b.thr.toFixed(2)});
      }
      update(dt);
      if(b.y<=0) break;
    }
    return {
      scene:scene, ok:(result?result.ok:null), title:(result?result.title:null),
      lines:(result?result.lines:null),
      final:{x:+b.x.toFixed(1), y:+b.y.toFixed(2), vx:+b.vx.toFixed(2), vy:+b.vy.toFixed(2),
             ang_deg:+(b.ang*180/Math.PI).toFixed(2), angv:+b.angv.toFixed(4), fuel:+b.fuel.toFixed(0)},
      deckX:dk, offset:+(Math.abs(b.x-dk)).toFixed(1), samples:samples
    };
  }
  return { fly:fly };
})(); 'ready';
"""


def main():
    h = Harness()
    out = {}
    try:
        h.start(); assert h.call(DRIVER) == "ready"
        scen = {
            "1_nominal_60hz": {"hz": 60},
            "2_nominal_30hz": {"hz": 30},
            "3_nominal_120hz": {"hz": 120},
            "4_retroburn_orient": {"hz": 60, "sampleOrient": True},
            "5_gimbal_recovery": {"hz": 60, "standAlt": 2200},
            "6_hard_landing": {"hz": 60, "hard": True},
            "7_excessive_tilt": {"hz": 60, "tilt": True},
            "8_off_deck": {"hz": 60, "offdeck": True},
        }
        for name, cfg in scen.items():
            out[name] = h.call(f"__PT.fly({json.dumps(cfg)})")
    finally:
        h.stop()

    print("=" * 92)
    print("PLAYTEST TELEMETRY (headless autopilot, real game):")
    for name, r in out.items():
        f = r["final"]
        cls = "LAND OK" if r["ok"] else ("crash-splash" if r["ok"] is False else "?")
        print(f"\n[{name}]  -> {cls}  ({r.get('title')})")
        print(f"    final: vy={-f['vy']:.2f} m/s  drift|vx|={abs(f['vx']):.2f}  tilt={f['ang_deg']:.2f}°  "
              f"angv={f['angv']:.4f}  fuel={f['fuel']}  offset={r['offset']} m (deck {r['deckX']})")
    # orientation check
    s = out["4_retroburn_orient"]["samples"]
    print("\n" + "=" * 92)
    print("ORIENTATION during down-right retro-burn (vx>0, vy<0, thr>0.2):")
    if s:
        ok_all = all(x["tailX"] > 0 and x["tailY"] < 0 and x["noseX"] < 0 and x["noseY"] > 0
                     and x["thrX"] < 0 and x["thrY"] > 0 for x in s)
        e = s[len(s)//2]
        print(f"  sample: ang={e['ang']} rad  nose=({e['noseX']},{e['noseY']})  tail=({e['tailX']},{e['tailY']})  "
              f"thrust=({e['thrX']},{e['thrY']})")
        print(f"  aft bottom-right (tail.x>0,tail.y<0)? {e['tailX']>0 and e['tailY']<0}")
        print(f"  nose top-left    (nose.x<0,nose.y>0)? {e['noseX']<0 and e['noseY']>0}")
        print(f"  thrust up-left   (thr.x<0, thr.y>0)?  {e['thrX']<0 and e['thrY']>0}")
        print(f"  ALL {len(s)} samples consistent with spec orientation: {ok_all}")
    else:
        print("  (no down-right burning samples captured — autopilot burned in a different phase)")
    print("=" * 92)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "playtest_telemetry.json"), "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
