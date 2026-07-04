import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot_cdp import launch_chrome, discover_page_ws, CDP
GAME = r"C:\Users\nmurcin\Lumen\local\blue-origin-landings\index.html"
PORT = 9534
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frames", "glide_new.png")
# Hold a mid-glide state AND report the booster's on-screen pixel pos so we can verify the localizer
# is actually being drawn (read window.__loc set from inside a temporary hook on the anchor).
SEED = r"""
(function(){
function loop(){try{ if(typeof scene!=='undefined'&&scene==='flying'&&typeof b!=='undefined'&&b){
 b.opening=false; b.openT=999; b.openMeco=true; b.openSep=true;
 b.y=5200; b.vx=90; b.vy=-135; b.ang=0.5; b.angv=0; b.thr=0; b.fuel=Math.max(b.fuel,30000); b.heatFrac=0; b.damage=0;
 // expose the booster screen pos + the live miss the localizer uses
 try{ window.__bsx=w2sX(b.x); window.__bsy=w2sY(b.y+curveOff(b.x));
   var tj=predictTrajectory(); var last=tj&&tj.length?tj[tj.length-1]:null;
   window.__miss=(last&&last.y<=50)?Math.round(deckX()-last.x):null; }catch(e){}
}}catch(e){} requestAnimationFrame(loop);} requestAnimationFrame(loop);return true;})()
"""
READ = "(function(){return JSON.stringify({bsx:window.__bsx,bsy:window.__bsy,miss:window.__miss,W:W,H:H});})()"
p = launch_chrome(f"file:///{GAME.replace(chr(92),'/')}?play=ocean", port=PORT, headless=True)
try:
    ws = discover_page_ws(PORT, timeout=25); cdp = CDP(ws); cdp.enable_page(); time.sleep(1.6)
    cdp.evaluate(SEED); time.sleep(2.5)
    st = json.loads(cdp.evaluate(READ) or "{}")
    print("booster screen pos:", st.get("bsx"), st.get("bsy"), "| localizer miss=", st.get("miss"), "| canvas", st.get("W"), st.get("H"))
    n = cdp.screenshot(OUT); print("wrote", OUT, n, "bytes")
finally:
    try: cdp.close()
    except Exception: pass
    p.terminate()
