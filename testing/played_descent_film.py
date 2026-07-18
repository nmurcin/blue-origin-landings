"""
Played-descent FILMSTRIP: fly a real controlled ocean booster descent (retrograde
decel burn -> glide steering toward the deck -> terminal), capture a strip of frames
through the GLIDE so the pilot can watch how it flies and judge the glide steering
with their own eyes. Records with GLIDE_STEER_SIGN = +1 (lean into turn) AND -1
(lean away) so the two conventions can be compared side by side.

For each frame it also logs the exact state (body lean, velocity heading, whether
the wing lift is currently pushing toward or away from the deck) so the picture and
the physics correspond — no guessing from a fuzzy image.

Run: py testing/played_descent_film.py
Writes testing/frames/film_signP_*.png and film_signN_*.png + prints a telemetry table.
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

# A player-like controller: point retrograde and burn while high+fast (decel), then in
# the glide, steer the BODY toward a lean that walks the booster toward the deck, then
# stand up and (lightly) burn near the ground. Drives the real `keys`.
CTRL = r"""
window.__AP = function(){
  if(typeof b==='undefined'||!b) return;
  for(var k in keys) delete keys[k];
  if(b.opening) return;
  var spd=Math.hypot(b.vx,b.vy);
  var dx=(typeof deckX==='function'?deckX():0)-b.x;   // + => deck is to the RIGHT
  var inGlide=(typeof GLIDE_TOP_Y!=='undefined')&&b.vy<0&&b.y<GLIDE_TOP_Y&&b.y>GLIDE_FLOOR_Y&&spd<GLIDE_ENTRY_SPD;
  var hot=(b.y>ENTRY_Y-500 && spd>250);
  if(hot){
    // DECEL: point engine-first (nose opposite velocity) and burn
    var wantNoseX=-b.vx/(spd||1), wantNoseY=-b.vy/(spd||1);
    var tgt=Math.atan2(wantNoseX,wantNoseY);
    var e=tgt-b.ang; while(e>Math.PI)e-=2*Math.PI; while(e<-Math.PI)e+=2*Math.PI;
    if(e>0.02)keys['ArrowRight']=true; else if(e<-0.02)keys['ArrowLeft']=true;
    keys[' ']=true;
  } else if(inGlide){
    // GLIDE: hold a bank that (under the CURRENT sign) walks toward the deck. We just command a
    // fixed-magnitude lean in the direction dx indicates and let the pilot see which way the path goes.
    var wantBank=(dx>0? 0.5 : -0.5);   // lean ~30 deg toward the deck side
    var e=wantBank-b.ang; while(e>Math.PI)e-=2*Math.PI; while(e<-Math.PI)e+=2*Math.PI;
    if(e>0.03)keys['ArrowRight']=true; else if(e<-0.03)keys['ArrowLeft']=true;
  } else if(b.y<3000){
    // TERMINAL: stand upright, burn if sinking hard
    var e=0-b.ang; if(e>0.03)keys['ArrowRight']=true; else if(e<-0.03)keys['ArrowLeft']=true;
    if(b.vy<-40)keys[' ']=true;
  }
};
window.__PUMP=function(now){var q=window.__RAFQ;window.__RAFQ=[];for(var i=0;i<q.length;i++){try{q[i](now);}catch(e){}}return window.__RAFQ.length;};
window.__ST=function(){
  if(!b)return null; var spd=Math.hypot(b.vx,b.vy);
  var inGlide=(typeof GLIDE_TOP_Y!=='undefined')&&b.vy<0&&b.y<GLIDE_TOP_Y&&b.y>GLIDE_FLOOR_Y&&spd<GLIDE_ENTRY_SPD;
  var lvx=-b.vy/(spd||1); var bank=Math.max(-GLIDE_STALL_CAP,Math.min(GLIDE_STALL_CAP,b.ang));
  var CLg=GLIDE_STEER_SIGN*GLIDE_STEER_K*Math.sin(bank)*Math.cos(bank);
  var liftx=CLg*lvx;   // + => wing pushes +x (right)
  var dx=(typeof deckX==='function'?deckX():0)-b.x;
  var pushingTowardDeck = inGlide ? ((liftx>0)===(dx>0)) : null;
  return {t:+b.t.toFixed(1),y:Math.round(b.y),x:Math.round(b.x),spd:+spd.toFixed(0),thr:+b.thr.toFixed(2),
          lean:+(b.ang*180/Math.PI).toFixed(1),vhead:+(Math.atan2(b.vy,b.vx)*180/Math.PI).toFixed(0),
          inGlide:inGlide,liftPushX:(liftx>0?'RIGHT':'LEFT'),deckDir:(dx>0?'RIGHT':'LEFT'),
          towardDeck:pushingTowardDeck,sign:GLIDE_STEER_SIGN,scene:(typeof scene!=='undefined'?scene:'?')};
};
'ok';
"""


def run_sign(ch, sign, tag):
    ch.send("Page.navigate", {"url": GAME_URL + "?play=ocean"})
    ch.wait_event("Page.loadEventFired", timeout=25)
    ch.eval("window.__RAFQ=[]; window.requestAnimationFrame=function(cb){window.__RAFQ.push(cb);return 1;};")
    ch.eval(CTRL)
    ch.eval("GLIDE_STEER_SIGN = %d;" % sign)
    for _ in range(60):
        if (ch.eval("window.__RAFQ.length") or 0) >= 1:
            break
        time.sleep(0.05)
    now = float(ch.eval("(typeof lastT==='number'?lastT:100000)") or 100000.0)
    shots = 0
    rows = []
    last_shot_y = 1e9
    for i in range(8000):
        now += 40.0
        ch.eval("GLIDE_STEER_SIGN = %d;" % sign)   # keep it pinned per-run
        ch.eval("window.__AP()")
        ch.eval("window.__PUMP(%f)" % now)
        if i % 6 == 0:
            s = ch.eval("window.__ST()")
            if not s:
                continue
            # capture a strip through the glide: every ~700 m of descent while inGlide
            if s["inGlide"] and (last_shot_y - s["y"]) > 700 and shots < 6:
                time.sleep(0.12)
                p = os.path.join(REPO, "testing", "frames", "film_%s_%02d.png" % (tag, shots))
                ch.screenshot_png(p)
                rows.append(s)
                shots += 1
                last_shot_y = s["y"]
            if s["scene"] in ("done", "menu") or s["y"] <= 5:
                rows.append(s)
                break
    return rows


def main():
    prof = os.path.join(os.environ.get("TEMP", "/tmp"), "bo_film_%d" % os.getpid())
    ch = Chrome(CHROME, prof, port=9466, window=(1000, 1000))
    ch.launch()
    ch.send("Page.enable")
    ch.send("Runtime.enable")
    try:
        for sign, tag in ((1, "signP"), (-1, "signN")):
            print("\n=== GLIDE_STEER_SIGN = %+d (%s) ===" % (sign, "lean INTO turn" if sign > 0 else "lean AWAY"))
            rows = run_sign(ch, sign, tag)
            print("  frame  t     y     x     spd lean(deg) velHead inGlide  liftPush deckDir towardDeck")
            for s in rows:
                print("   %-6s %-5s %-5s %-6s %-3s %+7.1f  %+5s   %-6s   %-6s   %-6s  %s"
                      % (tag, s["t"], s["y"], s["x"], s["spd"], s["lean"], s["vhead"], s["inGlide"],
                         s["liftPushX"], s["deckDir"], s["towardDeck"]))
    finally:
        ch.close()
    print("\nframes: testing/frames/film_signP_*.png (lean-into) and film_signN_*.png (lean-away)")


if __name__ == "__main__":
    main()
