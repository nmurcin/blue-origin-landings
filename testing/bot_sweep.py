"""
bot_sweep.py — Active-steering strategy SWEEP against the REAL game (headless
Chrome via the bot_cdp DevTools harness). Maps the reachable landing-x envelope
for ocean (7x2) and tower (9x4) by varying the two levers that move the landing
point, then logs a per-strategy results table.

LEVERS (passed as a strategy dict, injected into an in-page controller):
  burnStartAlt : altitude (m) below which the DECEL/BLEED burn may start while
                 descending. HIGHER = start braking sooner = bleed more downrange
                 velocity = land SHORTER. (Capped to a heat-safe band per vehicle.)
  bleedVx      : bleed (retrograde burn) until horizontal vx <= this, then stop.
                 LOWER bleedVx = kill more horizontal = land SHORTER.
  glideLean    : body tilt (deg, + = downrange/+x) held during the GLIDE coast.
                 Strake lift is perpendicular to velocity ("bank to turn"): a
                 downrange lean adds cross-range that carries FARTHER; standing
                 upright / retrograde carries less. (Clamped by aero.)
  aNet         : assumed net full-burn decel (m/s^2) for the terminal suicide-burn
                 stop-distance. Tower is heavier -> different value.
  termVyK, termVy0 : terminal descent-rate target vtgt = termVyK*y + termVy0.

The terminal phase uses the proven proportional descent-rate suicide burn that
feathers to a soft, upright touchdown.

deckX for the run is passed in (so we can measure landing-x against a hypothetical
deck and compute the gap-over-time). The controller NEVER trusts an offline sim.

Usage:
    py bot_sweep.py <mode> <label> burnStartAlt bleedVx glideLean aNet [termVyK termVy0]
e.g.
    py bot_sweep.py ocean AGGR 9000 40 -3 10.5
    py bot_sweep.py ocean CARRY 3000 200 14 10.5

Writes: testing/bot_sweep_<mode>.csv (appended: one row per run) and a per-run
trajectory JSON testing/bot_run_<mode>_<label>.json for gap-over-time analysis.
"""
import csv
import json
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot_cdp import launch_chrome, discover_page_ws, CDP  # noqa: E402

GAME = r"C:\Users\nmurcin\Lumen\local\blue-origin-landings\index.html"
HERE = os.path.dirname(os.path.abspath(__file__))
DECKX = {"ocean": 14000, "tower": 17000}  # game index.html now returns these
PADHALF = {"ocean": 44, "tower": 34}
OKV = {"ocean": (8.5, 7.0), "tower": (6.0, 4.0)}


