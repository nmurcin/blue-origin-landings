"""
Automated physics tests for BLUE ORIGIN LANDINGS.
Run after every code change: py scripts/test_physics.py
Tests that every mission is WINNABLE by a competent autopilot, that constants are consistent,
and that key invariants hold. Exits non-zero if any test fails.

Usage:  py scripts/test_physics.py           (runs all tests)
        py scripts/test_physics.py ocean     (runs one mission)
"""
import math, sys

g0 = 9.80665

# === GAME CONSTANTS (must match the HTML; update if you change them there) ===
TIERS = {
    'arcade': {'bAltMul': 1.0, 'bSpdMul': 1.0, 'entryY': 8500, 'hscale': 8500},
}
VEHICLES = {
    'ocean': {'DRY': 180000, 'FUEL': 70000, 'THR': 4.0e6, 'MDOT': 1200, 'G': 9.81,
              'RHO0': 1.225, 'HSCALE': 8500, 'CDA_AX': 150, 'CDA_LAT': 360,
              'spawn': {'x': -13500, 'y': 16500, 'vx': 450, 'vy': -480},
              'OK_vy': 8.5, 'OK_vx': 7.0, 'padHalf': 44, 'deckX': 6250},
    'tower': {'DRY': 210000, 'FUEL': 90000, 'THR': 5.0e6, 'MDOT': 1500, 'G': 9.81,
              'RHO0': 1.225, 'HSCALE': 8500, 'CDA_AX': 165, 'CDA_LAT': 380,
              'spawn': {'x': -15000, 'y': 17500, 'vx': 550, 'vy': -600},
              'STRAKE_MULT': 1.35,
              'OK_vy': 6.0, 'OK_vx': 4.0, 'padHalf': 34, 'deckX': 8250},
    'mars':  {'DRY': 7500, 'FUEL': 3000, 'THR': 6.6e4, 'MDOT': 14.63, 'G': 1.62,
              'RHO0': 0, 'HSCALE': 50000, 'CDA_AX': 0, 'CDA_LAT': 0,
              'spawn': {'x': 15000, 'y': 5000, 'vx': -340, 'vy': -12},
              'OK_vy': 3.5, 'OK_vx': 2.5, 'padHalf': 30},
}
STRAKE_K = 75
FIN_K = 26
# FLAT-PLATE STRAKE LIFT constants (must match the HTML, see stepPhysics ~line 1701).
# CL = sin(beta)*cos(beta) = 1/2*sin(2*beta): ZERO lift when body is aligned with the flow
# (beta=0) AND at broadside/stall (beta=90deg), PEAK near a 45-55deg belly-flop lean.
CL_K = 120           # flat-plate lift scale (HTML const CL_K)
GLIDE_K = 0.15       # tiny along-velocity L/D bonus, |Flift|-gated (HTML const GLIDE_K)
LIFT_CLAMP_G = 1.2   # lift ceiling as a multiple of weight m*G (HTML const LIFT_CLAMP_G)
RCS0 = {'ocean': 600, 'tower': 700, 'mars': 2000}
RCS_BURN = 55
# heat model (matches the game): q3 = rho*v^3*hRamp; burn up if damage >= 100
HEAT_TOL_BELLY = 1.7e7   # engine-first tolerance (lowered 3.0e7→1.7e7 so no-burn reliably burns up)
HEAT_TOL_BARE = 1.4e7
HEAT_DMG_DIV = 3.0e5  # matches HTML: lowered 6.0e5→3.0e5 (with tol 1.7e7) so a no-burn engine-first
                      # descent reliably burns up (~1.6-1.8x) while a good decel burn survives (~0.35x).
ENTRY_Y = 8500


def rho(y, RHO0, HSCALE):
    return RHO0 * math.exp(-max(0, y) / HSCALE)


# === LOCKED OPENING SEQUENCE (must match blue_origin_landings.html newRun + opening override,
# ocean/tower branch, ~lines 1666-1692). The booster opens HIGH under power, CLIMBING: full
# throttle along the body axis (22deg prograde lean) to MECO, GS2 separates at OPEN_SEP with a
# recoil impulse, and control hands off at OPEN_CTRL. This carries the booster up to a ~24 km apex
# still moving downrange fast, so it arcs over and glides FAR downrange to the deck. ===
OPEN_MECO, OPEN_SEP, OPEN_CTRL = 2.2, 3.0, 4.6
OPEN_ANG = 22 * math.pi / 180   # shallow prograde lean during ascent
OPEN_VY = 180.0                 # ascending at open (positive = up)
# rotational-dynamics constants (match deck_geometry_both.py / the HTML stepPhysics pivot model)
NG_H = 62.0
COM_H = NG_H * 0.42
GLIDE_LEAN = 20 * math.pi / 180   # deck_geometry_both.py glide lean toward the deck


