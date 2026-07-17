"""
Glide crossrange-authority probe for the NG booster.

Answers, from the REAL stepPhysics (no trusting comments):
  1. As a function of lean angle, what is the CROSSRANGE accel (perpendicular to
     velocity) vs the ALONG-track (braking) accel? Where does steering peak, and
     where does it turn into pure braking (wing stall, β->90)?
  2. Is the lift CLAMP-limited (cap hit) or COEFFICIENT-limited (CL/CL_K too small)?
  3. Over a FULL glide, how far does the landing-X move between a modest left lean
     and a modest right lean? (the real 'how visible is the wing' number)
  4. Does the sign match the user's want (lean LEFT -> land RIGHT) across the
     USEFUL lean band, not just at one angle?

Run: py testing/glide_authority_probe.py
"""
import os
import sys
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from physics_harness import Harness  # noqa: E402


def force_breakdown(h, mode, x, y, vx, vy, ang_deg):
    """One real substep at a pinned angle; decompose the measured accel into
    along-velocity (braking, -) and crossrange (steering) components."""
    ang = ang_deg * math.pi / 180.0
    js = """
    (function(){
      __H.setup(%r); env={windBase:0,windGust:0,windPhase:0,gateX:0};
      SHIP_MODE=false; ASCENT_MODE=false;
      var s={x:%f,y:%f,vx:%f,vy:%f,ang:%f,angv:0,fuel:50000};
      var pvx=s.vx, pvy=s.vy, dt=1/120;
      stepPhysics(s, dt, 0, 0, 0);
      var ax=(s.vx-pvx)/dt, ay=(s.vy-pvy)/dt;
      return {ax:ax, ay:ay, vx:pvx, vy:pvy};
    })()
    """ % (mode, x, y, vx, vy, ang)
    r = h.chrome.eval(js)
    spd = math.hypot(r["vx"], r["vy"]) or 1e-9
    # unit along velocity, and +90 CCW crossrange
    ux, uy = r["vx"] / spd, r["vy"] / spd
    cx, cy = -uy, ux
    # remove gravity (-G) so we see AERO only: gravity is purely -y
    axa = r["ax"]
    aya = r["ay"] + h.chrome.eval("G")   # add back g to isolate non-gravity accel
    along = axa * ux + aya * uy          # + = prograde (speeds up), - = braking
    cross = axa * cx + aya * cy          # crossrange steering accel (signed)
    return {"along": along, "cross": cross, "spd": spd}


def full_glide_landing_x(h, mode, x0, y0, vx0, vy0, lean_deg, secs=18.0):
    """Integrate a full glide holding a fixed lean; return where it ends up (x at floor)."""
    ang = lean_deg * math.pi / 180.0
    js = """
    (function(){
      __H.setup(%r); env={windBase:0,windGust:0,windPhase:0,gateX:0};
      SHIP_MODE=false; ASCENT_MODE=false;
      var s={x:%f,y:%f,vx:%f,vy:%f,ang:%f,angv:0,fuel:50000};
      var dt=1/120, n=%d, ang=%f, floor=(typeof GLIDE_FLOOR_Y!=='undefined'?GLIDE_FLOOR_Y:2100);
      for(var i=0;i<n;i++){ s.ang=ang; s.angv=0; stepPhysics(s,dt,0,0,0); if(s.y<=floor||s.y<=0)break; }
      return {x:s.x,y:s.y,vx:s.vx,vy:s.vy};
    })()
    """ % (mode, x0, y0, vx0, vy0, ang, int(secs / (1 / 120)), ang)
    return h.chrome.eval(js)


