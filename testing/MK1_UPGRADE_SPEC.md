# MK1 (Blue Moon lunar lander) upgrade — shared spec & ownership map

**Goal:** make the `mars` game mode (BLUE MOON MK1 lunar landing) genuinely fun, interactive, and
worth playing. It is currently functional but flat, and has vacuum-wrong artifacts (clouds, blue
haze, a "MACH" readout, an ALT that shows ×6 the real altitude). We are doing a high-granularity,
improvement-driven overhaul with 5 specialized agents editing DISJOINT regions of one file.

**The file:** `C:/Users/nmurcin/Lumen/local/blue-origin-landings/index.html` — a single ~6957-line
HTML build, ONE `<script>` (lines ~315-6955). The named twin `blue_origin_landings.html` is a
byte-identical copy; the ORCHESTRATOR syncs it (`cp index.html blue_origin_landings.html`) — agents
edit ONLY `index.html`.

---

## HARD RULES (every agent, no exceptions)

1. **`mars` mode ONLY.** Internal mode key for Blue Moon MK1 is `'mars'` (historical; do not rename).
   Touch code only inside `mode === 'mars'` branches (and the shared functions' mars paths). MK1 in
   `applyModeParams`/`newRun` is the `m === 'mars'` branch.
2. **NEVER change ocean/tower/moon behavior.** No edits to shared physics constants that ocean/tower
   read (THRUST/MDOT/DRY_MASS/CDA_* are set per-mode inside `applyModeParams` — only touch the mars
   branch). If a change would alter a shared code path, gate it behind `mode === 'mars'`.
3. **The physics core is audited & golden for ocean/tower** — do not touch `stepPhysics` logic that
   runs for NG boosters. The mars path in stepPhysics is: `G=1.62, RHO0=0` (vacuum → all aero/heat
   terms are zero because `r = rho(y) = 0`), `SHIP_MODE=false`, `ASCENT_MODE=false`. So for mars,
   stepPhysics reduces to: gravity + (thrust along nose) + (tq torque + gimbal) + base-pivot rotation.
   No aero, no lift, no heating. Keep it that way unless A1 deliberately adds a vacuum term.
4. **Do NOT touch another agent's owned functions.** If you need a change there, write it in
   `testing/MK1_HANDOFF.md` under a `### to <agent>` heading and the orchestrator brokers it.
5. **No new external assets/network.** Pure procedural Canvas 2D + Web Audio, offline, public-data only.
6. **Windows/ASCII in any .py you write.** Use `py`. Don't trigger CC security prompts (no `cd &&`,
   no `#` after newline in bash strings).
7. **Green gate must pass after your change:** `py testing/green_gate.py` (sync+static+harness+probes+
   runtime+ui). The orchestrator runs it between integrations; your job is to not break it.

---

## COORDINATE / STATE CONVENTIONS (ground truth — see testing/PHYSICS_CONVENTIONS.md)

- World: **+x = right, +y = UP**, ground `y=0`. `ang=0` ⇒ nose points +y (up). Nose unit `(sin,cos)`.
- The booster state `b`: `x,y` (metres, base of vehicle), `vx,vy` (m/s), `ang` (rad), `angv`,
  `thr` (0..1 smoothed), `fuel` (kg), `rcsFuel`, `t` (s), `damage`, `heatFrac`, `phase`.
- **MK1 spawn (current):** `x≈15000` (15 km RIGHT of pad), `y≈5000` (5 km alt), `vx≈-340` (leftward),
  `vy≈-14`, `ang≈55°`. Landing site (pad) is at **x=0**. Player brakes retrograde, coasts, lands.
- **MK1 vehicle params (current):** `G=1.62`, `DRY_MASS=7500`, `FUEL0=3000`, `THRUST=6.6e4`,
  `MDOT=14.63`, RCS0.mars=2000. Lunar TWR ≈ 1.65 full-throttle at spawn mass.
