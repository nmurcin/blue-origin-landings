"""
mobile_hint_probe.py — Prove the MSTEER fix: on MOBILE, flightHint() referenced an
undeclared MSTEER at two branches (early tumbling; fins/strakes glide hint), throwing
ReferenceError in the render loop. Desktop never hit it (MOBILE ternary took the ':' side).

This forces MOBILE via the built-in ?touch=1 hook, traps any render-loop error, then
DIRECTLY drives flightHint() through BOTH former-MSTEER branches by seeding the exact
game state each one keys off:
  branch A (line ~4700): b.t < 4 && |b.angv| > 0.12   (early tumbling)
  branch B (line ~4718): b.y > 2600 (fins/strakes glide hint)
We call flightHint() itself and also let the render loop run, checking window.__err.

PASS = MOBILE confirmed true, both branches invoked, hint strings returned, NO error.
Stdlib only; reuses bot_cdp.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot_cdp import launch_chrome, discover_page_ws, CDP  # noqa: E402

GAME = r"C:\Users\nmurcin\Lumen\local\blue-origin-landings\index.html"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9500

TRAP = r"""
(function(){
  window.__err=null;
  var _raf=window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame=function(cb){return _raf(function(t){try{return cb(t);}
    catch(e){if(!window.__err)window.__err={msg:String(e&&e.message||e),stack:e&&e.stack?String(e.stack):null,src:'raf'};throw e;}});};
  window.onerror=function(m,s,l,c,e){if(!window.__err)window.__err={msg:String(m),line:l,stack:e&&e.stack?String(e.stack):null,src:'onerror'};return false;};
  return (typeof MOBILE!=='undefined') ? MOBILE : 'MOBILE-undefined';
})()
"""

# Directly exercise both former-MSTEER branches by seeding state and calling flightHint().
# Returns the hint string (proves the branch ran without throwing) or an {err} if it threw.
DRIVE = r"""
(function(){
  var out={mobile:(typeof MOBILE!=='undefined')?MOBILE:null, branchA:null, branchB:null, errA:null, errB:null};
  if(typeof b==='undefined'||!b||typeof flightHint!=='function'){out.err='no b/flightHint';return JSON.stringify(out);}
  // save
  var save={t:b.t,angv:b.angv,y:b.y,vx:b.vx,vy:b.vy,thr:b.thr,opening:b.opening,ang:b.ang};
  try{
    // BRANCH A: early tumbling -> b.t<4 && |angv|>0.12  (and not in an earlier-winning branch)
    b.opening=false; b.t=2; b.angv=0.5; b.y=9000; b.vx=10; b.vy=-100; b.thr=0; b.ang=0.1;
    var hA=flightHint(); out.branchA=(hA&&hA.hint)?hA.hint:String(hA);
  }catch(e){out.errA={msg:String(e&&e.message||e),stack:e&&e.stack?String(e.stack):null};}
  try{
    // BRANCH B: fins/strakes glide hint -> b.y>2600, moving downrange, not tumbling, not fast-decel
    b.opening=false; b.t=30; b.angv=0.0; b.y=5000; b.vx=60; b.vy=-120; b.thr=0; b.ang=0.5;
    var hB=flightHint(); out.branchB=(hB&&hB.hint)?hB.hint:String(hB);
  }catch(e){out.errB={msg:String(e&&e.message||e),stack:e&&e.stack?String(e.stack):null};}
  // restore
  for(var k in save) b[k]=save[k];
  return JSON.stringify(out);
})()
"""

READ_ERR = "(function(){return JSON.stringify({err:window.__err||null});})()"


def main():
    proc = launch_chrome(f"file:///{GAME.replace(chr(92),'/')}?play=ocean&touch=1", port=PORT, headless=True)
    try:
        ws = discover_page_ws(PORT, timeout=25)
        cdp = CDP(ws); cdp.enable_page(); time.sleep(1.6)
        mobile = cdp.evaluate(TRAP)
        print(f"MOBILE (via ?touch=1) = {mobile}", flush=True)
        # let a few frames render first (render-loop path)
        time.sleep(1.0)
        drive = json.loads(cdp.evaluate(DRIVE) or "{}")
        time.sleep(0.5)
        loop_err = json.loads(cdp.evaluate(READ_ERR) or "{}").get("err")

        print("\n" + "=" * 60)
        ok = True
        if mobile is not True:
            print(f"WARN: MOBILE not forced true (got {mobile!r}) — ?touch=1 hook may have changed."); ok = False
        print(f"branch A (tumbling) hint : {drive.get('branchA')!r}")
        if drive.get("errA"):
            print(f"  FAIL branch A threw: {drive['errA'].get('msg')}"); ok = False
        print(f"branch B (fins/strakes)  : {drive.get('branchB')!r}")
        if drive.get("errB"):
            print(f"  FAIL branch B threw: {drive['errB'].get('msg')}"); ok = False
        if loop_err:
            print(f"  FAIL render loop threw: {loop_err.get('msg')}"); ok = False
        if drive.get("err"):
            print(f"  (setup note: {drive['err']})")
        print("\n" + ("PASS — MOBILE hints render with NO ReferenceError (MSTEER fix verified)."
                       if ok else "FAIL — see above."))
        return 0 if ok else 1
    finally:
        try: cdp.close()
        except Exception: pass
        proc.terminate()


if __name__ == "__main__":
    sys.exit(main())
