"""Localize the ctx.save/.restore imbalance to specific functions."""
import re

src = open("index.html", encoding="utf-8").read()
m = re.search(r"<script>(.*)</script>", src, re.S)
body = m.group(1)
start_line = src[:m.start(1)].count("\n") + 1

# split into top-level functions by scanning brace depth
lines = body.split("\n")
# Find function headers at column 0-ish
func_re = re.compile(r"^\s*function\s+([a-zA-Z_$][\w$]*)\s*\(")

# Build a simple map: for each line, which top-level function is it in.
# Track brace depth ignoring strings/comments crudely per line.
def strip_line(s):
    s = re.sub(r"//.*$", "", s)
    s = re.sub(r"'(?:\\.|[^'\\])*'", "''", s)
    s = re.sub(r'"(?:\\.|[^"\\])*"', '""', s)
    s = re.sub(r"`(?:\\.|[^`\\])*`", "``", s)
    return s

results = []
i = 0
n = len(lines)
while i < n:
    hm = func_re.match(lines[i])
    if hm:
        name = hm.group(1)
        depth = 0
        started = False
        saves = restores = 0
        j = i
        while j < n:
            sl = strip_line(lines[j])
            saves += len(re.findall(r"\.save\(\)", sl))
            restores += len(re.findall(r"\.restore\(\)", sl))
            for ch in sl:
                if ch == "{":
                    depth += 1
                    started = True
                elif ch == "}":
                    depth -= 1
            if started and depth <= 0:
                break
            j += 1
        if saves != restores:
            results.append((name, start_line + i, saves, restores, saves - restores))
        i = j + 1
    else:
        i += 1

print("Functions with save != restore:")
if not results:
    print("  (none — imbalance is only across nested/non-top-level scopes)")
for name, ln, s, r, d in results:
    print("  %-28s line %d   save=%d restore=%d  delta=%d" % (name, ln, s, r, d))

# global tally for sanity
allsl = strip_line("\n".join(lines))
print("\nGlobal: save=%d restore=%d delta=%d"
      % (len(re.findall(r"\.save\(\)", allsl)), len(re.findall(r"\.restore\(\)", allsl)),
         len(re.findall(r"\.save\(\)", allsl)) - len(re.findall(r"\.restore\(\)", allsl))))