def _ng_landing(mode, verbose=False):
    """Faithful full-sequence sim for an NG booster (ocean/tower): locked climbing OPENING, then a
    competent decel -> glide-toward-deck -> terminal-arrest autopilot. Mirrors deck_geometry_both.py
    run()+step() exactly (rotational dynamics via COM pivot, dt=1/120, thrust easing). Returns the
    same details dict shape as the generic sim_landing so callers/tests are unchanged."""
    v = VEHICLES[mode]
    DRY, FUEL, THR, MDOT, G = v['DRY'], v['FUEL'], v['THR'], v['MDOT'], v['G']
    RHO0, HSCALE, CDA_AX, CDA_LAT = v['RHO0'], v['HSCALE'], v['CDA_AX'], v['CDA_LAT']
    deckX = v.get('deckX', 0)
    sp0 = v['spawn']
    # FAITHFUL OPENING seed: high, ascending, shallow prograde lean, vx = spawn_vx*0.9.
    x, y = float(sp0['x']), ENTRY_Y + 14000.0
    vx, vy = abs(sp0['vx']) * 0.9, OPEN_VY
    ang, angv, fuel = OPEN_ANG, 0.0, float(FUEL)
    openT, thr, sepDone, t, dt = 0.0, 0.0, False, 0.0, 1.0 / 120.0
    dmg = 0.0; maxheat = 0.0
    vx_min = vx   # minimum horizontal velocity over the whole flight (no-reversal check)

    while y > 0 and t < 400:
        m = DRY + fuel
        # --- guidance: scripted opening, then autopilot ---
        if openT < OPEN_CTRL:
            thrCmd = 1.0 if openT < OPEN_MECO else 0.0
            if not sepDone and openT >= OPEN_SEP:
                sepDone = True
                vx -= math.sin(ang); vy -= math.cos(ang)   # GS2 separation recoil impulse
            openT += dt
            # ang held at the opening lean (body-axis thrust); rotational dynamics apply below.
        else:
            sp = math.hypot(vx, vy) or 1e-9
            eff = THR / m - G
            stop_dist = vy * vy / (2 * max(0.01, eff)) if eff > 0 else 1e9
            hot = (y > ENTRY_Y - 1500) and (sp > 250)
            dist = deckX - x
            if hot:
                ang_cmd = math.atan2(-vx, -vy); thrCmd = 1.0                 # DECEL BURN engine-first through heat
            elif y < stop_dist * 1.15 and vy < -4:
                ang_cmd = max(-0.12, min(0.12, dist * 0.0004 - vx * 0.01)); thrCmd = 1.0  # terminal arrest -> deck
            elif dist > 500:
                ang_cmd = GLIDE_LEAN; thrCmd = 0.0                            # glide right toward the deck
            elif abs(vx) > 12:
                ang_cmd = math.atan2(-vx, 0) * 0.3; thrCmd = 0.5             # kill residual drift near deck
            else:
                ang_cmd = 0.0; thrCmd = 0.0
            ang += (ang_cmd - ang) * min(1.0, dt * 6); angv = 0.0            # autopilot commands ang directly
        thr += (thrCmd - thr) * min(1.0, dt * 8)                            # throttle easing (matches HTML)

        # --- dynamics (mirror deck_geometry_both.py step()) ---
        ax, ay = 0.0, -G
        if fuel <= 0:
            thr = 0.0
        if thr > 0:
            T = THR * thr
            ax += T * math.sin(ang) / m
            ay += T * math.cos(ang) / m
            fuel = max(0.0, fuel - MDOT * thr * dt)
        r = rho(y, RHO0, HSCALE)
        axx, axy = math.sin(ang), math.cos(ang)
        nxx, nxy = axy, -axx
        vax = vx * axx + vy * axy
        vno = vx * nxx + vy * nxy
        sp = math.hypot(vx, vy)
        atmoT = min(1.0, max(0.0, (ENTRY_Y + 2500 - y) / 2200.0))
        axDragF = min(1.0, max(0.4, 1 - (y - ENTRY_Y) / 12000.0))
        Fax = -0.5 * r * CDA_AX * axDragF * abs(vax) * vax
        Fno = -0.5 * r * CDA_LAT * abs(vno) * vno
        ax += (Fax * axx + Fno * nxx) / m
        ay += (Fax * axy + Fno * nxy) / m
        if r > 0 and sp > 1:
            sinB = max(-1.0, min(1.0, vno / sp))
            cosB = math.sqrt(max(0.0, 1 - sinB * sinB))
            CL = sinB * cosB
            clk = CL_K * v.get('STRAKE_MULT', 1.0)
            Flift = clk * r * sp * sp * CL * atmoT
            cap = LIFT_CLAMP_G * m * G
            Flift = max(-cap, min(cap, Flift))
            ax += Flift * (-vy / sp) / m + abs(Flift) * GLIDE_K * (vx / sp) / m
            ay += Flift * (vx / sp) / m + abs(Flift) * GLIDE_K * (vy / sp) / m
        # rotational dynamics: aero-restoring torque + pivot about the center of mass
        aacc = -angv * (0.18 + r * sp * 0.0024 * atmoT)
        aacc -= 1.2e-5 * r * sp * vno * atmoT * (1.0 if vy < 0 else 0.4)
        comX = x + math.sin(ang) * COM_H; comY = y + math.cos(ang) * COM_H
        angv += aacc * dt; ang += angv * dt
        x = comX - math.sin(ang) * COM_H; y = comY - math.cos(ang) * COM_H
        vx += ax * dt; vy += ay * dt; x += vx * dt; y += vy * dt; t += dt
        if vx < vx_min:
            vx_min = vx

        # reentry heat (engine-first protected; broadside burns)
        hRamp = min(1.0, max(0.0, (ENTRY_Y + 2500 - y) / 2200.0))
        q3 = r * sp ** 3 * hRamp
        belly = abs(vno) / sp if sp > 1 else 1.0
        safe = 1 - belly
        tol = HEAT_TOL_BARE + (HEAT_TOL_BELLY - HEAT_TOL_BARE) * safe * safe
        if q3 > tol:
            dmg += (q3 - tol) / HEAT_DMG_DIV * dt
        maxheat = max(maxheat, q3 / tol)
        if dmg >= 100:
            return False, {'mode': mode, 'result': 'BURNED UP', 'maxheat': round(maxheat, 1),
                           'vy': 999, 'vx': 999, 'x': round(x), 'fuel': round(fuel), 't': round(t, 1),
                           'on_deck': False, 'vy_ok': False, 'vx_ok': False,
                           'vx_min': round(vx_min, 2)}

    result = {
        'mode': mode, 'vy': round(-vy, 1), 'vx': round(abs(vx), 1),
        'x': round(x), 'off': round(abs(x - deckX)), 'fuel': round(fuel), 't': round(t, 1),
        'on_deck': abs(x - deckX) <= v['padHalf'],
        'vy_ok': -vy <= v['OK_vy'], 'vx_ok': abs(vx) <= v['OK_vx'],
        'vx_min': round(vx_min, 2),
    }
    # ocean/tower must actually reach the downrange deck AND touch down softly.
    success = result['vy_ok'] and result['on_deck']
    if verbose:
        print(f"  {mode}: vy={result['vy']} (OK<={v['OK_vy']} {'PASS' if result['vy_ok'] else 'FAIL'}) "
              f"vx={result['vx']} x={result['x']} deckX={deckX} off={result['off']} "
              f"on_deck={result['on_deck']} vx_min={result['vx_min']} fuel={result['fuel']} t={result['t']}s")
    return success, result


