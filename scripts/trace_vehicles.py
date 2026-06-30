"""
Region-trace the Blue Origin reference PNGs into clean vector art for the game, OBJECTIVELY
graded by silhouette IoU (OpenCV + numpy, no LLM vision).

Per image:
  1. Foreground mask (corner-sampled background; flood-fill encloses light line-art; largest CC;
     interior holes filled) → the solid silhouette.
  2. K-means quantize the foreground colours to a small flat palette (KCOLORS).
  3. For each palette colour, take its mask ∩ silhouette, keep regions above an area threshold,
     and approxPolyDP each into a simplified outline polygon. These are the colour REGIONS — so
     vertical features (gold side-tanks, bands) land in their true 2D place, not as stripes.
  4. Normalize all polygons: origin = base centre, y in [0..1] of height (0 base, 1 top), x in
     the same unit (aspect preserved). Emit `const VEHICLE_SHAPE = {...}` with
     { aspect, outline:[...], regions:[{color,poly}, ...] }.

Usage:  py local/scripts/trace_vehicles.py
"""
import cv2, numpy as np, os, json

REF = r'C:\Users\nmurcin\Downloads'
NAMES = {'7 by 2': 'ng7x2', '9 by 4': 'ng9x4', 'mark 1': 'mk1', 'mark 2': 'mk2'}
TARGET_IOU = 0.985
KCOLORS = 5            # flat palette size
MIN_REGION_FRAC = 0.004  # ignore colour blobs smaller than this fraction of the silhouette area

NG_GOLD = '#ba8224'    # the exact gold used on NG 7×2 / 9×4 (reused on MK1's tanks)

# Per-vehicle overrides. `fine` = finer approxPolyDP steps + higher IoU target → smoother outlines.
# `remap` = {sourceHex: targetHex} recolour after k-means (e.g. MK1 tank tan-gold → NG gold).
# `src` = override the source image path. `grabcut` = (x,y,w,h) fractional bbox → use GrabCut
# foreground segmentation instead of corner-background (for subjects on a textured ground).
MK2_SRC = r'C:\Users\nmurcin\Downloads\BlueMoon_pagehero-removebg-preview (1).png'
PROFILE = {
    'ng7x2': {'fine': True},
    'ng9x4': {'fine': True},
    # MK2: white-dominant. The legs splay over moon ground, so GrabCut tends to bleed gray
    # background INTO the leg triangles — `gc_clean` runs extra iterations + trims mid-gray
    # ground-coloured pixels so only the vehicle remains. kcolors=4 → clean body tones.
    # remap maps the raw k=4 palette (#3a332c/#5c5652/#878380/#dfdcda) → white-dominant + struts.
    'mk2':   {'fine': True, 'src': MK2_SRC, 'grabcut': (0.32, 0.12, 0.34, 0.78), 'kcolors': 4,
              'gc_clean': True, 'gold_base': NG_GOLD,
              # white-dominant: lightest two tones → white; mids → light gray; darkest → strut.
              'remap': {'#e4e0dc': '#f2f5f8', '#817a75': '#eef1f4', '#595450': '#b6bcc2',
                        '#322b26': '#444a53'}},
    'mk1':   {'fine': False, 'remap': {'#968270': NG_GOLD, '#494849': NG_GOLD}},
}
FINE_STEPS = [0.0015, 0.0025, 0.004, 0.006, 0.009, 0.013]   # smaller eps → more points, smoother
COARSE_STEPS = [0.004, 0.007, 0.011, 0.016, 0.024, 0.035]

def _fill_from_border(mask):
    h, w = mask.shape
    ff = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    flood = ff.copy(); m2 = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(flood, m2, (0, 0), 1)
    return ((flood == 0).astype(np.uint8) | ff).astype(np.uint8)

