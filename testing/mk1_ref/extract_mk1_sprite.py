"""
Extract the Blue Moon MK1 vehicle from the clean reference render into a transparent-background sprite,
then base64-encode it for embedding in the offline single-file game.

Method (white-key, border-connected):
  1. Load render_clean.png. The background is pure white (255,255,255); the silver body is ~#c5c1bf.
  2. Flood-fill "near-white" from all four image borders (4-connected). Border-connected white =
     background AND the genuine see-through gaps between the splayed legs / around the side tanks.
     Enclosed light pixels (e.g. a light panel fully surrounded by darker body) are NOT reached -> stay
     part of the vehicle. This is the crux: it makes leg-gaps transparent but keeps interior detail.
  3. alpha = 0 on background, 255 on vehicle; 1px feather for a soft edge.
  4. DE-FRINGE: anti-aliased edge pixels are white-ish; over the dark moon sky they'd glow. Bleed the
     nearest opaque vehicle color outward into the semi-transparent rim so the edge color is the body,
     not white. Verified by compositing over a dark swatch (composite_over_dark.png).
  5. Auto-crop to the alpha bbox; downscale to <=256 px tall; emit mk1_sprite.png (RGBA) + b64 text.

Usage:  py testing/mk1_ref/extract_mk1_sprite.py [--tol 26] [--cap 256]
"""
import cv2, numpy as np, os, sys, base64

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'render_clean.png')

def arg(flag, default, cast):
    return cast(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default

TOL = arg('--tol', 26, int)     # how close to white counts as background (0..441)
CAP = arg('--cap', 256, int)    # max output height in px

def main():
    bgr = cv2.imread(SRC)
    if bgr is None:
        print("FAILED to read", SRC); sys.exit(2)
    h, w = bgr.shape[:2]
    rgb = bgr[:, :, ::-1].astype(np.int32)

    # near-white mask
    white_dist = np.sqrt(((rgb - np.array([255, 255, 255])) ** 2).sum(2))
    nearwhite = (white_dist < TOL).astype(np.uint8)

    # Flood fill from the borders THROUGH near-white pixels only -> border-connected background.
    # Seed a 1px white frame around the image so every border pixel is a start point, then floodFill.
    ff = nearwhite.copy()
    # ensure a connected border of "near-white" to seed from even if the render touches an edge
    ff[0, :] = 1; ff[-1, :] = 1; ff[:, 0] = 1; ff[:, -1] = 1
    flood = ff.copy()
    m2 = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(flood, m2, (0, 0), 2)              # fill reachable near-white with sentinel 2
    background = (flood == 2).astype(np.uint8)        # border-connected near-white = background
    vehicle = 1 - background                          # everything else = vehicle (keeps enclosed lights)

    # largest CC of the vehicle (drop any stray specks the key left behind)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(vehicle, 8)
    if n > 1:
        vehicle = (lab == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
    # close 1px pinholes inside the body without bridging the wide leg gaps
    vehicle = cv2.morphologyEx(vehicle, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

    # soft alpha: feather the boundary ~1px
    alpha = (vehicle * 255).astype(np.uint8)
    alpha = cv2.GaussianBlur(alpha, (0, 0), 0.8)
    alpha[vehicle == 0] = np.minimum(alpha[vehicle == 0], 60)   # keep outside mostly transparent

    # DE-FRINGE: replace edge color with nearest fully-opaque vehicle color so the rim isn't white.
    core = (alpha > 200).astype(np.uint8)
    # nearest opaque pixel index via distance transform on the INVERSE of the core
    dist, lbl = cv2.distanceTransformWithLabels(1 - core, cv2.DIST_L2, 3,
                                                labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.where(core > 0)
    # map each label -> a core coordinate. cv2 labels number the zero-pixels' nearest; build LUT.
    # Simpler robust route: inpaint-like bleed — iteratively dilate core colors into the rim.
    out = bgr.copy()
    coremask = core.copy()
    for _ in range(6):                                # a few passes cover the ~1-3px AA rim
        dil = cv2.dilate(coremask, np.ones((3, 3), np.uint8))
        newpx = (dil > 0) & (coremask == 0)
        # for new pixels, take the blurred color of current core neighborhood
        blurred = cv2.blur(out, (3, 3))
        out[newpx] = blurred[newpx]
        coremask = dil
    rgba = np.dstack([out[:, :, ::-1], alpha])        # RGB + A

    # auto-crop to alpha bbox
    ys, xs = np.where(alpha > 40)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    crop = rgba[y0:y1, x0:x1]
    ch, cw = crop.shape[:2]
    aspect = round(cw / ch, 4)

    # downscale to CAP height
    if ch > CAP:
        nw = int(round(cw * CAP / ch))
        crop = cv2.resize(crop, (nw, CAP), interpolation=cv2.INTER_AREA)
        ch, cw = crop.shape[:2]

    out_png = os.path.join(HERE, 'mk1_sprite.png')
    # cv2 writes BGRA
    cv2.imwrite(out_png, np.dstack([crop[:, :, 2::-1], crop[:, :, 3]]) if False else
                cv2.cvtColor(crop, cv2.COLOR_RGBA2BGRA))
    size = os.path.getsize(out_png)

    # composite over dark swatch for halo QA
    darkbg = np.full((ch, cw, 3), (14, 16, 22), np.uint8)   # BGR dark space
    a = crop[:, :, 3:4].astype(float) / 255.0
    comp = (crop[:, :, 2::-1].astype(float) * a + darkbg.astype(float) * (1 - a)).astype(np.uint8)
    cv2.imwrite(os.path.join(HERE, 'composite_over_dark.png'), comp)

    b64 = base64.b64encode(open(out_png, 'rb').read()).decode('ascii')
    open(os.path.join(HERE, 'mk1_sprite_b64.txt'), 'w').write(b64)

    print("tol=%d cap=%d" % (TOL, CAP))
    print("cropped sprite: %dx%d  aspect(w/h)=%.4f" % (cw, ch, aspect))
    print("mk1_sprite.png: %d bytes ; base64: %d chars (~%d KB embedded)" % (size, len(b64), len(b64)//1024))
    print("wrote mk1_sprite.png, composite_over_dark.png, mk1_sprite_b64.txt")

main()
