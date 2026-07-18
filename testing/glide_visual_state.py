"""
Capture a REAL glide-phase frame AND dump the exact physics state at that same
frame, so the screenshot and the numbers correspond. Answers definitively:
  - what body angle (b.ang) the sprite is drawn at during the glide
  - the velocity vector (which way it's actually moving)
  - the lift-force direction the wing is applying (which way the path bends)
  - whether the engine is on (plume) or off (glide/heating glow)

Flies HANDS-OFF (no steering, no burn) so the body settles to the game's own
glide trim — i.e. exactly what a player sees when they let go in the glide.

Run: py testing/glide_visual_state.py
Writes testing/frames/glide_state.png and prints the state block.
"""
import os
import sys
import time
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Chrome  # noqa: E402

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME_URL = "file:///" + os.path.join(REPO, "index.html").replace("\\", "/")


def main():
    prof = os.path.join(os.environ.get("TEMP", "/tmp"), "bo_glide_vis_%d" % os.getpid())
    ch = Chrome(CHROME, prof, port=9455, window=(1000, 1000))
    ch.launch()
    ch.send("Page.enable")
    ch.send("Runtime.enable")
    try:
        ch.send("Page.navigate", {"url": GAME_URL + "?play=ocean"})
        ch.wait_event("Page.loadEventFired", timeout=25)
        ch.eval(r"""
        (function(){
          window.__RAFQ=[]; window.requestAnimationFrame=function(cb){window.__RAFQ.push(cb);return 1;};
          window.__PUMP=function(now){var q=window.__RAFQ;window.__RAFQ=[];for(var i=0;i<q.length;i++){try{q[i](now);}catch(e){}}return window.__RAFQ.length;};
          // HANDS-OFF after opening: no keys at all -> body settles to the game's glide trim.
          window.__AP=function(){ if(typeof keys!=='undefined'){ for(var k in keys) delete keys[k]; } };
          window.__STATE=function(){
            if(typeof b==='undefined'||!b) return null;
            var spd=Math.hypot(b.vx,b.vy);
            var noseX=Math.sin(b.ang), noseY=Math.cos(b.ang);
            // lift dir the game applies: perpendicular to velocity, sign by CL(bank). Recompute like stepPhysics glide:
            var inGlide=(typeof GLIDE_TOP_Y!=='undefined')&&b.vy<0&&b.y<GLIDE_TOP_Y&&b.y>GLIDE_FLOOR_Y&&spd<GLIDE_ENTRY_SPD;
            var bank=b.ang; if(bank>GLIDE_STALL_CAP)bank=GLIDE_STALL_CAP; else if(bank<-GLIDE_STALL_CAP)bank=-GLIDE_STALL_CAP;
            var CLg=-GLIDE_STEER_K*Math.sin(bank)*Math.cos(bank);
            var lvx=-b.vy/(spd||1), lvy=b.vx/(spd||1);      // +90 CCW of velocity
            var liftx=CLg*lvx, lifty=CLg*lvy;               // direction (sign) of the applied lift
            var liftHeading=Math.atan2(lifty,liftx)*180/Math.PI;
            return {t:+b.t.toFixed(1), y:Math.round(b.y), x:Math.round(b.x), spd:+spd.toFixed(1),
                    thr:+b.thr.toFixed(2), engineOn:(b.thr>0.05),
                    bodyLeanDeg:+(b.ang*180/Math.PI).toFixed(1),
                    velHeadingDeg:+(Math.atan2(b.vy,b.vx)*180/Math.PI).toFixed(1),
                    inGlide:inGlide, CLglide:+CLg.toFixed(3), liftHeadingDeg:+liftHeading.toFixed(1),
                    deckX:(typeof deckX==='function'?deckX():null), heatFrac:+(b.heatFrac||0).toFixed(2)};
          };
          return 'ok';
        })()
        """)
        for _ in range(60):
            if (ch.eval("window.__RAFQ.length") or 0) >= 1:
                break
            time.sleep(0.05)
        now = float(ch.eval("(typeof lastT==='number'?lastT:100000)") or 100000.0)
        grabbed = False
        for i in range(6000):
            now += 50.0
            ch.eval("window.__AP()")
            ch.eval("window.__PUMP(%f)" % now)
            if i % 8 == 0:
                s = ch.eval("window.__STATE()")
                if s and s["inGlide"] and 4500 < s["y"] < 6500 and not grabbed:
                    time.sleep(0.15)
                    path = os.path.join(REPO, "testing", "frames", "glide_state.png")
                    n = ch.screenshot_png(path)
                    print("GLIDE FRAME captured (%d bytes) at:" % n)
                    print("  t=%.1f  y=%d m  x=%d  spd=%.1f m/s" % (s["t"], s["y"], s["x"], s["spd"]))
                    print("  engine: %s (thr=%.2f)   heatFrac=%.2f" % ("ON" if s["engineOn"] else "OFF (gliding)", s["thr"], s["heatFrac"]))
                    print("  BODY LEAN (sprite angle) = %+.1f deg  (0=upright; + = nose toward +x/RIGHT; - = nose LEFT)" % s["bodyLeanDeg"])
                    print("  VELOCITY heading         = %+.1f deg  (-90=straight down; -90..-180=down-LEFT; 0..-90=down-RIGHT)" % s["velHeadingDeg"])
                    print("  wing CL (glide)          = %+.3f" % s["CLglide"])
                    print("  LIFT force heading       = %+.1f deg  (which way the wing pushes the path)" % s["liftHeadingDeg"])
                    print("  deckX=%s (booster x=%d => deck is %s of booster)" % (s["deckX"], s["x"], "RIGHT" if s["deckX"] > s["x"] else "LEFT"))
                    grabbed = True
                    break
                if s and (ch.eval("scene") in ("done", "menu")):
                    break
        if not grabbed:
            print("did not reach a clean hands-off glide window; last state:", ch.eval("window.__STATE()"))
    finally:
        ch.close()


if __name__ == "__main__":
    main()
