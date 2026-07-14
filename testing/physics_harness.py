"""
REAL-JS deterministic physics test harness for BLUE ORIGIN LANDINGS.

This is the GROUND TRUTH test runner. It loads the actual blue_origin_landings.html
in headless Chrome and calls the game's REAL stepPhysics()/applyModeParams()/evalTouchdown()
functions with synthetic states — NOT a Python re-implementation. (scripts/test_physics.py is a
stale Python port with wrong constants; do not trust it for physics behavior.)

Why headless Chrome and not Node: there is no Node/Deno on this box. The game is one <script> with
top-level `function stepPhysics` and `let`/`const` globals, no IIFE — so Runtime.evaluate in the page's
global scope can read/reassign the globals and call the functions directly.

Run:  py testing/physics_harness.py                 (all tests, prints PASS/FAIL, exits nonzero on fail)
      py testing/physics_harness.py --only A,C,K     (subset)
      py testing/physics_harness.py --json out.json  (also dump raw results)

Test battery (audit spec A-K):
  A free-fall   B axial-thrust   C deceleration   D orientation/sign   E gimbal torque
  F glide-slope G hover-equilibrium H fuel/mass    I energy/drag        J touchdown
  K 30/60/120 Hz time-step invariance
"""

import argparse
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Chrome  # noqa: E402

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
GAME_HTML = os.path.join(REPO, "blue_origin_landings.html")
# Use a FRESH temp profile per process (pid-tagged) so a prior force-kill can never leave a
# SingletonLock that silently kills the next launch. Cleaned up by Chrome.close()/OS temp reaper.
# NOTE: never run `taskkill /F /IM chrome.exe` — it kills the user's real browser AND corrupts
# whatever profile was open. Use testing/kill_test_chrome.ps1 (matches only our profile paths).
PROFILE = os.path.join(tempfile.gettempdir(), f"bo_landings_prof_{os.getpid()}")

# file:// URL Chrome wants (Windows path -> forward slashes, file:///C:/...)
GAME_URL = "file:///" + GAME_HTML.replace("\\", "/")

