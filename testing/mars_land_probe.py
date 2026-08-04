"""
mars_land_probe.py — prove the MK1 moonlander touchdown + pad scoring is CORRECT
and every pad is landable, on the REAL headless game.

The green gate only proves mars doesn't crash/NaN/hang; it never asserts a
successful pad landing or that the pad multiplier scores. This probe seeds the
lander in a clean short-final over each pad (low, slow, centered, upright) and
flies a trivial descent controller (hold upright, keep a ~2 m/s sink, flare) all
the way to contact — then asserts scene ends 'done' with a WIN and the correct
×N multiplier. Isolates the terrain-contact + pad-resolution + multiplier path
(the code that changed) from the separate hard problem of a cross-range autopilot.

  py testing/mars_land_probe.py            # test all four pads (x2/x3/x5/x8)
  py testing/mars_land_probe.py --pad 8    # just the narrow x8 pad

Reuses the same headless-Chrome + manual-pump harness (cdp.Chrome) as
runtime_error_scan.
"""
import os
import sys
import time
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cdp import Chrome  # noqa: E402

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
GAME_URL = "file:///" + os.path.join(os.path.dirname(HERE), "index.html").replace("\\", "/")

HOOK = r"""
(function () {
  window.__ERR = '';
  window.__RAFQ = [];
  window.requestAnimationFrame = function (cb) { window.__RAFQ.push(cb); return window.__RAFQ.length; };
  window.__PUMP = function (nowMs) {
    var q = window.__RAFQ; window.__RAFQ = [];
    for (var i = 0; i < q.length; i++) { try { q[i](nowMs); } catch (e) { window.__ERR = (e && e.stack) ? e.stack : String(e); } }
    return window.__RAFQ.length;
  };
  return true;
})();
"""

# Seed the lander in a clean short-final directly over the target pad: centered (x = pad.x), low
# (pad surface + SEED_CLR), slow sink, zero drift, upright. Returns the setup for logging.
SEED = r"""
(function(padMult, seedClr){
  var pad=null; for (var i=0;i<marsPads.length;i++){ if(marsPads[i].mult===padMult) pad=marsPads[i]; }
  if(!pad) pad=marsPads[0];
  b.x = pad.x;
  b.y = marsGroundY(pad.x) + seedClr;
  b.vx = 0; b.vy = -3.0;          // gentle sink, no drift
  b.ang = 0; b.angv = 0;          // upright
  scene = 'flying'; result = null;
  return {padX: pad.x, padHalf: pad.half, mult: pad.mult, y: b.y, gUnder: marsGroundY(pad.x)};
})(%d, %d)
"""

# Trivial vertical descent controller for the short-final: hold upright (PD with rate lead), keep a
# ~2 m/s sink easing to a soft flare near contact. No cross-range needed (seeded centered).
DESCEND = r"""
(function(){
  if (typeof b === 'undefined' || !b) return {phase:'noB'};
  if (typeof scene !== 'undefined' && scene === 'done') {
    keys[' ']=false; keys['ArrowLeft']=false; keys['ArrowRight']=false;
    return {phase:'done', won: !!(result && result.ok), score: result?result.score:0,
            title: result?result.title:'', mult: (result&&result.mk1)?result.mk1.mult:0};
  }
  var clr = b.y - marsGroundY(b.x);
  var vDesc = -b.vy;
  // hold upright: PD on angle with rate lead
  var effAng = b.ang + b.angv*0.45;
  keys['ArrowLeft']=false; keys['ArrowRight']=false;
  if (effAng > 0.03) keys['ArrowLeft']=true; else if (effAng < -0.03) keys['ArrowRight']=true;
  // descent corridor: brisk (~3.2 m/s) up high, easing to a soft ~1.3 m/s in the last 12 m for the kiss
  var wantDesc = clr > 12 ? 3.2 : 1.3;
  keys[' '] = vDesc > wantDesc;
  return {phase:'fly', clr:clr, vDesc:vDesc, vx:b.vx, ang:b.ang, angv:b.angv, thr:b.thr};
})()
"""


def fly_pad(ch, mult, seed_clr=45, max_steps=4000, verbose=False):
    """Seed a short-final over the pad with the given multiplier, fly the descent, return (won, info)."""
    # fresh run each pad
    ch.eval("(function(){ try{ newRun('mars'); scene='flying'; }catch(e){ window.__ERR=String(e);} })()")
    ch.eval("if (window.__RAFQ.length===0 && typeof frame==='function'){ try{frame(0);}catch(e){window.__ERR=String(e);} }")
    setup = ch.eval(SEED % (mult, seed_clr))
    if verbose:
        print("  seed x%d: over x=%s, %d m up (surface %s)"
              % (mult, setup.get("padX"), seed_clr, setup.get("gUnder")), flush=True)
    now = 0.0
    for step in range(max_steps):
        st = ch.eval(DESCEND)
        if isinstance(st, dict) and st.get("phase") == "done":
            return bool(st.get("won")), st
        now += 16.7
        ch.eval("window.__PUMP(%f)" % now)
    return False, {"phase": "timeout"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pad", type=int, default=0, help="single pad multiplier to test (0 = all)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    prof = os.path.join(os.environ.get("TEMP", "/tmp"), "bo_mars_land_%d" % os.getpid())
    port = 9300 + (os.getpid() % 200)
    ch = Chrome(CHROME, prof, port=port, window=(1280, 900))
    ch.launch()
    ch.send("Page.enable")
    ch.send("Runtime.enable")
    try:
        ch.send("Page.navigate", {"url": GAME_URL + "?play=mars"})
        time.sleep(1.2)
        ch.eval(HOOK)
        pads = [args.pad] if args.pad else [2, 3, 5, 8]
        all_ok = True
        for mult in pads:
            won, st = fly_pad(ch, mult, verbose=args.verbose)
            got_mult = st.get("mult", 0)
            ok = won and got_mult == mult
            all_ok = all_ok and ok
            print("%s  x%d pad -> %s | title=%r score=%s reported_mult=x%s"
                  % ("PASS" if ok else "FAIL", mult, "WIN" if won else "LOSS/" + str(st.get("phase")),
                     st.get("title"), st.get("score"), got_mult), flush=True)
            err = ch.eval("window.__ERR||''")
            if err:
                print("     frame error:", str(err)[:160], flush=True)
        print("\n" + ("ALL PADS LANDABLE + SCORED" if all_ok else "SOME PADS FAILED"))
        sys.exit(0 if all_ok else 2)
    finally:
        try:
            ch.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
