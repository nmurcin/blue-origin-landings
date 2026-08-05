import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from cdp import Chrome
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
GAME = "file:///" + os.path.join(os.path.dirname(HERE), "index.html").replace("\\", "/")
ch = Chrome(CHROME, os.path.join(os.environ.get("TEMP","/tmp"),"bo_latch_%d"%os.getpid()), port=9418, window=(1280,900)); ch.launch()
ch.send("Page.enable"); ch.send("Runtime.enable")
ch.send("Page.navigate", {"url": GAME + "?play=mars"}); time.sleep(1.2)
ch.eval("(function(){window.__RAFQ=[];window.requestAnimationFrame=function(cb){window.__RAFQ.push(cb);return 1;};window.__PUMP=function(n){var q=window.__RAFQ;window.__RAFQ=[];for(var i=0;i<q.length;i++){try{q[i](n)}catch(e){window.__ERR=String(e)}}return window.__RAFQ.length;};return 1;})()")
ch.eval("(function(){try{newRun('mars');scene='flying';}catch(e){window.__ERR=String(e)}})()")

now=[0.0]
def pump(frames=2):
    for _ in range(frames): now[0]+=16.7; ch.eval("window.__PUMP(%f)"%now[0])

def probe(name, setup_js):
    ch.eval("(function(){var p=marsPads.find(function(q){return q.mult===2});%s;scene='flying';})()" % setup_js)
    pump(2)
    # run the actual draw path (drawBurnStop sets burnStopInfo) then read the latch + marker
    r = ch.eval("""(function(){
      try{ if(typeof drawBurnStop==='function') drawBurnStop(); }catch(e){ return {err:String(e)} }
      return {armed: !!b.stopArmed, hasMarker: (burnStopInfo!==null),
              info: burnStopInfo?burnStopInfo.text:null,
              vy: Math.round(b.vy*10)/10, angDeg: Math.round(b.ang*57.3), thr: Math.round(b.thr*100)/100};
    })()""")
    print("%-26s %s" % (name, r))
    return r

print("--- STOP-marker LATCH probe (all mars) ---")
# 1) ARM: descending, upright, low -> marker should turn on and stay on
r1 = probe("1 arm (desc/upright/low)", "b.x=p.x;b.y=marsGroundY(p.x)+1200;b.vx=0;b.vy=-30;b.ang=0;b.angv=0;b.thr=0")
# 2) HARD TILT >34deg (0.7 rad): OLD code hid the marker here. Latched -> must stay on.
r2 = probe("2 hard tilt 45deg",       "b.ang=0.785;b.angv=0;b.vy=-25")
# 3) vy OVERSHOOT above -5 (mid-burn arrest / brief climb): OLD code hid it. Latched -> stay on.
r3 = probe("3 vy overshoot +3",       "b.ang=0.1;b.vy=3;b.thr=1")
# 4) back to a normal descending state -> still on
r4 = probe("4 back to descending",    "b.ang=0.0;b.vy=-18;b.thr=0")
# 5) FRESH RUN must RESET the latch (stopArmed cleared on newRun's new b)
rreset = ch.eval("(function(){newRun('mars');scene='flying';return {armedAfterNewRun: !!b.stopArmed};})()")
print("%-26s %s" % ("5 newRun resets latch", rreset))

ok = (r1.get('armed') and r1.get('hasMarker')
      and r2.get('armed') and r2.get('hasMarker')
      and r3.get('armed') and r3.get('hasMarker')
      and r4.get('armed') and r4.get('hasMarker')
      and rreset.get('armedAfterNewRun') == False)
print("RESULT", "PASS" if ok else "FAIL")
ch.close()
sys.exit(0 if ok else 1)