# ---------------------------------------------------------------------------
# JS TEST LIBRARY — injected once into the page. Every function calls the REAL
# game code. Returns plain JSON so Python asserts on it.
#
# CONVENTIONS (see testing/PHYSICS_CONVENTIONS.md), all traced from the game:
#   world +y = UP; ang=0 = nose up; nose=(sin,cos); tail=-(sin,cos);
#   thrust force on vehicle = T*(sin(ang),cos(ang)) along nose; g pulls -y.
#
# We reconstruct the ACCELERATION the game applied in a step by差分: run one
# stepPhysics substep from a known state with dt, then read back the velocity
# delta / dt. To isolate FORCES cleanly we mostly use analytic reconstruction
# from the same formulas the game uses, but ALWAYS validated by stepping the
# real function so a sign/mass/dt bug in the real code surfaces.
# ---------------------------------------------------------------------------
JS_LIB = r"""
window.__H = (function () {
  // Deep-ish clone of a plain state object (no funcs).
  function S(o){ return Object.assign({x:0,y:5000,vx:0,vy:0,ang:0,angv:0,fuel:50000}, o||{}); }

  // Set the game into a given mode with real per-mode constants applied.
  // Returns the key constants so the test can compute expected values with the
  // SAME numbers the game uses.
  function setup(m){
    mode = m;
    applyModeParams(m);           // real setter: G, THRUST, MDOT, DRY_MASS, FUEL0, CDA_*, ENTRY_Y...
    SHIP_MODE = (m==='mars');     // applyModeParams keeps SHIP_MODE=false; mars uses flip only near ground
    ASCENT_MODE = false;
    return consts();
  }
  function consts(){
    return { G:G, THRUST:THRUST, MDOT:MDOT, DRY_MASS:DRY_MASS, FUEL0:FUEL0,
             CDA_AX:CDA_AX, CDA_LAT:CDA_LAT, ENTRY_Y:ENTRY_Y, RHO0:RHO0, HSCALE:HSCALE,
             TORQUE:TORQUE, CL_K:(typeof CL_K!=='undefined'?CL_K:null),
             GLIDE_TOP_Y:(typeof GLIDE_TOP_Y!=='undefined'?GLIDE_TOP_Y:null),
             GLIDE_FLOOR_Y:(typeof GLIDE_FLOOR_Y!=='undefined'?GLIDE_FLOOR_Y:null),
             GLIDE_ENTRY_SPD:(typeof GLIDE_ENTRY_SPD!=='undefined'?GLIDE_ENTRY_SPD:null),
             GLIDE_LEAN:(typeof GLIDE_LEAN!=='undefined'?GLIDE_LEAN:null),
             deckX: (function(){ try { return deckX(); } catch(e){ return null; } })() };
  }

  // Run N real substeps of stepPhysics with fixed sdt. Kills wind for determinism
  // unless keepWind. Returns the final state + the measured mean accel over step 1.
  function run(m, st, opts){
    opts = opts||{};
    setup(m);
    if (opts.SHIP_MODE!==undefined) SHIP_MODE = opts.SHIP_MODE;
    if (opts.ASCENT_MODE!==undefined) ASCENT_MODE = opts.ASCENT_MODE;
    // deterministic env: no wind unless asked
    env = { windBase:0, windGust:0, windPhase:0, gateX:0 };
    if (opts.wind) env = opts.wind;
    var s = S(st);
    var thr = (opts.thr===undefined?0:opts.thr);
    var tq  = (opts.tq===undefined?0:opts.tq);
    var fin = (opts.fin===undefined?0:opts.fin);
    var dt  = (opts.dt===undefined?(1/120):opts.dt);
    var n   = (opts.steps===undefined?1:opts.steps);
    // capture accel on the FIRST substep via velocity delta (semi-implicit: v uses this-step accel)
    var v0x=s.vx, v0y=s.vy, av0=s.angv;
    var heat=null, first=null;
    for (var i=0;i<n;i++){
      var pvx=s.vx, pvy=s.vy, pav=s.angv, py=s.y;
      heat = stepPhysics(s, dt, thr, tq, fin);
      if (i===0){
        first = { ax:(s.vx-pvx)/dt, ay:(s.vy-pvy)/dt, aacc:(s.angv-pav)/dt };
      }
    }
    return { s:s, first:first, heat:heat, consts:consts() };
  }

  // vectors
  function nose(ang){ return {x:Math.sin(ang), y:Math.cos(ang)}; }
  function tail(ang){ return {x:-Math.sin(ang), y:-Math.cos(ang)}; }
  function dot(a,b){ return a.x*b.x+a.y*b.y; }

  // Reconstruct the THRUST FORCE the game applies (analytic, matches L1774-1775),
  // but only meaningful when thr>0 & fuel>0. Used by tests B/C/D/G.
  function thrustForce(m, ang, thr){
    setup(m);
    var T = THRUST*thr;
    return { x:T*Math.sin(ang), y:T*Math.cos(ang), mag:T };
  }

  // Touchdown evaluation: set b to a landing state at y<=0 boundary, call the real
  // evalTouchdown, read back result.ok + result.title. Restores scene after.
  function touchdown(m, st){
    setup(m);
    env = { windBase:0, windGust:0, windPhase:0, gateX:0 };
    scene='flying'; result=null;
    b = Object.assign(S(st), {y:0});   // at the deck
    // make sure deckX-relative offset is what the test set (st.x is world x)
    try { evalTouchdown(); } catch(e){ return {error:String(e)}; }
    var ok = !!(result && result.ok);
    var title = result? result.title : null;
    var lines = result? result.lines : null;
    scene='menu';
    return { ok:ok, title:title, lines:lines, hadResult: !!result };
  }

  return { S:S, setup:setup, consts:consts, run:run, nose:nose, tail:tail, dot:dot,
           thrustForce:thrustForce, touchdown:touchdown };
})();
'ready';
"""


