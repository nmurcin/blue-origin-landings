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

### to orchestrator / A1 (from A5) — one mars-gated line added to newRun's SHARED cam init (FYI, non-conflicting)

I added ONE line to the shared post-branch camera init in `newRun` (right after `cam.x=b.x; cam.y=b.y*0.62; cam.s=H/30000;`, ~L1795), NOT inside A1's mars spawn block (1702-1713):
`if (mode === 'mars') snapGroundCam();`
It makes MK1 open already framed by my cinematic camera (no zoom-in lerp on the first frames). It only fires for mars, so ocean/tower/moon inits are byte-for-byte unchanged. If A1 also edits this tail, the orchestrator can keep both — they don't collide.

### to A4 (from A5) — shake hook is LIVE for the hoverslam

My mars `updateCam` honors the existing global `shakeT` (same convention as ocean/tower/moon) — if you set `shakeT` on touchdown/crash/hard-landing, the mars camera rattles proportionally (kick scales `1/cam.s` so it reads the same at any zoom). No new hook needed; just `shakeT = <secs>` in your evalTouchdown mars path and the camera does the rest. Suggested: a short punchy `shakeT = Math.max(shakeT, 0.25)` on a hard-but-survivable touchdown, more on a crash.

### A5 summary — what I changed (mars mode ONLY)

- **Camera** (`updateCam`/`snapGroundCam`/new `marsCamTarget()`): added a dedicated `mode==='mars'` branch
  (previously MK1 fell through to the ocean/tower deck-framing path — lander was a tiny edge-jammed speck).
  New broadcast-style framing, altitude-keyed, three eased phases (no hard cuts, the lerp smooths):
  BRAKE/COAST (high) → wide enough to read the approach arc + pad direction, lander stays prominent;
  PITCH-OVER (mid) → tighten + lead harder toward the pad (x=0);
  HOVERSLAM (terminal) → zoom in on pad+lander, camera center CAPPED near the ground so the lunar surface,
  A3's beacon, and A3's regolith dust fill the lower frame with the lander riding upper-middle. Horizontal
  lead toward the pad (`padBias` 16%→78%) + a small velocity lead, clamped so the lander never leaves frame.
  Camera only reads state + sets cam.x/y/s (never draws). Warp-scaled follow so it keeps pace under warp.
  New constant `MK1_PAD_X = 0` (== deckX() for mars). Verified in testing/frames/a5_over_pad_{600,220,60}.png.
- **Audio** (`update()` `if(AC)` block, new `mode==='mars'` path; every node access guarded, AC-null-safe):
  BE-7 lander character — a NON-LINEAR engine-gain curve so A1's min-throttle floor (0.25) is an audible
  IDLE RUMBLE (~0.11) while a firewall clearly ROARS (~0.34), with a ~35 ms responsive ear-slew. **NO WIND**
  in vacuum: `windGain` hard-zeroed for mars (not relying on rho()=0 arithmetic). **RCS** = crisp attitude
  puffs (~6 ms attack / ~50 ms release, gated on |b.tqIn|>0.2 + a live RCS bank). Non-mars audio (ocean/tower
  + moon MK2 descent) is byte-for-byte the old behavior, just moved into an `else` and node-guarded.
- **Warp/controls** (mars-only): capped the MK1 warp ladder at `MK1_WARP_MAX_IDX = 7` (×160) in both
  `warpStep` (mobile) and the X key (desktop) — the full ×5120 ladder would overshoot the pad in one frame
  on the ~30-40 s Apollo coast. The frame() warp gate already snaps warp back to ×1 the instant you burn or
  steer (floorIdx=0 for mars), so the active landing is always real-time — I left that intact. Raw input
  mapping (burn→thrCmd, steer→tqIn) left untouched: it's clean and the throttle spool/min-floor is A1's
  physics, not mine.
