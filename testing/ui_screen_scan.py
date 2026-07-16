"""
UI-screen runtime scan for BLUE ORIGIN LANDINGS — covers the screens the flying
bot never touches: the MENU (no ?play), the BOARD/leaderboard, the DONE result
screen (win + crash + splashdown), and a resize event. Loads the real game in
headless Chrome, installs the same error/NaN/ctx-depth hooks as
runtime_error_scan, forces each scene, pumps a few frames, and checks for
exceptions / NaN draws / canvas-state leaks on each screen.

Run: py testing/ui_screen_scan.py    (exit 0 iff clean)
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Chrome  # noqa: E402

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME_URL = "file:///" + os.path.join(REPO, "index.html").replace("\\", "/")

HOOK_JS = r"""
(function () {
  window.__ERRORS = []; window.__NANDRAW = [];
  window.__CTXDEPTH = 0; window.__CTXDEPTH_UNDERFLOW = 0;
  window.addEventListener('error', function (e) { window.__ERRORS.push(String(e.message)+' @'+(e.lineno||'')); });
  window.addEventListener('unhandledrejection', function (e) { window.__ERRORS.push('reject: '+String(e.reason)); });
  var _e = console.error.bind(console); console.error = function(){ window.__ERRORS.push('console.error: '+Array.from(arguments).map(String).join(' ')); return _e.apply(console,arguments); };
  try {
    var cp = CanvasRenderingContext2D.prototype, _s=cp.save, _r=cp.restore;
    cp.save=function(){window.__CTXDEPTH++;return _s.apply(this,arguments);};
    cp.restore=function(){window.__CTXDEPTH--;if(window.__CTXDEPTH<0){window.__CTXDEPTH_UNDERFLOW++;window.__CTXDEPTH=0;}return _r.apply(this,arguments);};
    var num=['moveTo','lineTo','rect','fillRect','strokeRect','clearRect','arc','arcTo','ellipse','translate','scale','rotate','quadraticCurveTo','bezierCurveTo','setTransform','transform','fillText','strokeText','createLinearGradient','createRadialGradient','drawImage'];
    num.forEach(function(m){ var o=cp[m]; if(typeof o!=='function')return; cp[m]=function(){ for(var i=0;i<arguments.length;i++){var a=arguments[i]; if(typeof a==='number'&&!isFinite(a)){ if(window.__NANDRAW.length<100) window.__NANDRAW.push({method:m,argi:i}); break; }} return o.apply(this,arguments); }; });
  } catch(e){ window.__ERRORS.push('wrap: '+e); }
  window.__RAFQ=[]; window.requestAnimationFrame=function(cb){window.__RAFQ.push(cb);return window.__RAFQ.length;};
  window.__PUMP=function(now){ var q=window.__RAFQ; window.__RAFQ=[]; window.__CTXDEPTH=0; for(var i=0;i<q.length;i++){ try{q[i](now);}catch(e){window.__ERRORS.push('frame-threw: '+(e&&e.stack?e.stack:e));} } return {queued:window.__RAFQ.length, ctxEnd:window.__CTXDEPTH, underflow:window.__CTXDEPTH_UNDERFLOW}; };
  return true;
})();
"""


def pump(ch, n, now0):
    now = now0
    worst = {"ctxEnd": 0, "underflow": 0, "queued": 0}
    for _ in range(n):
        now += 16.667
        r = ch.eval("window.__PUMP(%f)" % now) or {}
        if abs(r.get("ctxEnd", 0)) > abs(worst["ctxEnd"]):
            worst["ctxEnd"] = r.get("ctxEnd", 0)
        worst["underflow"] = max(worst["underflow"], r.get("underflow", 0))
        worst["queued"] = r.get("queued", 0)
    return now, worst


def snap(ch):
    return {
        "errors": ch.eval("window.__ERRORS") or [],
        "nan_draw": ch.eval("window.__NANDRAW.length") or 0,
        "underflow": ch.eval("window.__CTXDEPTH_UNDERFLOW") or 0,
    }


def scenario(ch, name, setup_js, pumps=20):
    """Load fresh, install hooks, apply a scene setup, pump, report."""
    ch.send("Page.navigate", {"url": GAME_URL})
    ch.wait_event("Page.loadEventFired", timeout=25)
    time.sleep(0.4)
    ch.eval(HOOK_JS)
    # wait for a real rAF to hand us the loop
    for _ in range(60):
        if (ch.eval("window.__RAFQ.length") or 0) >= 1:
            break
        time.sleep(0.05)
    now = float(ch.eval("(typeof lastT==='number'?lastT:100000)") or 100000.0)
    now, _ = pump(ch, 3, now)                 # let the menu settle
    if setup_js:
        ch.eval(setup_js)
    now, worst = pump(ch, pumps, now)
    s = snap(ch)
    bad = bool(s["errors"]) or s["nan_draw"] > 0 or worst["ctxEnd"] != 0 or s["underflow"] > 0
    print("  %-22s %s | errs=%d nan_draw=%d ctxEnd=%d underflow=%d"
          % (name, "BAD" if bad else "clean", len(s["errors"]), s["nan_draw"], worst["ctxEnd"], s["underflow"]),
          flush=True)
    for e in s["errors"][:6]:
        print("       ERROR:", str(e)[:160], flush=True)
    return {"name": name, "bad": bad, **s, "worst_ctx": worst}


# Scene setups. These drive the game into each screen using its own globals/fns.
SCENARIOS = [
    ("menu-idle", "", 30),
    ("menu-narrow", "try{ W=380; H=780; if(typeof resize==='function') resize(); }catch(e){window.__ERRORS.push('resize:'+e);}", 20),
    ("board-open", "try{ if(typeof openBoard==='function') openBoard(); else scene='board'; }catch(e){window.__ERRORS.push('board:'+e);}", 25),
    # WIN done screen
    ("done-win", "try{ if(save&&!save.pilot) save.pilot={name:'TP',email:''}; newRun('ocean'); finish(true,'JACKLYN HAS THE BOOSTER',['Vertical speed 3.0 m/s'],3200,'base 2000 · fuel 900 · precision 300'); }catch(e){window.__ERRORS.push('donewin:'+e);}", 25),
    # CRASH done screen
    ("done-crash", "try{ if(save&&!save.pilot) save.pilot={name:'TP',email:''}; newRun('ocean'); crash(5000,2,'Came in too hot (42.0 m/s)'); }catch(e){window.__ERRORS.push('donecrash:'+e);}", 25),
    # SPLASHDOWN (miss the deck) done screen
    ("done-splash", "try{ if(save&&!save.pilot) save.pilot={name:'TP',email:''}; newRun('tower'); finish(false,'SPLASHDOWN',['Missed Jacklyn by 3200 m'],0); }catch(e){window.__ERRORS.push('donesplash:'+e);}", 25),
    # MARS win done screen
    ("done-mars-win", "try{ if(save&&!save.pilot) save.pilot={name:'TP',email:''}; newRun('mars'); finish(true,'BLUE MOON MK1 IS ON THE MOON',['Vertical speed 2.0 m/s'],4000,'base 2500'); }catch(e){window.__ERRORS.push('donemars:'+e);}", 25),
    # PAUSED overlay mid-flight
    ("paused", "try{ if(save&&!save.pilot) save.pilot={name:'TP',email:''}; newRun('ocean'); scene='paused'; }catch(e){window.__ERRORS.push('paused:'+e);}", 20),
]


def main():
    prof = os.path.join(os.environ.get("TEMP", "/tmp"), "bo_ui_scan_%d" % os.getpid())
    port = 9500 + (os.getpid() % 200)
    ch = Chrome(CHROME, prof, port=port, window=(1280, 900))
    ch.launch()
    ch.send("Page.enable")
    ch.send("Runtime.enable")
    any_bad = False
    out = {}
    try:
        print("=== UI screen scan ===", flush=True)
        for name, setup, pumps in SCENARIOS:
            r = scenario(ch, name, setup, pumps)
            out[name] = r
            any_bad = any_bad or r["bad"]
    finally:
        ch.close()
    with open(os.path.join(REPO, "testing", "ui_scan.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("\nRESULT %s" % ("FAIL" if any_bad else "PASS (all screens clean)"), flush=True)
    sys.exit(1 if any_bad else 0)


if __name__ == "__main__":
    main()