def main():
    h = Harness(port=9377)
    h.start()
    try:
        c = h.chrome.eval("__H.setup('ocean')")
        top, floor, espd, deck = c["GLIDE_TOP_Y"], c["GLIDE_FLOOR_Y"], c["GLIDE_ENTRY_SPD"], c["deckX"]
        lean = c["GLIDE_LEAN"] * 180 / math.pi
        print("ocean: glide band %d-%d m, entry_spd %d, deckX %d, GLIDE_LEAN %.1f deg" % (floor, top, espd, deck, lean))
        print("       CL_K=%s GLIDE_LIFT_BOOST=%s GLIDE_CLAMP_G=%s LIFT_CLAMP_G=%s GLIDE_K=%s"
              % (c["CL_K"], h.chrome.eval("typeof GLIDE_LIFT_BOOST!=='undefined'?GLIDE_LIFT_BOOST:null"),
                 h.chrome.eval("typeof GLIDE_CLAMP_G!=='undefined'?GLIDE_CLAMP_G:null"),
                 c.get("LIFT_CLAMP_G", h.chrome.eval("typeof LIFT_CLAMP_G!=='undefined'?LIFT_CLAMP_G:null")),
                 h.chrome.eval("typeof GLIDE_K!=='undefined'?GLIDE_K:null")))

        # Representative glide state: near top of band, at glide-entry speed, moving downrange (right), descending.
        y0 = top - 400
        x0 = deck - 6000
        # split entry speed into a downrange + descent that sums near espd
        vx0, vy0 = 180.0, -150.0
        spd0 = math.hypot(vx0, vy0)
        print("\nstate: x=%d y=%d vx=%d vy=%d spd=%.0f (glide-entry ~%d)\n" % (x0, y0, vx0, vy0, spd0, espd))

        print("=== crossrange (steering) vs along (braking) accel by lean angle ===")
        print(" (cross>0 pushes +90CCW of velocity; velocity is down-right so +cross ~ up/right)")
        print("  lean   cross a   along a   |ratio steer/brake|")
        for ld in (-40, -30, -20, -10, 0, 10, 20, 30, 40):
            fb = force_breakdown(h, "ocean", x0, y0, vx0, vy0, ld)
            ratio = abs(fb["cross"]) / (abs(fb["along"]) + 1e-9)
            print("  %+4d   %+7.3f   %+7.3f   %.2f" % (ld, fb["cross"], fb["along"], ratio))

        # Is lift clamp-limited? Instrument Flift vs cap at the peak-authority angle.
        peakjs = """
        (function(){
          __H.setup('ocean'); env={windBase:0,windGust:0,windPhase:0,gateX:0}; SHIP_MODE=false; ASCENT_MODE=false;
          var s={x:%f,y:%f,vx:%f,vy:%f,ang:0,angv:0,fuel:50000};
          var out=[];
          for(var ld=-40;ld<=40;ld+=10){
            var ang=ld*Math.PI/180; s.ang=ang;
            var r=rho(s.y), spd=Math.hypot(s.vx,s.vy);
            var axx=Math.sin(ang),axy=Math.cos(ang),nxx=axy,nxy=-axx;
            var vno=s.vx*nxx+s.vy*nxy, sinB=Math.max(-1,Math.min(1,vno/spd)), cosB=Math.sqrt(Math.max(0,1-sinB*sinB));
            var CL=sinB*cosB, m=DRY_MASS+s.fuel;
            var top=GLIDE_TOP_Y,floor=GLIDE_FLOOR_Y,espd=GLIDE_ENTRY_SPD;
            var inGlide = s.vy<0 && s.y<top && s.y>floor && spd<espd;
            var atmoT=Math.min(1,Math.max(0,(ENTRY_Y+2500-s.y)/2200));
            var clk=CL_K, lb=inGlide?GLIDE_LIFT_BOOST:1;
            var Flift=clk*r*spd*spd*CL*atmoT*lb;
            var cap=(inGlide?GLIDE_CLAMP_G:LIFT_CLAMP_G)*m*G;
            out.push({lean:ld,inGlide:inGlide,Flift:Math.round(Flift),cap:Math.round(cap),clamped:(Math.abs(Flift)>=cap),CL:+CL.toFixed(3),accel:+(Math.min(Math.abs(Flift),cap)/m).toFixed(3)});
          }
          return out;
        })()
        """ % (x0, y0, vx0, vy0)
        print("\n=== is lift clamp-limited? (Flift vs cap at each lean) ===")
        for row in h.chrome.eval(peakjs):
            print("  lean %+4d  inGlide=%s  CL=%+.3f  Flift=%8d  cap=%8d  clamped=%s  lift_accel=%.3f m/s^2"
                  % (row["lean"], row["inGlide"], row["CL"], row["Flift"], row["cap"], row["clamped"], row["accel"]))

        print("\n=== FULL-GLIDE landing-X shift (the 'how visible' number) ===")
        base = full_glide_landing_x(h, "ocean", x0, y0, vx0, vy0, 0)
        for ld in (-30, -20, -10, 0, 10, 20, 30):
            r = full_glide_landing_x(h, "ocean", x0, y0, vx0, vy0, ld)
            d = r["x"] - base["x"]
            print("  lean %+4d deg -> landing x=%d  (%+d m vs neutral)  final y=%d" % (ld, r["x"], d, r["y"]))
        rL = full_glide_landing_x(h, "ocean", x0, y0, vx0, vy0, -20)
        rR = full_glide_landing_x(h, "ocean", x0, y0, vx0, vy0, 20)
        print("\n  lean LEFT(-20) vs RIGHT(+20): total landing-X spread = %d m" % (rL["x"] - rR["x"]))
        print("  user wants lean LEFT -> land RIGHT: %s"
              % ("YES (L lands right of R)" if rL["x"] > rR["x"] else "NO / INVERTED"))
    finally:
        h.chrome.close()


if __name__ == "__main__":
    main()
