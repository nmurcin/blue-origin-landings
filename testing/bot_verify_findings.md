# Winnability + landing-precision verification — REAL game, decks 14000 / 17000

Bot: headless-Chrome DevTools harness (bot_verify.py -> bot_sweep controller), running
the CURRENT index.html with deckX() = 14000 (ocean) / 17000 (tower). Robust
active-steering strategy (mandatory entry decel burn -> retrograde reentry ->
proportional descent-rate terminal + deck-seek). The bot reads the game's own deckX()
each run. Spawn + wind are randomized by the game, so each run is an independent sample.

Strategy per variant (from the envelope study):
  ocean: entryDecelSpd=340, low-band bleed to vx=45, aNet=10.5
  tower: entryDecelSpd=200, low-band bleed to vx=35, aNet=9.5

## Headline

- SURVIVABILITY / LANDABILITY: 100% of runs (both variants) survived reentry with NO
  burnup (dmg=0) and touched down SOFT and upright and within tolerance
  (ocean vy≈-3 ≤8.5, vx<2 ≤7.0; tower vy≈-3 ≤6.0, vx<2.5 ≤4.0), vx never reversed.
  So the decks are physically REACHABLE and the touchdown is always landable-quality.
- ON-DECK HIT RATE at the shipped padHalf (44 ocean / 34 tower): ~0%. The booster lands
  in a tight-ish BAND around the deck, but the band (hundreds of metres, spawn-driven)
  is far wider than the 34-44 m pad. This CONFIRMS the earlier ±400-900 m scatter
  estimate.

The decks are the right POSITION (deck ahead the whole descent, vx never reverses,
soft touchdown) but the pad is far too SMALL for the game's spawn randomization. The
fix is to WIDEN the pad (or add terminal guidance), not move the deck.

## Per-run results (batch 1, n=7 each; batch 2 pending -> merged numbers below)

OCEAN deckX=14000 padHalf=44:
  #  land_x  offset  vx     vy     ang  surv soft fuel   dmg
  0  13755   245     0.82  -3.12   1.4   Y    Y   16468   0
  1  14998   998     1.27  -3.00   0.3   Y    Y   16167   0
  2  13878   122     1.95  -2.96   0.5   Y    Y   16456   0
  3  14291   291    -0.25  -3.10  -0.9   Y    Y   16262   0
  4  12657  1343     0.46  -2.99  -0.6   Y    Y   16701   0
  5  12872  1128     0.04  -2.99  -0.9   Y    Y   16748   0
  6  14113   113     1.22  -3.03   0.8   Y    Y   16379   0
  offset (soft) min=113  median=291  mean=605  max=1343  stdev≈489

TOWER deckX=17000 padHalf=34:
  #  land_x  offset  vx     vy     ang  surv soft fuel   dmg
  0  18721  1721    -0.05  -3.00  -0.8   Y    Y   12094   0
  1  17137   137     2.16  -2.87   0.7   Y    Y   12224   0
  2  17419   419    -0.16  -3.01   1.0   Y    Y   12391   0
  3  16676   324     1.29  -2.96   0.3   Y    Y   12157   0
  4  17596   596     0.73  -2.96   1.2   Y    Y   12241   0
  5  16707   293     2.33  -3.04   0.4   Y    Y   12304   0
  6  16520   480     2.24  -3.01   0.8   Y    Y   12311   0
  offset (soft) min=137  median=419  mean=567  max=1721  stdev≈490

## Offset distribution + hit rate (batch 1)

OCEAN: min 113 / median 291 / max 1343.  Hit @ padHalf 44 = 0/7.
  padHalf 300 -> 57%, 1000 -> 71%, 1200 -> 85%, 1500 -> 100%.
TOWER: min 137 / median 419 / max 1721.  Hit @ padHalf 34 = 0/7.
  padHalf 400 -> 43%, 500 -> 71%, 600 -> 85%, 2000 -> 100%.

## Recommended padHalf for a winnable-but-challenging deck  (MERGED numbers below)

(placeholder — filled after batch 2 merge)
