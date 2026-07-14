# Physics conventions — BLUE ORIGIN LANDINGS (ground truth, traced 2026-07-14)

Single source of truth for the physics audit. Traced directly from
`blue_origin_landings.html` (`stepPhysics` ~L1766, `update` ~L2669, render ~L4191).
All line numbers are for the state at branch `physics-audit-2026-07-14` off `main` (HEAD b6444b7).

## World / coordinate frame
- **+x = right, +y = UP.** Confirmed by `let ax=0, ay=-G` (gravity pulls toward −y). Ground = `y=0`.
- This is a standard math frame (right-handed with z out of screen). It corresponds to the
  audit spec's **"+y upward"** branch, NOT the "+y down" branch.
- **Screen transform** isolates the flip: `w2sX = (wx-cam.x)*s + W/2`,
  `w2sY = H/2 - (wy-cam.y)*s`. World +y (up) → screen up. Physics never sees screen coords.

## Attitude / angle
- **`ang = 0` ⇒ nose points +y (straight up).** Angle measured from the +y axis toward +x.
- **Nose (body-axis) unit vector** = `(sin(ang), cos(ang))` (see `axx=sin, axy=cos` at L1783).
- **Tail / engine-end unit vector** = `-(sin(ang), cos(ang))` = `(-sin, -cos)`.
- **Body normal** = `(cos(ang), -sin(ang))` (`nxx=axy, nxy=-axx` at L1784).
- **Positive `ang`** leans the nose toward +x (downrange/right). Positive `angv` increases `ang`.
- `ang` normalized to (−π, π] each step (L1924).

## Forces (all in `stepPhysics`)
- **Gravity:** `ay = -G`. SI: G=9.81 (ocean/tower/moon-launch), 1.62 (mars=MK1 lunar).
- **Thrust:** if `thr>0` and `fuel>0`: `F_thrust = THRUST*thr * (sin(ang), cos(ang))` — pure axial,
  along the NOSE (`ax += T*sin/m`, `ay += T*cos/m`, L1774-1775). Reaction of exhaust out the tail. ✓
  - **Thrust never produces torque** in this model (torque comes only from the `tq` input, see below).
    Engine gimbal is abstracted as an angular-accel contribution `thr*1.3*tq`, not a lateral force.
    This is an intentional arcade simplification (no moment arm, no lateral gimbal force).
- **Fuel burn:** `fuel = max(0, fuel - MDOT*thr*dt)`. Thrust forced to 0 when `fuel<=0` (L1771).
- **Axial drag:** `Fax = -0.5*rho*CDA_AX*axDragF*|vax|*vax` where `vax` = rel-wind component on body axis.
  `axDragF` reduces axial drag high in the entry regime (thin hypersonic), ×REENTRY_DRAG_MUL for NG.
- **Crossflow (normal) drag:** `Fno = -0.5*rho*CDA_LAT*|vno|*vno`, `vno` = rel-wind on body normal.
- **Strake flat-plate LIFT** (core NG glide mechanic, L1818-1863): perpendicular to the *velocity*
  vector, `CL = sin(β)cos(β) = ½sin(2β)`, β = angle between body axis and relative wind
  (`sinB = vno/spd`). Lift dir = +90° CCW of velocity `(-rvy, rvx)/spd`, sign carried by CL.
  Clamped to a multiple of weight. Small along-velocity L/D bonus uses `|Flift|` (only extends glide).
- Relative wind: `rvx = vx - wind(y)`, `rvy = vy`. (Wind only in x.)

## Rotation (all in `stepPhysics`)
- Control input `tq ∈ {-1,0,+1}` (keyboard) or analog (mobile). **`fin` param is currently UNUSED**
  inside stepPhysics — `finD` is computed (L1767) then never read. Steering uses raw `tq`.
- `aacc = tqEff*((rcsOK?TORQUE:0) + thr*1.3)` — RCS couple (TORQUE=1.5) + gimbal (thr*1.3), scaled
  by `tqEff` (a lean-ramp near vertical). Moment of inertia is baked into these constants (no explicit I).
- Rate damping: `aacc -= angv*(0.18 + rho*spd*0.0024*atmoT)`.
- Weathercock / glide attitude spring (L1884-1909): in the glide band an attitude spring pulls the
  body toward `GLIDE_LEAN*deckSide`; otherwise a weathercock trims toward flow-alignment.
- **CoM pivot** (ocean/tower only, L1910-1930): state `(x,y)` tracks the booster BASE (engine end).
  Before integrating angle, the CoM is derived (`comH=62*0.42` up the body axis); after the angle
  updates, the base is re-placed so the CoM stayed fixed during the rotation.