def controller_js(strat, deckx):
    """Return the in-page controller JS for a given strategy dict + hypothetical deckX."""
    return r"""
(function(){
  if(window.__p)return 'already'; window.__p=1; window.__ph='INIT'; window.__tr=[]; window.__n=0;
  var DECKX=%(deckx)s;
  var BURN_START_ALT=%(burnStartAlt)s, BLEED_VX=%(bleedVx)s, GLIDE_LEAN=%(glideLean)s*Math.PI/180;
  var A_NET=%(aNet)s, TVK=%(termVyK)s, TV0=%(termVy0)s;
  // Steer toward target angle with RATE DAMPING so we don't tumble in thin air
  // (up high there's no aero damping; pure bang-bang toward a target spins the
  // vehicle). Command = kp*angleErr - kd*angv, wrapped to [-pi,pi]; bang-bang the
  // arrow matching the command sign, with a deadband that also stops when nearly
  // aligned AND not rotating. angv is the body angular rate (rad/s).
  function angWrap(a){while(a>Math.PI)a-=2*Math.PI; while(a<-Math.PI)a+=2*Math.PI; return a;}
  function steer(t){
    var e=angWrap(t-b.ang);
    var av=(b.angv||0);
    var cmd = e*1.0 - av*0.55;              // PD: rate damping kills the tumble
    keys['ArrowLeft']=false; keys['ArrowRight']=false;
    if(cmd>0.03) keys['ArrowRight']=true; else if(cmd<-0.03) keys['ArrowLeft']=true;
  }
  // Up high (vacuum, no heat): don't chase a precise attitude — just KILL spin so
  // we arrive at the air stable, then hold true retrograde once aero bites.
  function killSpin(){
    var av=(b.angv||0);
    keys['ArrowLeft']=false; keys['ArrowRight']=false;
    if(av>0.02) keys['ArrowLeft']=true; else if(av<-0.02) keys['ArrowRight']=true;
  }
  function samp(ph){window.__n++;
    if(window.__n%%4===0 && window.__tr.length<9000){
      window.__tr.push([+(b.t||0).toFixed(2),Math.round(b.x),Math.round(b.y),
        +b.vx.toFixed(1),+b.vy.toFixed(1),+(b.ang*180/Math.PI).toFixed(1),
        +b.thr.toFixed(2),Math.round(b.fuel),+(b.damage||0).toFixed(1),
        +(b.heatFrac||0).toFixed(2),ph]);}}
  function loop(){
    try{
      if(scene==='done'){
        window.__d={result:(result?(result.ok?'WON':'LOST'):'?'),ok:(result?result.ok:null),
          x:Math.round(b.x),y:Math.round(b.y),vx:+b.vx.toFixed(2),vy:+b.vy.toFixed(2),
          ang:+(b.ang*180/Math.PI).toFixed(1),fuel:Math.round(b.fuel),
          dmg:Math.round(b.damage||0),reason:(result&&result.lines?result.lines[0]:null),
          deckX:(typeof deckX==='function'?deckX():null)};
        keys[' ']=false;keys['ArrowLeft']=false;keys['ArrowRight']=false;return;}
      if(b.opening){window.__ph='OPENING';requestAnimationFrame(loop);return;}
      var desc=b.vy<0, sd=desc?-b.vy:0, gap=DECKX-b.x, spd=Math.hypot(b.vx,b.vy);
      var stop=(b.vy*b.vy)/(2*A_NET), burnAlt=stop*1.20+150, ph,tgt,burn;
      var HEAT_TOP = (typeof ENTRY_Y!=='undefined'?ENTRY_Y:8500) + 2500;  // ~11000 m: air/heat onset
      // ENTRY_DECEL_SPD: the MANDATORY reentry decel-burn target. A hot entry (esp.
      // tower: vx~550 vy~-600) burns up in the dense air unless total speed is bled
      // BEFORE the heat ramps in. So once DESCENDING and nearing the heat band, point
      // retrograde (engines/belly to wind = protected side) and burn until total speed
      // <= ENTRY_DECEL_SPD. The retrograde attitude also gives the highest heat
      // tolerance, and the burn caps the peak q3 = rho*spd^3.
      var ENTRY_DECEL_SPD=%(entryDecelSpd)s;
      var nearBand = b.y < (HEAT_TOP + 4000);   // start braking a bit ABOVE the band
      if(desc && nearBand && spd>ENTRY_DECEL_SPD && ENTRY_DECEL_SPD>0){
        tgt=Math.atan2(-b.vx,-b.vy); steer(tgt); keys[' ']=true;
        window.__ph='ENTRY_DECEL'; samp('ENTRY_DECEL');
        requestAnimationFrame(loop); return;
      }
      // ABOVE the heat/air band with no decel needed (or ascending): if descending,
      // steer to retrograde so we present the protected side belly-first; if still
      // ascending in vacuum just kill spin.
      if(b.y > HEAT_TOP){
        if(desc){ steer(Math.atan2(-b.vx,-b.vy)); } else { killSpin(); }
        keys[' ']=false; window.__ph = desc?'COAST_HI':'ASCEND_HI'; samp(window.__ph);
        requestAnimationFrame(loop); return;
      }
      if(!desc){
        // (rare here) coasting up inside the air band: hold retrograde
        tgt=Math.atan2(-b.vx,-b.vy); burn=false; ph='COAST_UP';
      } else if(b.y<=burnAlt && sd>1){
        // TERMINAL proportional descent-rate suicide burn -> soft upright touchdown.
        // Steering: null residual drift but CLAMP so we never command an angle that
        // drives vx NEGATIVE (never reverse downrange). If vx already small +, hold
        // near-upright; if vx>0, allow a slight retrograde lean only down to vx~+2.
        var vtgt=Math.max(3.0, TVK*b.y + TV0);
        var aim;
        // TERM_VX_KEEP: don't bleed horizontal below this in the terminal phase. Set
        // high (via strategy) to CARRY farther (terminal only arrests vertical); set
        // low (default) to null drift for an on-spot vertical touchdown. Never reverse.
        var TKEEP=%(termVxKeep)s;
        // Gentle deck-SEEK: if still SHORT of the deck (gap>0), allow a small forward
        // lean to stretch toward it (adds +x); if PAST (gap<0) or drifting, null vx.
        // Never command a retrograde lean strong enough to reverse vx.
        if(b.vx>Math.max(6,TKEEP)) aim=-b.vx*0.010;    // shed excess downrange drift
        else if(b.vx<0) aim=(-b.vx)*0.03;              // recover if it went negative
        else {
          // small +vx regime: bias toward the deck if short, else hold upright
          var seek = (gap>150)? Math.min(0.06, gap*0.00004) : 0.0;
          aim = seek - b.vx*0.003;
        }
        tgt=Math.max(-0.16,Math.min(0.16,aim));
        if(b.y<250)tgt=Math.max(-0.07,Math.min(0.07,(b.vx<0?(-b.vx)*0.03:-b.vx*0.003)));
        burn=(sd>vtgt); ph='TERMINAL';
      } else if(desc && b.vx>BLEED_VX && b.y<=BURN_START_ALT && b.y>burnAlt){
        // BLEED: brake retrograde to shed downrange velocity. Gated below burnStartAlt
        // (heat-safe band) and above the terminal burn altitude. Stops at BLEED_VX so
        // vx stays positive (never reverses).
        tgt=Math.atan2(-b.vx,-b.vy); burn=true; ph='BLEED';
      } else {
        // GLIDE: coast holding retrograde (belly to wind) -> heat-safe carry. A downrange
        // GLIDE_LEAN can extend range via strake lift but exposes the bare side to the
        // hypersonic flow (burns up up high), so only lean LOW where heat is safe.
        if(GLIDE_LEAN>0.01 && b.y<ENTRY_Y) tgt=GLIDE_LEAN; else tgt=Math.atan2(-b.vx,-b.vy);
        burn=false; ph='GLIDE';
      }
      keys[' ']=burn; steer(tgt); window.__ph=ph; samp(ph);
      requestAnimationFrame(loop);
    }catch(e){window.__d={result:'ERR',err:''+e};}
  }
  requestAnimationFrame(loop); return 'ok';
})()
""" % {
        "deckx": deckx,
        "burnStartAlt": strat["burnStartAlt"],
        "bleedVx": strat["bleedVx"],
        "glideLean": strat["glideLean"],
        "aNet": strat["aNet"],
        "termVyK": strat.get("termVyK", 0.055),
        "termVy0": strat.get("termVy0", 3.0),
        "termVxKeep": strat.get("termVxKeep", 0.0),
        "entryDecelSpd": strat.get("entryDecelSpd", 0.0),
    }


