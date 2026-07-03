"""
bot_playtest.py — Autonomous game-playing bot for Blue Origin Landings.

APPROACH 1 (primary, WORKING): drives the REAL game in headless Chrome over the
DevTools Protocol (raw WebSocket, Python stdlib only — see bot_cdp.py).

Design (why it works): the game physics runs at its own ~120 Hz tied to
requestAnimationFrame. An EXTERNAL Python control loop at ~12 Hz aliases the
decel-burn/glide phase logic and oscillates. So instead we INJECT an in-page
autopilot (bot_autopilot.js) that runs inside the page's own rAF loop and sets
the game's `keys` map every frame, faithfully mirroring the winning autopilot in
local/tmp/deck_geometry_both.py (decel-burn -> 20deg glide -> terminal arrest).

Python then only:
  - monitors live state b via Runtime.evaluate (~10 Hz),
  - logs a telemetry CSV: t,x,y,vx,vy,ang_deg,thr,fuel,deckX,gap,phase,scene,
  - captures Page.captureScreenshot at key moments (handoff, decel burn, glide,
    terminal, low-alt, touchdown),
  - detects window.__botDone (scene->done) and reports WON/LOST + touchdown vy/vx.

Usage:
    py bot_playtest.py [ocean|tower|mars] [--show]   (default: ocean)
        --show  visible Chrome window instead of --headless=new

Deliverables: testing/frames/*.png + testing/bot_telemetry_<mode>.csv.
Does NOT edit or commit game code.
"""
import csv
import json
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot_cdp import launch_chrome, discover_page_ws, CDP  # noqa: E402
from bot_autopilot import AUTOPILOT_JS  # noqa: E402

GAME = r"C:\Users\nmurcin\Lumen\local\blue-origin-landings\index.html"
HERE = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(HERE, "frames")
os.makedirs(FRAMES, exist_ok=True)
# Random high port per run so the bot never collides with the user's own Chrome
# or a stale bot instance holding 9222.
PORT = random.randint(9300, 9899)
DECKX = {"ocean": 7050, "tower": 8350, "mars": 0}

READ_JS = (
    "(function(){try{"
    "if(typeof b==='undefined'||!b)return JSON.stringify({noB:true,"
    "scene:(typeof scene!=='undefined'?scene:null),done:window.__botDone||null});"
    "var dx=(typeof deckX==='function')?deckX():null;"
    "return JSON.stringify({x:b.x,y:b.y,vx:b.vx,vy:b.vy,ang:b.ang,thr:b.thr,"
    "fuel:b.fuel,opening:!!b.opening,phase:window.__botPhase||null,"
    "damage:b.damage||0,heatFrac:b.heatFrac||0,deckX:dx,"
    "scene:(typeof scene!=='undefined'?scene:null),done:window.__botDone||null});"
    "}catch(e){return JSON.stringify({err:''+e});}})()"
)