def sim_landing(mode, verbose=False):
    """Simulate a landing with a competent autopilot. Returns (success, details_dict).
    Ocean/tower NG boosters run the FAITHFUL climbing opening sequence (see _ng_landing); mars runs
    a vacuum Apollo-style descent from its spawn."""
    if mode in ('ocean', 'tower'):
        return _ng_landing(mode, verbose)

    v = VEHICLES[mode]
    DRY, FUEL, THR, MDOT, G = v['DRY'], v['FUEL'], v['THR'], v['MDOT'], v['G']
    RHO0, HSCALE, CDA_AX, CDA_LAT = v['RHO0'], v['HSCALE'], v['CDA_AX'], v['CDA_LAT']
    s = v['spawn']
    x, y, vx, vy = float(s['x']), float(s['y']), float(s['vx']), float(s['vy'])
    fuel, t, dt = float(FUEL), 0.0, 0.02
    dmg = 0.0; maxheat = 0.0
    vx_min = vx   # track the minimum horizontal velocity over the whole descent (no-reversal check)
    ang = math.atan2(-vx, -vy) * 0.5   # mars: half-retrograde lean at start

    while y > 0 and t < 600:
        m = DRY + fuel
        sp = math.hypot(vx, vy) or 1e-9
        ax, ay = 0, -G

        # atmosphere + drag (mars: RHO0=0 so these are inert, but kept for generality)
        r = rho(y, RHO0, HSCALE)
        atmoT = min(1, max(0, (ENTRY_Y + 2500 - y) / 2200))
        vno = 0.0
        if r > 0:
            axx, axy = math.sin(ang), math.cos(ang)
            nxx, nxy = axy, -axx
            vax = vx * axx + vy * axy
            vno = vx * nxx + vy * nxy
            Fax = -0.5 * r * CDA_AX * abs(vax) * vax
            Fno = -0.5 * r * CDA_LAT * abs(vno) * vno
            ax += (Fax * axx + Fno * nxx) / m
            ay += (Fax * axy + Fno * nxy) / m

        # AUTOPILOT (Apollo: retro-brake to kill horizontal, coast, vertical arrest).
        stop_dist = vy * vy / (2 * max(0.01, THR / m - G)) if THR / m > G else 1e9
        if abs(vx) > 15:
            ang = math.atan2(-vx, 0); thr = 1.0
        elif y < 400 or (vy < -3 and y < stop_dist * 2):
            ang = max(-0.06, min(0.06, -vx * 0.003))
            thr = min(1.0, max(0.3, (-vy - 2) / 15))  # ease down to vy≈-2
        else:
            ang = 0; thr = 0  # coast (save fuel)

        if thr > 0 and fuel > 0:
            T = THR * thr
            ax += T * math.sin(ang) / m
            ay += T * math.cos(ang) / m
            fuel = max(0, fuel - MDOT * thr * dt)

        vx += ax * dt; vy += ay * dt; x += vx * dt; y += vy * dt; t += dt
        if vx < vx_min:
            vx_min = vx

    result = {
        'mode': mode, 'vy': round(-vy, 1), 'vx': round(abs(vx), 1),
        'x': round(x), 'off': round(abs(x - v.get('deckX', 0))), 'fuel': round(fuel), 't': round(t, 1),
        'on_deck': abs(x - v.get('deckX', 0)) <= v['padHalf'],
        'vy_ok': -vy <= v['OK_vy'], 'vx_ok': abs(vx) <= v['OK_vx'],
        'vx_min': round(vx_min, 2),
    }
    success = result['vy_ok']  # mars: vy within tolerance is the primary landability check
    if verbose:
        print(f"  {mode}: vy={result['vy']} (OK<={v['OK_vy']} {'PASS' if result['vy_ok'] else 'FAIL'}) "
              f"vx={result['vx']} x={result['x']} fuel={result['fuel']} t={result['t']}s")
    return success, result


