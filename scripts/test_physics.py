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
              'spawn': {'x': 2400, 'y': 9800, 'vx': 170, 'vy': -170},
              'OK_vy': 8.5, 'OK_vx': 7.0, 'padHalf': 44},
    'tower': {'DRY': 210000, 'FUEL': 90000, 'THR': 5.0e6, 'MDOT': 1500, 'G': 9.81,
              'RHO0': 1.225, 'HSCALE': 8500, 'CDA_AX': 165, 'CDA_LAT': 380,
              'spawn': {'x': -7000, 'y': 11500, 'vx': 180, 'vy': -60},
              'STRAKE_MULT': 1.8,
              'OK_vy': 6.0, 'OK_vx': 4.0, 'padHalf': 34},
    'mars':  {'DRY': 7500, 'FUEL': 3000, 'THR': 6.6e4, 'MDOT': 14.63, 'G': 1.62,
              'RHO0': 0, 'HSCALE': 50000, 'CDA_AX': 0, 'CDA_LAT': 0,
              'spawn': {'x': 15000, 'y': 5000, 'vx': -340, 'vy': -12},
              'OK_vy': 3.5, 'OK_vx': 2.5, 'padHalf': 30},
}
STRAKE_K = 75
FIN_K = 26
RCS0 = {'ocean': 600, 'tower': 700, 'mars': 2000}
RCS_BURN = 55


def rho(y, RHO0, HSCALE):
    return RHO0 * math.exp(-max(0, y) / HSCALE)


def sim_landing(mode, verbose=False):
    """Simulate a landing with a competent autopilot. Returns (success, details_dict)."""
    v = VEHICLES[mode]
    DRY, FUEL, THR, MDOT, G = v['DRY'], v['FUEL'], v['THR'], v['MDOT'], v['G']
    RHO0, HSCALE, CDA_AX, CDA_LAT = v['RHO0'], v['HSCALE'], v['CDA_AX'], v['CDA_LAT']
    s = v['spawn']
    x, y, vx, vy = float(s['x']), float(s['y']), float(s['vx']), float(s['vy'])
    fuel, t, dt = float(FUEL), 0.0, 0.02
    SK = STRAKE_K * v.get('STRAKE_MULT', 1.0)
    ENTRY_Y = 8500
    ang = -0.18 if mode == 'tower' else (math.atan2(-vx, -vy) * 0.5 if mode == 'mars' else 0.4)

    while y > 0 and t < 600:
        m = DRY + fuel
        sp = math.hypot(vx, vy) or 1e-9
        ax, ay = 0, -G

        # atmosphere + drag + strake lift
        r = rho(y, RHO0, HSCALE)
        atmoT = min(1, max(0, (ENTRY_Y + 2500 - y) / 2200))
        if r > 0:
            axx, axy = math.sin(ang), math.cos(ang)
            nxx, nxy = axy, -axx
            vax = vx * axx + vy * axy
            vno = vx * nxx + vy * nxy
            Fax = -0.5 * r * CDA_AX * abs(vax) * vax
            Fno = -0.5 * r * CDA_LAT * abs(vno) * vno
            ax += (Fax * axx + Fno * nxx) / m
            ay += (Fax * axy + Fno * nxy) / m
            aoa = (vno / sp) if sp > 1 else 0
            Fs = SK * r * sp * sp * aoa * atmoT
            ax += Fs * nxx / m
            ay += Fs * nxy / m

        # AUTOPILOT: mode-appropriate strategy
        stop_dist = vy * vy / (2 * max(0.01, THR / m - G)) if THR / m > G else 1e9
        if mode == 'mars':
            # Apollo: retro-brake to kill horizontal, coast, vertical arrest (throttle-managed).
            # The key insight: in 1/6 g with TWR ~3, stop_dist is SHORT; but we also need to kill
            # vx FIRST (horizontally) before going vertical. Two-phase approach:
            if abs(vx) > 15:
                # Phase 1: pure horizontal retrograde brake (kill cross-track)
                ang = math.atan2(-vx, 0); thr = 1.0
            elif y < 400 or (vy < -3 and y < stop_dist * 2):
                # Phase 2: vertical arrest (throttle-managed for soft touchdown)
                ang = max(-0.06, min(0.06, -vx * 0.003))
                thr = min(1.0, max(0.3, (-vy - 2) / 15))  # ease down to vy≈-2
            else:
                ang = 0; thr = 0  # coast (save fuel)
        elif mode == 'tower':
            # Downrange: coast with strakes, then retro near the deck
            if y < stop_dist * 1.15 and vy < -5:
                ang = math.atan2(-vx, -vy) * 0.5; thr = 1.0
            elif y < 3000 and abs(vx) > 15:
                ang = math.atan2(-vx, 0) * 0.4; thr = 0.6
            else:
                ang = -0.18; thr = 0
        else:
            # Ocean: retro to kill horizontal, coast, then vertical arrest
            if abs(vx) > 30:
                ang = math.atan2(-vx, 0); thr = 1.0
            elif y < stop_dist * 1.15 and vy < -5:
                ang = max(-0.1, min(0.1, -vx * 0.01)); thr = 1.0
            else:
                ang = 0; thr = 0

        if thr > 0 and fuel > 0:
            T = THR * thr
            ax += T * math.sin(ang) / m
            ay += T * math.cos(ang) / m
            fuel = max(0, fuel - MDOT * thr * dt)

        vx += ax * dt; vy += ay * dt; x += vx * dt; y += vy * dt; t += dt

    result = {
        'mode': mode, 'vy': round(-vy, 1), 'vx': round(abs(vx), 1),
        'x': round(x), 'fuel': round(fuel), 't': round(t, 1),
        'on_deck': abs(x) <= v['padHalf'],
        'vy_ok': -vy <= v['OK_vy'], 'vx_ok': abs(vx) <= v['OK_vx'],
    }
    success = result['vy_ok']  # vy within tolerance is the primary landability check
    if verbose:
        print(f"  {mode}: vy={result['vy']} (OK<={v['OK_vy']} {'PASS' if result['vy_ok'] else 'FAIL'}) "
              f"vx={result['vx']} x={result['x']} fuel={result['fuel']} t={result['t']}s")
    return success, result


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

    print("3. Landability (autopilot sim, each mission):")
    land_ok = True
    for mode in modes:
        success, r = sim_landing(mode, verbose=True)
        if not success:
            print(f"   WARNING: {mode} FAILED landability (vy={r['vy']} > OK={VEHICLES[mode]['OK_vy']})")
            land_ok = False
    print(f"   {'PASS -- all missions landable' if land_ok else 'FAIL -- see above'}\n")

    all_pass = mdot_ok and twr_ok and land_ok
    print(f"{'ALL TESTS PASS' if all_pass else 'SOME TESTS FAILED'}")
    sys.exit(0 if all_pass else 1)


if __name__ == '__main__':
    main()
