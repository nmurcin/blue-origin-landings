"""
reach_probe.py — Measure the PROJECTED landing spot (the in-game X trajectory
predictor) vs the deck, across the glide, to fix "landing short". This reads the
game's OWN predictTrajectory() — exactly what the player sees as the X — so it
answers the real complaint directly and fast (no full-flight, no timeout).

Method: skip the long opening ascent by forcing b.opening=false and seeding the
natural post-sep descent state (real spawn x + entry velocity). Fly a simple
decel burn (engine-first while high+fast); then, through the glide band, sample
predictTrajectory()'s LAST point x (the projected touchdown) and deckX(). Report
how far the projected landing falls short/long of the deck at several altitudes.

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
PORT = 9470

SETUP_JS = r"""
(function(){
  window.__err=null;
  var _raf=window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame=function(cb){return _raf(function(t){try{return cb(t);}
    catch(e){if(!window.__err)window.__err={msg:String(e&&e.message||e),stack:e&&e.stack?String(e.stack):null};throw e;}});};
  window.__seeded=false; window.__samples=[];
  function loop(){
    try{
      if(typeof scene!=='undefined' && scene==='flying' && typeof b!=='undefined' && b && typeof keys!=='undefined'){
        if(!window.__seeded){
          // skip opening ascent; seed the natural post-sep descent (spawn-like)
          b.opening=false; b.openMeco=true; b.openSep=true;
          b.y=10500; b.vx=440; b.vy=-490; b.ang=0.0; b.angv=0; b.thr=0;
          b.fuel=Math.max(b.fuel,60000); b.heatFrac=0; b.damage=0;
          window.__seeded=true;
        }
        var spd=Math.hypot(b.vx,b.vy);
        keys['ArrowLeft']=false;keys['ArrowRight']=false;keys[' ']=false;
        if(b.y>7500 && spd>250){
          var des=Math.atan2(-b.vx,-b.vy); var dA=b.ang-des;
          while(dA>Math.PI)dA-=2*Math.PI;while(dA<-Math.PI)dA+=2*Math.PI;
          if(dA>0.05)keys['ArrowLeft']=true;else if(dA<-0.05)keys['ArrowRight']=true;
          keys[' ']=true;
        }
        // in the glide band: sample the projected landing (last X point) vs deck
        if(window.__seeded && b.y<8000 && b.y>2200 && b.vy<0 && spd<270){
          try{
            var pts=predictTrajectory(); var last=pts&&pts.length?pts[pts.length-1]:null;
            var dcx=(typeof deckX==='function')?deckX():null;
            if(last) window.__samples.push({y:Math.round(b.y), proj_x:Math.round(last.x),
                                            deck:dcx, gap:Math.round(dcx-last.x), bx:Math.round(b.x), spd:Math.round(spd)});
          }catch(e){}
        }
      }
    }catch(e){if(!window.__err)window.__err={msg:String(e&&e.message||e),stack:e&&e.stack?String(e.stack):null};}
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  return true;
})()
"""

READ = ("(function(){try{return JSON.stringify({err:window.__err||null,n:(window.__samples||[]).length,"
        "samples:window.__samples||[],y:(typeof b!=='undefined'&&b)?Math.round(b.y):null,"
        "scene:(typeof scene!=='undefined')?scene:null});}catch(e){return JSON.stringify({err:{msg:''+e}});}})()")


def run(n):
    proc = launch_chrome(f"file:///{GAME.replace(chr(92),'/')}?play=ocean", port=PORT + n, headless=True)
    try:
        ws = discover_page_ws(PORT + n, timeout=25)
        cdp = CDP(ws); cdp.enable_page(); time.sleep(1.4)
        cdp.evaluate(SETUP_JS)
        t0 = time.time(); last = {}
        while time.time() - t0 < 60:
            last = json.loads(cdp.evaluate(READ) or "{}")
            if last.get("err"):
                return {"err": last["err"]}
            # once we've collected samples down to low altitude, done
            if last.get("n", 0) >= 4 and (last.get("y") or 9999) < 2400:
                break
            time.sleep(0.7)
        return {"samples": last.get("samples", [])}
    finally:
        try: cdp.close()
        except Exception: pass
        proc.terminate()


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    print(f"measuring projected-landing (X) vs deck across the glide, {runs} runs...\n", flush=True)
    entry_gaps, low_gaps, deck = [], [], None
    for i in range(runs):
        r = run(i)
        if r.get("err"):
            print(f"  run {i}: JS ERROR {r['err'].get('msg')}"); continue
        s = r.get("samples", [])
        if not s:
            print(f"  run {i}: no glide samples"); continue
        deck = s[0]["deck"]
        entry = s[0]; low = s[-1]
        entry_gaps.append(entry["gap"]); low_gaps.append(low["gap"])
        print(f"  run {i}: entry y={entry['y']} proj_x={entry['proj_x']} gap={entry['gap']:+d}  |  "
              f"low y={low['y']} proj_x={low['proj_x']} gap={low['gap']:+d}  (deck={deck})", flush=True)
    if low_gaps:
        print(f"\n  deck(ocean) = {deck}")
        print(f"  projected-landing GAP to deck (positive = landing SHORT / left of deck):")
        print(f"    at glide entry : median {statistics.median(entry_gaps):+.0f} m")
        print(f"    near floor     : median {statistics.median(low_gaps):+.0f} m")
        med = statistics.median(low_gaps)
        if abs(med) < 300:
            print(f"  => projected landing ~ON the deck (within {med:+.0f} m). Deck placement good.")
        elif med > 0:
            print(f"  => landing SHORT by ~{med:.0f} m. Move deck LEFT to ~{round(deck-med,-2):.0f} "
                  f"(or add reach) so the X meets Jacklyn.")
        else:
            print(f"  => landing LONG by ~{-med:.0f} m. Move deck RIGHT to ~{round(deck-med,-2):.0f}.")


if __name__ == "__main__":
    main()
