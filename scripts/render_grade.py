"""
Render each traced VEHICLE_SHAPE the SAME way the game will (filled outline polygon, clipped,
with vertical colour bands + soft left-right cylinder shading) to an offscreen raster, then grade
it against the original reference by silhouette IoU — objective, no LLM vision. Also writes a
side-by-side PNG (reference | render) per vehicle for eyeball confirmation.

Usage: py local/scripts/render_grade.py
"""
import cv2, numpy as np, os, json, re

REF = r'C:\Users\nmurcin\Downloads'
NAMES = {'7 by 2': 'ng7x2', '9 by 4': 'ng9x4', 'mark 1': 'mk1', 'mark 2': 'mk2'}

def load_shapes():
    # Re-run the tracer's trace() directly so we always grade the current data.
    import trace_vehicles as tv
    return {k: tv.trace(os.path.join(REF, f + '.png'), tv.PROFILE.get(k)) for f, k in NAMES.items()}

def hexrgb(h):
    h = h.lstrip('#'); return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

def render(shape, H=1000):
    """Render to BGR on black; return (img, mask). x and y share one scale (aspect preserved).
    Fills the silhouette, then paints each colour REGION polygon on top, then soft L-R shading."""
    asp = shape['aspect']; pad = 0.06
    drawH = H * (1 - 2 * pad)
    W = int(drawH * (asp + 0.10))
    cx = W / 2; baseY = H - pad * H
    def px(poly):
        return np.array([[cx + p[0] * drawH, baseY - p[1] * drawH] for p in poly], np.int32)
    out = px(shape['outline'])
    img = np.zeros((H, W, 3), np.uint8)
    mask = np.zeros((H, W), np.uint8)
    cv2.fillPoly(mask, [out], 1)
    # base fill = lightest region colour (body), so any gaps read as body not black
    cols = [hexrgb(r['color']) for r in shape['regions']]
    base = max(cols, key=lambda c: sum(c)) if cols else (220, 224, 228)
    img[mask > 0] = (base[2], base[1], base[0])
    # paint regions in listed order (dark→light already from tracer; accents land sensibly)
    for r in shape['regions']:
        rr, gg, bb = hexrgb(r['color'])
        if 'poly' in r:
            cv2.fillPoly(img, [px(r['poly'])], (bb, gg, rr))
        if 'detail' in r:
            for d in r['detail']:
                cv2.fillPoly(img, [px(d)], (bb, gg, rr))
    img[mask == 0] = 0
    # soft cylinder shading
    xs = np.linspace(-1, 1, W)
    shade = (0.82 + 0.26 * np.cos((xs - 0.18) * 1.25)).clip(0.66, 1.12)
    img = (img * shade[None, :, None]).clip(0, 255).astype(np.uint8)
    img[mask == 0] = 0
    return img, mask

def ref_mask(path):
    import trace_vehicles as tv
    m, _ = tv.fg_mask(path)
    return m

def ref_mask_for(key, f):
    """Reference foreground mask honouring the per-vehicle profile (src override + GrabCut)."""
    import trace_vehicles as tv
    prof = tv.PROFILE.get(key, {})
    p = prof.get('src') or os.path.join(REF, f + '.png')
    if prof.get('grabcut'):
        m, rgb = tv.grabcut_mask(p, prof['grabcut'], prof.get('gc_clean', False))
    else:
        m, rgb = tv.fg_mask(p)
    return m, rgb, p

def _norm(mask, S=256):
    """Crop to the silhouette bbox and resize to SxS so two masks are compared shape-to-shape
    (position/scale-invariant) rather than being thrown off by canvas padding differences."""
    ys, xs = np.where(mask > 0)
    if len(ys) == 0:
        return np.zeros((S, S), np.uint8)
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8)
    return cv2.resize(crop, (S, S), interpolation=cv2.INTER_NEAREST)

def iou(a, b):
    a = _norm(a); b = _norm(b)
    a = a > 0; b = b > 0
    inter = np.logical_and(a, b).sum(); uni = np.logical_or(a, b).sum()
    return inter / uni if uni else 0.0

def main():
    shapes = load_shapes()
    outdir = os.path.join(os.path.dirname(__file__), '..', 'tmp')
    print('rendered-vs-reference silhouette IoU:')
    for f, k in NAMES.items():
        rimg, rmask = render(shapes[k])
        refm, refrgb, refpath = ref_mask_for(k, f)
        score = iou(rmask, refm)
        print(f"  {k}: IoU(render vs ref) = {score:.3f}")
        # side-by-side: crop the reference to its silhouette bbox so it aligns with the render
        ys, xs = np.where(refm > 0)
        refimg = cv2.imread(refpath)[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        refimg = cv2.resize(refimg, (int(rimg.shape[0] * shapes[k]['aspect']), rimg.shape[0]))
        h = rimg.shape[0]
        canvas = np.zeros((h, refimg.shape[1] + rimg.shape[1] + 20, 3), np.uint8)
        canvas[:, :refimg.shape[1]] = refimg
        canvas[:, refimg.shape[1] + 20:] = rimg
        cv2.imwrite(os.path.join(outdir, f'cmp_{k}.png'), canvas)
    print('wrote cmp_*.png side-by-sides to local/tmp/')

if __name__ == '__main__':
    main()