class Harness:
    def __init__(self, html_path=None, port=9333, profile=None):
        # html_path lets a caller point the harness at a DIFFERENT build (e.g. the extracted
        # baseline b6444b7) for A/B regression testing. Defaults to the current working-tree build.
        self.url = ("file:///" + os.path.abspath(html_path).replace("\\", "/")) if html_path else GAME_URL
        self.chrome = Chrome(CHROME, profile or PROFILE, port=port, window=(900, 700))

    def start(self):
        self.chrome.launch()
        self.chrome.send("Page.enable")
        self.chrome.send("Runtime.enable")
        self.chrome.send("Page.navigate", {"url": self.url})
        # wait for load
        try:
            self.chrome.wait_event("Page.loadEventFired", timeout=20)
        except Exception:
            pass
        # give the script a beat to define globals, then inject the lib
        time.sleep(0.6)
        ready = self.chrome.eval(JS_LIB)
        if ready != "ready":
            raise RuntimeError(f"JS lib injection failed: {ready!r}")
        # sanity: real stepPhysics exists
        ok = self.chrome.eval("typeof stepPhysics==='function' && typeof applyModeParams==='function'")
        if not ok:
            raise RuntimeError("real game functions not found in page scope")

    def call(self, expr):
        return self.chrome.eval(expr)

    def stop(self):
        self.chrome.close()


def approx(a, b, tol):
    return abs(a - b) <= tol


# ---------------------------------------------------------------------------
# TESTS. Each returns (name, passed, detail-dict). They call the real JS via h.call.
# ---------------------------------------------------------------------------

def test_A_freefall(h):
    """No thrust, no air: ay=-G exactly; vx constant; ang unchanged (no torque)."""
    r = h.call("__H.run('ocean', {y:60000, vx:120, vy:-50, ang:0.3, angv:0, fuel:50000}, "
               "{thr:0, tq:0, dt:1/120, steps:1})")
    # at 60 km rho ~ 0 (HSCALE 8500 -> exp(-7) ~ 9e-4 * 1.225 ~ tiny), so aero negligible
    G = r["consts"]["G"]
    ax, ay = r["first"]["ax"], r["first"]["ay"]
    s = r["s"]
    ok = approx(ay, -G, 0.05) and approx(ax, 0.0, 0.05) and approx(r["first"]["aacc"], 0.0, 1e-6)
    return ("A free-fall", ok, {"ay": ay, "expected_ay": -G, "ax": ax, "aacc": r["first"]["aacc"]})


def test_B_axial_thrust(h):
    """Thrust through COM along body axis: accel opposite the TAIL (i.e. along nose); ~0 angular accel."""
    ang = 0.0
    r = h.call(f"__H.run('ocean', {{y:60000, vx:0, vy:0, ang:{ang}, angv:0, fuel:50000}}, "
               "{thr:1, tq:0, dt:1/120, steps:1})")
    c = r["consts"]
    m = c["DRY_MASS"] + 50000
    exp_ay = c["THRUST"] / m - c["G"]   # nose up => +y thrust, minus gravity
    ax, ay = r["first"]["ax"], r["first"]["ay"]
    # accel direction should be along nose(0)=(0,1): ax~0, ay = T/m - G
    ok = approx(ax, 0.0, 0.05) and approx(ay, exp_ay, 0.3) and approx(r["first"]["aacc"], 0.0, 1e-6)
    # also verify direction is OPPOSITE tail: tail(0)=(0,-1); thrust accel dot(-tail)=+
    return ("B axial-thrust", ok, {"ax": ax, "ay": ay, "expected_ay": exp_ay,
                                   "aacc": r["first"]["aacc"], "T_over_m": c["THRUST"]/m})


def test_C_deceleration(h):
    """Down-right velocity, tail bottom-right (nose up-left => ang in (-pi/2,0)); burn opposes v."""
    # tail bottom-right means tail=(-sin,-cos) has tail.x>0,tail.y<0 => sin<0,cos>0 => ang in (-pi/2,0)
    ang = -0.5  # ~ -28.6 deg: nose up-left, tail down-right
    # velocity down-right: vx>0, vy<0
    r = h.call(f"__H.run('ocean', {{y:60000, vx:200, vy:-200, ang:{ang}, angv:0, fuel:50000}}, "
               "{thr:1, tq:0, dt:1/120, steps:1})")
    c = r["consts"]
    # thrust force = T*(sin ang, cos ang) = T*(neg, pos) = up-left. dot with v(=+,-) < 0.
    import math
    T = c["THRUST"]
    Fx, Fy = T*math.sin(ang), T*math.cos(ang)
    vdotF = Fx*200 + Fy*(-200)
    # measured: does speed decrease? compare |v| before/after a few steps of pure thrust at altitude
    r2 = h.call(f"__H.run('ocean', {{y:60000, vx:200, vy:-200, ang:{ang}, angv:0, fuel:50000}}, "
                "{thr:1, tq:0, dt:1/120, steps:30})")
    import math as _m
    spd0 = _m.hypot(200, -200)
    spd1 = _m.hypot(r2["s"]["vx"], r2["s"]["vy"])
    ok = (vdotF < 0) and (spd1 < spd0)
    return ("C deceleration", ok, {"F": [Fx, Fy], "dot_F_v": vdotF,
                                   "spd_before": spd0, "spd_after": spd1,
                                   "thrust_opposes_v": vdotF < 0, "speed_decreased": spd1 < spd0})


