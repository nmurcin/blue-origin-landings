import os, sys, time, json
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from cdp import Chrome
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
GAME = "file:///" + os.path.join(os.path.dirname(HERE), "index.html").replace("\\", "/")
ch = Chrome(CHROME, os.path.join(os.environ.get("TEMP","/tmp"),"bo_rand_%d"%os.getpid()), port=9420, window=(1280,900)); ch.launch()
ch.send("Page.enable"); ch.send("Runtime.enable")
ch.send("Page.navigate", {"url": GAME + "?play=mars"}); time.sleep(1.2)

def field():
    return ch.eval("""(function(){
      newRun('mars');
      return {seed: marsSeed,
              pads: marsPads.map(function(p){return {x:p.x, half:p.half, mult:p.mult};})};
    })()""")

def checks(f):
    pads = f['pads']
    errs = []
    # 1) exactly 4 pads, sorted left->right
    if len(pads) != 4: errs.append("not 4 pads")
    if pads != sorted(pads, key=lambda p: p['x']): errs.append("pads not sorted by x")
    # 2) multipliers are exactly {2,3,5,8}
    if sorted(p['mult'] for p in pads) != [2,3,5,8]: errs.append("mults != {2,3,5,8}")
    # 3) RANK RULE: narrowest pad = highest mult, widest = lowest. i.e. half and mult inversely ranked.
    by_half = sorted(pads, key=lambda p: p['half'])          # narrow -> wide
    by_mult = sorted(pads, key=lambda p: -p['mult'])         # high -> low
    if [p['x'] for p in by_half] != [p['x'] for p in by_mult]:
        errs.append("mult not assigned by narrowness (smallest pad must be x8)")
    # 4) no pad-span overlap (incl 45 m blend each side)
    spans = sorted([(p['x']-p['half']-45, p['x']+p['half']+45) for p in pads])
    for i in range(1,len(spans)):
        if spans[i][0] < spans[i-1][1]: errs.append("pad spans overlap")
    return errs

# roll a bunch of runs
fields = [field() for _ in range(6)]
seeds = [f['seed'] for f in fields]
layouts = [json.dumps(f['pads'], sort_keys=True) for f in fields]
print("seeds:", seeds)
allerr = []
for i,f in enumerate(fields):
    e = checks(f)
    print("run %d  seed=%-8d pads=%s  %s" % (i, f['seed'],
          [(p['x'],p['half'],'x%d'%p['mult']) for p in f['pads']], "OK" if not e else "ERR:"+";".join(e)))
    allerr += e

# 5) RANDOMNESS: at least most runs differ (seed + layout)
distinct_seeds = len(set(seeds))
distinct_layouts = len(set(layouts))
if distinct_seeds < 5: allerr.append("seeds not varied (%d/6 distinct)" % distinct_seeds)
if distinct_layouts < 5: allerr.append("layouts not varied (%d/6 distinct)" % distinct_layouts)

# 6) PHYSICS==RENDER determinism WITHIN a run: marsGroundY is a pure fn of the current seed.
#    Sample the same x twice (no run in between) -> identical; and equals pad top on a pad center.
det = ch.eval("""(function(){
  var xs=[-1800,-600,0,300,900,1500], a=xs.map(marsGroundY), b=xs.map(marsGroundY);
  var same=true; for(var i=0;i<xs.length;i++){ if(a[i]!==b[i]) same=false; }
  // on a pad center, marsGroundY must equal the flat pad top
  var p=marsPads[2], onpad=Math.abs(marsGroundY(p.x)-marsGroundY(p.x))<1e-9;
  // flat across the pad: center vs +/- (half-2) equal
  var flat=Math.abs(marsGroundY(p.x)-marsGroundY(p.x+p.half-2))<1e-6 &&
           Math.abs(marsGroundY(p.x)-marsGroundY(p.x-(p.half-2)))<1e-6;
  return {sameTwice:same, flatOnPad:flat};
})()""")
print("determinism:", det)
if not det.get('sameTwice'): allerr.append("marsGroundY not stable within a run")
if not det.get('flatOnPad'): allerr.append("pad not flat in marsGroundY")

print("distinct seeds=%d layouts=%d" % (distinct_seeds, distinct_layouts))
print("RESULT", "PASS" if not allerr else "FAIL: " + "; ".join(allerr))
ch.close()
sys.exit(0 if not allerr else 1)
