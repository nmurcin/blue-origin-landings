r"""
A5 camera probe: place the MK1 lander directly over the pad (x=0) at a chosen
altitude and near-vertical, low-speed attitude -- the realistic terminal/hoverslam
composition that --alt drops cannot produce (a ballistic drop stays 15 km downrange).
Then let the cinematic camera lerp settle and screenshot. Verifies that the terminal
frame zooms in, leads to the pad, and composes lander + surface + beacon with headroom.

ASCII only. Windows py.

USAGE
  py testing/a5_cam_probe.py --alt 220 --name a5_over_pad_220
  py testing/a5_cam_probe.py --alt 60  --name a5_over_pad_60
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


SNAP = r"""
(() => {
  const s = { scene: (typeof scene!=='undefined'?scene:null),
              mode: (typeof mode!=='undefined'?mode:null) };
  if (typeof b!=='undefined' && b) {
    s.b = { x:b.x, y:b.y, vx:b.vx, vy:b.vy, ang:b.ang, thr:b.thr };
    s.cam = { x:cam.x, y:cam.y, s:cam.s };
  } else s.b = null;
  return JSON.stringify(s);
})()
"""


def snap(ch):
    raw = ch.eval(SNAP)
    return json.loads(raw) if raw else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alt", type=float, default=220.0)
    ap.add_argument("--offx", type=float, default=6.0, help="lander world-x offset from pad (m)")
    ap.add_argument("--vy", type=float, default=-6.0)
    ap.add_argument("--vx", type=float, default=-1.5)
    ap.add_argument("--angdeg", type=float, default=3.0)
    ap.add_argument("--thr", type=float, default=0.6)
    ap.add_argument("--name", default="a5_over_pad")
    ap.add_argument("--window", default="1280x900")
    ap.add_argument("--port", type=int, default=9223)
    ap.add_argument("--settle-ms", type=int, default=400)
    args = ap.parse_args()

    w, h = (int(x) for x in args.window.lower().split("x"))
    os.makedirs(FRAMES, exist_ok=True)
    ch = Chrome(CHROME, PROFILE, port=args.port, window=(w, h))
    try:
        ch.launch()
        ch.send("Page.enable")
        ch.send("Runtime.enable")
        url = file_url(GAME_HTML, "mars")
        print(f"[load] {url}")
        ch.send("Page.navigate", {"url": url})
        try:
            ch.wait_event("Page.loadEventFired", timeout=20)
        except WSError:
            pass

        # wait for flying + booster
        end = time.time() + 20
        st = {}
        while time.time() < end:
            st = snap(ch)
            if st.get("scene") == "flying" and st.get("b"):
                break
            time.sleep(0.05)
        if not (st.get("scene") == "flying" and st.get("b")):
            print("[FAIL] never reached flying", file=sys.stderr)
            return 2
        print(f"[flying] b.y={st['b']['y']:.0f}")

        # Inject a realistic over-the-pad terminal state, hold a light burn so the plume
        # + dust-kick show, then let the camera lerp settle over several frames.
        inject = (
            "(()=>{"
            f"b.x={args.offx}; b.y={args.alt};"
            f"b.vx={args.vx}; b.vy={args.vy};"
            f"b.ang={args.angdeg}*Math.PI/180; b.angv=0; b.thr={args.thr};"
            "window.burnHeld=true; keys[' ']=true;"
            "if (typeof snapGroundCam==='function') snapGroundCam();"
            "return 1;})()"
        )
        ch.eval(inject)
        # re-assert the state each ~frame for ~0.8 s so gravity/physics can't run it away
        # while the camera converges (we only want to judge FRAMING here, not fly it).
        t_end = time.time() + 0.8
        while time.time() < t_end:
            ch.eval(inject)
            time.sleep(0.05)
        time.sleep(max(0, args.settle_ms) / 1000.0)
        st = snap(ch)
        out = os.path.join(FRAMES, f"{args.name}.png")
        n = ch.screenshot_png(out)
        cam = st.get("cam", {})
        print(f"[grab] b=({st['b']['x']:.0f},{st['b']['y']:.0f}) "
              f"cam=({cam.get('x'):.0f},{cam.get('y'):.0f},s={cam.get('s'):.4f}) "
              f"-> {out} ({n} bytes)")
    finally:
        ch.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
