"""Static sweep: find ALL_CAPS identifiers USED in the game script but never declared —
catches renamed/removed consts (like the GLIDE_AOA->GLIDE_LEAN crash) before runtime."""
import re

src = open('blue_origin_landings.html', encoding='utf-8').read()
m = re.search(r'<script>(.*)</script>', src, re.S)
body = m.group(1)

# strip line comments, block comments, then string literals (order matters)
code = re.sub(r'//[^\n]*', '', body)
code = re.sub(r'/\*.*?\*/', '', code, flags=re.S)
code = re.sub(r"'(?:\\.|[^'\\])*'", "''", code)
code = re.sub(r'"(?:\\.|[^"\\])*"', '""', code)
code = re.sub(r'`(?:\\.|[^`\\])*`', '``', code)

used = set(re.findall(r'[A-Z][A-Z0-9_]{2,}', code))
declared = set(re.findall(r'(?:const|let|var)\s+([A-Z][A-Z0-9_]{2,})', code))
declared |= set(re.findall(r'([A-Z][A-Z0-9_]{2,})\s*=', code))       # assignments
declared |= set(re.findall(r'([A-Z][A-Z0-9_]{2,})\s*:', code))       # object keys / enum members

builtins = {'NaN','Infinity','JSON','Math','PI','RESULT'}
missing = sorted(n for n in used if n not in declared and n not in builtins)

print("CAPS identifiers USED but never declared/assigned (candidate dangling refs):")
if not missing:
    print("  (none)")
for n in missing:
    c = len(re.findall(r'\b' + re.escape(n) + r'\b', code))
    print(f"  {n:26s} x{c}")

print("\nRemoved constant still referenced anywhere?")
for gone in ('GLIDE_AOA',):
    print(f"  {gone}: {'PRESENT (BAD)' if re.search(r'\b'+gone+r'\b', code) else 'absent (good)'}")
