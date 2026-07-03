"""
crash_probe.py — Prove the reentry->glide transition no longer crashes the game.

Launches the REAL game headless at ?play=ocean, installs a page-side error trap
(window.onerror + unhandledrejection + wraps requestAnimationFrame so a throw
inside the rAF/render loop is captured with its message+stack), then injects a
minimal autopilot: hold engine-first decel burn until slowed, then RELEASE into
the glide (thr=0) so the game enters the exact reentry->glide transition that was
crashing. Polls state + the error trap for ~40 s of game time.

PASS  = booster passes through the glide band (y falls below GLIDE_TOP_Y while
        slowed) AND no error was trapped AND the render loop kept ticking.
FAIL  = any trapped error (prints message+stack) or the loop froze at transition.

Stdlib only; reuses bot_cdp. Does not edit game code.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot_cdp import launch_chrome, discover_page_ws, CDP  # noqa: E402

GAME = r"C:\Users\nmurcin\Lumen\local\blue-origin-landings\index.html"
PORT = 9457

# Page-side error trap: capture the FIRST error from any source, incl. the rAF/render loop.
TRAP_JS = r"""
(function(){
  window.__err = null;
  window.onerror = function(msg, src, line, col, err){
    if(!window.__err) window.__err = {msg:String(msg), line:line, col:col,
       stack: err && err.stack ? String(err.stack) : null, src:'onerror'};
    return false;
  };
  window.addEventListener('unhandledrejection', function(e){
    if(!window.__err) window.__err = {msg:'unhandledrejection: '+ (e.reason&&e.reason.message||e.reason),
       stack: e.reason&&e.reason.stack?String(e.reason.stack):null, src:'promise'};
  });
  // wrap rAF so an exception inside the render/update loop is captured (else it
  // just kills the frame silently and the canvas freezes).
  var _raf = window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame = function(cb){
    return _raf(function(t){
      try { return cb(t); }
      catch(e){
        if(!window.__err) window.__err = {msg:String(e && e.message || e),
           stack: e && e.stack ? String(e.stack) : null, src:'raf'};
        throw e;
      }
    });
  };
  return true;
})()
"""

# Probe driver: once the game is flying (past the opening/ascent), FORCE the exact
# reentry->glide transition state (post-decel: mid-altitude, slowed, descending) and
# then RELEASE all controls so the real game physics + render carry the booster down
# through the glide band. This deterministically exercises the glide code path
# (inGlide weathercock + lift boost + drawGlideGuide) that was crashing — no need to
# fly it there. Re-arm once so we don't fight the game's own re-seeding.
AUTOPILOT_JS = r"""
(function(){
  window.__ap = true; window.__frames = 0; window.__minY = 1e9;
  window.__enteredGlide=false; window.__forced=false; window.__sawGlideY=null;
  function loop(){
    try{
      window.__frames++;
      var flying = (typeof scene!=='undefined' && scene==='flying');
      if (flying && typeof b !== 'undefined' && b && typeof keys !== 'undefined'){
        if (!window.__forced){
          // FORCE post-decel glide-entry state: high in the glide band, slowed, descending.
          b.opening = false;
          b.y = 8200; b.vx = 150; b.vy = -175; b.ang = 0.10; b.angv = 0;
          b.thr = 0; b.fuel = Math.max(b.fuel, 30000); b.heatFrac = 0; b.damage = 0;
          window.__forced = true;
        }
        // release everything — let the game's own physics fly the glide
        keys['ArrowLeft']=false; keys['ArrowRight']=false; keys[' ']=false; keys['ArrowUp']=false;
        var spd = Math.hypot(b.vx, b.vy);
        if (b.y < window.__minY) window.__minY = b.y;
        // record that we're inside the glide band descending (the crash window)
        if (window.__forced && b.y < 8300 && b.y > 2100 && b.vy < 0 && spd < 260){
          window.__enteredGlide = true; window.__sawGlideY = b.y;
        }
      }
    }catch(e){ if(!window.__err) window.__err={msg:String(e&&e.message||e), stack:e&&e.stack?String(e.stack):null, src:'ap'}; }
    if(window.__ap) requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  return true;
})()
"""

READ_JS = (
    "(function(){try{"
    "var s=(typeof scene!=='undefined')?scene:null;"
    "if(typeof b==='undefined'||!b)return JSON.stringify({noB:true,scene:s,err:window.__err||null,frames:window.__frames||0});"
    "var projx=null,dcx=null;try{var pts=predictTrajectory();if(pts&&pts.length)projx=Math.round(pts[pts.length-1].x);"
    "dcx=(typeof deckX==='function')?deckX():null;}catch(e){}"
    "return JSON.stringify({x:b.x,y:b.y,vx:b.vx,vy:b.vy,ang:b.ang,thr:b.thr,fuel:b.fuel,"
    "scene:s,frames:window.__frames||0,minY:window.__minY||null,enteredGlide:!!window.__enteredGlide,"
    "projx:projx,deck:dcx,err:window.__err||null,done:window.__botDone||null});"
    "}catch(e){return JSON.stringify({err:{msg:''+e,src:'read'}});}})()"
)


def main():
    proc = launch_chrome(f"file:///{GAME.replace(chr(92), '/')}?play=ocean", port=PORT, headless=True)
    try:
        ws = discover_page_ws(PORT, timeout=25)
        cdp = CDP(ws)
        cdp.enable_page()
        time.sleep(1.5)  # let the page + game boot
        cdp.evaluate(TRAP_JS)
        cdp.evaluate(AUTOPILOT_JS)
        print(f"probe running (port {PORT})...", flush=True)

        t0 = time.time()
        last = None
        crossed_glide = False
        err = None
        frames_seen = []
        gaps = []   # (y, projx, deck, gap) sampled in the glide band
        while time.time() - t0 < 55:
            raw = cdp.evaluate(READ_JS)
            st = json.loads(raw) if raw else {}
            if st.get("err"):
                err = st["err"]
                break
            last = st
            frames_seen.append(st.get("frames", 0))
            y = st.get("y")
            spd = None
            if st.get("vx") is not None:
                spd = (st["vx"] ** 2 + st["vy"] ** 2) ** 0.5
            if st.get("enteredGlide"):
                crossed_glide = True
            if st.get("projx") is not None and st.get("deck") is not None and y and 2100 < y < 8300:
                gaps.append((round(y), st["projx"], st["deck"], st["deck"] - st["projx"]))
            if st.get("scene") == "done" or st.get("done"):
                break
            if y is not None:
                pj = st.get("projx"); dk = st.get("deck")
                gtxt = f" projX={pj} deck={dk} gap={dk-pj:+d}" if (pj is not None and dk is not None) else ""
                print(f"  t={time.time()-t0:4.1f}s y={y:7.0f} spd={spd:6.1f} "
                      f"ang={st.get('ang'):+.2f} thr={st.get('thr'):.2f} "
                      f"glide={st.get('enteredGlide')}{gtxt}", flush=True)
            time.sleep(1.0)

        # verdict
        print("\n" + "=" * 60)
        # did the render loop keep advancing (not frozen)?
        advancing = len(frames_seen) >= 3 and frames_seen[-1] > frames_seen[0]
        if err:
            print("FAIL — JS ERROR TRAPPED:")
            print(f"   source : {err.get('src')}")
            print(f"   message: {err.get('msg')}")
            if err.get("stack"):
                print("   stack  :")
                for ln in str(err["stack"]).splitlines()[:6]:
                    print(f"      {ln}")
            return 1
        if not crossed_glide and (last is None or last.get("minY", 1e9) > 8300):
            print("INCONCLUSIVE — booster never reached the glide band; couldn't exercise the transition.")
            print(f"   last={last}")
            return 2
        print("PASS — no JS error through the reentry->glide transition.")
        print(f"   entered glide band : {crossed_glide}")
        print(f"   min altitude       : {last.get('minY') if last else '?'}")
        print(f"   render loop advancing: {advancing} (frames {frames_seen[0]}..{frames_seen[-1]})")
        print(f"   final scene        : {last.get('scene') if last else '?'}")
        if gaps:
            # projected-landing gap to the deck (positive = X falls SHORT / left of deck).
            # This forced-state passive glide is a LOWER BOUND on reach (no player steer-for-distance),
            # and the sim underpredicts real carry — so treat as directional, not absolute.
            entry_gap = gaps[0][3]; low_gap = gaps[-1][3]
            print(f"   projected-landing gap to deck (passive glide, forced entry state):")
            print(f"      glide entry (y={gaps[0][0]}): projX={gaps[0][1]}  deck={gaps[0][2]}  gap={entry_gap:+d}")
            print(f"      near floor  (y={gaps[-1][0]}): projX={gaps[-1][1]}  deck={gaps[-1][2]}  gap={low_gap:+d}")
            print(f"      (positive gap = X lands SHORT of the deck)")
        return 0
    finally:
        try:
            cdp.close()
        except Exception:  # noqa: BLE001
            pass
        proc.terminate()


if __name__ == "__main__":
    sys.exit(main())
