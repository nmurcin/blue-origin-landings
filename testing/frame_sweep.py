"""
Frame-schedule stability sweep for BLUE ORIGIN LANDINGS — the closeout for the substep claim.

The game uses a BOUNDED VARIABLE SUBSTEP (sdt = dt/ceil(dt*120)), NOT a fixed-step accumulator.
This module tests how much a full maneuver diverges across frame rates / jittered / stalled schedules
when the CONTROL INPUTS are applied at IDENTICAL simulation times in every run (so input quantization
is removed as a confound — events are applied by SPLITTING the physics interval at the event boundary).

It drives the REAL game update(dt) in headless Chrome via a one-shot in-page loop, and also provides a
TRUE FIXED-STEP ACCUMULATOR driver (physics advanced in exact 1/120 s chunks, render-decoupled) so the
current method can be compared head-to-head against the ideal.

Determinism: wind is zeroed; turbulence is a pure function of sim time (b.t), no RNG affects physics.
So (start state, event schedule, frame schedule, stepping mode) fully determines the outcome.

Run:  py testing/frame_sweep.py                 (full sweep, both modes, prints table + writes json)
      py testing/frame_sweep.py --seconds 7
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from physics_harness import Harness  # noqa: E402

# In-page driver. Applies a timestamped control schedule at EXACT sim time by splitting each physics
# advance at event boundaries. mode='variable' -> one update() per render frame (the CURRENT method).
# mode='fixed120' -> physics advanced in exact 1/120 s chunks accumulated from the render frames (a
# true fixed-step accumulator, render-decoupled). Events split whichever advance straddles them.
DRIVER = r"""
window.__FS = (function(){
  function applyEvent(ev){
    burnHeld = !!ev.burn;
    steerVal = ev.steer || 0;
    for (var k in keys) delete keys[k];
    if (ev.steer > 0) keys['ArrowRight'] = true;
    else if (ev.steer < 0) keys['ArrowLeft'] = true;
  }
  // start a fresh ocean descent at a known post-handoff state, controls clear, no wind.
  function reset(st){
    startMode('ocean');
    b.opening = false;
    env = { windBase:0, windGust:0, windPhase:0, gateX:0 };
    b.x=st.x; b.y=st.y; b.vx=st.vx; b.vy=st.vy; b.ang=st.ang; b.angv=st.angv; b.fuel=st.fuel;
    b.thr=0; b.fin=0; b.rcsFuel=1e9; b.t=0; timeScale=1;
    for (var k in keys) delete keys[k]; burnHeld=false; steerVal=0;
  }
  function snap(){ return { x:b.x, y:b.y, vx:b.vx, vy:b.vy, ang:b.ang, angv:b.angv, fuel:b.fuel,
                            thr:b.thr, t:b.t, scene:scene }; }

  // Advance sim by exactly `want` seconds using the chosen stepping discipline, WITHOUT crossing an
  // event (caller splits at events). variable: one update(want). fixed120: whole 1/120 chunks + a
  // final partial chunk so total == want (the partial keeps event timing exact; it is a single small
  // substep, negligible vs the fixed cadence).
  function advance(want, mode){
    if (want <= 1e-12) return;
    if (mode === 'variable'){ update(want); return; }
    // fixed120 accumulator
    var H = 1/120, left = want;
    while (left > H + 1e-9){ update(H); if (scene!=='flying') return; left -= H; }
    if (left > 1e-9) update(left);
  }

  // frames: array of render-frame dt values (their sum = total sim time).
  // events: array of {t, burn, steer} sorted by t (t in sim seconds; applied at exact t).
  function run(startState, frames, events, mode){
    reset(startState);
    // apply any t<=0 events first
    var ei = 0;
    while (ei < events.length && events[ei].t <= 1e-9){ applyEvent(events[ei]); ei++; }
    var t = 0;
    for (var f = 0; f < frames.length; f++){
      var end = t + frames[f];
      var cursor = t;
      while (ei < events.length && events[ei].t < end - 1e-9){
        var et = events[ei].t;
        if (et > cursor + 1e-9){ advance(et - cursor, mode); cursor = et; }
        if (scene!=='flying') return snap();
        applyEvent(events[ei]); ei++;
      }
      if (end > cursor + 1e-9){ advance(end - cursor, mode); }
      if (scene!=='flying') return snap();
      t = end;
    }
    return snap();
  }
  return { run:run };
})();
'ready';
"""

# Known post-handoff descent start (in the buffet band so turbulence is active: y<ENTRY_Y+2500=11000).
START = {"x": -6000, "y": 9000, "vx": 250, "vy": -250, "ang": -0.30, "angv": 0.0, "fuel": 60000}

# Timestamped control schedule (sim seconds). Coast, steer-right pulse, burn, steer-left pulse, hold burn.
# NOT run to touchdown (measured at the fixed horizon) so contact-timing is not a confound.
def events():
    return [
        {"t": 0.0, "burn": False, "steer": 0},
        {"t": 2.0, "burn": False, "steer": 1},
        {"t": 2.5, "burn": False, "steer": 0},
        {"t": 3.0, "burn": True,  "steer": 0},
        {"t": 5.0, "burn": True,  "steer": -1},
        {"t": 5.4, "burn": True,  "steer": 0},
    ]


def const_frames(hz, seconds):
    dt = 1.0 / hz
    n = int(math.floor(seconds / dt))
    frames = [dt] * n
    rem = seconds - n * dt
    if rem > 1e-9:
        frames.append(rem)
    return frames


def alternating_frames(a_ms, b_ms, seconds):
    a, b = a_ms / 1000.0, b_ms / 1000.0
    frames, t = [], 0.0
    i = 0
    while t < seconds - 1e-9:
        d = a if i % 2 == 0 else b
        d = min(d, seconds - t)
        frames.append(d); t += d; i += 1
    return frames


def jittered_frames(seconds, seed=1234):
    # deterministic LCG jitter around 16.67 ms in [10, 24] ms — test code, fixed seed, repeatable.
    frames, t = [], 0.0
    state = seed
    while t < seconds - 1e-9:
        state = (1103515245 * state + 12345) & 0x7fffffff
        d = (0.010 + (state % 1000) / 1000.0 * 0.014)  # 10..24 ms
        d = min(d, seconds - t)
        frames.append(d); t += d
    return frames


def stall_frames(seconds, stall_at=3.2, stall_ms=100):
    # nominal 60 Hz with one 100 ms stall frame inserted near t=stall_at.
    dt = 1.0 / 60.0
    frames, t, inserted = [], 0.0, False
    while t < seconds - 1e-9:
        if not inserted and t >= stall_at:
            d = min(stall_ms / 1000.0, seconds - t)
            inserted = True
        else:
            d = min(dt, seconds - t)
        frames.append(d); t += d
    return frames


def run_one(h, frames, mode):
    payload = json.dumps({"start": START, "frames": frames, "events": events(), "mode": mode})
    expr = f"(function(){{ var p={payload}; return __FS.run(p.start, p.frames, p.events, p.mode); }})()"
    return h.call(expr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=7.0)
    args = ap.parse_args()
    S = args.seconds

    schedules = {
        "24Hz": const_frames(24, S),
        "30Hz": const_frames(30, S),
        "50Hz": const_frames(50, S),
        "59.94Hz": const_frames(59.94, S),
        "60Hz": const_frames(60, S),
        "75Hz": const_frames(75, S),
        "90Hz": const_frames(90, S),
        "120Hz": const_frames(120, S),
        "144Hz": const_frames(144, S),
        "alt_8_24ms": alternating_frames(8, 24, S),
        "jittered": jittered_frames(S),
        "stall_100ms": stall_frames(S),
    }

    h = Harness()
    results = {}
    try:
        h.start()
        ready = h.call(DRIVER)
        assert ready == "ready", ready
        for mode in ("variable", "fixed120"):
            results[mode] = {}
            for name, frames in schedules.items():
                st = run_one(h, frames, mode)
                st["_nframes"] = len(frames)
                st["_sum"] = round(sum(frames), 6)
                results[mode] = {**results[mode], name: st}
    finally:
        h.stop()

    # reference = 120Hz within each mode (finest constant schedule)
    def cmp(a, b):
        return {
            "dpos": round(math.hypot(a["x"] - b["x"], a["y"] - b["y"]), 3),
            "dvel": round(math.hypot(a["vx"] - b["vx"], a["vy"] - b["vy"]), 4),
            "dang_deg": round(abs(a["ang"] - b["ang"]) * 180 / math.pi, 4),
            "dangv": round(abs(a["angv"] - b["angv"]), 5),
            "dfuel": round(abs(a["fuel"] - b["fuel"]), 3),
        }

    report = {"seconds": S, "start": START, "modes": {}}
    for mode in ("variable", "fixed120"):
        ref = results[mode]["120Hz"]
        rows = {}
        for name in schedules:
            rows[name] = cmp(results[mode][name], ref)
            rows[name]["nframes"] = results[mode][name]["_nframes"]
        report["modes"][mode] = {"ref": "120Hz", "vs_ref": rows,
                                 "final_120Hz": {k: round(results[mode]["120Hz"][k], 4)
                                                 for k in ("x", "y", "vx", "vy", "ang", "angv", "fuel", "t")}}

    # cross-mode: variable vs fixed120 at 60 Hz (does the discipline itself matter?)
    report["variable_vs_fixed120_at_60Hz"] = cmp(results["variable"]["60Hz"], results["fixed120"]["60Hz"])

    print("=" * 78)
    for mode in ("variable", "fixed120"):
        print(f"MODE: {mode}   (vs 120Hz reference, control events at identical sim times)")
        print(f"  {'schedule':<12} {'dpos(m)':>9} {'dvel(m/s)':>10} {'dang(deg)':>10} {'dangv':>9} {'dfuel(kg)':>10} {'frames':>7}")
        for name in schedules:
            r = report["modes"][mode]["vs_ref"][name]
            print(f"  {name:<12} {r['dpos']:>9} {r['dvel']:>10} {r['dang_deg']:>10} {r['dangv']:>9} {r['dfuel']:>10} {r['nframes']:>7}")
        print()
    print("variable vs fixed120 @60Hz:", report["variable_vs_fixed120_at_60Hz"])
    print("=" * 78)

    outp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frame_sweep.json")
    with open(outp, "w") as f:
        json.dump({"report": report, "raw": results}, f, indent=2)
    print("wrote " + outp)


if __name__ == "__main__":
    main()
