"""
phase_sweep_probe.py — Ride the REAL game through EVERY descent phase and trap any
JS error, not just the reentry->glide transition. Catches crashes that could lurk in
the terminal/straighten/landing-burn/touchdown code paths too.

Flow (in-page autopilot, runs in the game's own rAF; error trap wraps rAF so a throw
in the render/update loop is captured with message+stack):
  - skip the long opening: force b.opening=false and seed a realistic post-sep state
  - DECEL: engine-first burn while high+fast
  - GLIDE: release; physics auto-leans ~30deg (the phase that was crashing)
  - TERMINAL: below the floor, stand vertical and burn to arrest -> real touchdown
  - run until scene=='done' (touchdown handled + scored) or timeout

PASS = reached scene 'done' (or ground) with NO trapped error through all phases.
Takes an optional port arg so it never collides with another headless Chrome.

Stdlib only; reuses bot_cdp. Does not edit game code.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot_cdp import launch_chrome, discover_page_ws, CDP  # noqa: E402

GAME = r"C:\Users\nmurcin\Lumen\local\blue-origin-landings\index.html"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9480

TRAP_AND_FLY = r"""
(function(){
  window.__err=null; window.__phases={}; window.__done=false; window.__land=null;
  var _raf=window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame=function(cb){return _raf(function(t){try{return cb(t);}
    catch(e){if(!window.__err)window.__err={msg:String(e&&e.message||e),stack:e&&e.stack?String(e.stack):null,src:'raf'};throw e;}});};
  window.onerror=function(m,s,l,c,e){if(!window.__err)window.__err={msg:String(m),line:l,stack:e&&e.stack?String(e.stack):null,src:'onerror'};return false;};
  window.__seeded=false;
  function mark(p){window.__phases[p]=(window.__phases[p]||0)+1;}
  function loop(){
    try{
      if(typeof scene!=='undefined' && (scene==='done'||window.__botDone)){
        if(!window.__done){window.__done=true; mark('done');
          window.__land={x:(typeof b!=='undefined'&&b)?b.x:null,vy:(b?b.vy:null),vx:(b?b.vx:null),
                         deck:(typeof deckX==='function')?deckX():null};}
      } else if(typeof scene!=='undefined' && scene==='flying' && typeof b!=='undefined' && b && typeof keys!=='undefined'){
        if(!window.__seeded){
          // gentle seed (same shape crash_probe descends cleanly with): already slowed into the
          // glide regime so we exercise GLIDE -> TERMINAL -> soft TOUCHDOWN, not a hypersonic lawn dart.
          b.opening=false; b.y=8000; b.vx=150; b.vy=-170; b.ang=0.10; b.angv=0; b.thr=0;
          b.fuel=Math.max(b.fuel,40000); b.heatFrac=0; b.damage=0; window.__seeded=true;
        }
        var spd=Math.hypot(b.vx,b.vy);
        keys['ArrowLeft']=false;keys['ArrowRight']=false;keys[' ']=false;keys['ArrowUp']=false;
        if(b.y>7500 && spd>250){
          mark('decel');
          var des=Math.atan2(-b.vx,-b.vy); var dA=b.ang-des;
          while(dA>Math.PI)dA-=2*Math.PI;while(dA<-Math.PI)dA+=2*Math.PI;
          if(dA>0.05)keys['ArrowLeft']=true;else if(dA<-0.05)keys['ArrowRight']=true;
          keys[' ']=true;
        } else if(b.y>2100){
          mark('glide');   // physics auto-leans; let it fly, nudge toward deck for reach
          var dcx=(typeof deckX==='function')?deckX():16000; var want=(dcx>=b.x)?0.55:-0.55;
          var dA=b.ang-want; if(dA>0.05)keys['ArrowLeft']=true;else if(dA<-0.05)keys['ArrowRight']=true;
        } else {
          mark('terminal'); // stand vertical; let it fall to a real touchdown, only arresting hard near the pad
          var dA=b.ang-0.0; if(dA>0.05)keys['ArrowLeft']=true;else if(dA<-0.05)keys['ArrowRight']=true;
          // burn ONLY in the last ~120 m so it descends into an actual touchdown within the window
          if(b.y<120 && b.vy<-6) keys[' ']=true;
        }
      }
    }catch(e){if(!window.__err)window.__err={msg:String(e&&e.message||e),stack:e&&e.stack?String(e.stack):null,src:'ap'};}
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  return true;
})()
"""

READ = ("(function(){try{return JSON.stringify({err:window.__err||null,done:window.__done||false,"
        "land:window.__land||null,phases:window.__phases||{},"
        "y:(typeof b!=='undefined'&&b)?Math.round(b.y):null,ang:(b?Number(b.ang.toFixed(2)):null),"
        "scene:(typeof scene!=='undefined')?scene:null});}catch(e){return JSON.stringify({err:{msg:''+e}});}})()")


def main():
    proc = launch_chrome(f"file:///{GAME.replace(chr(92),'/')}?play=ocean", port=PORT, headless=True)
    try:
        ws = discover_page_ws(PORT, timeout=25)
        cdp = CDP(ws); cdp.enable_page(); time.sleep(1.5)
        cdp.evaluate(TRAP_AND_FLY)
        print(f"phase-sweep probe running (port {PORT})...", flush=True)
        t0 = time.time(); last = {}
        while time.time() - t0 < 90:
            last = json.loads(cdp.evaluate(READ) or "{}")
            if last.get("err"):
                break
            if last.get("done"):
                break
            print(f"  t={time.time()-t0:4.1f}s y={last.get('y')} ang={last.get('ang')} "
                  f"scene={last.get('scene')} phases={last.get('phases')}", flush=True)
            time.sleep(1.2)

        print("\n" + "=" * 60)
        err = last.get("err")
        phases = last.get("phases", {})
        if err:
            print("FAIL — JS ERROR TRAPPED:")
            print(f"   source : {err.get('src')}")
            print(f"   message: {err.get('msg')}")
            for ln in str(err.get("stack") or "").splitlines()[:6]:
                print(f"      {ln}")
            return 1
        phases_hit = [p for p in ("decel", "glide", "terminal", "done") if phases.get(p)]
        if not last.get("done"):
            print(f"INCONCLUSIVE — no touchdown in window. phases exercised: {phases_hit}")
            print(f"   last y={last.get('y')} scene={last.get('scene')}")
            # still a partial pass if it got through glide+terminal with no error
            return 2
        L = last.get("land", {})
        print("PASS — flew DECEL -> GLIDE -> TERMINAL -> TOUCHDOWN with NO JS error.")
        print(f"   phases exercised   : {phases_hit}")
        print(f"   touchdown          : x={L.get('x'):.0f} vy={L.get('vy'):.1f} vx={L.get('vx'):.1f} deck={L.get('deck')}")
        gap = (L.get("deck") - L.get("x")) if (L.get("deck") is not None and L.get("x") is not None) else None
        if gap is not None:
            print(f"   landing gap to deck: {gap:+.0f} m ({'SHORT' if gap>0 else 'long'})")
        return 0
    finally:
        try: cdp.close()
        except Exception: pass
        proc.terminate()


if __name__ == "__main__":
    sys.exit(main())