## Integration order (per substep, `stepPhysics`)
1. gravity + thrust accel (uses **angle at start of substep**)
2. axial + normal aero drag
3. strake flat-plate lift
4. angular accel `aacc` (torque + damping + weathercock/glide-spring)
5. CoM-pivot pre-capture
6. **semi-implicit** angular integrate: `angv += aacc*dt; ang += angv*dt`
7. CoM-pivot base re-placement
8. **semi-implicit** linear integrate: `vx += ax*dt; vy += ay*dt; x += vx*dt; y += vy*dt`
- NOTE: accels (step 1-3) are computed with the **pre-rotation** angle, then the angle is updated
  (step 6) before velocity uses those accels (step 8). One-substep attitude/force lag. ~120 Hz substep.

## Time step
- Render frame: `dt = min(0.05, (now-lastT)/1000)` (L6815) — capped at 50 ms.
- Optional `timeScale` (2×) or moon/mars warp multiplies dt BEFORE update.
- Substep: `steps = min(400, max(1, ceil(dt/(1/120))))`, `sdt = dt/steps`.
- **This is a BOUNDED VARIABLE SUBSTEP, NOT a fixed-step accumulator.** There is no carried-remainder
  accumulator anywhere; each frame is divided into `ceil(dt·120)` equal substeps, so `sdt = dt/ceil(dt·120)`
  lands in `(~1/240, 1/120]` and its exact value depends on the frame dt (60 Hz → 2 steps → 8.33 ms;
  59.94 Hz → 3 steps → 5.56 ms). It is always ≤ 1/120 s (stable for semi-implicit Euler here), which is
  why different frame rates agree closely, but they are **not bit-identical** — measured drift over a full
  descent is sub-metre / sub-0.01-rad (see `testing/frame_sweep.py`). Describe it as "≤1/120 s bounded
  variable substep," never "fixed-step."
- **Everything trajectory-affecting is now inside the substep loop:** stepPhysics forces, the turbulence
  buffet, AND the throttle/fin smoothing ramps (`b.thr`/`b.fin`). The ramps were moved into the loop
  (commit after 57cf1db) so the SUB-FRAME throttle trajectory — hence fuel burn and gimbal authority —
  is frame-rate-invariant, not just the per-frame sampled value. Because `smoothK` telescopes exactly
  (`smoothK(k,sdt)` applied `n` times == `smoothK(k,n·sdt)`), the end-of-frame value is unchanged, so
  60 fps feel is preserved (measured 60fps drift vs the per-frame version: 0.14 m / 0.005° / 4.8 kg over
  a 5 s maneuver). The only per-frame-updated quantities left are `b.t` (advanced once, sampled correctly
  per substep) and `b.rcsFuel` (RCS spend — cosmetic bank, telescopes linearly). Coast + burn are now
  bit-identical across 30/60/120 Hz (`testing/verify_ramp_fix.py`, `decompose_attitude.py` S7/S8).

## Touchdown (`evalTouchdown` L2305)
- Fires when `y<=0`. Scores: `-vy` (descent speed) vs OK.vy, `|vx|` (drift) vs OK.vx,
  `|ang|` (tilt, deg) vs OK.ang, `|x-deckX()|` (miss) vs padHalf.
- **No landing-leg contact model** — success is velocity+tilt+offset gates only. "Legs touch before
  body/bell" and "valid leg contact" from the audit spec are NOT modeled (arcade). Flag, don't invent.
- On success: `vx=vy=0; y=0; angv=0` (hard zero — no contact impulse, so no energy injection).

## Modes (internal keys)
- `ocean` = NG 7×2 → Jacklyn (deckX 12000). `tower` = NG 9×4 → Jacklyn (deckX 16000).
- `mars` = Blue Moon MK1 (lunar, vacuum, SHIP_MODE flip-to-land). `moon` = MK2 (orbital, dormant in UI).
- `SHIP_MODE` = belly-stable flip lander (mars). `ASCENT_MODE` = powered climb (moon launch).

## Known-stale / not-ground-truth
- `scripts/test_physics.py` is a **Python re-implementation** with constants that do NOT match the
  HTML (THRUST 4.0e6 vs real 6.9e6, MDOT 1200 vs 2150, DRY 180k vs 220k, CDA_AX 150 vs 95,
  deckX 6250 vs 12000). Memory [[bo-landings-testing-harness]]: offline ports carry ~2.5× short.
  **Ground truth = the real `stepPhysics` run in headless Chrome**, never a Python port.
