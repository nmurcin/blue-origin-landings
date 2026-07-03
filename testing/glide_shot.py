import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot_cdp import launch_chrome, discover_page_ws, CDP
GAME = r"C:\Users\nmurcin\Lumen\local\blue-origin-landings\index.html"
PORT = 9532
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frames", "glide_new.png")
# FORCE and HOLD a mid-glide state every frame so the steer-director stays active + on-screen,
# and clear the opening/handoff beat so its "YOU HAVE CONTROL" text doesn't win flightHint.
SEED = r"""
(function(){
function loop(){try{ if(typeof scene!=='undefined'&&scene==='flying'&&typeof b!=='undefined'&&b){
 b.opening=false; b.openT=999; b.openMeco=true; b.openSep=true;
 b.y=5200; b.vx=110; b.vy=-140; b.ang=0.5; b.angv=0; b.thr=0; b.fuel=Math.max(b.fuel,30000); b.heatFrac=0; b.damage=0;
}}catch(e){} requestAnimationFrame(loop);} requestAnimationFrame(loop);return true;})()
"""
p = launch_chrome(f"file:///{GAME.replace(chr(92),'/')}?play=ocean", port=PORT, headless=True)
try:
    ws = discover_page_ws(PORT, timeout=25); cdp = CDP(ws); cdp.enable_page(); time.sleep(1.6)
    cdp.evaluate(SEED); time.sleep(2.5)
    n = cdp.screenshot(OUT); print("wrote", OUT, n, "bytes")
finally:
    try: cdp.close()
    except Exception: pass
    p.terminate()
