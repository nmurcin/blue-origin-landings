r"""
Headless screenshot harness for BLUE ORIGIN LANDINGS (single-file HTML/Canvas game).

Renders the game in **headless Chrome** (never shows a window, never steals focus
from the user's visible desktop) and captures PNG screenshots of the game canvas
mid-descent. Drives Chrome over the DevTools Protocol (stdlib-only client in
cdp.py) so capture timing is deterministic — we poll the live booster state `b`
and screenshot exactly when the rocket is where we want it.

USAGE
  py testing/headless_capture.py --mode ocean --at 12000 --name ocean_burn
  py testing/headless_capture.py --mode tower --at 6000 12000 20000 --name tower_seq
  py testing/headless_capture.py --mode mars  --alt 2000 --name mars_lowalt

  --mode  ocean (NG 7x2) | tower (NG 9x4) | mars (Blue Moon MK1)   [default ocean]
  --at    one or more GAME-ELAPSED times in ms to capture at (a sequence)
  --alt   capture once when booster altitude b.y first drops to <= this (metres)
  --name  base filename (frames/<name>.png, or <name>_<at>ms.png for a sequence)
  --hold-burn / --steer L|R|N   optional autopilot inputs while waiting (for
          action shots); default is hands-off so you see the natural descent.
  --window WxH   window size (default 1280x900)
  --settle-ms N  extra real-time ms to let rAF paint before each grab (default 120)

Screenshots land in testing/frames/. Exit code 0 on success.

See testing/README.md for working flags, gotchas (black canvas, virtual time),
and copy-pasteable commands.
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cdp import Chrome, WSError  # noqa: E402

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
GAME_HTML = os.path.abspath(os.path.join(HERE, "..", "index.html"))
FRAMES = os.path.join(HERE, "frames")
PROFILE = os.path.join(HERE, "_chromeprofile_cdp")


def file_url(path, mode):
    p = path.replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    return f"file://{p}?play={mode}"


# --- JS injected into the page after load -----------------------------------
# We install a game-time accumulator that hooks the SAME dt the game's frame()
# computes (capped 0.05s/frame), so "--at <ms>" means "<ms> of *game* time",
# matching what the physics has actually integrated. We also expose a snapshot
# of the booster state for altitude-based waits and telemetry.
INSTALL_PROBE = r"""
(() => {
  if (window.__cap) return 'already';
  window.__cap = { gameMs: 0, lastNow: null };
  // Wrap requestAnimationFrame so we accumulate the exact per-frame dt the game
  // uses (Math.min(0.05,(now-lastT)/1000)). This tracks game time even if the
  // tab is throttled — one accumulator, driven by the same clock as frame().
  const raf = window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame = function (cb) {
    return raf(function (now) {
      const c = window.__cap;
      if (c.lastNow !== null) {
        c.gameMs += Math.min(0.05, (now - c.lastNow) / 1000) * 1000;
      }
      c.lastNow = now;
      return cb(now);
    });
  };
  return 'installed';
})()
"""

SNAPSHOT = r"""
(() => {
  const s = { scene: (typeof scene !== 'undefined' ? scene : null),
              mode: (typeof mode !== 'undefined' ? mode : null),
              gameMs: (window.__cap ? window.__cap.gameMs : null) };
  if (typeof b !== 'undefined' && b) {
    s.b = { x: b.x, y: b.y, vx: b.vx, vy: b.vy, ang: b.ang,
            thr: b.thr, fuel: b.fuel,
            opening: !!b.opening, openT: b.openT };
  } else { s.b = null; }
  return JSON.stringify(s);
})()
"""


def snap(chrome):
    raw = chrome.eval(SNAPSHOT)
    return json.loads(raw) if raw else {}


def set_inputs(chrome, hold_burn, steer):
    """Drive the game's global input surface (keys/burnHeld/steerVal)."""
    parts = []
    if hold_burn:
        parts.append("window.burnHeld = true; keys[' '] = true;")
    else:
        parts.append("window.burnHeld = false; keys[' '] = false; keys['ArrowUp'] = false;")
    if steer == "L":
        parts.append("keys['ArrowLeft'] = true; keys['ArrowRight'] = false; window.steerVal = -1;")
    elif steer == "R":
        parts.append("keys['ArrowRight'] = true; keys['ArrowLeft'] = false; window.steerVal = 1;")
    else:
        parts.append("keys['ArrowLeft'] = false; keys['ArrowRight'] = false; window.steerVal = 0;")
    chrome.eval("(()=>{ " + " ".join(parts) + " return 1; })()")