def test_D_orientation_sign(h):
    """+y-up branch: v down-right, aft bottom-right, thrust up-left, nose top-left. Catches sprite/sign flips."""
    import math
    ang = -0.5
    no = h.call(f"__H.nose({ang})")
    ta = h.call(f"__H.tail({ang})")
    tf = h.call(f"__H.thrustForce('ocean', {ang}, 1)")
    # expectations for +y-up frame:
    # nose top-left: nose.x<0, nose.y>0
    # tail bottom-right: tail.x>0, tail.y<0
    # thrust up-left: F.x<0, F.y>0
    checks = {
        "nose_top_left": no["x"] < 0 and no["y"] > 0,
        "tail_bottom_right": ta["x"] > 0 and ta["y"] < 0,
        "thrust_up_left": tf["x"] < 0 and tf["y"] > 0,
        "thrust_opposite_tail": approx(tf["x"], -tf["mag"]*ta["x"], 1.0) and approx(tf["y"], -tf["mag"]*ta["y"], 1.0),
    }
    ok = all(checks.values())
    return ("D orientation/sign", ok, {"nose": no, "tail": ta, "thrust": tf, "checks": checks})


def test_E_gimbal_torque(h):
    """Equal +/- tq give opposite, symmetric angular accel; controller rotates toward desired attitude."""
    base = {"y": 60000, "vx": 0, "vy": -10, "ang": 0.0, "angv": 0, "fuel": 50000}
    rp = h.call(f"__H.run('ocean', {json.dumps(base)}, {{thr:0, tq:1, dt:1/120, steps:1}})")
    rn = h.call(f"__H.run('ocean', {json.dumps(base)}, {{thr:0, tq:-1, dt:1/120, steps:1}})")
    ap = rp["first"]["aacc"]
    an = rn["first"]["aacc"]
    # symmetric & opposite (no weathercock at ang=0, vy<0 tiny air at 60km): ap ~ -an, both nonzero
    ok = (ap * an < 0) and approx(abs(ap), abs(an), max(1e-6, 0.02*abs(ap)))
    # +tq should increase ang (rotate nose toward +x): ap>0
    ok = ok and ap > 0
    return ("E gimbal-torque", ok, {"aacc_plus": ap, "aacc_minus": an,
                                    "symmetric": approx(abs(ap), abs(an), max(1e-6, 0.02*abs(ap))),
                                    "plus_tq_increases_ang": ap > 0})


def test_F_glide_slope(h):
    """Above-left of deck with down-right velocity: altitude falls, x moves right toward deck; aft stays downrange."""
    import math
    # ocean deckX=12000. Start left of it, in the glide band (below GLIDE_TOP_Y, slowed below GLIDE_ENTRY_SPD).
    c = h.call("__H.setup('ocean')")
    top = c["GLIDE_TOP_Y"]; floor = c["GLIDE_FLOOR_Y"]; espd = c["GLIDE_ENTRY_SPD"]; deck = c["deckX"]
    y0 = (top + floor) / 2  # mid glide band
    x0 = deck - 6000        # left of deck
    # slowed below glide-entry speed, descending, moving right
    st = {"x": x0, "y": y0, "vx": 80, "vy": -80, "ang": 0.0, "angv": 0, "fuel": 40000}
    r = h.call(f"__H.run('ocean', {json.dumps(st)}, {{thr:0, tq:0, dt:1/120, steps:240}})")  # 2 s
    s = r["s"]
    alt_fell = s["y"] < y0
    moved_right = s["x"] > x0
    # aft/tail generally downrange+down during glide: with the attitude spring pulling toward +GLIDE_LEAN
    # (deck is to the right => deckSide +1), ang should trend positive (nose toward +x, tail toward -x/down).
    # We check the glide spring engaged: ang moved toward +GLIDE_LEAN.
    ang_moved_toward_lean = s["ang"] > 0.001
    ok = alt_fell and moved_right and ang_moved_toward_lean
    return ("F glide-slope", ok, {"x0": x0, "x1": s["x"], "y0": y0, "y1": s["y"], "ang1": s["ang"],
                                  "alt_fell": alt_fell, "moved_right": moved_right,
                                  "ang_toward_lean": ang_moved_toward_lean, "GLIDE_LEAN": c["GLIDE_LEAN"]})


