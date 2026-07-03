# Headless screenshot harness — BLUE ORIGIN LANDINGS

Capture PNG screenshots of the game canvas **without ever opening a visible
window or stealing focus** from the user's desktop. Chrome runs `--headless=new`,
so nothing is shown on screen — the harness drives it over the DevTools Protocol
and writes frames to `testing/frames/`.

- Game: `../index.html` (single-file HTML/Canvas, canvas id = `game`).
- Dev URL routing: `?play=ocean` (NG 7×2), `?play=tower` (NG 9×4), `?play=mars`
  (Blue Moon MK1) drops straight into a flying level (`scene='flying'`).
- Python: `py` (Windows launcher). **No Node, no pip deps** — stdlib only.
- Chrome: `C:\Program Files\Google\Chrome\Application\chrome.exe` (v149 tested).

## TL;DR — does the canvas render headless?

**Yes.** This is a 2D `<canvas>` game, and it paints correctly in headless Chrome
with plain `--disable-gpu`. No SwiftShader / WebGL flags are needed — the 2D
canvas backend does not require the GPU. Frames are ~110–145 KB PNGs of real
game content (verified by eye), never black.

## Quick start (copy-paste)

Single frame, 12 s of game-time into the run:

```
py testing/headless_capture.py --mode ocean --at 12000 --name ocean_burn
```

A sequence (one PNG per time point → `ocean_seq_6000ms.png`, `_12000ms.png`, …):

```
py testing/headless_capture.py --mode ocean --at 6000 12000 20000 --name ocean_seq
```

Capture when the booster first descends to a target altitude (metres):

```
py testing/headless_capture.py --mode ocean --alt 7000 --name ocean_alt --timeout 120
```

Action shot — hold the engine on (and optionally steer) while waiting:

```
py testing/headless_capture.py --mode ocean --at 30000 --name ocean_burn_active --hold-burn
py testing/headless_capture.py --mode tower --at 20000 --name tower_steer --steer R
```

Blue Moon (lunar) descent:

```
py testing/headless_capture.py --mode mars --at 8000 --name mars_descent
```

Output → `testing/frames/<name>.png`. Exit code 0 on success.

## CLI reference

| Flag | Meaning |
|------|---------|
| `--mode` | `ocean` \| `tower` \| `mars` (default `ocean`) |
| `--at N [N …]` | one or more **game-elapsed** times in ms to grab at (a sequence) |
| `--alt M` | grab once when booster altitude `b.y` first drops to ≤ M metres |
| `--name` | base filename (`<name>.png`, or `<name>_<N>ms.png` for a sequence) |
| `--hold-burn` | hold the engine on (`burnHeld`/`keys[' ']`) while waiting |
| `--steer L\|R\|N` | steering input while waiting (default `N` = none) |
| `--window WxH` | window/canvas size (default `1280x900`) |
| `--settle-ms N` | real-time ms to let rAF paint before each grab (default 120) |
| `--timeout S` | max real seconds to reach a target before giving up (default 90) |

`--at` is measured in **game time**, tracked by an injected accumulator that
sums the exact per-frame `dt` the game's `frame()` uses (`Math.min(0.05,
(now-lastT)/1000)`). Because the game runs on real-time `requestAnimationFrame`,
game-time ≈ wall-clock time, so `--at 20000` takes ~20 s to reach.

## Working Chrome flags

The harness (see `cdp.py → Chrome.launch`) uses:

```
--headless=new --disable-gpu --hide-scrollbars
--remote-debugging-port=9222 --user-data-dir=<testing/_chromeprofile_cdp>
--window-size=1280,900 --no-first-run --no-default-browser-check
--disable-extensions --mute-audio
--disable-background-timer-throttling --disable-renderer-backgrounding
--disable-backgrounding-occluded-windows
```

The throttling flags matter: headless/background tabs otherwise clamp
`requestAnimationFrame`/timers, which would slow or stall the descent.

Flags that are **NOT** needed for this game: `--use-gl=swiftshader`,
`--enable-unsafe-swiftshader`, `--disable-gpu-sandbox`. They only matter for
**WebGL**; this is a 2D canvas and paints fine without them. (If a future
version adds WebGL and frames come back black, add `--use-gl=angle
--use-angle=swiftshader` — the modern replacement for the deprecated
`--use-gl=swiftshader`.)

## Why CDP instead of one-shot `--screenshot`?

Chrome's one-shot mode —
`chrome --headless=new --screenshot=out.png --virtual-time-budget=NNNN URL` —
**does** render this canvas (proven: a 6000 ms budget produced a correct
140 KB frame). But it is **unreliable for this game** and was rejected:

- The game runs an **infinite `requestAnimationFrame` loop**. With a long
  `--virtual-time-budget`, the budget can expire while a rAF callback is still
  pending, Chrome never reaches the "quiescent" state that triggers the
  screenshot, and **no PNG is written** (observed at 10000/15000/20000/40000/
  80000 ms — all produced no file).
- Worse, each hung one-shot run **leaks a Chrome process that keeps the
  `--user-data-dir` locked**, so the *next* run fails too. We saw 26 zombie
  chrome.exe processes accumulate this way, which even made a previously-working
  6000 ms budget start failing.
- Virtual time also **does not advance the physics further** than wall-clock
  would: the game caps `dt` at 0.05 s/frame, so reaching the descent still needs
  many frames regardless of the budget number.

Driving a **persistent headless Chrome over the DevTools Protocol** (a
stdlib-only client in `cdp.py`) is deterministic instead: we load the page, poll
the live `scene`/`b.y`/game-time via `Runtime.evaluate`, and call
`Page.captureScreenshot` exactly when the target condition is met. One clean
process, torn down via `Browser.close` at the end.

`cdp.py` implements a minimal RFC 6455 client WebSocket (handshake + masked text
frames + ping/pong) plus a tiny CDP request/response + event loop. No external
dependencies.

## Gotchas

- **Descent is slow & climbs first.** The booster modes open with a *mated-stack
  ascent* (`b.opening`) that climbs past apogee before falling. In the first
  ~20 s of game-time the altitude *increases* (e.g. 23 km → 25 km). To grab a
  true mid/late descent, use a large `--at` (e.g. 60000+) with a matching
  `--timeout`, or `--alt` with a generous `--timeout`. Hands-off (no burn) the
  booster descends slowly — expect only ~7–10 km after 90–120 s.
- **Stale Chrome locks the profile.** If a run dies uncleanly, a leftover
  chrome.exe can hold `_chromeprofile_cdp`. Clear it:
  `Get-Process chrome | Stop-Process -Force` (PowerShell). The harness closes
  Chrome via `Browser.close` in a `finally`, so clean runs don't leak.
- **Port in use.** Default DevTools port is 9222; pass `--port` if it clashes.
- **`--settle-ms`** gives rAF a couple of frames to paint the newest state
  before the grab; bump it if a frame looks a step stale.
- **Tiny PNG warning.** The harness warns if any PNG is < 3000 bytes (a likely
  blank/black frame). In practice frames are 110–145 KB.

## Files

- `headless_capture.py` — the CLI harness (this is the deliverable).
- `cdp.py` — stdlib-only Chrome DevTools Protocol + WebSocket client.
- `frames/` — captured PNGs.
- `_chromeprofile_cdp/` — throwaway Chrome user-data-dir (safe to delete).

## Do NOT

- Do not edit `../index.html` or any game code — the harness is read-only w.r.t.
  the game (it only injects input/telemetry probes at runtime in the headless
  tab, never on disk).
