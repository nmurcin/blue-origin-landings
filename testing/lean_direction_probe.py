"""
Lean-direction probe: measure the ACTUAL trajectory deflection when the NG booster
leans left vs right during the glide phase, and (separately) confirm MK1/mars is a
vacuum descent where leaning does nothing aerodynamic.

The user's mental model: "when the rocket leans LEFT it should act like a wing and
push the landing point to the RIGHT, and vice versa." We measure what the REAL
stepPhysics does — no trusting comments (this codebase has a lift-sign history).

Method: park the booster in the glide band, descending, moving downrange, then HOLD a
fixed body angle (tilt left / neutral / right) and integrate the real stepPhysics for
a few seconds with steering torque disabled but the angle pinned. Compare the final
horizontal position (proxy for where the landing point moves).

Run: py testing/lean_direction_probe.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from physics_harness import Harness  # noqa: E402


def integrate_pinned(h, mode, x0, y0, vx0, vy0, ang_deg, secs=4.0, dt=1 / 120):
    """Integrate real stepPhysics holding body angle FIXED at ang_deg (no torque),
    thr=0 (pure glide). Returns final state. We re-pin ang each substep so we isolate
    the AERO force produced by holding that attitude, not the rotation dynamics."""
    ang = ang_deg * 3.141592653589793 / 180.0
    n = int(secs / dt)
    js = """
    (function(){
      __H.setup(%r);
      env = { windBase:0, windGust:0, windPhase:0, gateX:0 };
      SHIP_MODE = (%r==='mars'); ASCENT_MODE=false;
      var s = { x:%f, y:%f, vx:%f, vy:%f, ang:%f, angv:0, fuel:50000 };
      var dt=%f, n=%d, ang=%f;
      for (var i=0;i<n;i++){
        s.ang = ang; s.angv = 0;          // PIN attitude — isolate the aero of holding this lean
        stepPhysics(s, dt, 0, 0, 0);
        if (s.y <= 0) break;
      }
      return { x:s.x, y:s.y, vx:s.vx, vy:s.vy, ang:s.ang };
    })()
    """ % (mode, mode, x0, y0, vx0, vy0, ang, dt, n, ang)
    return h.chrome.eval(js)


def main():
    h = Harness(port=9366)
    h.start()
    try:
        c = h.chrome.eval("__H.setup('ocean')")
        top = c["GLIDE_TOP_Y"]
        floor = c["GLIDE_FLOOR_Y"]
        espd = c["GLIDE_ENTRY_SPD"]
        deck = c["deckX"]
        print("ocean glide band: floor=%s top=%s entry_spd=%s deckX=%s GLIDE_LEAN=%.3f rad (%.1f deg)"
              % (floor, top, espd, deck, c["GLIDE_LEAN"], c["GLIDE_LEAN"] * 180 / 3.14159))

        # Glide-band start: mid-band altitude, slowed below glide-entry speed, descending, moving RIGHT
        # (downrange toward the deck). x starts LEFT of the deck.
        y0 = (top + floor) / 2
        x0 = deck - 6000
        vx0 = 90.0     # moving right (downrange), below GLIDE_ENTRY_SPD when combined with vy
        vy0 = -70.0    # descending
        print("\nstart: x0=%.0f (deck-6000) y0=%.0f vx0=%.0f vy0=%.0f spd=%.0f\n"
              % (x0, y0, vx0, vy0, (vx0**2 + vy0**2) ** 0.5))

        print("=== OCEAN (NG 7x2) — hold a fixed lean, integrate the real glide ===")
        base = None
        for ang_deg in (-25, -10, 0, 10, 25):
            r = integrate_pinned(h, "ocean", x0, y0, vx0, vy0, ang_deg, secs=5.0)
            if base is None and ang_deg == 0:
                base = r["x"]
            print("  lean %+3d deg (nose %s): final x=%.0f  y=%.0f  vx=%.1f"
                  % (ang_deg, "LEFT/-x" if ang_deg < 0 else ("RIGHT/+x" if ang_deg > 0 else "neutral"),
                     r["x"], r["y"], r["vx"]))
        # interpret vs neutral
        rL = integrate_pinned(h, "ocean", x0, y0, vx0, vy0, -25, secs=5.0)
        rN = integrate_pinned(h, "ocean", x0, y0, vx0, vy0, 0, secs=5.0)
        rR = integrate_pinned(h, "ocean", x0, y0, vx0, vy0, 25, secs=5.0)
        print("\n  INTERPRETATION (ang uses body-axis: +ang leans nose toward +x/RIGHT):")
        print("   lean LEFT (-25):  final x %+.0f vs neutral  -> landing point moves %s"
              % (rL["x"] - rN["x"], "RIGHT (+x)" if rL["x"] > rN["x"] else "LEFT (-x)"))
        print("   lean RIGHT(+25):  final x %+.0f vs neutral  -> landing point moves %s"
              % (rR["x"] - rN["x"], "RIGHT (+x)" if rR["x"] > rN["x"] else "LEFT (-x)"))
        print("\n  USER WANTS: lean LEFT -> landing point RIGHT; lean RIGHT -> landing point LEFT.")
        want_left_right = (rL["x"] > rN["x"]) and (rR["x"] < rN["x"])
        print("  CURRENT CODE MATCHES USER'S WANT? %s" % ("YES" if want_left_right else "NO (INVERTED)"))

        print("\n=== MARS (Blue Moon MK1) — same test in vacuum ===")
        cm = h.chrome.eval("__H.setup('mars')")
        print("  mars RHO0=%s (0 => no air => no aero lift at all)" % cm["RHO0"])
        mL = integrate_pinned(h, "mars", 8000, 3000, -120, -40, -25, secs=5.0)
        mN = integrate_pinned(h, "mars", 8000, 3000, -120, -40, 0, secs=5.0)
        mR = integrate_pinned(h, "mars", 8000, 3000, -120, -40, 25, secs=5.0)
        print("  lean LEFT  final x=%.0f | neutral x=%.0f | lean RIGHT x=%.0f" % (mL["x"], mN["x"], mR["x"]))
        print("  spread L-vs-R = %.3f m (≈0 => leaning does NOTHING aerodynamic in vacuum, as expected)"
              % (mL["x"] - mR["x"]))
    finally:
        h.chrome.close()


if __name__ == "__main__":
    main()