def run(mode="ocean", headless=True, max_seconds=210.0):
    url = "file:///" + GAME.replace("\\", "/") + f"?play={mode}"
    print(f"[bot] launching {'headless ' if headless else ''}Chrome: {url}")
    proc = launch_chrome(url, port=PORT, headless=headless)
    csv_path = os.path.join(HERE, f"bot_telemetry_{mode}.csv")
    frames = []
    outcome = {"result": "TIMEOUT"}
    try:
        ws = discover_page_ws(PORT)
        cdp = CDP(ws)
        cdp.enable_page()
        time.sleep(1.2)  # let the game boot + start the run

        # sanity: confirm we connected to a fresh run of the requested mode
        chk = json.loads(cdp.evaluate(
            "(function(){try{return JSON.stringify({mode:(typeof mode!=='undefined'?mode:null),"
            "scene:(typeof scene!=='undefined'?scene:null),y:(typeof b!=='undefined'&&b?b.y:null)});}"
            "catch(e){return JSON.stringify({err:''+e});}})()"))
        print(f"[bot] connected page: {chk}")
        if chk.get("mode") != mode:
            raise RuntimeError(f"connected to wrong page: expected mode={mode}, got {chk}")

        # install the in-page autopilot (runs in the game's own rAF loop)
        inst = cdp.evaluate(AUTOPILOT_JS)
        print(f"[bot] autopilot: {inst}")

        f = open(csv_path, "w", newline="", encoding="utf-8")
        w = csv.writer(f)
        w.writerow(["t", "x", "y", "vx", "vy", "ang_deg", "thr", "fuel",
                    "deckX", "gap", "phase", "scene", "action"])

        t0 = time.time()
        captured = set()
        last_phase = None
        consecutive_errs = 0
        while True:
            now = time.time() - t0
            if now > max_seconds:
                outcome = {"result": "TIMEOUT", "t": round(now, 1)}
                break
            try:
                st = json.loads(cdp.evaluate(READ_JS))
                consecutive_errs = 0
            except Exception as e:  # noqa: BLE001
                consecutive_errs += 1
                if consecutive_errs >= 8:
                    outcome = {"result": "CONN_LOST", "t": round(now, 1),
                               "note": f"{consecutive_errs} consecutive CDP errors: {e}"}
                    print("[bot] connection lost, aborting:", e)
                    break
                print("[bot] read hiccup:", e)
                time.sleep(0.15)
                continue
            if st.get("err"):
                print("[bot] JS err:", st["err"]); time.sleep(0.1); continue

            done = st.get("done")
            scene = st.get("scene")

            if st.get("noB"):
                if done or scene == "done":
                    outcome = _finalize(done, mode)
                    p = os.path.join(FRAMES, f"bot_{mode}_5_touchdown.png")
                    try:
                        cdp.screenshot(p); frames.append(p)
                    except Exception:  # noqa: BLE001
                        pass
                    break
                time.sleep(0.1); continue

            dx = st["deckX"] if st.get("deckX") is not None else DECKX[mode]
            gap = dx - st["x"]
            phase = st.get("phase")

            w.writerow([f"{now:.2f}", f"{st['x']:.1f}", f"{st['y']:.1f}",
                        f"{st['vx']:.2f}", f"{st['vy']:.2f}",
                        f"{st['ang']*180/math.pi:.2f}", f"{st['thr']:.3f}",
                        f"{st['fuel']:.0f}", dx, f"{gap:.1f}",
                        phase, scene, phase])

            if done or scene == "done":
                outcome = _finalize(done, mode, st)
                p = os.path.join(FRAMES, f"bot_{mode}_5_touchdown.png")
                cdp.screenshot(p); frames.append(p)
                break

            # ---- key-moment screenshots ----
            def grab(tag, name):
                if tag not in captured:
                    pth = os.path.join(FRAMES, name)
                    cdp.screenshot(pth); frames.append(pth); captured.add(tag)

            if phase in ("COAST_UP", "GLIDE", "MARS_COAST"):
                grab("handoff", f"bot_{mode}_1_handoff.png")
            if phase == "BLEED":
                grab("bleed", f"bot_{mode}_2_bleed.png")
            if st["y"] < 8000:
                grab("descent", f"bot_{mode}_3_descent.png")
            if phase in ("TERMINAL", "MARS_BURN"):
                grab("terminal", f"bot_{mode}_4_terminal.png")
            if st["y"] < 400:
                grab("lowalt", f"bot_{mode}_4b_lowalt.png")

            if phase != last_phase:
                print(f"[bot] t={now:5.1f}s y={st['y']:8.0f} vy={st['vy']:7.1f} "
                      f"vx={st['vx']:7.1f} gap={gap:8.0f} fuel={st['fuel']:6.0f} "
                      f"ang={st['ang']*180/math.pi:6.1f} -> {phase}")
                last_phase = phase

            time.sleep(0.10)

        f.close()
        # pull the in-page trace as a cross-check (optional)
        try:
            trace = cdp.evaluate("JSON.stringify(window.__botTrace||[])")
            with open(os.path.join(HERE, f"bot_trace_{mode}.json"), "w", encoding="utf-8") as tf:
                tf.write(trace)
        except Exception:  # noqa: BLE001
            pass
        cdp.close()
    finally:
        proc.terminate()
        time.sleep(0.4)
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass

    print("\n[bot] ================ OUTCOME ================")
    for k, v in outcome.items():
        print(f"[bot]   {k:8}= {v}")
    print("[bot] telemetry CSV:", csv_path)
    print("[bot] frames:")
    for p in frames:
        sz = os.path.getsize(p) if os.path.exists(p) else 0
        print(f"        {p}  ({sz} bytes)")
    return outcome, csv_path, frames


def _finalize(done, mode, st=None):
    src = done if isinstance(done, dict) else (st or {})
    ok = src.get("ok")
    res = (done or {}).get("result") if isinstance(done, dict) else None
    if res in ("WON", "LOST"):
        pass
    else:
        res = "WON" if ok else "LOST"
    dx = src.get("deckX") or DECKX[mode]
    x = src.get("x")
    out = {"result": res, "ok": ok}
    if x is not None:
        out.update({
            "land_x": round(x, 1),
            "vy_touch": round(-src.get("vy", 0), 2),
            "vx_touch": round(src.get("vx", 0), 2),
            "ang_deg": round(src.get("ang", 0) * 180 / math.pi, 2),
            "fuel": round(src.get("fuel", 0)),
            "offset_from_deck": round(abs(x - dx), 1),
            "deckX": dx,
        })
    return out


if __name__ == "__main__":
    mode = "ocean"
    headless = True
    for a in sys.argv[1:]:
        if a in ("ocean", "tower", "mars"):
            mode = a
        elif a == "--show":
            headless = False
    run(mode, headless=headless)