def _sim_heat(mode, do_decel):
    """Sim a booster reentry, optionally doing a decel burn. Returns (burned_up, maxheat)."""
    v = VEHICLES[mode]
    DRY, FUEL, THR, MDOT, G = v['DRY'], v['FUEL'], v['THR'], v['MDOT'], v['G']
    CDA_AX, CDA_LAT = v['CDA_AX'], v['CDA_LAT']
    SK = STRAKE_K * v.get('STRAKE_MULT', 1.0)
    s = v['spawn']
    x, y, vx, vy = float(s['x']), float(s['y']), float(s['vx']), float(s['vy'])
    fuel, t, dt = float(FUEL), 0.0, 0.02
    dmg = 0.0; maxheat = 0.0
    while y > 0 and t < 400:
        m = DRY + fuel
        r = rho(y, 1.225, 8500)
        sp = math.hypot(vx, vy) or 1e-9
        atmoT = min(1, max(0, (ENTRY_Y + 2500 - y) / 2200))
        # decel burn: fire HIGH (above the entry interface) and engine-first to bleed speed before
        # the heat pulse. no-decel: just point engine-first (retrograde) and never burn.
        if do_decel and sp > 200 and y > ENTRY_Y - 500:
            ang = math.atan2(-vx, -vy); thr = 1.0
        else:
            ang = math.atan2(-vx, -vy); thr = 0   # engine-first, no burn (the "cheese" attempt)
        axx, axy = math.sin(ang), math.cos(ang)
        nxx, nxy = axy, -axx
        vax = vx * axx + vy * axy; vno = vx * nxx + vy * nxy
        axDragF = min(1, max(0.4, 1 - (y - ENTRY_Y) / 12000))
        Fax = -0.5 * r * CDA_AX * axDragF * abs(vax) * vax
        Fno = -0.5 * r * CDA_LAT * abs(vno) * vno
        ax = (Fax * axx + Fno * nxx) / m; ay = -G + (Fax * axy + Fno * nxy) / m
        # FLAT-PLATE STRAKE LIFT (matches the fixed game): CL = sin(beta)*cos(beta),
        # lift perpendicular to velocity + tiny |Flift|-gated glide bonus.
        if sp > 1:
            sinB = max(-1.0, min(1.0, vno / sp))
            cosB = math.sqrt(max(0.0, 1 - sinB * sinB))
            CL = sinB * cosB
            clk = CL_K * v.get('STRAKE_MULT', 1.0)
            Flift = clk * r * sp * sp * CL * atmoT
            cap = LIFT_CLAMP_G * m * G
            if Flift > cap:
                Flift = cap
            elif Flift < -cap:
                Flift = -cap
            ax += Flift * (-vy / sp) / m + abs(Flift) * GLIDE_K * (vx / sp) / m
            ay += Flift * (vx / sp) / m + abs(Flift) * GLIDE_K * (vy / sp) / m
        if thr > 0 and fuel > 0:
            ax += THR * thr * math.sin(ang) / m; ay += THR * thr * math.cos(ang) / m
            fuel = max(0, fuel - MDOT * thr * dt)
        hRamp = min(1, max(0, (ENTRY_Y + 2500 - y) / 2200))
        q3 = r * sp ** 3 * hRamp
        belly = abs(vno) / sp if sp > 1 else 1; safe = 1 - belly
        tol = HEAT_TOL_BARE + (HEAT_TOL_BELLY - HEAT_TOL_BARE) * safe * safe
        if q3 > tol: dmg += (q3 - tol) / HEAT_DMG_DIV * dt
        maxheat = max(maxheat, q3 / tol)
        vx += ax * dt; vy += ay * dt; x += vx * dt; y += vy * dt; t += dt
        if dmg >= 100: return True, maxheat
    return False, maxheat