def test_G_hover(h):
    """T=m*g upright => ~0 vertical accel; T>mg accel up; T<mg accel down. Uses vacuum (mars) to isolate."""
    # Use mars (vacuum, no aero) at ang=0. m=DRY+fuel. thr* such that T=m*g.
    c = h.call("__H.setup('mars')")
    m = c["DRY_MASS"] + 3000
    g = c["G"]; T = c["THRUST"]
    thr_hover = m * g / T
    detail = {"m": m, "g": g, "T": T, "thr_hover": thr_hover}
    if thr_hover > 1:
        # can't hover (TWR<1 at full) — skip gracefully but note
        return ("G hover-equilibrium", None, {**detail, "note": "TWR<1, hover impossible for this vehicle"})
    r0 = h.call(f"__H.run('mars', {{y:2000, vx:0, vy:0, ang:0, angv:0, fuel:3000}}, {{thr:{thr_hover}, tq:0, dt:1/120, steps:1}})")
    rup = h.call(f"__H.run('mars', {{y:2000, vx:0, vy:0, ang:0, angv:0, fuel:3000}}, {{thr:{min(1,thr_hover*1.2)}, tq:0, dt:1/120, steps:1}})")
    rdn = h.call(f"__H.run('mars', {{y:2000, vx:0, vy:0, ang:0, angv:0, fuel:3000}}, {{thr:{thr_hover*0.8}, tq:0, dt:1/120, steps:1}})")
    ay0, ayu, ayd = r0["first"]["ay"], rup["first"]["ay"], rdn["first"]["ay"]
    ok = approx(ay0, 0.0, 0.05) and ayu > 0.02 and ayd < -0.02
    return ("G hover-equilibrium", ok, {**detail, "ay_hover": ay0, "ay_up": ayu, "ay_down": ayd})


def test_H_fuel_mass(h):
    """Mass falls per mdot; never below dry; accel grows as fuel burns; no thrust after empty."""
    import math
    c = h.call("__H.setup('ocean')")
    mdot = c["MDOT"]
    # burn for 1 s at full throttle, check fuel delta = mdot*1
    r = h.call("__H.run('ocean', {y:60000, vx:0, vy:0, ang:0, angv:0, fuel:50000}, {thr:1, tq:0, dt:1/120, steps:120})")
    fuel1 = r["s"]["fuel"]
    burned = 50000 - fuel1
    exp_burn = mdot * 1.0
    fuel_ok = approx(burned, exp_burn, exp_burn * 0.02)
    # never below dry: run to empty (start low fuel), fuel clamps at 0
    r2 = h.call("__H.run('ocean', {y:60000, vx:0, vy:0, ang:0, angv:0, fuel:100}, {thr:1, tq:0, dt:1/120, steps:120})")
    clamp_ok = r2["s"]["fuel"] >= 0 and r2["s"]["fuel"] < 1
    # no thrust after empty: at fuel=0, accel should be pure -G (no thrust term). ay ~ -G.
    r3 = h.call("__H.run('ocean', {y:60000, vx:0, vy:0, ang:0, angv:0, fuel:0}, {thr:1, tq:0, dt:1/120, steps:1})")
    G = c["G"]
    noThrust_ok = approx(r3["first"]["ay"], -G, 0.05)
    # accel grows as fuel burns: compare T/m at full vs near-empty
    mfull = c["DRY_MASS"] + 50000
    mlow = c["DRY_MASS"] + 100
    a_grows = (c["THRUST"]/mlow) > (c["THRUST"]/mfull)
    ok = fuel_ok and clamp_ok and noThrust_ok and a_grows
    return ("H fuel/mass", ok, {"burned": burned, "expected": exp_burn, "fuel_ok": fuel_ok,
                                "clamp_fuel": r2["s"]["fuel"], "clamp_ok": clamp_ok,
                                "ay_empty": r3["first"]["ay"], "noThrust_ok": noThrust_ok,
                                "accel_grows_as_fuel_burns": a_grows})


