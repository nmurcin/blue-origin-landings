import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from cdp import Chrome
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
GAME = "file:///" + os.path.join(os.path.dirname(HERE), "index.html").replace("\\", "/")
ch = Chrome(CHROME, os.path.join(os.environ.get("TEMP","/tmp"),"bo_bsc_%d"%os.getpid()), port=9416, window=(1280,900)); ch.launch()
ch.send("Page.enable"); ch.send("Runtime.enable")
ch.send("Page.navigate", {"url": GAME + "?play=mars"}); time.sleep(1.2)
ch.eval("(function(){window.__RAFQ=[];window.requestAnimationFrame=function(cb){window.__RAFQ.push(cb);return 1;};window.__PUMP=function(n){var q=window.__RAFQ;window.__RAFQ=[];for(var i=0;i<q.length;i++){try{q[i](n)}catch(e){window.__ERR=String(e)}}return window.__RAFQ.length;};return 1;})()")
ch.eval("(function(){try{newRun('mars');scene='flying';}catch(e){window.__ERR=String(e)}})()")
ch.eval("if(window.__RAFQ.length===0&&typeof frame==='function'){try{frame(0)}catch(e){window.__ERR=String(e)}}")

def case(name, setup_js):
    ch.eval("(function(){var p=marsPads.find(function(q){return q.mult===2});%s;scene='flying';result=null;})()" % setup_js)
    now=0.0
    for i in range(2): now+=16.7; ch.eval("window.__PUMP(%f)"%now)
    r = ch.eval("""(function(){
      var s=predictBurnStop();
      if(!s) return {stop:null};
      // is the stop marker's WORLD y sensible? report clr (clearance above surface) + world y + arrested
      // also: analytic full-burn arrest distance for cross-check
      var m=DRY_MASS+b.fuel, aNet=THRUST/m - G, analytic=aNet>0?(b.vy*b.vy)/(2*aNet):-1;
      // and where the dashed line ENDS (to confirm decoupling)
      var pts=predictTrajectory(); var last=pts[pts.length-1];
      return {clr:Math.round(s.clr), worldY:Math.round(s.y), arrested:s.arrested,
              analyticDist:Math.round(analytic), bClr:Math.round(b.y-marsGroundY(b.x)), bVy:Math.round(b.vy*10)/10, bThr:Math.round(b.thr*100)/100,
              lineEndClr:Math.round(last.y-marsGroundY(last.x))};
    })()""")
    print("%-22s %s" % (name, r))

# 1) ENGINE OFF, free-fall from 900m at -30 m/s: STOP should show a full-burn arrest ABOVE ground (clr>0),
#    NOT stuck at ground; the dashed line (ballistic) ends AT the ground (lineEndClr~0) -> decoupled.
case("off/free-fall",  "b.x=p.x;b.y=marsGroundY(p.x)+900;b.vx=0;b.vy=-30;b.ang=0;b.angv=0;b.thr=0")
# 2) ENGINE ON full, gentle -14 from 900m: arrests in air, clr>0, arrested=true (matches analytic-ish)
case("on/arresting",   "b.x=p.x;b.y=marsGroundY(p.x)+900;b.vx=0;b.vy=-14;b.ang=0;b.angv=0;b.thr=1")
# 3) TOO HOT: -80 m/s at only 150m up, full throttle -> can't stop before surface -> clr<=~0 (arrested may
#    still be true but at/below surface) -> should read at/below the surface, not pinned to a false +height.
case("too-hot",        "b.x=p.x;b.y=marsGroundY(p.x)+150;b.vx=0;b.vy=-80;b.ang=0;b.angv=0;b.thr=1")
ch.close()
