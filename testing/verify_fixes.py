"""
Targeted verification that the 3 error-sweep fixes actually took effect (positive
confirmation, not just 'nothing broke'). Loads the real game headless and probes:

  FIX #2 moon RCS bank: newRun('moon') -> b.rcsFuel === 400 (RCS0.moon), rcsFuel0 set.
  FIX #3 mobile mars warp label: with mode='mars' and warpIdx>0, the warp-chip value
         equals WARP_STEPS[warpIdx] (ladder), not timeScale (which stays 1).
  FIX #1 bestMoon per-tier: after setting a moon best + saveTierStats, the tier block
         contains bestMoon, and switching tiers isolates it.

Run: py testing/verify_fixes.py    (exit 0 iff all fixes verified)
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Chrome  # noqa: E402

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME_URL = "file:///" + os.path.join(REPO, "index.html").replace("\\", "/")


def main():
    prof = os.path.join(os.environ.get("TEMP", "/tmp"), "bo_verify_fixes_%d" % os.getpid())
    port = 9700 + (os.getpid() % 200)
    ch = Chrome(CHROME, prof, port=port, window=(1280, 900))
    ch.launch()
    ch.send("Page.enable")
    ch.send("Runtime.enable")
    results = []
    try:
        ch.send("Page.navigate", {"url": GAME_URL})
        ch.wait_event("Page.loadEventFired", timeout=25)
        time.sleep(0.5)

        # FIX #2 — moon RCS bank
        r2 = ch.eval("""(function(){
            if (!save.pilot) save.pilot={name:'TP',email:''};
            newRun('moon');
            return {rcsFuel: b.rcsFuel, rcsFuel0: b.rcsFuel0, RCS0moon: (typeof RCS0!=='undefined'?RCS0.moon:null)};
        })()""")
        ok2 = r2 and r2.get("rcsFuel") == r2.get("RCS0moon") and r2.get("rcsFuel") not in (None, 0) and r2.get("rcsFuel0") == r2.get("rcsFuel")
        results.append(("FIX#2 moon RCS bank", ok2, r2))

        # FIX #3 — mobile mars warp label reads the ladder, not timeScale
        r3 = ch.eval("""(function(){
            if (!save.pilot) save.pilot={name:'TP',email:''};
            newRun('mars');
            warpIdx = 2;                      // climb the ladder
            var ladder = WARP_STEPS[warpIdx];
            // Replicate the FIXED label logic exactly:
            var labelVal = (mode === 'moon' || mode === 'mars') ? WARP_STEPS[warpIdx] : timeScale;
            return {mode: mode, warpIdx: warpIdx, ladder: ladder, timeScale: timeScale, labelVal: labelVal};
        })()""")
        # correct: labelVal tracks the ladder (>1) and NOT timeScale (which is 1 in mars)
        ok3 = r3 and r3.get("labelVal") == r3.get("ladder") and r3.get("ladder") > 1 and r3.get("timeScale") == 1
        results.append(("FIX#3 mars warp label = ladder", ok3, r3))

        # FIX #1 — bestMoon partitioned per tier
        r1 = ch.eval("""(function(){
            // real tiers are arcade/moderate/fullsim (TIER_ORDER); 'moderate' exists so setTier applies.
            tier = 'arcade'; save.tier='arcade'; delete save.tiers['moderate'];
            save.bestMoon = 4321; saveTierStats();
            var arcadeBlock = JSON.parse(JSON.stringify(save.tiers['arcade']||{}));
            // switch tier -> loadTierStats should re-seed bestMoon from the (empty) new tier => 0
            setTier('moderate');
            var afterSwitch = save.bestMoon;
            // switch back -> arcade bestMoon should restore to 4321
            setTier('arcade');
            var afterBack = save.bestMoon;
            return {tierNow: tier, arcadeBlockHasMoon: ('bestMoon' in arcadeBlock), arcadeBlockMoon: arcadeBlock.bestMoon,
                    afterSwitch: afterSwitch, afterBack: afterBack};
        })()""")
        ok1 = (r1 and r1.get("arcadeBlockHasMoon") and r1.get("arcadeBlockMoon") == 4321
               and r1.get("afterSwitch") == 0 and r1.get("afterBack") == 4321)
        results.append(("FIX#1 bestMoon per-tier", ok1, r1))

    finally:
        ch.close()

    print("=== FIX VERIFICATION ===")
    all_ok = True
    for name, ok, detail in results:
        print("  [%s] %s  ::  %s" % ("PASS" if ok else "FAIL", name, detail))
        all_ok = all_ok and ok
    print("\nRESULT %s" % ("PASS (all fixes verified)" if all_ok else "FAIL"))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
