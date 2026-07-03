"""Smoke test: launch headless Chrome on the game, connect via CDP, read state, screenshot."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot_cdp import launch_chrome, discover_page_ws, CDP  # noqa: E402

GAME = r"C:\Users\nmurcin\Lumen\local\blue-origin-landings\index.html"
HERE = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(HERE, "frames")
os.makedirs(FRAMES, exist_ok=True)

url = "file:///" + GAME.replace("\\", "/") + "?play=ocean"
print("launching:", url)
proc = launch_chrome(url, port=9222, headless=True)
try:
    ws = discover_page_ws(9222)
    print("ws:", ws)
    cdp = CDP(ws)
    cdp.enable_page()
    # give the game a moment to boot + start the run
    time.sleep(2.5)
    val = cdp.evaluate("(function(){try{return JSON.stringify({scene:typeof scene!=='undefined'?scene:null,mode:typeof mode!=='undefined'?mode:null,hasB:typeof b!=='undefined'&&!!b,y:(typeof b!=='undefined'&&b)?b.y:null,x:(typeof b!=='undefined'&&b)?b.x:null,opening:(typeof b!=='undefined'&&b)?b.opening:null});}catch(e){return 'ERR:'+e;}})()")
    print("state:", val)
    n = cdp.screenshot(os.path.join(FRAMES, "bot_smoke.png"))
    print("screenshot bytes:", n)
    cdp.close()
finally:
    proc.terminate()
    time.sleep(0.5)
    try:
        proc.kill()
    except Exception:
        pass
print("done")