- **Touchdown gate (MK1_OK):** `vy ≤ 3.5, vx ≤ 2.5, |ang| ≤ 6°`, `padHalf=30 m`. Fires in
  `evalTouchdown()` when `b.y <= 0` (the `else` branch of update()'s ground-contact block).
- **HUD scale bug to FIX:** HUD altitude/speed multiply by `T().dispSpd`/`dispAlt` (the ×6 arcade
  display scale) EXCEPT `evalTouchdown` already uses `sf = (mode==='mars') ? 1 : T().dispSpd`. The
  drawHUD readouts do NOT special-case mars, so MK1 shows ALT/SPD ×6 (30 km when really 5 km, "MACH
  6.7" in vacuum). MK1 is already real-scale — it must display REAL numbers, no Mach.

---

## OWNERSHIP MAP (disjoint — each function belongs to exactly one agent)

Agents edit only the **mars branch** inside these functions unless the function is wholly MK1-specific.

### A1 — Flight model & landing feel (physics/tuning)
- `applyModeParams` — the `m === 'mars'` branch (lines ~507-519): G/mass/thrust/MDOT/RCS tuning.
- `newRun` — the `m === 'mars'` spawn block (~1662-1679): spawn state, approach geometry.
- `stepPhysics` — MAY add a mars-only vacuum term (e.g. throttle response), gated `mode==='mars'`.
  Do NOT alter the ngBooster/SHIP_MODE/aero/lift paths.
- `landingSpec` — the `m === 'mars'` return (~816): MK1_OK tolerances, scoring weights (coordinate
  the scoring-weight numbers with A4 via handoff — A1 owns the physics feel, A4 owns score meaning).
- `predictBurnStop` / `predictTrajectory` — mars behavior if it needs a vacuum tweak (read first;
  these are shared with the predictor HUD A2 draws — coordinate).
- Constants A1 may add (prefix `MK1_`): e.g. `MK1_MIN_THROTTLE`, `MK1_THROTTLE_RATE`.

### A2 — HUD, guidance & instrumentation
- `drawHUD` — mars readouts: **remove Mach, show honest real-scale ALT + split V-SPEED/H-SPEED**,
  fuel, descent-rate-vs-safe. (drawHUD is shared; edit the mars-relevant readout lines / add a
  `mode==='mars'` block.)
- `flightHint` — the `mode === 'mars'` branch (~4870-4886).
- `drawMK1DistanceIndicator` (~3869) — wholly MK1; own it fully. May evolve into a guidance tape.
- NEW MK1 guidance instrument function(s), prefix `drawMK1*` — call site added in the mars render
  path (coordinate the ONE call-site line with A3, who owns the mars render dispatch, via handoff).
- Attitude/engine readout mars specifics in `drawAttitudeIndicator`/`drawEngineCluster` mars branches.

### A3 — Lunar environment & vehicle art
- `drawSky` — mars branch: **kill clouds & blue atmospheric haze in vacuum**, add starfield + Earth
  in the black lunar sky. (`drawClouds` is called from the frame/scene path — ensure it's suppressed
  for mars.)
- `drawGround` — the `mode === 'mars'` lunar-surface branch (~3402-3459): terrain depth, the target
  landing site, south-pole character.
- `drawBooster` mars branch + `drawBlueMoonBody` (~4525): the MK1 lander silhouette + BE-7 plume
  (`VEH_H`/`VW`/`jl` mars values ~4265-4314), landing legs (`drawLandingLegs(MK1_H)`).
- `drawParticles` / plume / a NEW regolith-dust-kick on terminal descent (mars-gated).
- Owns the **mars render dispatch** — the ONE place the frame decides mars draws chase vs map. A2's
  new instrument call-site and A5's camera must coordinate through A3.

### A4 — Game loop, scoring, objectives & juice
- `evalTouchdown` — the `mode === 'mars'` scoring/crash paths (~2346-2378): medals, bullseye scoring.
- `finish` — mars best-score/prevBest handling (already per-tier after the error sweep); scorecard.
- `drawDone` — the `mode === 'mars'` result screen (~6716): scorecard, medals, replay CTA.
- NEW objective/challenge layer (prefix `mk1*` or `MK1_`): landing-zone bullseye, fuel/precision/
  speed medals, optional target variety. State lives on `b` or a new `mk1` object.
- Coordinate MK1_OK / scoring-weight NUMBERS with A1 (A1 sets feel, A4 sets meaning) via handoff.

### A5 — Camera, audio & controls polish
- `updateCam` / `snapGroundCam` / `moonCamTarget` — mars branches: terminal-descent framing, lead
  the camera toward the pad, zoom for the hoverslam.
- Audio: the mars `engineGain`/`rcsGain`/`windGain` handling in update() (~2846-2857) — BE-7 engine
  character, RCS puffs, NO wind in vacuum. `initAudio`/`playChime`/`playClank` mars specifics.
- Input/warp for mars: `warpStep`/frame() warp gate (~1234, 6885-6893), control responsiveness.
- Coordinate camera framing with A3 (scene) via handoff; do not edit A3's draw functions.

---

## SHARED HOOKS (add-only; announce in MK1_HANDOFF.md if you add one others need)

- If you add a per-frame MK1 state field, put it on `b` (e.g. `b.mk1Dust`, `b.mk1Phase`) so newRun's
  mars branch initializes it. A1 owns newRun — request the init line via handoff.
- New MK1 constants: prefix `MK1_` and place them near the existing MK1 constants block (A1 brokers
  the constant block location to avoid line collisions).
- New MK1 draw functions: prefix `drawMK1*`; the single call-site goes in A3's mars render dispatch.

## INTEGRATION ORDER (orchestrator runs agents in this order, green-gate + screenshot between)

1. **A1** (physics) — establishes the flight envelope everything else keys off.
2. **A3** (environment/art) — establishes the mars render dispatch + scene others hook into.
3. **A2** (HUD) — reads A1's envelope, hooks A3's dispatch.
4. **A5** (camera/audio) — frames A3's scene, reacts to A1's flight.
5. **A4** (scoring/juice) — scores the whole thing, adds the endgame.

Agents produce a UNIFIED DIFF or an exact edit list against `index.html` with line-anchored context;
the orchestrator APPLIES edits (so concurrent writes never corrupt the file), runs the gate + a mars
screenshot, and commits per agent. If two agents need the same line, the orchestrator resolves it.
