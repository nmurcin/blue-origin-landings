r"""
A4 scoring probe: drive the REAL MK1 (mars) evalTouchdown() to a touchdown of a
chosen quality, then render the done screen and screenshot the scorecard. This
exercises the full A4 path: mk1EvalTouchdown -> mk1Score -> finish -> drawDone ->
drawMK1Scorecard (grade banner + medal chips), plus the win/crash screen-flash.

It sets b to a hand-picked contact state (off-center, descent, drift, tilt, fuel),
calls evalTouchdown() directly (the same fn the ground-contact block calls), lets a
few real frames paint, verifies NO JS errors, and grabs a PNG.

ASCII only. Windows py. Verifies clean; captures a screenshot for eyeballing.

USAGE
  py testing/a4_score_probe.py --preset perfect --name a4_done_perfect
  py testing/a4_score_probe.py --preset good    --name a4_done_good
  py testing/a4_score_probe.py --preset crash    --name a4_done_crash
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cdp import Chrome, WSError  # noqa: E402

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
GAME_HTML = os.path.abspath(os.path.join(HERE, "..", "index.html"))
FRAMES = os.path.join(HERE, "frames")
PROFILE = os.path.join(HERE, "_chromeprofile_cdp")

# preset -> contact state (off m from center, vy down m/s, vx drift m/s, ang deg, fuel kg)
# FUEL0 mars = 2400. EFFICIENCY medal needs fuel >= 0.55*2400 = 1320.
PRESETS = {
    "perfect": dict(off=1.0, vy=0.8, vx=0.4, ang=1.0, fuel=1600),   # bullseye + feather + fat tank
    "good":    dict(off=10.0, vy=2.0, vx=1.2, ang=3.0, fuel=900),   # legal, some medals missed
    "rough":   dict(off=26.0, vy=3.2, vx=2.2, ang=5.5, fuel=300),   # scruffy edge landing, no medals
    "crash":   dict(off=5.0, vy=9.0, vx=0.5, ang=2.0, fuel=800),    # too hot -> HARD LUNAR IMPACT
}

HOOK = r"""
(function(){ window.__ERR=[];
  window.addEventListener('error',function(e){window.__ERR.push(String(e.message)+' @'+(e.lineno||''));});
  window.addEventListener('unhandledrejection',function(e){window.__ERR.push('reject:'+String(e.reason));});
  var _e=console.error.bind(console); console.error=function(){window.__ERR.push('console.error:'+Array.from(arguments).map(String).join(' '));return _e.apply(console,arguments);};
  return true; })()
"""

SNAP = r"""
(() => JSON.stringify({
  scene: (typeof scene!=='undefined'?scene:null),
  ok: (typeof result!=='undefined'&&result)?!!result.ok:null,
  title: (typeof result!=='undefined'&&result)?result.title:null,
  score: (typeof result!=='undefined'&&result)?result.score:null,
  breakdown: (typeof result!=='undefined'&&result)?result.breakdown:null,
  mk1: (typeof result!=='undefined'&&result&&result.mk1)?result.mk1:null,
  errs: window.__ERR||[]
}))()
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="perfect", choices=list(PRESETS))
    ap.add_argument("--name", default=None)
    ap.add_argument("--window", default="1280x900")
    ap.add_argument("--port", type=int, default=9224)
    args = ap.parse_args()
    p = PRESETS[args.preset]
    name = args.name or ("a4_done_" + args.preset)

    w, h = (int(x) for x in args.window.lower().split("x"))
    os.makedirs(FRAMES, exist_ok=True)
    ch = Chrome(CHROME, PROFILE, port=args.port, window=(w, h))
    rc = 0
    try:
        ch.launch()
        ch.send("Page.enable")
        ch.send("Runtime.enable")
        url = "file:///" + GAME_HTML.replace("\\", "/") + "?play=mars"
        print("[load]", url)
        ch.send("Page.navigate", {"url": url})
        try:
            ch.wait_event("Page.loadEventFired", timeout=20)
        except WSError:
            pass
        ch.eval(HOOK)

        # wait for flying + booster
        end = time.time() + 20
        ready = False
        while time.time() < end:
            import json
            st = json.loads(ch.eval(SNAP) or "{}")
            if st.get("scene") == "flying":
                ready = True
                break
            time.sleep(0.05)
        if not ready:
            print("[FAIL] never reached flying", file=sys.stderr)
            return 2

        # Give a pilot name so submitScore's local mirror path runs, then set the contact
        # state at ground level and call the REAL evalTouchdown() (the mars ground-contact fn).
        inject = (
            "(()=>{"
            "if(save&&!save.pilot)save.pilot={name:'A4',email:''};"
            "b.x=%f; b.y=0; b.vy=-%f; b.vx=%f; b.ang=%f*Math.PI/180; b.angv=0; b.fuel=%f;"
            "evalTouchdown();"
            "return (typeof result!=='undefined'&&result)?result.title:'noresult';})()"
        ) % (p["off"], p["vy"], p["vx"], p["ang"], p["fuel"])
        title = ch.eval(inject)
        print("[touchdown]", title)

        # let a few real frames paint the done screen + the flash bloom
        time.sleep(0.4)
        import json
        st = json.loads(ch.eval(SNAP) or "{}")
        errs = st.get("errs") or []
        out = os.path.join(FRAMES, name + ".png")
        n = ch.screenshot_png(out)
        print("[result] scene=%s ok=%s title=%r score=%s"
              % (st.get("scene"), st.get("ok"), st.get("title"), st.get("score")))
        print("[breakdown]", st.get("breakdown"))
        print("[mk1]", json.dumps(st.get("mk1")))
        print("[grab] -> %s (%d bytes)" % (out, n))
        if errs:
            rc = 1
            print("[ERRORS]")
            for e in errs[:8]:
                print("   ", str(e)[:160])
        else:
            print("[clean] no JS errors")
    finally:
        ch.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