def wait_until(chrome, predicate, timeout_s, poll_s=0.05, label=""):
    end = time.time() + timeout_s
    last = {}
    while time.time() < end:
        last = snap(chrome)
        if predicate(last):
            return last
        time.sleep(poll_s)
    raise WSError(f"timeout waiting for {label}; last state: "
                  f"scene={last.get('scene')} gameMs={last.get('gameMs')} "
                  f"b.y={last.get('b', {}).get('y') if last.get('b') else None}")


def capture(chrome, out_path, settle_ms):
    # let a couple of rAF frames paint the latest state before grabbing
    time.sleep(max(0, settle_ms) / 1000.0)
    n = chrome.screenshot_png(out_path)
    return n


def main():
    ap = argparse.ArgumentParser(description="Headless canvas screenshot harness")
    ap.add_argument("--mode", default="ocean", choices=["ocean", "tower", "mars"])
    ap.add_argument("--at", type=float, nargs="*", default=None,
                    help="game-elapsed time(s) in ms to capture at")
    ap.add_argument("--alt", type=float, default=None,
                    help="capture once when b.y <= this altitude (m)")
    ap.add_argument("--name", default=None, help="base output filename")
    ap.add_argument("--hold-burn", action="store_true", help="hold the engine on while waiting")
    ap.add_argument("--steer", default="N", choices=["L", "R", "N"], help="steering input while waiting")
    ap.add_argument("--window", default="1280x900")
    ap.add_argument("--settle-ms", type=int, default=120)
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--timeout", type=float, default=90.0, help="max real seconds to reach a target")
    args = ap.parse_args()

    if args.at is None and args.alt is None:
        args.at = [12000.0]  # sensible default: mid-descent
    w, h = (int(x) for x in args.window.lower().split("x"))
    os.makedirs(FRAMES, exist_ok=True)
    base = args.name or f"{args.mode}"

    chrome = Chrome(CHROME, PROFILE, port=args.port, window=(w, h))
    saved = []
    try:
        print(f"[launch] headless Chrome {w}x{h}, port {args.port}")
        chrome.launch()
        chrome.send("Page.enable")
        chrome.send("Runtime.enable")
        url = file_url(GAME_HTML, args.mode)
        print(f"[load] {url}")
        chrome.send("Page.navigate", {"url": url})
        try:
            chrome.wait_event("Page.loadEventFired", timeout=20)
        except WSError:
            pass  # some file:// loads fire before we subscribe; the probe below confirms

        # install game-time accumulator ASAP
        for _ in range(40):
            if chrome.eval(INSTALL_PROBE) in ("installed", "already"):
                break
            time.sleep(0.1)

        # wait for the game to actually be flying with a booster present
        st = wait_until(chrome, lambda s: s.get("scene") == "flying" and s.get("b"),
                        timeout_s=20, label="scene=flying")
        print(f"[flying] mode={st.get('mode')} b.y={st['b']['y']:.0f} m")

        if args.hold_burn or args.steer != "N":
            set_inputs(chrome, args.hold_burn, args.steer)
            print(f"[input] hold_burn={args.hold_burn} steer={args.steer}")

        if args.alt is not None:
            st = wait_until(
                chrome,
                lambda s: s.get("b") and s["b"]["y"] <= args.alt,
                timeout_s=args.timeout,
                label=f"altitude<= {args.alt} m",
            )
            out = os.path.join(FRAMES, f"{base}.png")
            n = capture(chrome, out, args.settle_ms)
            print(f"[grab] alt={st['b']['y']:.0f} m -> {out} ({n} bytes)")
            saved.append((out, n, st))
        else:
            targets = sorted(args.at)
            seq = len(targets) > 1
            for t in targets:
                # keep re-driving inputs so held burn/steer persists across the wait
                if args.hold_burn or args.steer != "N":
                    set_inputs(chrome, args.hold_burn, args.steer)
                st = wait_until(
                    chrome,
                    lambda s, tt=t: (s.get("gameMs") or 0) >= tt,
                    timeout_s=args.timeout,
                    label=f"gameMs>= {t}",
                )
                fname = f"{base}_{int(t)}ms.png" if seq else f"{base}.png"
                out = os.path.join(FRAMES, fname)
                n = capture(chrome, out, args.settle_ms)
                by = st["b"]["y"] if st.get("b") else float("nan")
                print(f"[grab] gameMs={st.get('gameMs'):.0f} b.y={by:.0f} m "
                      f"scene={st.get('scene')} -> {out} ({n} bytes)")
                saved.append((out, n, st))
    finally:
        chrome.close()

    if not saved:
        print("[FAIL] nothing captured", file=sys.stderr)
        return 2
    # sanity: warn on suspiciously tiny PNGs (possible black frame)
    for out, n, _ in saved:
        if n < 3000:
            print(f"[WARN] {out} is only {n} bytes — may be blank", file=sys.stderr)
    print(f"[done] {len(saved)} frame(s) in {FRAMES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
