import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot_cdp import launch_chrome, discover_page_ws, CDP
GAME=r"C:\Users\nmurcin\Lumen\local\blue-origin-landings\index.html"; PORT=9540
# Let the REAL game fly its natural spawn; do a simple engine-first decel burn; measure how long the
# booster stays in the reentry regime (y>ENTRY_Y-500 and spd>250) — i.e. the phase the pilot lengthened.
AP=r"""
(function(){window.__err=null;window.__t0=null;window.__tReentry=0;window.__last=null;window.__spawnY=null;
var _r=window.requestAnimationFrame.bind(window);
window.requestAnimationFrame=function(cb){return _r(function(t){try{return cb(t)}catch(e){if(!window.__err)window.__err={msg:String(e&&e.message||e)};throw e}})};
function loop(){try{
 if(typeof scene!=='undefined'&&scene==='flying'&&typeof b!=='undefined'&&b&&typeof keys!=='undefined'&&!b.opening){
   if(window.__spawnY===null)window.__spawnY=Math.round(b.y);
   var spd=Math.hypot(b.vx,b.vy); var now=performance.now();
   if(window.__last!==null && b.y>(ENTRY_Y-500) && spd>250) window.__tReentry+=(now-window.__last)/1000;
   window.__last=now;
   // engine-first decel while high+fast
   keys['ArrowLeft']=false;keys['ArrowRight']=false;keys[' ']=false;
   if(b.y>(ENTRY_Y-500)&&spd>250){var des=Math.atan2(-b.vx,-b.vy);var dA=b.ang-des;while(dA>Math.PI)dA-=6.283;while(dA<-Math.PI)dA+=6.283;if(dA>0.05)keys['ArrowLeft']=true;else if(dA<-0.05)keys['ArrowRight']=true;keys[' ']=true;}
 }
}catch(e){if(!window.__err)window.__err={msg:String(e&&e.message||e)};}
requestAnimationFrame(loop);}
requestAnimationFrame(loop);return true;})()
"""
READ="(function(){var spd=(typeof b!=='undefined'&&b)?Math.hypot(b.vx,b.vy):null;return JSON.stringify({err:window.__err,tReentry:window.__tReentry,spawnY:window.__spawnY,y:(b?Math.round(b.y):null),spd:spd?Math.round(spd):null,scene:(typeof scene!=='undefined')?scene:null});})()"
p=launch_chrome(f"file:///{GAME.replace(chr(92),'/')}?play=ocean",port=PORT,headless=True)
try:
    ws=discover_page_ws(PORT,timeout=25);cdp=CDP(ws);cdp.enable_page();time.sleep(1.6)
    cdp.evaluate(AP)
    st={}
    for _ in range(60):
        st=json.loads(cdp.evaluate(READ) or "{}")
        if st.get("err"):print("ERR",st["err"]);break
        # stop once well past the reentry regime (into glide/low)
        if st.get("y") and st["y"]<7000 and st.get("spd") and st["spd"]<260: break
        time.sleep(0.8)
    print("spawn Y:",st.get("spawnY"),"m")
    print("time in reentry regime (y>%s, spd>250): %.1f s"%("ENTRY_Y-500", st.get("tReentry",0)))
    print("(baseline before this change was ~6-7 s; goal ~2-3x longer)")
finally:
    try:cdp.close()
    except:pass
    p.terminate()
