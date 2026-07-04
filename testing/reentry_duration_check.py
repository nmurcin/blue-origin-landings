"""
reentry_duration_check.py — Pick reentry-phase-lengthening params from DATA, not by eye.

The pilot wants the reentry phase LONGER, with slower speeds ("drag really increases here, speeds a
lot slower in real life"). The phase length = time from control-handoff (spawn) until GLIDE takes over
(spd < GLIDE_ENTRY_SPD=260 AND y < GLIDE_TOP_Y). The knobs:
  - spawn altitude y0        (taller corridor above the glide band = more time in reentry)
  - entry interface ENTRY_Y  (raising it moves aero/decel onset higher -> longer decel regime)
  - drag scale               (more drag = slower speeds = the "slower in real life" feel)
  - spawn speed              (slower entry = longer, calmer descent)

Passive engine-first plunge (no player burn) as a conservative proxy for phase duration. Mirrors
stepPhysics' NG axial-drag model. GLIDE_TOP_Y stays 8300 (glide band unchanged).
"""
import math

G=9.81; DRY=220000.0; CDA_AX=95.0; RHO0=1.225; HSCALE=8500.0; GLIDE_TOP=8300.0

def rho(y): return RHO0*math.exp(-max(0.0,y)/HSCALE)

def sim(entry_y, y0, vx0, vy0, drag_mul=1.0, ramp=12000.0, dt=0.05):
    x=0.0; y=y0; vx=vx0; vy=-abs(vy0); m=DRY+20000.0   # vy is DOWNWARD (negative) — booster is descending
    t=0.0; t_regime=0.0; t_to_glide=None; peak_g=0.0; spd_at_glidetop=None
    while y>0 and t<400:
        spd=math.hypot(vx,vy) or 1e-9
        axDragF=min(1.0,max(0.4, 1-(y-entry_y)/ramp))
        r=rho(y)
        Fax=0.5*r*CDA_AX*drag_mul*axDragF*spd*spd
        ax=-Fax*vx/spd/m; ay=-G-Fax*vy/spd/m
        peak_g=max(peak_g,(Fax/m)/G)
        if y>entry_y-500 and spd>250: t_regime+=dt
        if spd_at_glidetop is None and y<=GLIDE_TOP: spd_at_glidetop=spd
        if t_to_glide is None and spd<260 and y<GLIDE_TOP: t_to_glide=t
        vx+=ax*dt; vy+=ay*dt; x+=vx*dt; y+=vy*dt; t+=dt
    return dict(t_regime=round(t_regime,1), t_to_glide=(round(t_to_glide,1) if t_to_glide else None),
                peak_g=round(peak_g,1), spd_glidetop=round(spd_at_glidetop) if spd_at_glidetop else None)

CASES = [
    ("CURRENT (baseline)",           8500, 11200, 470, 510, 1.0),
    # ENTRY_Y FIXED at 8500 (no heat/glide blast radius) — lengthen via higher/slower spawn + drag:
    ("F: spawn 15k, same spd",       8500, 15000, 470, 510, 1.0),
    ("G: spawn 15k, slower",         8500, 15000, 400, 440, 1.0),
    ("H: spawn 15k slower +drag1.5", 8500, 15000, 400, 440, 1.5),
    ("I: spawn 16k slower +drag1.6", 8500, 16000, 380, 420, 1.6),
    ("J: spawn 17k slower +drag1.8", 8500, 17000, 360, 400, 1.8),
]
print(f"{'case':32} {'reentry_regime_s':>16} {'spawn->glide_s':>15} {'peak_g':>7} {'spd@8.3km':>10}")
for name,ey,y0,vx,vy,dm in CASES:
    r=sim(ey,y0,vx,vy,dm)
    print(f"{name:32} {r['t_regime']:>16} {str(r['t_to_glide']):>15} {r['peak_g']:>7} {str(r['spd_glidetop']):>10}")
print("\nGoal: 'spawn->glide_s' clearly LONGER than baseline, speeds slower (lower spd@8.3km),")
print("peak_g sane (<~6g). Pick the calmest case that ~2-3x the baseline reentry time.")
