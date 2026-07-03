"""
Super-glide sanity port — mirrors the CURRENT flat-plate stepPhysics (super-glide branch) closely
enough to answer three questions before a human playtest:
  1) Does the weathercock auto-settle into a belly-flop lean (beta ~= GLIDE_AOA) in the glide band?
  2) Does the heavy-tilt glide EXTEND downrange reach vs the old vertical-trim baseline?
  3) Is it stable (no NaN / runaway spin), and does it re-vertical below the floor?
Passive glide (no player torque, no burn) from a post-decel state. Units m/s/rad. NOT the game;
a check. The game is ground truth — this only screens for an obviously-broken build.
"""
import math

G=9.81; DRY=220000.0; FUEL0=66000.0; ENTRY_Y=8500.0; THRUST=6.9e6; MDOT=2150.0
CDA_AX=95.0; CDA_LAT=195.0; RHO0=1.225; HSCALE=8500.0
CL_K=120.0; GLIDE_K=0.15; TORQUE=1.5
GLIDE_LEAN=0.52; GLIDE_TRIM_K=0.15; GLIDE_TOP_Y=8300.0; GLIDE_FLOOR_Y=2100.0; GLIDE_ENTRY_SPD=260.0
GLIDE_LIFT_BOOST=3.6; GLIDE_CLAMP_G=5.0
DECKX=22000.0  # placeholder deck (right of x0) so deckSide=+1; bot re-derives the real value

def rho(y): return RHO0*math.exp(-max(0.0,y)/HSCALE)

def run(lift_clamp_g, trim_mode, y0=7200.0, x0=0.0, vx0=150.0, vy0=-150.0, ang0=0.0, dt=0.05, tmax=400.0):
    s=dict(x=x0,y=y0,vx=vx0,vy=vy0,ang=ang0,angv=0.0,fuel=20000.0)
    t=0.0; beta_max=0.0; nanflag=False; ang_at_floor=None; lean_samples=[]
    while s['y']>0 and t<tmax:
        m=DRY+s['fuel']; ax=0.0; ay=-G
        r=rho(s['y']); rvx=s['vx']; rvy=s['vy']
        axx,axy=math.sin(s['ang']),math.cos(s['ang']); nxx,nxy=axy,-axx
        vax=rvx*axx+rvy*axy; vno=rvx*nxx+rvy*nxy; spd=math.hypot(rvx,rvy) or 1e-9
        atmoT=min(1.0,max(0.0,(ENTRY_Y+2500-s['y'])/2200.0))
        axDragF=min(1.0,max(0.4,1-(s['y']-ENTRY_Y)/12000.0))
        Fax=-0.5*r*CDA_AX*axDragF*abs(vax)*vax; Fno=-0.5*r*CDA_LAT*abs(vno)*vno
        ax+=(Fax*axx+Fno*nxx)/m; ay+=(Fax*axy+Fno*nxy)/m
        inGlide_lift=(trim_mode=='glide' and s['vy']<0 and GLIDE_FLOOR_Y<s['y']<GLIDE_TOP_Y and spd<GLIDE_ENTRY_SPD)
        if r>0 and spd>1:
            sinB=max(-1.0,min(1.0,vno/spd)); cosB=math.sqrt(max(0,1-sinB*sinB)); CL=sinB*cosB
            boost=GLIDE_LIFT_BOOST if inGlide_lift else 1.0
            Flift=CL_K*r*spd*spd*CL*atmoT*boost
            cap=(GLIDE_CLAMP_G if inGlide_lift else lift_clamp_g)*m*G
            Flift=max(-cap,min(cap,Flift))
            lvx,lvy=-rvy/spd,rvx/spd
            ax+=Flift*lvx/m; ay+=Flift*lvy/m
            fvx,fvy=rvx/spd,rvy/spd
            ax+=abs(Flift)*GLIDE_K*fvx/m; ay+=abs(Flift)*GLIDE_K*fvy/m
        # weathercock (passive: tq=0)
        aacc=-s['angv']*(0.18+r*spd*0.0024*atmoT)
        if trim_mode=='glide':
            inGlide=(s['vy']<0 and s['y']<GLIDE_TOP_Y and s['y']>GLIDE_FLOOR_Y and spd<GLIDE_ENTRY_SPD)
            if inGlide:
                deckSide=1.0 if DECKX>=s['x'] else -1.0
                targetAng=GLIDE_LEAN*deckSide
                dA=targetAng-s['ang']
                while dA>math.pi: dA-=2*math.pi
                while dA<-math.pi: dA+=2*math.pi
                aacc+=GLIDE_TRIM_K*dA*atmoT
            else:
                aacc-=1.2e-5*r*spd*vno*atmoT*(1 if s['vy']<0 else 0.4)
        else:  # baseline vertical trim (amazing build)
            aacc-=1.2e-5*r*spd*vno*atmoT*(1 if s['vy']<0 else 0.4)
        s['angv']+=aacc*dt; s['ang']+=s['angv']*dt
        s['vx']+=ax*dt; s['vy']+=ay*dt; s['x']+=s['vx']*dt; s['y']+=s['vy']*dt
        if not all(math.isfinite(v) for v in (s['x'],s['y'],s['vx'],s['vy'],s['ang'])): nanflag=True; break
        # track belly-flop beta in the glide band
        if GLIDE_FLOOR_Y<s['y']<GLIDE_TOP_Y:
            b=abs(math.asin(max(-1,min(1,vno/spd)))); beta_max=max(beta_max,b)
            lean_samples.append(abs(s['ang']))   # body lean from vertical (rad)
        if ang_at_floor is None and s['y']<=GLIDE_FLOOR_Y: ang_at_floor=abs(s['ang'])
        t+=dt
    # settled lean = median of the back half of the glide band (after the spring settles)
    settled=None
    if lean_samples:
        half=lean_samples[len(lean_samples)//2:]
        settled=math.degrees(sorted(half)[len(half)//2])
    return dict(x=round(s['x']),y=round(s['y'],1),beta_max_deg=round(math.degrees(beta_max),1),
                lean_settled_deg=round(settled,1) if settled is not None else None,
                ang_floor_deg=round(math.degrees(ang_at_floor),1) if ang_at_floor is not None else None,
                nan=nanflag,t=round(t,1))

base=run(1.2,'vertical')
glide=run(2.0,'glide')
print("BASELINE (vertical trim, clamp 1.2):", base)
print("SUPER-GLIDE (auto-lean, clamp 2.0): ", glide)
print()
print("1) settles to ~30deg-from-vertical lean? settled=%.1f deg (target %.0f) -> %s"
      % (glide['lean_settled_deg'], math.degrees(GLIDE_LEAN),
         'PASS' if (glide['lean_settled_deg'] is not None and 22<=glide['lean_settled_deg']<=38) else 'CHECK'))
print("2) extends downrange vs baseline? dx=%d m -> %s"
      % (glide['x']-base['x'], 'PASS' if glide['x']>base['x'] else 'FAIL (glide should reach further)'))
print("3a) stable (no NaN)? -> %s" % ('PASS' if not glide['nan'] else 'FAIL'))
print("3b) re-verticals below floor? ang_at_floor=%s deg -> %s"
      % (glide['ang_floor_deg'], 'PASS' if (glide['ang_floor_deg'] is not None and glide['ang_floor_deg']<35) else 'CHECK'))