def grabcut_mask(path, bbox_frac, clean=False):
    """Foreground segmentation via GrabCut for subjects on a textured ground (no flat background).
    bbox_frac = (x,y,w,h) as fractions of the image. Returns (mask, rgb).
    clean=True: extra iterations + trim mid-gray ground-coloured pixels that bleed into the splayed
    legs, so only the white vehicle / dark struts remain."""
    im = cv2.imread(path)
    h, w = im.shape[:2]
    fx, fy, fw, fh = bbox_frac
    rect = (int(w * fx), int(h * fy), int(w * fw), int(h * fh))
    mask = np.zeros((h, w), np.uint8)
    bgd = np.zeros((1, 65), np.float64); fgd = np.zeros((1, 65), np.float64)
    cv2.grabCut(im, mask, rect, bgd, fgd, 10 if clean else 6, cv2.GC_INIT_WITH_RECT)
    fg = ((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)).astype(np.uint8)
    if clean:
        # Moon ground is mid-gray with low saturation; the vehicle is bright white OR dark strut.
        # In the lower half (leg zone), drop GrabCut pixels whose colour matches mid-gray ground so
        # the background stops bleeding into the leg triangles.
        gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        groundish = ((gray > 95) & (gray < 180)).astype(np.uint8)   # mid-gray = likely ground
        lower = np.zeros_like(fg); lower[int(h * 0.58):, :] = 1       # only police the leg zone
        fg[(groundish & lower) > 0] = 0
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))   # despeckle ground bits
    n, lab, stats, _ = cv2.connectedComponentsWithStats(fg, 8)
    if n > 1:
        fg = (lab == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
    if clean:
        # reconnect the thin, near-vertical leg struts the trim may have broken, without
        # re-bridging the wide gaps BETWEEN legs: a tall thin vertical kernel only.
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((11, 3), np.uint8))
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    return fg, im[:, :, ::-1]