def test_decel_burn_required():
    """Verify the NG decel burn is MANDATORY: skipping it burns the booster up (heat), while doing
    it keeps the vehicle survivable. This is the faithful-to-NG mechanic the user requested."""
    ok = True
    for mode in ('ocean', 'tower'):
        burned_no, heat_no = _sim_heat(mode, do_decel=False)
        burned_yes, heat_yes = _sim_heat(mode, do_decel=True)
        # want: no-decel BURNS UP, with-decel SURVIVES the heat
        good = burned_no and not burned_yes
        print(f"  {mode}: no-decel={'BURNED UP' if burned_no else 'survived'} ({heat_no:.1f}x tol), "
              f"with-decel={'BURNED UP' if burned_yes else 'survived'} ({heat_yes:.1f}x tol) "
              f"{'PASS' if good else 'FAIL'}")
        if not good:
            ok = False
    return ok


def test_no_reversal():
    """Verify the booster NEVER reverses horizontal direction during an ocean/tower descent.
    Faithful to the real NG GS1: it lands downrange carrying its separation momentum (always
    moving left->right, positive vx, no boostback/no direction reversal). We assert the MINIMUM
    vx over the whole descent stays above a small negative tolerance (numerical noise near
    touchdown). vx_min > -3.0 means the booster never truly reversed course."""
    TOL = -3.0
    ok = True
    for mode in ('ocean', 'tower'):
        _success, r = sim_landing(mode)
        vx_min = r.get('vx_min', -999)
        good = vx_min > TOL
        print(f"  {mode}: vx_min={vx_min:.2f} (> {TOL} for no-reversal) {'PASS' if good else 'FAIL'}")
        if not good:
            ok = False
    return ok


