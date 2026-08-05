import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from cdp import Chrome
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
GAME = "file:///" + os.path.join(os.path.dirname(HERE), "index.html").replace("\\", "/")
FRAMES = os.path.join(HERE, "frames"); os.makedirs(FRAMES, exist_ok=True)
port = int(sys.argv[1]) if len(sys.argv) > 1 else 9338
ch = Chrome(CHROME, os.path.join(os.environ.get("TEMP","/tmp"),"bo_plume_%d"%os.getpid()), port=port, window=(1280,900)); ch.launch()
ch.send("Page.enable"); ch.send("Runtime.enable")
ch.send("Page.navigate", {"url": GAME + "?play=mars"}); time.sleep(1.4)

# Real rAF pump so the game renders on demand (same trick the other probes use).
ch.eval("(function(){window.__RAFQ=[];window.requestAnimationFrame=function(cb){window.__RAFQ.push(cb);return 1;};window.__PUMP=function(n){var q=window.__RAFQ;window.__RAFQ=[];for(var i=0;i<q.length;i++){try{q[i](n)}catch(e){window.__ERR=String(e)}}return window.__RAFQ.length;};return 1;})()")
ch.eval("(function(){try{newRun('mars');scene='flying';}catch(e){window.__ERR=String(e)}})()")

def shot(name, setup_js, frames=3):
    # seed the state, snap the camera onto the lander, then pump a couple frames so the plume renders
    ch.eval("(function(){var p=marsPads.find(function(q){return q.mult===8})||marsPads[marsPads.length-1];%s;scene='flying';if(typeof snapGroundCam==='function')snapGroundCam();})()" % setup_js)
    now = 0.0
    for _ in range(frames):
        now += 16.7; ch.eval("window.__PUMP(%f)"%now)
    # re-snap after the pumps so the ease-toward-field doesn't pull the lander off-frame for the shot
    ch.eval("(function(){if(typeof snapGroundCam==='function')snapGroundCam();})()")
    # Recompute the splash-reach predicate the code uses (axisToGnd <= plume) so we can assert on it,
    # plus confirm drawBooster (which now calls drawMK1PlumeSplash) ran WITHOUT a runtime error.
    st = ch.eval("""(function(){
      window.__ERR=null;
      try{ drawBooster(); }catch(e){ window.__ERR=String(e); }
      var clr=b.y-marsGroundY(b.x);
      var plume=b.thr*30*1.15;
      var axisToGnd=clr/Math.max(0.35,Math.cos(b.ang));
      var reaches=(axisToGnd<=plume && clr>=-3);
      return {clr:Math.round(clr), thr:Math.round(b.thr*100)/100, ang:Math.round(b.ang*57.3),
              reaches:reaches, err:window.__ERR||null};
    })()""")
    p = os.path.join(FRAMES, name + ".png")
    ch.screenshot_png(p)
    print("%-22s %s -> %s" % (name, st, os.path.basename(p)))
    return st

# Over the ×8 pad, ~18 m clearance, engine hard on, roughly upright: plume should hit the deck and fan out.
a = shot("plume_on_pad_18m", "b.x=p.x;b.y=marsGroundY(p.x)+18;b.vx=0;b.vy=-4;b.ang=0;b.angv=0;b.thr=1;b.fuel=FUEL0")
# Tilted 20 deg, low, engine on — impingement point should walk to the tilted-axis side and still hug ground.
c = shot("plume_tilt20_14m", "b.x=p.x;b.y=marsGroundY(p.x)+14;b.vx=6;b.vy=-3;b.ang=0.35;b.angv=0;b.thr=0.9;b.fuel=FUEL0")
# Higher up (120 m), engine on: plume should NOT reach ground -> no splash (control).
d = shot("plume_high_120m", "b.x=p.x;b.y=marsGroundY(p.x)+120;b.vx=0;b.vy=-8;b.ang=0;b.angv=0;b.thr=0.7;b.fuel=FUEL0")
ch.close()

errs = []
if a.get('err') or c.get('err') or d.get('err'): errs.append("runtime error in drawBooster/plume")
if not a.get('reaches'): errs.append("low upright plume should reach ground")
if not c.get('reaches'): errs.append("low tilted plume should reach ground")
if d.get('reaches'): errs.append("high plume should NOT reach ground (control)")
print("RESULT", "PASS" if not errs else "FAIL: " + "; ".join(errs))
sys.exit(0 if not errs else 1)
