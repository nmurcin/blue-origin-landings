"""
Deterministic static structural checks for BLUE ORIGIN LANDINGS (no Chrome).
Catches mechanical faults the runtime scan can't see on unflown paths:
  - ctx.save()/ctx.restore() imbalance (leaks canvas state across frames)
  - duplicate function definitions (a later def silently shadows an earlier one)
  - brace/paren/bracket balance across the whole script
  - beginPath/closePath (informational only)
Run: py testing/static_checks.py
"""
import re
from collections import Counter

src = open("index.html", encoding="utf-8").read()
m = re.search(r"<script>(.*)</script>", src, re.S)
body = m.group(1)

# strip comments then string literals (order matters) so counts ignore text
code = re.sub(r"//[^\n]*", "", body)
code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
code = re.sub(r"'(?:\\.|[^'\\])*'", "''", code)
code = re.sub(r'"(?:\\.|[^"\\])*"', '""', code)
code = re.sub(r"`(?:\\.|[^`\\])*`", "``", code)

print("=== global ctx.save/.restore balance (per-frame state leak check) ===")
saves = len(re.findall(r"\.save\(\)", code))
restores = len(re.findall(r"\.restore\(\)", code))
print("  .save() = %d   .restore() = %d   delta = %d  %s"
      % (saves, restores, saves - restores, "(OK)" if saves == restores else "<-- IMBALANCE"))

print("=== duplicate function definitions (later shadows earlier) ===")
defs = re.findall(r"\bfunction\s+([a-zA-Z_$][\w$]*)\s*\(", code)
dups = {k: v for k, v in Counter(defs).items() if v > 1}
print("  ", dups if dups else "(none)")

print("=== brace / paren / bracket balance (whole script) ===")
for pair in ("{}", "()", "[]"):
    o, c = code.count(pair[0]), code.count(pair[1])
    print("  %s: %d vs %d  delta %d  %s" % (pair, o, c, o - c, "(OK)" if o == c else "<-- IMBALANCE"))

print("=== beginPath / closePath (informational) ===")
print("  beginPath = %d   closePath = %d"
      % (len(re.findall(r"\.beginPath\(\)", code)), len(re.findall(r"\.closePath\(\)", code))))