def _lift_ax(ang, vx, vy, r, m, G, CDA_ax_unused=None, strake_mult=1.0, atmoT=1.0):
    """Return the HORIZONTAL acceleration contributed by STRAKE LIFT ALONE for a body at angle
    `ang` in a relative wind (vx, vy). Mirrors the game's exact lift expression in stepPhysics:
        axx,axy = sin(ang), cos(ang)      (body axis / nose)
        nxx,nxy = axy, -axx               (body normal)
        vno     = vx*nxx + vy*nxy         (flow component on the plate face)
        sinB    = clamp(vno/spd, -1, 1);  cosB = sqrt(1 - sinB^2)
        CL      = sinB*cosB               (= 1/2 sin 2beta)
        Flift   = CL_K*strake_mult * r * spd^2 * CL * atmoT   (clamped to +-LIFT_CLAMP_G*m*G)
        lift is perpendicular to velocity: lv = (-vy, vx)/spd
        plus |Flift|*GLIDE_K along velocity fv = (vx, vy)/spd
    Only the lift + glide terms are returned (no gravity/drag/thrust), isolating the invariant.
    """
    spd = math.hypot(vx, vy)
    axx, axy = math.sin(ang), math.cos(ang)
    nxx, nxy = axy, -axx
    vno = vx * nxx + vy * nxy
    sinB = max(-1.0, min(1.0, vno / spd))
    cosB = math.sqrt(max(0.0, 1 - sinB * sinB))
    CL = sinB * cosB
    clk = CL_K * strake_mult
    Flift = clk * r * spd * spd * CL * atmoT
    cap = LIFT_CLAMP_G * m * G
    if Flift > cap:
        Flift = cap
    elif Flift < -cap:
        Flift = -cap
    lvx = -vy / spd
    fvx = vx / spd
    ax = Flift * lvx / m + abs(Flift) * GLIDE_K * fvx / m
    return ax


def test_lift_direction_sane():
    """CORE flat-plate invariant: for a booster falling down-right (vx=140, vy=-200), the horizontal
    acceleration from lift must be LARGER at a moderate lean than when the body is ALIGNED with the
    flow (a near-vertical body pointed along a near-vertical fall). A flat plate makes ZERO lift when
    aligned (beta=0) and PEAK lift near a 45deg lean. The OLD (buggy) model did the opposite: it grew
    lift as the body swung toward the flow direction, so pointing vertical in a vertical fall pushed
    you sideways HARDER. This test guards against that regression.

    Assert: |ax at aligned-with-flow| < |ax at 40deg-off-flow lean|.
    """
    vx, vy = 140.0, -200.0
    spd = math.hypot(vx, vy)
    # Use the ocean booster's atmosphere/mass regime for a representative magnitude.
    v = VEHICLES['ocean']
    m = v['DRY'] + v['FUEL']
    G = v['G']
    r = rho(3000, v['RHO0'], v['HSCALE'])   # mid-atmosphere density where lift is live

    # The flow-direction angle (velocity vector) as a body angle: body axis = (sin,cos), so the body
    # is ALIGNED with the flow (tail-first, beta=0) when ang = atan2(vx, vy). vno = 0 there → CL = 0.
    ang_flow = math.atan2(vx, vy)
    # 40deg off-flow lean (nose leaned toward +x side of the flight path).
    ang_off = ang_flow + math.radians(40)

    ax_aligned = _lift_ax(ang_flow, vx, vy, r, m, G)
    ax_off = _lift_ax(ang_off, vx, vy, r, m, G)

    # Sweep table for visibility: ax from lift vs body-angle offset from the flow direction.
    print(f"  flow dir (vx={vx:.0f}, vy={vy:.0f}), spd={spd:.1f} m/s, rho={r:.4f} kg/m^3, m={m} kg")
    print(f"  {'off-flow deg':>12} | {'beta(deg)':>9} | {'CL':>8} | {'ax_lift (m/s^2)':>16}")
    for deg in (0, 10, 20, 30, 40, 50, 60, 70, 80, 90):
        ang = ang_flow + math.radians(deg)
        # recover beta for display
        nxx, nxy = math.cos(ang), -math.sin(ang)
        vno = vx * nxx + vy * nxy
        sinB = max(-1.0, min(1.0, vno / spd))
        beta = math.degrees(math.asin(sinB))
        CL = sinB * math.sqrt(max(0.0, 1 - sinB * sinB))
        ax = _lift_ax(ang, vx, vy, r, m, G)
        print(f"  {deg:>12} | {beta:>9.1f} | {CL:>8.4f} | {ax:>16.4f}")

    ok = abs(ax_aligned) < abs(ax_off)
    print(f"  |ax aligned-with-flow| = {abs(ax_aligned):.4f}  <  "
          f"|ax 40deg-off-flow| = {abs(ax_off):.4f}  ->  {'PASS' if ok else 'FAIL'}")
    if not ok:
        print("  FAIL: lift is NOT larger at a moderate lean than when aligned with the flow "
              "(flat-plate direction invariant violated).")
    return ok