- Green gate PASS; mars runtime line: `errs=0 warns=0 nan_draw=0 ctx_unbal=0 ctx_underflow=0 landed=True`.
- Added a testing-only helper `testing/a5_cam_probe.py` (positions the lander over the pad at a chosen alt
  to verify terminal framing — a ballistic `--alt` drop stays 15 km downrange and can't show it). Not part
  of the game; does not affect the gate.

### to A1 (from A4) — I did NOT change the touchdown GATE; only scoring weights + the leaderboard ceiling

I kept your envelope exactly: MK1_OK (vy<=3.5, vx<=2.5, |ang|<=6) and padHalf=30 are UNTOUCHED. The gate
in evalTouchdown's mars path fires on the same tolerances you set — the physics still hits it. All I did was
change what a *legal* touchdown SCORES (pillar-multiplied), so no re-tune is needed on your end.

Two SHARED-line changes I made (flagging for your awareness, both mars-only in effect):
- `SCORE_MAX.mars`: 2000 -> 4600. A PERFECT TOUCHDOWN now scores base 900 × (1+1.20+1.10+0.90+0.60) = 4320,
  and the old 2000 ceiling silently BLOCKED any score >2000 from boarding (submitScore rejects > SCORE_MAX).
  4600 gives headroom for a legit perfect. ocean/tower/moon ceilings untouched.
- `landingSpec('mars').base`: 1200 -> 900 (now a FLOOR for a sloppy-but-legal landing; mk1Score multiplies
  it). The mars fuelW/precPos/precVy fields are now LEGACY (the mars path calls mk1Score, not those weights)
  — left in place only for object-shape parity with ocean/tower. Your `landingSpec` return SHAPE is unchanged.

### A4 summary — what I changed (mars mode ONLY)

- **Scoring model** (`mk1Score()`, new): score = base × (1 + prec + soft + fuel + combo), each pillar a
  0..1 quality × its weight (MK1_W_PREC 1.20, MK1_W_SOFT 1.10, MK1_W_FUEL 0.90, MK1_W_COMBO 0.60). PRECISION
  = 1 at bullseye→0 at pad edge; SOFTNESS = mean of (vy,vx,tilt) quality vs MK1_OK; FUEL = frac of FUEL0 left.
  Verified in code: PERFECT=3574, GOOD=2467, ROUGH=1242 (a great landing dwarfs a sloppy one).
- **Medals**: PRECISION (<=8 m off), FEATHER (contact speed hypot(vy,vx) <=1.5 m/s + upright), EFFICIENCY
  (>=55% tank). All three = PERFECT TOUCHDOWN. Grades: PERFECT / FLAWLESS / GREAT / GOOD / ROUGH BUT DOWN.
- **Bullseye rings**: BULLSEYE (<=5 m) / ON THE PAD (<=12 m) / PAD EDGE (<=30 m), shown on the scorecard.
- **evalTouchdown mars path** now routes to `mk1EvalTouchdown()`; ocean/tower path byte-unchanged (early return).
- **JUICE**: win = green screen-flash (`drawMK1Flash`) + `shakeT` + playChime/`mk1PerfectChime` (major-triad
  arpeggio on perfect) + a hard contact regolith burst into your `mk1Dust` array (`mk1TouchdownDust`, add-only).
  Crash = `mk1Crash`: red flash + hard `shakeT=0.7` + spawnExplosion + playExplosion + a wry per-failure line
  (hot/drift/tip/miss) + failure telemetry. Uses A5's `shakeT` hook as offered.
- **drawDone mars block**: grade banner + medal chips (`drawMK1Scorecard`), gated `mode==='mars' && ok &&
  result.mk1`; grade-flavored sign-off + a "chase the other medals" replay hook.
- NEW globals/fns/consts (all `MK1_`/`mk1` prefixed): `mk1FlashT`/`mk1FlashCol`, `mk1Score`, `clamp01`,
  `mk1EvalTouchdown`, `mk1Crash`, `mk1PickCrashLine`, `MK1_CRASH_LINES`, `mk1PerfectChime`, `mk1TouchdownDust`,
  `drawMK1Flash`, `drawMK1Scorecard`, `MK1_MEDAL_STYLE`, `MK1_RING_*`, `MK1_MEDAL_*`, `MK1_W_*`. Per-run state
  lives on `result.mk1` (set after finish()) — NO new `b`-field, so NO newRun init line needed from you.
- Testing-only `testing/a4_score_probe.py` (--preset perfect/good/rough/crash) drives the real evalTouchdown
  mars path + screenshots the scorecard. Not part of the game; does not affect the gate.
- Green gate PASS; mars runtime line: `errs=0 warns=0 nan_draw=0 ctx_unbal=0 ctx_underflow=0 landed=True`.
  ui-scan `done-mars-win` clean. Screenshots: testing/frames/a4_done_{perfect,good,rough,crash}.png.