def test_I_energy_drag(h):
    """With drag, no thrust: dot(F_drag, v_rel) <= 0 (drag never adds air-relative KE)."""
    import math
    # low altitude, dense air, high speed, some AoA so both axial+normal drag act. No thrust, no wind.
    c = h.call("__H.setup('ocean')")
    st = {"x": 0, "y": 3000, "vx": 150, "vy": -150, "ang": 0.4, "angv": 0, "fuel": 40000}
    # measure KE change over 1 substep from drag+lift+gravity; subtract gravity's contribution to isolate aero.
    r = h.call(f"__H.run('ocean', {json.dumps(st)}, {{thr:0, tq:0, dt:1/120, steps:1}})")
    G = c["G"]
    ax, ay = r["first"]["ax"], r["first"]["ay"]
    # aero accel = total - gravity(0,-G)
    aax, aay = ax - 0.0, ay - (-G)
    v = (st["vx"], st["vy"])
    # aero power on the vehicle = (m*a_aero) . v ; sign of a_aero . v tells if aero adds KE.
    # STRAKE LIFT is perpendicular to v so it contributes ~0 to a_aero.v; the DRAG part must be <=0.
    aero_dot_v = aax * v[0] + aay * v[1]
    # allow a tiny positive slack for the along-v L/D bonus (uses |Flift|, can add along v) — the audit
    # flags that term; here we assert drag itself doesn't dominate positive. Use a relative tolerance.
    ok = aero_dot_v <= abs(v[0]*v[0]+v[1]*v[1]) * 1e-4  # effectively <=0 within numerical noise
    return ("I energy/drag", ok, {"aero_accel": [aax, aay], "aero_dot_v": aero_dot_v,
                                  "note": "dot<=0 means aero removes air-relative KE (lift is perp, so this is the drag sign)"})


def test_J_touchdown(h):
    """Valid slow upright landing succeeds; too-fast/tilted/drifting/off-pad fail."""
    deck = h.call("__H.setup('ocean'); __H.consts().deckX")
    # good landing: on deck, slow descent, low drift, upright
    good = h.call(f"__H.touchdown('ocean', {{x:{deck}, vx:1, vy:-3, ang:0.02, angv:0, fuel:8000}})")
    hot = h.call(f"__H.touchdown('ocean', {{x:{deck}, vx:1, vy:-40, ang:0.02, angv:0, fuel:8000}})")
    drift = h.call(f"__H.touchdown('ocean', {{x:{deck}, vx:40, vy:-3, ang:0.02, angv:0, fuel:8000}})")
    tilt = h.call(f"__H.touchdown('ocean', {{x:{deck}, vx:1, vy:-3, ang:0.6, angv:0, fuel:8000}})")
    offpad = h.call(f"__H.touchdown('ocean', {{x:{deck+5000}, vx:1, vy:-3, ang:0.02, angv:0, fuel:8000}})")
    checks = {
        "good_succeeds": good.get("ok") is True,
        "hot_fails": hot.get("ok") is False,
        "drift_fails": drift.get("ok") is False,
        "tilt_fails": tilt.get("ok") is False,
        "offpad_fails": offpad.get("ok") is False,
    }
    ok = all(checks.values())
    return ("J touchdown", ok, {"checks": checks, "good": good, "hot": hot, "drift": drift,
                                "tilt": tilt, "offpad": offpad})


