"""
Runtime error + NaN scanner for BLUE ORIGIN LANDINGS.

The physics_harness only exercises stepPhysics; this drives the WHOLE real game
(update + render + HUD + scoring + phase machine) in headless Chrome and watches
for anything the static scan and physics harness cannot see:

  - uncaught exceptions  (window.onerror)
  - console.error / console.warn output
  - CanvasRenderingContext2D calls with NaN/Infinite args (wrapped + counted)
  - NaN / non-finite leaking into the booster state `b` (x,y,vx,vy,ang,angv,thr,fuel)
  - a run that never terminates (scene stuck 'flying' past the frame budget)

Design (deterministic, one Chrome under tight control — NO parallel Chrome):
  * Load ../index.html?play=<mode> so newRun() drops straight into 'flying'.
  * BEFORE the game script runs we can't inject (single file), so instead we
    install hooks AFTER load, then override requestAnimationFrame with a manual
    pump and call the game's own frame() at a fixed dt via fake timestamps.
    (The game reads `now` from the rAF arg, so we control game-time exactly.)
  * Each pump we optionally push inputs via the real `keys` map (autopilot-lite:
    a simple retro-burn-below-threshold law) so the booster actually lands
    rather than free-falling — this exercises the burn / touchdown / done paths.
  * We sample `b` every pump for non-finite, and read the error/warn buffers.

Run:  py testing/runtime_error_scan.py [ocean|tower|mars|all]
Writes runtime_scan_<mode>.json ; exits 0 iff no errors/NaN across all modes run.
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

# Hook installed after load: capture errors, wrap ctx methods for NaN args,
# and replace rAF with a global manual pump __PUMP(nowMs).
HOOK_JS = r"""
(function () {
  window.__ERRORS = [];
  window.__WARNS = [];
  window.__NANDRAW = [];   // {method, args} where a numeric arg was non-finite
  window.addEventListener('error', function (e) {
    window.__ERRORS.push(String(e.message) + ' @ ' + (e.filename||'') + ':' + (e.lineno||''));
  });
  window.addEventListener('unhandledrejection', function (e) {
    window.__ERRORS.push('unhandledrejection: ' + String(e.reason));
  });
  var _err = console.error.bind(console);
  console.error = function () {
    window.__ERRORS.push('console.error: ' + Array.from(arguments).map(String).join(' '));
    return _err.apply(console, arguments);
  };
  var _warn = console.warn.bind(console);
  console.warn = function () {
    window.__WARNS.push(Array.from(arguments).map(String).join(' '));
    return _warn.apply(console, arguments);
  };

  // Track ctx save/restore stack depth so we can prove per-frame balance at
  // runtime (a textual save!=restore count is a false positive when the restores
  // are on mutually-exclusive early-return branches; only runtime depth is truth).
  window.__CTXDEPTH = 0;
  window.__CTXDEPTH_MAX = 0;
  window.__CTXDEPTH_UNDERFLOW = 0;   // restore() called with empty stack (real bug)
  try {
    var cp = CanvasRenderingContext2D.prototype;
    var _save = cp.save, _restore = cp.restore;
    cp.save = function () { window.__CTXDEPTH++; if (window.__CTXDEPTH > window.__CTXDEPTH_MAX) window.__CTXDEPTH_MAX = window.__CTXDEPTH; return _save.apply(this, arguments); };
    cp.restore = function () { window.__CTXDEPTH--; if (window.__CTXDEPTH < 0) { window.__CTXDEPTH_UNDERFLOW++; window.__CTXDEPTH = 0; } return _restore.apply(this, arguments); };
  } catch (e) { window.__ERRORS.push('ctx-depth-wrap failed: ' + e); }

  // Wrap the numeric 2D-context methods so a NaN/Infinity coordinate is recorded
  // (silent in Chrome: it just no-ops the draw, which is exactly the kind of
  //  render bug we want surfaced).
  try {
    var proto = CanvasRenderingContext2D.prototype;
    var numMethods = ['moveTo','lineTo','rect','fillRect','strokeRect','clearRect',
                      'arc','arcTo','ellipse','translate','scale','rotate',
                      'quadraticCurveTo','bezierCurveTo','setTransform','transform',
                      'fillText','strokeText','createLinearGradient','createRadialGradient',
                      'drawImage'];
    numMethods.forEach(function (m) {
      var orig = proto[m];
      if (typeof orig !== 'function') return;
      proto[m] = function () {
        for (var i = 0; i < arguments.length; i++) {
          var a = arguments[i];
          if (typeof a === 'number' && !isFinite(a)) {
            if (window.__NANDRAW.length < 200)
              window.__NANDRAW.push({method: m, argi: i, args: Array.from(arguments).map(function(x){return typeof x==='number'?x:String(x).slice(0,20);})});
            break;
          }
        }
        return orig.apply(this, arguments);
      };
    });
  } catch (e) { window.__ERRORS.push('ctx-wrap failed: ' + e); }

  // Replace rAF with a manual pump. The game just called requestAnimationFrame(frame)
  // once at load; capture that pending callback and every subsequent one.
  window.__RAFQ = [];
  window.requestAnimationFrame = function (cb) { window.__RAFQ.push(cb); return window.__RAFQ.length; };
  window.__PUMP = function (nowMs) {
    var q = window.__RAFQ; window.__RAFQ = [];
    for (var i = 0; i < q.length; i++) { try { q[i](nowMs); } catch (e) { window.__ERRORS.push('frame-threw: ' + (e && e.stack ? e.stack : e)); } }
    return window.__RAFQ.length;   // callbacks queued for next pump (should be >=1 while looping)
  };
  return true;
})();
"""

# Autopilot control law as a plain function expression (single source of truth).
# Stateless — sets the real `keys` map then returns; it does NOT register its own
# rAF, so it composes with our __PUMP override instead of colliding with it. This
# is the tuned law from bot_autopilot.py (proven to fly a complete controlled
# descent to a soft, upright, zero-damage touchdown in the LIVE game).
_AUTOPILOT_FN = r"""
function () {
  if (typeof b === 'undefined' || !b) return 'nob';
  if (typeof scene !== 'undefined' && (scene === 'done' || scene === 'menu')) {
    keys[' ']=false; keys['ArrowLeft']=false; keys['ArrowRight']=false; return 'ended';
  }
  if (b.opening) { return 'opening'; }   // mated ascent handoff; hold hands-off
  var A_NET = 10.5, VX_KEEP = 60, MARGIN = 150;
  function steer(t){ var e=t-b.ang; keys['ArrowLeft']=false; keys['ArrowRight']=false;
    if (e>0.015) keys['ArrowRight']=true; else if (e<-0.015) keys['ArrowLeft']=true; }
  var dx=(typeof deckX==='function')?deckX():0;
  var gap=dx-b.x, desc=b.vy<0, sd=desc?-b.vy:0;
  var stop=(b.vy*b.vy)/(2*A_NET), burnAlt=stop*1.20+MARGIN;
  var m=(typeof mode!=='undefined')?mode:'ocean', ph, tgt, burn;
  if (m==='mars'){
    var vtgtM=Math.max(2.0, 0.05*b.y + 2.0);
    tgt=Math.max(-0.12,Math.min(0.12,(dx-b.x)*0.0008 - b.vx*0.03));
    burn = desc && b.y<=stop*1.25+MARGIN && sd>vtgtM; ph='MARS';
  } else if (!desc){ tgt=0; burn=false; ph='COAST_UP';
  } else if (b.y<=burnAlt && sd>1){
    var vtgt=Math.max(3.0, 0.055*b.y + 3.0);
    var aim=(Math.abs(gap)<250)?(-b.vx*0.012):((dx-b.x)*0.00035 - b.vx*0.010);
    tgt=Math.max(-0.20,Math.min(0.20,aim));
    if (b.y<250) tgt=Math.max(-0.09,Math.min(0.09,-b.vx*0.02));
    burn=(sd>vtgt); ph='TERMINAL';
  } else if (b.vx>VX_KEEP && gap>800 && b.y>burnAlt && b.y<9500){
    tgt=Math.atan2(-b.vx,-b.vy); burn=true; ph='BLEED';
  } else { tgt=Math.atan2(-b.vx,-b.vy); burn=false; ph='GLIDE'; }
  keys[' ']=burn; steer(tgt);
  return {phase: ph, y:b.y, vy:b.vy, x:b.x, gap:gap, thr:b.thr, fuel:b.fuel};
}
"""

STATE_JS = r"""
(function () {
  if (typeof b === 'undefined' || !b) return {scene: (typeof scene!=='undefined'?scene:'?'), nob: true};
  function bad(v){ return typeof v==='number' && !isFinite(v); }
  var fields = ['x','y','vx','vy','ang','angv','thr','fuel','damage','heatFrac'];
  var nan = [];
  fields.forEach(function(f){ if (bad(b[f])) nan.push(f); });
  return {
    scene: (typeof scene!=='undefined'?scene:'?'),
    phase: b.phase, x:b.x, y:b.y, vx:b.vx, vy:b.vy, ang:b.ang, angv:b.angv,
    thr:b.thr, fuel:b.fuel, nan: nan,
    nErr: window.__ERRORS.length, nWarn: window.__WARNS.length, nNanDraw: window.__NANDRAW.length
  };
})();
"""

# One combined in-page step: run autopilot, pump the frame, and (every `sampleEvery`
# pumps) return a state sample — all in ONE CDP round-trip. Cuts per-pump latency
# ~3x vs. separate autopilot+pump+state evals. Defines window.__STEP(nowMs, i, sampleEvery).
COMBINED_STEP_JS = r"""
window.__AUTOPILOT = """ + _AUTOPILOT_FN + r""";
window.__stateSnap = function () {
  if (typeof b === 'undefined' || !b) return {scene: (typeof scene!=='undefined'?scene:'?'), nob: true};
  function bad(v){ return typeof v==='number' && !isFinite(v); }
  var f=['x','y','vx','vy','ang','angv','thr','fuel','damage','heatFrac'], nan=[];
  f.forEach(function(k){ if (bad(b[k])) nan.push(k); });
  return {scene:(typeof scene!=='undefined'?scene:'?'), phase:b.phase, x:b.x, y:b.y,
    vx:b.vx, vy:b.vy, ang:b.ang, angv:b.angv, thr:b.thr, fuel:b.fuel, nan:nan,
    nErr:window.__ERRORS.length, nWarn:window.__WARNS.length, nNanDraw:window.__NANDRAW.length};
};
window.__STEP = function (nowMs, i, sampleEvery) {
  window.__AUTOPILOT();
  window.__CTXDEPTH = 0;                 // reset before the frame; a well-formed frame ends at 0
  var queued = window.__PUMP(nowMs);
  window.__CTXEND = window.__CTXDEPTH;   // ctx save-depth left dangling at end of this frame (should be 0)
  var out = {queued: queued, ctxEnd: window.__CTXDEPTH, ctxUnderflow: window.__CTXDEPTH_UNDERFLOW};
  if (i % sampleEvery === 0 || queued === 0) { out.sample = window.__stateSnap(); out.sample.pump = i; out.sample.ctxEnd = window.__CTXDEPTH; }
  return out;
};
"""


def scan_mode(ch, mode, max_pumps=5000, dt_ms=50.0, verbose=False):
    """Drive one mode to termination; return a findings dict."""
    ch.send("Page.navigate", {"url": GAME_URL + "?play=" + mode})
    # Wait for load + the game's initial rAF(frame) registration.
    ch.wait_event("Page.loadEventFired", timeout=25)
    time.sleep(0.4)
    ch.eval(HOOK_JS)
    # The game called requestAnimationFrame(frame) during page-script execution,
    # BEFORE our hook replaced rAF. That first callback fires on a REAL Chrome
    # rAF tick with a real `now` (setting the game's lastT), and its end-of-frame
    # requestAnimationFrame(frame) is then captured by our __RAFQ. So we WAIT for
    # that real tick to hand us a queued callback rather than kicking frame(0)
    # ourselves (a frame(0) kick would feed a huge NEGATIVE dt = (0-lastT)/1000
    # and produce spurious errors that are pure harness artifacts, not game bugs).
    got = False
    for _ in range(60):
        if (ch.eval("window.__RAFQ.length") or 0) >= 1:
            got = True
            break
        time.sleep(0.05)
    if not got:
        # Fallback: re-arm the loop with a REALISTIC dt by setting lastT just
        # behind a base timestamp, then registering one frame under our hook.
        ch.eval("try{ lastT = 100000 - 16.667; }catch(e){}")
        ch.eval("if (window.__RAFQ.length===0 && typeof frame==='function'){ try{frame(100000);}catch(e){window.__ERRORS.push('kick: '+(e&&e.stack?e.stack:e));} }")

    # Install the combined per-pump step (autopilot + pump + optional sample) so
    # each game frame costs ONE CDP round-trip instead of three.
    ch.eval(COMBINED_STEP_JS)

    # Start virtual time at the game's current lastT so the first pump's dt is a
    # normal ~16.7 ms, not a clamp/negative spike.
    now = float(ch.eval("(typeof lastT==='number'?lastT:performance.now())") or 100000.0)
    landed_at = None
    nan_first = None
    samples = []
    stuck = False
    ctx_bad = []          # frames where ctx save-stack didn't return to 0
    ctx_underflow_max = 0
    sample_every = 30
    i = 0
    for i in range(max_pumps):
        now += dt_ms
        res = ch.eval("window.__STEP(%f, %d, %d)" % (now, i, sample_every)) or {}
        queued = res.get("queued", 0)
        st = res.get("sample")
        if res.get("ctxEnd", 0) != 0 and len(ctx_bad) < 20:
            ctx_bad.append({"pump": i, "ctxEnd": res.get("ctxEnd")})
        ctx_underflow_max = max(ctx_underflow_max, res.get("ctxUnderflow", 0) or 0)
        if st:
            samples.append(st)
            if st.get("nan") and nan_first is None:
                nan_first = st
        if queued == 0:
            # loop stopped queuing frames — terminal (done/menu) or a throw killed it
            st2 = ch.eval(STATE_JS)
            samples.append({"pump": i, "stopped_queue": True, **(st2 or {})})
            if st2 and st2.get("scene") in ("done", "menu"):
                landed_at = {"pump": i, **st2}
            break
        if st and st.get("scene") in ("done", "menu"):
            landed_at = {"pump": i, **st}
            break
    else:
        stuck = True

    errors = ch.eval("window.__ERRORS") or []
    warns = ch.eval("window.__WARNS") or []
    nandraw = ch.eval("window.__NANDRAW") or []
    final = ch.eval(STATE_JS)
    return {
        "mode": mode,
        "pumps_run": i + 1,
        "final": final,
        "landed_at": landed_at,
        "nan_first": nan_first,
        "stuck_never_terminated": stuck,
        "errors": errors,
        "warns": warns,
        "nan_draw_calls": nandraw[:40],
        "nan_draw_count": len(nandraw),
        "ctx_unbalanced_frames": ctx_bad,
        "ctx_underflow_max": ctx_underflow_max,
        "samples": samples,
    }


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    modes = ["ocean", "tower", "mars"] if which == "all" else [which]
    prof = os.path.join(os.environ.get("TEMP", "/tmp"), "bo_runtime_scan_%d" % os.getpid())
    port = 9300 + (os.getpid() % 200)
    ch = Chrome(CHROME, prof, port=port, window=(1280, 900))
    ch.launch()
    ch.send("Page.enable")
    ch.send("Runtime.enable")
    any_bad = False
    results = {}
    try:
        for m in modes:
            print("=== scanning %s ===" % m, flush=True)
            r = scan_mode(ch, m)
            results[m] = r
            bad = (bool(r["errors"]) or bool(r["nan_first"]) or r["stuck_never_terminated"]
                   or r["nan_draw_count"] > 0 or bool(r["ctx_unbalanced_frames"])
                   or r["ctx_underflow_max"] > 0)
            any_bad = any_bad or bad
            status = "BAD" if bad else "clean"
            print("  %s: %s | pumps=%d final_scene=%s errs=%d warns=%d nan_draw=%d ctx_unbal=%d ctx_underflow=%d landed=%s stuck=%s"
                  % (m, status, r["pumps_run"],
                     (r["final"] or {}).get("scene"), len(r["errors"]), len(r["warns"]),
                     r["nan_draw_count"], len(r["ctx_unbalanced_frames"]), r["ctx_underflow_max"],
                     bool(r["landed_at"]), r["stuck_never_terminated"]), flush=True)
            if r["errors"]:
                for e in r["errors"][:8]:
                    print("     ERROR:", str(e)[:160], flush=True)
            if r["nan_first"]:
                print("     NAN in b:", r["nan_first"], flush=True)
            if r["nan_draw_count"]:
                print("     NAN draw sample:", r["nan_draw_calls"][:3], flush=True)
            if r["ctx_unbalanced_frames"]:
                print("     CTX save/restore unbalanced frames:", r["ctx_unbalanced_frames"][:5], flush=True)
            if r["ctx_underflow_max"]:
                print("     CTX restore underflow (restore on empty stack) count:", r["ctx_underflow_max"], flush=True)
            out = os.path.join(REPO, "testing", "runtime_scan_%s.json" % m)
            with open(out, "w") as f:
                json.dump(r, f, indent=2)
    finally:
        ch.close()
    print("\nRESULT %s" % ("FAIL (issues found)" if any_bad else "PASS (all clean)"), flush=True)
    sys.exit(1 if any_bad else 0)


if __name__ == "__main__":
    main()