READ_JS = ("(function(){try{return JSON.stringify({ph:window.__ph,d:window.__d||null,"
           "y:(b?Math.round(b.y):null),x:(b?Math.round(b.x):null),"
           "vx:(b?+b.vx.toFixed(1):null),vy:(b?+b.vy.toFixed(1):null),"
           "dmg:(b?Math.round(b.damage||0):null),sc:scene});}"
           "catch(e){return JSON.stringify({err:''+e});}})()")


def run_strategy(mode, label, strat, max_seconds=230.0, verbose=False, deckx=None):
    if deckx is None:
        deckx = DECKX[mode]
    url = "file:///" + GAME.replace("\\", "/") + f"?play={mode}"
    port = random.randint(9300, 9899)
    proc = launch_chrome(url, port=port, headless=True)
    out = {"result": "TIMEOUT"}
    try:
        ws = discover_page_ws(port)
        cdp = CDP(ws)
        cdp.enable_page()
        time.sleep(1.2)
        chk = json.loads(cdp.evaluate(
            "(function(){try{return JSON.stringify({mode:(typeof mode!=='undefined'?mode:null),"
            "sc:scene});}catch(e){return JSON.stringify({err:''+e});}})()"))
        if chk.get("mode") != mode:
            raise RuntimeError(f"wrong page: {chk}")
        cdp.evaluate(controller_js(strat, deckx))

        t0 = time.time()
        errs = 0
        last_ph = None
        while True:
            if time.time() - t0 > max_seconds:
                out = {"result": "TIMEOUT", "t": round(time.time() - t0, 1)}
                break
            try:
                st = json.loads(cdp.evaluate(READ_JS))
                errs = 0
            except Exception as e:  # noqa: BLE001
                errs += 1
                if errs >= 8:
                    out = {"result": "CONN_LOST"}
                    break
                time.sleep(0.15)
                continue
            if st.get("err"):
                time.sleep(0.1); continue
            d = st.get("d")
            if d:
                out = d
                break
            if verbose and st.get("ph") != last_ph:
                print(f"    [{label}] t={time.time()-t0:5.1f} ph={st.get('ph'):9} "
                      f"y={st.get('y')} x={st.get('x')} vx={st.get('vx')} vy={st.get('vy')} dmg={st.get('dmg')}")
                last_ph = st.get("ph")
            time.sleep(0.08)
        # pull trajectory trace for gap analysis + vx-reversal / min-gap checks
        traj = []
        try:
            tr = cdp.evaluate("JSON.stringify(window.__tr||[])")
            traj = json.loads(tr)
            with open(os.path.join(HERE, f"bot_run_{mode}_{label}.json"), "w", encoding="utf-8") as f:
                f.write(tr)
        except Exception:  # noqa: BLE001
            pass
        cdp.close()
    finally:
        proc.terminate(); time.sleep(0.3)
        try: proc.kill()
        except Exception: pass

    # score against a hypothetical deck AT the landing point's implied deck (deckx used)
    okvy, okvx = OKV[mode]
    landx = out.get("x")
    row = {
        "label": label, "mode": mode,
        "burnStartAlt": strat["burnStartAlt"], "bleedVx": strat["bleedVx"],
        "glideLean": strat["glideLean"], "aNet": strat["aNet"],
        "result": out.get("result"), "land_x": landx,
        "entryDecelSpd": strat.get("entryDecelSpd", 0),
        "deckX_used": deckx,
        "offset_from_deck": (abs(landx - deckx) if landx is not None else None),
        "on_deck": (landx is not None and abs(landx - deckx) <= PADHALF[mode]),
        "vx": out.get("vx"), "vy": out.get("vy"), "ang": out.get("ang"),
        "fuel": out.get("fuel"), "dmg": out.get("dmg"),
        "reason": out.get("reason"),
        "survived": (out.get("result") in ("WON", "LOST") and (out.get("dmg", 100) or 0) < 100
                     and out.get("y", 99) is not None and abs(out.get("y", 99)) < 5),
        "vy_ok": (out.get("vy") is not None and -out.get("vy", -99) <= okvy),
        "vx_ok": (out.get("vx") is not None and abs(out.get("vx", 99)) <= okvx),
        "vx_never_neg": None,  # filled from trace below
    }
    # vx-reversal check across the whole flying trajectory (trace col 3 = vx).
    # Only consider samples once descending under control (ignore tiny numerical
    # noise): flag if vx dips below a small negative threshold.
    min_vx = None
    if traj:
        vxs = [pt[3] for pt in traj if isinstance(pt, list) and len(pt) > 3]
        if vxs:
            min_vx = min(vxs)
    row["min_vx"] = min_vx
    row["vx_never_neg"] = (min_vx is not None and min_vx >= -2.0)
    # touchdown landability (soft + upright) regardless of deck offset
    row["soft_touchdown"] = bool(row["vy_ok"] and row["vx_ok"]
                                 and out.get("ang") is not None and abs(out.get("ang", 99)) <= (10 if mode == "ocean" else 6))
    return row, out


if __name__ == "__main__":
    mode = sys.argv[1]
    label = sys.argv[2]
    strat = {
        "burnStartAlt": float(sys.argv[3]),
        "bleedVx": float(sys.argv[4]),
        "glideLean": float(sys.argv[5]),
        "aNet": float(sys.argv[6]),
    }
    if len(sys.argv) > 8:
        strat["termVyK"] = float(sys.argv[7])
        strat["termVy0"] = float(sys.argv[8])
    row, out = run_strategy(mode, label, strat, verbose=True)
    print("RESULT:", json.dumps(row))
    print("RAW:", json.dumps(out))
