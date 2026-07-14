# Fidelity assessment — BLUE ORIGIN LANDINGS physics (verification closeout, 2026-07-14)

This separates what is **internally correct** from what is an **intentional arcade approximation**, and for
each approximation reports whether it can inject energy, fake acceleration, alter the glide, mislead the
predictor, or turn a failed touchdown into a success. Do NOT describe the whole model as "first-principles
accurate." The evidence supports: **internally consistent and gameplay-oriented.**

## A. Confirmed internally correct (verified by real-JS harness + adversarial audit)
These are sign/frame/order-correct against the +y-up, ang=0=nose-up convention:
- Coordinate transforms (world↔screen y-flip isolated to `w2sY`/`curveOff`; physics never sees screen coords)
- Nose/tail orientation: nose=(sin,cos), tail=−(sin,cos)
- Thrust sign: `F = T·(sin,cos)` along the nose (retro-burn on down-right descent points up-left, opposes v)
- Gravity sign: `ay = −G`, applied once per substep
- Retro-burn direction: `dot(F_thrust, v) < 0` during the decel burn (measured −1.09e9 in test C)
- Torque / controller sign: +tq (ArrowRight) → +ang (nose toward +x); glide attitude-spring drives toward target
- Semi-implicit (symplectic) Euler order: `v += a·dt` before `x += v·dt`, for both linear and angular
- Drag sign: `dot(F_drag, v_rel) ≤ 0` (orthonormal body-basis recombination, proven + 200k-state Monte Carlo)

## B. Intentional arcade approximations — RISK MATRIX
Columns: **Energy?** = can add mechanical energy · **FakeAccel?** = accel not from a real force ·
**Glide?** = alters the glide slope · **Predictor?** = makes the ✕ disagree with the flown path ·
**Touchdown?** = can turn a physically-failed landing into a success.

| Approximation | Energy? | FakeAccel? | Glide? | Predictor? | Touchdown? | Notes |
|---|---|---|---|---|---|---|
| Moment of inertia folded into `TORQUE`/gimbal (no explicit I) | No | No (it IS an angular accel) | No | No | No | Dimensionally consistent; both couples are rad/s². Purely a tuning abstraction. |
| Gimbal = pure torque, no lateral force | No | Yes (a real gimbal adds a small lateral force this omits) | Indirect (via attitude) | Consistent (predictor uses same model) | No | The omitted lateral force is tiny vs thrust; abstraction is standard for arcade. |
| **`GLIDE_K` along-velocity "L/D bonus" (prograde)** | **YES** | **YES (prograde thrust-like)** | **YES (extends downrange)** | Consistent (predictor uses same physics) | Indirectly (more downrange reach) | **See §C — this is the one that is NOT tiny (up to 4 m/s², ~41% of g).** |
| Simplified flat-plate lift + weathercock | No (lift ⊥ v does no work) | Lift is a modeled aero force | Yes (it IS the glide mechanism) | Consistent | No | Lift clamped ≤2×(3× glide) weight so it can't become a thruster. Restoring weathercock verified. |
| No landing-leg / contact geometry | No | No | No | No | **Partially** — legs "touching first" is not modeled; success is a state-gate at y≤0 regardless of leg geometry. |
| Velocity/tilt/offset touchdown gate | No | No | No | No | Gate is pos AND vy AND vx AND tilt — cannot pass on position alone. No energy path. |
| Predictor holds attitude (tq=0), doesn't simulate steering | No (display only) | No | No | **YES (by design)** | No | The ✕ shows "hold this attitude", not "keep steering". Documented limitation; see §D. |
| Bounded variable substep (not fixed-step) | No | No | Negligible | Negligible | No (per-substep touchdown, ≤1/120 s overshoot) | ≤1/120 s always; frame-rate drift sub-metre. |

## C. GLIDE_K quantified (the honest correction to "tiny")
`a_bonus = |Flift|·GLIDE_K/m` along v̂, GLIDE_K=0.15. Because it scales with the (boosted, clamped) lift:
- It is **always exactly 15% of the perpendicular-lift acceleration** (by construction).
- Over the glide envelope (ocean, m≈220 t, β≈45°, y 2–8 km, spd 120–240 m/s): **a_bonus ranges 0.5 – 4.06 m/s²**,
  i.e. up to **~41% of one g**, and injects up to **~214 MW** of mechanical power (F·v > 0, genuinely prograde).
- **This is NOT negligible.** My earlier "tiny prograde push" wording was wrong. It is a *bounded* (inherits the
  lift clamp) but *significant* arcade glide-extension assist. It does positive work along velocity — a real
  L/D benefit would instead REDUCE drag, never inject prograde energy.
- **Recommendation:** rename/comment it honestly as an **arcade glide-assist** (not "L/D bonus"), and document
  that it adds energy. Do NOT remove/retune without approval + a playtest (per instruction). Whether the glide
  slope survives its removal is measured in §D (predictor/GLIDE_K necessity test).

## D. Predictor limitation (MEASURED, testing/predictor_glidek.py)
The trajectory ✕ integrates with tq=0, so during **active held steering** it shows where you'd land if you
STOPPED steering and held attitude — not where continued steering leads. It DOES carry live attitude + angular
velocity, so tilting swings it. This is an intentional "hold what you're doing" read; display-only, never
perturbs the flown path. Measured impact-X error (start ~8 km up, ~5 km downrange flight):
- **No-steer coast: ~148 m** (≈3% — the predictor's intrinsic accuracy; good).
- **Constant held steer, coast: ~2507 m** (forecast X is byte-identical to the no-steer forecast — it
  genuinely ignores the held steer torque).
- **Constant held steer, burning: ~1412 m.**
So under a *held* steer the ✕ can be off by **1.4–2.5 km**. Documented in-code at the `predictTrajectory`
definition. If tighter guidance is ever wanted, pass the live tq into the forecast (risk: ✕ jitter on taps —
needs a playtest), per the audit's guidance-smell finding.

## E. GLIDE_K necessity (analytic + note)
The prograde GLIDE_K term is 15% of the (clamped) perpendicular lift, so it is bounded by the same lift cap.
It is a glide-EXTENSION assist: removing it shortens downrange reach by up to ~15% of the lift-driven range
in the glide band but does NOT remove the glide (the perpendicular flat-plate lift is the actual glide
mechanism). It cannot reverse velocity (|Flift| gating). Recommend: document/rename as arcade glide-assist;
do not remove/retune without approval + playtest.
