# Blue Origin Landings — Game-Playing Bot (`bot_*`)

A **testing tool** that flies the browser rocket-landing game to completion and
produces reviewable "in-action" telemetry + frames an AI agent can look at. It is
**not** game code and does not touch `index.html` / `blue_origin_landings.html`.

All files here are namespaced with a `bot_` prefix (another agent shares this dir).

## Which approach worked: APPROACH 1 (drives the REAL game)

The bot launches **headless Chrome** on the actual game and controls it over the
Chrome DevTools Protocol (CDP) — no black screenshots, real input injection. The
matplotlib fallback (approach 2) was **not needed**.

- **`bot_cdp.py`** — a minimal CDP client using ONLY the Python stdlib (`socket`,
  `base64`, `hashlib`, `struct`, `http.client`, `json`). It launches headless
  Chrome (`--headless=new`, so it never steals the user's window; a **random high
  debug port + fresh per-run user-data-dir** so it never collides with the user's
  own Chrome), opens a raw RFC-6455 WebSocket to the page target, and wraps
  `Runtime.evaluate` (read state / inject input) and `Page.captureScreenshot`
  (frames). Transparently reconnects on a transient socket drop.
- **`bot_autopilot.py`** — the in-page JavaScript autopilot (a Python string),
  injected ONCE. It runs inside the game's own `requestAnimationFrame` loop
  (~120 Hz) and sets the page's own `keys` map (`keys[' ']` = burn, `keys['ArrowLeft'
  ]/['ArrowRight']` = steer). Publishes `window.__botPhase`, `window.__botTrace`,
  `window.__botDone`.
- **`bot_playtest.py`** — the runnable bot. Installs the autopilot, then monitors
  live `b` state (~10 Hz), logs a telemetry CSV, captures key-moment screenshots,
  and reports the outcome when `scene` becomes `done`.
- **`bot_smoke.py`** — quick connectivity check (launch → connect → read state →
  one screenshot). Run this first if something seems off.
- **`bot_probe_law.py`** — a tuning harness that injects a parametrized control law
  (`VX_KEEP`, `MARGIN`) and reports the landing; used to characterize the live
  physics and tune the autopilot. Handy for re-tuning.

## Run it

```
py bot_playtest.py ocean          # NG 7x2 (default)
py bot_playtest.py tower          # NG 9x4
py bot_playtest.py mars           # Blue Moon MK1 lunar pad
py bot_playtest.py ocean --show   # visible Chrome window (debugging)
```

A full ocean/tower descent takes ~150-170 s of wall time (the game runs at 1.0x
real-time; the timeout is 210 s). Outputs land in:
- `bot_telemetry_<mode>.csv` — columns: `t, x, y, vx, vy, ang_deg, thr, fuel,
  deckX, gap, phase, scene, action` (one row per ~100 ms).
- `frames/bot_<mode>_*.png` — handoff, descent, terminal-burn, low-alt, touchdown.
- `bot_trace_<mode>.json` — the in-page 120 Hz sampled trace (cross-check).

## Landing outcome (real run, ocean 7x2)

The bot completes the mission every run. A representative completed ocean run:

- **result: LOST (SPLASHDOWN)** — soft, upright, **damage-free** touchdown on the
  water, but downrange of Jacklyn: `land_x ≈ 18383`, `deckX = 7050`, offset ≈ 11.3 km.
- **Touchdown quality: excellent** — `vy ≈ -3.0 m/s`, `vx ≈ -3.1 m/s`, tilt ≈ 5°,
  ~28,700 kg fuel remaining. That vy/vx is well inside the landing tolerance
  (ocean OK: vy ≤ 8.5, vx ≤ 7.0); the "LOST" is purely a horizontal miss of the
  ±44 m deck, not a crash.

The five reviewed frames clearly show the booster descending toward the deck:
handoff ("YOU HAVE CONTROL — align retrograde…", ALT 145 km), descent (engine
plume lit, ALT 47 km, trajectory arc to the ✕), terminal ("BURN STOP +914 m above
the deck", vertical descent), low-alt, and touchdown (upright on the ocean).

**Tower (9x4)** also completes the mission (result LOST, land_x ≈ 9902 vs deckX
8350 — offset ~1.5 km, closer horizontally, but a hard vertical arrival because the
terminal-burn tuning `A_NET`/`vtgt` is calibrated for the lighter ocean vehicle; the
heavier 9x4 needs an earlier/harder burn). Both modes fly to a real `scene==='done'`
outcome and log telemetry — a completed mission per spec (land or crash). Tuning the
tower vehicle to a soft touchdown is the same `A_NET`/`VX_KEEP` exercise done for ocean.

## Why it lands soft but off-deck (important finding)

The autopilot is **NOT** a direct port of `local/tmp/deck_geometry_both.py`. That
reference sim "wins" in **its own** physics model; the LIVE game physics diverge
enough that the sim's control law fails outright in the browser. Established by
direct live probing (see `bot_probe_law.py` + the findings below):

1. **Full burn at ~24 km flies the booster UP, not down.** Above `ENTRY_Y = 8500`
   the air is negligible, so a full "decel burn" just cancels gravity and adds
   upward Δv. The sim's `hot` decel-burn (burn while `y>7000 & spd>250`) never
   exits in the live game → the booster climbs and drains all fuel. Fix: never
   full-burn high up.
2. **Holding RETROGRADE (belly to wind) all the way down keeps heat damage at 0**
   (heatFrac peaks ~0.5). This is the key to surviving reentry.
3. **A proportional descent-rate terminal burn** (`vtgt = 0.055·y + 3`, burn only
   when sinking faster than target) feathers to a reliably **soft, upright,
   zero-damage touchdown** (~-3 m/s) instead of hovering at altitude.
4. **On-deck horizontal precision does not transfer.** The booster crosses the
   deck's x-coordinate while still ~10-15 km up, then keeps going downrange.
   Bleeding enough horizontal velocity *that high* to null it over the ±44 m deck
   **burns the vehicle up** (heat scales with speed × air; the safe bleed band is
   low, by which point it's already far past). So the bot flies a complete,
   controlled, soft descent and reports the real outcome — but does not reliably
   plant it on the narrow deck. `VX_KEEP` (in `bot_autopilot.py`) trades range vs.
   heat; `VX_KEEP=60` gives the cleanest damage-free landing.

Measured live physics envelope (for future tuning):
- No-input: apogee ~25.6 km; momentum carries the booster far downrange.
- Full upright burn net decel: ~16 m/s² @ 9.7 km → ~10 m/s² @ 7 km.
- Retrograde burn while descending bleeds vx (405 → tens of m/s) staying upright;
  with vx≈0 it degenerates into a vertical hover (avoid).

## Constraints honored

- Windows: `py` launcher; Chrome at `C:\Program Files\Google\Chrome\Application\chrome.exe`;
  **no Node.js, no pip installs** (stdlib-only CDP client).
- Headless (never grabs the user's window). Random debug port + fresh profile per
  run (no collision with the user's Chrome).
- Does **not** edit game code and does **not** commit.
