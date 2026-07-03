"""Probe a candidate control law end-to-end and report the landing.
Law (args: SPD_KEEP  BURN_ALT_MARGIN):
  - COAST while ascending (vy>=0): no burn, hold near-upright.
  - RETRO decel burn while descending AND spd>SPD_KEEP AND y>burnAlt: point
    retrograde atan2(-vx,-vy), full burn. Bleeds entry speed + horizontal drift.
  - GLIDE otherwise while high: coast, hold near-upright.
  - TERMINAL suicide burn when y<=burnAlt (stopDist*1.2+MARGIN): full burn,
    null drift, upright below 300m.
Reports final x vs deckX=7050, touchdown vy/vx, ok.
"""
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot_cdp import launch_chrome, discover_page_ws, CDP  # noqa: E402

GAME = r"C:\Users\nmurcin\Lumen\local\blue-origin-landings\index.html"
mode = "ocean"
SPD_KEEP = sys.argv[1] if len(sys.argv) > 1 else "70"
MARGIN = sys.argv[2] if len(sys.argv) > 2 else "150"
for a in sys.argv[1:]:
    if a in ("ocean", "tower", "mars"):
        mode = a
port = random.randint(9300, 9899)
url = "file:///" + GAME.replace("\\", "/") + f"?play={mode}"
proc = launch_chrome(url, port=port, headless=True)
CTRL = r"""
(function(){
  if(window.__p)return 'a'; window.__p=1; window.__ph='INIT';
  // args: VX_KEEP (stop bleeding horizontal below this) , MARGIN (terminal burn pad m)
  var A=10.5, VX_KEEP=%s, MARGIN=%s;
  function steer(t){var e=t-b.ang;keys['ArrowLeft']=false;keys['ArrowRight']=false;
    if(e>0.015)keys['ArrowRight']=true; else if(e<-0.015)keys['ArrowLeft']=true;}
  function loop(){
    try{
      if(scene==='done'){window.__d={x:Math.round(b.x),y:Math.round(b.y),
        vx:+b.vx.toFixed(1),vy:+b.vy.toFixed(1),ang:+(b.ang*180/Math.PI).toFixed(1),
        dmg:Math.round(b.damage||0),fuel:Math.round(b.fuel),ok:(result?result.ok:null),
        reason:(result&&result.lines?result.lines[0]:null)};return;}
      if(b.opening){requestAnimationFrame(loop);return;}
      var desc=b.vy<0, sd=desc?-b.vy:0;
      var dx=(typeof deckX==='function')?deckX():0, gap=dx-b.x;
      var stop=(b.vy*b.vy)/(2*A), burnAlt=stop*1.20+MARGIN, ph,tgt,burn;
      if(!desc){
        // coast up to apogee: hold retrograde-ish (belly to wind, no burnup), no burn
        tgt=0; burn=false; ph='COAST_UP';
      } else if(b.y<=burnAlt && sd>1){
        // TERMINAL: proportional descent-rate control. Command a target sink rate
        // that shrinks with altitude so we keep DESCENDING and arrive at y=0 slow,
        // instead of nulling vy at altitude and hovering. Burn only if sinking
        // faster than the target -> naturally feathers to a soft touchdown.
        var vtgt = Math.max(3.0, 0.055*b.y + 3.0);   // e.g. 300m->19.5, 60m->6.3, 10m->3.5
        var aim=(Math.abs(gap)<250)?(-b.vx*0.012):((dx-b.x)*0.00035-b.vx*0.010);
        tgt=Math.max(-0.20,Math.min(0.20,aim));
        if(b.y<250)tgt=Math.max(-0.09,Math.min(0.09,-b.vx*0.02));
        burn = (sd > vtgt); ph='TERMINAL';
      } else if(b.vx>VX_KEEP && gap>800 && b.y>burnAlt && b.y<9500){
        // BLEED horizontal in the LOWER band (y<9500) where drag has capped speed and
        // heat is safe -> avoids the burnup that high-altitude bleeds cause. Point
        // retrograde, full burn; stops once vx<=VX_KEEP (leaves downrange momentum).
        tgt=Math.atan2(-b.vx,-b.vy); burn=true; ph='BLEED';
      } else {
        // GLIDE: coast, hold retrograde attitude (belly to wind) so we don't burn up
        // and don't add downrange lift; momentum carries us toward the deck.
        tgt = Math.atan2(-b.vx,-b.vy); burn=false; ph='GLIDE';
      }
      keys[' ']=burn; steer(tgt); window.__ph=ph;
      requestAnimationFrame(loop);
    }catch(e){window.__d={err:''+e};}
  }
  requestAnimationFrame(loop);return 'ok';
})()
""" % (SPD_KEEP, MARGIN)
try:
    ws = discover_page_ws(port)
    cdp = CDP(ws)
    cdp.enable_page()
    time.sleep(1.2)
    print(f"mode={mode} SPD_KEEP={SPD_KEEP} MARGIN={MARGIN}  ctrl:", cdp.evaluate(CTRL))
    read = ("(function(){try{return JSON.stringify({t:+b.t.toFixed(1),x:Math.round(b.x),"
            "y:Math.round(b.y),vx:Math.round(b.vx),vy:Math.round(b.vy),"
            "ph:window.__ph,fuel:Math.round(b.fuel),sc:scene,d:window.__d||null});}"
            "catch(e){return JSON.stringify({err:''+e});}})()")
    t0 = time.time(); lastph = None
    while time.time() - t0 < 190:
        st = json.loads(cdp.evaluate(read))
        if st.get("d"):
            print("=== DONE ===", st["d"])
            dx = 7050 if mode == "ocean" else 8350 if mode == "tower" else 0
            d = st["d"]
            print(f"    land_x={d.get('x')} deckX={dx} offset={abs(d.get('x',0)-dx)} "
                  f"vy={d.get('vy')} vx={d.get('vx')} ang={d.get('ang')} ok={d.get('ok')}")
            break
        if st.get("ph") != lastph:
            print(f"t={st['t']:5.1f} x={st['x']:7d} y={st['y']:6d} vx={st['vx']:5d} "
                  f"vy={st['vy']:5d} fuel={st['fuel']:6d} -> {st['ph']}")
            lastph = st["ph"]
        time.sleep(0.15)
    cdp.close()
finally:
    proc.terminate(); time.sleep(0.3)
    try: proc.kill()
    except Exception: pass
