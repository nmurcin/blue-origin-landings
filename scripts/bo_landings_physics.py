"""
BLUE ORIGIN LANDINGS — physics constant derivation.
All vehicle figures are PUBLIC-DATA-DERIVED game-tuning estimates, NOT official specs.
Public inputs (see plan References): BE-4 2.847e6 N SL, Isp 340 s; BE-7 4.4e4 N vac, Isp 460 s;
NG 7 m dia x 57.5 m GS1; Blue Moon MK1 ~21,350 kg wet / 1x BE-7; MK2 16,000 kg dry / 3x BE-7.
g0 = 9.80665 m/s^2.  MDOT = Thrust / (Isp * g0).
"""
g0 = 9.80665

def mdot(thrust_N, isp_s):
    return thrust_N / (isp_s * g0)

def twr(thrust_N, mass_kg, g):
    return thrust_N / (mass_kg * g)

def dv(isp_s, m_wet, m_dry):
    import math
    return isp_s * g0 * math.log(m_wet / m_dry)

print("=== Engine MDOT (public thrust + Isp) ===")
be4 = 2.847e6
print(f"BE-4 SL  : thrust {be4:.3e} N, Isp 340 -> MDOT {mdot(be4,340):.1f} kg/s/engine")
print(f"  7x BE-4 liftoff : {7*be4:.3e} N, MDOT {7*mdot(be4,340):.0f} kg/s")
print(f"  9x BE-4 liftoff : {9*be4:.3e} N, MDOT {9*mdot(be4,340):.0f} kg/s")
be7 = 4.4e4
print(f"BE-7 vac : thrust {be7:.3e} N, Isp 460 -> MDOT {mdot(be7,460):.2f} kg/s/engine")
print(f"  3x BE-7 (MK2)   : {3*be7:.3e} N, MDOT {3*mdot(be7,460):.2f} kg/s")

print("\n=== OCEAN (NG 7x2 landing) — game-tuning estimate ===")
# Landing burn = a few BE-4 deeply throttled. Target landing TWR ~3 for a controllable hoverslam.
ocean_dry, ocean_fuel = 180000, 70000
ocean_land_mass = ocean_dry + ocean_fuel
# pick THRUST for TWR ~3.0 at full landing mass
ocean_thrust = 7.4e6
print(f"DRY {ocean_dry}  FUEL {ocean_fuel}  land mass {ocean_land_mass}")
print(f"THRUST {ocean_thrust:.3e} N (= {ocean_thrust/be4:.2f}x BE-4 SL-equiv, within 3-engine throttled range)")
print(f"MDOT {mdot(ocean_thrust,340):.0f} kg/s  | landing TWR {twr(ocean_thrust,ocean_land_mass,9.81):.2f}")
print(f"full-throttle burn budget {ocean_fuel/mdot(ocean_thrust,340):.1f} s  | dv {dv(340,ocean_land_mass,ocean_dry):.0f} m/s")
# Drag areas scaled from Falcon's 95/195 by NG cross-section ratio (7m vs 3.7m dia)
ratio = (7.0/3.7)**2
print(f"CDA scale (7m/3.7m)^2 = {ratio:.2f} -> CDA_AX ~{95*ratio:.0f} (use 150), CDA_LAT ~{195*ratio:.0f} (use 360)")

print("\n=== TOWER (NG 9x4 landing) — heavier + tighter + higher-energy ===")
tower_dry, tower_fuel = 210000, 70000
tower_land_mass = tower_dry + tower_fuel
tower_thrust = 8.4e6   # more engines available, keep TWR a touch lower than ocean (harder)
print(f"DRY {tower_dry}  FUEL {tower_fuel}  land mass {tower_land_mass}")
print(f"THRUST {tower_thrust:.3e} N  MDOT {mdot(tower_thrust,340):.0f} kg/s  | landing TWR {twr(tower_thrust,tower_land_mass,9.81):.2f}")
print(f"full-throttle burn budget {tower_fuel/mdot(tower_thrust,340):.1f} s")

print("\n=== MARS key -> BLUE MOON MK1 (lunar propulsive descent) ===")
mk1_dry, mk1_fuel = 7500, 9000
mk1_mass = mk1_dry + mk1_fuel
mk1_thrust = be7  # 1x BE-7
print(f"DRY {mk1_dry}  FUEL {mk1_fuel}  mass {mk1_mass}  (derived from ~21,350 kg public wet, descent config)")
print(f"THRUST {mk1_thrust:.3e} N (1x BE-7)  MDOT {mdot(mk1_thrust,460):.2f} kg/s")
print(f"lunar TWR (g=1.62) {twr(mk1_thrust,mk1_mass,1.62):.2f}  | min-throttle 20% TWR {0.20*twr(mk1_thrust,mk1_mass,1.62):.2f}")
print(f"descent dv {dv(460,mk1_mass,mk1_dry):.0f} m/s (vs ~2000 m/s needed)  | burn budget {mk1_fuel/mdot(mk1_thrust,460):.0f} s")

print("\n=== MOON key -> BLUE MOON MK2 (dock + TLI + lunar landing) ===")
# Landing-config (final powered descent) — what toLunarDescentFrame() will use.
mk2_dry, mk2_fuel = 16000, 12000
mk2_mass = mk2_dry + mk2_fuel
mk2_thrust = 3*be7
print(f"landing DRY {mk2_dry} (public)  FUEL {mk2_fuel}  mass {mk2_mass}")
print(f"THRUST {mk2_thrust:.3e} N (3x BE-7)  MDOT {mdot(mk2_thrust,460):.2f} kg/s")
print(f"lunar TWR (g=1.62) {twr(mk2_thrust,mk2_mass,1.62):.2f}  | min 20% TWR {0.20*twr(mk2_thrust,mk2_mass,1.62):.2f}")
print(f"descent dv {dv(460,mk2_mass,mk2_dry):.0f} m/s  | burn budget {mk2_fuel/mdot(mk2_thrust,460):.0f} s")

print("\n=== Fin + strake reference areas (Phase 3) from PUBLIC 7m x 57.5m dims ===")
D, L = 7.0, 57.5
A_side = D*L
A_cross = 3.14159*(D/2)**2
print(f"body side area D*L = {A_side:.1f} m^2 ; cross-section {A_cross:.1f} m^2")
print(f"4 fins  ~8%  of side  = {0.08*A_side:.1f} m^2 total (~{0.08*A_side/4:.1f} m^2 each)")
print(f"strakes ~15% of side  = {0.15*A_side:.1f} m^2 total")
print("low-AR lift-curve slope CL_a = 2*pi*AR/(AR+2):")
for AR in (1.5, 1.7, 2.0):
    print(f"  AR {AR}: {2*3.14159*AR/(AR+2):.2f} /rad")