def test_mdot_consistency():
    """Verify MDOT = THRUST / (Isp · g0) for each vehicle."""
    isps = {'ocean': 340, 'tower': 340, 'mars': 460}
    ok = True
    for mode, v in VEHICLES.items():
        expected_mdot = v['THR'] / (isps[mode] * g0)
        actual_mdot = v['MDOT']
        err = abs(actual_mdot - expected_mdot) / expected_mdot
        if err > 0.05:  # 5% tolerance (game-tuned values may diverge slightly)
            print(f"  FAIL: {mode} MDOT={actual_mdot} vs expected {expected_mdot:.1f} (err {err*100:.1f}%)")
            ok = False
    return ok


def test_twr_sane():
    """Verify TWR is in a sensible range for each vehicle."""
    ok = True
    for mode, v in VEHICLES.items():
        mass = v['DRY'] + v['FUEL']
        twr = v['THR'] / (mass * v['G'])
        if twr < 1.1:
            print(f"  FAIL: {mode} TWR={twr:.2f} < 1.1 (can't even hover!)")
            ok = False
        elif twr > 5:
            print(f"  WARN: {mode} TWR={twr:.2f} > 5 (over-powered?)")
    return ok


def main():
    modes = sys.argv[1:] if len(sys.argv) > 1 else ['ocean', 'tower', 'mars']
    print("=== BLUE ORIGIN LANDINGS — physics test suite ===\n")

    print("1. MDOT consistency (THRUST / Isp·g0):")
    mdot_ok = test_mdot_consistency()
    print(f"   {'PASS' if mdot_ok else 'FAIL'}\n")

    print("2. TWR sanity (1.1 < TWR < 5):")
    twr_ok = test_twr_sane()
    print(f"   {'PASS' if twr_ok else 'FAIL'}\n")

    print("2b. Decel burn required (no burn = burn up; with burn = survive):")
    reach_ok = test_decel_burn_required()
    print(f"   {'PASS' if reach_ok else 'FAIL'}\n")

    print("2c. No horizontal reversal (booster always moves left->right, vx_min > -3.0):")
    no_rev_ok = test_no_reversal()
    print(f"   {'PASS' if no_rev_ok else 'FAIL'}\n")

    print("2d. Lift direction sane (flat-plate: aligned-with-flow < 40deg lean):")
    lift_dir_ok = test_lift_direction_sane()
    print(f"   {'PASS' if lift_dir_ok else 'FAIL'}\n")

    print("3. Landability (autopilot sim; ocean/tower must land ON-DECK, mars vy-only):")
    land_ok = True
    for mode in modes:
        success, r = sim_landing(mode, verbose=True)
        if not success:
            vm = VEHICLES[mode]
            reasons = []
            if not r.get('vy_ok', False):
                reasons.append(f"vy={r['vy']} > OK={vm['OK_vy']}")
            if mode in ('ocean', 'tower') and not r.get('on_deck', False):
                reasons.append(f"OFF-DECK: x={r.get('x')} vs deckX={vm.get('deckX')} (off={r.get('off')} > padHalf={vm['padHalf']})")
            print(f"   WARNING: {mode} FAILED landability ({'; '.join(reasons) or 'unknown'})")
            land_ok = False
    print(f"   {'PASS -- all missions landable' if land_ok else 'FAIL -- see above'}\n")

    all_pass = mdot_ok and twr_ok and reach_ok and no_rev_ok and lift_dir_ok and land_ok
    print(f"{'ALL TESTS PASS' if all_pass else 'SOME TESTS FAILED'}")
    sys.exit(0 if all_pass else 1)


if __name__ == '__main__':
    main()
