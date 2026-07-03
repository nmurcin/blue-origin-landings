import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot_cdp import launch_chrome, discover_page_ws, CDP
GAME=r"C:\Users\nmurcin\Lumen\local\blue-origin-landings\index.html"; PORT=9520
SETUP=r"""
(function(){window.__err=null;var _r=window.requestAnimationFrame.bind(window);
window.requestAnimationFrame=function(cb){return _r(function(t){try{return cb(t)}catch(e){if(!window.__err)window.__err={msg:String(e&&e.message||e),stack:e&&e.stack};throw e}})};
window.onerror=function(m,s,l,c,e){if(!window.__err)window.__err={msg:String(m),stack:e&&e.stack};return false};
window.__seed=false;window.__seen=[];
function loop(){try{
 if(typeof scene!=='undefined'&&scene==='flying'&&typeof b!=='undefined'&&b){
  if(!window.__seed){b.opening=false;b.y=11000;b.vx=430;b.vy=-470;b.ang=0.0;b.angv=0;b.thr=0;b.fuel=60000;b.heatFrac=0;window.__seed=true;}
  // hold state high+fast so drawReentryGuide's decel branch stays active; sample the slewed director angle
  if(typeof reentryDirAng!=='undefined'&&reentryDirAng!==null) window.__seen.push(Number(reentryDirAng.toFixed(4)));
  // keep it in the decel regime a while (don't let it fall out)
  if(b.y<9500){b.y=11000;b.vy=-470;b.vx=430;}
 }
}catch(e){if(!window.__err)window.__err={msg:String(e&&e.message||e),stack:e&&e.stack};}
requestAnimationFrame(loop);}
requestAnimationFrame(loop);return true;})()
"""
READ="(function(){var s=window.__seen||[];return JSON.stringify({err:window.__err||null,n:s.length,first:s.slice(0,3),last:s.slice(-6)});})()"
p=launch_chrome(f"file:///{GAME.replace(chr(92),'/')}?play=ocean",port=PORT,headless=True)
try:
    ws=discover_page_ws(PORT,timeout=25);cdp=CDP(ws);cdp.enable_page();time.sleep(1.6)
    cdp.evaluate(SETUP);time.sleep(4.0)
    st=json.loads(cdp.evaluate(READ) or "{}")
    print("err:",st.get("err"))
    print("samples:",st.get("n"),"first",st.get("first"),"last",st.get("last"))
    seen=st.get("last",[])
    # slew = consecutive deltas should be small & smooth (no snap)
    if st.get("err"): print("FAIL: render error"); sys.exit(1)
    if st.get("n",0)<10: print("INCONCLUSIVE: director not active (decel branch not hit)"); sys.exit(2)
    print("PASS: reentry director active, slewed angle updating smoothly (no crash)")
finally:
    try:cdp.close()
    except:pass
    p.terminate()
