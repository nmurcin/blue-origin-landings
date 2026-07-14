"""
Sync guard for BLUE ORIGIN LANDINGS: blue_origin_landings.html (the canonical named build) and
index.html (the GitHub-Pages entry point) are intended to be byte-identical duplicates. This asserts
that. Run in CI / pre-commit and before any merge.

Exit 0 if identical, 1 if they differ (prints the first differing lines + both SHA-256s).

Run:  py testing/check_sync.py
"""
import hashlib
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A = os.path.join(REPO, "blue_origin_landings.html")
B = os.path.join(REPO, "index.html")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def main():
    with open(A, "rb") as f:
        da = f.read()
    with open(B, "rb") as f:
        db = f.read()
    ha, hb = sha(A), sha(B)
    if da == db:
        print(f"SYNC OK: blue_origin_landings.html == index.html  (sha256 {ha[:16]}...)")
        sys.exit(0)
    print("SYNC FAIL: blue_origin_landings.html and index.html DIFFER")
    print(f"  blue_origin_landings.html sha256 {ha}")
    print(f"  index.html                sha256 {hb}")
    # show first differing line
    la = da.decode("utf-8", "replace").splitlines()
    lb = db.decode("utf-8", "replace").splitlines()
    for i in range(max(len(la), len(lb))):
        xa = la[i] if i < len(la) else "<EOF>"
        xb = lb[i] if i < len(lb) else "<EOF>"
        if xa != xb:
            print(f"  first diff at line {i+1}:")
            print(f"    named: {xa[:120]}")
            print(f"    index: {xb[:120]}")
            break
    print("  Fix: cp blue_origin_landings.html index.html  (then re-run)")
    sys.exit(1)


if __name__ == "__main__":
    main()
