"""
Angle-vs-path probe: at several points along a REAL ocean booster flight, report
whether the body angle (what the sprite draws via ctx.rotate(b.ang)) is CONSISTENT
with the velocity vector and the thrust/lift that actually bend the path.

The player looked at a screenshot (engine FIRING, high up, predicted path curving
down-LEFT to the deck) and asked: doesn't the rocket LOOK angled to fall down-RIGHT?
This isolates: (a) which phase that is (decel burn vs glide), (b) the body angle in
deg, (c) the velocity heading, (d) the thrust direction (nose) and lift direction,
(e) whether the sprite lean the player sees matches the physics that curves the path.

Runs the REAL game loop headless via the bot-style pump (reuses cdp.py through the
runtime scanner's approach) — but here we just drive newRun('ocean') + hold a decel
burn like a player would, sampling the state. No trusting comments.

Run: py testing/angle_vs_path_probe.py
"""
import os
import sys
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Chrome  # noqa: E402

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME_URL = "file:///" + os.path.join(REPO, "index.html").replace("\\", "/")


def main():
    prof = os.path.join(os.environ.get("TEMP", "/tmp"), "bo_angle_probe_%d" % os.getpid())
    ch = Chrome(CHROME, prof, port=9440, window=(1000, 800))
    ch.launch()
    ch.send("Page.enable")
    ch.send("Runtime.enable")
    try:
        ch.send("Page.navigate", {"url": GAME_URL + "?play=ocean"})
        ch.wait_event("Page.loadEventFired", timeout=25)
        # install a manual pump + a simple "point retrograde and burn when hot/fast" autopilot,
        # then sample the state each phase. Mirrors what a player does in the decel burn + glide.
        ch.eval(r"""
        (function(){
          window.__RAFQ=[]; window.requestAnimationFrame=function(cb){window.__RAFQ.push(cb);return 1;};
          window.__PUMP=function(now){ var q=window.__RAFQ; window.__RAFQ=[]; for(var i=0;i<q.length;i++){try{q[i](now);}catch(e){}} return window.__RAFQ.length; };
          window.__AP=function(){
            if(typeof b==='undefined'||!b) return;
            for(var k in keys) delete keys[k];
            if(b.opening) return;
            var spd=Math.hypot(b.vx,b.vy);
            // retrograde target: nose OPPOSITE velocity => point (-vx,-vy). body ang from +y axis: atan2(sin,cos)
            // nose dir=(sin,cos); we want nose ~ opposite velocity for a retro burn.
            var wantNoseX=-b.vx/ (spd||1), wantNoseY=-b.vy/(spd||1);
            var targetAng=Math.atan2(wantNoseX, wantNoseY);   // ang s.t. (sin,cos)=(wantNoseX,wantNoseY)
            var e=targetAng-b.ang; while(e>Math.PI)e-=2*Math.PI; while(e<-Math.PI)e+=2*Math.PI;
            if(e>0.02) keys['ArrowRight']=true; else if(e<-0.02) keys['ArrowLeft']=true;
            // burn while high+fast (decel) to bleed speed
            if(b.y>7000 && spd>250) keys[' ']=true;
          };
          window.__SNAP=function(){
            if(!b) return null;
            var spd=Math.hypot(b.vx,b.vy);
            var noseX=Math.sin(b.ang), noseY=Math.cos(b.ang);        // sprite/thrust axis
            var velHeadingDeg=Math.atan2(b.vy,b.vx)*180/Math.PI;      // 0=+x right, -90=straight down
            var bodyLeanDeg=b.ang*180/Math.PI;                       // 0=nose up; + = nose toward +x (right)
            // dot of nose with velocity: <0 means engine-first (retrograde), >0 nose-first
            var noseDotVelUnit=(noseX*b.vx+noseY*b.vy)/(spd||1);
            var inGlide = (typeof GLIDE_TOP_Y!=='undefined') && b.vy<0 && b.y<GLIDE_TOP_Y && b.y>GLIDE_FLOOR_Y && spd<GLIDE_ENTRY_SPD;
            return {t:+b.t.toFixed(1), x:Math.round(b.x), y:Math.round(b.y), vx:+b.vx.toFixed(1), vy:+b.vy.toFixed(1),
                    spd:+spd.toFixed(1), thr:+b.thr.toFixed(2), bodyLeanDeg:+bodyLeanDeg.toFixed(1),
                    velHeadingDeg:+velHeadingDeg.toFixed(1), noseDotVelUnit:+noseDotVelUnit.toFixed(2),
                    retro:(noseDotVelUnit<0), inGlide:inGlide, deckX:(typeof deckX==='function'?deckX():null)};
          };
          return 'ok';
        })()
        """)
        # let the initial rAF register under our pump
        import time
        for _ in range(60):
            if (ch.eval("window.__RAFQ.length") or 0) >= 1:
                break
            time.sleep(0.05)
        now = float(ch.eval("(typeof lastT==='number'?lastT:100000)") or 100000.0)
        phases = []
        seen = set()
        for i in range(4000):
            now += 50.0
            ch.eval("window.__AP()")
            ch.eval("window.__PUMP(%f)" % now)
            if i % 10 == 0:
                s = ch.eval("window.__SNAP()")
                if not s:
                    continue
                # tag phase
                if s["thr"] > 0.1 and s["retro"]:
                    ph = "DECEL-BURN (retro)"
                elif s["inGlide"]:
                    ph = "GLIDE"
                elif s.get("y", 0) < 3000:
                    ph = "TERMINAL"
                else:
                    ph = "COAST"
                if ph not in seen and s["y"] > 200:
                    seen.add(ph)
                    phases.append((ph, s))
                    print("[%s] t=%.1f y=%d x=%d spd=%.0f thr=%.2f  bodyLean=%+.1f deg  velHeading=%+.1f deg  noseDotVel=%+.2f (%s)"
                          % (ph, s["t"], s["y"], s["x"], s["spd"], s["thr"], s["bodyLeanDeg"], s["velHeadingDeg"],
                             s["noseDotVelUnit"], "ENGINE-FIRST" if s["retro"] else "NOSE-FIRST"))
                if (ch.eval("scene") in ("done", "menu")) or s["y"] <= 5:
                    break
        print("\nINTERPRETATION:")
        print(" bodyLean +deg = nose leaned toward +x (right).  velHeading -90 = straight down; -90..-180 = down-left; -90..0 = down-right.")
        print(" In a DECEL burn the body points ENGINE-FIRST (noseDotVel<0): the SPRITE leans one way but THRUST pushes the OPPOSITE way,")
        print(" so the path bends opposite to the visible nose lean — that is correct retro-burn physics, and is the usual source of the")
        print(" 'sprite looks angled the wrong way for the path' perception. In GLIDE (engine off) the wing bends the path toward the lean.")
    finally:
        ch.close()


if __name__ == "__main__":
    main()
