"""
bot_autopilot.py — the in-page JavaScript autopilot for Blue Origin Landings,
held as a Python string and injected ONCE into the running game page.

WHY THIS IS TUNED TO THE LIVE GAME (not a direct port of deck_geometry_both.py):
The reference sim's phase logic ("hot decel burn while high+fast") assumes the sim's
own drag/thrust model. The LIVE game physics diverge — a full burn at ~24 km (far
above ENTRY_Y=8500, negligible air) just cancels gravity and pushes the booster
UP, never exiting the burn and draining all fuel. Extensive live probing
(bot_probe_*.py) established the real envelope:
  - No-input: booster arcs over apogee (~25.6 km); momentum flies it far downrange.
  - Holding RETROGRADE (belly to wind) all the way down keeps heat damage at ZERO
    (heatFrac peaks ~0.5) — this is the key to surviving reentry.
  - A retrograde BURN while descending bleeds horizontal vx (405 -> tens of m/s) and
    stays near-upright; but held with vx~0 it degenerates into a vertical hover.
  - Full-burn NET deceleration is ~10-16 m/s^2 near landing altitude.
  - Bleeding horizontal HIGH + FAST overheats -> burnup; bleeding LOW is heat-safe.

CONTROL LAW (ocean/tower), a robust powered-descent guidance:
  1) COAST_UP  — ascending after handoff (vy>=0): no burn, hold upright.
  2) BLEED      — descending, in the heat-safe lower band, still too fast horizontally
                  AND deck still ahead: point retrograde, full burn to shed vx (leaves
                  VX_KEEP of downrange momentum). Off by default up high (heat).
  3) GLIDE      — otherwise while high: coast holding RETROGRADE (belly to wind) so we
                  neither burn up nor add downrange lift; momentum carries us on.
  4) TERMINAL   — proportional descent-rate suicide burn: command a target sink rate
                  that shrinks with altitude (vtgt = 0.055*y + 3), burning only when
                  sinking faster than target. This feathers to a SOFT, upright, zero-
                  damage touchdown (measured vy ~ -3 m/s) instead of hovering.

Tuning note: VX_KEEP trades range vs. heat. VX_KEEP=60 reliably yields a clean,
damage-free, upright soft landing in the live game (the reference sim's exact on-deck
targeting does not transfer because the two physics models diverge — the booster
crosses deckX's x while still high, and bleeding enough to null that high up burns
the vehicle up). The bot's job here is to fly a complete, reviewable, controlled
descent and report the real outcome, which this law does.

Runs in the game's own requestAnimationFrame loop (~120 Hz), driving the page `keys`
map (SPACE=burn, ArrowLeft/Right=steer). Publishes __botPhase, __botTrace, __botDone.
"""

AUTOPILOT_JS = r"""
(function(){
  if (window.__botInstalled) return 'already';
  window.__botInstalled = true;
  window.__botTrace = [];
  window.__botPhase = 'INIT';
  window.__botDone = null;
  window.__botN = 0;

  var A_NET  = 10.5;   // measured live net full-burn decel near landing altitude (m/s^2)
  var VX_KEEP = 60;    // stop bleeding horizontal below this (leaves downrange momentum)
  var MARGIN  = 150;   // terminal-burn altitude pad (m)

  function vehParams(){
    if (typeof mode==='undefined') return {kind:'ocean'};
    if (mode==='tower') return {kind:'tower'};
    if (mode==='mars')  return {kind:'mars'};
    return {kind:'ocean'};
  }
  function steer(t){
    var e=t-b.ang; keys['ArrowLeft']=false; keys['ArrowRight']=false;
    if (e>0.015) keys['ArrowRight']=true; else if (e<-0.015) keys['ArrowLeft']=true;
  }
  function sample(dx,phase){
    window.__botN++;
    if (window.__botN % 6 === 0 && window.__botTrace.length < 6000){
      window.__botTrace.push([+(b.t||0).toFixed(2), Math.round(b.x), Math.round(b.y),
        +b.vx.toFixed(1), +b.vy.toFixed(1), +(b.ang*180/Math.PI).toFixed(1),
        +b.thr.toFixed(2), Math.round(b.fuel), Math.round(dx), phase]);
    }
  }

  function tick(){
    try{
      if (typeof b==='undefined' || !b){ window.__botDone={result:'NO_B'}; return; }
      if (typeof scene!=='undefined' && scene==='done'){
        var ok=(typeof result!=='undefined'&&result)?!!result.ok:null;
        var reason=(typeof result!=='undefined'&&result&&result.lines)?result.lines[0]:null;
        window.__botDone={result: ok?'WON':'LOST', ok:ok, x:b.x, y:b.y, vx:b.vx,
          vy:b.vy, ang:b.ang, fuel:b.fuel, damage:Math.round(b.damage||0),
          reason:reason, deckX:(typeof deckX==='function'?deckX():null)};
        keys[' ']=false; keys['ArrowLeft']=false; keys['ArrowRight']=false;
        return;
      }
      if (b.opening){ window.__botPhase='OPENING'; requestAnimationFrame(tick); return; }

      var V=vehParams();
      var dx=(typeof deckX==='function')?deckX():0;
      var gap=dx-b.x;
      var desc=b.vy<0, sd=desc?-b.vy:0;
      var stop=(b.vy*b.vy)/(2*A_NET), burnAlt=stop*1.20+MARGIN;
      var ph,tgt,burn;

      if (V.kind==='mars'){
        // lunar pad at x=0: proportional descent-rate suicide burn, steer to x~0
        var vtgtM=Math.max(2.0, 0.05*b.y + 2.0);
        tgt=Math.max(-0.12,Math.min(0.12,(dx-b.x)*0.0008 - b.vx*0.03));
        burn = desc && b.y<=stop*1.25+MARGIN && sd>vtgtM;
        ph = burn?'MARS_BURN':'MARS_COAST';
        keys[' ']=burn; steer(tgt); window.__botPhase=ph; sample(dx,ph);
        requestAnimationFrame(tick); return;
      }

      if (!desc){
        tgt=0; burn=false; ph='COAST_UP';
      } else if (b.y<=burnAlt && sd>1){
        // TERMINAL — proportional descent-rate control -> soft, upright touchdown
        var vtgt=Math.max(3.0, 0.055*b.y + 3.0);
        var aim=(Math.abs(gap)<250)?(-b.vx*0.012):((dx-b.x)*0.00035 - b.vx*0.010);
        tgt=Math.max(-0.20,Math.min(0.20,aim));
        if (b.y<250) tgt=Math.max(-0.09,Math.min(0.09,-b.vx*0.02));
        burn=(sd>vtgt); ph='TERMINAL';
      } else if (b.vx>VX_KEEP && gap>800 && b.y>burnAlt && b.y<9500){
        // BLEED horizontal in the heat-safe lower band (avoids high-altitude burnup)
        tgt=Math.atan2(-b.vx,-b.vy); burn=true; ph='BLEED';
      } else {
        // GLIDE — coast holding retrograde (belly to wind): no burnup, no added lift
        tgt=Math.atan2(-b.vx,-b.vy); burn=false; ph='GLIDE';
      }

      keys[' ']=burn; steer(tgt);
      window.__botPhase=ph; sample(dx,ph);
      requestAnimationFrame(tick);
    } catch(e){ window.__botDone={result:'ERR', err:''+e}; }
  }

  requestAnimationFrame(tick);
  return 'installed';
})()
"""