def fg_mask(path):
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im.ndim == 2: im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
    bgr = im[:, :, :3].astype(int)
    al = im[:, :, 3] if im.shape[2] == 4 else np.full(im.shape[:2], 255)
    rgb = bgr[:, :, ::-1]
    cs = 8
    corners = np.concatenate([rgb[:cs, :cs].reshape(-1, 3), rgb[:cs, -cs:].reshape(-1, 3),
                              rgb[-cs:, :cs].reshape(-1, 3), rgb[-cs:, -cs:].reshape(-1, 3)])
    bg = np.median(corners, 0); light_bg = bg.mean() > 150
    m = ((np.sqrt(((rgb - bg) ** 2).sum(2)) > 40) & (al > 40)).astype(np.uint8)
    if light_bg: m = _fill_from_border(m)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    if n > 1:
        m = (lab == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    return _fill_from_border(m), rgb

def iou(a, b):
    a = a > 0; b = b > 0
    return np.logical_and(a, b).sum() / max(1, np.logical_or(a, b).sum())

def simplify(cnt, peri, mask, target=0.97, fine=False):
    steps = FINE_STEPS if fine else COARSE_STEPS
    best = None
    for f in steps:
        ap = cv2.approxPolyDP(cnt, f * peri, True)
        rm = np.zeros_like(mask); cv2.fillPoly(rm, [ap], 1)
        sc = iou(mask > 0, rm > 0)
        if sc >= target and (best is None or len(ap) < best[1]):
            best = (ap, len(ap), sc)
    if best is None:
        ap = cv2.approxPolyDP(cnt, steps[0] * peri, True)
        rm = np.zeros_like(mask); cv2.fillPoly(rm, [ap], 1)
        best = (ap, len(ap), iou(mask > 0, rm > 0))
    return best[0], best[2]

def norm_poly(approx, x0, y0, h, cx):
    return [[round((px - cx) / h, 4), round((y0 + h - py) / h, 4)] for px, py in approx.reshape(-1, 2).astype(float)]

def trace(path, prof=None):
    prof = prof or {}
    fine = prof.get('fine', False)
    remap = prof.get('remap', {})
    target = 0.995 if fine else TARGET_IOU           # finer mode chases a tighter outline too
    if prof.get('src'):
        path = prof['src']
    if prof.get('grabcut'):
        m, rgb = grabcut_mask(path, prof['grabcut'], prof.get('gc_clean', False))
        # light close to tidy edges WITHOUT bridging the gaps between splayed legs (small kernel)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    else:
        m, rgb = fg_mask(path)
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    c = max(cnts, key=cv2.contourArea)
    x0, y0, w, h = cv2.boundingRect(c); cx = x0 + w / 2.0
    peri = cv2.arcLength(c, True)
    outline_ap, out_iou = simplify(c, peri, m, target, fine)
    outline = norm_poly(outline_ap, x0, y0, h, cx)
    # k-means palette over the foreground pixels
    fgpx = rgb[m > 0].astype(np.float32)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    K = min(prof.get('kcolors', KCOLORS), len(np.unique(fgpx.astype(int), axis=0)))
    _, lab, centers = cv2.kmeans(fgpx, K, None, crit, 5, cv2.KMEANS_PP_CENTERS)
    centers = centers.astype(int)
    # full-image label map (only meaningful inside the silhouette)
    flat = rgb.reshape(-1, 3).astype(np.float32)
    d = np.linalg.norm(flat[:, None, :] - centers[None, :, :].astype(np.float32), axis=2)
    lblmap = d.argmin(1).reshape(rgb.shape[:2])
    area = (m > 0).sum(); regions = []
    # order palette dark→light so big light body paints first, accents on top
    order = sorted(range(K), key=lambda i: centers[i].mean())
    for ci in order:
        cmask = ((lblmap == ci) & (m > 0)).astype(np.uint8)
        cmask = cv2.morphologyEx(cmask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        cmask = cv2.morphologyEx(cmask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        rc, _ = cv2.findContours(cmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        col = '#%02x%02x%02x' % tuple(int(v) for v in centers[ci])
        col = remap.get(col, col)                    # optional recolour (e.g. MK1 tank → NG gold)
        for rcc in rc:
            if cv2.contourArea(rcc) < area * MIN_REGION_FRAC: continue
            ap, _sc = simplify(rcc, cv2.arcLength(rcc, True), _one(cmask, rcc), 0.96 if fine else 0.93, fine)
            regions.append({'color': col, 'poly': norm_poly(ap, x0, y0, h, cx)})
    # DARK-DETAIL pass: thin dark linework (e.g. MK2's X-brace truss, window frames) gets washed
    # out by whole-image k-means on a light vehicle. Capture it separately as dark line segments so
    # the structure reads. Only emit when the vehicle is predominantly LIGHT (mean luma high).
    if fgpx.mean() > 150:
        lum = rgb.dot([0.299, 0.587, 0.114])
        dark = ((lum < 110) & (m > 0)).astype(np.uint8)
        dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        dc, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        details = []
        for d in dc:
            if cv2.contourArea(d) < area * 0.0008: continue       # keep even thin strokes
            ap = cv2.approxPolyDP(d, 0.02 * cv2.arcLength(d, True), True)
            details.append(norm_poly(ap, x0, y0, h, cx))
        if details:
            regions.append({'color': '#3a3f47', 'detail': details})
    # GOLD_BASE: tint the lowest band of the silhouette gold (the footpads / aft skirt), since the
    # dim reference washes the gold out. Take the silhouette ∩ bottom 9% of height as a region.
    if prof.get('gold_base'):
        band = np.zeros_like(m)
        band[int(y0 + h * 0.91):y0 + h, :] = 1
        gmask = ((band > 0) & (m > 0)).astype(np.uint8)
        gc, _ = cv2.findContours(gmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for g in gc:
            if cv2.contourArea(g) < area * 0.002: continue
            ap = cv2.approxPolyDP(g, 0.01 * cv2.arcLength(g, True), True)
            regions.append({'color': prof['gold_base'], 'poly': norm_poly(ap, x0, y0, h, cx)})
    return dict(aspect=round(w / h, 4), iou=round(float(out_iou), 4),
                outline=outline, regions=regions, nreg=len(regions))

def _one(mask, cnt):
    z = np.zeros_like(mask); cv2.drawContours(z, [cnt], -1, 1, -1); return z

def main():
    out = {}
    for f, k in NAMES.items():
        out[k] = trace(os.path.join(REF, f + '.png'), PROFILE.get(k))
        print(f"{k}: silhouette IoU={out[k]['iou']}  regions={out[k]['nreg']}  aspect={out[k]['aspect']}")
    js = ("// Vehicle art auto-traced from the reference PNGs (OpenCV: silhouette outline + flat\n"
          "// colour REGIONS via k-means, each region's outline simplified). IoU-graded vs originals.\n"
          "// Origin = base centre; [x,y] with y in [0..1] of height (0 base, 1 top), x same unit.\n"
          "// Generated by local/scripts/trace_vehicles.py.\n"
          "const VEHICLE_SHAPE = {\n")
    for k, v in out.items():
        js += "  %s: { aspect: %s, outline: %s, regions: %s },\n" % (
            k, v['aspect'], json.dumps(v['outline']), json.dumps(v['regions']))
    js += "};\n"
    dst = os.path.join(os.path.dirname(__file__), '..', 'tmp', 'vehicle_shapes.js')
    open(dst, 'w', encoding='utf-8').write(js)
    print('wrote', os.path.normpath(dst), '(', os.path.getsize(dst), 'bytes )')

if __name__ == '__main__':
    main()
