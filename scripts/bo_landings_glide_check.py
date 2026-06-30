"""
CHECKER-1 (physics realism): faithful port of stepPhysics descent to validate the New Glenn
fin+strake model. Confirms (a) strakes stretch the zero-input glide vs the old grid-fin model,
(b) the path stays stable (no NaN/runaway), (c) steering authority can shift the impact point.
Atmosphere/wind mirror the game (rho0=1.225, Hscale=8500; wind small). Units: m, s, rad.
"""
import math

g0 = 9.80665

def rho(y, RHO0=1.225, HSCALE=8500.0):
    return RHO0 * math.exp(-max(0.0, y) / HSCALE)

def run(model, DRY, FUEL, THRUST, MDOT, CDA_AX, CDA_LAT, G,
        x0, y0, vx0, vy0, ang0, ENTRY_Y=8500.0,
        FIN_K=14.0, STRAKE_K=26.0, finD=0.0, hold_ang=None, dt=0.1, tmax=400.0):
    s = dict(x=x0, y=y0, vx=vx0, vy=vy0, ang=ang0, angv=0.0, fuel=FUEL)
    TORQUE = 1.5
    t = 0.0
    while s['y'] > 0 and t < tmax:
        m = DRY + s['fuel']
        ax, ay = 0.0, -G
        thr = 0.0  # gliding, no burn (we test the unpowered descent shape)
        r = rho(s['y'])
        rvx, rvy = s['vx'], s['vy']
        axx, axy = math.sin(s['ang']), math.cos(s['ang'])
        nxx, nxy = axy, -axx
        vax = rvx*axx + rvy*axy
        vno = rvx*nxx + rvy*nxy
        spd = math.hypot(rvx, rvy)
        atmoT = min(1.0, max(0.0, (ENTRY_Y + 2500 - s['y']) / 2200.0))
        Fax = -0.5*r*CDA_AX*abs(vax)*vax
        Fno = -0.5*r*CDA_LAT*abs(vno)*vno
        ax += (Fax*axx + Fno*nxx)/m
        ay += (Fax*axy + Fno*nxy)/m
        if r > 0:
            if model == 'grid' and finD:        # OLD grid-fin lift (coeff 20), no strake
                Ffin = 20*r*spd*spd*finD*atmoT
                ax += Ffin*nxx/m; ay += Ffin*nxy/m
            elif model == 'ng':                 # NEW fins + always-on strakes
                if finD:
                    Ffin = FIN_K*r*spd*spd*finD*atmoT
                    ax += Ffin*nxx/m; ay += Ffin*nxy/m
                aoa = (vno/spd) if spd > 1 else 0.0
                Fstrake = STRAKE_K*r*spd*spd*aoa*atmoT
                ax += Fstrake*nxx/m; ay += Fstrake*nxy/m
        # rotation
        if hold_ang is not None:
            s['ang'] = hold_ang; s['angv'] = 0.0
        else:
            aacc = -s['angv']*(0.18 + r*spd*0.0024*atmoT)
            if model == 'ng':
                aacc -= 6e-5*r*spd*vno*atmoT*(1 if s['vy'] < 0 else 0.4)
            else:
                alignW = (max(0.0, 1 - (abs(vno)/spd if spd > 1 else 0)))**2
                aacc -= 8.5e-5*r*spd*vno*atmoT*alignW*(1 if s['vy'] < 0 else 0.25)
            s['angv'] += aacc*dt
            s['ang'] += s['angv']*dt
        s['vx'] += ax*dt; s['vy'] += ay*dt
        s['x'] += s['vx']*dt; s['y'] += s['vy']*dt
        if math.isnan(s['x']) or math.isnan(s['ang']):
            return dict(impact=float('nan'), nan=True, t=t)
        t += dt
    return dict(impact=s['x'], vy=s['vy'], vx=s['vx'], ang=s['ang'], t=t, nan=False)

# 7x2 booster descent params (from applyModeParams ocean branch)
P = dict(DRY=180000, FUEL=70000, THRUST=7.4e6, MDOT=2219, CDA_AX=150, CDA_LAT=360, G=9.81)
# Start: tail-first lean at altitude, some downrange velocity (like the ocean spawn)
start = dict(x0=0.0, y0=8000.0, vx0=-120.0, vy0=-40.0, ang0=0.35, ENTRY_Y=8500.0)

print("=== 7x2: glide reach (zero stick), OLD grid-fin vs NEW fins+strakes ===")
old = run('grid', finD=0.0, **P, **start)
new = run('ng',   finD=0.0, **P, **start)
print(f"OLD grid (no lift at zero stick): impact x = {old['impact']:.0f} m, descent {old['t']:.0f} s, stable={not old['nan']}")
print(f"NEW fins+strakes (zero stick):    impact x = {new['impact']:.0f} m, descent {new['t']:.0f} s, stable={not new['nan']}")
print(f"strake glide extends downrange by {new['impact']-old['impact']:+.0f} m at zero input")

print("\n=== 7x2: steering authority (hold fin left vs right) ===")
left  = run('ng', finD=-1.0, **P, **start)
right = run('ng', finD=+1.0, **P, **start)
print(f"fin = -1 -> impact {left['impact']:.0f} m ; fin = +1 -> impact {right['impact']:.0f} m")
print(f"controllable spread = {abs(right['impact']-left['impact']):.0f} m")

print("\n=== 9x4: higher-energy steep entry reachable? (heavier, faster, higher) ===")
P9 = dict(DRY=210000, FUEL=70000, THRUST=8.4e6, MDOT=2519, CDA_AX=165, CDA_LAT=380, G=9.81)
start9 = dict(x0=0.0, y0=11500.0, vx0=-230.0, vy0=-70.0, ang0=0.45, ENTRY_Y=8500.0)
g9_none = run('ng', finD=0.0, **P9, **start9)
g9_pull = run('ng', finD=+1.0, **P9, **start9)
print(f"9x4 zero stick: impact {g9_none['impact']:.0f} m ; full strake-steer: impact {g9_pull['impact']:.0f} m")
print(f"9x4 glide-steer range = {abs(g9_pull['impact']-g9_none['impact']):.0f} m, stable={not g9_none['nan'] and not g9_pull['nan']}")

print("\n=== stability: 420-step predictor-style run, check no NaN ===")
chk = run('ng', finD=0.5, hold_ang=None, **P, **start, dt=0.3, tmax=200)
print(f"impact {chk['impact']:.0f} m, final ang {chk['ang']:.2f} rad, NaN={chk['nan']}")
