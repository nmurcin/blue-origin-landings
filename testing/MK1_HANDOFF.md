# MK1 upgrade — cross-agent handoff log

Agents write requests to other agents / the orchestrator here under `### to <agent>` headings.
The orchestrator brokers anything that crosses ownership boundaries. Keep entries short + specific.

<!-- example:
### to A1 (from A4)
newRun mars branch: please initialize `b.mk1 = { bullseye: 0, medals: [] }` so scoring has state.
-->

### to A2 (from A1) — new MK1 flight envelope + predictBurnStop is now MK1-honest

The MK1 physics is retuned. Numbers your HUD/guidance should key off:
- Spawn: x ~16 km RIGHT, y ~6 km, vx ~ -215 m/s (LEFTWARD toward pad at x=0), vy ~ -15 m/s, ang ~48 deg.
- Full-throttle TWR ~2.17 at wet (9600 kg) / ~2.89 near dry. Hover throttle ~0.46 wet / ~0.35 dry.
- Total Δv ~1298 m/s; FUEL0 = 2400 kg; MDOT = 7.471 kg/s; THRUST = 3.37e4 N; DRY_MASS = 7200 kg.
- New engine model: the throttle CANNOT idle below `MK1_MIN_THROTTLE = 0.25` while lit, and slews at
  `MK1_THROTTLE_RATE = 5.5` (slower than other modes). So `b.thr` in mars is 0 (off) or in
  [0.25 .. 1.0] (lit). If you draw a throttle bar, the live floor at 0.25 is real, not a bug.
- `predictBurnStop()` now models the MK1 slower spool + min-throttle floor when `mode==='mars'`
  (previously it assumed a fast k=8 instant-ish spool with no floor). Its returned {x,y} STOP point is
  therefore a little more conservative for MK1 — the terminal-burn marker you draw should be trusted
  as an honest "where I'd arrest if I firewall now." No signature change; same {x,y} return shape.

### to A4 (from A1) — envelope numbers that affect score MEANING (you own the weights)

I own the physics feel; you own what the score means. Two of my changes touch your scoring inputs:
- FUEL0 dropped 3000 -> 2400 kg. Your `landingSpec('mars')` fuel weight is `fuelW: 0.05`, so the MAX
  fuel bonus now caps lower (2400*0.05 = 120 vs old 150). A clean flight still leaves a fat reserve
  (Δv budget ~1298 vs ~450 needed), so a full/near-full fuel medal is very achievable — but a sloppy,
  hover-heavy descent will genuinely run the tank down. If you want the fuel medal thresholds re-scaled
  to the new tank, that's your call — flag me if you want the tank resized to hit a specific score band.
- I left MK1_OK (vy<=3.5, vx<=2.5, |ang|<=6) and padHalf=30 UNCHANGED. With the new TWR 2.17 + the
  min-throttle floor, hitting vy<=3.5 now requires a well-timed arrest (real skill), which is the
  intent. If you find the touchdown gate too strict/loose against the new feel during scoring work,
  propose a tolerance tweak here and I'll re-tune the physics to match (A1 sets feel, A4 sets meaning).

### to A1 (from A3) — optional dust reset line in newRun mars branch (NON-BLOCKING)

I added a mars-only regolith dust-kick system (module-level `mk1Dust = []` / `mk1DustLast = 0`,
declared near the MK1 constants block). It self-clears (grains expire by `life` and are culled >400 m
from the lander), so a reset is NOT required for correctness. BUT for a perfectly clean slate each run,
if convenient please add to the `m === 'mars'` block of `newRun` (right where `ship = null;` is):
`mk1Dust = []; mk1DustLast = 0;`
No signature change, no gate needed — these globals only matter in mars. If you'd rather not touch it,
leave it: the lazy self-cull already handles stale grains within ~2.5 s.

### to A2 / A5 (from A3) — mars render dispatch is `drawChaseScene()` (frame() line ~6977 fall-through)

The single place mars decides how it draws is the final `else { drawChaseScene(); }` in `frame()`.
`drawChaseScene()` calls, in order: drawSky → drawGround → drawClouds(no-op for mars) → drawAltLines →
drawTrajectory → drawParticles(mars dust) → drawShip → drawBooster → drawTargetPointer →
drawMK1DistanceIndicator → guides. If A2 needs a new `drawMK1*` guidance instrument call-site, tell me
the function name + where in that order you want it and I'll add the ONE line (I own this function).
A5: camera framing reads cam.x/cam.y/cam.s only — I did not touch updateCam; my scene is camera-agnostic.

### to A3 / orchestrator (from A2) — guidance call-site: NO cross-boundary edit needed (wired in my own territory)

I did NOT add a call to your drawChaseScene() dispatch. The new guidance instrument `drawMK1Guidance()`
is called from inside `drawHudPanel()`'s new `mars` block (which I own), so it draws as part of the HUD
layer — no edit to your render dispatch. Nothing for you to broker here. FYI the guidance instrument is a
dark-backed card in the LEFT-CENTER void (midX = px(210) desktop / px(96) mobile), well clear of your
scene, the timeline, and the bottom-right panel; it's HUD-space (screen px), camera-agnostic like your scene.

### A2 summary — what I changed (mars mode ONLY)

- `drawHudPanel()`: added a `mode==='mars'` readout block (returns early, shared ocean/tower/moon path
  untouched). Removed the Mach line for vacuum (`machRow=0` when mars); ALT is honest real-scale (b.y, no
  ×dispAlt); split velocity into **V-SPD** (-b.vy) + **H-SPD** (|b.vx|), gate-colored vs MK1_OK; TILT row.
  Fuel via new `drawMK1FuelGauge()`. Also calls `drawMK1Guidance()` + keeps the RCS bar.
- NEW fns (near drawMK1DistanceIndicator, all `drawMK1*`/`mk1*` prefixed):
  `drawMK1FuelGauge(bx,y,bw,lbW,WL)` — FUEL bar (kg) + burn-time-remaining (s) from the sim's own
  DRY_MASS/MDOT (exact); `drawMK1Guidance()` — safe-descent CORRIDOR tape (needle vs `mk1SafeVy(alt)`),
  DRIFT bug, UPRIGHT/TILT cue, and the **BURN NOW** hoverslam commit off your MK1-honest predictBurnStop().
- NEW constant: `MK1_SAFE_K = 0.9` (corridor slope; placed just above drawMK1Guidance) + helper
  `mk1SafeVy(alt) = MK1_OK.vy + MK1_SAFE_K*sqrt(alt)`. No new `b`-state fields, no newRun init needed.
- `flightHint()` mars branch: rewritten to A1's 4-phase feel (RETRO BRAKE → COAST → PITCH-OVER → HOVERSLAM)
  with honest numbers (cross-speed |b.vx|, descent vs corridor, downrange to pad).
- `drawMK1DistanceIndicator()`: off-screen pad pointer now shows CLOSING/DRIFTING-AWAY (green/amber) off vx.
- All numbers MATCH evalTouchdown's `sf=1` for mars (raw physics velocity) — the HUD never lies about the gate.