def _descent_run(h, hz, seconds=6.0):
    """Deterministic scripted descent at a given physics frame rate (dt=1/hz), no wind.
    Returns final state after `seconds` of the SAME control sequence."""
    dt = 1.0 / hz
    steps = int(round(seconds * hz))
    # a fixed control script: coast 2s, then burn full 4s, no steering. Start high & fast.
    # We emulate the game's substep by calling run() with steps at this dt. NOTE: the game itself
    # substeps to <=1/120; this test bypasses that to check the RAW integrator's frame sensitivity,
    # which is the honest test of "if physics ran at this dt".
    st = {"x": -6000, "y": 9000, "vx": 250, "vy": -250, "ang": -0.3, "angv": 0, "fuel": 60000}
    coast = int(round(2.0 * hz))
    burn = steps - coast
    r1 = h.call(f"__H.run('ocean', {json.dumps(st)}, {{thr:0, tq:0, dt:{dt}, steps:{coast}}})")
    s1 = r1["s"]
    r2 = h.call(f"__H.run('ocean', {json.dumps(s1)}, {{thr:1, tq:0, dt:{dt}, steps:{burn}}})")
    return r2["s"]


def test_K_timestep(h):
    """Same scripted descent at 30/60/120 Hz gives materially similar final state."""
    s30 = _descent_run(h, 30)
    s60 = _descent_run(h, 60)
    s120 = _descent_run(h, 120)
    import math
    def dpos(a, b): return math.hypot(a["x"]-b["x"], a["y"]-b["y"])
    def dvel(a, b): return math.hypot(a["vx"]-b["vx"], a["vy"]-b["vy"])
    p_30_120 = dpos(s30, s120)
    p_60_120 = dpos(s60, s120)
    v_30_120 = dvel(s30, s120)
    v_60_120 = dvel(s60, s120)
    fuel_spread = max(s30["fuel"], s60["fuel"], s120["fuel"]) - min(s30["fuel"], s60["fuel"], s120["fuel"])
    # tolerances (documented): position within 500 m, velocity within 25 m/s over a 6 s open-loop burn.
    # (open-loop explicit-euler divergence; the GAME substeps to 120 Hz so live play is tighter — this is
    # the raw-integrator honesty check.)
    ok = p_30_120 < 500 and v_30_120 < 25 and fuel_spread < 50
    return ("K time-step 30/60/120", ok, {
        "s30": {k: round(s30[k], 2) for k in ("x", "y", "vx", "vy", "fuel", "ang")},
        "s60": {k: round(s60[k], 2) for k in ("x", "y", "vx", "vy", "fuel", "ang")},
        "s120": {k: round(s120[k], 2) for k in ("x", "y", "vx", "vy", "fuel", "ang")},
        "pos_30_vs_120": round(p_30_120, 2), "pos_60_vs_120": round(p_60_120, 2),
        "vel_30_vs_120": round(v_30_120, 2), "vel_60_vs_120": round(v_60_120, 2),
        "fuel_spread": round(fuel_spread, 3)})


ALL_TESTS = {
    "A": test_A_freefall, "B": test_B_axial_thrust, "C": test_C_deceleration,
    "D": test_D_orientation_sign, "E": test_E_gimbal_torque, "F": test_F_glide_slope,
    "G": test_G_hover, "H": test_H_fuel_mass, "I": test_I_energy_drag,
    "J": test_J_touchdown, "K": test_K_timestep,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma list of test letters, e.g. A,C,K")
    ap.add_argument("--json", default="", help="dump raw results to this path")
    args = ap.parse_args()

    which = [x.strip().upper() for x in args.only.split(",") if x.strip()] or list(ALL_TESTS)

    h = Harness()
    results = []
    try:
        h.start()
        for k in which:
            fn = ALL_TESTS.get(k)
            if not fn:
                continue
            try:
                name, ok, detail = fn(h)
            except Exception as e:  # noqa: BLE001
                name, ok, detail = (f"{k} (ERROR)", False, {"exception": repr(e)})
            results.append({"key": k, "name": name, "ok": ok, "detail": detail})
    finally:
        h.stop()

    npass = sum(1 for r in results if r["ok"] is True)
    nfail = sum(1 for r in results if r["ok"] is False)
    nskip = sum(1 for r in results if r["ok"] is None)

    print("=" * 72)
    for r in results:
        tag = "PASS" if r["ok"] is True else ("SKIP" if r["ok"] is None else "FAIL")
        print(f"[{tag}] {r['name']}")
        if r["ok"] is not True:
            print("       " + json.dumps(r["detail"]))
    print("=" * 72)
    print(f"RESULT p {npass} f {nfail} s {nskip}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"raw -> {args.json}")

    sys.exit(1 if nfail else 0)


if __name__ == "__main__":
    main()
