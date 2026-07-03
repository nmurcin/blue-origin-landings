"""
measure_reach.py — Measure where the REAL game's 7x2 booster actually lands, to
place Jacklyn correctly (fix "landing short"). Ground truth = real game, not sim.

Strategy per run (in-page autopilot, runs in the game's own rAF):
  1) engine-first DECEL burn while fast+high (survive reentry heat, bleed speed)
  2) release into the GLIDE — the physics auto-leans ~30deg toward the deck; we
     also nudge the fins toward the deck to seek MAX downrange reach
  3) terminal: ease toward vertical and burn to arrest so it "lands" (so the
     landing x is a real touchdown point, not a crater)
Reports landing_x per run and the distribution, plus the current deckX(), so we
can set the deck to the reachable band. Samples the game's spawn+wind RNG.

Usage: py measure_reach.py [n]     (default 6 runs)
Stdlib only; reuses bot_cdp. Does not edit game code.
"""
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot_cdp import launch_chrome, discover_page_ws, CDP  # noqa: E402

GAME = r"C:\Users\nmurcin\Lumen\local\blue-origin-landings\index.html"
PORT = 9461

AUTOPILOT_JS = r"""
(function(){
  window.__done=false; window.__land=null; window.__err=null; window.__maxx=-1e9;
  var _raf=window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame=function(cb){return _raf(function(t){try{return cb(t);}
    catch(e){if(!window.__err)window.__err={msg:String(e&&e.message||e),stack:e&&e.stack?String(e.stack):null};throw e;}});};
  function loop(){
    try{
      if(typeof scene!=='undefined' && (scene==='done' || window.__botDone)){
        if(!window.__done){window.__done=true;
          window.__land={x:(typeof b!=='undefined'&&b)?b.x:null, vy:(b?b.vy:null), vx:(b?b.vx:null),
                         deck:(typeof deckX==='function')?deckX():null};}
      } else if(typeof b!=='undefined' && b && typeof keys!=='undefined' && scene==='flying'){
        var spd=Math.hypot(b.vx,b.vy); var dcx=(typeof deckX==='function')?deckX():18000;
        if(b.x>window.__maxx) window.__maxx=b.x;
        keys['ArrowLeft']=false;keys['ArrowRight']=false;keys[' ']=false;
        if(b.opening){ /* wait out the opening */ }
        else if(b.y>7500 && spd>250){
          // DECEL: point engine-first (nose opposite velocity), burn
          var des=Math.atan2(-b.vx,-b.vy); var dA=b.ang-des;
          while(dA>Math.PI)dA-=2*Math.PI; while(dA<-Math.PI)dA+=2*Math.PI;
          if(dA>0.05)keys['ArrowLeft']=true; else if(dA<-0.05)keys['ArrowRight']=true;
          keys[' ']=true;
        } else if(b.y>2200){
          // GLIDE: lean toward the deck for max downrange reach (physics auto-leans; nudge harder)
          var want=(dcx>=b.x)?0.6:-0.6; var dA=b.ang-want;
          if(dA>0.04)keys['ArrowLeft']=true; else if(dA<-0.04)keys['ArrowRight']=true;
        } else {
          // TERMINAL: stand vertical, arrest descent so it actually lands
          var dA=b.ang-0.0;
          if(dA>0.04)keys['ArrowLeft']=true; else if(dA<-0.04)keys['ArrowRight']=true;
          if(b.vy<-22 || b.y<300) keys[' ']=true;
        }
      }
    }catch(e){if(!window.__err)window.__err={msg:String(e&&e.message||e),stack:e&&e.stack?String(e.stack):null};}
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  return true;
})()
"""

READ = ("(function(){try{return JSON.stringify({done:window.__done||false,land:window.__land||null,"
        "err:window.__err||null,maxx:window.__maxx,scene:(typeof scene!=='undefined')?scene:null,"
        "y:(typeof b!=='undefined'&&b)?b.y:null});}catch(e){return JSON.stringify({err:{msg:''+e}});}})()")


def one_run(n):
    proc = launch_chrome(f"file:///{GAME.replace(chr(92),'/')}?play=ocean", port=PORT + n, headless=True)
    try:
        ws = discover_page_ws(PORT + n, timeout=25)
        cdp = CDP(ws); cdp.enable_page(); time.sleep(1.4)
        cdp.evaluate(AUTOPILOT_JS)
        t0 = time.time()
        while time.time() - t0 < 120:
            st = json.loads(cdp.evaluate(READ) or "{}")
            if st.get("err"):
                return {"err": st["err"]}
            if st.get("done") and st.get("land"):
                return {"land": st["land"], "maxx": st.get("maxx")}
            time.sleep(0.8)
        return {"timeout": True, "maxx": st.get("maxx"), "last_y": st.get("y")}
    finally:
        try: cdp.close()
        except Exception: pass
        proc.terminate()


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    print(f"measuring real-game 7x2 landing reach, {n} runs...\n", flush=True)
    lands, deck = [], None
    for i in range(n):
        r = one_run(i)
        if r.get("err"):
            print(f"  run {i}: JS ERROR {r['err'].get('msg')}"); continue
        if r.get("timeout"):
            print(f"  run {i}: timeout (maxx={r.get('maxx'):.0f}, last_y={r.get('last_y')})"); continue
        L = r["land"]; deck = L.get("deck")
        lands.append(L["x"])
        short = (deck - L["x"]) if (deck is not None and L["x"] is not None) else None
        print(f"  run {i}: land_x={L['x']:.0f}  deck={deck}  short_by={short:.0f}  "
              f"vy={L['vy']:.1f} vx={L['vx']:.1f}  maxx={r.get('maxx'):.0f}", flush=True)
    if lands:
        print(f"\n  landing_x: min={min(lands):.0f} median={statistics.median(lands):.0f} max={max(lands):.0f}")
        print(f"  current deckX(ocean) = {deck}")
        print(f"  => median short_by = {deck - statistics.median(lands):.0f} m"
              if deck else "")
        print(f"  suggestion: set ocean deck near median landing x (~{round(statistics.median(lands),-2):.0f}) "
              f"so a competent glide reaches it.")
    else:
        print("\n  no clean landings measured.")


if __name__ == "__main__":
    main()
