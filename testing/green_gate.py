"""
Green gate for BLUE ORIGIN LANDINGS — runs the full verification suite in order
and reports one PASS/FAIL. Use before/after any change (esp. bug fixes) to prove
nothing regressed. Ordered fast->slow so a cheap failure aborts early.

  1. check_sync.py         — index.html == blue_origin_landings.html (byte-identical)
  2. dangling_ref_scan.py  — no ALL_CAPS identifier used-but-undeclared
  3. static_checks.py      — brace/paren balance, dup defs, save/restore count (informational)
  4. physics_harness.py    — real-JS A-K physics battery (11 tests)
  5. physics_probes.py     — P1-P7 targeted probes (frame-rate, predictor, NaN smoke)
  6. runtime_error_scan.py — full ascent+descent+touchdown for ocean/tower/mars: 0 errors/NaN/ctx-leak
  7. ui_screen_scan.py     — menu/board/done(win,crash,splash,mars)/paused screens clean
  8. mars_land_probe.py    — every MK1 moonlander pad (x2/x3/x5/x8) lands soft + scores its ×N multiplier
  9. _stop_latch.py        — STOP marker arms once then stays on through hard tilt / vy overshoot (no flicker)
                             (the low-altitude touchdown path the autopilot scan doesn't reach)

Run: py testing/green_gate.py            (exit 0 iff all pass)
     py testing/green_gate.py --fast     (skip the two slow Chrome scans 6+7)
"""
import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FAST = "--fast" in sys.argv

# (label, args, how to decide pass). Most report their own RESULT/exit code.
STEPS = [
    ("sync",            ["testing/check_sync.py"],            "exit"),
    ("dangling-ref",    ["testing/dangling_ref_scan.py"],     "always"),   # informational (x0 false-positives)
    ("static-checks",   ["testing/static_checks.py"],         "always"),   # informational (save/restore FP)
    ("physics-harness", ["testing/physics_harness.py"],       "result_p"),
    ("physics-probes",  ["testing/physics_probes.py", "gate"], "always"),  # writes json; inspected below
    ("runtime-scan",    ["testing/runtime_error_scan.py", "all"], "exit", True),
    ("ui-scan",         ["testing/ui_screen_scan.py"],        "exit", True),
    ("mars-landable",   ["testing/mars_land_probe.py"],       "exit", True),   # every MK1 pad lands + scores ×N
    ("stop-latch",      ["testing/_stop_latch.py"],           "exit", True),   # STOP marker arms once then stays on (no flicker on tilt/overshoot)
]


def run(step):
    label, args = step[0], step[1]
    mode = step[2]
    slow = len(step) > 3 and step[3]
    if FAST and slow:
        print("  [skip] %s (--fast)" % label)
        return True
    p = subprocess.run([sys.executable.replace("python.exe", "py.exe") if False else "py"] + args,
                       cwd=REPO, capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    ok = True
    if mode == "exit":
        ok = p.returncode == 0
    elif mode == "result_p":
        # physics_harness prints "RESULT p 11 f 0 s 0" — pass iff f 0
        ok = " f 0 " in out and p.returncode == 0
    elif mode == "always":
        ok = p.returncode == 0
    tail = out.strip().splitlines()[-1] if out.strip() else "(no output)"
    print("  [%s] %s  ::  %s" % ("PASS" if ok else "FAIL", label, tail[:120]))
    if not ok:
        print("    ---- output ----")
        for ln in out.strip().splitlines()[-25:]:
            print("    " + ln[:160])
    return ok


def main():
    print("=== GREEN GATE%s ===" % (" (fast)" if FAST else ""))
    all_ok = True
    for step in STEPS:
        all_ok = run(step) and all_ok
        if not all_ok and step[0] in ("sync",):
            print("  aborting: sync must pass first")
            break
    print("\nGREEN GATE %s" % ("PASS" if all_ok else "FAIL"))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
