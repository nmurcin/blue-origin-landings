"""
Fuel-vs-descent-height sweep for the MK1 75%% fuel cut (FUEL0=600).

Uses the PROVEN clean-descent controller from mars_land_probe (the one that lands all 4 pads in the
gate) but seeds it from progressively HIGHER clearances over the x8 pad — a pure vertical drop, zero
drift. This isolates the question the gate can't answer: from how high can a CLEAN pilot still land on
600 kg? If it lands from ~1350 m (the real hover-spawn height) with fuel to spare, the level is hard
but fair. If it runs dry well below 1350 m, 600 kg is too tight and we should bump it up.

  py testing/_mars_fuel_sweep.py [port]
"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from cdp import Chrome
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
GAME = "file:///" + os.path.join(os.path.dirname(HERE), "index.html").replace("\\", "/")
port = int(sys.argv[1]) if len(sys.argv) > 1 else 9346

HOOK = r"""(function(){window.__ERR='';window.__RAFQ=[];window.requestAnimationFrame=function(cb){window.__RAFQ.push(cb);return window.__RAFQ.length;};window.__PUMP=function(n){var q=window.__RAFQ;window.__RAFQ=[];for(var i=0;i<q.length;i++){try{q[i](n);}catch(e){window.__ERR=String(e);}}return window.__RAFQ.length;};return true;})();"""

# Seed a pure vertical drop over the x8 pad at a chosen clearance (no drift, upright) — the cheapest
# possible descent (no cross-range), so it's the most GENEROUS test of the fuel budget.
SEED = r"""(function(clr){
  var pad=null; for(var i=0;i<marsPads.length;i++){ if(marsPads[i].mult===8) pad=marsPads[i]; }
  if(!pad) pad=marsPads[marsPads.length-1];
  b.x=pad.x; b.y=marsGroundY(pad.x)+clr; b.vx=0; b.vy=-3.0; b.ang=0; b.angv=0;
  scene='flying'; result=null;
  return {padx:pad.x, half:pad.half, fuel:Math.round(b.fuel), fuel0:Math.round(FUEL0)};
})(%d)"""

# The PROVEN mars_land_probe descent law: hold upright, brisk sink up high, soft flare in the last 12 m.
DESCEND = r"""(function(){
  if(typeof b==='undefined'||!b) return {phase:'noB'};
  if(scene==='done'){ keys[' ']=false;keys['ArrowLeft']=false;keys['ArrowRight']=false;
    var td=window.__lastTD||{};
    return {phase:'done', won:!!(result&&result.ok), title:result?result.title:'', mult:(result&&result.mk1)?result.mk1.mult:0, fuel:Math.round(b.fuel), tdVy:td.vDesc, tdClr:td.clr}; }
  var clr=b.y-marsGroundY(b.x), vDesc=-b.vy, effAng=b.ang+b.angv*0.45;
  keys['ArrowLeft']=false; keys['ArrowRight']=false;
  if(effAng>0.03) keys['ArrowLeft']=true; else if(effAng<-0.03) keys['ArrowRight']=true;
  // clearance-SCALED descent corridor: the higher you are the faster you may sink, easing to a soft
  // kiss near the deck. (The old fixed 3.2 m/s until 12 m arrived too hot from >500 m with the lighter
  // reduced-fuel vehicle.) v_allow ~ sqrt(2 * a_margin * clr) capped, then a gentle terminal flare.
  var aMargin = 1.4;                                   // conservative net decel to plan the sink on
  var vAllow = Math.min(30, Math.sqrt(2*aMargin*Math.max(0,clr-6)) + 1.2);
  if (clr < 12) vAllow = 1.3;                          // soft flare
  keys[' '] = vDesc > vAllow;
  window.__lastTD = {clr:Math.round(clr), vDesc:Math.round(vDesc*10)/10, fuel:Math.round(b.fuel)};
  return {phase:'fly', clr:Math.round(clr), fuel:Math.round(b.fuel)};
})()"""

def fly_from(ch, clr, max_steps=8000):
    ch.eval("(function(){try{newRun('mars');scene='flying';}catch(e){window.__ERR=String(e);}})()")
    ch.eval("if(window.__RAFQ.length===0&&typeof frame==='function'){try{frame(0);}catch(e){window.__ERR=String(e);}}")
    seed = ch.eval(SEED % clr)
    now=0.0; last=None
    for _ in range(max_steps):
        st = ch.eval(DESCEND); last=st
        if isinstance(st,dict) and st.get('phase')=='done':
            return st, seed
        now+=16.7; ch.eval("window.__PUMP(%f)"%now)
    return last, seed

def main():
    ch = Chrome(CHROME, os.path.join(os.environ.get("TEMP","/tmp"),"bo_sweep_%d"%os.getpid()), port=port, window=(900,700)); ch.launch()
    ch.send("Page.enable"); ch.send("Runtime.enable")
    ch.send("Page.navigate", {"url": GAME + "?play=mars"}); time.sleep(1.3); ch.eval(HOOK)
    heights = [200, 500, 900, 1350, 1500]   # 1350 = real hover-spawn height
    rows=[]
    for h in heights:
        st, seed = fly_from(ch, h)
        won = bool(st.get('won')); fuel_left = st.get('fuel', 0); title = st.get('title')
        rows.append((h, won, fuel_left, title, seed.get('fuel0')))
        print("from %4d m: %-4s fuel_left=%-4s tdVy=%s title=%r (tank=%s)" % (h, "WIN" if won else "LOSS", fuel_left, st.get('tdVy'), title, seed.get('fuel0')), flush=True)
    ch.close()
    # The real spawn is ~1350 m. Require a clean vertical descent from >=1350 m to WIN with fuel left.
    spawn_row = [r for r in rows if r[0]==1350][0]
    ok = spawn_row[1] and spawn_row[2] > 0
    print("\nspawn-height(1350 m) clean descent:", "WIN fuel_left=%s" % spawn_row[2] if spawn_row[1] else "LOSS", flush=True)
    print("RESULT", "PASS" if ok else "FAIL (clean descent from spawn height can't land on 600 kg)")
    sys.exit(0 if ok else 1)

main()
